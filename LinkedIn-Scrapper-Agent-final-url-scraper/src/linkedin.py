"""
linkedin.py
-----------
LinkedIn-specific page state detection.

This module provides a single public function, ``detect_linkedin_restriction``,
which inspects the current page and raises an appropriate exception if LinkedIn
is blocking, rate-limiting, or demanding authentication.

IMPORTANT
---------
When a restriction is detected we:
  1. Log the reason.
  2. Raise an exception so the caller can save already-collected data and stop.

We NEVER attempt to bypass, evade, or solve any challenge or CAPTCHA.
"""

import logging
from typing import TYPE_CHECKING

from playwright.sync_api import Page

from src.exceptions import (
    AccountRestrictedError,
    CheckpointError,
    LoginRequiredError,
    RateLimitError,
)

if TYPE_CHECKING:
    from src.config import AppConfig

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Restriction signals
# ------------------------------------------------------------------ #

# These URL fragments indicate LinkedIn has redirected to a protected/
# challenge page.  Sourced from the reference implementation and expanded.
_RESTRICTION_URL_SIGNALS: tuple[str, ...] = (
    "checkpoint",
    "challenge",
    "/login",
    "authwall",
    "captcha",
    "unusual-activity",
    "security-verification",
    "session-redirect",
)

# Body phrases that indicate a rate limit or account restriction.
_RATE_LIMIT_PHRASES: tuple[str, ...] = (
    "reached the monthly search limit",
    "commercial use limit",
    "try searching again later",
    "out of search results",
    "unable to load search results",
)

_ACCOUNT_RESTRICTION_PHRASES: tuple[str, ...] = (
    "account restricted",
    "temporarily restricted",
    "your account has been restricted",
)

_AUTH_PHRASES: tuple[str, ...] = (
    "join now to see",
    "sign in to view",
    "please log in",
    "verify your identity",
    "you must be logged in",
)

_CHECKPOINT_PHRASES: tuple[str, ...] = (
    "security verification",
    "verify your phone",
    "we noticed unusual activity",
    "confirm your identity",
    "suspicious activity",
    "let us know it's you",
)


def detect_linkedin_restriction(page: Page, cfg: "AppConfig | None" = None) -> None:
    """
    Inspect the current page for signs of LinkedIn blocking or limiting access.

    Checks are performed in this order:
    1. URL-based signals (fastest — no page text needed).
    2. Body text phrases for rate limits.
    3. Body text phrases for account restrictions.
    4. Body text phrases for checkpoint / verification.
    5. Body text phrases for login walls.

    When a restriction is detected this function:
    - Logs the detection at WARNING level.
    - Raises the appropriate exception so the caller can handle it.

    When no restriction is detected this function returns normally.

    Args:
        page: The active Playwright page to inspect.
        cfg:  Optional AppConfig; if provided its ``restriction_*`` lists
              are used instead of the module defaults.

    Raises:
        LoginRequiredError:       LinkedIn is showing a login/authwall page.
        CheckpointError:          A CAPTCHA or security challenge is present.
        RateLimitError:           A rate or commercial-use limit is in effect.
        AccountRestrictedError:   The account has been restricted.
    """
    try:
        current_url = page.url.lower()
    except Exception:
        # Page may have crashed — not a restriction, let other code handle it
        return

    # ---- 1. URL signals ----
    # Use config signals if available, fall back to module defaults
    url_signals = (
        cfg.restriction_url_signals if cfg else list(_RESTRICTION_URL_SIGNALS)
    )
    for signal in url_signals:
        if signal in current_url:
            _log_and_raise_url(signal, current_url)

    # ---- 2. Body text checks ----
    try:
        body = page.inner_text("body").lower()
    except Exception:
        # Page may not have a body yet — not a restriction
        return

    # Use config body phrases if available, otherwise module defaults
    body_phrases = (
        cfg.restriction_body_phrases if cfg else []
    )

    # Check config-supplied phrases first
    for phrase in body_phrases:
        phrase_lower = phrase.lower()
        if phrase_lower in body:
            _classify_and_raise_body(phrase_lower, current_url)

    # ---- 3. Module-default categorised checks ----
    for phrase in _RATE_LIMIT_PHRASES:
        if phrase in body:
            logger.warning("Rate limit detected on page %s: '%s'", current_url, phrase)
            raise RateLimitError(
                f"LinkedIn rate limit: '{phrase}'. "
                "The scraper will stop and save collected data."
            )

    for phrase in _ACCOUNT_RESTRICTION_PHRASES:
        if phrase in body:
            logger.warning("Account restricted on page %s: '%s'", current_url, phrase)
            raise AccountRestrictedError(
                f"LinkedIn account restricted: '{phrase}'. "
                "Please check your LinkedIn account status."
            )

    for phrase in _CHECKPOINT_PHRASES:
        if phrase in body:
            logger.warning("Security checkpoint on page %s: '%s'", current_url, phrase)
            raise CheckpointError(
                f"LinkedIn security checkpoint: '{phrase}'. "
                "Please resolve the challenge in the browser and restart."
            )

    for phrase in _AUTH_PHRASES:
        if phrase in body:
            logger.warning("Login wall detected on page %s: '%s'", current_url, phrase)
            raise LoginRequiredError(
                f"LinkedIn login required: '{phrase}'. "
                "Please log in via the browser and restart the scraper."
            )


# ------------------------------------------------------------------ #
# Private helpers
# ------------------------------------------------------------------ #

def _log_and_raise_url(signal: str, url: str) -> None:
    """Raise the correct exception for a URL-based restriction signal."""
    msg = f"LinkedIn restriction detected in URL '{url}' (signal: '{signal}')."
    logger.warning(msg)

    if "login" in signal or "authwall" in signal:
        raise LoginRequiredError(msg + " Please log in manually.")
    if "checkpoint" in signal or "challenge" in signal or "captcha" in signal:
        raise CheckpointError(msg + " A security challenge is present.")
    if "security-verification" in signal:
        raise CheckpointError(msg + " Identity verification required.")
    # Default: treat unknown URL signals as checkpoint
    raise CheckpointError(msg)


def _classify_and_raise_body(phrase: str, url: str) -> None:
    """Classify a body-phrase match from the config list and raise."""
    msg = f"LinkedIn restriction detected on page '{url}': '{phrase}'."
    logger.warning(msg)

    if any(p in phrase for p in ("rate", "commercial", "search limit", "out of search")):
        raise RateLimitError(msg)
    if any(p in phrase for p in ("restricted", "temporarily")):
        raise AccountRestrictedError(msg)
    if any(p in phrase for p in ("checkpoint", "captcha", "verification", "challenge", "verify")):
        raise CheckpointError(msg)
    if any(p in phrase for p in ("log in", "sign in", "join now")):
        raise LoginRequiredError(msg)
    # Default: treat as checkpoint
    raise CheckpointError(msg)
