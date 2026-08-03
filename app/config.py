from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_prefix="VERBANODE_",
        case_sensitive=False,
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8002
    pin: str = "1234"
    db_path: Path = ROOT_DIR / "data" / "verbanode.db"
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
    kokoro_dir: Path = ROOT_DIR / "models" / "kokoro" / "kokoro-int8-multi-lang-v1_1"
    tts_cache_path: Path = ROOT_DIR / "data" / "tts_cache"
    kokoro_threads: int = Field(default=2, ge=1, le=16)
    open_browser: bool = True
    ssl_certfile: Path | None = None
    ssl_keyfile: Path | None = None
    controller_timeout_seconds: int = 45
    takeover_timeout_seconds: int = 30
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

    @property
    def runtime_audio_dir(self) -> Path:
        path = ROOT_DIR / "runtime_audio"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def tts_cache_dir(self) -> Path:
        path = self.tts_cache_path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def backup_dir(self) -> Path:
        path = ROOT_DIR / "backups"
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    if not settings.db_path.is_absolute():
        settings.db_path = ROOT_DIR / settings.db_path
    if not settings.kokoro_dir.is_absolute():
        settings.kokoro_dir = ROOT_DIR / settings.kokoro_dir
    if not settings.tts_cache_path.is_absolute():
        settings.tts_cache_path = ROOT_DIR / settings.tts_cache_path
    if settings.ssl_certfile and not settings.ssl_certfile.is_absolute():
        settings.ssl_certfile = ROOT_DIR / settings.ssl_certfile
    if settings.ssl_keyfile and not settings.ssl_keyfile.is_absolute():
        settings.ssl_keyfile = ROOT_DIR / settings.ssl_keyfile
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
