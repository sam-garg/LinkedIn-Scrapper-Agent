#!/usr/bin/env python3

# Please God Make This Work #
"""
Filter Indian students doing PG abroad (PG completion 2024-2028).

Flow
----
1. Read linkedin_urls.json
2. Open each LinkedIn profile with Playwright Chromium (no login)
3. Scrape ONLY the Education section
4. Send just that education text to Gemini 2.5 Flash -> UG / PG / PG year
5. Keep profile if: UG is Indian (clean_indian_universities.json)
                   AND PG is international
                   AND 2024 <= PG year <= 2028
6. Write indian_students_urls.json

Usage
-----
    pip install -r requirements.txt
    playwright install chromium
    export LOVABLE_API_KEY=...        # or GEMINI_API_KEY=...
    python filter_pg_students.py \
        --urls ../../data/linkedin_urls.json \
        --indian ../../data/clean_indian_universities.json \
        --out ../../data/indian_students_urls.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
from playwright.async_api import Browser, async_playwright

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

MODEL = "google/gemini-2.5-flash"
LOVABLE_GATEWAY = "https://ai.gateway.lovable.dev/v1/chat/completions"
GEMINI_DIRECT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

PG_YEAR_MIN = 2024
PG_YEAR_MAX = 2028

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Words that indicate a postgraduate degree (used as a sanity check on Gemini)
PG_HINTS = (
    "master", "msc", "m.sc", "ms ", "m.s.", "mba", "m.b.a", "meng", "m.eng",
    "mtech", "m.tech", "ma ", "m.a.", "mim", "mfin", "llm", "mph", "mps",
    "postgraduate", "post graduate", "pg diploma", "pgdm",
)

INDIA_TOKENS = ("india", "indian", "bharat", "iit", "nit", "iiit", "iim")


def load_dotenv(path: str | Path = ".env") -> None:
    path = Path(path)
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ[key] = value


load_dotenv()

Li_AT = os.environ.get("li_at")

# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def norm(text: str) -> str:
    """Lowercase, strip accents/punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


STOPWORDS = {
    "university", "univ", "college", "institute", "institution", "school",
    "of", "the", "and", "for", "technology", "tech", "science", "sciences",
    "engineering", "management", "studies", "national", "international",
    "deemed", "be", "a", "at", "in",
}


def tokens(name: str) -> set[str]:
    return {t for t in norm(name).split() if t and t not in STOPWORDS}


@dataclass
class EducationEntry:
    school: str = ""
    degree: str = ""
    start_year: int | None = None
    end_year: int | None = None

    def as_text(self) -> str:
        span = ""
        if self.start_year or self.end_year:
            span = f" ({self.start_year or '?'} - {self.end_year or '?'})"
        return f"- School: {self.school} | Degree: {self.degree}{span}"


@dataclass
class ProfileResult:
    url: str
    status: str  # selected | rejected | skipped | error
    reason: str = ""
    ug_university: str | None = None
    pg_university: str | None = None
    pg_year: int | None = None
    education: list[EducationEntry] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Indian university database
# --------------------------------------------------------------------------- #


class IndianUniversityIndex:
    """Fuzzy-ish matcher over clean_indian_universities.json."""

    def __init__(self, names: list[str]) -> None:
        self.names = [n for n in names if n and n.strip()]
        self.exact = {norm(n) for n in self.names}
        self.token_sets = [(n, tokens(n)) for n in self.names]

    @classmethod
    def load(cls, path: Path) -> "IndianUniversityIndex":
        raw = json.loads(path.read_text(encoding="utf-8"))
        names = []
        if isinstance(raw, dict):
            if "universities" in raw:
                raw = raw["universities"]
            elif "data" in raw:
                raw = raw["data"]
            else:
            # Handle state-wise format
                for value in raw.values():
                    if isinstance(value, list):
                        names.extend(value)
                return cls(names)
        for item in raw:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                for key in ("name", "university", "college", "institute", "title"):
                    if item.get(key):
                        names.append(str(item[key]))
                        break
        if not names:
            raise ValueError(f"No university names found in {path}")
        return cls(names)

    def is_indian(self, school: str) -> bool:
        if not school:
            return False
        n = norm(school)
        if not n:
            return False
        if n in self.exact:
            return True
        # substring match either direction (handles campus suffixes)
        for known in self.exact:
            if len(known) >= 8 and (known in n or n in known):
                return True
        # token overlap >= 70% of the shorter name
        st = tokens(school)
        if st:
            for _, kt in self.token_sets:
                if not kt:
                    continue
                overlap = len(st & kt)
                if overlap and overlap / min(len(st), len(kt)) >= 0.7:
                    return True
        # last resort: explicit India signals
        return any(tok in f" {n} " for tok in INDIA_TOKENS)


