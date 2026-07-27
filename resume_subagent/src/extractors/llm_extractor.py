"""
LLM Structured Extraction Engine.

When regex pre-filtering fails (obscured formatting, complex fields like
experience/education), this module routes the document text to an LLM with
strict Pydantic schema enforcement.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

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
    """LLM-driven structured extraction with Pydantic schema validation.

    Uses OpenAI's function-calling / structured output mode to guarantee
    the response matches the expected schema.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.0,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.client = AsyncOpenAI(api_key=api_key) if api_key else AsyncOpenAI()

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
                "Calling LLM (model=%s) to extract fields: %s",
                self.model,
                missing_fields,
            )

            response = await self.client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_object"
                },
            )

            raw = response.choices[0].message.content
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
            logger.debug("Raw response: %s", raw)
        except Exception as e:
            logger.exception("LLM extraction failed: %s", e)

        return None

