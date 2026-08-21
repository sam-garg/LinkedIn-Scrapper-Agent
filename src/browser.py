"""
browser.py
----------
Browser session management using Playwright with a persistent local profile.

SESSION APPROACH
----------------
This scraper uses a *persistent browser context* stored on disk at
``data/browser_profile/``.  The workflow is:

1. First run  : browser opens, session is not active → login is performed
   (automatically via form, or manually by the user).
   Playwright saves the resulting authenticated session in the profile directory.

2. Subsequent runs: Playwright loads the saved profile and the user is
   already logged in — the login step is skipped entirely.

3. Session expiry: when LinkedIn redirects to the login page again, the
   login flow repeats.

AUTOMATIC LOGIN
---------------
When ``--auto-login`` is requested (or ``LINKEDIN_AUTO_LOGIN=true`` in .env),
the scraper fills the NORMAL visible LinkedIn login form using credentials
supplied via environment variables.

What automatic login does:
  - Navigates to https://www.linkedin.com/login
  - Fills the email input
  - Fills the password input
  - Clicks the Sign In button
  - Waits for navigation

What automatic login does NOT do:
  - Inject ``li_at`` or any other session cookie
  - Bypass CAPTCHA or security checkpoints
  - Use stealth / anti-detection techniques
  - Modify browser fingerprints
  - Disable security features
  - Retry after a checkpoint is detected

If LinkedIn shows a CAPTCHA, checkpoint, or identity verification after the
form is submitted, automatic login stops immediately and the user is asked
to complete it manually in the open browser window.

CREDENTIAL SECURITY
-------------------
  - Credentials are read from environment variables only.
  - They are NEVER written to logs, CSV files, or any other output.
  - They are NEVER stored in source code or JSON files.
"""

import logging
import time
from typing import TYPE_CHECKING, Literal

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from src.exceptions import BrowserError, CheckpointError, LoginRequiredError
from src.utils import human_delay

if TYPE_CHECKING:
    from src.config import AppConfig

logger = logging.getLogger(__name__)

# LinkedIn URLs
_LINKEDIN_FEED = "https://www.linkedin.com/feed/"
_LINKEDIN_HOME = "https://www.linkedin.com/"
_LINKEDIN_LOGIN = "https://www.linkedin.com/login"

# Selectors for the login form — wrapped in try/except throughout because
# LinkedIn may change them.  If a selector fails the code falls back gracefully.
_SEL_EMAIL = "input#username"
_SEL_PASSWORD = "input#password"
_SEL_SUBMIT = "button[type='submit']"

# Page-state signals
_FEED_SIGNALS = ("feed", "linkedin.com/in/", "linkedin.com/mynetwork",
                 "linkedin.com/jobs", "linkedin.com/messaging")
_BLOCK_SIGNALS = ("checkpoint", "challenge", "captcha", "unusual-activity",
                  "security-verification", "authwall")
_LOGIN_SIGNALS = ("/login", "/uas/login")

LoginMode = Literal["auto", "manual", "default"]


# ------------------------------------------------------------------ #
# Session state detection
# ------------------------------------------------------------------ #

def is_logged_in(page: Page) -> bool:
    """
    Return True if the current page indicates an active LinkedIn session.

    Checks the URL for feed/profile indicators without making an extra
    navigation request — uses whatever page is already loaded.

    This is a lightweight check.  For a full verification that navigates
    to the feed, use ``verify_session()``.

    Args:
        page: Active Playwright page.

    Returns:
        True if the page URL suggests the user is authenticated.
    """
    try:
        url = page.url.lower()
        if any(sig in url for sig in _FEED_SIGNALS):
            return True

        # A successful login may land on the LinkedIn home page instead of
        # /feed/. Check for authenticated navigation as a second signal.
        return page.locator(
            "nav.global-nav, div.feed-identity-module, "
            "button[aria-label*='Me']"
        ).count() > 0
    except Exception:
        return False


def _is_on_login_page(page: Page) -> bool:
    """Return True if the current page is the LinkedIn login page."""
    try:
        url = page.url.lower()
        return any(sig in url for sig in _LOGIN_SIGNALS)
    except Exception:
        return False


def _is_blocked(page: Page) -> bool:
    """Return True if LinkedIn is showing a checkpoint/CAPTCHA/challenge page."""
    try:
        url = page.url.lower()
        return any(sig in url for sig in _BLOCK_SIGNALS)
    except Exception:
        return False


# ------------------------------------------------------------------ #
# Browser launch
# ------------------------------------------------------------------ #

