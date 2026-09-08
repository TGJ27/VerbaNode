from __future__ import annotations

import json
import logging
import os
import platform
import re
import statistics
import sys
import threading
import time
import zipfile
from collections import deque
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Callable

try:
    import psutil
except Exception:  # pragma: no cover - diagnostics degrades gracefully
    psutil = None  # type: ignore[assignment]


_TOKEN_PATTERNS = (
    re.compile(r"([?&]token=)[^&\s]+", re.IGNORECASE),
    re.compile(r"(x-session-token\s*[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(authorization\s*[:=]\s*bearer\s+)\S+", re.IGNORECASE),
    re.compile(r"(pairing\s+secret\s*[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(device[_ -]?token\s*[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(\bpin\s*[:=]\s*)\S+", re.IGNORECASE),
)
_CONTENT_PATTERNS = (
    re.compile(r"(\btext=)(['\"]).*?\2", re.IGNORECASE),
    re.compile(r"(Queued TTS sentence \d+:\s*).*$", re.IGNORECASE),
    re.compile(r"(STT transcript rejected[^:]*:\s*).*$", re.IGNORECASE),
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _redact(value: str) -> str:
    text = str(value)
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(r"\1<redacted>", text)
    for pattern in _CONTENT_PATTERNS:
        text = pattern.sub(r"\1<content redacted>", text)
    return text


class RingLogHandler(logging.Handler):
    """Thread-safe in-memory application log used by the diagnostics dashboard."""

    def __init__(self, capacity: int = 800):
        super().__init__(level=logging.INFO)
        self.capacity = max(100, int(capacity))
        self._entries: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._lock = threading.RLock()
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] [%(processName)s] %(name)s - %(message)s"
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            formatted = _redact(self.format(record))
            entry = {
                "timestamp": datetime.fromtimestamp(
                    record.created, timezone.utc
                ).isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "logger": record.name,
                "process": record.processName,
                "message": _redact(record.getMessage()),
                "formatted": formatted,
            }
            with self._lock:
                self._entries.append(entry)
        except Exception:
            self.handleError(record)

    def entries(self, limit: int = 200, minimum_level: str | None = None) -> list[dict[str, Any]]:
        level_value = logging._nameToLevel.get(str(minimum_level or "").upper(), 0)
        with self._lock:
            values = list(self._entries)
        if level_value:
            values = [
                entry
                for entry in values
                if logging._nameToLevel.get(str(entry.get("level", "")).upper(), 0)
                >= level_value
            ]
        return values[-max(1, min(int(limit), self.capacity)) :]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class DiagnosticsManager:
    """Collect runtime health, recent logs, self-test results and soak samples."""

    def __init__(
        self,
        diagnostics_dir: Path,
        *,
        app_version: str,
        build_label: str,
        log_capacity: int = 800,
    ) -> None:
        self.diagnostics_dir = Path(diagnostics_dir)
        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        self.app_version = str(app_version)
        self.build_label = str(build_label)
        self.started_monotonic = time.monotonic()
        self.started_at = _utc_iso()
        self.log_handler = RingLogHandler(log_capacity)
        self._logging_installed = False
        self._soak_lock = threading.RLock()
        self._soak_stop = threading.Event()
        self._soak_thread: threading.Thread | None = None
        self._soak: dict[str, Any] = self._empty_soak()
        self._last_self_test: dict[str, Any] | None = None

    @staticmethod
    def _empty_soak() -> dict[str, Any]:
        return {
            "active": False,
            "id": None,
            "started_at": None,
            "completed_at": None,
            "duration_seconds": 0,
            "interval_seconds": 5,
            "elapsed_seconds": 0,
            "remaining_seconds": 0,
            "sample_count": 0,
            "stop_reason": None,
            "samples": [],
            "summary": {},
            "report_path": None,
        }

    def install_logging(self) -> None:
        if self._logging_installed:
            return
        root_logger = logging.getLogger()
        if self.log_handler not in root_logger.handlers:
            root_logger.addHandler(self.log_handler)
        self._logging_installed = True

    def logs(self, limit: int = 200, minimum_level: str | None = None) -> list[dict[str, Any]]:
        return self.log_handler.entries(limit, minimum_level)

    def clear_logs(self) -> None:
        self.log_handler.clear()

    @property
    def uptime_seconds(self) -> int:
        return max(0, int(time.monotonic() - self.started_monotonic))

    @staticmethod
    def _process_metrics(pid: int | None) -> dict[str, Any]:
        if not pid:
            return {"available": False, "pid": pid}
        if psutil is None:
            return {"available": False, "pid": pid, "error": "psutil unavailable"}
        try:
            process = psutil.Process(int(pid))
            memory = process.memory_info()
            return {
                "available": True,
                "pid": int(pid),
                "name": process.name(),
                "status": process.status(),
                "cpu_percent": round(float(process.cpu_percent(interval=None)), 1),
                "rss_mb": round(memory.rss / (1024**2), 1),
                "threads": process.num_threads(),
                "started_at": datetime.fromtimestamp(
                    process.create_time(), timezone.utc
                ).isoformat(timespec="seconds"),
            }
        except Exception as exc:
            return {"available": False, "pid": int(pid), "error": str(exc)}

    def environment(self) -> dict[str, Any]:
        packages: dict[str, str] = {}
        for name in (
            "fastapi",
            "uvicorn",
            "pydantic",
            "httpx",
            "numpy",
            "sounddevice",
            "soundfile",
            "funasr",
            "modelscope",
            "torch",
            "onnxruntime",
            "sherpa-onnx",
            "edge-tts",
            "psutil",
        ):
            try:
                packages[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                continue
            except Exception:
                continue
        return {
            "app_version": self.app_version,
            "build": self.build_label,
            "started_at": self.started_at,
            "uptime_seconds": self.uptime_seconds,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "packages": packages,
        }

    def system_metrics(self) -> dict[str, Any]:
        if psutil is None:
            return {"available": False, "error": "psutil unavailable"}
        try:
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(str(self.diagnostics_dir.anchor or self.diagnostics_dir))
            return {
                "available": True,
                "cpu_percent": round(float(psutil.cpu_percent(interval=None)), 1),
                "cpu_count": psutil.cpu_count(logical=True),
                "ram_total_gb": round(memory.total / (1024**3), 2),
                "ram_used_gb": round(memory.used / (1024**3), 2),
                "ram_available_gb": round(memory.available / (1024**3), 2),
                "ram_percent": round(float(memory.percent), 1),
                "disk_total_gb": round(disk.total / (1024**3), 2),
                "disk_free_gb": round(disk.free / (1024**3), 2),
                "disk_percent": round(float(disk.percent), 1),
            }
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def resource_snapshot(
        self,
        *,
        core_pid: int,
        audio_pid: int | None,
        ai_pid: int | None,
    ) -> dict[str, Any]:
        return {
            "system": self.system_metrics(),
            "processes": {
                "core": self._process_metrics(core_pid),
                "audio": self._process_metrics(audio_pid),
                "ai": self._process_metrics(ai_pid),
            },
        }

    def set_last_self_test(self, result: dict[str, Any]) -> None:
        self._last_self_test = dict(result)

    def last_self_test(self) -> dict[str, Any] | None:
        return dict(self._last_self_test) if self._last_self_test else None

    @staticmethod
    def _numeric(values: list[Any]) -> list[float]:
        result: list[float] = []
        for value in values:
            try:
                if value is not None:
                    result.append(float(value))
            except (TypeError, ValueError):
                continue
        return result

    def _summarize_soak(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        if not samples:
            return {}

        def stats(values: list[Any]) -> dict[str, float | None]:
            numbers = self._numeric(values)
            if not numbers:
                return {"min": None, "max": None, "avg": None}
            return {
                "min": round(min(numbers), 2),
                "max": round(max(numbers), 2),
                "avg": round(statistics.fmean(numbers), 2),
            }

        process_names = ("core", "audio", "ai")
        processes: dict[str, Any] = {}
        for name in process_names:
            processes[name] = {
                "cpu_percent": stats(
                    [sample.get("processes", {}).get(name, {}).get("cpu_percent") for sample in samples]
                ),
                "rss_mb": stats(
                    [sample.get("processes", {}).get(name, {}).get("rss_mb") for sample in samples]
                ),
                "threads": stats(
                    [sample.get("processes", {}).get(name, {}).get("threads") for sample in samples]
                ),
            }

        first = samples[0]
        last = samples[-1]
        first_audio_restarts = int(first.get("audio_restart_count") or 0)
        last_audio_restarts = int(last.get("audio_restart_count") or 0)
        first_ai_restarts = int(first.get("ai_restart_count") or 0)
        last_ai_restarts = int(last.get("ai_restart_count") or 0)
        return {
            "system_cpu_percent": stats(
                [sample.get("system", {}).get("cpu_percent") for sample in samples]
            ),
            "system_ram_percent": stats(
                [sample.get("system", {}).get("ram_percent") for sample in samples]
            ),
            "processes": processes,
            "audio_heartbeat_age_seconds": stats(
                [sample.get("audio_heartbeat_age_seconds") for sample in samples]
            ),
            "ai_heartbeat_age_seconds": stats(
                [sample.get("ai_heartbeat_age_seconds") for sample in samples]
            ),
            "max_asr_inflight": max(int(sample.get("asr_inflight") or 0) for sample in samples),
            "max_kokoro_inflight": max(int(sample.get("kokoro_inflight") or 0) for sample in samples),
            "audio_restart_delta": max(0, last_audio_restarts - first_audio_restarts),
            "ai_restart_delta": max(0, last_ai_restarts - first_ai_restarts),
            "pipeline_error_delta": max(
                0,
                int(last.get("pipeline_errors") or 0)
                - int(first.get("pipeline_errors") or 0),
            ),
            "sample_count": len(samples),
        }

    def start_soak(
        self,
        sample_provider: Callable[[], dict[str, Any]],
        *,
        duration_seconds: int,
        interval_seconds: int = 5,
    ) -> dict[str, Any]:
        duration_seconds = max(60, min(int(duration_seconds), 8 * 60 * 60))
        interval_seconds = max(2, min(int(interval_seconds), 60))
        with self._soak_lock:
            if self._soak.get("active"):
                raise RuntimeError("A diagnostics soak test is already running")
            test_id = datetime.now().strftime("%Y%m%d-%H%M%S")
            self._soak_stop.clear()
            self._soak = {
                **self._empty_soak(),
                "active": True,
                "id": test_id,
                "started_at": _utc_iso(),
                "duration_seconds": duration_seconds,
                "interval_seconds": interval_seconds,
                "remaining_seconds": duration_seconds,
            }

        def worker() -> None:
            started = time.monotonic()
            stop_reason = "completed"
            while True:
                elapsed = max(0, int(time.monotonic() - started))
                if elapsed >= duration_seconds:
                    break
                if self._soak_stop.is_set():
                    stop_reason = "stopped_by_user"
                    break
                try:
                    sample = dict(sample_provider())
                    sample["captured_at"] = _utc_iso()
                    sample["elapsed_seconds"] = elapsed
                except Exception as exc:
                    sample = {
                        "captured_at": _utc_iso(),
                        "elapsed_seconds": elapsed,
                        "sample_error": str(exc),
                    }
                with self._soak_lock:
                    samples = self._soak["samples"]
                    samples.append(sample)
                    # Eight hours at two-second intervals stays bounded below 15k entries.
                    if len(samples) > 15000:
                        del samples[: len(samples) - 15000]
                    self._soak.update(
                        {
                            "elapsed_seconds": elapsed,
                            "remaining_seconds": max(0, duration_seconds - elapsed),
                            "sample_count": len(samples),
                            "summary": self._summarize_soak(samples),
                        }
                    )
                if self._soak_stop.wait(interval_seconds):
                    stop_reason = "stopped_by_user"
                    break

            completed_at = _utc_iso()
            with self._soak_lock:
                samples = list(self._soak.get("samples") or [])
                elapsed = max(0, int(time.monotonic() - started))
                summary = self._summarize_soak(samples)
                report = {
                    **self._soak,
                    "active": False,
                    "completed_at": completed_at,
                    "elapsed_seconds": min(elapsed, duration_seconds),
                    "remaining_seconds": max(0, duration_seconds - elapsed),
                    "stop_reason": stop_reason,
                    "summary": summary,
                }
                report_path = self.diagnostics_dir / f"soak-{report['id']}.json"
                report["report_path"] = str(report_path)
                report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
                self._soak = report

        self._soak_thread = threading.Thread(
            target=worker,
            name="verbanode-diagnostics-soak",
            daemon=True,
        )
        self._soak_thread.start()
        return self.soak_status(include_samples=False)

    def stop_soak(self) -> dict[str, Any]:
        with self._soak_lock:
            if not self._soak.get("active"):
                return self.soak_status(include_samples=False)
            self._soak_stop.set()
        thread = self._soak_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        return self.soak_status(include_samples=False)

    def soak_status(self, *, include_samples: bool = False) -> dict[str, Any]:
        with self._soak_lock:
            payload = dict(self._soak)
            samples = list(payload.get("samples") or [])
        if payload.get("active") and payload.get("started_at"):
            # elapsed is updated by the sampler; keep status monotonic between samples.
            payload["remaining_seconds"] = max(
                0,
                int(payload.get("duration_seconds") or 0)
                - int(payload.get("elapsed_seconds") or 0),
            )
        if include_samples:
            payload["samples"] = samples
        else:
            payload.pop("samples", None)
        return payload

    def create_report(
        self,
        snapshot: dict[str, Any],
        *,
        recent_turns: list[dict[str, Any]],
        self_test: dict[str, Any] | None = None,
    ) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.diagnostics_dir / f"verbanode-diagnostics-{timestamp}.zip"
        report = {
            "generated_at": _utc_iso(),
            "environment": self.environment(),
            "snapshot": snapshot,
            "self_test": self_test or self.last_self_test(),
            "recent_turns": recent_turns,
            "soak": self.soak_status(include_samples=True),
            "privacy": {
                "session_tokens_redacted": True,
                "environment_file_included": False,
                "database_included": False,
                "conversation_content_included": False,
            },
        }
        logs = self.logs(limit=self.log_handler.capacity)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("diagnostics.json", json.dumps(report, indent=2, ensure_ascii=False))
            archive.writestr(
                "recent-logs.txt",
                "\n".join(str(entry.get("formatted") or "") for entry in logs),
            )
            archive.writestr(
                "recent-turns.json",
                json.dumps(recent_turns, indent=2, ensure_ascii=False),
            )
            archive.writestr(
                "README.txt",
                "VerbaNode diagnostics report. Session tokens are redacted. "
                "The .env file, controller PIN, database, conversations, certificates, "
                "and model binaries are not included.\n",
            )
        return path

    def shutdown(self) -> None:
        self.stop_soak()
