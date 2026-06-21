"""
Central configuration via pydantic-settings.

All tunable values (model, API key, record caps, base URL, turn limit) live here
instead of being read from os.environ at call sites. Reading them in one place
makes them discoverable and overridable from a single .env file.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr


class Settings(BaseSettings):
    # env_file is loaded if present; real environment variables take precedence.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM provider ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # --- ClinicalTrials.gov API ---
    ct_base_url: str = "https://clinicaltrials.gov/api/v2"

    # --- Fetch caps ---
    default_max_records: int = 5_000     # per-query default when the agent doesn't override
    max_records_cap: int = 10_000        # hard ceiling to prevent runaway fetches

    # --- Citations ---
    # For demo, capped at lower citations per group to keep the response payload manageable.
    citations_per_group: int = 3         # max citations kept per aggregation bucket

    # --- Agent loop ---
    agent_max_turns: int = 12            # safety bound on tool-calling iterations


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — construct Settings once per process."""
    return Settings()
