"""Strict candidate qualification over structured education records."""

import re
from typing import Iterable

from src.extractors import parse_education_records
from src.models import ProfileData

MASTER_PATTERN = re.compile(
    r"\b(?:ms|m\.s\.?|mba|meng|m\.eng\.?|mem|master(?:'s|s)?|"
    r"master of (?:science|engineering|business|management)|postgraduate|"
    r"graduate student)\b", re.IGNORECASE,
)
INDIA_CONTEXT_PATTERN = re.compile(
    r"\b(?:india|indian|iit|nit|vit|bits|jntu|anna university|"
    r"mumbai|pune|delhi|bangalore|bengaluru|hyderabad|chennai|kerala|v ellore|vellore|"
    r"maharashtra|telangana|karnataka|tamil nadu)\b", re.IGNORECASE,
)


def _normalise(value: str) -> str:
    value = value.lower().replace("&", " and ")
    value = re.sub(r"\buniv\.?\b", "university", value)
    value = re.sub(r"\binst\.?\b", "institute", value)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value)).strip()


def _degree_label(record: dict) -> str:
    text = record.get("degree", "")
    upper = text.upper()
    if "MBA" in upper or "MASTER OF BUSINESS" in upper:
        return "MBA"
    if re.search(r"\bM(?:\.S|S)\b|MASTER OF SCIENCE", upper):
        return "Master of Science"
    if re.search(r"\bM(?:\.ENG|ENG)\b|MASTER OF ENGINEERING", upper):
        return "Master of Engineering"
    if "MEM" in upper:
        return "Master of Engineering Management"
    if "POSTGRADUATE" in upper or "GRADUATE" in upper:
        return "Postgraduate"
    return "Master's Degree"


def extract_expected_graduation_year(record_or_text: dict | str) -> int | None:
    """Extract the end year from one education record, never from page-wide text."""
    if isinstance(record_or_text, dict):
        value = record_or_text.get("graduation_year") or record_or_text.get("end_year")
        match = re.search(r"20\d{2}", str(value))
        return int(match.group()) if match else None
    years = re.findall(r"\b20\d{2}\b", record_or_text)
    return int(years[-1]) if years else None


def match_target_university(record: dict | str, universities: Iterable[str] | None = None) -> tuple[bool, str, str]:
    """Match the university attached to one education record against config."""
    text = record.get("university", "") if isinstance(record, dict) else record
    normalized = _normalise(text)
    aliases = {
        "massachusetts institute of technology": "mit",
        "new york university": "nyu",
        "university of southern california": "usc",
        "carnegie mellon university": "cmu",
        "georgia institute of technology": "georgia tech",
    }
    for university in (u.strip() for u in (universities or []) if isinstance(u, str) and u.strip()):
        configured = _normalise(university)
        if normalized == configured:
            return True, university, text
        alias = aliases.get(configured)
        if alias and normalized == alias:
            return True, university, text
    return False, text or "N/A", text or "No configured target university"


def detect_indian_context(profile: ProfileData, records: list[dict]) -> tuple[bool, str]:
    """Use public location/profile context or education context, never names/photos."""
    location_context = " ".join((profile.location, profile.summary, profile.headline))
    if INDIA_CONTEXT_PATTERN.search(location_context):
        return True, "Public India-related location/profile context"
    education_context = " ".join(record.get("raw_text", "") for record in records)
    if INDIA_CONTEXT_PATTERN.search(education_context):
        return True, "Indian/India-related education context"
    return False, "No reliable India-context evidence"


def _is_postgraduate(record: dict) -> bool:
    return bool(MASTER_PATTERN.search(record.get("degree", "") or record.get("raw_text", "")))


def _record_status(record: dict, year: int | None) -> str:
    status = record.get("status", "unknown")
    if status == "current" or record.get("current"):
        return "Current"
    if status == "completed" and year is not None and year >= 2026:
        return "Completed"
    return "Unknown"


def qualify_candidate(profile: ProfileData, universities: Iterable[str] | None = None) -> dict:
    """Qualify Indian-context candidates with a target postgraduate record."""
    configured = list(universities or [])
    education_source = profile.education if profile.education != "N/A" else profile.source_text
    records = parse_education_records(education_source, configured) if education_source else profile.education_records
    india_pass, india_evidence = detect_indian_context(profile, records)
    postgraduate_records = [record for record in records if _is_postgraduate(record)]
    selected = None
    rejection_reasons: list[str] = []

    for record in postgraduate_records:
        year = extract_expected_graduation_year(record)
        status = _record_status(record, year)
        university_pass, university, university_evidence = match_target_university(record, configured)
        valid_timing = status == "Current" or (status == "Completed" and year is not None and year >= 2026)
        if india_pass and university_pass and valid_timing:
            selected = {
                "record": record, "degree": _degree_label(record), "field": record.get("field", "N/A"),
                "university": university, "university_evidence": university_evidence,
                "year": year, "start_year": record.get("start_year", "N/A"), "status": status,
            }
            break

    if not india_pass:
        rejection_reasons.append(india_evidence)
    if not postgraduate_records:
        rejection_reasons.append("No Master's/postgraduate education record")
    if postgraduate_records and not any(match_target_university(record, configured)[0] for record in postgraduate_records):
        rejection_reasons.append("Master's university not in target US list")
    if postgraduate_records and not any(
        _record_status(record, extract_expected_graduation_year(record)) in ("Current", "Completed")
        and extract_expected_graduation_year(record) is not None
        for record in postgraduate_records
    ):
        rejection_reasons.append("Master's completed before 2026 or education dates unclear")

    result = {
        "qualified": selected is not None,
        "indian_context_result": "PASS" if india_pass else "FAIL",
        "indian_context": india_evidence,
        "education_records": records,
        "masters_result": "PASS" if postgraduate_records else "FAIL",
        "degree": selected["degree"] if selected else "N/A",
        "field": selected["field"] if selected else "N/A",
        "university_result": "PASS" if selected and selected["university"] else "FAIL",
        "university": selected["university"] if selected else "N/A",
        "graduation_result": "PASS" if selected and selected["year"] is not None else "FAIL",
        "graduation_year": selected["year"] if selected else "N/A",
        "status": selected["status"] if selected else "Unknown",
        "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
        "qualification_reason": "Indian context; target postgraduate record; configured university; current or completion >= 2026" if selected else "",
    }
    if selected:
        profile.degree = selected["degree"]
        profile.university = selected["university"]
        profile.graduation_year = str(selected["year"] or "N/A")
        profile.start_year = str(selected["start_year"])
        profile.field = selected["field"]
        profile.graduation_status = selected["status"]
        profile.indian_context = india_evidence if hasattr(profile, "indian_context") else profile.location
        profile.qualification_reason = result["qualification_reason"]
    return result