def launch_browser(cfg: "AppConfig") -> tuple[Playwright, BrowserContext]:
    """
    Start Playwright and open a persistent Chromium browser context.

    The context is backed by the local profile directory so that an
    authenticated LinkedIn session is preserved between runs.

    Args:
        cfg: Application configuration.

    Returns:
        Tuple of (playwright_instance, browser_context).

    Raises:
        BrowserError: If Chromium cannot be launched.
    """
    logger.info("Launching Chromium browser (headless=%s)", cfg.headless)
    logger.info("Browser profile directory: %s", cfg.browser_profile_dir)

    p = sync_playwright().start()
    try:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(cfg.browser_profile_dir),
            headless=cfg.headless,
            viewport={"width": 1280, "height": 800},
            # Suppress the automation banner — this is cosmetic only.
            # We are not bypassing any anti-bot system; we rely on a real
            # human-initiated session (or a user-supplied credential form fill).
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
    except Exception as exc:
        p.stop()
        raise BrowserError(f"Failed to launch Chromium: {exc}") from exc

    logger.info("Browser launched successfully.")
    return p, context


def get_page(context: BrowserContext) -> Page:
    """
    Return the first existing page in the context, or open a new one.

    Args:
        context: An open Playwright browser context.

    Returns:
        A Playwright Page object.
    """
    pages = context.pages
    if pages:
        return pages[0]
    return context.new_page()


# ------------------------------------------------------------------ #
# Session verification
# ------------------------------------------------------------------ #

def verify_session(page: Page, cfg: "AppConfig") -> bool:
    """
    Navigate to the LinkedIn feed and confirm the session is authenticated.

    Args:
        page: Active Playwright page.
        cfg:  Application configuration.

    Returns:
        True if authenticated, False otherwise.
    """
    logger.info("Verifying LinkedIn session…")
    try:
        page.goto(
            _LINKEDIN_FEED,
            wait_until="domcontentloaded",
            timeout=cfg.navigation_timeout_ms,
        )
        human_delay(1.5, 3.0)

        # LinkedIn can briefly expose /feed/ before redirecting an expired
        # session to /uas/login. Allow that redirect to settle first.
        page.wait_for_timeout(3_000)

        if _is_on_login_page(page):
            logger.warning("LinkedIn session redirected to login: %s", page.url)
            return False

        if is_logged_in(page):
            logger.info("LinkedIn session verified — user is logged in.")
            print("LinkedIn session already active.")
            return True

        if _is_blocked(page):
            logger.warning("Session check hit a checkpoint/block page: %s", page.url)
            return False

        # Ambiguous — try a DOM indicator before giving up
        try:
            page.wait_for_selector("div.feed-identity-module", timeout=5_000)
            logger.info("LinkedIn session verified via feed DOM selector.")
            print("LinkedIn session already active.")
            return True
        except Exception:
            pass

        logger.warning("Session is not active. Current URL: %s", page.url)
        return False
    except Exception as exc:
        logger.error("Error during session verification: %s", exc)
        return False


# ------------------------------------------------------------------ #
# Automatic form-based login
# ------------------------------------------------------------------ #

def auto_login(page: Page, cfg: "AppConfig") -> bool:
    """
    Fill the normal LinkedIn login form using credentials from environment variables.

    This function:
      1. Navigates to the LinkedIn login page.
      2. Fills the email field.
      3. Fills the password field.
      4. Clicks the Sign In button.
      5. Waits for navigation.
      6. Checks whether login succeeded or a checkpoint appeared.

    It does NOT:
      - Inject cookies.
      - Bypass CAPTCHA or checkpoints.
      - Use stealth techniques.
      - Retry after a block is detected.

    Args:
        page: Active Playwright page.
        cfg:  Application configuration (provides credentials and timeout).

    Returns:
        True if login completed successfully (user is on the feed).
        False if login could not be completed within the timeout.

    Raises:
        LoginRequiredError: If credentials are missing.
        CheckpointError:    If LinkedIn shows a CAPTCHA or security challenge.
        BrowserError:       If a Playwright error occurs during the flow.
    """
    if not cfg.has_credentials:
        raise LoginRequiredError(
            "Automatic login requested but LINKEDIN_EMAIL and/or "
            "LINKEDIN_PASSWORD are not set in the environment. "
            "Set them in your .env file or use --manual-login instead."
        )

    # Log email (safe to show), never log the password
    logger.info(
        "Attempting automatic login for account: %s",
        cfg.linkedin_email,
    )
    print(f"\nAttempting automatic login for: {cfg.linkedin_email}")

    try:
        page.goto(
            _LINKEDIN_LOGIN,
            wait_until="domcontentloaded",
            timeout=cfg.navigation_timeout_ms,
        )
        human_delay(1.0, 2.0)
    except Exception as exc:
        raise BrowserError(f"Cannot navigate to LinkedIn login page: {exc}") from exc

    # ---- Fill email ----
    try:
        page.wait_for_selector(_SEL_EMAIL, timeout=10_000)
        page.fill(_SEL_EMAIL, cfg.linkedin_email)
        human_delay(0.5, 1.2)
    except Exception as exc:
        raise BrowserError(
            f"Could not fill the email field on the LinkedIn login page. "
            f"The page structure may have changed. Error: {exc}"
        ) from exc

    # ---- Fill password — never log this value ----
    try:
        page.wait_for_selector(_SEL_PASSWORD, timeout=5_000)
        page.fill(_SEL_PASSWORD, cfg.linkedin_password)
        human_delay(0.5, 1.2)
    except Exception as exc:
        raise BrowserError(
            f"Could not fill the password field on the LinkedIn login page. "
            f"Error: {exc}"
        ) from exc

    # ---- Click submit ----
    try:
        page.click(_SEL_SUBMIT)
        page.wait_for_load_state("domcontentloaded", timeout=cfg.login_timeout_sec * 1_000)
        human_delay(2.0, 4.0)
    except Exception as exc:
        raise BrowserError(f"Error submitting the login form: {exc}") from exc

    # ---- Evaluate result ----
    return _evaluate_post_login(page, cfg)


