from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.paths import (
    BACKUP_DIR,
    CERT_DIR,
    CONFIG_DIR,
    DATA_DIR,
    DIAGNOSTICS_DIR,
    MODEL_DIR,
    LOG_DIR,
    PLUGIN_DIR,
    RESOURCE_ROOT,
    RUNTIME_AUDIO_DIR,
    SOURCE_ROOT,
    ensure_runtime_layout,
)

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = RESOURCE_ROOT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=CONFIG_DIR / ".env",
        env_prefix="VERBANODE_",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8002
    pin: str = "1234"
    db_path: Path = DATA_DIR / "verbanode.db"
    ollama_url: str = "http://127.0.0.1:11434"
    default_model: str = "qwen3.5:0.8b"
    default_location: str = "Jakarta"
    default_timezone: str = "Asia/Jakarta"
    funasr_model: str = "iic/SenseVoiceSmall"
    sample_rate: int = 16000
    silence_ms: int = 900
    max_record_seconds: int = 30
    post_tts_mic_guard_ms: int = Field(default=500, ge=0, le=3000)
    barge_in_start_delay_ms: int = Field(default=800, ge=0, le=5000)
    kokoro_dir: Path = MODEL_DIR / "kokoro" / "kokoro-int8-multi-lang-v1_1"
    tts_cache_path: Path = DATA_DIR / "tts_cache"
    kokoro_threads: int = Field(default=2, ge=1, le=16)
    open_browser: bool = True
    ssl_certfile: Path | None = None
    ssl_keyfile: Path | None = None
    controller_timeout_seconds: int = 45
    login_max_attempts: int = Field(default=5, ge=2, le=20)
    login_attempt_window_seconds: float = Field(default=60.0, ge=10.0, le=600.0)
    login_lockout_base_seconds: float = Field(default=5.0, ge=1.0, le=120.0)
    login_lockout_max_seconds: float = Field(default=60.0, ge=5.0, le=900.0)
    websocket_ticket_ttl_seconds: float = Field(default=15.0, ge=5.0, le=120.0)
    summary_trigger_messages: int = 24
    summary_keep_recent: int = 10
    stt_timeout_seconds: float = Field(default=30.0, ge=3.0, le=120.0)
    stt_retry_count: int = Field(default=1, ge=0, le=3)
    ollama_connect_timeout_seconds: float = Field(default=5.0, ge=1.0, le=60.0)
    ollama_read_timeout_seconds: float = Field(default=120.0, ge=10.0, le=600.0)
    tool_timeout_seconds: float = Field(default=12.0, ge=1.0, le=120.0)
    max_tool_rounds: int = Field(default=3, ge=1, le=5)
    tts_edge_timeout_seconds: float = Field(default=12.0, ge=3.0, le=120.0)
    tts_retry_count: int = Field(default=1, ge=0, le=3)
    tts_circuit_open_seconds: float = Field(default=60.0, ge=5.0, le=600.0)
    tts_text_queue_size: int = Field(default=8, ge=2, le=64)
    tts_audio_queue_size: int = Field(default=4, ge=1, le=32)
    audio_engine_process: bool = True
    audio_engine_startup_timeout_seconds: float = Field(default=8.0, ge=2.0, le=60.0)
    audio_engine_command_timeout_seconds: float = Field(default=15.0, ge=3.0, le=120.0)
    audio_engine_watchdog_seconds: float = Field(default=3.0, ge=1.0, le=30.0)
    ai_engine_process: bool = True
    ai_engine_startup_timeout_seconds: float = Field(default=10.0, ge=2.0, le=60.0)
    ai_engine_command_timeout_seconds: float = Field(default=45.0, ge=5.0, le=300.0)
    ai_engine_watchdog_seconds: float = Field(default=3.0, ge=1.0, le=30.0)
    ai_engine_asr_queue_size: int = Field(default=2, ge=1, le=8)
    ai_engine_kokoro_queue_size: int = Field(default=4, ge=1, le=16)
    ai_engine_preload_asr: bool = True
    ai_engine_preload_kokoro: bool = True
    ai_engine_kokoro_timeout_seconds: float = Field(default=60.0, ge=10.0, le=300.0)
    external_plugins_path: Path = PLUGIN_DIR
    plugin_execution_timeout_seconds: float = Field(default=10.0, ge=1.0, le=120.0)
    plugin_failure_threshold: int = Field(default=3, ge=1, le=20)
    plugin_max_concurrent_executions: int = Field(default=4, ge=1, le=32)
    plugin_shutdown_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    plugin_manifest_max_bytes: int = Field(default=65536, ge=1024, le=1048576)
    plugin_entry_max_bytes: int = Field(default=2097152, ge=4096, le=16777216)
    capability_audit_path: Path = LOG_DIR / "capability-actions.jsonl"
    capability_execution_timeout_seconds: float = Field(default=10.0, ge=0.1, le=120.0)
    capability_cancel_timeout_seconds: float = Field(default=2.0, ge=0.1, le=30.0)
    capability_provider_shutdown_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)
    capability_max_concurrent_executions: int = Field(default=4, ge=1, le=32)
    capability_provider_max_concurrent_executions: int = Field(default=2, ge=1, le=16)
    capability_max_arguments_bytes: int = Field(default=65536, ge=1024, le=1048576)
    capability_default_ttl_seconds: float = Field(default=30.0, ge=0.1, le=3600.0)
    capability_max_ttl_seconds: float = Field(default=300.0, ge=1.0, le=86400.0)

    @property
    def external_plugins_dir(self) -> Path:
        path = self.external_plugins_path
        if not path.is_absolute():
            path = ROOT_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def runtime_audio_dir(self) -> Path:
        path = RUNTIME_AUDIO_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def tts_cache_dir(self) -> Path:
        path = self.tts_cache_path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def backup_dir(self) -> Path:
        path = BACKUP_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def diagnostics_dir(self) -> Path:
        path = DIAGNOSTICS_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    ensure_runtime_layout()
    settings = Settings()
    if not settings.db_path.is_absolute():
        settings.db_path = DATA_DIR.parent / settings.db_path
    if not settings.kokoro_dir.is_absolute():
        settings.kokoro_dir = MODEL_DIR.parent / settings.kokoro_dir
    if not settings.tts_cache_path.is_absolute():
        settings.tts_cache_path = DATA_DIR.parent / settings.tts_cache_path
    if not settings.external_plugins_path.is_absolute():
        settings.external_plugins_path = PLUGIN_DIR.parent / settings.external_plugins_path
    if not settings.capability_audit_path.is_absolute():
        settings.capability_audit_path = LOG_DIR.parent / settings.capability_audit_path
    if settings.ssl_certfile and not settings.ssl_certfile.is_absolute():
        settings.ssl_certfile = CERT_DIR.parent / settings.ssl_certfile
    if settings.ssl_keyfile and not settings.ssl_keyfile.is_absolute():
        settings.ssl_keyfile = CERT_DIR.parent / settings.ssl_keyfile
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
