"""
Agent Interface — Multi-Agent Pipeline Entry Point.

This module provides a clean, standardized interface for the orchestrator
(Merge Stage / Agent 3 Validation Agent) to invoke the Resume Scraper
Sub-Agent. It follows the agent contract expected by the pipeline:

    - Input:  ResumeScraperInput (Pydantic model)
    - Output: ResumeScraperOutput (Pydantic model)
    - Async execution via `run()` method

Other agents in the pipeline (Search Agent, Scraper Agent, Portfolio Scraper,
Validation Agent) will follow the same pattern by implementing their own
`run()` method that accepts and returns standardized Pydantic models.
"""

from __future__ import annotations

import logging
from typing import Optional

from .config import ResumeScraperConfig
from .processor import InMemoryResumeProcessor
from .schemas import ResumeScraperInput, ResumeScraperOutput

logger = logging.getLogger(__name__)


class ResumeScraperAgent:
    """Standardized agent wrapper for the multi-agent pipeline.

    This is the interface that the orchestrator / pipeline merge stage
    will call. It handles initialization, lifecycle, and error boundaries.
    """

    def __init__(self, config: Optional[ResumeScraperConfig] = None) -> None:
        self.config = config or ResumeScraperConfig()
        self.processor: Optional[InMemoryResumeProcessor] = None

    async def initialize(self) -> None:
        """Initialize the processor (lazy-load pattern for pipeline startup)."""
        if self.processor is None:
            logger.info("Initializing ResumeScraperAgent...")
            self.processor = InMemoryResumeProcessor(config=self.config)
            logger.info("ResumeScraperAgent initialized successfully.")

    async def run(self, inp: ResumeScraperInput) -> ResumeScraperOutput:
        """Execute the resume scraping sub-agent.

        Args:
            inp: Standardized input contract.

        Returns:
            Standardized output contract.
        """
        if self.processor is None:
            await self.initialize()

        assert self.processor is not None
        return await self.processor.process(inp)

    async def shutdown(self) -> None:
        """Graceful shutdown — release any resources."""
        self.processor = None
        logger.info("ResumeScraperAgent shut down.")

