"""Central config loaded from .env."""

import os
from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default or "")
    if required and not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


LINKEDIN_EMAIL = _get("LINKEDIN_EMAIL", required=False)
LINKEDIN_PASSWORD = _get("LINKEDIN_PASSWORD", required=False)

GEMINI_API_KEY = _get("GEMINI_API_KEY", required=True)
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-2.0-flash")

SUPABASE_URL = _get("SUPABASE_URL", required=True)
SUPABASE_SERVICE_KEY = _get("SUPABASE_SERVICE_KEY", required=True)

HEADLESS = _get("HEADLESS", "false").lower() == "true"
MAX_PAGES_PER_UNIVERSITY = int(_get("MAX_PAGES_PER_UNIVERSITY", "5"))
MIN_DELAY = float(_get("MIN_DELAY", "2.5"))
MAX_DELAY = float(_get("MAX_DELAY", "6.0"))
STORAGE_STATE = _get("STORAGE_STATE", "storage_state.json")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)