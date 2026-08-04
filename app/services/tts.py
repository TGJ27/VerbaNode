from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.services.text import clean_assistant_text
from app.services.audio import AudioUnavailable, HostAudioPlayer
from app.services.kokoro_voices import voice_name

LOGGER = logging.getLogger(__name__)


class TtsUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class GeneratedSpeech:
    path: Path
    provider: str
    text: str
    cached: bool = False
    persistent: bool = False


class EdgeTtsProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, text: str, voice: str, rate: float) -> Path:
        try:
            import edge_tts
        except ImportError as exc:
            raise TtsUnavailable("edge-tts is not installed") from exc
        path = self.settings.runtime_audio_dir / f"edge-{uuid.uuid4().hex}.mp3"
        rate_percent = int(round((rate - 1.0) * 100))
        rate_string = f"{rate_percent:+d}%"

        async def save() -> None:
            communicator = edge_tts.Communicate(text=text, voice=voice, rate=rate_string)
            await communicator.save(str(path))

        try:
            asyncio.run(asyncio.wait_for(save(), timeout=float(self.settings.tts_edge_timeout_seconds)))
            if not path.exists() or path.stat().st_size == 0:
                raise TtsUnavailable("Edge TTS returned an empty audio file")
            return path
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise TtsUnavailable(f"Edge TTS failed: {exc}") from exc


class KokoroTtsProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._tts = None
        self._lock = threading.RLock()

    def _paths(self) -> dict[str, Path]:
        base = self.settings.kokoro_dir
        return {
            "model": next((candidate for candidate in (base / "model.int8.onnx", base / "model.onnx") if candidate.exists()), base / "model.int8.onnx"),
            "voices": base / "voices.bin",
            "tokens": base / "tokens.txt",
            "data_dir": base / "espeak-ng-data",
            "lexicon": next((candidate for candidate in (base / "lexicon-us-en.txt", base / "lexicon.txt") if candidate.exists()), base / "lexicon-us-en.txt"),
        }

    def model_ready(self) -> bool:
        paths = self._paths()
        return all(paths[name].exists() for name in ("model", "voices", "tokens", "data_dir"))

    def model_fingerprint(self) -> str:
        model = self._paths()["model"]
        if not model.exists():
            return str(model)
        stat = model.stat()
        return f"{model.name}:{stat.st_size}:{stat.st_mtime_ns}"

    def _load(self):
        with self._lock:
            if self._tts is not None:
                return self._tts
            if not self.model_ready():
                raise TtsUnavailable(
                    "Kokoro model is missing. Run: python scripts/download_kokoro.py"
                )
            try:
                import sherpa_onnx
            except ImportError as exc:
                raise TtsUnavailable("sherpa-onnx is not installed") from exc
            paths = self._paths()
            try:
                kokoro = sherpa_onnx.OfflineTtsKokoroModelConfig(
                    model=str(paths["model"]),
                    voices=str(paths["voices"]),
                    tokens=str(paths["tokens"]),
                    data_dir=str(paths["data_dir"]),
                    lexicon=str(paths["lexicon"]) if paths["lexicon"].exists() else "",
                )
                model_config = sherpa_onnx.OfflineTtsModelConfig(
                    kokoro=kokoro,
                    provider="cpu",
                    debug=False,
                    num_threads=self.settings.kokoro_threads,
                )
                config = sherpa_onnx.OfflineTtsConfig(
                    model=model_config,
                    max_num_sentences=1,
                )
                if not config.validate():
                    raise TtsUnavailable("Kokoro model configuration is invalid")
                self._tts = sherpa_onnx.OfflineTts(config)
                return self._tts
            except TtsUnavailable:
                raise
            except Exception as exc:
                raise TtsUnavailable(f"Unable to initialize Kokoro: {exc}") from exc

    def warmup(self) -> dict[str, Any]:
        """Load Kokoro once so the first local sentence has predictable latency."""
        self._load()
        return self.status()

    def reload_model(self, *, load: bool = True) -> dict[str, Any]:
        """Release the native Kokoro object and optionally initialize it again."""
        import gc

        with self._lock:
            self._tts = None
            gc.collect()
        if load:
            return self.warmup()
        return self.status()

    def status(self) -> dict[str, Any]:
        try:
            import sherpa_onnx  # noqa: F401

            installed = True
        except Exception:
            installed = False
        return {
            "installed": installed,
            "model_ready": self.model_ready(),
            "loaded": self._tts is not None,
            "model": self.model_fingerprint(),
        }

    def generate(self, text: str, voice_id: int, speed: float) -> Path:
        try:
            import sherpa_onnx
            import soundfile as sf
        except ImportError as exc:
            raise TtsUnavailable("sherpa-onnx and soundfile are required") from exc
        with self._lock:
            tts = self._load()
            generation = sherpa_onnx.GenerationConfig()
            generation.sid = int(voice_id)
            generation.speed = float(speed)
            generation.silence_scale = 0.2
            try:
                audio = tts.generate(text, generation)
            except Exception as exc:
                raise TtsUnavailable(f"Kokoro generation failed: {exc}") from exc
            if len(audio.samples) == 0:
                raise TtsUnavailable("Kokoro generated no audio")
            path = self.settings.runtime_audio_dir / f"kokoro-{uuid.uuid4().hex}.wav"
            sf.write(path, audio.samples, audio.sample_rate, subtype="PCM_16")
            return path


