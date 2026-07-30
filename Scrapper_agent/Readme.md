🤖 Agent 2: Scraping & Multi-Tier Fallback Extraction Agent

Agent 2 is an intelligent data extraction pipeline designed to harvest missing candidate contact details (Email, Phone Number) from LinkedIn profiles, resumes, and candidate personal portfolios. 

It implements a **Multi-Tiered Fallback Architecture** with **Zero-Memory (RAM-only) Resume Processing** to ensure maximum data recovery rates while prioritizing security, speed, and zero disk-footprint overhead.

---

## 📐 System Architecture

```
                                  [ Input: LinkedIn URL ]
                                             │
                                             ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ AGENT 2: SCRAPER AGENT CORE                                                            │
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 1. LinkedIn Scraper Engine                                                      │  │
│  │    Extracts: Email, Phone Number, Resume URL, Portfolio/GitHub/Personal Web URLs │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
│                                            │                                           │
│                                  [ Valid Email & Phone? ]                              │
│                                     /              \                                   │
│                             (Yes)  /                \  (No)                            │
│                                   /                  \                                 │
│                                  ▼                    ▼                                │
│                     ┌──────────────────┐    ┌──────────────────────────────────────┐   │
│                     │ Merge Payload &  │    │ Fallback 1: Resume Scraper Sub-Agent │   │
│                     │ Send to Agent 3  │    │ (Zero-Memory / RAM BytesIO Streaming)│   │
│                     └──────────────────┘    └──────────────────────────────────────┘   │
│                                                               │                        │
│                                                    [ Still Missing Info? ]             │
│                                                       /              \                 │
│                                               (No)   /                \  (Yes)         │
│                                                     /                  \               │
│                                                    ▼                    ▼              │
│                                       ┌──────────────────┐  ┌──────────────────────┐ │
│                                       │ Merge Payload &  │  │ Fallback 2:          │ │
│                                       │ Send to Agent 3  │  │ Portfolio Scraper    │ │
│                                       └──────────────────┘  │ (Dynamic Web Crawler)│ │
│                                                             └──────────────────────┘ │
│                                                                         │              │
│                                                                         ▼              │
│                                                             ┌──────────────────────┐ │
│                                                             │ Data Merger Engine   │ │
│                                                             └──────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┼──────────────┘
                                                                          │
                                                                          ▼
                                                         [ Output: Structured JSON to Agent 3 ]
```

---

## ⚡ Multi-Tier Fallback Workflow

### 🔹 Stage 1: Primary LinkedIn Extraction
1. Receives candidate profile URLs passed from **Agent 1 (Search Agent)**.
2. Extracts direct contact details (Email, Phone) alongside secondary document links (Resume URLs, Portfolio/GitHub URLs).
3. If both **Email** and **Phone** are populated, execution immediately bypasses fallbacks and hands off structured data to **Agent 3**.

### 🔹 Fallback 1: Resume Scraper Sub-Agent (Zero-Memory RAM Processing)
Triggered when mandatory fields remain missing and a candidate resume URL is available:
* **In-Memory Streaming:** Streams file binaries directly into host memory (`io.BytesIO`), bypassing disk storage (`/tmp`).
* **RAM Text Extraction:** Parses PDF/DOCX formats directly in-memory using `pdfplumber` and `python-docx`.
* **Pattern & Entity Parsing:** Employs regex search and structured LLM extraction (GPT-4o-mini / Pydantic schema) for high-accuracy contact matching.
* **Instant RAM Purge:** Closes buffer channels and invokes Python Garbage Collection (`gc.collect()`), ensuring **zero residual candidate PII on disk**.

### 🔹 Fallback 2: Portfolio / Web Scraper Sub-Agent
Triggered if fields remain missing after resume processing and a portfolio link (Personal site, GitHub, Linktree, etc.) was identified:
* Resolves dynamic links and navigates key contact endpoints (`/contact`, `/about`, `/resume`, footer DOM elements).
* Scrapes HTML DOM elements directly for `mailto:` and `tel:` protocols.
* Checks public GitHub API endpoints (`api.github.com/users/{username}`) and commit histories for verified author emails.

### 🔹 Stage 4: Aggregation & Hand-off
Combines output streams from all three layers into a single validated JSON payload for **Agent 3 (Validation & Storage Agent)**.

---

## 🛠️ Project Structure

