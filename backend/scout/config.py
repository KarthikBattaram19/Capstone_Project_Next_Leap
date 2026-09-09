"""All configuration. Every secret is a backend environment variable (spec §5.4)."""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/, resolved from this file rather than from the working directory. The
# conventions put secrets in backend/.env but run commands from the repo root, so a
# plain relative ".env" would silently miss the file in exactly the documented case:
# the integration tests would skip and the boot check would report every secret
# missing, with the file sitting right there.
BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    # `.env.example` lists what an operator must supply. This model also carries
    # defaults nobody sets by hand (port, the model ids, the speech timings), so it
    # legitimately has more fields than that file has names.
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    deepgram_api_key: str = ""
    groq_api_key: str = ""
    anthropic_api_key: str = ""
    smallest_api_key: str = ""
    gemini_api_key: str = ""
    google_oauth_credentials: str = ""
    google_tenant_calendar_id: str = ""
    google_owner_calendar_id: str = ""
    google_sender_email: str = ""
    operator_token: str = ""
    # Resolved from the code, not the cwd: `python -m scout.main` must find the bundle
    # from the repo root and from backend/ alike. Docker overrides it with BUNDLE_DIR.
    bundle_dir: str = str(BACKEND_DIR.parent / "data" / "bundle")
    cors_allowed_origins: str = ""
    latency_log_path: str | None = None
    port: int = 8000

    # Models — pinned by exact id, never an alias (spec §5.1)
    job1_model: str = "openai/gpt-oss-120b"
    # Job 1 fills in a form; it does not need to deliberate. "low" cut the call from
    # 1,147 to 886 tokens with no measured loss of accuracy (2026-09-09), which is what
    # makes a 60-case eval run fit inside the account's daily token allowance.
    job1_effort: str = "low"
    # Which provider answers Job 1. Measured 2026-09-10 on the same probe set:
    # gemini-3.5-flash-lite 6/6 correct at 0.99 s median and 399 tokens a call, against
    # gpt-oss-120b 5/5 at 1.50 s and 886. Groq stays a one-line fallback (spec §5.1
    # amendment, Docs/GATE_L.md) because it is known-good and needs no new code path.
    job1_provider: str = "gemini"  # "gemini" | "groq"
    job1_gemini_model: str = "gemini-3.5-flash-lite"
    # gemini-3.8-flash rejects MINIMAL; on flash-lite it is what keeps the call at ~1 s.
    job1_gemini_thinking: str = "MINIMAL"
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
    smallest_model: str = "lightning_v3.1_pro"
    smallest_sample_rate: int = 24000

    session_ttl_s: int = 1800
    max_clarifying_questions: int = 5

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @field_validator("bundle_dir")
    @classmethod
    def _bundle_dir_absolute(cls, v: str) -> str:
        # A relative value is taken relative to backend/ (where .env lives), never to the
        # working directory: "../data/bundle" in backend/.env must name the same directory
        # whether the server starts from the repo root or from backend/. An absolute
        # value (Docker's /data/bundle) passes through unchanged.
        return str((BACKEND_DIR / v).resolve())

    @field_validator("deepgram_endpointing_ms")
    @classmethod
    def _endpointing_floor(cls, v: int) -> int:
        if v < 400:
            raise ValueError("P3: endpointing must not be shorter than 400 ms")
        return v
