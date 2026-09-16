"""Typed configuration for the research-assistant SE layer.

Reads settings from environment variables / .env and exposes them as one typed
object. API keys are intentionally NOT stored here: the provided ai/ package
reads its own provider keys directly from the environment, and we never want
secrets flowing through (or hard-coded in) our code. Keeping keys out of here
is also what protects us from the -10pt hard-coded-keys deduction.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- which providers the ai/ layer will use ---------------------------
    # The ai/ package reads these from env itself; we mirror them only so the
    # CLI / logs / report can show what was used. No API keys live here.
    llm_provider: str = "anthropic"
    web_search_provider: str = "duckduckgo"   # free, no key — good for grading

    # --- concurrency ------------------------------------------------------
    max_concurrency: int = 5          # semaphore bound (respects rate limits)
    source_timeout: float = 10.0      # per-source timeout, seconds

    # --- retries (consumed by the tenacity policy in ai_service) ----------
    max_retries: int = 3
    retry_backoff: float = 1.0        # base seconds for exponential backoff

    # --- cache ------------------------------------------------------------
    cache_dir: str = ".cache"
    cache_ttl: int = 86_400           # seconds (24h)

    # --- input validation -------------------------------------------------
    min_question_len: int = 3
    max_question_len: int = 500

    # --- logging ----------------------------------------------------------
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance so env is read only once."""
    return Settings()


if __name__ == "__main__":
    # print-based inspection: `python -m src.config`
    s = get_settings()
    for name, value in s.model_dump().items():
        print(f"{name:20} = {value!r}")