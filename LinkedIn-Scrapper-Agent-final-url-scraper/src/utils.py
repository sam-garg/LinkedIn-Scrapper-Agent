"""
utils.py
--------
Shared utility functions for the LinkedIn URL Discovery Tool.

Contains:
- Logging setup
- URL normalisation
- Profile URL detection
- Deduplication helpers
- Previously-collected URL loading (from CSV and txt)
- Human-like delay
"""

import csv
import logging
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse


# ------------------------------------------------------------------ #
# Logging
# ------------------------------------------------------------------ #

def setup_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    """
    Configure the root logger to write to both stdout and a rotating log file.

    Call this once from main.py before any other module is imported.

    Args:
        log_dir: Directory where log files will be written.
        level:   Log level string, e.g. "INFO", "DEBUG".

    Returns:
        The root logger instance.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "scraper.log"

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    fmt = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=date_fmt)

    # File handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(numeric_level)

    # Console handler (stdout so pytest captures it cleanly)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(numeric_level)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Avoid duplicate handlers if setup_logging is called more than once
    if not root.handlers:
        root.addHandler(file_handler)
        root.addHandler(console_handler)

    return root


# ------------------------------------------------------------------ #
# URL normalisation
# ------------------------------------------------------------------ #

def normalize_linkedin_url(url: str) -> str:
    """
    Return the canonical form of a LinkedIn profile URL.

    - Strips query parameters (e.g. ?trk=...)
    - Strips fragment (#...)
    - Ensures scheme is https and host is www.linkedin.com
    - Strips trailing slash from the path

    Examples::

        >>> normalize_linkedin_url("https://www.linkedin.com/in/john-doe/?trk=abc")
        'https://www.linkedin.com/in/john-doe'
        >>> normalize_linkedin_url("/in/john-doe")
        'https://www.linkedin.com/in/john-doe'

    Args:
        url: Raw URL string from a page link or file.

    Returns:
        Normalised URL string, or the original string if parsing fails.
    """
    if not url:
        return url

    url = url.strip()

    # Add scheme if missing so urlparse works correctly
    if url.startswith("/in/"):
        url = "https://www.linkedin.com" + url
    elif not url.startswith("http"):
        url = "https://" + url

    try:
        parsed = urlparse(url)
        clean = urlunparse((
            "https",
            "www.linkedin.com",
            parsed.path.rstrip("/"),
            "",   # params
            "",   # query
            "",   # fragment
        ))
        return clean
    except Exception:
        return url


def is_profile_url(url: str) -> bool:
    """
    Return True if the URL looks like a LinkedIn profile URL.

    Accepts:
    - Absolute URLs:  ``https://www.linkedin.com/in/john-doe``
    - Relative paths: ``/in/john-doe``

    Args:
        url: URL string to test.
    """
    if not url:
        return False
    # Absolute URL: must contain linkedin.com/in/<slug>
    if re.search(r"linkedin\.com/in/[^/\s?#]+", url):
        return True
    # Relative URL: starts with /in/ followed by a slug
    if re.search(r"^/in/[^/\s?#]+", url):
        return True
    return False


# ------------------------------------------------------------------ #
# Deduplication
# ------------------------------------------------------------------ #

def load_seen_urls(csv_path: Path) -> set[str]:
    """
    Read a previously written output CSV and return a set of normalised
    profile URLs that have already been collected.

    Args:
        csv_path: Path to the existing CSV output file.

    Returns:
        Set of normalised URL strings. Empty set if file does not exist.
    """
    seen: set[str] = set()
    if not csv_path.exists():
        return seen
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                raw_url = row.get("linkedin_url", "").strip()
                if raw_url:
                    seen.add(normalize_linkedin_url(raw_url))
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot read {csv_path}. Close it in Excel or any other program."
        ) from exc
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Could not load collected URLs from %s: %s", csv_path, exc
        )
    return seen


def load_seen_urls_from_txt(txt_path: Path) -> set[str]:
    """
    Read a plain-text URL file (one URL per line) and return normalised URLs.

    This is the primary deduplication source — any URL already in
    ``linkedin_urls.txt`` is skipped in subsequent runs.

    Args:
        txt_path: Path to the linkedin_urls.txt file.

    Returns:
        Set of normalised URL strings. Empty set if file does not exist.
    """
    seen: set[str] = set()
    if not txt_path.exists():
        return seen
    try:
        for line in txt_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and is_profile_url(line):
                seen.add(normalize_linkedin_url(line))
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Could not load previously collected URLs from %s: %s", txt_path, exc
        )
    return seen


def deduplicate_urls(urls: list[str], seen: set[str] | None = None) -> list[str]:
    """
    Remove duplicate and already-seen profile URLs from a list.

    Args:
        urls:  List of raw URL strings to deduplicate.
        seen:  Optional set of already-processed normalised URLs.

    Returns:
        Ordered list of unique normalised URLs not present in *seen*.
    """
    if seen is None:
        seen = set()
    result: list[str] = []
    local_seen: set[str] = set(seen)
    for url in urls:
        norm = normalize_linkedin_url(url)
        if is_profile_url(norm) and norm not in local_seen:
            result.append(norm)
            local_seen.add(norm)
    return result


# ------------------------------------------------------------------ #
# Human-like delay
# ------------------------------------------------------------------ #

def human_delay(min_sec: float = 2.5, max_sec: float = 6.0) -> None:
    """
    Sleep for a random duration in [min_sec, max_sec].

    Mimics the natural pause between user actions to avoid triggering
    LinkedIn's rate-limiting heuristics.

    Args:
        min_sec: Minimum sleep seconds.
        max_sec: Maximum sleep seconds.
    """
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)
