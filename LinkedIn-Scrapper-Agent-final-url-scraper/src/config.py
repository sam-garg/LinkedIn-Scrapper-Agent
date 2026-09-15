"""
config.py
---------
Central configuration loader for the LinkedIn URL Discovery Tool.

Reads settings from two sources (in precedence order):
  1. Environment variables / .env file  (runtime config, including optional credentials)
  2. config/settings.json               (structured application defaults)

CREDENTIAL SECURITY
-------------------
LinkedIn credentials (LINKEDIN_EMAIL, LINKEDIN_PASSWORD) are loaded from
environment variables only — never from source code, JSON files, or anywhere
that could be committed to Git.

Passwords are stored in memory only for the duration of the process and are
never written to logs, CSV files, or any other output.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Project root: this file lives at src/config.py, so root is one level up.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# CSV columns for the discovery output — fixed, not configurable.
DISCOVERY_CSV_COLUMNS = [
    "linkedin_url",
    "name",
    "headline",
    "location",
    "search_query",
    "scraped_at",
]


def _load_settings_json(path: Path) -> dict:
    """Load and return the settings.json dictionary."""
    if not path.exists():
        raise FileNotFoundError(
            f"settings.json not found at {path}. "
            "Run the project from its root directory or check the config/ folder."
        )
    with path.open("r", encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"settings.json is malformed: {exc}") from exc
    return data


def _load_universities(path: Path) -> list[str]:
    """
    Load the universities list from a JSON file.

    Used only to generate additional discovery search queries.
    Not used as a filter.

    Returns an empty list (with a warning) if the file is missing.
    """
    if not path.exists():
        logger.warning(
            "universities.json not found at %s. "
            "University-based discovery queries will be skipped.",
            path,
        )
        return []
    with path.open("r", encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            logger.error("universities.json is malformed: %s", exc)
            return []
    if not isinstance(data, list):
        logger.error("universities.json must contain a JSON array.")
        return []
    logger.info("Loaded %d universities from %s", len(data), path)
    return [u for u in data if isinstance(u, str) and u.strip()]


def _parse_bool(value: str, default: bool = False) -> bool:
    """Parse a string environment variable as a boolean."""
    if not value:
        return default
    return value.strip().lower() in ("true", "1", "yes")


class AppConfig:
    """
    Application-wide configuration object.

    Instantiate once and pass around; avoids global mutable state.

    Credential attributes
    ---------------------
    ``linkedin_email`` and ``linkedin_password`` are loaded from environment
    variables.  They are ``None`` when not set.  The password is NEVER logged.
    """

    def __init__(self) -> None:
        # Load .env (silently no-op if file absent)
        load_dotenv(dotenv_path=_PROJECT_ROOT / ".env", override=False)

        raw = _load_settings_json(_PROJECT_ROOT / "config" / "settings.json")

        # ---- Scraper settings ----
        scraper = raw.get("scraper", {})
        self.headless: bool = _parse_bool(
            os.getenv("SCRAPER_HEADLESS", ""), default=bool(scraper.get("headless", False))
        )
        self.default_limit: int = int(os.getenv("DEFAULT_LIMIT", scraper.get("default_limit", 10)))
        self.page_timeout_ms: int = scraper.get("page_timeout_ms", 30_000)
        self.navigation_timeout_ms: int = scraper.get("navigation_timeout_ms", 60_000)
        self.delay_min_sec: float = scraper.get("delay_min_sec", 2.5)
        self.delay_max_sec: float = scraper.get("delay_max_sec", 6.0)
        self.search_page_max: int = scraper.get("search_page_max", 5)
        self.scroll_steps: int = scraper.get("scroll_steps", 3)
        self.login_poll_interval_sec: int = scraper.get("login_poll_interval_sec", 3)
        self.login_poll_max_attempts: int = scraper.get("login_poll_max_attempts", 30)
        self.safe_mode: bool = _parse_bool(
            os.getenv("LINKEDIN_SAFE_MODE", ""), default=bool(scraper.get("safe_mode", False))
        )
        self.max_profiles_per_run: int = int(
            os.getenv("MAX_PROFILES_PER_RUN", scraper.get("max_profiles_per_run", 200))
        )
        self.max_search_pages_per_run: int = int(
            os.getenv("MAX_SEARCH_PAGES_PER_RUN", scraper.get("max_search_pages_per_run", 10))
        )
        self.min_action_delay: float = float(
            os.getenv("MIN_ACTION_DELAY", scraper.get("min_action_delay", 3))
        )
        self.max_action_delay: float = float(
            os.getenv("MAX_ACTION_DELAY", scraper.get("max_action_delay", 7))
        )

        # ---- Path settings ----
        paths = raw.get("paths", {})
        self.browser_profile_dir: Path = _PROJECT_ROOT / paths.get(
            "browser_profile_dir", "data/browser_profile"
        )
        self.output_dir: Path = _PROJECT_ROOT / os.getenv(
            "OUTPUT_DIR", paths.get("output_dir", "data/output")
        )
        self.log_dir: Path = _PROJECT_ROOT / os.getenv(
            "LOG_DIR", paths.get("log_dir", "data/logs")
        )
        self.universities_json: Path = _PROJECT_ROOT / paths.get(
            "universities_json", "config/universities.json"
        )
        self.leads_csv: Path = _PROJECT_ROOT / paths.get(
            "leads_csv", "data/output/linkedin_leads.csv"
        )
        self.leads_txt: Path = _PROJECT_ROOT / paths.get(
            "leads_txt", "data/output/linkedin_urls.txt"
        )
        self.search_queries_path: Path = _PROJECT_ROOT / "config/search_queries.json"

        # ---- Output column order (fixed for this tool) ----
        self.csv_columns: list[str] = DISCOVERY_CSV_COLUMNS

        # ---- University list (used for query generation only, NOT filtering) ----
        self.universities: list[str] = _load_universities(self.universities_json)

        # ---- Postgraduate discovery queries ----
        self.postgraduate_queries: list[str] = self._load_search_queries()

        # ---- Restriction detection signals (used by linkedin.py) ----
        self.restriction_url_signals: list[str] = raw.get("restriction_url_signals", [])
        self.restriction_body_phrases: list[str] = raw.get("restriction_body_phrases", [])

        # ---- Logging ----
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

        # ---- LinkedIn automatic login settings ----
        # Credentials are loaded from env vars only — never from source code.
        # The password is stored in memory only; never written to any file or log.
        self.linkedin_email: str | None = os.getenv("LINKEDIN_EMAIL") or None
        self.linkedin_password: str | None = os.getenv("LINKEDIN_PASSWORD") or None
        self.auto_login: bool = _parse_bool(os.getenv("LINKEDIN_AUTO_LOGIN", ""), default=False)
        self.login_timeout_sec: int = int(os.getenv("LINKEDIN_LOGIN_TIMEOUT", "120"))

        # Ensure output directories exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)

    def _load_search_queries(self) -> list[str]:
        """Load broad postgraduate discovery terms from configuration."""
        if not self.search_queries_path.exists():
            return [
                "MS", "Master's", "Masters", "M.S.", "MBA", "MEng", "M.Eng",
                "MEM", "Master of Science", "Master of Engineering",
                "Master of Business Administration", "Master's student",
                "Master's candidate", "MS student", "Graduate student", "Postgraduate",
            ]
        try:
            data = json.loads(self.search_queries_path.read_text(encoding="utf-8"))
            return [
                query.strip()
                for query in data.get("postgraduate_queries", [])
                if isinstance(query, str) and query.strip()
            ]
        except (OSError, ValueError, AttributeError):
            return [
                "MS", "Master's", "Masters", "M.S.", "MBA", "MEng", "M.Eng",
                "MEM", "Master of Science", "Master of Engineering",
                "Master of Business Administration", "Master's student",
                "Master's candidate", "MS student", "Graduate student", "Postgraduate",
            ]

    @property
    def has_credentials(self) -> bool:
        """True if both email and password are present in the environment."""
        return bool(self.linkedin_email and self.linkedin_password)

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-style attribute access for compatibility."""
        return getattr(self, key, default)


# Module-level singleton — created lazily on first import by calling load()
_config_instance: AppConfig | None = None


def load() -> AppConfig:
    """
    Return the singleton AppConfig, creating it on first call.

    Usage::

        from src.config import load as load_config
        cfg = load_config()
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = AppConfig()
    return _config_instance
