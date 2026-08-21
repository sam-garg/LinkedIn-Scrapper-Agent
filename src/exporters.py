"""
exporters.py
------------
Output writers for the LinkedIn URL Discovery Tool.

This module writes discovered profile URLs to two files:

1. ``linkedin_urls.txt``  — plain text, one URL per line (primary output).
2. ``linkedin_leads.csv`` — CSV with lightweight card-visible fields.

Both files are appended to incrementally so that collected data is safe
even if the run is interrupted partway through.
"""

import csv
import logging
from datetime import datetime
from pathlib import Path

from src.exceptions import CSVPermissionError
from src.models import DiscoveredProfile

logger = logging.getLogger(__name__)

# Fixed column order for the discovery CSV
DISCOVERY_COLUMNS = [
    "linkedin_url",
    "name",
    "headline",
    "location",
    "search_query",
    "scraped_at",
]


# ------------------------------------------------------------------ #
# CSV helpers
# ------------------------------------------------------------------ #

def ensure_csv_header(csv_path: Path, columns: list[str] | None = None) -> None:
    """
    Write the CSV header row if the file does not yet exist or is empty.

    If the file exists but has a different column set, it is archived to a
    ``.legacy.csv`` file and a fresh file is created with the new columns.

    Args:
        csv_path: Destination file path.
        columns:  Column names (defaults to DISCOVERY_COLUMNS).

    Raises:
        CSVPermissionError: If the file cannot be opened for writing.
    """
    cols = columns or DISCOVERY_COLUMNS

    if csv_path.exists() and csv_path.stat().st_size > 0:
        try:
            with csv_path.open("r", newline="", encoding="utf-8") as fh:
                existing_columns = next(csv.reader(fh), [])
            if existing_columns == cols:
                return
            # Archive incompatible file
            legacy_path = csv_path.with_name(csv_path.stem + ".legacy.csv")
            csv_path.replace(legacy_path)
            logger.warning("Archived incompatible CSV to %s", legacy_path)
        except (PermissionError, OSError) as exc:
            raise CSVPermissionError(
                f"Cannot prepare {csv_path}. Close the file and try again."
            ) from exc

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=cols)
            writer.writeheader()
        logger.info("Created discovery CSV: %s", csv_path)
    except PermissionError as exc:
        raise CSVPermissionError(
            f"Cannot write to {csv_path}. "
            "Close the file in Excel or any other application and try again."
        ) from exc


def append_profile_to_csv(
    profile: DiscoveredProfile,
    csv_path: Path,
    columns: list[str] | None = None,
) -> None:
    """
    Append a single DiscoveredProfile row to the CSV file.

    The file must already have a header (call ``ensure_csv_header`` first).

    Args:
        profile:  DiscoveredProfile instance to write.
        csv_path: Destination CSV file path.
        columns:  Column names (defaults to DISCOVERY_COLUMNS).

    Raises:
        CSVPermissionError: If the file is locked by another program.
    """
    cols = columns or DISCOVERY_COLUMNS
    row = profile.to_dict()
    safe_row = {col: row.get(col, "N/A") for col in cols}
    try:
        with csv_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=cols)
            writer.writerow(safe_row)
    except PermissionError as exc:
        raise CSVPermissionError(
            f"Cannot write to {csv_path}. "
            "Close the file in Excel or any other application."
        ) from exc
    except Exception as exc:
        logger.error(
            "Unexpected error writing CSV row for %s: %s",
            profile.linkedin_url, exc,
        )
        raise


# ------------------------------------------------------------------ #
# Plain-text URL file
# ------------------------------------------------------------------ #

def append_url_to_txt(url: str, txt_path: Path) -> None:
    """
    Append a single URL to the plain-text URL file (one URL per line).

    Skips if the URL is already present in the file.

    Args:
        url:      Normalised LinkedIn profile URL.
        txt_path: Path to the linkedin_urls.txt file.
    """
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if txt_path.exists():
        existing = {
            line.strip()
            for line in txt_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    if url not in existing:
        try:
            with txt_path.open("a", encoding="utf-8") as fh:
                fh.write(url + "\n")
        except PermissionError as exc:
            logger.warning("Cannot write to %s: %s", txt_path, exc)


def write_urls_to_txt(urls: list[str], txt_path: Path) -> int:
    """
    Write a batch of URLs to the plain-text file, appending only new ones.

    Args:
        urls:     List of normalised LinkedIn profile URLs.
        txt_path: Path to the linkedin_urls.txt file.

    Returns:
        Number of URLs actually written (excluding already-present ones).
    """
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if txt_path.exists():
        existing = {
            line.strip()
            for line in txt_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    written = 0
    try:
        with txt_path.open("a", encoding="utf-8") as fh:
            for url in urls:
                if url not in existing:
                    fh.write(url + "\n")
                    existing.add(url)
                    written += 1
    except PermissionError as exc:
        logger.warning("Cannot write to %s: %s", txt_path, exc)
    logger.info("Wrote %d new URLs to %s", written, txt_path)
    return written
