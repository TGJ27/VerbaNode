from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings, get_settings
from app.db import Database
from app.services.audio import HostAudioPlayer, HostAudioRecorder
from app.services.audio_engine import (
    AudioEngineSupervisor,
    AudioPlayerProxy,
    AudioRecorderProxy,
)
from app.services.controller import ControllerManager
from app.services.conversation import ConversationManager
from app.services.events import EventHub
from app.services.llm import OllamaService
from app.services.pipeline import PipelineMonitor
from app.services.script_queue import ScriptQueueManager
from app.services.stt import FunASRService
from app.services.tools import ToolService
from app.services.tts import TtsService


@dataclass
class AppState:
    settings: Settings
    db: Database
    events: EventHub
    controller: ControllerManager
    monitor: PipelineMonitor
    recorder: Any
    player: Any
    audio_engine: AudioEngineSupervisor | None
    stt: FunASRService
    tools: ToolService
    llm: OllamaService
    tts: TtsService
    conversation: ConversationManager
    script_queue: ScriptQueueManager

    def reconcile_audio_devices(self) -> dict[str, int | None]:
        runtime = self.db.get_runtime_settings()
        input_fingerprint = runtime.get("input_device_fingerprint")
        output_fingerprint = runtime.get("output_device_fingerprint")
        resolved_input = self.recorder.resolve_device_id(
            runtime.get("input_device"),
            input_fingerprint,
            "input",
        )
        resolved_output = self.recorder.resolve_device_id(
            runtime.get("output_device"),
            output_fingerprint,
            "output",
        )
        if resolved_input != runtime.get("input_device"):
            self.db.set_setting("input_device", "" if resolved_input is None else str(resolved_input))
        if resolved_output != runtime.get("output_device"):
            self.db.set_setting("output_device", "" if resolved_output is None else str(resolved_output))
        if self.audio_engine is not None:
            self.audio_engine.configure_input(
                resolved_input, fingerprint=input_fingerprint, locked=False
            )
            self.audio_engine.configure_output(
                resolved_output, fingerprint=output_fingerprint, locked=False
            )
        self.player.set_output_device(resolved_output)
        return {"input_device": resolved_input, "output_device": resolved_output}

    def refresh_audio_devices(self, reason: str = "dashboard refresh") -> dict[str, Any]:
        """Rebuild PortAudio's device snapshot and reconcile saved fingerprints."""
        runtime = self.db.get_runtime_settings()
        if self.audio_engine is not None:
            self.audio_engine.configure_input(
                runtime.get("input_device"),
                fingerprint=runtime.get("input_device_fingerprint"),
                locked=False,
            )
            self.audio_engine.configure_output(
                runtime.get("output_device"),
                fingerprint=runtime.get("output_device_fingerprint"),
                locked=False,
            )
            refresh = self.audio_engine.refresh_devices(attempts=3, reason=reason)
        else:
            self.recorder.close()
            self.player.close()
            HostAudioRecorder.refresh_portaudio(settle_seconds=0.45)
            devices = HostAudioRecorder.list_devices()
            refresh = {"ok": True, "devices": devices, "device_count": len(devices)}
        resolved = self.reconcile_audio_devices()
        self.monitor.increment("audio_device_recoveries")
        return {"ok": True, "refresh": refresh, **resolved}



def build_state() -> AppState:
    settings = get_settings()
    db = Database(settings)
    db.initialize()
    events = EventHub()
    controller = ControllerManager(settings)
    monitor = PipelineMonitor()

    audio_engine: AudioEngineSupervisor | None = None
    if settings.audio_engine_process:
        audio_engine = AudioEngineSupervisor(
            sample_rate=settings.sample_rate,
            startup_timeout=settings.audio_engine_startup_timeout_seconds,
            command_timeout=settings.audio_engine_command_timeout_seconds,
            watchdog_interval=settings.audio_engine_watchdog_seconds,
        )

        def persist_remapped_audio_ids(
            input_device: int | None, output_device: int | None
        ) -> None:
            db.set_setting(
                "input_device", "" if input_device is None else str(input_device)
            )
            db.set_setting(
                "output_device", "" if output_device is None else str(output_device)
            )

        audio_engine.set_device_state_callback(persist_remapped_audio_ids)
        recorder: Any = AudioRecorderProxy(audio_engine, settings.sample_rate)
    else:
        recorder = HostAudioRecorder(settings.sample_rate)

    # Preserve saved IDs during module import. Device enumeration is performed
    # after FastAPI startup so Windows PortAudio is touched only by the Audio
    # Engine child process when isolation is enabled.
    runtime_settings = db.get_runtime_settings()
    resolved_input = runtime_settings.get("input_device")
    resolved_output = runtime_settings.get("output_device")

    if audio_engine is not None:
        audio_engine.configure_input(
            resolved_input,
            fingerprint=runtime_settings.get("input_device_fingerprint"),
            locked=False,
        )
        player: Any = AudioPlayerProxy(
            audio_engine,
            resolved_output,
            runtime_settings.get("output_device_fingerprint"),
        )
    else:
        player = HostAudioPlayer(resolved_output)

    stt = FunASRService(settings)
    tools = ToolService(settings)
    llm = OllamaService(settings, tools, monitor)
    tts = TtsService(settings, player, monitor)
    conversation = ConversationManager(
        settings,
        db,
        events,
        recorder,
        stt,
        llm,
        tts,
        monitor=monitor,
    )
    script_queue = ScriptQueueManager(db, tts, events, conversation.active_agent)
    conversation.script_queue = script_queue
    return AppState(
        settings=settings,
        db=db,
        events=events,
        controller=controller,
        monitor=monitor,
        recorder=recorder,
        player=player,
        audio_engine=audio_engine,
        stt=stt,
        tools=tools,
        llm=llm,
        tts=tts,
        conversation=conversation,
        script_queue=script_queue,
    )


state = build_state()
