from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

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
    client_name: str = Field(default="Browser", min_length=1, max_length=120)
    client_type: str = Field(default="unknown", min_length=1, max_length=32)
    client_version: str | None = Field(default=None, max_length=64)
    api_version: int | None = Field(default=None, ge=1, le=1000)


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
    language: Literal["en", "id"] = "en"
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

    @model_validator(mode="after")
    def apply_language_profile(self) -> "AgentCreate":
        if self.language == "id":
            if self.stt_model not in {"Whisper-base", "Whisper-small"}:
                self.stt_model = "Whisper-base"
            self.tts_mode = "edge"
            if not self.edge_voice.startswith("id-"):
                self.edge_voice = "id-ID-GadisNeural"
        else:
            self.stt_model = "iic/SenseVoiceSmall"
            if not self.edge_voice.lower().startswith("en-"):
                self.edge_voice = "en-US-AriaNeural"
        return self


class AgentUpdate(AgentCreate):
    pass


class RoleGenerateRequest(BaseModel):
    description: str = Field(min_length=3, max_length=4000)
    model: str | None = None


class InfoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=50000)
    enabled: bool = True


class KnowledgeLibraryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    enabled: bool = True

    @model_validator(mode="after")
    def normalize_library(self) -> "KnowledgeLibraryCreate":
        self.name = self.name.strip()
        self.description = self.description.strip()
        if not self.name:
            raise ValueError("Knowledge library name cannot be blank")
        return self


class KnowledgeLibraryUpdate(KnowledgeLibraryCreate):
    pass


class AgentKnowledgeLibrariesUpdate(BaseModel):
    library_ids: list[int] = Field(default_factory=list, max_length=500)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    library_ids: list[int] = Field(default_factory=list, max_length=500)
    agent_id: int | None = Field(default=None, ge=1)
    mode: Literal["hybrid", "lexical", "vector", "table"] = "hybrid"
    top_k: int = Field(default=8, ge=1, le=50)
    candidate_k: int = Field(default=30, ge=1, le=200)

    @model_validator(mode="after")
    def normalize_search(self) -> "KnowledgeSearchRequest":
        self.query = self.query.strip()
        self.library_ids = sorted({int(value) for value in self.library_ids if int(value) > 0})
        if not self.query:
            raise ValueError("Knowledge search query cannot be blank")
        if self.candidate_k < self.top_k:
            self.candidate_k = self.top_k
        return self


class KnowledgeIndexRebuildRequest(BaseModel):
    library_id: int | None = Field(default=None, ge=1)


class ScriptCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=20000)
    enabled: bool = True
    language: Literal["en", "id"] = "en"
    tts_mode: Literal["edge", "kokoro", "edge_fallback", "kokoro_fallback"] = "edge"
    edge_voice: str = "en-US-AriaNeural"
    kokoro_voice_id: int = Field(default=0, ge=0, le=102)
    tts_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    tts_volume: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def apply_script_language_profile(self) -> "ScriptCreate":
        if self.language == "id":
            self.tts_mode = "edge"
            if not self.edge_voice.startswith("id-"):
                self.edge_voice = "id-ID-GadisNeural"
        elif not self.edge_voice.lower().startswith("en-"):
            self.edge_voice = "en-US-AriaNeural"
        return self


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
    show_rejected_stt_transcripts: bool = True
    input_device: int | None = None
    output_device: int | None = None


class AudioDeviceTestRequest(BaseModel):
    input_device: int | None = None
    output_device: int | None = None


class EdgeVoicePreviewRequest(BaseModel):
    voice: str = Field(min_length=3, max_length=120)
    text: str = Field(
        default="Hello. This is a preview of the selected VerbaNode voice.",
        min_length=1,
        max_length=500,
    )
    rate: float = Field(default=1.0, ge=0.5, le=2.0)
    volume: float = Field(default=1.0, ge=0.0, le=1.0)


class ScriptTtsPreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    language: Literal["en", "id"] = "en"
    tts_mode: Literal["edge", "kokoro", "edge_fallback", "kokoro_fallback"] = "edge"
    edge_voice: str = "en-US-AriaNeural"
    kokoro_voice_id: int = Field(default=0, ge=0, le=102)
    tts_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    tts_volume: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def apply_language_profile(self) -> "ScriptTtsPreviewRequest":
        if self.language == "id":
            self.tts_mode = "edge"
            if not self.edge_voice.startswith("id-"):
                self.edge_voice = "id-ID-GadisNeural"
        elif not self.edge_voice.lower().startswith("en-"):
            self.edge_voice = "en-US-AriaNeural"
        return self