# --------------------------------------------------------------------------- #
# Step 2 + 3: Playwright scrape of the Education section only
# --------------------------------------------------------------------------- #

YEAR_RE = re.compile(r"(19|20)\d{2}")

SCRAPE_JS = r"""
() => {
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();

  // De-duplicate LinkedIn's visually-hidden / aria duplicated spans.
  const textOf = (el) => {
    if (!el) return "";
    const vis = el.querySelector('span[aria-hidden="true"]');
    return clean(vis ? vis.textContent : el.textContent);
  };

  const collect = (items) => items.map((li) => {
    const school = textOf(li.querySelector(
      '.t-bold, h3, .pv-entity__school-name, [data-field="school_name"]'
    ));
    const subs = Array.from(li.querySelectorAll('.t-14, .pv-entity__degree-name, .pv-entity__dates, span'))
      .map(textOf).filter(Boolean);
    const uniq = [...new Set(subs)].filter((t) => t !== school);
    const dateLine = uniq.find((t) => /(19|20)\d{2}/.test(t)) || "";
    const degreeLine = uniq.find((t) => t !== dateLine && t.length > 2) || "";
    return { school, degree: degreeLine, dates: dateLine, raw: [school, ...uniq].join(" | ") };
  }).filter((e) => e.school || e.degree);

  // 1) Authenticated / full profile layout
  let section = document.querySelector('#education')?.closest('section')
    || document.querySelector('section[data-section="educationsDetails"]')
    || Array.from(document.querySelectorAll('section')).find((s) =>
         /^education$/i.test(clean(s.querySelector('h2, h3')?.textContent || '')));
  if (section) {
    const items = Array.from(section.querySelectorAll('li'));
    const out = collect(items);
    if (out.length) return { source: 'section', entries: out };
  }

  // 2) Public guest layout
  const guest = Array.from(document.querySelectorAll('section.education, .education__list'));
  for (const g of guest) {
    const out = collect(Array.from(g.querySelectorAll('li')));
    if (out.length) return { source: 'guest', entries: out };
  }

  // 3) JSON-LD fallback (alumniOf)
  for (const s of Array.from(document.querySelectorAll('script[type="application/ld+json"]'))) {
    try {
      const data = JSON.parse(s.textContent);
      const graph = data['@graph'] || [data];
      for (const node of graph) {
        const alumni = node.alumniOf;
        if (Array.isArray(alumni) && alumni.length) {
          return {
            source: 'jsonld',
            entries: alumni.map((a) => ({
              school: clean(a.name || ''),
              degree: clean((a.description || a.programName || '')),
              dates: [a.startDate, a.endDate].filter(Boolean).join(' - '),
              raw: JSON.stringify(a),
            })),
          };
        }
      }
    } catch (_) { /* ignore */ }
  }

  return { source: 'none', entries: [] };
}
"""

AUTHWALL_MARKERS = (
    "authwall", "/login", "signup", "join now to see", "this page doesn",
    "profile not found",
)


def parse_years(dates: str) -> tuple[int | None, int | None]:
    years = [int(m.group(0)) for m in YEAR_RE.finditer(dates or "")]
    if not years:
        return None, None
    if len(years) == 1:
        return years[0], None
    return min(years), max(years)


