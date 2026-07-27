"""
Pydantic schemas for the Resume Scraper Sub-Agent.

Defines strict input/output contracts for the multi-agent pipeline.
All extracted data is validated before being propagated to the merge stage.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


class ExtractionStatus(str, Enum):
    """Status of the extraction process."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class ResumeScraperInput(BaseModel):
    """Input schema for the Resume Scraper Sub-Agent.

    This is the contract expected from the orchestrator (e.g., Agent 2 Scraper
    or the pipeline merge stage) when a resume needs to be parsed.
    """

    candidate_id: str = Field(
        ..., description="Unique identifier for the candidate across the pipeline."
    )
    resume_stream_url: str = Field(
        ...,
        description="HTTP/HTTPS URL pointing to the resume file (PDF or DOCX).",
    )
    missing_fields: List[str] = Field(
        ...,
        description="List of field names that are null/missing and need extraction.",
        examples=[["email", "phone", "skills"]],
    )
    max_stream_size_mb: int = Field(
        default=10,
        description="Hard cap on the stream buffer size in MB.",
        ge=1,
        le=100,
    )
    max_pages_to_parse: int = Field(
        default=3,
        description="Maximum number of pages to extract text from.",
        ge=1,
        le=50,
    )


class ExtractedData(BaseModel):
    """The structured data delta extracted from the resume."""

    email: Optional[str] = Field(
        default=None, description="Candidate email address.", examples=["john.doe@email.com"]
    )
    phone: Optional[str] = Field(
        default=None,
        description="Candidate phone number (international format preferred).",
        examples=["+1-555-019-2834"],
    )
    skills: Optional[List[str]] = Field(
        default=None,
        description="List of technical/professional skills.",
        examples=[["Python", "FastAPI", "PostgreSQL"]],
    )
    experience: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="List of work experiences. Each entry may contain role, company, duration, description.",
    )
    education: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="List of education entries. Each entry may contain degree, institution, year.",
    )


class ExtractionMethodMap(BaseModel):
    """Tracks which method was used to extract each field."""

    email: Optional[str] = Field(default=None, examples=["regex_pass", "llm_pass"])
    phone: Optional[str] = Field(default=None, examples=["regex_pass", "llm_pass"])
    skills: Optional[str] = Field(default=None, examples=["regex_pass", "llm_pass"])
    experience: Optional[str] = Field(default=None, examples=["llm_pass"])
    education: Optional[str] = Field(default=None, examples=["llm_pass"])


class ResumeScraperOutput(BaseModel):
    """Output schema produced by the Resume Scraper Sub-Agent.

    This is returned to the pipeline merge stage for final consolidation.
    """

    candidate_id: str = Field(
        ..., description="The candidate ID passed in the input request."
    )
    extracted_data: ExtractedData = Field(
        ..., description="The structured data delta extracted from the resume."
    )
    extraction_method: ExtractionMethodMap = Field(
        ...,
        description="Maps each extracted field to the method used (regex_pass or llm_pass).",
    )
    status: ExtractionStatus = Field(
        ...,
        description="Overall status of the extraction pipeline.",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if the extraction failed or was partial.",
    )

