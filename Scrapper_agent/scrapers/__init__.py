"""
Scrapers package for Agent 2 (Scraper Agent).

Provides:
    - LinkedInScraper: Primary LinkedIn profile extraction engine.
    - ResumeScraper: Fallback 1 — zero-memory resume parser wrapper.

Other agents (Search Agent, Portfolio Scraper, Validation Agent) will
follow the same pattern by implementing their own scrape() methods.
"""

from .linkedin_scraper import LinkedInScraper
from .resume_scraper import ResumeScraper

__all__ = ["LinkedInScraper", "ResumeScraper"]

