"""
LinkedIn Profile URL Discovery Tool
------------------------------------
Discovers LinkedIn profile URLs from people-search results.

This tool does NOT open individual profile pages.
It collects URLs directly from search result cards and saves them.

Usage examples
--------------
Broad postgraduate discovery (recommended)::

    python -m src.main --postgraduate --limit 100

Single keyword search::

    python -m src.main --query "MBA" --limit 50

With location filter::

    python -m src.main --query "Master's" --limit 50 --location "United States"

Automatic login::

    python -m src.main --postgraduate --limit 25 --auto-login

Full help::

    python -m src.main --help
"""

import argparse
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: set up sys.path so the package is importable when run via
# ``python -m src.main`` from the project root.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.browser import close_browser, ensure_authenticated, get_page, launch_browser
from src.config import load as load_config
from src.exceptions import (
    AccountRestrictedError,
    BrowserError,
    CheckpointError,
    CSVPermissionError,
    LoginRequiredError,
    NavigationError,
    RateLimitError,
    ScraperError,
)
from src.exporters import append_profile_to_csv, append_url_to_txt, ensure_csv_header
from src.search import collect_profile_urls
from src.utils import load_seen_urls_from_txt, setup_logging

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Argument parser
# ------------------------------------------------------------------ #

def build_argument_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m src.main",
        description=(
            "LinkedIn Profile URL Discovery Tool\n"
            "Collects LinkedIn profile URLs from search results.\n\n"
            "This tool does NOT open individual profile pages.\n"
            "It discovers URLs and hands them to a downstream model for\n"
            "profile scraping, education extraction, and qualification.\n\n"
            "IMPORTANT: You must log into LinkedIn manually on first run.\n"
            "           The tool never stores your credentials."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m src.main --postgraduate --limit 100\n"
            "  python -m src.main --query \"MBA\" --limit 50\n"
            "  python -m src.main --query \"Master's\" --limit 50 --location \"United States\"\n"
            "  python -m src.main --postgraduate --limit 25 --auto-login\n"
        ),
    )

    # ---- Search mode (mutually exclusive) ----
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--query", "-q",
        type=str,
        default=None,
        metavar="KEYWORDS",
        help='Search keywords, e.g. "MBA" or "Master of Science"',
    )
    mode_group.add_argument(
        "--postgraduate",
        action="store_true",
        default=False,
        help=(
            "Run the full broad postgraduate discovery query set "
            "(MS, Master's, MBA, MEng, etc. — from config/search_queries.json)."
        ),
    )

    # ---- Search parameters ----
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=None,
        metavar="N",
        help="Number of unique profile URLs to collect (default: value from config/settings.json)",
    )
    parser.add_argument(
        "--location", "-l",
        type=str,
        default=None,
        metavar="LOCATION",
        help='Geographic filter, e.g. "United States" or "San Francisco, CA"',
    )

    # ---- Behaviour ----
    behaviour_group = parser.add_argument_group("Behaviour")
    behaviour_group.add_argument(
        "--no-dedup",
        action="store_true",
        default=False,
        help="Disable cross-run deduplication (re-collect URLs already in linkedin_urls.txt)",
    )
    behaviour_group.add_argument(
        "--safe-mode",
        action="store_true",
        default=False,
        help="Use conservative delays between search pages.",
    )

    # ---- Login mode ----
    login_group = parser.add_argument_group(
        "Login",
        description=(
            "Control how the tool authenticates with LinkedIn.\n"
            "If neither flag is supplied, LINKEDIN_AUTO_LOGIN in .env is used.\n"
            "Credentials must be set in .env as LINKEDIN_EMAIL and LINKEDIN_PASSWORD.\n"
            "The password is NEVER printed or logged."
        ),
    )
    login_mutex = login_group.add_mutually_exclusive_group()
    login_mutex.add_argument(
        "--auto-login",
        action="store_true",
        default=False,
        help=(
            "Fill the LinkedIn login form automatically using "
            "LINKEDIN_EMAIL and LINKEDIN_PASSWORD from .env."
        ),
    )
    login_mutex.add_argument(
        "--manual-login",
        action="store_true",
        default=False,
        help="Open LinkedIn in the browser and wait for you to log in manually.",
    )

    return parser


