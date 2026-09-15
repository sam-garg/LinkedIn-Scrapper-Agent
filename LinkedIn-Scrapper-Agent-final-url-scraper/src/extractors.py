"""
extractors.py
-------------
Independent field-extraction functions.

Each function accepts page text (a plain string) and returns either the
extracted value or the sentinel ``"N/A"`` when the field cannot be found.

Design principles
-----------------
- Pure functions: no Playwright calls, no side effects.
- Each function is independently testable without a browser.
- Use regex patterns that are robust to minor formatting changes.
- Never invent or hallucinate data.
- Return "N/A" consistently for missing fields (never None or empty string).
"""

import re


def parse_education_records(text: str, universities: list[str]) -> list[dict]:
    """Parse individual education records without using headline/job text."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    degree_pattern = re.compile(
        r"\b(?:ms|m\.s\.?|mba|meng|m\.eng\.?|mem|master(?:'s|s)?|"
        r"master of|bachelor(?:'s|s)?|b\.tech|b\.s\.?)\b", re.IGNORECASE,
    )
    records: list[dict] = []
    for index, line in enumerate(lines):
        if not degree_pattern.search(line):
            continue
        start = index
        if index > 0 and not degree_pattern.search(lines[index - 1]) and re.search(
            r"university|college|institute|school|polytechnic", lines[index - 1], re.IGNORECASE
        ):
            start = index - 1
        end = index + 1
        while end < len(lines) and end < index + 4:
            if degree_pattern.search(lines[end]):
                break
            end += 1
        record_lines = lines[start:end]
        raw = " | ".join(record_lines)
        institution = extract_university("\n".join(record_lines), universities)
        years = re.findall(r"\b20\d{2}\b", raw)
        explicit_current = bool(re.search(
            r"currently|pursuing|candidate|expected|graduat(?:ing|ion)|class of|"
            r"present", raw, re.IGNORECASE,
        ))
        completed = bool(re.search(
            r"\b(?:graduated|completed|alumni|alumnus|alumna)\b", raw, re.IGNORECASE
        ))
        status = "current" if explicit_current else "completed" if completed else "unknown"
        if years and not explicit_current and not completed:
            status = "current" if int(years[-1]) >= 2026 else "completed"
        records.append({
            "university": institution,
            "institution": institution,
            "degree": line,
            "field": re.sub(r"\b(?:master|ms|m\.s\.?|mba|meng|m\.eng\.?|mem|bachelor|b\.tech|b\.s\.?)\b", "", line, flags=re.IGNORECASE).strip(" ,-"),
            "start_year": years[0] if years else "N/A",
            "end_year": years[-1] if years else "N/A",
            "graduation_year": years[-1] if years else "N/A",
            "status": status,
            "current": status == "current",
            "raw_text": raw,
        })
    return records


def extract_education_records(text: str, universities: list[str]) -> list[dict]:
    """Backward-compatible alias for the structured education parser."""
    return parse_education_records(text, universities)


# ------------------------------------------------------------------ #
# Name
# ------------------------------------------------------------------ #

def extract_name(url: str, page_text: str) -> str:
    """
    Extract a person's name from the LinkedIn profile page text.

    Strategy:
    1. Look for a capitalised two-to-four word name at the start of the text.
    2. Fall back to deriving a name from the URL slug.

    Args:
        url:       The profile URL (used as a fallback).
        page_text: Full visible text of the profile page.

    Returns:
        Name string, or "N/A" if it cannot be determined.
    """
    # Strategy 1: Heading-style name at the top of the page text
    heading_match = re.search(
        r"^([A-Z][a-zA-ZÀ-ÖØ-öø-ÿ'\-]+(?: [A-Z][a-zA-ZÀ-ÖØ-öø-ÿ'\-]+){1,3})",
        page_text.strip(),
    )
    if heading_match:
        candidate = heading_match.group(1).strip()
        if 2 <= len(candidate.split()) <= 4:
            return candidate

    # Strategy 2: Derive from the URL slug
    match = re.search(r"linkedin\.com/in/([^/?#\s]+)", url)
    if match:
        slug = match.group(1)
        # Strip trailing IDs like -a1b2c3
        slug = re.sub(r"-[a-f0-9]{6,}$", "", slug)
        name = slug.replace("-", " ").title()
        if name:
            return name

    return "N/A"


# ------------------------------------------------------------------ #
# Email
# ------------------------------------------------------------------ #

def extract_email(text: str) -> str:
    """
    Extract an email address from profile text.

    Supports:
    - Standard format: ``name@domain.com``
    - Obfuscated format: ``name at domain dot com``

    Only extracts emails that are explicitly visible in the text.
    Does not access private databases or contact-info APIs.

    Args:
        text: Page text or contact-info dialog text.

    Returns:
        First valid email found, or "N/A".
    """
    # Standard email pattern
    emails = re.findall(
        r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
        text,
    )
    # Filter out image/asset false positives
    valid = [
        e for e in emails
        if not re.search(r"\.(png|jpg|jpeg|gif|css|js|svg|ico|woff)$", e, re.IGNORECASE)
        and not e.startswith("@")
    ]
    if valid:
        return valid[0]

    # Obfuscated: "name at domain dot com"
    obf = re.search(
        r"([A-Za-z0-9._%+\-]+)\s+(?:at|AT)\s+([A-Za-z0-9.\-]+)\s+(?:dot|DOT)\s+([A-Za-z]{2,})",
        text,
    )
    if obf:
        return f"{obf.group(1)}@{obf.group(2)}.{obf.group(3)}"

    return "N/A"


# ------------------------------------------------------------------ #
# Phone / contact
# ------------------------------------------------------------------ #

def extract_phone(text: str) -> str:
    """
    Extract a publicly visible phone number from profile text.

    Supports common international and US formats.
    Only extracts numbers explicitly present in the text.

    Args:
        text: Page text or contact-info dialog text.

    Returns:
        Phone number string, or "N/A".
    """
    patterns = [
        # Indian mobile: +91 or leading 6-9 digit
        r"\+91[\s\-]?[6-9]\d{9}",
        r"(?<!\d)[6-9]\d{9}(?!\d)",
        # US: +1 (optional), then area code + 7 digits
        r"\+1[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}",
        r"\(?\d{3}\)?[\s\-\.]\d{3}[\s\-\.]\d{4}",
        # International: +XX ...
        r"\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{3,5}[\s\-]?\d{4,6}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group().strip()
    return "N/A"


# ------------------------------------------------------------------ #
# Summary / about
# ------------------------------------------------------------------ #

def extract_summary(page_text: str, max_length: int = 400) -> str:
    """
    Extract a summary/about snippet from the page text.

    Collapses whitespace and truncates at *max_length* characters.

    Args:
        page_text:  Full visible text of the profile page.
        max_length: Maximum number of characters to return.

    Returns:
        Summary string, or "N/A" if the text is empty.
    """
    if not page_text or not page_text.strip():
        return "N/A"
    clean = re.sub(r"\s+", " ", page_text).strip()
    if len(clean) > max_length:
        return clean[:max_length] + "…"
    return clean


# ------------------------------------------------------------------ #
# Technologies / skills
# ------------------------------------------------------------------ #

def extract_technologies(text: str, keywords: list[str]) -> str:
    """
    Find technology keywords present in the profile text.

    Uses case-insensitive word-boundary matching to reduce false positives
    (e.g. "Go" should not match "Google").

    Args:
        text:     Profile page text.
        keywords: List of technology keyword strings from config.

    Returns:
        Comma-separated string of matched technologies, or "N/A".
    """
    text_lower = text.lower()
    found: list[str] = []
    for tech in keywords:
        # Build a word-boundary regex for each keyword.
        # Escape special regex chars in the keyword (e.g. "C++", ".NET").
        pattern = r"\b" + re.escape(tech.lower()) + r"\b"
        if re.search(pattern, text_lower):
            found.append(tech)
    return ", ".join(found) if found else "N/A"


# ------------------------------------------------------------------ #
# University
# ------------------------------------------------------------------ #

# University abbreviation shortcuts that don't appear verbatim in the whitelist
_UNIVERSITY_SHORTCUTS: dict[str, str] = {
    "NORTHEASTERN": "Northeastern University",
    "ARIZONA STATE": "Arizona State University",
    "ASU": "Arizona State University",
    "NYU": "New York University",
    "NEW YORK UNIVERSITY": "New York University",
    "STANFORD": "Stanford University",
    "USC": "University of Southern California",
    "SJSU": "San Jose State University",
    "SAN JOSE STATE": "San Jose State University",
    "PACE": "Pace University",
    "STEVENS": "Stevens Institute of Technology",
    "GEORGIA TECH": "Georgia Institute of Technology",
    "CMU": "Carnegie Mellon University",
    "CARNEGIE MELLON": "Carnegie Mellon University",
    "UT DALLAS": "University of Texas at Dallas",
    "UTD": "University of Texas at Dallas",
    "NJIT": "New Jersey Institute of Technology",
    "GEORGE MASON": "George Mason University",
    "MIT": "Massachusetts Institute of Technology",
    "UCLA": "University of California Los Angeles",
    "UC BERKELEY": "University of California Berkeley",
    "BERKELEY": "University of California Berkeley",
    "UIUC": "University of Illinois Urbana Champaign",
    "UMD": "University of Maryland",
}

# Keywords that indicate a likely Indian institution (used to filter false positives)
_INDIAN_KEYWORDS: tuple[str, ...] = (
    "Delhi", "Mumbai", "Pune", "Anna", "Amity", "SRM", "VIT", "BITS",
    "IIT", "NIT", "Manipal", "JNTU", "KIIT", "Chandigarh", "Osmania",
    "Madras", "Kharagpur", "Kanpur", "Roorkee", "Guwahati", "Indore",
    "Bangalore", "Hyderabad", "Noida", "Vellore", "Pilani", "Symbiosis",
    "NMIMS", "Jadavpur", "Sathyabama", "Banasthali", "Galgotias", "India",
)


def extract_university(text: str, universities: list[str]) -> str:
    """
    Extract the name of a US university from profile text.

    Matching order:
    1. Full whitelist match (from ``config/universities.json``).
    2. Abbreviation / shortcode table.
    3. Regex fallback for lines containing "University", "College",
       "Institute of Technology", etc. — excluding Indian institutions.

    Args:
        text:         Profile page text.
        universities: List of university names loaded from the whitelist.

    Returns:
        University name string, or "N/A".
    """
    # 1. Whitelist match (case-insensitive word boundary)
    for uni in universities:
        if not uni or not isinstance(uni, str):
            continue
        pattern = r"\b" + re.escape(uni.strip()) + r"\b"
        if re.search(pattern, text, re.IGNORECASE):
            return uni.strip()

    # 2. Shortcode overrides
    text_upper = text.upper()
    for keyword, full_name in _UNIVERSITY_SHORTCUTS.items():
        if re.search(r"\b" + re.escape(keyword) + r"\b", text_upper):
            return full_name

    # 3. Regex fallback
    segments = re.split(r"[,|•\n]", text)
    for seg in segments:
        seg = seg.strip()
        has_edu_word = re.search(
            r"\b(University|College|Institute of Technology|Polytechnic|School of)\b",
            seg,
            re.IGNORECASE,
        )
        if has_edu_word and 10 < len(seg) < 120:
            is_indian = any(
                re.search(r"\b" + re.escape(ind) + r"\b", seg, re.IGNORECASE)
                for ind in _INDIAN_KEYWORDS
            )
            if not is_indian:
                return seg.strip()

    return "N/A"


# ------------------------------------------------------------------ #
# Degree
# ------------------------------------------------------------------ #

def extract_degree(text: str) -> str:
    """
    Extract the highest degree label found in the profile text.

    Returns a normalised degree label (e.g. "Master of Science (MS)") or "N/A".

    Args:
        text: Profile page text.
    """
    combined = text.upper()

    if "MBA" in combined:
        return "MBA"
    if re.search(r"\bMASTER OF SCIENCE\b|\bMS IN\b|\bM\.S\.\b|\bM\.S\b", combined):
        return "Master of Science (MS)"
    if re.search(r"\bMASTER OF ENGINEERING\b|\bMENG\b|\bM\.ENG\b", combined):
        return "Master of Engineering (M.Eng)"
    if re.search(r"\bMEM\b|\bMASTER OF ENGINEERING MANAGEMENT\b", combined):
        return "Master of Engineering Management (MEM)"
    if re.search(r"\bMASTER OF\b|\bMASTER'S\b|\bMASTER DEGREE\b", combined):
        return "Master's Degree"
    if re.search(r"\bPHD\b|\bPH\.D\b|\bDOCTOR OF\b|\bDOCTORATE\b", combined):
        return "PhD / Doctorate"
    if re.search(r"\bBACHELOR OF\b|\bB\.S\.\b|\bB\.E\.\b|\bBE\b|\bBTECH\b|\bB\.TECH\b", combined):
        return "Bachelor's Degree"

    return "N/A"


# ------------------------------------------------------------------ #
# Graduation year
# ------------------------------------------------------------------ #

def extract_graduation_year(text: str) -> str:
    """
    Extract a graduation year from the profile text.

    Prefers recent years (2020–2028) and supports short-form notation
    like ``'24`` or ``'25``.

    Args:
        text: Profile page text.

    Returns:
        Four-digit year string, or "N/A".
    """
    combined = text.upper()

    # Prefer recent graduation years
    match = re.search(r"\b(202[0-9])\b", combined)
    if match:
        return match.group(1)

    # Short form: '24, '25, etc.
    match_short = re.search(r"'(2[0-9])\b", combined)
    if match_short:
        return "20" + match_short.group(1)

    # Broader fallback: any plausible year
    years = re.findall(r"\b(20(?:1[5-9]|2[0-9]))\b", text)
    if years:
        return sorted(set(years), reverse=True)[0]

    return "N/A"


# ------------------------------------------------------------------ #
# Company
# ------------------------------------------------------------------ #

def extract_company(page_text: str) -> str:
    """
    Extract the current company name from the profile page text.

    Looks for typical LinkedIn patterns like "at <Company>",
    "Currently at <Company>", or lines following "Experience".

    Args:
        page_text: Full visible text of the profile page.

    Returns:
        Company name string, or "N/A".
    """
    # Pattern: "at Company Name" — common in headline/experience sections
    match = re.search(
        r"\bat\s+([A-Z][A-Za-z0-9&,.\s'\-]{2,40}?)(?:\s*[·|•]|\s*\n|$)",
        page_text,
    )
    if match:
        candidate = match.group(1).strip()
        if len(candidate) > 2:
            return candidate

    # Fallback: line after the word "Experience"
    exp_match = re.search(
        r"Experience\s*\n+\s*([A-Z][A-Za-z0-9&,.\s'\-]{2,50}?)\n",
        page_text,
        re.IGNORECASE,
    )
    if exp_match:
        return exp_match.group(1).strip()

    return "N/A"


# ------------------------------------------------------------------ #
# Job title
# ------------------------------------------------------------------ #

def extract_job_title(page_text: str) -> str:
    """
    Extract the current job title from the profile page text.

    Looks for common role patterns or the headline before the company name.

    Args:
        page_text: Full visible text of the profile page.

    Returns:
        Job title string, or "N/A".
    """
    role_keywords = (
        "Engineer", "Developer", "Scientist", "Analyst", "Architect",
        "Manager", "Director", "Lead", "Consultant", "Designer",
        "Researcher", "Specialist", "Intern", "Associate", "Officer",
    )
    for keyword in role_keywords:
        match = re.search(
            rf"([A-Z][A-Za-z\s,./\-]{{3,60}}?{keyword}[A-Za-z\s,./\-]{{0,30}}?)(?:\n|at\s|·|$)",
            page_text,
        )
        if match:
            candidate = match.group(1).strip()
            if 4 < len(candidate) < 80:
                return candidate

    return "N/A"


# ------------------------------------------------------------------ #
# Location
# ------------------------------------------------------------------ #

def extract_location(page_text: str) -> str:
    """
    Extract the geographic location listed on the profile.

    Looks for "City, State" or "City, Country" patterns common in
    LinkedIn profiles.

    Args:
        page_text: Full visible text of the profile page.

    Returns:
        Location string, or "N/A".
    """
    # City, State/Country  (e.g. "San Francisco, California", "New York, NY")
    match = re.search(
        r"\b([A-Z][a-zA-Z\s]{2,30}),\s*([A-Z][a-zA-Z\s]{2,30})\b",
        page_text,
    )
    if match:
        return f"{match.group(1).strip()}, {match.group(2).strip()}"

    # Fallback: US state names
    us_states = (
        "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
        "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
        "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
        "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
        "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
        "New Hampshire", "New Jersey", "New Mexico", "New York",
        "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
        "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
        "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
        "West Virginia", "Wisconsin", "Wyoming", "United States",
    )
    for state in us_states:
        if re.search(r"\b" + re.escape(state) + r"\b", page_text):
            return state

    return "N/A"


# ------------------------------------------------------------------ #
# Resume links
# ------------------------------------------------------------------ #

def extract_resume_links(text: str) -> str:
    """
    Detect publicly visible resume or CV references in the profile text.

    Supports:
    - Direct URLs (Google Drive, Dropbox, Notion, Canva, PDF links, bit.ly, etc.)
    - Textual mentions of "resume" or "CV" (returns a note string).

    We never download private files automatically.

    Args:
        text: Profile page text or bio/about text.

    Returns:
        URL string, note string, or "N/A".
    """
    # Look for common resume-hosting URLs
    resume_urls = re.findall(
        r"https?://(?:"
        r"drive\.google\.com|"
        r"docs\.google\.com|"
        r"dropbox\.com|"
        r"notion\.site|"
        r"notion\.so|"
        r"canva\.com|"
        r"cutt\.ly|"
        r"bit\.ly|"
        r"tinyurl\.com|"
        r"resume\.io|"
        r"flowcv\.com"
        r")[^\s)\]>\"']+|"
        r"https?://[^\s)\]>\"']+\.pdf",
        text,
        re.IGNORECASE,
    )
    if resume_urls:
        unique = sorted(set(resume_urls))
        return ", ".join(unique)

    # Textual reference to a resume/CV
    if re.search(r"\b(resume|cv|curriculum vitae)\b", text, re.IGNORECASE):
        return "Resume mentioned in profile"

    return "N/A"
