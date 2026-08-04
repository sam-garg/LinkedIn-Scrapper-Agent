"""Turn raw LinkedIn result-card text into structured student records via Gemini."""

from __future__ import annotations

import json
import re

import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

from config import GEMINI_API_KEY, GEMINI_MODEL

genai.configure(api_key=GEMINI_API_KEY)

_PROMPT = """You are parsing scraped LinkedIn people-search result cards.

For each distinct person in the input, output an object with:
  full_name  - the person's name, or null
  headline   - their headline / current role line, or null
  location   - their location line, or null
  profile_url - their linkedin.com/in/... URL

Rules:
- Only include people who plausibly study or studied at: {university}
- These names/abbreviations all refer to the SAME university, treat them as equivalent: {aliases}
- Never invent a profile_url. Only use URLs present in the input.
- Skip entries with no profile_url.
- Return ONLY a JSON array. No prose, no markdown fences.

INPUT:
{blob}
"""

_URL_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[^\s\"'?)]+", re.I)


def _clean_url(url: str) -> str:
    url = url.split("?")[0].rstrip("/")
    return url.replace("http://", "https://")


def _fallback(blob: str) -> list[dict]:
    """Regex-only extraction if Gemini fails or is rate limited."""
    seen, out = set(), []
    for match in _URL_RE.findall(blob):
        url = _clean_url(match)
        if url not in seen:
            seen.add(url)
            out.append({"full_name": None, "headline": None, "location": None, "profile_url": url})
    return out


def _parse_json(text: str) -> list[dict]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    data = json.loads(text[start : end + 1])
    return [d for d in data if isinstance(d, dict)]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
def _call_gemini(prompt: str) -> str:
    model = genai.GenerativeModel(GEMINI_MODEL)
    response = model.generate_content(
        prompt,
        generation_config={"temperature": 0.1, "response_mime_type": "application/json"},
    )
    return response.text or ""


def extract_students(blob: str, university: str, aliases: list[str] | None = None) -> list[dict]:
    if not blob.strip():
        return []

    alias_text = ", ".join(aliases) if aliases else university
    try:
        raw = _call_gemini(
            _PROMPT.format(university=university, aliases=alias_text, blob=blob[:60000])
        )
        records = _parse_json(raw)
    except Exception as exc:  # rate limit, bad JSON, network
        print(f"    [gemini] falling back to regex extraction: {exc}")
        return _fallback(blob)

    if not records:
        return _fallback(blob)

    cleaned, seen = [], set()
    for r in records:
        url = (r.get("profile_url") or "").strip()
        if not url or "linkedin.com/in/" not in url:
            continue
        url = _clean_url(url)
        if url in seen:
            continue
        seen.add(url)
        cleaned.append(
            {
                "full_name": r.get("full_name") or None,
                "headline": r.get("headline") or None,
                "location": r.get("location") or None,
                "profile_url": url,
            }
        )
    return cleaned or _fallback(blob)
