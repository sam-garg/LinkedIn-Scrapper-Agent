"""
search.py
---------
LinkedIn people-search: URL construction and profile URL discovery.

Workflow
--------
1. Build a LinkedIn people-search URL from a keyword query and optional filters.
2. Navigate to each search-results page using Playwright.
3. For each result card on the page:
   - Extract the profile URL (/in/...)
   - Optionally extract lightweight card-visible fields (name, headline, location)
     WITHOUT navigating to the profile page.
4. Normalise and deduplicate URLs.
5. Stop when the requested number of profiles has been collected or all
   search pages have been exhausted.

Important
---------
- Profile pages are NEVER visited. Only search-result pages are loaded.
- The ``limit`` parameter is passed through exactly as given by the caller —
  there is no hidden internal cap.
- If a login wall, checkpoint, or rate-limit is detected on any search page,
  the function raises the appropriate exception so the caller can save data
  and stop cleanly.
"""

import logging
import math
import urllib.parse
from datetime import datetime
from typing import TYPE_CHECKING

from playwright.sync_api import Page

from src.exceptions import NavigationError
from src.linkedin import detect_linkedin_restriction
from src.models import DiscoveredProfile
from src.utils import deduplicate_urls, human_delay, is_profile_url, normalize_linkedin_url

if TYPE_CHECKING:
    from src.config import AppConfig

logger = logging.getLogger(__name__)

_SEARCH_BASE = "https://www.linkedin.com/search/results/people/"

# LinkedIn search result card selectors.
# These are tried in order; the first match wins.  They degrade gracefully
# to "N/A" if LinkedIn changes the DOM structure.
_CARD_SELECTORS = {
    "name": [
        ".entity-result__title-text a span[aria-hidden='true']",
        ".entity-result__title-text span[aria-hidden='true']",
        ".entity-result__title a span",
        ".artdeco-entity-lockup__title span[aria-hidden='true']",
    ],
    "headline": [
        ".entity-result__primary-subtitle",
        ".entity-result__summary",
        ".artdeco-entity-lockup__subtitle",
    ],
    "location": [
        ".entity-result__secondary-subtitle",
        ".artdeco-entity-lockup__caption",
    ],
}


def build_search_url(
    query: str,
    page_num: int = 1,
    location: str | None = None,
) -> str:
    """
    Construct a LinkedIn people-search URL.

    Args:
        query:    Keyword search string.
        page_num: Result page number (1-indexed).
        location: Optional geographic filter (e.g. "United States").

    Returns:
        Fully-encoded LinkedIn search URL string.
    """
    keywords = f"{query} {location}".strip() if location else query
    params: dict[str, str] = {
        "keywords": keywords,
        "origin": "GLOBAL_SEARCH_HEADER",
    }
    if page_num > 1:
        params["page"] = str(page_num)

    return _SEARCH_BASE + "?" + urllib.parse.urlencode(params)


def _scroll_search_page(page: Page, steps: int) -> None:
    """Scroll the search results page to trigger lazy-loaded content."""
    for _ in range(steps):
        page.evaluate("window.scrollBy(0, 500);")
        human_delay(0.4, 0.9)


def _safe_text(page: Page, selectors: list[str]) -> str:
    """
    Try each selector in order and return the first non-empty text found.

    Returns "N/A" if no selector matches or the element has no text.
    """
    for sel in selectors:
        try:
            locator = page.locator(sel).first
            if locator.count() > 0:
                text = locator.inner_text(timeout=1_000).strip()
                if text:
                    return text
        except Exception:
            continue
    return "N/A"


def _collect_profiles_from_page(
    page: Page,
    query: str,
) -> list[DiscoveredProfile]:
    """
    Extract DiscoveredProfile objects from all result cards on the current page.

    For each card:
    - The profile URL is extracted from the anchor href (required).
    - Name, headline, and location are extracted from card elements if available.
    - No profile page is visited.

    Args:
        page:  Current Playwright page (a search results page).
        query: The search query that produced these results (stored for provenance).

    Returns:
        List of DiscoveredProfile objects found on the page.
        Non-profile URLs are silently skipped.
    """
    profiles: list[DiscoveredProfile] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Find all result card containers first, so we can scope selectors per card
        cards = page.locator("li.reusable-search__result-container").all()
        if not cards:
            # Fallback: grab all /in/ links if the card selector doesn't match
            cards = []
    except Exception as exc:
        logger.debug("Could not locate result cards: %s", exc)
        cards = []

    if cards:
        # Per-card extraction: scoped to each card container
        for card in cards:
            try:
                # Get the profile link from this card
                link = card.locator('a[href*="/in/"]').first
                href = link.get_attribute("href", timeout=1_000)
                if not href:
                    continue
                if href.startswith("/"):
                    href = "https://www.linkedin.com" + href
                norm_url = normalize_linkedin_url(href)
                if not is_profile_url(norm_url):
                    continue

                # Extract card-visible fields (graceful fallback to "N/A")
                name = _extract_card_text(card, _CARD_SELECTORS["name"])
                headline = _extract_card_text(card, _CARD_SELECTORS["headline"])
                location = _extract_card_text(card, _CARD_SELECTORS["location"])

                profiles.append(DiscoveredProfile(
                    linkedin_url=norm_url,
                    name=name,
                    headline=headline,
                    location=location,
                    search_query=query,
                    scraped_at=now,
                ))
            except Exception as exc:
                logger.debug("Error extracting card: %s", exc)
                continue
    else:
        # Fallback: collect bare URLs only (no card-level data)
        try:
            links = page.locator('a[href*="/in/"]').all()
        except Exception as exc:
            logger.warning("Could not query profile links: %s", exc)
            return profiles

        for link in links:
            try:
                href = link.get_attribute("href", timeout=500)
            except Exception:
                continue
            if not href:
                continue
            if href.startswith("/"):
                href = "https://www.linkedin.com" + href
            norm_url = normalize_linkedin_url(href)
            if is_profile_url(norm_url):
                profiles.append(DiscoveredProfile(
                    linkedin_url=norm_url,
                    name="N/A",
                    headline="N/A",
                    location="N/A",
                    search_query=query,
                    scraped_at=now,
                ))

    return profiles


