from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.db import Database
from app.services.audio import HostAudioPlayer, HostAudioRecorder
from app.services.controller import ControllerManager
from app.services.conversation import ConversationManager
from app.services.events import EventHub
from app.services.llm import OllamaService
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
    recorder: HostAudioRecorder
    player: HostAudioPlayer
    stt: FunASRService
    tools: ToolService
    llm: OllamaService
    tts: TtsService
    conversation: ConversationManager
    script_queue: ScriptQueueManager


def build_state() -> AppState:
    settings = get_settings()
    db = Database(settings)
    db.initialize()
    events = EventHub()
    controller = ControllerManager(settings)
    recorder = HostAudioRecorder(settings.sample_rate)
    runtime_settings = db.get_runtime_settings()
    player = HostAudioPlayer(runtime_settings.get("output_device"))
    stt = FunASRService(settings)
    tools = ToolService(settings)
    llm = OllamaService(settings, tools)
    tts = TtsService(settings, player)
    conversation = ConversationManager(settings, db, events, recorder, stt, llm, tts)
    script_queue = ScriptQueueManager(db, tts, events, conversation.active_agent)
    conversation.script_queue = script_queue
    return AppState(
        settings=settings,
        db=db,
        events=events,
        controller=controller,
        recorder=recorder,
        player=player,
        stt=stt,
        tools=tools,
        llm=llm,
        tts=tts,
        conversation=conversation,
        script_queue=script_queue,
    )


state = build_state()
