"""
profile.py
----------
Profile-page scraping orchestration.

This module ties together:
- Playwright page navigation
- LinkedIn restriction detection
- Field extractors (extractors.py)
- Activity/posts page fallback for email discovery

It does NOT filter results — filtering is the responsibility of filters.py.

Notes on fragile selectors
--------------------------
LinkedIn frequently changes its DOM structure.  This module wraps every
selector-dependent call in try/except blocks so that a missing selector
degrades gracefully to "N/A" rather than crashing the run.

The selectors used here were valid at the time of writing:
  - ``a#top-card-text-details-contact-info``   (contact info modal trigger)
  - ``div[role='dialog']``                     (contact info modal)
  - ``button[aria-label='Dismiss']``           (close button)

If LinkedIn changes these, the extractor will silently fall back to
extracting contact info from the main page body text only.
"""

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

from playwright.sync_api import Page

from src.exceptions import NavigationError, PageNotFoundError
from src.extractors import (
    extract_company,
    extract_degree,
    extract_education_records,
    extract_email,
    extract_graduation_year,
    extract_job_title,
    extract_location,
    extract_name,
    extract_phone,
    extract_resume_links,
    extract_summary,
    extract_technologies,
    extract_university,
)
from src.linkedin import detect_linkedin_restriction
from src.models import ProfileData
from src.utils import human_delay

if TYPE_CHECKING:
    from src.config import AppConfig

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Contact-info modal
# ------------------------------------------------------------------ #

def _try_open_contact_modal(page: Page) -> str:
    """
    Attempt to open LinkedIn's contact-info modal and return its text.

    This modal sometimes contains a visible email or phone not present
    in the main page body.

    If any step fails (selector changed, modal missing, etc.) the function
    returns an empty string silently — the caller falls back to body text.

    Args:
        page: Active Playwright page on a profile URL.

    Returns:
        Text content of the contact dialog, or empty string.
    """
    try:
        contact_link = page.locator("a#top-card-text-details-contact-info")
        if contact_link.count() == 0:
            return ""
        contact_link.click()
        page.wait_for_timeout(2_000)
        dialog = page.locator("div[role='dialog']")
        if dialog.count() == 0:
            return ""
        text = dialog.inner_text()
        # Close the modal
        try:
            close_btn = page.locator("button[aria-label='Dismiss']")
            if close_btn.count() > 0:
                close_btn.click()
                page.wait_for_timeout(800)
        except Exception:
            pass
        return text
    except Exception as exc:
        logger.debug("Contact modal not available: %s", exc)
        return ""


# ------------------------------------------------------------------ #
# Activity / posts page
# ------------------------------------------------------------------ #

def _fetch_activity_text(page: Page, profile_url: str, cfg: "AppConfig") -> str:
    """
    Navigate to the profile's public activity/posts page and return its text.

    Used as a fallback when the main profile page does not contain a visible
    email address.  We only read publicly accessible content.

    Args:
        page:        Active Playwright page.
        profile_url: Canonical profile URL.
        cfg:         Application configuration.

    Returns:
        Text content of the activity page (up to 2000 chars), or empty string.
    """
    activity_url = profile_url.rstrip("/") + "/recent-activity/all/"
    logger.debug("Fetching activity page: %s", activity_url)
    try:
        page.goto(
            activity_url,
            wait_until="domcontentloaded",
            timeout=cfg.navigation_timeout_ms,
        )
        human_delay(1.5, 3.0)

        # Light scroll to load a few posts
        for _ in range(3):
            page.evaluate("window.scrollBy(0, 600);")
            human_delay(0.4, 0.9)

        # Detect restriction before reading
        detect_linkedin_restriction(page, cfg)

        text = page.inner_text("body")
        clean = re.sub(r"\s+", " ", text).strip()
        return clean[:2_000]
    except Exception as exc:
        logger.debug("Could not fetch activity page %s: %s", activity_url, exc)
        return ""


# ------------------------------------------------------------------ #
# Main scroll helper
# ------------------------------------------------------------------ #

