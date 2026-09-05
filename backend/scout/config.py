"""All configuration. Every secret is a backend environment variable (spec §5.4)."""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # `.env.example` lists what an operator must supply. This model also carries
    # defaults nobody sets by hand (port, the model ids, the speech timings), so it
    # legitimately has more fields than that file has names.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    deepgram_api_key: str = ""
    groq_api_key: str = ""
    anthropic_api_key: str = ""
    smallest_api_key: str = ""
    google_oauth_credentials: str = ""
    google_tenant_calendar_id: str = ""
    google_owner_calendar_id: str = ""
    google_sender_email: str = ""
    operator_token: str = ""
    bundle_dir: str = "../data/bundle"
    cors_allowed_origins: str = ""
    latency_log_path: str | None = None
    port: int = 8000

    # Models — pinned by exact id, never an alias (spec §5.1)
    job1_model: str = "openai/gpt-oss-120b"
    job2_model: str = "claude-sonnet-5"
    job2_effort: str = "low"  # P7
    job2_max_tokens: int = 2048

    # Voice (P3, P3b)
    deepgram_model: str = "nova-3"
    deepgram_endpointing_ms: int = 400
    hold_extra_ms: int = 400
    utterance_end_ms: int = 1000
    audio_sample_rate: int = 16000
    smallest_voice_id: str = ""
    smallest_model: str = "lightning_v3.1"
    smallest_sample_rate: int = 24000

    session_ttl_s: int = 1800
    max_clarifying_questions: int = 5

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @field_validator("deepgram_endpointing_ms")
    @classmethod
    def _endpointing_floor(cls, v: int) -> int:
        if v < 400:
            raise ValueError("P3: endpointing must not be shorter than 400 ms")
        return v
