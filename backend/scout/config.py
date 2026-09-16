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

# A field whose name carries one of these is a secret and is redacted from repr().
SECRET_FIELD_MARKERS = ("key", "token", "credentials", "secret", "password")


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
    # The §6 walkthrough's fault switch (Task 4.2). Exactly "1" turns it on; anything else,
    # including unset, leaves POST /admin/fault unregistered. A string, not a bool, so
    # "true" or a stray "yes" in .env cannot open an operator door by accident.
    fault_injection: str = ""
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
    # Free tier: 15 requests per minute per model, and a REJECTED request still counts,
    # so pacing under the cap beats retrying into it. 0 disables pacing (paid tiers).
    job1_gemini_rpm: int = 15
    # Job 1 must finish before a shortlist exists and Gate L gives first audio 3.5 s, so a
    # call still running at 12 s has already missed its purpose - waiting the old 30 s only
    # delayed "I didn't catch that". Median is 0.99 s (measured 2026-09-10); p99 is NOT
    # measured, so this is a judgement, and it is a setting precisely so it can be tuned.
    job1_gemini_timeout_s: float = 12.0
    # Three attempts in all. The 2026-09-10 eval pass lost three cases that each timed out
    # TWICE, which one retry could not save.
    job1_gemini_timeout_retries: int = 2
    job2_model: str = "claude-sonnet-5"
    job2_effort: str = "low"  # P7
    job2_max_tokens: int = 2048

    # Voice (P3, P3b)
    deepgram_model: str = "nova-3"
    # Spec §6.20: below this, a transcript is treated as low confidence and confirmed rather
    # than acted on. Deepgram returns `confidence` on every alternative (verified against
    # deepgram-sdk 7.8.0, listen_v1results_channel_alternatives_item.py, where it is a
    # required float). **This number is a judgement, not a measurement** - no noisy audio has
    # been scored against it, because the project has none labelled. It is a setting
    # precisely so it can be tuned once Task 4.1 puts real production audio on the clock.
    # 0.0 disables the check and restores the pre-§6.20 behaviour.
    stt_min_confidence: float = 0.6
    deepgram_endpointing_ms: int = 400
    hold_extra_ms: int = 400
    utterance_end_ms: int = 1000
    audio_sample_rate: int = 16000
    smallest_voice_id: str = ""
    smallest_model: str = "lightning_v3.1_pro"
    smallest_sample_rate: int = 24000

    session_ttl_s: int = 1800
    max_clarifying_questions: int = 5

    def __repr_args__(self):
        # pytest prints every fixture's repr under a failing test, and the eval `settings`
        # fixture is a live Settings: on 2026-09-14 a Suite C failure put the first fifty
        # characters of the Anthropic key in the terminal. A secret never appears in a
        # repr, a str, or a traceback — only whether it is set.
        for name, value in super().__repr_args__():
            if name and value and any(m in name for m in SECRET_FIELD_MARKERS):
                yield name, "<set>"
            else:
                yield name, value

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
