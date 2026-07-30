"""
Configuration loader for the Resume Scraper Sub-Agent.

Loads settings from config.yaml or environment variables with pydantic-settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


class ResumeScraperConfig(BaseSettings):
    """Typed configuration for the In-Memory Resume Scraper."""

    max_stream_size_mb: int = Field(
        default=10, ge=1, le=100, description="Hard cap on the stream buffer size in MB."
    )
    max_pages_to_parse: int = Field(
        default=3, ge=1, le=50, description="Maximum number of pages to parse."
    )
    regex_prefilter_enabled: bool = Field(
        default=True, description="Use fast regex pass before calling the LLM."
    )
    llm_provider: str = Field(
        default="google", description="LLM provider: 'google' (Gemini) or 'openai'."
    )
    llm_model: str = Field(
        default="gemini-2.0-flash", description="Model identifier for LLM extraction (e.g., gemini-2.0-flash, gpt-4o-mini)."
    )
    temperature: float = Field(
        default=0.0, ge=0.0, le=2.0, description="LLM temperature setting."
    )
    api_key: Optional[str] = Field(
        default=None, description="LLM API key. Falls back to RESUME_AGENT_API_KEY or GEMINI_API_KEY/OPENAI_API_KEY env vars."
    )

    class Config:
        env_prefix = "RESUME_AGENT_"
        env_file = ".env"
        env_file_encoding = "utf-8"

    @classmethod
    def from_yaml(cls, yaml_path: str | Path) -> "ResumeScraperConfig":
        """Load configuration from a YAML file, overlaying env vars."""
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            return cls()

        with open(yaml_path, "r") as f:
            raw = yaml.safe_load(f) or {}

        scraper_cfg = raw.get("in_memory_resume_scraper", {})
        return cls(**scraper_cfg)

