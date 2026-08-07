from __future__ import annotations

import logging
import math
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np

from app.config import Settings

LOGGER = logging.getLogger(__name__)


class SttUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class TranscriptionResult:
    """Speech recognition output with a best-effort confidence estimate.

    SenseVoice/FunASR's normal AutoModel result does not consistently expose a
    calibrated utterance confidence. When a provider score is available we use
    it; otherwise VerbaNode derives a conservative estimate from audio quality,
    duration, speech rate, and transcript shape. The UI labels this value as an
    estimated confidence rather than a guaranteed probability of correctness.
    """

    text: str
    confidence: float
    confidence_source: str

    @property
    def confidence_percent(self) -> int:
        return int(round(max(0.0, min(1.0, self.confidence)) * 100))


class FunASRService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None
        self._model_name: str | None = None
        self._lock = threading.RLock()

    @staticmethod
    def _is_whisper_model(model_name: str) -> bool:
        return str(model_name or "").strip().lower().startswith("whisper")

    @staticmethod
    def fallback_model(model_name: str | None, language: str | None) -> str | None:
        """Return a conservative fallback for optional multilingual ASR models.

        Whisper Small is the accuracy-first Indonesian option. If it cannot be
        loaded or times out in the isolated AI Engine, Whisper Base is the only
        automatic fallback. English SenseVoice never silently changes models.
        """
        normalized = str(model_name or "").strip().lower()
        lang = str(language or "").strip().lower()
        if lang.startswith("id") and normalized == "whisper-small":
            return "Whisper-base"
        return None

    def _load(self, model_name: str) -> Any:
        with self._lock:
            if self._model is not None and self._model_name == model_name:
                return self._model
            try:
                from funasr import AutoModel
            except ImportError as exc:
                raise SttUnavailable("FunASR is not installed. Run setup_windows.bat.") from exc

            is_whisper = self._is_whisper_model(model_name)
            if is_whisper:
                try:
                    import whisper  # noqa: F401
                except ImportError as exc:
                    raise SttUnavailable(
                        "OpenAI Whisper support is not installed. Run setup_windows.bat again."
                    ) from exc
            try:
                LOGGER.info(
                    "Loading %s ASR model %s",
                    "OpenAI Whisper through FunASR" if is_whisper else "FunASR",
                    model_name,
                )
                options: dict[str, Any] = {
                    "model": model_name,
                    "device": "cpu",
                    "ncpu": 2,
                }
                if is_whisper:
                    options["hub"] = "openai"
                else:
                    options.update({"trust_remote_code": True, "disable_update": True})
                try:
                    self._model = AutoModel(**options)
                except TypeError:
                    # Older FunASR versions may not accept ncpu for the OpenAI hub.
                    options.pop("ncpu", None)
                    self._model = AutoModel(**options)
                self._model_name = model_name
                return self._model
            except Exception as exc:
                raise SttUnavailable(f"Unable to load ASR model '{model_name}': {exc}") from exc

    @staticmethod
    def _clean_text(text: str) -> str:
        # SenseVoice may prepend tags such as <|en|><|NEUTRAL|><|Speech|>.
        text = re.sub(r"<\|[^|]+\|>", "", text)
        return " ".join(text.strip().split())

    @staticmethod
    def _normalize_score(value: Any, *, allow_log_score: bool = False) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        if 0.0 <= number <= 1.0:
            return number
        if 1.0 < number <= 100.0:
            return number / 100.0
        if allow_log_score and -20.0 <= number < 0.0:
            return math.exp(number)
        return None

    @classmethod
    def _provider_confidence(cls, value: Any) -> float | None:
        """Extract confidence if a FunASR/provider build exposes one.

        Different model wrappers use different names. Only known confidence-like
        keys are inspected so timestamp and duration numbers cannot be mistaken
        for confidence.
        """

        direct_keys = {
            "confidence",
            "conf",
            "probability",
            "prob",
            "avg_confidence",
            "mean_confidence",
        }
        score_keys = {"score", "avg_score", "mean_score", "logprob", "avg_logprob"}
        list_keys = {"confidences", "token_confidences", "scores", "token_scores", "probs"}

        if isinstance(value, dict):
            candidates: list[float] = []
            for key, item in value.items():
                normalized_key = str(key).lower().replace("-", "_")
                if normalized_key in direct_keys:
                    score = cls._normalize_score(item)
                    if score is not None:
                        candidates.append(score)
                elif normalized_key in score_keys:
                    score = cls._normalize_score(item, allow_log_score=True)
                    if score is not None:
                        candidates.append(score)
                elif normalized_key in list_keys and isinstance(item, (list, tuple, np.ndarray)):
                    values = [
                        score
                        for raw in item
                        if (score := cls._normalize_score(raw, allow_log_score=True)) is not None
                    ]
                    if values:
                        candidates.append(float(np.mean(values)))
                elif normalized_key in {"sentence_info", "segments", "result", "results"}:
                    nested = cls._provider_confidence(item)
                    if nested is not None:
                        candidates.append(nested)
            return float(np.mean(candidates)) if candidates else None

        if isinstance(value, (list, tuple)):
            candidates = [score for item in value if (score := cls._provider_confidence(item)) is not None]
            return float(np.mean(candidates)) if candidates else None
        return None

    @staticmethod
    def _estimated_confidence(samples: np.ndarray, text: str) -> float:
        """Return a conservative 0..1 quality estimate for threshold filtering."""

        audio = np.asarray(samples, dtype=np.float32).reshape(-1)
        if audio.size == 0 or not text.strip():
            return 0.0

        sample_rate = 16000.0
        duration = max(audio.size / sample_rate, 0.01)
        rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
        peak = float(np.max(np.abs(audio)))
        rms_db = 20.0 * math.log10(max(rms, 1e-7))

        # Typical close-mic speech is commonly around -35 to -15 dBFS. This is
        # deliberately forgiving because VAD has already selected a speech span.
        signal_score = max(0.0, min(1.0, (rms_db + 48.0) / 30.0))
        clipping_ratio = float(np.mean(np.abs(audio) >= 0.985))
        clipping_score = max(0.0, min(1.0, 1.0 - clipping_ratio / 0.025))
        if peak < 0.003:
            signal_score *= 0.35

        visible = [char for char in text if not char.isspace()]
        alpha_numeric = sum(char.isalnum() for char in visible)
        character_quality = alpha_numeric / max(len(visible), 1)
        words = re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)?", text)
        length_score = max(0.25, min(1.0, len(text.strip()) / 18.0))
        transcript_score = max(0.0, min(1.0, 0.68 * character_quality + 0.32 * length_score))

        words_per_minute = len(words) * 60.0 / duration
        if not words:
            rate_score = 0.2
        elif 45.0 <= words_per_minute <= 260.0:
            rate_score = 1.0
        elif words_per_minute < 45.0:
            rate_score = max(0.25, words_per_minute / 45.0)
        else:
            rate_score = max(0.15, 1.0 - (words_per_minute - 260.0) / 500.0)

        duration_score = max(0.25, min(1.0, duration / 0.8))
        confidence = (
            0.34 * transcript_score
            + 0.30 * signal_score
            + 0.16 * rate_score
            + 0.10 * duration_score
            + 0.10 * clipping_score
        )
        return max(0.05, min(0.98, confidence))

    def transcribe_with_confidence(
        self,
        samples: np.ndarray,
        model_name: str | None = None,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe one immutable PCM snapshot with one transient retry.

        SenseVoice accepts NumPy PCM in current FunASR builds, avoiding a WAV
        round-trip. Older builds are retained through a file fallback. A retry
        is used only for transient runtime/I/O failures; empty speech is never
        retried.
        """
        audio = np.asarray(samples, dtype=np.float32).reshape(-1).copy()
        if audio.size == 0:
            return TranscriptionResult("", 0.0, "empty")
        model_name = model_name or self.settings.funasr_model
        language = "id" if str(language or "").lower().startswith("id") else "en"
        model = self._load(model_name)
        is_whisper = self._is_whisper_model(model_name)
        attempts = max(1, int(getattr(self.settings, "stt_retry_count", 1)) + 1)
        errors: list[str] = []

        for attempt in range(attempts):
            output_path = self.settings.runtime_audio_dir / f"stt-{uuid.uuid4().hex}.wav"
            try:
                if is_whisper:
                    import soundfile as sf
                    sf.write(output_path, audio, self.settings.sample_rate, subtype="PCM_16")
                    decoding_options = {
                        "task": "transcribe",
                        "language": language,
                        "beam_size": None,
                        "fp16": False,
                        "without_timestamps": True,
                        "prompt": None,
                    }
                    result = model.generate(
                        input=str(output_path),
                        DecodingOptions=decoding_options,
                        batch_size_s=0,
                    )
                else:
                    try:
                        result = model.generate(
                            input=audio,
                            cache={},
                            language="en",
                            use_itn=True,
                            batch_size_s=60,
                        )
                    except (TypeError, ValueError, AttributeError) as direct_exc:
                        # Compatibility with FunASR/provider builds that only accept
                        # a file path as input.
                        import soundfile as sf

                        sf.write(output_path, audio, self.settings.sample_rate, subtype="PCM_16")
                        LOGGER.debug("Direct PCM ASR unsupported; using WAV fallback: %s", direct_exc)
                        result = model.generate(
                            input=str(output_path),
                            cache={},
                            language="en",
                            use_itn=True,
                            batch_size_s=60,
                        )
                if not result:
                    return TranscriptionResult("", 0.0, "empty")
                first = result[0] if isinstance(result, list) else result
                if isinstance(first, dict):
                    text = str(first.get("text") or first.get("sentence_info") or "")
                else:
                    text = str(first)
                text = self._clean_text(text)
                provider_confidence = self._provider_confidence(first)
                if provider_confidence is not None:
                    confidence = max(0.0, min(1.0, provider_confidence))
                    source = "provider"
                else:
                    confidence = self._estimated_confidence(audio, text)
                    source = "estimated"
                LOGGER.info(
                    "STT result language=%s confidence=%d%% source=%s attempt=%d text=%r",
                    language,
                    round(confidence * 100),
                    source,
                    attempt + 1,
                    text[:160],
                )
                return TranscriptionResult(text, confidence, source)
            except SttUnavailable:
                raise
            except (OSError, RuntimeError) as exc:
                errors.append(str(exc))
                if attempt + 1 >= attempts:
                    break
                LOGGER.warning("Transient STT failure; retrying once: %s", exc)
            except Exception as exc:
                raise SttUnavailable(f"Speech recognition failed: {exc}") from exc
            finally:
                try:
                    output_path.unlink(missing_ok=True)
                except Exception:
                    pass

        raise SttUnavailable("Speech recognition failed after retry: " + "; ".join(errors))


    def warmup(self, model_name: str | None = None) -> dict[str, Any]:
        """Load the configured model once without performing transcription."""
        model_name = model_name or self.settings.funasr_model
        self._load(model_name)
        return self.status()

    def reload_model(
        self,
        model_name: str | None = None,
        *,
        load: bool = True,
    ) -> dict[str, Any]:
        """Release the current model reference and optionally load it again."""
        import gc

        with self._lock:
            self._model = None
            self._model_name = None
            gc.collect()
        if load:
            return self.warmup(model_name)
        return self.status()

    def transcribe(
        self, samples: np.ndarray, model_name: str | None = None, language: str | None = None
    ) -> str:
        """Backward-compatible text-only interface."""
        return self.transcribe_with_confidence(samples, model_name, language).text

    def status(self) -> dict[str, Any]:
        try:
            import funasr  # noqa: F401

            installed = True
        except Exception:
            installed = False
        return {
            "provider": "OpenAI Whisper via FunASR" if self._is_whisper_model(self._model_name or self.settings.funasr_model) else "FunASR",
            "installed": installed,
            "loaded": self._model is not None,
            "model": self._model_name or self.settings.funasr_model,
            "confidence": "estimated",
        }
