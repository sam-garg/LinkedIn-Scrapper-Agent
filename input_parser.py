"""Parse the university list from a JSON or PDF file.

JSON is accepted in any of these shapes:
    ["MIT", "IIT Delhi"]
    [{"name": "MIT", "country": "USA"}, ...]
    {"universities": [ ... ]}

PDF: every non-empty line that looks like a university name is taken.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

NAME_KEYS = ("name", "university", "university_name", "college", "school", "institution")
COUNTRY_KEYS = ("country", "location", "region")
ALIAS_KEYS = ("aliases", "alias", "short_names", "abbreviations")

# Lines that are page numbers, headers, bullets-only, etc.
_NOISE = re.compile(r"^(page\s*\d+|\d+|[-•*\s]+)$", re.IGNORECASE)
_LEADING_BULLET = re.compile(r"^\s*(?:[-•*]|\d+[.)])\s*")


def _pick(d: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        for actual in d:
            if actual.lower().strip() == k and d[actual]:
                return str(d[actual]).strip()
    return None


def _pick_list(d: dict, keys: tuple[str, ...]) -> list[str]:
    for k in keys:
        for actual in d:
            if actual.lower().strip() == k and d[actual]:
                value = d[actual]
                if isinstance(value, str):
                    value = [v for v in re.split(r"[,;|]", value)]
                if isinstance(value, list):
                    return [str(v).strip() for v in value if str(v).strip()]
    return []


def _from_json(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(raw, dict):
        for key in ("universities", "data", "items", "results", "records"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
        else:
            raw = [raw]

    out: list[dict] = []
    for entry in raw:
        if isinstance(entry, str):
            name, country, aliases = entry.strip(), None, []
        elif isinstance(entry, dict):
            name = _pick(entry, NAME_KEYS)
            country = _pick(entry, COUNTRY_KEYS)
            aliases = _pick_list(entry, ALIAS_KEYS)
        else:
            continue
        if name:
            out.append(
                {
                    "name": name,
                    "country": country,
                    "aliases": aliases,
                    "source_ref": path.name,
                }
            )
    return out



def _from_pdf(path: Path) -> list[dict]:
    import pdfplumber

    out: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                line = _LEADING_BULLET.sub("", line).strip()
                if not line or _NOISE.match(line) or len(line) < 4:
                    continue
                out.append(
                    {"name": line, "country": None, "aliases": [], "source_ref": path.name}
                )
    return out


def load_universities(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    suffix = path.suffix.lower()
    if suffix == ".json":
        items = _from_json(path)
    elif suffix == ".pdf":
        items = _from_pdf(path)
    else:
        raise ValueError(f"Unsupported input file type: {suffix} (use .json or .pdf)")

    # Dedupe, preserving order.
    seen: set[str] = set()
    unique: list[dict] = []
    for item in items:
        key = item["name"].casefold()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
