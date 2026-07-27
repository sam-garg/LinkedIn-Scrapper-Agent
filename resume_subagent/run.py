#!/usr/bin/env python3
"""
Standalone entry point for the Resume Scraper Sub-Agent.

This allows running the sub-agent independently for testing/debugging.

Usage:
    # Run with default config
    python run.py --candidate-id "cand_001" --url "https://example.com/resume.pdf" --fields email phone skills

    # With custom config
    python run.py --candidate-id "cand_001" --url "https://example.com/resume.pdf" --fields email phone --config config.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure the src package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.agent_interface import ResumeScraperAgent
from src.config import ResumeScraperConfig
from src.schemas import ResumeScraperInput

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="In-Memory Resume Scraper Sub-Agent",
    )
    parser.add_argument(
        "--candidate-id",
        type=str,
        default="test_candidate",
        help="Unique identifier for the candidate.",
    )
    parser.add_argument(
        "--url",
        type=str,
        required=True,
        help="URL of the resume file (PDF or DOCX) to process.",
    )
    parser.add_argument(
        "--fields",
        type=str,
        nargs="+",
        default=["email", "phone", "skills"],
        help="List of missing fields to extract (default: email phone skills).",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to YAML config file (optional).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="Maximum pages to parse (PDF only, default: 3).",
    )
    parser.add_argument(
        "--max-size-mb",
        type=int,
        default=10,
        help="Maximum stream size in MB (default: 10).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    # Load config
    config = None
    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            config = ResumeScraperConfig.from_yaml(str(config_path))
            logger.info("Loaded config from %s", config_path)
        else:
            logger.warning("Config file not found: %s. Using defaults.", config_path)

    if config is None:
        config = ResumeScraperConfig(
            max_stream_size_mb=args.max_size_mb,
            max_pages_to_parse=args.max_pages,
        )

    # Build input
    inp = ResumeScraperInput(
        candidate_id=args.candidate_id,
        resume_stream_url=args.url,
        missing_fields=args.fields,
        max_stream_size_mb=config.max_stream_size_mb,
        max_pages_to_parse=config.max_pages_to_parse,
    )

    # Run
    agent = ResumeScraperAgent(config=config)
    result = await agent.run(inp)

    # Output
    print("\n" + "=" * 60)
    print(f"RESULT — candidate_id: {result.candidate_id}")
    print(f"Status: {result.status.value}")
    if result.error:
        print(f"Error: {result.error}")
    print("-" * 60)
    print(f"Extracted Data:")
    print(f"  Email:    {result.extracted_data.email or '—'}")
    print(f"  Phone:    {result.extracted_data.phone or '—'}")
    print(f"  Skills:   {result.extracted_data.skills or '—'}")
    print(f"  Experience: {len(result.extracted_data.experience) if result.extracted_data.experience else 0} entries")
    print(f"  Education:  {len(result.extracted_data.education) if result.extracted_data.education else 0} entries")
    print("-" * 60)
    print(f"Extraction Methods:")
    for field, method in result.extraction_method.model_dump().items():
        if method:
            print(f"  {field}: {method}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