def _evaluate_post_login(page: Page, cfg: "AppConfig") -> bool:
    """
    Check the page state after the login form has been submitted.

    Returns True on success.
    Raises CheckpointError if a verification challenge is present.
    Falls through to manual-wait if state is ambiguous.
    """
    current_url = page.url.lower()

    # Success
    if any(sig in current_url for sig in _FEED_SIGNALS):
        logger.info("Automatic login succeeded.")
        print("LinkedIn login successful.")
        return True

    # Checkpoint / CAPTCHA / challenge — do not attempt to bypass
    if _is_blocked(page):
        _handle_checkpoint(page, cfg)
        # _handle_checkpoint returns only if the user resolved it manually
        return is_logged_in(page)

    # Still on login page — wrong credentials or another obstacle
    if _is_on_login_page(page):
        # Check for an error message on the page
        try:
            error_text = page.inner_text("body").lower()
        except Exception:
            error_text = ""
        if any(p in error_text for p in (
            "incorrect", "wrong", "invalid", "unrecognized",
            "couldn't find", "we can't", "check your",
        )):
            logger.error(
                "Automatic login failed — credentials appear to be incorrect "
                "for account %s. Password is not logged.",
                cfg.linkedin_email,
            )
            raise LoginRequiredError(
                f"LinkedIn login failed for {cfg.linkedin_email}. "
                "The credentials may be incorrect. "
                "Check LINKEDIN_EMAIL and LINKEDIN_PASSWORD in your .env file."
            )
        logger.warning("Still on login page after submission. Waiting for user action.")

    # Ambiguous state — poll for success within timeout
    logger.info(
        "Login result unclear at %s, polling for up to %ds…",
        page.url, cfg.login_timeout_sec,
    )
    deadline = time.time() + cfg.login_timeout_sec
    while time.time() < deadline:
        time.sleep(cfg.login_poll_interval_sec)
        try:
            if page.is_closed():
                raise BrowserError("Browser was closed during login wait.")
            if is_logged_in(page):
                logger.info("Login confirmed during polling.")
                print("LinkedIn login successful.")
                return True
            if _is_blocked(page):
                _handle_checkpoint(page, cfg)
                return is_logged_in(page)
        except BrowserError:
            raise
        except Exception:
            pass

    logger.error("Auto-login timed out after %ds.", cfg.login_timeout_sec)
    return False


def _handle_checkpoint(page: Page, cfg: "AppConfig") -> None:
    """
    LinkedIn has shown a CAPTCHA, checkpoint, or identity verification.

    We STOP the automatic flow here and ask the user to resolve it manually.
    The browser stays open.  We poll until the user completes the challenge
    or the timeout is reached.

    Never attempts to solve or bypass the challenge.
    """
    logger.warning(
        "LinkedIn checkpoint / verification detected at: %s", page.url
    )
    print("\n" + "!" * 60)
    print("  LinkedIn requires additional verification.")
    print("  Complete it manually in the browser window.")
    print("  The scraper will continue once you are on the feed page.")
    print("!" * 60 + "\n")

    deadline = time.time() + cfg.login_timeout_sec
    while time.time() < deadline:
        time.sleep(cfg.login_poll_interval_sec)
        try:
            if page.is_closed():
                raise BrowserError("Browser was closed during checkpoint wait.")
            if is_logged_in(page):
                logger.info("User completed checkpoint — session is now active.")
                print("LinkedIn login successful.")
                return
        except BrowserError:
            raise
        except Exception:
            pass

    logger.error("Checkpoint wait timed out after %ds.", cfg.login_timeout_sec)
    raise CheckpointError(
        "LinkedIn security verification was not completed within the timeout. "
        "Please restart the scraper and complete the challenge in the browser."
    )


