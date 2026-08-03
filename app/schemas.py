from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.defaults import (
    ROPI_CONTEXT_SIZE,
    ROPI_GREETING,
    ROPI_MAX_TOKENS,
    ROPI_ROLE,
    ROPI_SYSTEM_PROMPT,
    ROPI_TEMPERATURE,
    ROPI_TOP_P,
)


class LoginRequest(BaseModel):
    pin: str
    client_name: str = "Browser"
    force_takeover: bool = False


class TakeoverResponse(BaseModel):
    request_id: str
    approve: bool


class AgentCreate(BaseModel):
    name: str = Field(default="Ropi", min_length=1, max_length=80)
    color: str = "#6c63ff"
    avatar: str = "RP"
    role: str = ROPI_ROLE
    system_prompt: str = ROPI_SYSTEM_PROMPT
    greeting: str = ROPI_GREETING
    llm_model: str = "qwen3.5:0.8b"
    temperature: float = Field(default=ROPI_TEMPERATURE, ge=0, le=2)
    top_p: float = Field(default=ROPI_TOP_P, ge=0, le=1)
    max_tokens: int = Field(default=ROPI_MAX_TOKENS, ge=32, le=8192)
    context_size: int = Field(default=ROPI_CONTEXT_SIZE, ge=512, le=131072)
    tts_mode: Literal["edge", "kokoro", "edge_fallback", "kokoro_fallback"] = "edge_fallback"
    edge_voice: str = "en-US-AriaNeural"
    kokoro_voice_id: int = Field(default=0, ge=0, le=102)
    tts_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    tts_volume: float = Field(default=1.0, ge=0, le=1)
    stt_model: str = "iic/SenseVoiceSmall"
    tools_enabled: list[str] = Field(
        default_factory=lambda: [
            "get_current_time",
            "get_location",
            "get_weather",
            "handle_exit_intent",
        ]
    )
    info_ids: list[int] = Field(default_factory=list)


class AgentUpdate(AgentCreate):
    pass


class RoleGenerateRequest(BaseModel):
    description: str = Field(min_length=3, max_length=4000)
    model: str | None = None


class InfoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=50000)
    enabled: bool = True


class ScriptCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=20000)
    enabled: bool = True


class TextMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    conversation_id: int | None = None


class ConversationCreate(BaseModel):
    title: str | None = None


class ConversationSettingsUpdate(BaseModel):
    interruption_enabled: bool = False
    silence_ms: int = Field(default=900, ge=300, le=5000)
    max_record_seconds: int = Field(default=30, ge=3, le=180)
    stt_confidence_filter_enabled: bool = True
    stt_confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    input_device: int | None = None
    output_device: int | None = None


class AudioDeviceTestRequest(BaseModel):
    input_device: int | None = None
    output_device: int | None = None


class QueueReorder(BaseModel):
    ordered_ids: list[int]


class QueueAction(BaseModel):
    action: Literal["play", "pause", "stop", "clear"]


class SettingsPatch(BaseModel):
    values: dict[str, Any]


class PinChangeRequest(BaseModel):
    current_pin: str
    new_pin: str = Field(min_length=4, max_length=32)
