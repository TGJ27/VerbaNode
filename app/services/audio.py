from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

LOGGER = logging.getLogger(__name__)


class AudioUnavailable(RuntimeError):
    pass


def _linear_resample(samples: np.ndarray, source_rate: float, target_rate: float) -> np.ndarray:
    """Small dependency-free resampler suitable for speech and TTS playback."""
    data = np.asarray(samples, dtype=np.float32)
    if data.size == 0 or abs(float(source_rate) - float(target_rate)) < 1.0:
        return data.astype(np.float32, copy=False)
    if data.ndim == 1:
        data = data[:, None]
    output_frames = max(1, int(round(data.shape[0] * float(target_rate) / float(source_rate))))
    old_axis = np.linspace(0.0, 1.0, data.shape[0], endpoint=True)
    new_axis = np.linspace(0.0, 1.0, output_frames, endpoint=True)
    output = np.empty((output_frames, data.shape[1]), dtype=np.float32)
    for channel in range(data.shape[1]):
        output[:, channel] = np.interp(new_axis, old_axis, data[:, channel]).astype(np.float32)
    return output[:, 0] if np.asarray(samples).ndim == 1 else output


def decode_pcm_wav(payload: bytes, target_rate: int = 16000) -> np.ndarray:
    """Decode a browser-generated PCM WAV file to mono float32 speech samples."""
    import io
    import wave

    if not payload:
        return np.empty(0, dtype=np.float32)
    try:
        with wave.open(io.BytesIO(payload), "rb") as wav_file:
            channels = int(wav_file.getnchannels())
            sample_width = int(wav_file.getsampwidth())
            source_rate = int(wav_file.getframerate())
            frame_count = int(wav_file.getnframes())
            raw = wav_file.readframes(frame_count)
    except (wave.Error, EOFError) as exc:
        raise AudioUnavailable(f"The dashboard microphone upload is not a valid PCM WAV file: {exc}") from exc

    if channels < 1 or source_rate < 8000:
        raise AudioUnavailable("The dashboard microphone WAV has invalid audio parameters")
    if sample_width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise AudioUnavailable(f"Unsupported dashboard microphone WAV sample width: {sample_width * 8}-bit")

    if data.size == 0:
        return np.empty(0, dtype=np.float32)
    if data.size % channels != 0:
        data = data[: data.size - (data.size % channels)]
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    data = np.clip(data, -1.0, 1.0).astype(np.float32, copy=False)
    return _linear_resample(data, source_rate, target_rate).astype(np.float32, copy=False)


class _SileroDetector:
    def __init__(self, sample_rate: int, silence_ms: int):
        self.sample_rate = sample_rate
        self.silence_ms = silence_ms
        self._iterator = None
        self._torch = None
        try:
            import torch
            from silero_vad import VADIterator, load_silero_vad

            torch.set_num_threads(1)
            model = load_silero_vad(onnx=True)
            self._iterator = VADIterator(
                model,
                sampling_rate=sample_rate,
                threshold=0.5,
                min_silence_duration_ms=silence_ms,
                speech_pad_ms=80,
            )
            self._torch = torch
            LOGGER.info("Silero VAD initialized")
        except Exception as exc:  # optional dependency/runtime model issue
            LOGGER.warning("Silero VAD unavailable; using energy fallback: %s", exc)

    @property
    def using_silero(self) -> bool:
        return self._iterator is not None and self._torch is not None

    def reset(self) -> None:
        if self._iterator is not None:
            try:
                self._iterator.reset_states()
            except Exception:
                pass

    def event(self, chunk: np.ndarray) -> dict | None:
        if not self.using_silero:
            return None
        tensor = self._torch.from_numpy(chunk.astype(np.float32, copy=False))
        return self._iterator(tensor, return_seconds=True)