# ------------------------------------------------------------------ #
# Run orchestration
# ------------------------------------------------------------------ #

def run(args: argparse.Namespace) -> int:
    """
    Main execution flow.

    1. Load configuration.
    2. Set up logging.
    3. Load previously-collected URLs for deduplication.
    4. Launch browser and verify/wait for authentication.
    5. Run search queries and collect profile URLs from result cards.
    6. Save discovered URLs to linkedin_urls.txt and linkedin_leads.csv.
    7. Close browser and print summary.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 = success, 1 = error).
    """
    # ---- Load configuration ----
    cfg = load_config()
    safe_mode = args.safe_mode or cfg.safe_mode

    # ---- Logging ----
    setup_logging(cfg.log_dir, cfg.log_level)
    logger.info("=" * 60)
    logger.info("LinkedIn Profile URL Discovery Tool starting")
    logger.info("=" * 60)

    limit = args.limit if args.limit is not None else cfg.default_limit

    # ---- Resolve search queries ----
    if args.query:
        search_queries: str | list[str] = args.query
        logger.info("Query mode: single query '%s'", args.query)
    elif args.postgraduate:
        # Use the full broad postgraduate query set
        search_queries = list(cfg.postgraduate_queries)
        # Also add university-based discovery queries (first 5 universities)
        for uni in cfg.universities[:5]:
            search_queries.append(f"{uni} MS")
            search_queries.append(f"{uni} Master's")
        logger.info("Postgraduate mode: %d queries", len(search_queries))
    else:
        # Default: postgraduate behaviour
        search_queries = list(cfg.postgraduate_queries)
        logger.info("Default mode: using postgraduate queries (%d)", len(search_queries))

    query_count = len(search_queries) if isinstance(search_queries, list) else 1
    logger.info("Limit: %d | Location: %s", limit, args.location or "any")

    # ---- Load previously-collected URLs for deduplication ----
    seen_urls: set[str] = set()
    previously_collected = 0
    if not args.no_dedup:
        seen_urls = load_seen_urls_from_txt(cfg.leads_txt)
        previously_collected = len(seen_urls)
        if seen_urls:
            logger.info(
                "Loaded %d previously-collected URLs for deduplication.", len(seen_urls)
            )

    # ---- Ensure CSV header ----
    try:
        ensure_csv_header(cfg.leads_csv, cfg.csv_columns)
    except CSVPermissionError as exc:
        logger.error("Cannot initialise CSV: %s", exc)
        print(f"\n✗ Error: {exc}\n")
        return 1

    # ---- Launch browser ----
    playwright_instance = None
    context = None
    discovered: list = []
    errors = 0

    try:
        playwright_instance, context = launch_browser(cfg)
        page = get_page(context)

        # ---- Resolve login mode ----
        if args.auto_login:
            login_mode = "auto"
        elif args.manual_login:
            login_mode = "manual"
        else:
            login_mode = "default"

        logger.info("Login mode: %s", login_mode)

        # ---- Authenticate ----
        ensure_authenticated(page, cfg, login_mode=login_mode)
        logger.info("LinkedIn session verified.")

        # ---- Discover profile URLs ----
        print(f"\nSearching LinkedIn for up to {limit} profile URLs…\n")
        logger.info("Starting URL discovery (limit=%d)", limit)

        try:
            discovered = collect_profile_urls(
                page=page,
                cfg=cfg,
                query=search_queries,
                limit=limit,
                location=args.location,
                seen_urls=seen_urls,
            )
        except (LoginRequiredError, CheckpointError, RateLimitError, AccountRestrictedError) as exc:
            logger.warning("Search stopped due to restriction: %s", exc)
            _print_restriction_message(exc)
            # Save whatever was collected before the restriction
            if discovered:
                _save_batch(discovered, cfg)
                print(f"\n  Saved {len(discovered)} URLs collected before restriction.\n")
            return 1
        except NavigationError as exc:
            logger.error("Navigation error during search: %s", exc)
            print(f"\n✗ Navigation error: {exc}\n")
            return 1

        if not discovered:
            print("\nNo new profile URLs found. Try different queries or check your LinkedIn session.\n")
            return 0

        logger.info("Discovery complete. Found %d new profile URLs.", len(discovered))
        print(f"Found {len(discovered)} new profile URLs. Saving…\n")

        # ---- Save discovered URLs ----
        saved = 0
        for profile in discovered:
            try:
                append_url_to_txt(profile.linkedin_url, cfg.leads_txt)
                append_profile_to_csv(profile, cfg.leads_csv, cfg.csv_columns)
                saved += 1
                print(f"  ✓ {profile.linkedin_url}")
            except CSVPermissionError as exc:
                logger.error("Cannot save to CSV: %s", exc)
                print(f"\n✗ CSV Error: {exc}\n  Continuing…")
                errors += 1
            except Exception as exc:
                logger.warning("Error saving %s: %s", profile.linkedin_url, exc)
                errors += 1

        # ---- Summary ----
        _print_summary(
            query_count=query_count,
            search_results=len(discovered),
            new_urls=saved,
            previously_collected=previously_collected,
            errors=errors,
            txt_path=cfg.leads_txt,
            csv_path=cfg.leads_csv,
        )

        logger.info(
            "Run complete. Saved=%d Previously=%d Errors=%d",
            saved, previously_collected, errors,
        )
        return 0

    except BrowserError as exc:
        logger.error("Browser error: %s", exc)
        print(f"\n✗ Browser error: {exc}\n")
        return 1
    except LoginRequiredError as exc:
        _print_restriction_message(exc)
        return 1
    except KeyboardInterrupt:
        logger.info("Run interrupted by user (Ctrl+C).")
        print("\n\nInterrupted by user.")
        if discovered:
            _save_batch(discovered, cfg)
            print(f"Saved {len(discovered)} URLs collected before interruption.")
        return 0
    finally:
        if context is not None and playwright_instance is not None:
            close_browser(playwright_instance, context)


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _save_batch(profiles: list, cfg) -> None:
    """Save a batch of DiscoveredProfile objects (used on early exit)."""
    for profile in profiles:
        try:
            append_url_to_txt(profile.linkedin_url, cfg.leads_txt)
            append_profile_to_csv(profile, cfg.leads_csv, cfg.csv_columns)
        except Exception:
            pass


