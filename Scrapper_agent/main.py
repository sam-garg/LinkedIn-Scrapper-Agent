#!/usr/bin/env python3
"""
Agent 2: Scraper Agent -- Main Orchestrator.

This is the entry point for the Multi-Tier Fallback Extraction Pipeline.

Architecture:
    +-----------------------------------------------------------+
    | AGENT 2: SCRAPER AGENT CORE                               |
    |                                                           |
    |  1. LinkedIn Scraper Engine (primary)                     |
    |     -> Extracts: name, email, phone, resume_url, etc.    |
    |                                                           |
    |  2. Check: Are all 6 fields populated?                   |
    |     (name, email, phone, skills, experience, education)  |
    |       |                                                  |
    |       +- YES -> Send to Agent 3                          |
    |       |                                                  |
    |       +- NO  -> Fallback 1: Resume Scraper Sub-Agent     |
    |                  (zero-memory, RAM-only PDF/DOCX parsing)|
    |                  -> Merge & re-check                     |
    |                                                           |
    |  (Fallback 2: Portfolio Scraper - not yet implemented)   |
    +-----------------------------------------------------------+

Usage:
    # From command line:
    python main.py --url "https://linkedin.com/in/johndoe"
    python main.py --url "https://linkedin.com/in/johndoe" --config config.yaml
    python main.py --url "https://linkedin.com/in/janedoe" --candidate-id "cand_001"
    python main.py --url "https://linkedin.com/in/bobjohnson" --no-resume-fallback

    # As an imported module:
    from scrapper_agent.main import ScraperAgent

    agent = ScraperAgent()
    profile = await agent.run("https://linkedin.com/in/johndoe")
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import List, Optional, Set

from .config import ScraperAgentConfig
from .schemas import CandidateProfile, ExtractionSource
from .scrapers import LinkedInScraper, ResumeScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scraper_agent")


# -- Target fields that define a "complete" candidate profile ----------
TARGET_FIELDS: Set[str] = {
    "name",
    "email",
    "phone",
    "skills",
    "experience",
    "education",
}


class ScraperAgent:
    """Agent 2: Scraper Agent -- Multi-Tier Fallback Extraction Pipeline.

    This is the main orchestrator that:
    1. Scrapes LinkedIn for candidate profile data.
    2. If fields are missing, triggers the Resume Scraper Sub-Agent (Fallback 1).
    3. If fields are still missing, would trigger Portfolio Scraper (Fallback 2).
    4. Merges all data sources into a unified CandidateProfile.
    5. Returns the final profile to be passed to Agent 3 (Validation Agent).
    """

    def __init__(self, config: Optional[ScraperAgentConfig] = None) -> None:
        self.config = config or ScraperAgentConfig()
        self.linkedin_scraper = LinkedInScraper(config=self.config)
        self.resume_scraper: Optional[ResumeScraper] = None

        # Track which fields were resolved by each source
        self._field_sources: dict = {}

    async def run(
        self,
        linkedin_url: str,
        candidate_id: Optional[str] = None,
        resume_url_override: Optional[str] = None,
    ) -> CandidateProfile:
        """Execute the full multi-tier extraction pipeline.

        Args:
            linkedin_url: Full URL to the candidate's LinkedIn profile.
            candidate_id: Optional unique ID (auto-generated if not provided).
            resume_url_override: Optional real resume URL to use instead of
                the one extracted from LinkedIn (useful when LinkedIn scraper
                returns synthetic/placeholder URLs).

        Returns:
            A unified CandidateProfile with data from all available sources.
        """
        if candidate_id is None:
            candidate_id = f"cand_{int(time.time())}"

        logger.info("=" * 60)
        logger.info("ScraperAgent started for candidate=%s", candidate_id)
        logger.info("LinkedIn URL: %s", linkedin_url)
        logger.info("=" * 60)

        # -- Stage 1: Primary LinkedIn Extraction --------------------
        logger.info("Stage 1: LinkedIn Scraping")
        profile = await self.linkedin_scraper.scrape(linkedin_url)
        self._log_profile_state(profile, "After LinkedIn Extraction")

        # -- Override resume URL if one was provided directly --------
        if resume_url_override:
            logger.info("Using provided resume URL override: %s", resume_url_override)
            profile.resume_url = resume_url_override

        # -- Stage 2: Check if fields are missing -------------------
        missing = self._get_missing_fields(profile)

        if not missing:
            logger.info("All target fields populated from LinkedIn. Skipping fallbacks.")
            profile.calculate_completeness()
            return profile

        # -- Stage 3: Fallback 1 - Resume Scraper -------------------
        if self.config.enable_resume_fallback and profile.resume_url:
            logger.info("Stage 2: Resume Scraper Fallback")
            logger.info(
                "Missing fields: %s. Attempting resume extraction from: %s",
                missing,
                profile.resume_url,
            )

            delta = await self._run_resume_scraper(
                candidate_id=candidate_id,
                resume_url=profile.resume_url,
                missing_fields=missing,
            )

            profile.merge(delta)
            self._log_profile_state(profile, "After Resume Fallback")
            missing = self._get_missing_fields(profile)

        # -- Stage 4: Fallback 2 - Portfolio Scraper (placeholder) --
        if self.config.enable_portfolio_fallback and profile.portfolio_url and missing:
            logger.info("Stage 3: Portfolio Scraper Fallback (TODO)")
            logger.info(
                "Still missing fields: %s. Portfolio scraper not yet implemented.",
                missing,
            )
            # TODO: Implement PortfolioScraper
            # delta = await self.portfolio_scraper.scrape(profile.portfolio_url, missing)
            # profile.merge(delta)

        # -- Final State ---------------------------------------------
        profile.calculate_completeness()

        logger.info("=" * 60)
        logger.info("ScraperAgent COMPLETE for candidate=%s", candidate_id)
        logger.info("Completeness: %.0f%%", profile.completeness * 100)
        logger.info(
            "Missing fields: %s",
            self._get_missing_fields(profile) or "None",
        )
        logger.info("=" * 60)

        return profile

    async def _run_resume_scraper(
        self,
        candidate_id: str,
        resume_url: str,
        missing_fields: List[str],
    ) -> CandidateProfile:
        """Initialize and run the resume scraper fallback."""
        if self.resume_scraper is None:
            self.resume_scraper = ResumeScraper(config=self.config)

        return await self.resume_scraper.extract(
            candidate_id=candidate_id,
            resume_url=resume_url,
            missing_fields=missing_fields,
        )

    @staticmethod
    def _get_missing_fields(profile: CandidateProfile) -> List[str]:
        """Determine which target fields are missing from the profile."""
        missing = []

        if not profile.name:
            missing.append("name")
        if not profile.email:
            missing.append("email")
        if not profile.phone:
            missing.append("phone")
        if not profile.skills:
            missing.append("skills")
        if not profile.experience:
            missing.append("experience")
        if not profile.education:
            missing.append("education")

        return missing

    @staticmethod
    def _log_profile_state(profile: CandidateProfile, stage: str) -> None:
        """Log the current state of the profile for debugging."""
        logger.info("--- %s ---", stage)
        logger.info("  name:       %s", profile.name or "-")
        logger.info("  about:      %s", profile.about[:80] + "..." if profile.about and len(profile.about) > 80 else profile.about or "-")
        logger.info("  email:      %s", profile.email or "-")
        logger.info("  phone:      %s", profile.phone or "-")
        logger.info("  skills:     %s", f"{len(profile.skills)} items" if profile.skills else "-")
        logger.info("  experience: %s", f"{len(profile.experience)} entries" if profile.experience else "-")
        logger.info("  education:  %s", f"{len(profile.education)} entries" if profile.education else "-")
        logger.info("  resume_url: %s", profile.resume_url or "-")
        logger.info("  source:     %s", profile.source.value)

    async def shutdown(self) -> None:
        """Gracefully shut down all sub-agents."""
        logger.info("Shutting down ScraperAgent...")
        if self.resume_scraper is not None:
            await self.resume_scraper.shutdown()
        logger.info("ScraperAgent shut down complete.")


# -- CLI Entry Point ---------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Agent 2: Scraper Agent -- LinkedIn + Resume Fallback Pipeline",
    )
    parser.add_argument(
        "--url",
        type=str,
        required=True,
        help="LinkedIn profile URL to scrape.",
    )
    parser.add_argument(
        "--candidate-id",
        type=str,
        default=None,
        help="Optional unique identifier for the candidate.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to YAML config file (optional).",
    )
    parser.add_argument(
        "--no-resume-fallback",
        action="store_true",
        help="Disable resume scraper fallback.",
    )
    parser.add_argument(
        "--resume-url",
        type=str,
        default=None,
        help="Real resume URL (PDF/DOCX) to use for fallback extraction. Overrides any resume URL from LinkedIn.",
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
            config = ScraperAgentConfig.from_yaml(str(config_path))
            logger.info("Loaded config from %s", config_path)
        else:
            logger.warning("Config file not found: %s. Using defaults.", config_path)

    if config is None:
        config = ScraperAgentConfig()

    if args.no_resume_fallback:
        config.enable_resume_fallback = False

    # Run the agent
    agent = ScraperAgent(config=config)

    try:
        profile = await agent.run(
            linkedin_url=args.url,
            candidate_id=args.candidate_id,
            resume_url_override=args.resume_url,
        )

        # Pretty-print the result
        print("\n" + "=" * 70)
        print("FINAL CANDIDATE PROFILE")
        print("=" * 70)
        print(profile.model_dump_json(indent=2, exclude_none=True))
        print("=" * 70)
        print(f"Completeness: {profile.completeness * 100:.0f}%")
        print(f"Source: {profile.source.value}")

        # Show missing fields
        missing = ScraperAgent._get_missing_fields(profile)
        if missing:
            print(f"Still missing: {', '.join(missing)}")
        else:
            print("All target fields populated.")

        print("=" * 70)

    finally:
        await agent.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