async def scrape_education(browser: Browser, url: str, timeout_ms: int) -> tuple[list[EducationEntry], str]:
    """Returns (entries, skip_reason). skip_reason is '' when scraping succeeded."""
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 1800},
        locale="en-US",
    )
    if Li_AT:
        await context.add_cookies([
            {
                "name": "li_at",
                "value": Li_AT,
                "domain": ".linkedin.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
            }
    ])
    page = await context.new_page()
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        print(page.url)
        status = resp.status if resp else 0
        if status in (404, 410):
            return [], f"profile not found (HTTP {status})"
        if status in (401, 403, 429, 999):
            return [], f"blocked / private (HTTP {status})"

        await page.wait_for_timeout(1200)
        final_url = (page.url or "").lower()
        if any(m in final_url for m in ("authwall", "/login", "/signup", "/uas/")):
            return [], "redirected to auth wall (no login used)"

        # Public profiles collapse Education behind a "see more"-style link.
        try:
            await page.get_by_role("button", name=re.compile("show all|see more", re.I)).first.click(timeout=1500)
            await page.wait_for_timeout(600)
        except Exception:
            pass

        data: dict[str, Any] = await page.evaluate(SCRAPE_JS)
        raw_entries = data.get("entries") or []
        if not raw_entries:
            body = norm(await page.inner_text("body"))
            if any(m in body for m in AUTHWALL_MARKERS):
                return [], "private / inaccessible profile"
            return [], "education section missing"

        entries: list[EducationEntry] = []
        for e in raw_entries:
            start, end = parse_years(e.get("dates", ""))
            entries.append(
                EducationEntry(
                    school=(e.get("school") or "").strip(),
                    degree=(e.get("degree") or "").strip(),
                    start_year=start,
                    end_year=end,
                )
            )
        return entries, ""
    except Exception as exc:  # navigation timeout, DNS, etc.
        import traceback
        traceback.print_exc()
        return [], f"scrape failed: {type(exc).__name__}: {exc}"
    finally:
        await context.close()


# --------------------------------------------------------------------------- #
# Step 4: Gemini 2.5 Flash analysis (education data only)
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = (
    "You classify university education history. You are given ONLY the education "
    "entries of one person. Identify the undergraduate (Bachelor's) institution, "
    "the postgraduate (Master's / MS / MSc / MBA / MEng / MTech / LLM / PGDM) "
    "institution, and the year the postgraduate degree was (or will be) completed. "
    "Respond with JSON only, no prose."
)

JSON_SHAPE = """{
  "ug_university": string | null,
  "ug_degree": string | null,
  "pg_university": string | null,
  "pg_degree": string | null,
  "pg_end_year": number | null,
  "pg_country": string | null,
  "ug_country": string | null
}"""


def build_prompt(entries: list[EducationEntry]) -> str:
    block = "\n".join(e.as_text() for e in entries)
    return (
        f"Education entries:\n{block}\n\n"
        "Return exactly this JSON shape (use null when unknown):\n"
        f"{JSON_SHAPE}\n\n"
        "Rules: BTech/BE/BSc/BA/BBA/BCom/Bachelor => UG. "
        "MS/MSc/MBA/MEng/MTech/MA/LLM/PGDM/Master => PG. "
        "Ignore school/high-school/diploma-only and PhD entries. "
        "pg_end_year must be the graduation/expected graduation year as a 4-digit number. "
        "Give the country of each institution when you can infer it."
    )