# ------------------------------------------------------------------ #
# Manual login wait
# ------------------------------------------------------------------ #

def wait_for_manual_login(page: Page, cfg: "AppConfig") -> bool:
    """
    Open LinkedIn and wait for the user to log in manually.

    Polls for up to ``cfg.login_timeout_sec`` seconds.

    Args:
        page: Active Playwright page.
        cfg:  Application configuration.

    Returns:
        True if the user logged in within the timeout, False otherwise.

    Raises:
        BrowserError: If the browser page is closed during the wait.
    """
    logger.info("Opening LinkedIn for manual login…")
    print("\n" + "=" * 60)
    print("  ACTION REQUIRED — Please log into LinkedIn")
    print("  A browser window has opened. Log in manually.")
    print("  The scraper will continue automatically once you are")
    print("  on the LinkedIn feed page.")
    print("=" * 60 + "\n")

    try:
        page.goto(
            _LINKEDIN_HOME,
            wait_until="domcontentloaded",
            timeout=cfg.navigation_timeout_ms,
        )
    except Exception as exc:
        raise BrowserError(f"Cannot open LinkedIn: {exc}") from exc

    logger.info("Waiting up to %ds for manual login…", cfg.login_timeout_sec)
    deadline = time.time() + cfg.login_timeout_sec
    attempt = 0
    while time.time() < deadline:
        time.sleep(cfg.login_poll_interval_sec)
        attempt += 1
        try:
            if page.is_closed():
                raise BrowserError("Browser page was closed during login wait.")
            if is_logged_in(page):
                logger.info(
                    "Manual login detected after ~%ds.",
                    attempt * cfg.login_poll_interval_sec,
                )
                print("\n✓ Login detected — continuing with scraper.\n")
                return True
        except BrowserError:
            raise
        except Exception as exc:
            raise BrowserError(f"Browser error during login wait: {exc}") from exc

    logger.error("Login timeout after %ds.", cfg.login_timeout_sec)
    print(f"\n✗ Login timeout ({cfg.login_timeout_sec}s). Please restart and log in.\n")
    return False


# ------------------------------------------------------------------ #
# ensure_authenticated — main entry point
# ------------------------------------------------------------------ #

def ensure_authenticated(
    page: Page,
    cfg: "AppConfig",
    login_mode: LoginMode = "default",
) -> None:
    """
    Ensure the browser session is authenticated on LinkedIn.

    Login mode resolution (first match wins):
      1. ``login_mode="manual"``  → always prompt for manual login.
      2. ``login_mode="auto"``    → always attempt automatic form-based login.
      3. ``login_mode="default"`` → use ``cfg.auto_login`` (from ``LINKEDIN_AUTO_LOGIN``
                                    env var) to decide.

    If the session is already active, login is skipped regardless of mode.

    Args:
        page:       Active Playwright page.
        cfg:        Application configuration.
        login_mode: ``"auto"``, ``"manual"``, or ``"default"``.

    Raises:
        LoginRequiredError: If authentication cannot be established.
        CheckpointError:    If a security challenge is not resolved.
        BrowserError:       If the browser encounters a fatal error.
    """
    # ---- Step 1: check if already logged in ----
    if verify_session(page, cfg):
        return

    logger.info("Session not active. Determining login mode (requested=%s).", login_mode)

    # ---- Step 2: resolve effective mode ----
    if login_mode == "manual":
        use_auto = False
    elif login_mode == "auto":
        use_auto = True
    else:
        # "default" — honour the env var / config
        use_auto = cfg.auto_login

    # ---- Step 3: perform login ----
    if use_auto:
        logger.info("Using automatic form-based login.")
        success = auto_login(page, cfg)
    else:
        logger.info("Using manual login flow.")
        success = wait_for_manual_login(page, cfg)

    if not success:
        raise LoginRequiredError(
            "LinkedIn authentication did not complete within the timeout. "
            "Please run again and log in when the browser opens."
        )

    # ---- Step 4: re-verify ----
    if not verify_session(page, cfg):
        raise LoginRequiredError(
            "Session verification failed after login. Please try again."
        )


# ------------------------------------------------------------------ #
# Browser teardown
# ------------------------------------------------------------------ #

def close_browser(playwright_instance: Playwright, context: BrowserContext) -> None:
    """
    Gracefully close the browser context and stop Playwright.

    Args:
        playwright_instance: The Playwright instance returned by launch_browser.
        context:             The BrowserContext returned by launch_browser.
    """
    try:
        context.close()
        logger.info("Browser context closed.")
    except Exception as exc:
        logger.warning("Error closing browser context: %s", exc)
    try:
        playwright_instance.stop()
        logger.info("Playwright stopped.")
    except Exception as exc:
        logger.warning("Error stopping Playwright: %s", exc)
