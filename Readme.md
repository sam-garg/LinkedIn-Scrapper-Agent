# LinkedIn Scraper + Education Filter Pipeline

This repository implements a LinkedIn profile screening workflow aimed at identifying candidates who meet a specific academic pattern:

- Undergraduate education from India
- Postgraduate education abroad
- Postgraduate degree year within a target range
- Only profiles with clear evidence are kept

The current project is a practical pipeline of Python scripts and Playwright-based scraping, not a full multi-agent orchestration framework.

---

## Overview

The workflow is built around the following idea:

1. Collect candidate LinkedIn profile URLs.
2. Open each profile and extract the education section.
3. Save the education data for review or processing.
4. Use Gemini to decide whether the profile matches the filtering rules.
5. Keep only profiles that satisfy the required UG/PG logic.
6. Export the selected URLs and supporting extracted profile data.

This is designed for a very specific use case: filtering profiles for international postgraduate study candidates based on education history.

---

## Pipeline Flow

```text
linkedin_urls.json
        |
        v
filter_education.py
        |
        v
education_extracted.txt
        |
        v
main.py
        |
        +--> filter_prompt.txt
        |
        +--> filter_results.txt
        |
        +--> selected_urls.json
        |
        v
scraper_authenticated.py
        |
        +--> linkedin_profiles_data.txt
        +--> extracted_profiles.txt
        |
        v
filter_pg_students.py
        |
        +--> Final filtered candidate URLs / classification results
```

---

## Files in this Repository

### Core scripts

- `main.py`  
  Reads the extracted education text and a filtering prompt, splits the raw profile content, extracts LinkedIn URLs, and uses Gemini to decide whether to keep each profile.

- `filter_education.py`  
  Opens each LinkedIn profile in a browser session, looks for the education section, and saves the extracted education details to `education_extracted.txt`.

- `scraper_authenticated.py`  
  Reads `selected_urls.json`, loads each selected profile, extracts raw profile text, and stores the result in `linkedin_profiles_data.txt` and `extracted_profiles.txt`.

- `filter_pg_students.py`  
  Performs a stricter education-only screening pass. It opens profiles, scrapes only the Education section, and uses Gemini to determine whether the UG is Indian and the PG is outside India, with a valid postgraduate year range.

### Input and output files

- `linkedin_urls.json`  
  Source list of LinkedIn profile URLs.

- `selected_urls.json`  
  URLs selected by the filtering logic.

- `education_extracted.txt`  
  Consolidated education content extracted from raw profiles.

- `filter_prompt.txt`  
  The decision prompt used by Gemini to classify a profile as KEEP or REJECT.

- `filter_results.txt`  
  Final output showing the Gemini decision for each profile.

- `linkedin_profiles_data.txt`  
  Raw profile text extracted from selected LinkedIn pages.

- `extracted_profiles.txt`  
  Structured or normalized output from the authenticated scraping pass.

---

## Actual Business Rule

The filtering logic follows the rules defined in `filter_prompt.txt` and implemented in `filter_pg_students.py`.

The target profile is:

- UG education is from India
- PG education is from outside India
- Both UG and PG are supported by clear evidence in the profile
- The PG is an actual postgraduate degree, not a short course or certificate
- PG year is between 2024 and 2028

The project is tuned for Indian-student filtering and international postgraduate admissions screening.

---

## Required Environment

Create a `.env` file in the project root with the required API key:

```env
GEMINI_API_KEY=your_google_gemini_api_key
```

For the authenticated scraping flow, additional session data may be required via a LinkedIn browser session or a stored Playwright state file such as `storage_state.json`.

---

## Installation

```bash
pip install -r requirements.txt
playwright install chromium
```

If you are using a local Python environment:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

---

## Typical Run Order

### 1. Extract education from profile URLs

```bash
python filter_education.py
```

This writes education data into `education_extracted.txt`.

### 2. Filter with Gemini using the prompt

```bash
python main.py
```

This reads the education text and prompt, then writes selected candidates into `selected_urls.json` and the decision results into `filter_results.txt`.

### 3. Scrape full selected profiles

```bash
python scraper_authenticated.py
```

This reads the selected URLs and produces raw and extracted profile data.

### 4. Run the stricter PG/UG classification pass

```bash
python filter_pg_students.py --urls linkedin_urls.json --out filtered_candidates.json
```

This is the final filter pass that checks for Indian UG + foreign PG + valid PG year window.

---

## Notes on the Current Implementation

- The repository is focused on education-based candidate filtering rather than a generic resume / portfolio enrichment engine.
- The scraping logic depends on Playwright and browser session state.
- Gemini is used as the classification model for KEEP / REJECT decisions.
- The project currently expects a real LinkedIn login session or stored browser context for authenticated profile access in some stages.
- The logic is highly targeted to one recruitment/academic screening use case and is not a universal candidate pipeline.

---

## Example Output Pattern

A selected profile is typically kept when Gemini produces a result such as:

```text
FINAL DECISION: KEEP

NAME: John Doe
UG_INSTITUTION: Indian Institute of Technology Delhi
UG_COUNTRY: India
PG_INSTITUTION: University of Michigan
PG_COUNTRY: United States
PG_START_YEAR: 2024
PG_END_YEAR: 2026
```

A rejected profile usually fails because:

- UG is not in India
- PG is not clearly abroad
- PG is not a real degree
- The profile lacks evidence
- The PG year is outside the required window

---

## Summary

This repository is best understood as a LinkedIn education-based candidate filter pipeline:

- gather URLs
- scrape education data
- classify with Gemini
- keep only Indian UG + foreign PG matches
- export selected profile URLs and extracted evidence

It is a focused screening workflow for identifying high-potential candidates based on study history, not a broad data warehouse or multi-source enrichment system.

---

## License

This project is provided as-is for internal or research use. Add a license file if you want to publish it publicly.