class ScriptDefaultsUpdate(BaseModel):
    language: Literal["en", "id"] = "en"
    tts_mode: Literal["edge", "kokoro", "edge_fallback", "kokoro_fallback"] = "edge"
    edge_voice: str = Field(default="en-US-AriaNeural", min_length=3, max_length=120)
    kokoro_voice_id: int = Field(default=0, ge=0, le=102)
    tts_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    tts_volume: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def apply_language_profile(self) -> "ScriptDefaultsUpdate":
        if self.language == "id":
            self.tts_mode = "edge"
            if not self.edge_voice.startswith("id-"):
                self.edge_voice = "id-ID-GadisNeural"
        elif self.edge_voice.lower().startswith("id-"):
            self.edge_voice = "en-US-AriaNeural"
        return self


class TypeToTalkCreate(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    language: Literal["en", "id"] | None = None
    tts_mode: Literal["edge", "kokoro", "edge_fallback", "kokoro_fallback"] | None = None
    edge_voice: str | None = Field(default=None, min_length=3, max_length=120)
    kokoro_voice_id: int | None = Field(default=None, ge=0, le=102)
    tts_rate: float | None = Field(default=None, ge=0.5, le=2.0)
    tts_volume: float | None = Field(default=None, ge=0.0, le=1.0)


class TypeToTalkSettingsUpdate(BaseModel):
    language: Literal["en", "id"] = "en"
    tts_mode: Literal["edge", "kokoro", "edge_fallback", "kokoro_fallback"] = "edge"
    edge_voice: str = Field(default="en-US-AriaNeural", min_length=3, max_length=120)
    kokoro_voice_id: int = Field(default=0, ge=0, le=102)
    tts_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    tts_volume: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def apply_language_profile(self) -> "TypeToTalkSettingsUpdate":
        if self.language == "id":
            self.tts_mode = "edge"
            if not self.edge_voice.startswith("id-"):
                self.edge_voice = "id-ID-GadisNeural"
        elif self.edge_voice.startswith("id-"):
            self.edge_voice = "en-US-AriaNeural"
        return self


class TypeToTalkReorder(BaseModel):
    ordered_ids: list[int]


class DiagnosticsSoakRequest(BaseModel):
    duration_minutes: int = Field(default=30, ge=1, le=480)
    interval_seconds: int = Field(default=5, ge=2, le=60)


class PluginStateUpdate(BaseModel):
    enabled: bool


class QueueReorder(BaseModel):
    ordered_ids: list[int]


class QueueItemUpdate(BaseModel):
    pause_after_seconds: float = Field(default=0.0, ge=0.0, le=3600.0)


class QueueSettingsUpdate(BaseModel):
    loop: bool


class QueueAction(BaseModel):
    action: Literal["play", "pause", "stop", "clear"]


class SettingsPatch(BaseModel):
    values: dict[str, Any]


class PinChangeRequest(BaseModel):
    current_pin: str
    new_pin: str = Field(min_length=4, max_length=32)


class DeviceLoginRequest(BaseModel):
    device_id: str = Field(min_length=8, max_length=128)
    device_token: str = Field(min_length=20, max_length=256)
    client_name: str = Field(default="VerbaNode Android", min_length=1, max_length=120)
    client_type: str = Field(default="mobile", min_length=1, max_length=32)
    client_version: str | None = Field(default=None, max_length=64)
    api_version: int | None = Field(default=None, ge=1, le=1000)


class PairingStartRequest(BaseModel):
    preferred_server_url: str | None = Field(default=None, max_length=500)


class PairingClaimRequest(BaseModel):
    pairing_id: str | None = Field(default=None, max_length=200)
    secret: str | None = Field(default=None, max_length=300)
    short_code: str | None = Field(default=None, min_length=6, max_length=12)
    device_name: str = Field(default="Android device", min_length=1, max_length=120)
    device_type: str = Field(default="mobile", min_length=1, max_length=32)
    device_version: str | None = Field(default=None, max_length=64)
    platform: str | None = Field(default="android", max_length=64)

    @model_validator(mode="after")
    def validate_pairing_proof(self) -> "PairingClaimRequest":
        has_qr = bool(self.pairing_id and self.secret)
        has_code = bool(self.short_code)
        if not has_qr and not has_code:
            raise ValueError("pairing_id + secret or short_code is required")
        return self


class DeviceRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
