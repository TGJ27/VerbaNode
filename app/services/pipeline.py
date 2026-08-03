from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


PIPELINE_STATES = {
    "starting",
    "idle",
    "listening",
    "recording",
    "transcribing",
    "thinking",
    "tooling",
    "speaking",
    "recovering",
    "error",
    "stopped",
}


@dataclass(slots=True)
class TurnContext:
    """Identifiers shared by every stage of one user/assistant turn."""

    source: str
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    capture_id: str | None = None
    generation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: float = field(default_factory=time.monotonic)

    @classmethod
    def for_audio(cls, source: str) -> "TurnContext":
        return cls(source=source, capture_id=uuid.uuid4().hex)


class PipelineMonitor:
    """Thread-safe state machine and lightweight latency/health recorder.

    The conversation pipeline remains authoritative in the core process while
    Phase 2 isolates native microphone and speaker ownership in a supervised
    Audio Engine child process.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = "starting"
        self._state_since = time.monotonic()
        self._turn: TurnContext | None = None
        self._marks: dict[str, float] = {}
        self._last_latency_ms: dict[str, int] = {}
        self._counters: dict[str, int] = {
            "turns_started": 0,
            "turns_completed": 0,
            "turns_cancelled": 0,
            "stt_retries": 0,
            "stt_timeouts": 0,
            "tool_timeouts": 0,
            "tts_provider_failures": 0,
            "tts_circuit_skips": 0,
            "queue_overflows": 0,
            "audio_device_recoveries": 0,
            "errors": 0,
        }
        self._last_error: dict[str, Any] | None = None
        self.transition("idle")

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def begin_turn(self, source: str, *, audio: bool = False) -> TurnContext:
        turn = TurnContext.for_audio(source) if audio else TurnContext(source=source)
        now = time.monotonic()
        with self._lock:
            self._turn = turn
            self._marks = {"turn_started": now}
            self._counters["turns_started"] += 1
        return turn

    def active_turn(self) -> TurnContext | None:
        with self._lock:
            return self._turn

    def transition(self, state: str, **metadata: Any) -> dict[str, Any]:
        if state not in PIPELINE_STATES:
            raise ValueError(f"Unknown pipeline state: {state}")
        now = time.monotonic()
        with self._lock:
            self._state = state
            self._state_since = now
            self._marks[f"state:{state}"] = now
            return self.snapshot(extra=metadata)

    def mark(self, name: str) -> None:
        with self._lock:
            self._marks[name] = time.monotonic()

    def duration(self, name: str, start_mark: str, end_mark: str | None = None) -> int | None:
        with self._lock:
            start = self._marks.get(start_mark)
            end = self._marks.get(end_mark) if end_mark else time.monotonic()
            if start is None or end is None:
                return None
            value = max(0, int(round((end - start) * 1000)))
            self._last_latency_ms[name] = value
            return value

    def finish_turn(self, *, cancelled: bool = False) -> None:
        with self._lock:
            self.duration("turn_total", "turn_started")
            self._counters["turns_cancelled" if cancelled else "turns_completed"] += 1
            self._turn = None

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + int(amount)

    def error(self, source: str, message: str) -> None:
        with self._lock:
            self._counters["errors"] += 1
            self._last_error = {
                "source": source,
                "message": str(message),
                "at_unix": int(time.time()),
            }
        self.transition("error", source=source)

    def snapshot(self, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            turn = self._turn
            payload: dict[str, Any] = {
                "state": self._state,
                "state_for_ms": max(0, int(round((time.monotonic() - self._state_since) * 1000))),
                "turn_id": turn.turn_id if turn else None,
                "capture_id": turn.capture_id if turn else None,
                "generation_id": turn.generation_id if turn else None,
                "source": turn.source if turn else None,
                "latency_ms": dict(self._last_latency_ms),
                "counters": dict(self._counters),
                "last_error": dict(self._last_error) if self._last_error else None,
            }
            if extra:
                payload.update(extra)
            return payload
