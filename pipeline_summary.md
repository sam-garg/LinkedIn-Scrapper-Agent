# Candidate Sourcing & Enrichment Pipeline Summary

This document provides a comprehensive technical overview of the two projects contained within this directory:
1. **`LinkedIn-Scrapper-Agent-final-url-scraper`** (Stage 1: Discovery & URL Scraping)
2. **`LinkedIn-Scrapper-Agent-filteration-and-scraper-agent`** (Stage 2: Scraping, Filtering & AI Enrichment)

---

## 📌 Architecture Overview & Data Flow

```
+-------------------------------------------------------------------+
|               STAGE 1: URL & LEAD DISCOVERY                       |
|           (LinkedIn-Scrapper-Agent-final-url-scraper)             |
+-------------------------------------------------------------------+
  • Input: Search Keywords ("MBA", "Software Engineer") / Target Universities
  • Action: Playwright fast card search (No individual profile navigation)
  • Output: List of canonical LinkedIn URLs & card-visible lead records
                                 │
                                 ▼
+-------------------------------------------------------------------+
|            STAGE 2: SCRAPING, FILTERING & ENRICHMENT             |
|    (LinkedIn-Scrapper-Agent-filteration-and-scraper-agent)        |
+-------------------------------------------------------------------+
  • Input: Discovered LinkedIn URLs / Raw Profile Text
  • Action:
      1. Authenticated Playwright scraping of profile & education
      2. Document Sub-Agent: Resume parsing (PDF/DOCX) + OCR if null fields
      3. Portfolio/GitHub scraping if missing info persists
      4. AI Evaluation: Google Gemini filters profiles based on criteria
  • Output: Qualified JSON profiles, detailed decision text logs, Supabase sync
```

---

## 📁 1. `LinkedIn-Scrapper-Agent-final-url-scraper`

### 💡 Summary
An **upstream discovery tool** designed for fast, high-volume collection of LinkedIn profile URLs. It automates LinkedIn search result page navigation using a Playwright browser instance connected to a persistent user session.

> [!NOTE]
> This tool does **not** visit individual profile pages or scrape full candidate details. It purely collects URLs and card-visible metadata to keep scraping speed high and minimize bot detection risks.

### ⚙️ How It Works
1. **Persistent Authentication**: Uses Playwright's chromium browser context backed by `data/browser_profile/`. The user manually logs into LinkedIn once; all subsequent runs reuse the session.
2. **Query Expansion**: Accepts single query strings or uses `--postgraduate` flag to automatically expand search terms using target universities from `config/universities.json`.
3. **Card Extraction**: Paginates through search result pages (`/search/results/people/`) and extracts the profile URL, name, headline, and location directly from result cards.
4. **Safety & Deduplication**: Checks incoming URLs against existing datasets to avoid duplicates. If LinkedIn triggers a CAPTCHA or security wall, the scraper halts safely and preserves collected data.

