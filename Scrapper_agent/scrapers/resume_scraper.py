"""
Fallback 1: Resume Scraper Sub-Agent Wrapper.

This module integrates the existing `resume_subagent` package into
the Agent 2 fallback pipeline. It provides a clean interface that
translates between Agent 2's `CandidateProfile` schema and the
resume sub-agent's `ResumeScraperInput`/`ResumeScraperOutput` schemas.

Key features:
    - Zero-disk, in-memory resume processing (RAM-only BytesIO streaming).
    - Hybrid regex + LLM extraction pipeline.
    - Automatic memory cleanup and garbage collection.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from ..config import ScraperAgentConfig
from ..schemas import CandidateProfile, EducationEntry, ExperienceEntry, ExtractionSource

# Import the existing resume sub-agent
from resume_subagent.src.agent_interface import ResumeScraperAgent as _ResumeScraperAgent
from resume_subagent.src.config import ResumeScraperConfig as _ResumeScraperConfig
from resume_subagent.src.schemas import ResumeScraperInput

logger = logging.getLogger(__name__)


def _resolve_api_key(config: ScraperAgentConfig) -> str | None:
    """Resolve the correct API key based on the configured LLM provider.

    For Google Gemini, checks (in order):
      1. config.google_api_key
      2. GOOGLE_API_KEY env var
      3. GEMINI_API_KEY env var

    For OpenAI, checks (in order):
      1. config.openai_api_key
      2. OPENAI_API_KEY env var
    """
    import os

    provider = config.resume_llm_provider.lower()

    if provider == "google":
        key = (
            config.google_api_key
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
        )
        if not key:
            logger.warning(
                "Google Gemini selected as LLM provider but no Google API key found. "
                "Set google_api_key in config, or GOOGLE_API_KEY / GEMINI_API_KEY env var."
            )
        return key

    elif provider == "openai":
        key = (
            config.openai_api_key
            or os.environ.get("OPENAI_API_KEY")
        )
        if not key:
            logger.warning(
                "OpenAI selected as LLM provider but no OpenAI API key found. "
                "Set openai_api_key in config, or OPENAI_API_KEY env var."
            )
        return key

    logger.warning("Unknown LLM provider '%s'. No API key resolved.", provider)
    return None


class ResumeScraper:
    """Fallback 1: Resume Scraper Sub-Agent wrapper.

    Triggered when the LinkedIn scraper returns incomplete candidate
    data and a resume URL is available.

    Usage:
        scraper = ResumeScraper(config)
        delta = await scraper.extract(
            candidate_id="cand_001",
            resume_url="https://example.com/resume.pdf",
            missing_fields=["email", "phone", "skills"]
        )
        # delta is a CandidateProfile with only the extracted fields filled
    """

    def __init__(self, config: Optional[ScraperAgentConfig] = None) -> None:
        self.config = config or ScraperAgentConfig()
        self._agent: Optional[_ResumeScraperAgent] = None

    async def initialize(self) -> None:
        """Lazy-initialize the resume sub-agent."""
        if self._agent is not None:
            return

        logger.info("Initializing ResumeScraper (Resume Sub-Agent)...")

        # Resolve the correct API key based on the configured LLM provider
        resolved_api_key = _resolve_api_key(self.config)

        subagent_config = _ResumeScraperConfig(
            max_stream_size_mb=self.config.resume_max_stream_size_mb,
            max_pages_to_parse=self.config.resume_max_pages_to_parse,
            regex_prefilter_enabled=self.config.resume_regex_prefilter_enabled,
            llm_provider=self.config.resume_llm_provider,
            llm_model=self.config.resume_llm_model,
            temperature=self.config.resume_llm_temperature,
            api_key=resolved_api_key,
        )

        self._agent = _ResumeScraperAgent(config=subagent_config)
        await self._agent.initialize()
        logger.info("ResumeScraper initialized successfully.")

    async def extract(
        self,
        candidate_id: str,
        resume_url: str,
        missing_fields: List[str],
    ) -> CandidateProfile:
        """Extract missing candidate data from a resume.

        Args:
            candidate_id: Unique identifier for the candidate.
            resume_url: HTTP URL to the resume file (PDF or DOCX).
            missing_fields: List of field names that need extraction
                (e.g., ["email", "phone", "skills"]).

        Returns:
            A CandidateProfile with only the extracted fields populated.
            All other fields will be None.
        """
        if self._agent is None:
            await self.initialize()

        assert self._agent is not None

        logger.info(
            "ResumeScraper extracting for candidate=%s, url=%s, fields=%s",
            candidate_id,
            resume_url,
            missing_fields,
        )

        # Build the input for the resume sub-agent
        inp = ResumeScraperInput(
            candidate_id=candidate_id,
            resume_stream_url=resume_url,
            missing_fields=missing_fields,
            max_stream_size_mb=self.config.resume_max_stream_size_mb,
            max_pages_to_parse=self.config.resume_max_pages_to_parse,
        )

        # Run the sub-agent
        result = await self._agent.run(inp)

        if result.status.value == "failed":
            logger.error(
                "Resume extraction failed for %s: %s",
                candidate_id,
                result.error,
            )
            return CandidateProfile(source=ExtractionSource.RESUME)

        # Translate sub-agent output to CandidateProfile
        profile = CandidateProfile(source=ExtractionSource.RESUME)

        data = result.extracted_data

        if data.email:
            profile.email = data.email
        if data.phone:
            profile.phone = data.phone
        if data.skills:
            profile.skills = data.skills

        # Convert experience dicts to ExperienceEntry models
        if data.experience:
            profile.experience = [
                ExperienceEntry(
                    role=exp.get("role"),
                    company=exp.get("company"),
                    duration=exp.get("duration"),
                    description=exp.get("description"),
                )
                for exp in data.experience
                if isinstance(exp, dict)
            ]

        # Convert education dicts to EducationEntry models
        if data.education:
            profile.education = [
                EducationEntry(
                    degree=edu.get("degree"),
                    institution=edu.get("institution"),
                    year=edu.get("year"),
                )
                for edu in data.education
                if isinstance(edu, dict)
            ]

        profile.calculate_completeness()

        logger.info(
            "Resume extraction complete for %s. Found: "
            "email=%s, phone=%s, skills=%d, experience=%d, education=%d",
            candidate_id,
            bool(profile.email),
            bool(profile.phone),
            len(profile.skills) if profile.skills else 0,
            len(profile.experience) if profile.experience else 0,
            len(profile.education) if profile.education else 0,
        )

        return profile

    async def shutdown(self) -> None:
        """Release sub-agent resources."""
        if self._agent is not None:
            await self._agent.shutdown()
            self._agent = None
            logger.info("ResumeScraper shut down.")

