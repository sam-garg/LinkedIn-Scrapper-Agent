# Reference Implementation Analysis

**File analysed:** `reference/linkedin_scraper_reference.py`  
**Analysis date:** 2026-08-19

---

## A. Features Worth Preserving

| Feature | Why it's valuable |
|---------|-------------------|
| `extract_email` — direct + obfuscated (`name at domain dot com`) | Captures a wider range of publicly visible emails than regex-only solutions |
| `extract_technologies` — keyword list matching | Simple and effective; using word-boundary matching prevents false positives |
| `extract_resume_links` — Google Drive, Dropbox, Notion, PDF patterns | Good multi-platform coverage |
| `extract_year` — prefers recent years, supports short form `'24` | Handles the variety of ways graduation years appear on LinkedIn |
| `verify_strict_postgrad` / `is_postgraduate` — phrase + pattern hybrid | More robust than a simple regex pattern alone |
| `extract_university` — whitelist → shortcodes → regex fallback | Three-tier approach balances precision (whitelist) with coverage (fallback) |
| `is_rate_limited` — checks both URL and body text | Covers the two main signals LinkedIn uses to indicate blocking |
| Deduplication from existing CSV before starting | Prevents redundant work on repeat runs |
| Persistent browser context (`launch_persistent_context`) | Correct approach for session reuse without storing credentials in code |
| `fetch_profile_posts` — activity page fallback for email | Genuinely useful; public emails often appear in posts rather than the main profile |
| Contact-info modal click before extracting contact fields | Opens more contact data than the main page body provides |

---

## B. Features That Should Be Redesigned

| Feature | Problem | Redesign |
|---------|---------|---------|
| `run_campaign` — single 400-line function | Monolithic; impossible to test individual parts | Split into `search.py`, `profile.py`, `filters.py`, `exporters.py` |
| Multi-account rotation | Violates LinkedIn's Terms of Service; creates legal and ethical risk | Removed entirely; single authenticated user session only |
| Hardcoded multi-query construction | Assumes email-hunting intent; not general-purpose | Single user-supplied query via `--query` flag |
| Global `US_UNIVERSITIES` loaded at module import | Crashes on startup if the JSON file is missing | Lazy load with graceful fallback in `config.py` |
| `print()` throughout | No log levels, no file output, cannot be captured by test runners | Replaced with Python `logging` module |
| No argparse / CLI | Script is run by editing `LEAD_COUNT` in `__main__` | Full `argparse` CLI with typed, documented flags |
| No type hints | Harder to understand and maintain | All functions annotated with Python 3.11 type hints |
| No tests | Cannot verify correctness without running against LinkedIn | Full `pytest` test suite for all pure functions |
| No data model | Profile fields scattered as dict keys | `ProfileData` dataclass with `to_dict()` |

---

## C. Fragile Selectors

The reference uses DOM selectors that are tightly coupled to LinkedIn's
current HTML structure. These change without notice.

| Selector | Risk | Mitigation in this implementation |
|----------|------|----------------------------------|
| `a#top-card-text-details-contact-info` | LinkedIn renames element IDs frequently | Wrapped in `try/except`; falls back to body text silently |
| `div[role='dialog']` | Generic role; could match any modal | Wrapped in `try/except`; falls back to body text |
| `button[aria-label='Dismiss']` | aria-label text changes with locale and LinkedIn updates | Wrapped in `try/except`; modal not being closed is non-fatal |

**Design principle:** Every selector-dependent call in `profile.py` is wrapped
in a `try/except` that degrades gracefully to `"N/A"` rather than crashing the
run.

---

## D. Hardcoded Configuration

| Hardcoded value | Location | Fixed by |
|----------------|----------|---------|
| `TECH_KEYWORDS` list in Python | Top of file | Moved to `config/settings.json` → `technology_keywords` |
| `UNIVERSITIES_JSON_PATH = "us_universities.json"` | Top of file | `config/settings.json` → `paths.universities_json` |
| `output_file = "campaign_results.csv"` | `run_campaign` arg | `config/settings.json` → `paths.output_csv` |
| `ACCOUNTS_JSON_PATH = "accounts.json"` | Top of file | Removed (accounts.json concept eliminated) |
| `LEAD_COUNT = 10` in `__main__` | Bottom of file | `--limit` CLI flag + `DEFAULT_LIMIT` env var |
| `headless=False` | `launch_persistent_context` call | `SCRAPER_HEADLESS` env var |

---

## E. Security Problems

| Problem | Risk level | Action taken |
|---------|-----------|-------------|
| `li_at` cookie injection from `accounts.json` | **Critical** — equivalent to stolen session authentication | Removed entirely. The tool only uses a session that the user themselves created by logging in. |
| `username` / `password` stored in `accounts.json` | **Critical** — credentials at rest in a local file | Removed entirely. Login is always manual. |
| Automated credential login (`page.fill("input#username", ...)`) | **High** — automates authentication, bypasses 2FA, violates ToS | Removed entirely. |
| Multi-account rotation | **High** — ToS violation, risk of all accounts being banned | Removed entirely. |

---

## F. Maintainability Problems

| Problem | Impact | Fixed by |
|---------|--------|---------|
| 400-line single-file implementation | Cannot test individual modules; changes in one area break unrelated features | Split into 12 focused modules |
| Global mutable state (`account_idx`, `US_UNIVERSITIES`) | Race conditions if ever parallelised; obscures data flow | State is local to function scope or encapsulated in `AppConfig` |
| `print()` instead of `logging` | Cannot redirect, filter by level, or write to file | `logging` module with file + console handlers |
| No custom exceptions | All errors fall through as generic `Exception` | 12-class exception hierarchy in `exceptions.py` |
| No `requirements.txt` | Dependency versions unknown | Pinned `requirements.txt` |
| No `README` or documentation | User must read 400 lines to understand how to run it | Full README with installation, CLI reference, and architecture diagram |

---

## G. Components That Became Separate Modules

| Reference code section | New module |
|------------------------|-----------|
| `load_accounts`, `launch_account_context`, `check_login_status` | `src/browser.py` |
| `is_rate_limited` | `src/linkedin.py` |
| Search URL construction + link collection loop | `src/search.py` |
| `extract_name`, `extract_email`, `extract_contact`, `extract_technologies`, `extract_resume_links`, `extract_visa`, `extract_year`, `extract_university`, `extract_summary` | `src/extractors.py` |
| `verify_strict_postgrad`, university whitelist matching | `src/filters.py` |
| `fetch_profile_posts`, profile scraping loop body | `src/profile.py` |
| Profile dict → CSV row | `src/exporters.py` |
| `load_us_universities`, `load_accounts`, settings | `src/config.py` |
| — (absent in reference) | `src/models.py` (ProfileData dataclass) |
| — (absent in reference) | `src/exceptions.py` (custom exception hierarchy) |
| — (absent in reference) | `src/utils.py` (URL normalisation, dedup, logging setup) |
| `__main__` block | `src/main.py` (full argparse CLI) |
