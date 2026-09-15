"""
exceptions.py
-------------
Custom exception hierarchy for the LinkedIn profile scraper.

All exceptions inherit from ScraperError so callers can catch the
entire family with a single except clause when needed.
"""


class ScraperError(Exception):
    """Base class for all scraper-specific errors."""


# ------------------------------------------------------------------ #
# Browser / navigation errors
# ------------------------------------------------------------------ #

class BrowserError(ScraperError):
    """Raised when the browser fails to launch or crashes unexpectedly."""


class NavigationError(ScraperError):
    """Raised when Playwright cannot navigate to a URL."""


class PageTimeoutError(ScraperError):
    """Raised when a page load or selector wait exceeds the configured timeout."""


class PageNotFoundError(ScraperError):
    """Raised when LinkedIn returns a 404 / profile-not-found page."""


# ------------------------------------------------------------------ #
# Authentication / restriction errors
# ------------------------------------------------------------------ #

class LoginRequiredError(ScraperError):
    """
    Raised when LinkedIn redirects to the login page.

    The scraper must stop and instruct the user to log in manually.
    Never attempt to auto-login or inject cookies.
    """


class CheckpointError(ScraperError):
    """
    Raised when LinkedIn shows a security checkpoint, CAPTCHA, or
    account-verification challenge.

    The scraper must stop, save collected data, and report to the user.
    """


class RateLimitError(ScraperError):
    """
    Raised when LinkedIn enforces a rate limit or commercial-use limit.

    Do not attempt to evade this restriction.
    """


class AccountRestrictedError(ScraperError):
    """Raised when LinkedIn reports the account is temporarily restricted."""


# ------------------------------------------------------------------ #
# Data / extraction errors
# ------------------------------------------------------------------ #

class ExtractionError(ScraperError):
    """Raised when a field extractor encounters an unexpected structure."""


class MissingFieldError(ScraperError):
    """Raised when a required field cannot be located on the page."""


# ------------------------------------------------------------------ #
# I/O errors
# ------------------------------------------------------------------ #

class CSVPermissionError(ScraperError):
    """
    Raised when the output CSV cannot be opened for writing.

    Most commonly caused by the file being open in Excel.
    """


class ConfigurationError(ScraperError):
    """Raised when a required configuration file is missing or malformed."""
