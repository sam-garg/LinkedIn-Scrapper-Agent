"""
filters.py
----------
Profile filtering functions.

All filters receive a ProfileData instance and return True/False.
They are pure functions with no side effects — safe to test without
a browser or network connection.

Available filters
-----------------
- is_postgraduate(text)          → bool, normalised degree label
- matches_university(profile, target_university, universities)  → bool
- matches_technology(profile, required_techs)                   → bool
- apply_filters(profile, ...)    → bool  (convenience combinator)
"""

import re
from typing import TYPE_CHECKING

from src.models import ProfileData

if TYPE_CHECKING:
    pass


# ------------------------------------------------------------------ #
# Postgraduate / Master's degree detection
# ------------------------------------------------------------------ #

# Phrases that strongly indicate a postgraduate degree
_MASTERS_INDICATOR_PHRASES: tuple[str, ...] = (
    "MS IN", "M.S. IN", "M.S IN", "MASTER OF",
    "MASTER'S", "MASTER DEGREE", "MASTER DEGR",
    "MBA", "MEM ", "MENG", "M.ENG",
    "POSTGRADUATE", "POST-GRADUATE",
    "MS GRADUATE", "MS GRAD",
    "MASTER GRADUATE", "MASTER'S GRADUATE",
    "MASTER OF SCIENCE", "MASTER OF ENGINEERING",
    "MASTER OF BUSINESS", "MASTER OF MANAGEMENT",
)

_MASTERS_PATTERN = re.compile(
    r"\b(MS|M\.S\.|MASTER|MBA|MEM|MENG|M\.ENG|PHD|PH\.D)\b"
)


def is_postgraduate(text: str) -> tuple[bool, str]:
    """
    Determine whether the text indicates a postgraduate degree.

    Checks for Master's, MBA, MEng, MEM, PhD, and postgraduate phrases.

    Args:
        text: Raw profile page text (or degree field value).

    Returns:
        A tuple of (is_postgrad: bool, degree_label: str).
        If not postgrad, degree_label is an empty string.

    Examples::

        >>> is_postgraduate("MS in Computer Science at Northeastern University")
        (True, 'Master of Science (MS)')
        >>> is_postgraduate("B.S. Computer Engineering")
        (False, '')
    """
    combined = text.upper()

    has_indicator = any(sig in combined for sig in _MASTERS_INDICATOR_PHRASES)
    has_pattern = bool(_MASTERS_PATTERN.search(combined))

    if not (has_indicator or has_pattern):
        return False, ""

    # Determine the normalised label
    if "PHD" in combined or re.search(r"\bPH\.D\b", combined):
        return True, "PhD / Doctorate"
    if "MBA" in combined:
        return True, "MBA"
    if "MASTER OF SCIENCE" in combined or "MS IN" in combined or re.search(r"\bM\.S\b|\bM\.S\.", combined):
        return True, "Master of Science (MS)"
    if "MASTER OF ENGINEERING" in combined or "MENG" in combined or "M.ENG" in combined:
        return True, "Master of Engineering (M.Eng)"
    if "MEM " in combined or "MASTER OF ENGINEERING MANAGEMENT" in combined:
        return True, "Master of Engineering Management (MEM)"
    if "MASTER OF BUSINESS" in combined or "MASTER OF MANAGEMENT" in combined:
        return True, "Master of Business Administration (MBA)"
    if has_indicator or has_pattern:
        return True, "Master's Degree"

    return False, ""


# ------------------------------------------------------------------ #
# University matching
# ------------------------------------------------------------------ #

def matches_university(
    profile: ProfileData,
    target: str,
    universities: list[str],
) -> bool:
    """
    Check whether the profile's university matches the requested target.

    Matching is case-insensitive substring.  If ``target`` is empty or
    None, returns True (no filter applied).

    Args:
        profile:      ProfileData to check.
        target:       University name requested via CLI (e.g. "Stanford").
        universities: Full whitelist from config (used to validate the target).

    Returns:
        True if the profile university matches the target (or no target set).
    """
    if not target:
        return True

    profile_uni = profile.university.lower()
    target_lower = target.lower()

    # Direct substring match on the stored university field
    if target_lower in profile_uni or profile_uni in target_lower:
        return True

    return False


def is_us_university(university: str, universities: list[str]) -> bool:
    """
    Return True if *university* is in the US whitelist.

    Args:
        university:   University name string to check.
        universities: Loaded whitelist from config/universities.json.
    """
    if not university or university == "N/A":
        return False
    uni_lower = university.lower()
    for u in universities:
        if u.lower() == uni_lower or uni_lower in u.lower() or u.lower() in uni_lower:
            return True
    return False


# ------------------------------------------------------------------ #
# Technology matching
# ------------------------------------------------------------------ #

def matches_technology(profile: ProfileData, required_techs: list[str]) -> bool:
    """
    Check whether the profile's technology field contains any of the
    required technologies.

    Matching is case-insensitive.  If ``required_techs`` is empty,
    returns True (no filter applied).

    Args:
        profile:       ProfileData to check.
        required_techs: List of technology keyword strings.

    Returns:
        True if any required technology is found in the profile, or if
        ``required_techs`` is empty.
    """
    if not required_techs:
        return True

    if profile.technology == "N/A":
        return False

    tech_lower = profile.technology.lower()
    return any(t.lower() in tech_lower for t in required_techs)


# ------------------------------------------------------------------ #
# Combined filter
# ------------------------------------------------------------------ #

def apply_filters(
    profile: ProfileData,
    *,
    university_filter: bool = False,
    target_university: str | None = None,
    postgrad_filter: bool = False,
    required_techs: list[str] | None = None,
    universities: list[str] | None = None,
) -> tuple[bool, str]:
    """
    Apply all active filters to a profile and return a pass/fail result.

    Filters are applied in this order (any failure short-circuits):
    1. University filter (if ``university_filter`` is True or ``target_university`` is set).
    2. Postgraduate degree filter (if ``postgrad_filter`` is True).
    3. Technology filter (if ``required_techs`` is non-empty).

    Args:
        profile:           ProfileData to evaluate.
        university_filter: If True, reject profiles with no matched US university.
        target_university: Specific university name to require.
        postgrad_filter:   If True, reject profiles without a postgraduate degree.
        required_techs:    List of required technology strings.
        universities:      US university whitelist (from config).

    Returns:
        (passed: bool, skip_reason: str)
        ``skip_reason`` is empty when ``passed`` is True.
    """
    unis = universities or []

    # ---- University filter ----
    if university_filter or target_university:
        if profile.university == "N/A":
            return False, "No US university found in profile"
        if university_filter and not is_us_university(profile.university, unis):
            return False, f"University not in whitelist: {profile.university}"
        if target_university and not matches_university(profile, target_university, unis):
            return False, f"University does not match '{target_university}'"

    # ---- Postgraduate filter ----
    if postgrad_filter:
        # Check the already-extracted degree field first
        passed_pg, _ = is_postgraduate(profile.degree)
        if not passed_pg:
            # Also check the full education/summary fields as fallback
            combined = " ".join([
                profile.degree, profile.education,
                profile.headline, profile.summary,
            ])
            passed_pg, _ = is_postgraduate(combined)
        if not passed_pg:
            return False, "No postgraduate degree signal found"

    # ---- Technology filter ----
    if required_techs:
        if not matches_technology(profile, required_techs):
            return (
                False,
                f"Required technologies not found: {', '.join(required_techs)}",
            )

    return True, ""
