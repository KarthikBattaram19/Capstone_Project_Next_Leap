"""Thin wrappers over the four voice/LLM providers. Signatures verified against the
installed SDKs on 2026-09-05; each module records what it saw."""


def make_job1_client(settings):
    """The client Job 1 talks to, chosen by Settings.job1_provider.

    One factory, so `create_app` and the eval harness can never end up on different
    providers — a suite that passed against a Job 1 the renter never reaches is not
    evidence of anything (spec §7).
    """
    if settings.job1_provider == "gemini":
        from scout.providers.gemini_job1 import GeminiJob1Client

        return GeminiJob1Client(settings)
    if settings.job1_provider == "groq":
        from scout.providers.groq_job1 import GroqJob1Client

        return GroqJob1Client(settings)
    raise ValueError(f"job1_provider must be 'gemini' or 'groq', not {settings.job1_provider!r}")