def _print_restriction_message(exc: Exception) -> None:
    """Print a user-friendly restriction message to stdout."""
    print("\n" + "!" * 60)
    print("  LinkedIn restriction detected — discovery stopped.")
    print(f"  Reason: {exc}")
    print()
    if isinstance(exc, LoginRequiredError):
        print("  Action: Open LinkedIn in a browser, log in, then restart.")
    elif isinstance(exc, CheckpointError):
        print("  Action: Open the browser, complete the challenge, then restart.")
    elif isinstance(exc, RateLimitError):
        print("  Action: Wait a while before running again.")
    elif isinstance(exc, AccountRestrictedError):
        print("  Action: Check your LinkedIn account status.")
    print()
    print("  Already collected URLs have been saved.")
    print("!" * 60 + "\n")


def _print_summary(
    query_count: int,
    search_results: int,
    new_urls: int,
    previously_collected: int,
    errors: int,
    txt_path: Path,
    csv_path: Path,
) -> None:
    """Print the final run summary."""
    print("\n" + "=" * 60)
    print("  Run complete")
    print()
    print(f"  Search queries        : {query_count}")
    print(f"  New LinkedIn URLs     : {new_urls}")
    print(f"  Previously collected  : {previously_collected}")
    print(f"  Errors                : {errors}")
    print()
    print("  Output:")
    print(f"    {txt_path}")
    print(f"    {csv_path}")
    print("=" * 60 + "\n")


# ------------------------------------------------------------------ #
# Entry point
# ------------------------------------------------------------------ #

def main() -> None:
    """Parse arguments and run the URL discovery tool."""
    parser = build_argument_parser()
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
