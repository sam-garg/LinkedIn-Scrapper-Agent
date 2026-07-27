"""
In-Memory Resume Processor — Main Orchestrator.

This is the primary entry point for the Resume Scraper Sub-Agent.
It implements the hybrid extraction pipeline described in the architecture:

    1. In-Memory Streaming Fetcher (httpx → io.BytesIO)
    2. Light-Footprint In-Memory Parser (fitz / python-docx)
    3. Fast Regular Expression Filter (regex pre-filter)
    4. LLM Structured Extraction Engine (fallback for complex/obscured fields)
    5. Memory Garbage Collection (explicit cleanup)
    6. Return Standardized Payload to Merge Stage
"""

from __future__ import annotations

import gc
import logging
from typing import Optional

from .config import ResumeScraperConfig
from .extractors import LLMExtractor, RegexExtractor
from .fetcher import InMemoryStreamFetcher
from .parser import InMemoryDocumentParser
from .schemas import (
    ExtractionMethodMap,
    ExtractionStatus,
    ExtractedData,
    ResumeScraperInput,
    ResumeScraperOutput,
)

logger = logging.getLogger(__name__)


class InMemoryResumeProcessor:
    """Orchestrates the full in-memory resume extraction pipeline.

    Usage:
        processor = InMemoryResumeProcessor()
        result = await processor.process(input_data)
    """

    def __init__(self, config: Optional[ResumeScraperConfig] = None) -> None:
        self.config = config or ResumeScraperConfig()

        # Initialize sub-components
        self.fetcher = InMemoryStreamFetcher(
            max_stream_size_mb=self.config.max_stream_size_mb,
        )
        self.parser = InMemoryDocumentParser()
        self.regex_extractor = RegexExtractor()
        self.llm_extractor = LLMExtractor(
            api_key=self.config.openai_api_key,
            model=self.config.llm_model,
            temperature=self.config.temperature,
        )

    async def process(self, inp: ResumeScraperInput) -> ResumeScraperOutput:
        """Execute the full extraction pipeline for a single resume.

        Args:
            inp: Validated input specifying the candidate ID, resume URL,
                 and missing fields.

        Returns:
            A validated ResumeScraperOutput containing extracted data,
            method map, and status.
        """
        logger.info(
            "Processing resume for candidate=%s, url=%s, missing=%s",
            inp.candidate_id,
            inp.resume_stream_url,
            inp.missing_fields,
        )

        # ── Step 1 & 2: Fetch + Parse in-memory ──────────────────────
        buffer = await self.fetcher.fetch(inp.resume_stream_url)
        if buffer is None:
            return self._error_output(
                inp.candidate_id,
                "Failed to fetch resume stream (file too large or unreachable).",
            )

        text = self.parser.extract_text(
            buffer, inp.resume_stream_url, inp.max_pages_to_parse
        )
        if text is None:
            self._cleanup(buffer)
            return self._error_output(
                inp.candidate_id,
                "Failed to parse resume document (unsupported format or corrupted file).",
            )

        logger.info("Extracted %d characters of text from resume.", len(text))

        # ── Step 3: Fast Regex Pre-Filter ─────────────────────────────
        extracted: dict = {}
        extraction_method: dict = {}

        if self.config.regex_prefilter_enabled:
            regex_results = self.regex_extractor.extract_all(
                text, inp.missing_fields
            )
            for field, value in regex_results.items():
                if value is not None and value != []:
                    extracted[field] = value
                    extraction_method[field] = "regex_pass"
                    logger.debug("Regex resolved field '%s'.", field)

        # Determine which fields still need LLM extraction
        remaining_fields = [
            f for f in inp.missing_fields if f not in extraction_method
        ]

        # ── Step 4: LLM Fallback for remaining fields ─────────────────
        llm_delta: Optional[ExtractedData] = None
        if remaining_fields:
            logger.info(
                "Fields not resolved by regex; routing to LLM: %s",
                remaining_fields,
            )
            llm_delta = await self.llm_extractor.extract(text, remaining_fields)

            if llm_delta is not None:
                # Merge LLM results into extracted dict
                for field in remaining_fields:
                    value = getattr(llm_delta, field, None)
                    if value is not None and value != []:
                        extracted[field] = value
                        extraction_method[field] = "llm_pass"

        # ── Step 5: Memory Cleanup ────────────────────────────────────
        self._cleanup(buffer)

        # ── Step 6: Build & Return Standardized Output ────────────────
        return self._build_output(inp.candidate_id, extracted, extraction_method)

    # ── Internal Helpers ──────────────────────────────────────────────

    @staticmethod
    def _cleanup(buffer) -> None:
        """Explicitly release memory buffers and trigger GC."""
        try:
            buffer.close()
        except Exception:
            pass
        gc.collect()
        logger.debug("Memory cleanup completed.")

    @staticmethod
    def _error_output(candidate_id: str, error_msg: str) -> ResumeScraperOutput:
        """Build a failed output."""
        logger.error("Extraction failed for %s: %s", candidate_id, error_msg)
        return ResumeScraperOutput(
            candidate_id=candidate_id,
            extracted_data=ExtractedData(),
            extraction_method=ExtractionMethodMap(),
            status=ExtractionStatus.FAILED,
            error=error_msg,
        )

    @staticmethod
    def _build_output(
        candidate_id: str,
        extracted: dict,
        method_map: dict,
    ) -> ResumeScraperOutput:
        """Construct a validated output from extracted data."""
        data = ExtractedData(
            email=extracted.get("email"),
            phone=extracted.get("phone"),
            skills=extracted.get("skills") or None,
            experience=extracted.get("experience") or None,
            education=extracted.get("education") or None,
        )
        methods = ExtractionMethodMap(
            email=method_map.get("email"),
            phone=method_map.get("phone"),
            skills=method_map.get("skills"),
            experience=method_map.get("experience"),
            education=method_map.get("education"),
        )

        # Determine status
        if not extracted:
            status = ExtractionStatus.FAILED
            error = "No data could be extracted from the resume."
        elif len(extracted) == 0:
            # This shouldn't happen, but guard against it
            status = ExtractionStatus.FAILED
            error = "No data could be extracted from the resume."
        else:
            status = ExtractionStatus.SUCCESS
            error = None

        logger.info(
            "Extraction complete for %s: status=%s, fields=%s",
            candidate_id,
            status.value,
            list(extracted.keys()),
        )

        return ResumeScraperOutput(
            candidate_id=candidate_id,
            extracted_data=data,
            extraction_method=methods,
            status=status,
            error=error,
        )