def _extract_json(text: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("model returned no JSON")
    return json.loads(match.group(0))


def analyze_education(entries: list[EducationEntry]) -> dict[str, Any]:
    prompt = build_prompt(entries)
    lovable_key = os.environ.get("LOVABLE_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if lovable_key:
        resp = requests.post(
            LOVABLE_GATEWAY,
            headers={
                "Content-Type": "application/json",
                "Lovable-API-Key": lovable_key,
                "X-Lovable-AIG-SDK": "fetch",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=90,
        )
        if resp.status_code == 429:
            raise RuntimeError("rate limited (429) - slow down with --delay")
        if resp.status_code == 402:
            raise RuntimeError("AI credits exhausted (402)")
        resp.raise_for_status()
        return _extract_json(resp.json()["choices"][0]["message"]["content"])

    if gemini_key:
        resp = requests.post(
            GEMINI_DIRECT,
            headers={"Content-Type": "application/json", "x-goog-api-key": gemini_key},
            json={
                "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
            timeout=90,
        )
        resp.raise_for_status()
        parts = resp.json()["candidates"][0]["content"]["parts"]
        return _extract_json("".join(p.get("text", "") for p in parts))

    raise RuntimeError("Set LOVABLE_API_KEY (preferred) or GEMINI_API_KEY")


# --------------------------------------------------------------------------- #
# Step 5: filters
# --------------------------------------------------------------------------- #


def apply_filters(
    analysis: dict[str, Any],
    entries: list[EducationEntry],
    index: IndianUniversityIndex,
) -> tuple[bool, str]:
    ug = (analysis.get("ug_university") or "").strip()
    pg = (analysis.get("pg_university") or "").strip()
    pg_year = analysis.get("pg_end_year")

    if not ug:
        return False, "UG could not be identified"
    if not pg:
        return False, "PG could not be identified"

    # Fall back to scraped end years if the model omitted the PG year.
    if not isinstance(pg_year, int):
        try:
            pg_year = int(str(pg_year))
        except (TypeError, ValueError):
            pg_year = None
    if pg_year is None:
        for e in entries:
            if any(h in norm(e.degree) + " " for h in PG_HINTS) and e.end_year:
                pg_year = e.end_year
                break
    if pg_year is None:
        return False, "PG completion year missing"

    if not index.is_indian(ug):
        return False, f"UG not Indian ({ug})"
    if index.is_indian(pg) or "india" in norm(analysis.get("pg_country") or ""):
        return False, f"PG is not international ({pg})"
    if not (PG_YEAR_MIN <= pg_year <= PG_YEAR_MAX):
        return False, f"PG year {pg_year} outside {PG_YEAR_MIN}-{PG_YEAR_MAX}"

    return True, f"UG {ug} (IN) -> PG {pg} ({pg_year})"


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def load_urls(path: Path) -> list[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("urls") or raw.get("data") or []
    urls: list[str] = []
    for item in raw:
        if isinstance(item, str):
            urls.append(item.strip())
        elif isinstance(item, dict):
            for key in ("url", "link", "profile", "profile_url", "linkedin_url"):
                if item.get(key):
                    urls.append(str(item[key]).strip())
                    break
    seen, out = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def run(args: argparse.Namespace) -> int:
    urls = load_urls(Path(args.urls))
    index = IndianUniversityIndex.load(Path(args.indian))
    print(f"[init] {len(urls)} urls | {len(index.names)} Indian institutions", flush=True)

    results: list[ProfileResult] = []
    selected: list[dict[str, Any]] = []
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=args.headless)
        try:
            for i, url in enumerate(urls, start=1):
                print(f"[{i}/{len(urls)}] {url}", flush=True)

                entries, skip = await scrape_education(browser, url, args.timeout)
                if skip:
                    print(f"    skip: {skip}", flush=True)
                    results.append(ProfileResult(url, "skipped", skip))
                    await asyncio.sleep(args.delay)
                    continue

                try:
                    analysis = analyze_education(entries)
                except Exception as exc:
                    print(f"    error: gemini failed - {exc}", flush=True)
                    results.append(ProfileResult(url, "error", str(exc), education=entries))
                    await asyncio.sleep(args.delay)
                    continue

                ok, reason = apply_filters(analysis, entries, index)
                res = ProfileResult(
                    url=url,
                    status="selected" if ok else "rejected",
                    reason=reason,
                    ug_university=analysis.get("ug_university"),
                    pg_university=analysis.get("pg_university"),
                    pg_year=analysis.get("pg_end_year"),
                    education=entries,
                )
                results.append(res)
                print(f"    {'SELECTED' if ok else 'rejected'}: {reason}", flush=True)

                if ok:
                    selected.append({"id": len(selected) + 1, "url": url})
                    # Step 6: write incrementally so a crash never loses progress.
                    out_path.write_text(
                        json.dumps(selected, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )

                await asyncio.sleep(args.delay)
        finally:
            await browser.close()

    out_path.write_text(
        json.dumps(selected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    if args.report:
        Path(args.report).write_text(
            json.dumps(
                [
                    {
                        "url": r.url,
                        "status": r.status,
                        "reason": r.reason,
                        "ug_university": r.ug_university,
                        "pg_university": r.pg_university,
                        "pg_year": r.pg_year,
                        "education": [e.__dict__ for e in r.education],
                    }
                    for r in results
                ],
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    counts = {s: sum(1 for r in results if r.status == s) for s in
              ("selected", "rejected", "skipped", "error")}
    print(f"\n[done] {counts} -> {out_path}", flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--urls", default="data/linkedin_urls.json")
    p.add_argument("--indian", default="data/clean_indian_universities.json")
    p.add_argument("--out", default="data/indian_students_urls.json")
    p.add_argument("--report", default="", help="optional per-profile debug JSON")
    p.add_argument("--delay", type=float, default=3.0, help="seconds between profiles")
    p.add_argument("--timeout", type=int, default=30000, help="navigation timeout (ms)")
    p.add_argument("--headed", dest="headless", action="store_false")
    p.set_defaults(headless=True)
    args = p.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
