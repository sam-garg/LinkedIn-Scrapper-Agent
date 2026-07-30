"""
Configuration loader for Agent 2 (Scraper Agent).

Manages settings for LinkedIn scraping, resume fallback sub-agent,
and overall pipeline behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


class ScraperAgentConfig(BaseSettings):
    """Typed configuration for the Scraper Agent (Agent 2)."""

    # ── LinkedIn Scraper Settings ────────────────────────────────────
    linkedin_timeout_seconds: int = Field(
        default=30, ge=5, le=120,
        description="Timeout in seconds for LinkedIn profile scraping.",
    )
    linkedin_headless: bool = Field(
        default=True,
        description="Run browser-based LinkedIn scraper in headless mode.",
    )
    linkedin_use_proxy: bool = Field(
        default=False,
        description="Whether to use proxy for LinkedIn scraping.",
    )
    proxy_server: Optional[str] = Field(
        default=None,
        description="Proxy server URL (e.g., http://proxy:8080).",
    )

    # ── Resume Sub-Agent Settings ────────────────────────────────────
    resume_max_stream_size_mb: int = Field(
        default=10, ge=1, le=100,
        description="Hard cap on resume stream buffer size in MB.",
    )
    resume_max_pages_to_parse: int = Field(
        default=3, ge=1, le=50,
        description="Maximum pages to parse from a PDF resume.",
    )
    resume_regex_prefilter_enabled: bool = Field(
        default=True,
        description="Use fast regex pass before calling LLM for resume extraction.",
    )
    resume_llm_model: str = Field(
        default="gemini-2.0-flash",
        description="LLM model for resume extraction (e.g., gemini-2.0-flash, gpt-4o-mini).",
    )
    resume_llm_provider: str = Field(
        default="google",
        description="LLM provider for resume extraction: 'google' or 'openai'.",
    )
    resume_llm_temperature: float = Field(
        default=0.0, ge=0.0, le=2.0,
        description="LLM temperature for resume extraction.",
    )

    # ── Pipeline Behavior ───────────────────────────────────────────
    enable_resume_fallback: bool = Field(
        default=True,
        description="Enable fallback to resume scraper when LinkedIn data is incomplete.",
    )
    enable_portfolio_fallback: bool = Field(
        default=False,
        description="Enable fallback to portfolio scraper (not yet implemented).",
    )
    openai_api_key: Optional[str] = Field(
        default=None,
        description="OpenAI API key. Falls back to SCRAPER_AGENT_OPENAI_API_KEY or OPENAI_API_KEY env var.",
    )
    google_api_key: Optional[str] = Field(
        default=None,
        description="Google/Gemini API key. Falls back to SCRAPER_AGENT_GOOGLE_API_KEY or GOOGLE_API_KEY or GEMINI_API_KEY env var.",
    )

    class Config:
        env_prefix = "SCRAPER_AGENT_"
        env_file = ".env"
        env_file_encoding = "utf-8"

    @classmethod
    def from_yaml(cls, yaml_path: str | Path) -> "ScraperAgentConfig":
        """Load configuration from a YAML file, overlaying env vars."""
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            return cls()

        with open(yaml_path, "r") as f:
            raw = yaml.safe_load(f) or {}

        agent_cfg = raw.get("scraper_agent", {})
        return cls(**agent_cfg)