def _scroll_profile_page(page: Page, cfg: "AppConfig") -> None:
    """Scroll the profile page in steps to trigger lazy-loaded sections."""
    try:
        total_height = page.evaluate("document.body.scrollHeight")
        step = max(total_height // max(cfg.scroll_steps, 1), 300)
        for i in range(1, cfg.scroll_steps + 1):
            page.evaluate(f"window.scrollTo(0, {step * i});")
            if getattr(cfg, "safe_mode", False):
                human_delay(cfg.min_action_delay, cfg.max_action_delay)
            else:
                human_delay(0.4, 1.0)
        # Scroll back up slightly to trigger any sticky-header content
        page.evaluate("window.scrollTo(0, 0);")
        if getattr(cfg, "safe_mode", False):
            human_delay(cfg.min_action_delay, cfg.max_action_delay)
        else:
            human_delay(0.3, 0.7)
    except Exception as exc:
        logger.debug("Scroll error (non-fatal): %s", exc)


# ------------------------------------------------------------------ #
# Education section text
# ------------------------------------------------------------------ #

def _extract_education_text(page_text: str) -> str:
    """
    Try to pull the raw education section text (truncated for the CSV).

    Returns up to 300 chars of the section starting at "Education".
    """
    match = re.search(r"Education\s*\n([\s\S]{10,300})", page_text, re.IGNORECASE)
    if match:
        raw = re.sub(r"\s+", " ", match.group(1)).strip()
        return raw[:300]
    return "N/A"


# ------------------------------------------------------------------ #
# Public entry point
# ------------------------------------------------------------------ #

def scrape_profile(
    page: Page,
    cfg: "AppConfig",
    url: str,
    include_posts: bool = False,
) -> ProfileData:
    """
    Scrape a single LinkedIn profile and return a populated ProfileData.

    Workflow:
    1. Navigate to the profile URL.
    2. Detect LinkedIn restrictions (raises if blocked).
    3. Scroll the page to load lazy sections.
    4. Attempt to open the contact-info modal.
    5. Extract all fields using extractor functions.
    6. If email is still missing and ``include_posts`` is True, fetch the
       activity page for a possible email in public posts.

    Args:
        page:          Active Playwright page (must be authenticated).
        cfg:           Application configuration.
        url:           Canonical profile URL.
        include_posts: If True, also visit the public activity page.

    Returns:
        Populated ProfileData instance.

    Raises:
        LoginRequiredError:  If LinkedIn demands authentication.
        CheckpointError:     If a security challenge is encountered.
        RateLimitError:      If LinkedIn enforces a rate limit.
        PageNotFoundError:   If the profile returns a 404-equivalent page.
        NavigationError:     If Playwright cannot navigate to the URL.
    """
    logger.info("Scraping profile: %s", url)

    # ---- Navigate ----
    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=cfg.navigation_timeout_ms,
        )
    except Exception as exc:
        raise NavigationError(f"Cannot navigate to {url}: {exc}") from exc

    if getattr(cfg, "safe_mode", False):
        human_delay(cfg.min_action_delay, cfg.max_action_delay)
    else:
        human_delay(cfg.delay_min_sec, cfg.delay_max_sec)

    # ---- Restriction check ----
    detect_linkedin_restriction(page, cfg)

    # Check for "Profile Not Found" or private profile messages
    try:
        body_preview = page.inner_text("body")[:500].lower()
        if any(p in body_preview for p in (
            "page not found", "this profile is not available",
            "no longer available", "profile doesn't exist",
        )):
            raise PageNotFoundError(f"Profile not available: {url}")
    except (PageNotFoundError, Exception):
        # Re-raise PageNotFoundError; swallow others
        raise

    # ---- Scroll ----
    _scroll_profile_page(page, cfg)

    # ---- Attempt contact-info modal ----
    contact_modal_text = "" if getattr(cfg, "safe_mode", False) else _try_open_contact_modal(page)

    # ---- Full page text ----
    try:
        page_text = page.inner_text("body")
    except Exception as exc:
        raise NavigationError(f"Cannot read page text for {url}: {exc}") from exc

    # Combine main page text with modal text for extraction
    combined_text = page_text + "\n" + contact_modal_text

    # ---- Extract fields ----
    name = extract_name(url, page_text)
    headline_match = re.search(
        r"^.+\n(.{10,200}?)(?:\n|$)",
        page_text.strip(),
        re.MULTILINE,
    )
    headline = headline_match.group(1).strip() if headline_match else "N/A"

    email = extract_email(combined_text)
    phone = extract_phone(combined_text)
    location = extract_location(page_text)
    company = extract_company(page_text)
    job_title = extract_job_title(page_text)
    education_text = _extract_education_text(page_text)
    education_records = extract_education_records(page_text, cfg.universities)
    university = extract_university(page_text, cfg.universities)
    degree = extract_degree(page_text)
    grad_year = extract_graduation_year(page_text)
    technologies = extract_technologies(combined_text, cfg.technology_keywords)
    resume = extract_resume_links(combined_text)
    summary = extract_summary(page_text)

    # ---- Activity / posts fallback ----
    posts_text = "N/A"
    if include_posts:
        logger.debug(
            "Fetching activity page (include_posts=%s, email missing=%s)",
            include_posts, email == "N/A",
        )
        activity_text = _fetch_activity_text(page, url, cfg)
        if activity_text:
            # Try to find email in posts
            if email == "N/A":
                post_email = extract_email(activity_text)
                if post_email != "N/A":
                    logger.info(
                        "Email found in public posts for %s: %s",
                        url, post_email,
                    )
                    email = post_email
            if include_posts:
                clean = re.sub(r"\s+", " ", activity_text).strip()
                posts_text = clean[:500] + "…" if len(clean) > 500 else clean

    profile = ProfileData(
        name=name,
        linkedin_url=url,
        headline=headline,
        summary=summary,
        location=location,
        company=company,
        job_title=job_title,
        education=education_text,
        education_records=education_records,
        university=university,
        degree=degree,
        graduation_year=grad_year,
        source_text=combined_text,
        technology=technologies,
        contact=phone,
        email=email,
        resume=resume,
        posts=posts_text,
        scraped_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    logger.info(
        "Profile extracted: %s | uni=%s | degree=%s | email=%s",
        profile.name, profile.university, profile.degree, profile.email,
    )
    return profile