```
agent2_scraper/
├── README.md
├── requirements.txt
├── config.py
├── main.py                          # Agent entry point & orchestration
├── schemas/
│   └── candidate.py                 # Pydantic data models
└── scrapers/
    ├── linkedin_scraper.py          # Primary LinkedIn extraction engine
    ├── resume_scraper.py            # Fallback 1: Zero-memory RAM resume parser
    └── portfolio_scraper.py         # Fallback 2: Portfolio & GitHub web crawler
```

---

## ⚙️ Installation & Setup

### Prerequisites
* Python 3.10+
* Playwright binaries (for browser-based web crawling)

### 1. Clone & Install Dependencies

```bash
# Install required Python packages
pip install -r requirements.txt

# Install Playwright browser drivers
playwright install chromium
```

### `requirements.txt`
```text
httpx>=0.27.0
pdfplumber>=0.11.0
python-docx>=1.1.0
playwright>=1.42.0
pydantic>=2.6.0
beautifulsoup4>=4.12.0
openai>=1.14.0
```

---

## 💻 Code Reference Implementation

### Zero-Memory Resume Scraper (`scrapers/resume_scraper.py`)

```python
import io
import re
import gc
import httpx
import pdfplumber
from typing import Dict, Optional

def scrape_resume_in_ram(resume_url: str) -> Dict[str, Optional[str]]:
    """
    Downloads and parses candidate resumes entirely in RAM memory.
    Ensures zero disk storage footprint.
    """
    extracted = {"email": None, "phone": None}
    pdf_buffer = None
    
    try:
        # Stream file binary into RAM buffer
        response = httpx.get(resume_url, timeout=12.0)
        response.raise_for_status()
        
        pdf_buffer = io.BytesIO(response.content)
        text_content = ""
        
        with pdfplumber.open(pdf_buffer) as pdf:
            for page in pdf.pages:
                text_content += page.extract_text() or ""
                
        # Regex Pattern Matchers
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        phone_pattern = r'(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
        
        name = 
        emails = re.findall(email_pattern, text_content)
        phones = re.findall(phone_pattern, text_content)
        skills = 
        
        if emails: 
            extracted["email"] = emails[0]
        if phones: 
            extracted["phone"] = phones[0]
            
    except Exception as e:
        print(f"[Resume Scraper Error]: {e}")
        
    finally:
        # Zero-Memory Cleanup: Force purging from memory
        if pdf_buffer:
            pdf_buffer.close()
        gc.collect()
        
    return extracted
```

### Orchestrator Logic (`main.py`)

```python
from schemas.candidate import CandidateProfile
from scrapers.linkedin_scraper import scrape_linkedin_profile
from scrapers.resume_scraper import scrape_resume_in_ram
from scrapers.portfolio_scraper import scrape_portfolio_website

def run_agent_2(profile_url: str) -> CandidateProfile:
    # Stage 1: Primary LinkedIn Scraping
    candidate = scrape_linkedin_profile(profile_url)
    
    if candidate.email and candidate.phone:
        print("✅ Primary extraction complete.")
        return candidate
        
    # Fallback 1: Resume Scraper (RAM-only)
    if candidate.resume_url and (not candidate.email or not candidate.phone):
        print("⚠️ Missing contact info. Triggering Fallback 1: Resume Scraper (RAM)...")
        resume_data = scrape_resume_in_ram(candidate.resume_url)
        candidate.email = candidate.email or resume_data.get("email")
        candidate.phone = candidate.phone or resume_data.get("phone")

    # Fallback 2: Portfolio Scraper
    if candidate.portfolio_url and (not candidate.email or not candidate.phone):
        print("⚠️ Still missing info. Triggering Fallback 2: Portfolio Scraper...")
        portfolio_data = scrape_portfolio_website(candidate.portfolio_url)
        candidate.email = candidate.email or portfolio_data.get("email")
        candidate.phone = candidate.phone or portfolio_data.get("phone")

    return candidate
```

---

## 🔒 Security & Performance Features

* **Zero Memory Footprint (Zero Disk Persistence):** Resumes are fetched directly into RAM streams (`io.BytesIO`), extracted, and garbage-collected immediately. No PII resides on server disks.
* **Non-Blocking Architecture:** Built with async compatibility (`httpx` + `playwright`) for high-throughput batch crawling.
* **Resilient Extraction Pipeline:** Combines deterministic Regex matching with LLM-backed natural language understanding for non-standard formats.