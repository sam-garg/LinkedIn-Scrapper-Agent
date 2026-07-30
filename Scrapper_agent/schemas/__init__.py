"""
Pydantic schemas for the Scraper Agent (Agent 2).

Defines the unified CandidateProfile model that holds all extracted
candidate information from LinkedIn + fallback sources.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ExtractionSource(str, Enum):
    """Source from which data was extracted."""

    LINKEDIN = "linkedin"
    RESUME = "resume"
    PORTFOLIO = "portfolio"
    MERGED = "merged"
    UNKNOWN = "unknown"


class ExperienceEntry(BaseModel):
    """A single work experience entry."""

    role: Optional[str] = Field(default=None, description="Job title / role.")
    company: Optional[str] = Field(default=None, description="Company name.")
    duration: Optional[str] = Field(
        default=None, description="Duration (e.g., 'Jan 2020 - Present')."
    )
    description: Optional[str] = Field(
        default=None, description="Description of responsibilities."
    )


class EducationEntry(BaseModel):
    """A single education entry."""

    degree: Optional[str] = Field(default=None, description="Degree name.")
    institution: Optional[str] = Field(default=None, description="School / university name.")
    year: Optional[str] = Field(default=None, description="Graduation year or period.")


class CandidateProfile(BaseModel):
    """Unified candidate profile combining data from all sources.

    This is the final output of Agent 2 sent to Agent 3 (Validation Agent).
    """

    # ── Core Identity ────────────────────────────────────────────────
    name: Optional[str] = Field(
        default=None,
        description="Full name of the candidate.",
        examples=["John Doe"],
    )
    email: Optional[str] = Field(
        default=None,
        description="Email address of the candidate.",
        examples=["john.doe@email.com"],
    )
    phone: Optional[str] = Field(
        default=None,
        description="Phone number of the candidate.",
        examples=["+1-555-019-2834"],
    )

    # ── Professional Details ─────────────────────────────────────────
    about: Optional[str] = Field(
        default=None,
        description="LinkedIn 'About' section summary of the candidate. "
                    "Only populated from LinkedIn scraping, never from fallback sources.",
        examples=["Experienced software engineer with 5+ years in full-stack development..."],
    )
    skills: Optional[List[str]] = Field(
        default=None,
        description="List of technical/professional skills.",
        examples=[["Python", "FastAPI", "PostgreSQL"]],
    )
    experience: Optional[List[ExperienceEntry]] = Field(
        default=None,
        description="List of work experience entries.",
    )
    education: Optional[List[EducationEntry]] = Field(
        default=None,
        description="List of education entries.",
    )

    # ── Source URLs ──────────────────────────────────────────────────
    linkedin_url: Optional[str] = Field(
        default=None,
        description="LinkedIn profile URL that was scraped.",
    )
    resume_url: Optional[str] = Field(
        default=None,
        description="URL of the candidate's resume (if found on LinkedIn).",
    )
    portfolio_url: Optional[str] = Field(
        default=None,
        description="URL of the candidate's portfolio/personal website (if found).",
    )

    # ── Metadata ─────────────────────────────────────────────────────
    source: ExtractionSource = Field(
        default=ExtractionSource.UNKNOWN,
        description="Primary data source for the profile.",
    )
    completeness: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of target fields that were successfully extracted (0.0 to 1.0).",
    )

    def calculate_completeness(self) -> float:
        """Calculate the fraction of target fields that are populated.

        Target fields: name, email, phone, skills, experience, education.
        Returns a value between 0.0 and 1.0.
        """
        target_fields = [
            self.name,
            self.email,
            self.phone,
            self.skills,
            self.experience,
            self.education,
        ]
        filled = sum(1 for field in target_fields if field is not None and field != [])
        self.completeness = round(filled / len(target_fields), 2)
        return self.completeness

    def merge(self, other: "CandidateProfile") -> "CandidateProfile":
        """Merge another candidate profile into this one.

        Only fills in fields that are currently None/empty.
        The other profile's non-None values take precedence on null fields.
        """
        if other.name is not None:
            self.name = self.name or other.name
        if other.email is not None:
            self.email = self.email or other.email
        if other.phone is not None:
            self.phone = self.phone or other.phone
        if other.skills is not None:
            existing_skills = set(self.skills or [])
            new_skills = [s for s in other.skills if s not in existing_skills]
            self.skills = (self.skills or []) + new_skills
        if other.experience is not None:
            self.experience = self.experience or other.experience
        if other.education is not None:
            self.education = self.education or other.education

        self.source = ExtractionSource.MERGED
        self.calculate_completeness()
        return self

    class Config:
        json_schema_extra = {
            "example": {
                "name": "John Doe",
                "email": "john.doe@email.com",
                "phone": "+1-555-019-2834",
                "skills": ["Python", "FastAPI", "PostgreSQL"],
                "experience": [
                    {
                        "role": "Senior Software Engineer",
                        "company": "Tech Corp",
                        "duration": "Jan 2020 - Present",
                        "description": "Building scalable microservices.",
                    }
                ],
                "education": [
                    {
                        "degree": "B.S. Computer Science",
                        "institution": "MIT",
                        "year": "2016",
                    }
                ],
                "linkedin_url": "https://linkedin.com/in/johndoe",
                "resume_url": "https://example.com/resume.pdf",
                "source": "linkedin",
                "completeness": 1.0,
            }
        }