class TtsService:
    def __init__(
        self,
        settings: Settings,
        player: HostAudioPlayer,
        monitor: Any | None = None,
        kokoro_provider: Any | None = None,
    ):
        self.settings = settings
        self.player = player
        self.edge = EdgeTtsProvider(settings)
        self.kokoro = kokoro_provider or KokoroTtsProvider(settings)
        self.monitor = monitor
        self._synthesis_lock = threading.RLock()
        self._playback_lock = threading.RLock()
        self._generation_lock = threading.RLock()
        self._generation = 0
        self._current_text = ""
        self._current_provider = ""
        self._last_error: str | None = None
        self._last_playback_meta: dict[str, Any] = {}
        self._provider_failures: dict[str, int] = {"edge": 0, "kokoro": 0}
        self._provider_open_until: dict[str, float] = {"edge": 0.0, "kokoro": 0.0}
        self._provider_last_error: dict[str, str | None] = {"edge": None, "kokoro": None}

    @property
    def is_playing(self) -> bool:
        return self.player.is_playing

    @property
    def current_text(self) -> str:
        return self._current_text

    @property
    def last_playback_meta(self) -> dict[str, Any]:
        return dict(self._last_playback_meta)

    def begin_speech(self) -> int:
        """Cancel earlier speech and reserve a token for the new utterance."""
        with self._generation_lock:
            self._generation += 1
            speech_id = self._generation
        # Stop the previous file but keep the selected Windows/SDL endpoint
        # open. Recreating the mixer for each utterance can make Bluetooth
        # outputs disappear and return in the Windows sound selector.
        self.player.stop()
        return speech_id

    def stop_current(self) -> None:
        with self._generation_lock:
            self._generation += 1
        self.player.stop()

    def _is_current(self, speech_id: int) -> bool:
        with self._generation_lock:
            return speech_id == self._generation

    def _provider_order(self, mode: str) -> list[str]:
        return {
            "edge": ["edge"],
            "kokoro": ["kokoro"],
            "edge_fallback": ["edge", "kokoro"],
            "kokoro_fallback": ["kokoro", "edge"],
        }.get(mode, ["edge", "kokoro"])

    @staticmethod
    def _normalise_text(text: str) -> str:
        return " ".join(clean_assistant_text(text).split()).strip()

    def _cache_path(self, provider: str, text: str, agent: dict[str, Any], namespace: str) -> Path:
        payload: dict[str, Any] = {
            "cache_version": 1,
            "namespace": namespace,
            "provider": provider,
            "text": self._normalise_text(text),
            "rate": round(float(agent.get("tts_rate", 1.0)), 4),
        }
        extension = ".mp3" if provider == "edge" else ".wav"
        if provider == "edge":
            payload["voice"] = str(agent.get("edge_voice") or "en-US-AriaNeural")
        else:
            payload["voice_id"] = int(agent.get("kokoro_voice_id", 0))
            payload["model"] = self.kokoro.model_fingerprint()
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        folder = self.settings.tts_cache_dir / namespace
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{digest}{extension}"

    def _provider_circuit_open(self, provider: str) -> bool:
        return time.monotonic() < self._provider_open_until.get(provider, 0.0)

    def _record_provider_success(self, provider: str) -> None:
        self._provider_failures[provider] = 0
        self._provider_open_until[provider] = 0.0
        self._provider_last_error[provider] = None

    def _record_provider_failure(self, provider: str, error: Exception) -> None:
        self._provider_failures[provider] = self._provider_failures.get(provider, 0) + 1
        self._provider_last_error[provider] = str(error)
        self._provider_open_until[provider] = time.monotonic() + float(self.settings.tts_circuit_open_seconds)
        if self.monitor:
            self.monitor.increment("tts_provider_failures")

    def generate_audio_blocking(
        self,
        text: str,
        agent: dict[str, Any],
        speech_id: int,
        *,
        use_cache: bool = False,
        cache_namespace: str = "script",
    ) -> GeneratedSpeech | None:
        text = self._normalise_text(text)
        if not text or not self._is_current(speech_id):
            return None
        errors: list[str] = []
        with self._synthesis_lock:
            provider_order = self._provider_order(agent.get("tts_mode", "edge_fallback"))
            for provider in provider_order:
                if not self._is_current(speech_id):
                    return None
                if self._provider_circuit_open(provider) and len(provider_order) > 1:
                    LOGGER.warning("Skipping TTS provider %s while its circuit is open", provider)
                    errors.append(f"{provider}: temporarily disabled after a recent failure")
                    if self.monitor:
                        self.monitor.increment("tts_circuit_skips")
                    continue
                cache_path = self._cache_path(provider, text, agent, cache_namespace) if use_cache else None
                if cache_path and cache_path.exists() and cache_path.stat().st_size > 0:
                    LOGGER.info("TTS cache hit [%s]: %s", provider, cache_path.name)
                    self._record_provider_success(provider)
                    return GeneratedSpeech(
                        path=cache_path,
                        provider=provider,
                        text=text,
                        cached=True,
                        persistent=True,
                    )
                attempts = max(1, int(self.settings.tts_retry_count) + 1)
                for attempt in range(attempts):
                    generated: Path | None = None
                    try:
                        if provider == "edge":
                            generated = self.edge.generate(
                                text,
                                str(agent.get("edge_voice") or "en-US-AriaNeural"),
                                float(agent.get("tts_rate", 1.0)),
                            )
                        else:
                            generated = self.kokoro.generate(
                                text,
                                int(agent.get("kokoro_voice_id", 0)),
                                float(agent.get("tts_rate", 1.0)),
                            )
                        if not self._is_current(speech_id):
                            generated.unlink(missing_ok=True)
                            return None
                        self._record_provider_success(provider)
                        if cache_path:
                            temp_target = cache_path.with_suffix(cache_path.suffix + f".{uuid.uuid4().hex}.tmp")
                            shutil.move(str(generated), str(temp_target))
                            os.replace(temp_target, cache_path)
                            generated = cache_path
                            LOGGER.info("TTS cached [%s]: %s", provider, cache_path.name)
                            return GeneratedSpeech(
                                path=cache_path,
                                provider=provider,
                                text=text,
                                cached=False,
                                persistent=True,
                            )
                        return GeneratedSpeech(
                            path=generated,
                            provider=provider,
                            text=text,
                            cached=False,
                            persistent=False,
                        )
                    except (TtsUnavailable, AudioUnavailable) as exc:
                        if generated and generated.exists():
                            generated.unlink(missing_ok=True)
                        if not self._is_current(speech_id):
                            return None
                        if attempt + 1 < attempts:
                            LOGGER.warning("TTS provider %s failed; retrying once: %s", provider, exc)
                            continue
                        self._record_provider_failure(provider, exc)
                        errors.append(f"{provider}: {exc}")
                        LOGGER.warning("TTS provider %s failed: %s", provider, exc)
            self._last_error = "; ".join(errors) or "No TTS provider succeeded"
            raise TtsUnavailable(self._last_error)

    def play_generated_blocking(
        self,
        generated: GeneratedSpeech,
        agent: dict[str, Any],
        speech_id: int,
    ) -> bool:
        if not self._is_current(speech_id):
            self.cleanup_generated(generated)
            return False
        with self._playback_lock:
            if not self._is_current(speech_id):
                self.cleanup_generated(generated)
                return False
            self._current_text = generated.text
            self._current_provider = generated.provider
            self._last_playback_meta = {
                "provider": generated.provider,
                "cached": generated.cached,
                "text": generated.text,
                "kokoro_voice": voice_name(agent.get("kokoro_voice_id", 0)),
            }
            try:
                played = self.player.play_file(
                    generated.path,
                    volume=float(agent.get("tts_volume", 1.0)),
                    cancel_check=lambda: not self._is_current(speech_id),
                )
                if played:
                    self._last_error = None
                return played
            finally:
                self._current_text = ""
                self._current_provider = ""
                self.cleanup_generated(generated)

    @staticmethod
    def cleanup_generated(generated: GeneratedSpeech | None) -> None:
        if not generated or generated.persistent:
            return
        try:
            generated.path.unlink(missing_ok=True)
        except Exception:
            pass

    def speak_blocking(
        self,
        text: str,
        agent: dict[str, Any],
        speech_id: int | None = None,
        *,
        use_cache: bool = False,
        cache_namespace: str = "script",
    ) -> bool:
        text = text.strip()
        if not text:
            return True
        if speech_id is None:
            speech_id = self.begin_speech()
        generated = self.generate_audio_blocking(
            text,
            agent,
            speech_id,
            use_cache=use_cache,
            cache_namespace=cache_namespace,
        )
        if generated is None:
            return False
        return self.play_generated_blocking(generated, agent, speech_id)

    def status(self) -> dict[str, Any]:
        try:
            import edge_tts  # noqa: F401

            edge_installed = True
        except Exception:
            edge_installed = False
        try:
            kokoro_status = (
                dict(self.kokoro.status())
                if hasattr(self.kokoro, "status")
                else {"installed": False, "model_ready": self.kokoro.model_ready(), "loaded": False}
            )
        except Exception as exc:
            kokoro_status = {
                "installed": False,
                "model_ready": self.kokoro.model_ready(),
                "loaded": False,
                "state": "unavailable",
                "last_error": str(exc),
            }
        return {
            "playing": self.is_playing,
            "current_text": self.current_text,
            "current_provider": self._current_provider,
            "edge_installed": edge_installed,
            "kokoro_installed": bool(kokoro_status.get("installed")),
            "kokoro_model_ready": bool(kokoro_status.get("model_ready")),
            "kokoro_loaded": bool(kokoro_status.get("loaded")),
            "kokoro_status": kokoro_status,
            "last_error": self._last_error,
            "last_playback": self.last_playback_meta,
            "cache_dir": str(self.settings.tts_cache_dir),
            "provider_health": {
                name: {
                    "circuit_open": self._provider_circuit_open(name),
                    "open_for_seconds": max(0, round(self._provider_open_until[name] - time.monotonic(), 1)),
                    "failures": self._provider_failures[name],
                    "last_error": self._provider_last_error[name],
                }
                for name in ("edge", "kokoro")
            },
        }
