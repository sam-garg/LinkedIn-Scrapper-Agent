"""Entry point.

Usage:
    python main.py --input universities.json
    python main.py --input universities.pdf --limit 10 --export out.csv
    python main.py --input universities.json --no-login
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import db
from batch_runner import run_batches
from input_parser import load_universities

CSV_FIELDS = [
    "university",
    "full_name",
    "headline",
    "location",
    "profile_url",
]


def _export_csv(export: str, rows: list[dict]) -> None:
    out = Path(export)
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=CSV_FIELDS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"[export] {len(rows)} rows written to {out}")


def main() -> None:

    parser = argparse.ArgumentParser(
        description="LinkedIn student profile scraper"
    )

    parser.add_argument(
        "--input",
        required=True,
        help="Path to universities .json or .pdf",
    )

    parser.add_argument(
        "--limit",
        type=int,
        help="Only process first N universities",
    )

    parser.add_argument(
        "--export",
        help="CSV output path",
    )

    parser.add_argument(
        "--no-login",
        action="store_true",
        help="Use Google search only",
    )

    args = parser.parse_args()

    parsed = load_universities(args.input)

    print(
        f"[input] {len(parsed)} universities parsed from {args.input}"
    )

    alias_map = {
        p["name"].casefold(): p.get("aliases") or []
        for p in parsed
    }

    db.upsert_universities(parsed)

    queue = db.pending_universities()

    if args.limit:
        queue = queue[: args.limit]

    print(f"[queue] {len(queue)} universities to process\n")

    if not queue:
        print("[queue] nothing to do")
        return

    try:

        all_rows = run_batches(
            queue=queue,
            alias_map=alias_map,
            no_login=args.no_login,
        )

    except KeyboardInterrupt:
        print("\n[main] interrupted")
        sys.exit(130)

    if args.export:

        if all_rows:
            _export_csv(args.export, all_rows)
        else:
            print("[export] no rows collected")


if __name__ == "__main__":
    main()