"""
Fast Regular Expression Filter.

Runs optimized regular expressions to rapidly detect standard candidate
email addresses and international phone numbers without incurring API
latency or LLM token costs.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)


# ── Email pattern ─────────────────────────────────────────────────────
# Standard email regex compliant with RFC 5322 (simplified for practical use).
EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}"
)

# ── Phone patterns ────────────────────────────────────────────────────
# International phone numbers with optional country code, area code, separators.
PHONE_PATTERNS = [
    # +1-555-019-2834 or +1 (555) 019-2834
    re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}"),
    # Plain 10-digit US numbers: 5550192834 or 555-019-2834
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    # International with + prefix
    re.compile(r"\+\d{1,3}[-.\s]?\d{4,14}"),
]

# ── Skills dictionary (common tech skills for fast lookup) ────────────
COMMON_SKILLS: Set[str] = {
    # Languages
    "python", "javascript", "typescript", "java", "c++", "c#", "go", "rust",
    "ruby", "php", "swift", "kotlin", "scala", "perl", "r", "matlab",
    "sql", "html", "css", "sass", "less", "bash", "shell", "powershell",
    # Web frameworks
    "react", "angular", "vue", "svelte", "django", "flask", "fastapi",
    "express", "node.js", "next.js", "nuxt", "spring", "asp.net", "rails",
    "laravel", "symfony", "asp.net core", "blazor",
    # Data & ML
    "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "keras",
    "spark", "hadoop", "airflow", "dbt", "tableau", "power bi",
    "machine learning", "deep learning", "nlp", "computer vision",
    "llm", "langchain", "llamaindex", "rag", "vector database",
    # Cloud & DevOps
    "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "ansible",
    "jenkins", "github actions", "gitlab ci", "circleci", "argocd",
    "prometheus", "grafana", "datadog", "new relic",
    # Databases
    "postgresql", "postgres", "mysql", "mongodb", "redis", "elasticsearch",
    "cassandra", "dynamodb", "couchbase", "neo4j", "influxdb", "clickhouse",
    # Tools & Misc
    "git", "linux", "rest api", "graphql", "grpc", "kafka", "rabbitmq",
    "nginx", "apache", "websocket", "oauth", "jwt", "microservices",
    "ci/cd", "tdd", "agile", "scrum", "jira", "confluence",
}


class RegexExtractor:
    """Ultra-fast regex-based pre-filter for contact and skills extraction.

    This runs *before* any LLM call, so simple patterns are resolved
    without API latency or token cost.
    """

    def __init__(self) -> None:
        self._email_pattern = EMAIL_PATTERN
        self._phone_patterns = PHONE_PATTERNS
        self._skills_set = COMMON_SKILLS

    def extract_email(self, text: str) -> Optional[str]:
        """Extract the first valid email address from text."""
        match = self._email_pattern.search(text)
        if match:
            email = match.group(0).strip()
            logger.debug("Regex extracted email: %s", email)
            return email
        return None

    def extract_phone(self, text: str) -> Optional[str]:
        """Extract the first valid phone number from text."""
        for pattern in self._phone_patterns:
            match = pattern.search(text)
            if match:
                phone = match.group(0).strip()
                # Basic validation: ensure minimum length
                digits = re.sub(r"\D", "", phone)
                if 7 <= len(digits) <= 15:
                    logger.debug("Regex extracted phone: %s", phone)
                    return phone
        return None

    def extract_skills(self, text: str) -> list[str]:
        """Extract known skills by scanning text against a dictionary.

        This is a simple case-insensitive substring scan. For deeper
        extraction (ordering, relevance), use the LLM extractor.
        """
        text_lower = text.lower()
        found: list[str] = []
        for skill in sorted(self._skills_set, key=len, reverse=True):
            # Use word-boundary matching to avoid false positives
            pattern = re.compile(r"\b" + re.escape(skill) + r"\b", re.IGNORECASE)
            if pattern.search(text_lower):
                found.append(skill)
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for skill in found:
            if skill not in seen:
                seen.add(skill)
                unique.append(skill)
        logger.debug("Regex extracted %d skills.", len(unique))
        return unique

    def extract_all(self, text: str, fields: list[str]) -> Dict[str, object]:
        """Run regex extraction for all specified fields.

        Args:
            text: The full extracted document text.
            fields: List of field names to extract (e.g., ['email', 'phone', 'skills']).

        Returns:
            dict: Mapping of field name -> extracted value (or None/[]).
        """
        results: Dict[str, object] = {}
        for field in fields:
            field_lower = field.lower()
            if field_lower == "email":
                results[field] = self.extract_email(text)
            elif field_lower == "phone":
                results[field] = self.extract_phone(text)
            elif field_lower == "skills":
                results[field] = self.extract_skills(text)
            else:
                results[field] = None
        return results