class HostAudioRecorder:
    """Persistent host microphone session used by conversation and PTT.

    The selected input stream is opened once and kept alive for the complete
    conversation. During TTS the callback discards microphone frames instead of
    closing the endpoint. This prevents Bluetooth profile/endpoint churn while
    still providing safe half-duplex behavior without acoustic echo cancellation.
    """

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = int(sample_rate)
        self._stream_lock = threading.RLock()
        self._session_lock = threading.RLock()
        self._input_stream = None
        self._input_device: int | None = None
        self._input_samplerate = float(self.sample_rate)
        self._input_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=300)
        self._capture_active = False
        self._capture_cancel: threading.Event | None = None
        self._capture_done = threading.Event()
        self._capture_done.set()
        self._ptt_active = False
        self._ptt_chunks: list[np.ndarray] = []
        self._ptt_started_at = 0.0
        self._dropped_input_chunks = 0
        self._input_reopen_count = 0

    @staticmethod
    def list_devices() -> list[dict]:
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
            default_input, default_output = sd.default.device
            result = []
            for index, device in enumerate(devices):
                hostapi_index = int(device.get("hostapi", -1))
                hostapi_name = "Unknown"
                if 0 <= hostapi_index < len(hostapis):
                    hostapi_name = str(hostapis[hostapi_index].get("name", "Unknown"))
                name = str(device.get("name", f"Device {index}"))
                max_input = int(device.get("max_input_channels", 0))
                max_output = int(device.get("max_output_channels", 0))
                result.append(
                    {
                        "id": index,
                        "name": name,
                        "hostapi": hostapi_name,
                        "max_input_channels": max_input,
                        "max_output_channels": max_output,
                        "default_samplerate": float(device.get("default_samplerate", 0)),
                        "is_default_input": index == default_input,
                        "is_default_output": index == default_output,
                        "recommended_input": max_input > 0 and "dji mic" in name.lower(),
                        "recommended_output": max_output > 0 and "jyx" in name.lower(),
                    }
                )
            return result
        except Exception as exc:
            LOGGER.warning("Unable to list audio devices: %s", exc)
            return []

    @staticmethod
    def device_info(device_id: int | None, direction: str | None = None) -> dict | None:
        try:
            import sounddevice as sd

            if device_id is None:
                if direction in {"input", "output"}:
                    device = sd.query_devices(kind=direction)
                    resolved_id = int(sd.default.device[0 if direction == "input" else 1])
                else:
                    return None
            else:
                resolved_id = int(device_id)
                device = sd.query_devices(resolved_id)
            try:
                hostapi = sd.query_hostapis(int(device.get("hostapi", -1)))
                hostapi_name = str(hostapi.get("name", "Unknown"))
            except Exception:
                hostapi_name = "Unknown"
            return {
                "id": resolved_id,
                "name": str(device.get("name", f"Device {resolved_id}")),
                "hostapi": hostapi_name,
                "max_input_channels": int(device.get("max_input_channels", 0)),
                "max_output_channels": int(device.get("max_output_channels", 0)),
                "default_samplerate": float(device.get("default_samplerate", 0) or 0),
            }
        except Exception:
            return None

    @staticmethod
    def device_fingerprint(device: dict | None, direction: str) -> str | None:
        if not device:
            return None
        payload = {
            "name": str(device.get("name") or "").strip(),
            "hostapi": str(device.get("hostapi") or "").strip(),
            "direction": direction,
            "channels": int(device.get("max_input_channels", 0) if direction == "input" else device.get("max_output_channels", 0)),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @classmethod
    def resolve_device_id(
        cls,
        preferred_id: int | None,
        fingerprint: str | dict | None,
        direction: str,
    ) -> int | None:
        """Resolve a saved device after Windows reorders PortAudio IDs."""
        devices = cls.list_devices()
        channel_key = "max_input_channels" if direction == "input" else "max_output_channels"
        available = [d for d in devices if int(d.get(channel_key, 0)) > 0]
        try:
            preferred = int(preferred_id) if preferred_id is not None else None
        except (TypeError, ValueError):
            preferred = None
        # If PortAudio enumeration is temporarily unavailable during startup,
        # preserve the saved ID rather than erasing a valid device selection.
        if not devices:
            return preferred
        try:
            expected = json.loads(fingerprint) if isinstance(fingerprint, str) and fingerprint else (fingerprint or {})
        except json.JSONDecodeError:
            expected = {}

        if preferred is not None:
            current = next((d for d in available if int(d.get("id", -1)) == preferred), None)
            if current:
                if not expected:
                    return preferred
                same_name = str(current.get("name", "")).casefold() == str(expected.get("name", "")).casefold()
                same_api = str(current.get("hostapi", "")).casefold() == str(expected.get("hostapi", "")).casefold()
                if same_name and same_api:
                    return preferred

        expected_name = str(expected.get("name") or "").strip().casefold()
        expected_api = str(expected.get("hostapi") or "").strip().casefold()
        if expected_name:
            exact = [d for d in available if str(d.get("name", "")).strip().casefold() == expected_name]
            if expected_api:
                exact_api = [d for d in exact if str(d.get("hostapi", "")).strip().casefold() == expected_api]
                if exact_api:
                    return int(exact_api[0]["id"])
            if exact:
                return int(exact[0]["id"])
            partial = [d for d in available if expected_name in str(d.get("name", "")).casefold()]
            if partial:
                return int(partial[0]["id"])
        return preferred if any(int(d.get("id", -1)) == preferred for d in available) else None

    def health(self) -> dict:
        return {
            "input_locked": self.input_locked,
            "input_device": self.locked_input_device,
            "dropped_input_chunks": self._dropped_input_chunks,
            "input_reopen_count": self._input_reopen_count,
            "input_queue_depth": self._input_queue.qsize(),
            "input_queue_capacity": self._input_queue.maxsize,
        }

    @property
    def input_locked(self) -> bool:
        with self._stream_lock:
            return bool(self._input_stream is not None and getattr(self._input_stream, "active", True))

    @property
    def locked_input_device(self) -> int | None:
        with self._stream_lock:
            return self._input_device

    def _clear_input_queue(self) -> None:
        while True:
            try:
                self._input_queue.get_nowait()
            except queue.Empty:
                break

    def _input_callback(self, indata, frames, time_info, status):  # noqa: ANN001
        if status:
            LOGGER.debug("Persistent input status: %s", status)
        raw = np.asarray(indata[:, 0], dtype=np.float32).copy()
        chunk = _linear_resample(raw, self._input_samplerate, self.sample_rate)
        with self._stream_lock:
            capture_active = self._capture_active
            ptt_active = self._ptt_active
            if ptt_active:
                self._ptt_chunks.append(chunk.copy())
        if not capture_active:
            return
        try:
            self._input_queue.put_nowait(chunk)
        except queue.Full:
            try:
                self._input_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._input_queue.put_nowait(chunk)
            except queue.Full:
                pass
            self._dropped_input_chunks += 1

    def lock_input(self, input_device: int | None = None) -> dict:
        """Open and start the selected input endpoint once, at its native rate."""
        normalized = int(input_device) if input_device is not None else None
        with self._stream_lock:
            if (
                self._input_stream is not None
                and normalized == self._input_device
                and getattr(self._input_stream, "active", True)
            ):
                info = self.device_info(normalized, "input")
                return info or {"id": normalized, "name": "System default input"}
        self.unlock_input()
        self._input_reopen_count += 1
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise AudioUnavailable("sounddevice is not installed") from exc

        info = self.device_info(normalized, "input")
        if normalized is not None and (not info or int(info.get("max_input_channels", 0)) <= 0):
            raise AudioUnavailable("The selected microphone is unavailable or has no input channels")
        native_rate = float((info or {}).get("default_samplerate") or self.sample_rate)
        # Request a block that becomes approximately 512 frames after resampling
        # to 16 kHz, which is the window size used by Silero in this project.
        native_blocksize = max(64, int(round(native_rate * 512.0 / self.sample_rate)))
        stream = None
        try:
            LOGGER.info(
                "Locking persistent host microphone%s at %.0f Hz",
                f": {info['name']} ({info['hostapi']}, device {normalized})"
                if info
                else " on the Windows default input",
                native_rate,
            )
            self._input_samplerate = native_rate
            stream = sd.InputStream(
                samplerate=native_rate,
                channels=1,
                dtype="float32",
                blocksize=native_blocksize,
                device=normalized,
                latency="low",
                callback=self._input_callback,
            )
            stream.start()
        except Exception as exc:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            raise AudioUnavailable(f"Could not lock the selected host microphone: {exc}") from exc
        with self._stream_lock:
            self._input_stream = stream
            self._input_device = normalized
        LOGGER.info("Persistent host microphone lock active")
        return info or {"id": normalized, "name": "System default input", "hostapi": "System default"}

    def unlock_input(self) -> None:
        self.cancel_capture(wait=True)
        self.cancel_ptt()
        with self._stream_lock:
            stream = self._input_stream
            self._input_stream = None
            self._input_device = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                try:
                    stream.abort()
                except Exception:
                    pass
            try:
                stream.close()
            except Exception:
                pass
            LOGGER.info("Persistent host microphone lock released")

    def test_input(self, input_device: int | None = None, seconds: float = 1.5) -> dict:
        was_locked = self.input_locked
        previous_device = self.locked_input_device
        self.lock_input(input_device)
        self.cancel_capture(wait=True)
        self.cancel_ptt()
        self._ptt_chunks = []
        self._ptt_started_at = time.monotonic()
        with self._stream_lock:
            self._ptt_active = True
        time.sleep(max(0.3, min(5.0, seconds)))
        samples = self.stop_ptt(minimum_seconds=0.0)
        if not was_locked:
            self.unlock_input()
        elif previous_device != input_device:
            self.lock_input(previous_device)
        rms = float(np.sqrt(np.mean(np.square(samples)) + 1e-12)) if samples.size else 0.0
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        info = self.device_info(input_device, "input")
        return {
            "ok": True,
            "device_id": input_device,
            "device_name": info["name"] if info else "System default input",
            "hostapi": info["hostapi"] if info else "System default",
            "rms": rms,
            "peak": peak,
            "rms_percent": min(100, round(rms * 400)),
            "peak_percent": min(100, round(peak * 100)),
        }

    def start_ptt(self, input_device: int | None = None) -> None:
        self.cancel_capture(wait=True)
        self.lock_input(input_device)
        with self._stream_lock:
            if self._ptt_active:
                return
            self._ptt_chunks = []
            self._ptt_started_at = time.monotonic()
            self._ptt_active = True
        LOGGER.info("PTT capture enabled on the persistent microphone stream")

    def stop_ptt(self, minimum_seconds: float = 0.12) -> np.ndarray:
        with self._stream_lock:
            if not self._ptt_active:
                return np.empty(0, dtype=np.float32)
            self._ptt_active = False
            elapsed = time.monotonic() - self._ptt_started_at
            chunks = self._ptt_chunks
            self._ptt_chunks = []
        if elapsed < minimum_seconds or not chunks:
            return np.empty(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32, copy=False)

    def cancel_ptt(self) -> None:
        with self._stream_lock:
            self._ptt_active = False
            self._ptt_chunks = []

    def cancel_capture(self, wait: bool = True, timeout: float = 2.0) -> bool:
        with self._stream_lock:
            cancel = self._capture_cancel
            active = self._capture_active
            self._capture_active = False
            if cancel is not None:
                cancel.set()
        if wait and active:
            closed = self._capture_done.wait(timeout=max(0.0, timeout))
            if not closed:
                LOGGER.warning("Timed out waiting for the active microphone capture to pause")
            return closed
        return not active

    def capture_until_silence(
        self,
        *,
        silence_ms: int,
        max_seconds: int,
        input_device: int | None = None,
        cancel_event: threading.Event | None = None,
        on_speech_start: Callable[[], None] | None = None,
    ) -> np.ndarray:
        with self._session_lock:
            self.lock_input(input_device)
            self.cancel_capture(wait=True)
            self._clear_input_queue()
            detector = _SileroDetector(self.sample_rate, silence_ms)
            speech_started = False
            chunks: list[np.ndarray] = []
            pre_roll: list[np.ndarray] = []
            last_voice = time.monotonic()
            started = time.monotonic()
            energy_threshold = 0.018
            session_cancel = threading.Event()
            with self._stream_lock:
                self._capture_cancel = session_cancel
                self._capture_active = True
                self._capture_done.clear()
            try:
                while time.monotonic() - started < max_seconds:
                    if session_cancel.is_set() or (cancel_event and cancel_event.is_set()):
                        return np.empty(0, dtype=np.float32)
                    try:
                        chunk = self._input_queue.get(timeout=0.10)
                    except queue.Empty:
                        continue
                    now = time.monotonic()
                    event = detector.event(chunk)
                    rms = float(np.sqrt(np.mean(np.square(chunk)) + 1e-12))
                    is_voice_energy = rms >= energy_threshold
                    if not speech_started:
                        pre_roll.append(chunk)
                        if len(pre_roll) > 10:
                            pre_roll.pop(0)
                        silero_start = bool(event and "start" in event)
                        if silero_start or (not detector.using_silero and is_voice_energy):
                            speech_started = True
                            chunks.extend(pre_roll)
                            pre_roll.clear()
                            last_voice = now
                            if on_speech_start:
                                on_speech_start()
                    else:
                        chunks.append(chunk)
                        silero_end = bool(event and "end" in event)
                        if is_voice_energy:
                            last_voice = now
                        if silero_end or (now - last_voice) * 1000 >= silence_ms:
                            break
            except Exception as exc:
                if session_cancel.is_set() or (cancel_event and cancel_event.is_set()):
                    return np.empty(0, dtype=np.float32)
                raise AudioUnavailable(f"Host microphone capture failed: {exc}") from exc
            finally:
                detector.reset()
                with self._stream_lock:
                    self._capture_active = False
                    if self._capture_cancel is session_cancel:
                        self._capture_cancel = None
                    self._capture_done.set()
                LOGGER.info("Host microphone capture paused; persistent stream remains locked")
            if not chunks:
                return np.empty(0, dtype=np.float32)
            return np.concatenate(chunks).astype(np.float32, copy=False)

    def close(self) -> None:
        self.unlock_input()


class HostAudioPlayer:
    """Persistent PortAudio speaker stream pinned to the chosen output.

    The stream continuously feeds silence while idle. This keeps the selected
    Bluetooth output endpoint owned by Python before and during microphone use,
    instead of relying on an SDL/pygame session that disappears between files.
    """

    def __init__(self, output_device: int | None = None):
        self._lock = threading.RLock()
        self._play_lock = threading.RLock()
        self._configured_device = int(output_device) if output_device is not None else None
        self._opened_device: int | None = None
        self._stream = None
        self._sample_rate = 48000.0
        self._channels = 2
        self._buffer: np.ndarray | None = None
        self._buffer_position = 0
        self._playback_done = threading.Event()
        self._playback_done.set()
        self._stop_event = threading.Event()
        self._playing = False
        self._refresh_required = True
        self._output_reopen_count = 0
        self._playback_recovery_count = 0

    @property
    def configured_output_device(self) -> int | None:
        with self._lock:
            return self._configured_device

    @property
    def output_locked(self) -> bool:
        with self._lock:
            return bool(self._stream is not None and getattr(self._stream, "active", True))

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._playing

    def health(self) -> dict:
        with self._lock:
            return {
                "output_locked": self.output_locked,
                "output_device": self._opened_device,
                "configured_output_device": self._configured_device,
                "playing": self._playing,
                "output_reopen_count": self._output_reopen_count,
                "playback_recovery_count": self._playback_recovery_count,
            }

    def set_output_device(self, output_device: int | None) -> None:
        normalized = int(output_device) if output_device is not None else None
        with self._lock:
            if normalized == self._configured_device:
                return
            self._configured_device = normalized
            self._refresh_required = True
        self.close()
        LOGGER.info(
            "Selected host output device changed to %s",
            normalized if normalized is not None else "system default",
        )

    def _output_callback(self, outdata, frames, time_info, status):  # noqa: ANN001
        if status:
            LOGGER.debug("Persistent output status: %s", status)
        outdata.fill(0)
        completed = False
        with self._lock:
            audio = self._buffer
            if audio is not None:
                remaining = audio.shape[0] - self._buffer_position
                count = min(frames, max(0, remaining))
                if count > 0:
                    outdata[:count, : self._channels] = audio[
                        self._buffer_position : self._buffer_position + count,
                        : self._channels,
                    ]
                    self._buffer_position += count
                if self._buffer_position >= audio.shape[0]:
                    self._buffer = None
                    self._buffer_position = 0
                    self._playing = False
                    completed = True
        if completed:
            self._playback_done.set()

    def lock_output(self, output_device: int | None = None) -> dict:
        selected = self._configured_device if output_device is None else int(output_device)
        with self._lock:
            if (
                self._stream is not None
                and selected == self._opened_device
                and getattr(self._stream, "active", True)
                and not self._refresh_required
            ):
                info = HostAudioRecorder.device_info(selected, "output")
                return info or {"id": selected, "name": "System default output"}
        self.close()
        self._output_reopen_count += 1
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise AudioUnavailable("sounddevice is not installed") from exc
        info = HostAudioRecorder.device_info(selected, "output")
        if selected is not None and (not info or int(info.get("max_output_channels", 0)) <= 0):
            raise AudioUnavailable("The selected speaker is unavailable or has no output channels")
        sample_rate = float((info or {}).get("default_samplerate") or 48000.0)
        max_channels = int((info or {}).get("max_output_channels") or 2)
        channels = 2 if max_channels >= 2 else 1
        blocksize = max(128, int(round(sample_rate * 0.02)))
        stream = None
        try:
            LOGGER.info(
                "Locking persistent host speaker%s at %.0f Hz",
                f": {info['name']} ({info['hostapi']}, device {selected})"
                if info
                else " on the Windows default output",
                sample_rate,
            )
            self._sample_rate = sample_rate
            self._channels = channels
            stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
                blocksize=blocksize,
                device=selected,
                latency="low",
                callback=self._output_callback,
            )
            stream.start()
        except Exception as exc:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            raise AudioUnavailable(f"Could not lock the selected Windows speaker: {exc}") from exc
        with self._lock:
            self._stream = stream
            self._opened_device = selected
            self._refresh_required = False
        LOGGER.info("Persistent host speaker lock active; idle output is silent")
        return info or {"id": selected, "name": "System default output", "hostapi": "System default"}

    def _decode_for_output(self, path: Path, volume: float) -> np.ndarray:
        try:
            import soundfile as sf

            audio, source_rate = sf.read(str(path), dtype="float32", always_2d=True)
        except Exception as exc:
            raise AudioUnavailable(f"Could not decode TTS audio {path.name}: {exc}") from exc
        if audio.size == 0:
            raise AudioUnavailable(f"TTS audio file is empty: {path.name}")
        if audio.shape[1] > 1:
            mono = np.mean(audio, axis=1, dtype=np.float32)
        else:
            mono = audio[:, 0]
        mono = _linear_resample(mono, float(source_rate), self._sample_rate)
        level = max(0.0, min(1.0, float(volume)))
        mono = np.clip(mono * level, -1.0, 1.0).astype(np.float32)
        if self._channels == 1:
            return mono[:, None]
        return np.repeat(mono[:, None], self._channels, axis=1)

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            self._buffer = None
            self._buffer_position = 0
            self._playing = False
            self._playback_done.set()

    def request_refresh(self) -> None:
        with self._lock:
            self._refresh_required = True
        self.close()

    def play_file(
        self,
        path: Path,
        volume: float = 1.0,
        output_device: int | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> bool:
        with self._play_lock:
            for attempt in range(2):
                try:
                    self.lock_output(output_device)
                    audio = self._decode_for_output(path, volume)
                    if cancel_check and cancel_check():
                        return False
                    self._stop_event.clear()
                    self._playback_done.clear()
                    with self._lock:
                        self._buffer = audio
                        self._buffer_position = 0
                        self._playing = True
                    LOGGER.info(
                        "Host audio playback started through persistent speaker lock: %s",
                        path.name,
                    )
                    while not self._playback_done.wait(0.03):
                        if self._stop_event.is_set() or (cancel_check and cancel_check()):
                            self.stop()
                            LOGGER.info("Host audio playback stopped: %s", path.name)
                            return False
                        with self._lock:
                            stream_active = bool(
                                self._stream is not None and getattr(self._stream, "active", True)
                            )
                        if not stream_active:
                            raise AudioUnavailable("The persistent speaker stream became inactive")
                    LOGGER.info("Host audio playback completed: %s", path.name)
                    return True
                except AudioUnavailable:
                    self.stop()
                    if attempt:
                        raise
                    LOGGER.warning("Persistent speaker stream failed; reopening once")
                    self._playback_recovery_count += 1
                    self.request_refresh()
                except Exception as exc:
                    self.stop()
                    if attempt:
                        raise AudioUnavailable(f"Windows speaker playback failed: {exc}") from exc
                    LOGGER.warning("Speaker playback failed; reopening once: %s", exc)
                    self._playback_recovery_count += 1
                    self.request_refresh()
            return False

    def close(self) -> None:
        self.stop()
        with self._lock:
            stream = self._stream
            self._stream = None
            self._opened_device = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                try:
                    stream.abort()
                except Exception:
                    pass
            try:
                stream.close()
            except Exception:
                pass
            LOGGER.info("Persistent host speaker lock released")