def _extract_card_text(card, selectors: list[str]) -> str:
    """
    Try each selector scoped to a card element; return first non-empty text.

    Returns "N/A" on any failure.
    """
    for sel in selectors:
        try:
            el = card.locator(sel).first
            if el.count() > 0:
                text = el.inner_text(timeout=500).strip()
                if text:
                    return text
        except Exception:
            continue
    return "N/A"


def collect_profile_urls(
    page: Page,
    cfg: "AppConfig",
    query: str | list[str],
    limit: int,
    location: str | None = None,
    seen_urls: set[str] | None = None,
) -> list[DiscoveredProfile]:
    """
    Search LinkedIn and collect up to *limit* unique profile URLs.

    Iterates through search result pages until *limit* new URLs are collected
    or no more results are available.  Profile pages are NEVER visited.

    The ``limit`` parameter is honoured exactly — there is no hidden internal cap.

    Args:
        page:      Active Playwright page (must be authenticated).
        cfg:       Application configuration.
        query:     Search keyword(s) — string or list of strings.
        limit:     Maximum number of new profile URLs to return.
        location:  Optional location filter.
        seen_urls: Set of already-collected URLs to skip (cross-run dedup).

    Returns:
        Ordered list of unique DiscoveredProfile objects (up to *limit*).

    Raises:
        LoginRequiredError:  If LinkedIn demands authentication.
        CheckpointError:     If a security challenge is encountered.
        RateLimitError:      If LinkedIn enforces a rate limit.
        NavigationError:     If page navigation fails.
    """
    if seen_urls is None:
        seen_urls = set()

    queries = [query] if isinstance(query, str) else [q for q in query if q.strip()]
    collected: list[DiscoveredProfile] = []
    collected_urls: set[str] = set()   # fast membership check
    max_pages = cfg.search_page_max

    # Distribute the limit evenly across queries but always collect up to limit total
    per_query_limit = max(1, math.ceil(limit / len(queries))) if len(queries) > 1 else limit

    for query_text in queries:
        if len(collected) >= limit:
            break

        query_collected = 0
        logger.info(
            "Searching LinkedIn: query='%s' limit=%d location=%s",
            query_text, limit, location or "any",
        )

        for page_num in range(1, max_pages + 1):
            if len(collected) >= limit or query_collected >= per_query_limit:
                break

            search_url = build_search_url(query_text, page_num=page_num, location=location)
            logger.info(
                "Fetching search page %d for query '%s': %s",
                page_num, query_text, search_url,
            )

            try:
                page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=cfg.navigation_timeout_ms,
                )
            except Exception as exc:
                raise NavigationError(
                    f"Failed to navigate to search page {page_num}: {exc}"
                ) from exc

            # Conservative pacing between search pages
            if cfg.safe_mode:
                human_delay(cfg.min_action_delay, cfg.max_action_delay)
            else:
                human_delay(cfg.delay_min_sec, cfg.delay_max_sec)

            # Detect any LinkedIn restrictions before processing results
            detect_linkedin_restriction(page, cfg)

            # Scroll to load lazy content
            _scroll_search_page(page, cfg.scroll_steps)

            # Collect profiles from this page
            page_profiles = _collect_profiles_from_page(page, query_text)

            # Deduplicate against already-seen + already-collected this run
            combined_seen = seen_urls | collected_urls
            new_profiles: list[DiscoveredProfile] = []
            for p in page_profiles:
                if p.linkedin_url not in combined_seen:
                    new_profiles.append(p)
                    combined_seen.add(p.linkedin_url)

            if not new_profiles:
                logger.info(
                    "Query '%s': no new profiles on page %d; stopping pagination.",
                    query_text, page_num,
                )
                break

            # Take only what we still need
            remaining = min(limit - len(collected), per_query_limit - query_collected)
            batch = new_profiles[:remaining]
            collected.extend(batch)
            for p in batch:
                collected_urls.add(p.linkedin_url)
            query_collected += len(batch)

            logger.info(
                "Query '%s': +%d new profiles (total: %d/%d)",
                query_text, len(batch), len(collected), limit,
            )

    logger.info("Search complete. Collected %d profile URLs.", len(collected))
    return collected
