"""
LLM Structured Extraction Engine.

When regex pre-filtering fails (obscured formatting, complex fields like
experience/education), this module routes the document text to an LLM with
strict JSON schema enforcement.

Supports:
    - Google Gemini (default, via google-genai SDK)
    - OpenAI (via openai SDK, configurable)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from ..schemas import ExtractedData

logger = logging.getLogger(__name__)

# System prompt instructing the LLM to extract structured candidate data.
SYSTEM_PROMPT = """You are a precise data extraction assistant. Your task is to extract candidate 
profile information from a resume/CV document.

Extract ONLY the fields specified in the 'missing_fields' list. Return a valid JSON object 
with exactly those keys filled in based on the document content.

Guidelines:
- EMAIL: Extract standard email addresses. If obscured (e.g., "john [at] example [dot] com"), normalize it.
- PHONE: Extract phone numbers in international format when possible.
- SKILLS: Extract technical and professional skills as a list of strings.
- EXPERIENCE: Extract work history as a list of objects, each with 'role', 'company', 
  'duration' (optional), and 'description' (optional).
- EDUCATION: Extract education history as a list of objects, each with 'degree', 
  'institution', and 'year' (optional).

Rules:
- If a field is not found in the document, return null for that field.
- Do NOT fabricate or hallucinate information.
- Keep the output strictly as JSON. No markdown, no extra text."""


class LLMExtractor:
    """LLM-driven structured extraction supporting both Google Gemini and OpenAI.

    Uses Gemini by default. Falls back to OpenAI if provider='openai'.

    Usage:
        # Google Gemini (default)
        extractor = LLMExtractor(api_key="...", model="gemini-2.0-flash")

        # OpenAI
        extractor = LLMExtractor(api_key="...", model="gpt-4o-mini", provider="openai")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.0-flash",
        temperature: float = 0.0,
        provider: str = "google",
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.provider = provider.lower()

        # Resolve API key
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("OPENAI_API_KEY")

        # Initialize the appropriate client
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        """Initialize the LLM client based on provider."""
        if self.provider == "google":
            try:
                from google import genai
                self._genai = genai
                if self.api_key:
                    self._client = genai.Client(api_key=self.api_key)
                else:
                    self._client = genai.Client()
                logger.info("Initialized Google Gemini client (model=%s)", self.model)
            except ImportError:
                logger.warning("google-genai not installed. Falling back to OpenAI.")
                self.provider = "openai"
                self._init_client()
            except Exception as e:
                logger.error("Failed to init Gemini client: %s", e)
                self._client = None

        elif self.provider == "openai":
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self.api_key) if self.api_key else AsyncOpenAI()
                logger.info("Initialized OpenAI client (model=%s)", self.model)
            except Exception as e:
                logger.error("Failed to init OpenAI client: %s", e)
                self._client = None
        else:
            logger.error("Unknown LLM provider: %s", self.provider)

    async def extract(
        self,
        text: str,
        missing_fields: List[str],
    ) -> Optional[ExtractedData]:
        """Extract structured data from document text via LLM.

        Args:
            text: Full plain-text content of the resume.
            missing_fields: Fields the pipeline needs extracted.

        Returns:
            An ExtractedData instance, or None if the LLM call fails.
        """
        # Build a dynamic user prompt based on missing fields
        fields_str = ", ".join(missing_fields)
        user_prompt = (
            f"Extract the following fields from this resume: {fields_str}.\n\n"
            f"--- RESUME TEXT START ---\n{text}\n--- RESUME TEXT END ---"
        )

        try:
            logger.info(
                "Calling LLM (provider=%s, model=%s) to extract fields: %s",
                self.provider,
                self.model,
                missing_fields,
            )

            if self.provider == "google":
                raw = await self._call_gemini(user_prompt)
            else:
                raw = await self._call_openai(user_prompt)

            if not raw:
                logger.warning("LLM returned empty response.")
                return None

            # Parse the JSON response
            parsed: Dict[str, Any] = json.loads(raw)

            # Map to Pydantic schema
            extracted = ExtractedData(
                email=parsed.get("email"),
                phone=parsed.get("phone"),
                skills=parsed.get("skills"),
                experience=parsed.get("experience"),
                education=parsed.get("education"),
            )

            logger.info(
                "LLM extraction complete. Found: email=%s, phone=%s, skills=%d, experience=%d, education=%d",
                bool(extracted.email),
                bool(extracted.phone),
                len(extracted.skills) if extracted.skills else 0,
                len(extracted.experience) if extracted.experience else 0,
                len(extracted.education) if extracted.education else 0,
            )

            return extracted

        except json.JSONDecodeError as e:
            logger.error("LLM response was not valid JSON: %s", e)
            if raw:
                logger.debug("Raw response: %s", raw)
        except Exception as e:
            logger.exception("LLM extraction failed: %s", e)

        return None

    async def _call_gemini(self, user_prompt: str) -> Optional[str]:
        """Call Google Gemini API for structured extraction."""
        if self._client is None:
            logger.error("Gemini client not initialized.")
            return None

        try:
            full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=full_prompt,
                config={
                    "temperature": self.temperature,
                    "response_mime_type": "application/json",
                },
            )

            return response.text

        except Exception as e:
            logger.exception("Gemini API call failed: %s", e)
            return None

    async def _call_openai(self, user_prompt: str) -> Optional[str]:
        """Call OpenAI API for structured extraction."""
        if self._client is None:
            logger.error("OpenAI client not initialized.")
            return None

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.exception("OpenAI API call failed: %s", e)
            return None