### 📥 Inputs Required
* **Command Line Arguments**: `--query`, `--postgraduate`, `--limit`, `--location`.
* **Configuration Files**:
  * [`config/settings.json`](file:///c:/Users/samga/Downloads/Quick%20Share/RGTVertex/Final_Scrapper_Merging/LinkedIn-Scrapper-Agent-final-url-scraper/config/settings.json): Timeouts, pagination limits, and rate-limit text signatures.
  * [`config/universities.json`](file:///c:/Users/samga/Downloads/Quick%20Share/RGTVertex/Final_Scrapper_Merging/LinkedIn-Scrapper-Agent-final-url-scraper/config/universities.json): List of target universities for automated query expansion.
* **Environment Variables**: `.env` (`SCRAPER_HEADLESS`, limits, optional credentials).
* **Active Session**: Persistent browser profile logged into LinkedIn.

### 📤 Outputs Produced
* **URL List**: Canonical, deduplicated profile URLs (one URL per line).
* **Leads Dataset**: CSV spreadsheet of card-visible lead attributes.

### 🗄️ Storage Locations
* **Plain Text URLs**: `data/output/linkedin_urls.txt`
* **CSV Spreadsheet**: `data/output/linkedin_leads.csv`
* **Browser Cookies & Session**: `data/browser_profile/`

---

## 📁 2. `LinkedIn-Scrapper-Agent-filteration-and-scraper-agent`

### 💡 Summary
A **downstream intelligence & enrichment engine** that processes candidate profiles, enriches incomplete candidate records using multi-source data (resumes, portfolios, GitHub), and uses Google Gemini AI to evaluate candidate qualification against specific filters.

### ⚙️ How It Works
1. **Profile Ingestion**: Ingests candidate URLs or raw extracted profile data.
2. **Authenticated Scraping**: Uses Playwright to extract full profile sections (specifically Education & Work Experience).
3. **Multi-Agent Fallback Cascading**:
   * If LinkedIn data contains null/missing fields, the **Resume Sub-Agent** processes attached PDF/DOCX resumes using `pdfplumber` or Tesseract OCR.
   * If fields remain missing, the **Portfolio Scraper** crawls GitHub or personal sites.
4. **AI Filtering (`main.py` / `filter_pg_students.py`)**: Combines candidate text with prompt templates ([`filter_prompt.txt`](file:///c:/Users/samga/Downloads/Quick%20Share/RGTVertex/Final_Scrapper_Merging/LinkedIn-Scrapper-Agent-filteration-and-scraper-agent/filter_prompt.txt)) and sends them to Google Gemini (`gemini-3.5-flash` / `gemini-2.5-flash`). Gemini parses qualification metrics (e.g. Indian UG degree + International PG between 2024–2028) and assigns a `KEEP` or `REJECT` decision.
5. **Validation & Sync**: Deduplicates, standardizes fields, and writes to output files or Supabase.

### 📥 Inputs Required
* **API Keys**: `GEMINI_API_KEY` (or `LOVABLE_API_KEY`), `SUPABASE_URL`, `SUPABASE_KEY` in `.env`.
* **Input Candidate Data**:
  * [`linkedin_urls.json`](file:///c:/Users/samga/Downloads/Quick%20Share/RGTVertex/Final_Scrapper_Merging/LinkedIn-Scrapper-Agent-filteration-and-scraper-agent/linkedin_urls.json) or raw text files (`education_extracted.txt` / `linkedin_profiles_data.txt`).
  * Candidate resumes (PDF/DOCX) or portfolio URLs (for fallback resolution).
* **Prompts & Heuristic Files**:
  * [`filter_prompt.txt`](file:///c:/Users/samga/Downloads/Quick%20Share/RGTVertex/Final_Scrapper_Merging/LinkedIn-Scrapper-Agent-filteration-and-scraper-agent/filter_prompt.txt): Prompts driving Gemini AI evaluation logic.
  * `clean_indian_universities.json`: Heuristic reference dataset of Indian universities.

### 📤 Outputs Produced
* **Evaluation Log**: Text log containing Gemini's detailed reasoning, profile metadata, and decision (`KEEP` / `REJECT`).
* **Selected Candidate JSON**: List of profiles that passed the AI filtering rules.
* **Structured Records**: Standardized JSON/CSV schema containing full candidate profiles.

### 🗄️ Storage Locations
* **AI Evaluation Log**: [`filter_results.txt`](file:///c:/Users/samga/Downloads/Quick%20Share/RGTVertex/Final_Scrapper_Merging/LinkedIn-Scrapper-Agent-filteration-and-scraper-agent/filter_results.txt)
* **Qualified Candidates JSON**: [`selected_urls.json`](file:///c:/Users/samga/Downloads/Quick%20Share/RGTVertex/Final_Scrapper_Merging/LinkedIn-Scrapper-Agent-filteration-and-scraper-agent/selected_urls.json) or `indian_students_urls.json`
* **Relational Database**: Supabase PostgreSQL database (`candidates` table) if configured.

---

## 📊 Quick Comparison Matrix

| Attribute | `final-url-scraper` (Stage 1) | `filteration-and-scraper-agent` (Stage 2) |
|---|---|---|
| **Primary Goal** | Broad candidate URL discovery | Deep scraping, fallback parsing & AI filtering |
| **Primary Tech** | Playwright, Python CLI | Playwright, Google Gemini LLM, Pydantic, OCR |
| **Scraping Depth** | Search cards only (Lightweight) | Full profile + Resumes + Portfolios |
| **Main Input** | Keywords / University list | Profile URLs / Raw Profile Text / Resumes |
| **Main Output** | `linkedin_urls.txt`, `linkedin_leads.csv` | `filter_results.txt`, `selected_urls.json`, Supabase DB |
| **Storage Type** | Local TXT & CSV | Local Text logs, JSON & Remote Supabase DB |
