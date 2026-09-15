## 🔄 Project Workflow

The project follows a two-stage pipeline:

1. **Profile Filtering**
2. **Full LinkedIn Profile Scraping & Data Extraction**

### 1. Input LinkedIn URLs

- Store the LinkedIn profile URLs in:
  `linkedin_urls.json`
- These URLs are used as the initial input for the pipeline.

### 2. LinkedIn Authentication

- Run `login_use.py`.
- The script opens LinkedIn and authenticates the account.
- After successful login, the browser session is saved in:
  `storage_state.json`
- This stored session is reused by the subsequent Playwright scripts.

### 3. Education Extraction

- Run `filter_education.py`.
- The script:
  - Reads URLs from `linkedin_urls.json`
  - Uses the authenticated session from `storage_state.json`
  - Opens each LinkedIn profile
  - Extracts the Education section
- The extracted education data is saved in:
  `education_extracted.txt`

### 4. Education-Based Profile Filtering

- Filtering rules are defined in:
  `filter_prompt.txt`
- Run `main.py`.
- The script:
  - Reads `education_extracted.txt`
  - Loads the filtering instructions from `filter_prompt.txt`
  - Sends the profile data to Gemini
  - Evaluates each profile against the required conditions
- The complete filtering explanation and Gemini response are saved in:
  `filter_results.txt`
- Profiles that satisfy all filtering conditions are selected.
- Their LinkedIn URLs are saved in:
  `selected_urls.json`

### 5. Selected URLs

`selected_urls.json` contains only the profiles that passed the filtering stage.

Example:

```json
[
  {
    "id": 1,
    "url": "https://www.linkedin.com/in/example/"
  }
]
### 6. Full LinkedIn Profile Scraping

- Run `scraper_authenticated.py`.
- The scraper:
  - Reads the selected LinkedIn URLs from `selected_urls.json`
  - Uses the authenticated session stored in `storage_state.json`
  - Opens each selected LinkedIn profile
  - Scrapes the complete LinkedIn profile data
- The raw scraped profile data is saved in:
  `linkedin_profile_data.txt`

### 7. Raw Profile Data

- `linkedin_profile_data.txt` contains the complete/raw information scraped from the selected LinkedIn profiles.
- This file serves as the input for the final data extraction stage.
- It contains the profile information required for extracting the final fields.

### 8. Required Data Extraction

- The required extraction rules are defined in:
  `extraction_prompt.txt`
- The extraction process:
  - Reads the scraped profile data from `linkedin_profile_data.txt`
  - Uses `extraction_prompt.txt` to identify the required information
  - Extracts only the required fields from each profile
- The final extracted information is saved in:
  `extracted_profiles.txt`


** Complete Pipeline **
  linkedin_urls.json
        │
        ▼
  login_use.py
        │
        ▼
storage_state.json
        │
        ▼
filter_education.py
        │
        ▼
education_extracted.txt
        │
        ▼
filter_prompt.txt
        │
        ▼
    main.py
        │
        ▼
     Gemini
        │
        ├───────────────► filter_results.txt
        │                 (Filtering explanations)
        │
        ▼
selected_urls.json
(Filtered LinkedIn URLs)
        │
        ▼
scraper_authenticated.py
        │
        ▼
linkedin_profile_data.txt
        │
        ▼
extraction_prompt.txt
        │
        ▼
Required Data Extraction
        │
        ▼
extracted_profiles.txt

----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


# Automated Candidate Profile Scraping & Enrichment Pipeline

An intelligent, multi-agent web scraping and data enrichment engine designed to automate candidate profile discovery, document parsing, and structured data storage. The pipeline combines web scrapers, OCR, and LLM-driven structured extraction to build complete candidate profiles from LinkedIn, resumes, and portfolio links with high accuracy. 
"THIS PIPELINE IS STILL IN BUILD PHASE."

## 📌 Table of Contents

- [Overview](#-overview)
- [Architecture & Workflow](#-architecture--workflow)
- [Key Features](#-key-features)
- [Agent Breakdown](#-agent-breakdown)
- [Tech Stack](#-tech-stack)
- [Getting Started](#-getting-started)
- [Configuration](#-configuration)
- [Database Schema (Supabase)](#-database-schema-supabase)
- [Troubleshooting & Challenges](#-troubleshooting--known-challenges)
- [License](#-license)

---

## 🔍 Overview

Manual candidate sourcing across multiple platforms leads to fragmented data, missing information, and high effort. This pipeline automates the entire candidate ingestion process:

- Searches for candidate profiles.
- Scrapes core LinkedIn profile data.
- Parses Resumes / CVs (PDFs, DOCX) whenever LinkedIn data contains null or missing fields.
- Scrapes Portfolios / GitHub / Personal Sites if missing fields persist.
- Validates & Merges all data sources into a standardized record.
- Stores clean records into Supabase and exports them to CSV.

---

## 🏗 Architecture & Workflow

```
                        +-----------------------+
                        |        Start          |
                        +-----------------------+
                                    |
                                    v
                        +-----------------------+
                        |  Agent 1: Search      |
                        | (Name, Role, Company) |
                        +-----------------------+
                                    |
                                    v
                        +-----------------------+
                        |      URL Builder      |
                        +-----------------------+
                                    |
                                    v
                        +-----------------------+
                        |  Agent 2: Scraper     |
                        |   (LinkedIn Profile)  |
                        +-----------------------+
                                    |
                                    v
                        +-----------------------+
                        | Null Values Present?  |
                        +-----------------------+
                         /                     \
                   (Yes)/                       \(No)
                       v                         v
       +-------------------------------+         |
       |  Resume Scraper Sub-Agent     |         |
       |  (PDF, DOCX Parsing & OCR)    |         |
       +-------------------------------+         |
                       |                         |
                       v                         |
       +-------------------------------+         |
       |     Extract Missing Data      |         |
       +-------------------------------+         |
                       |                         |
                       v                         |
       +-------------------------------+         |
       |    Still Null Values?         |         |
       +-------------------------------+         |
        /                             \          |
  (Yes)/                               \(No)     |
      v                                 v        v
+------------------------+          +-------------------+
| Portfolio Scraping     | -------> |    Merge Data     |
| (GitHub/Website/etc.)  |          | (LinkedIn+CV+Web) |
+------------------------+          +-------------------+
                                              |
                                              v
                                 +-------------------------+
                                 | Agent 3: Validation     |
                                 +-------------------------+
                                              |
                                              v
                                 +-------------------------+
                                 | Stores in Supabase &    |
                                 | Exports CSV             |
                                 +-------------------------+
```

---

## ✨ Key Features

- **Multi-Source Enrichment Pipeline**: Cascading architecture sequentially checks LinkedIn, Resume files, and Personal Websites to resolve missing data.
- **Intelligent Document Sub-Agent**: Handles PDF parsing, multi-column resumes, and OCR for scanned documents using vision/text models.
- **LLM-Driven Extraction**: Guarantees strict output schemas for fields like work experience, contact details, and technical skills using structured output parsing (Pydantic / Function Calling).
- **Automated Validation & Retry Handling**: Agent 3 cross-checks field completeness and triggers heuristic or manual fallbacks if critical data remains missing.
- **Supabase Sync & CSV Export**: Dual storage setup for live database queries and downloadable bulk datasets.

---

## 🤖 Agent Breakdown

| Agent / Sub-Agent       | Responsible For                                                      | Primary Inputs                  | Outputs                         |
| ----------------------- | -------------------------------------------------------------------- | ------------------------------- | ------------------------------- |
| **Agent 1: Search Agent** | Sourcing profile URLs using candidate metadata.                      | Name, Role, Company             | Search results, target URLs     |
| **URL Builder**           | Normalizing and constructing valid profile URLs.                     | Search Results                  | Cleaned URLs                    |
| **Agent 2: Scraper Agent** | Fetching public/authenticated LinkedIn data.                        | LinkedIn URL                    | Raw Profile JSON                |
| **Resume Sub-Agent**      | Ingesting PDFs/DOCX, applying OCR, and extracting missing attributes. | Resume File, Missing Fields list | Structured Profile Delta JSON   |
| **Portfolio Scraper**     | Crawling personal websites, GitHub repositories, or portfolios.      | Portfolio URL                   | Structured Profile Delta JSON   |
| **Agent 3: Validation Agent** | Schema validation, deduplication, backfilling missing attributes, storage trigger. | Merged Profile JSON    | Validated Record                |

---

## 🛠 Tech Stack

| Component                    | Technology                                                                 |
| ---------------------------- | -------------------------------------------------------------------------- |
| **Core Runtime**             | Python 3.10+                                                               |
| **Agent Framework / Orchestration** | LangChain / LangGraph (or Custom Python Async Pipeline)              |
| **Scraping & Automation**    | Playwright / Selenium / BeautifulSoup4                                     |
| **PDF & Document Processing**| pdfplumber, PyMuPDF (fitz), python-docx, pytesseract                       |
| **Extraction & LLMs**        | OpenAI API (GPT-4o / GPT-4o-mini) with Pydantic validation                 |
| **Database & Storage**       | Supabase (PostgreSQL)                                                      |
| **Exporting**                | Pandas / CSV                                                               |

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- Node.js (if running headless browser proxies)
- Tesseract OCR (if processing image-based scanned resumes locally)
- Supabase Account & Database instance

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/your-org/candidate-scraper-pipeline.git
cd candidate-scraper-pipeline

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install
```

### 2. Environment Setup

Create a `.env` file in the project root:

```env
# LLM Provider
OPENAI_API_KEY=your_openai_api_key

# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_or_service_role_key

# Scraper Credentials / Proxies (If Applicable)
PROXY_SERVER=http://your-proxy-provider.com:8080
PROXY_USERNAME=your_username
PROXY_PASSWORD=your_password
```

### 3. Usage

Run the pipeline by passing candidate metadata:

```bash
python main.py --name "John Doe" --role "Senior Software Engineer" --company "Tech Corp"
```

To run a batch job from an input file:

```bash
python batch_runner.py --input candidates.json --output-dir ./exports
```

---

## ⚙️ Configuration

You can customize agent behavior in `config/agent_config.yaml`:

```yaml
pipeline:
  max_retries: 3
  enable_portfolio_scraping: true

agents:
  scraper_agent:
    timeout_seconds: 30
    headless: true

  resume_sub_agent:
    ocr_engine: "tesseract"          # options: tesseract, vision_llm
    supported_formats: ["pdf", "docx", "doc", "png", "jpg"]

  validation_agent:
    strict_mode: false               # Set true to fail pipeline if nulls persist after all retries
```

---

## 🗄 Database Schema (Supabase)

The pipeline maps extracted candidate data to a standard `candidates` table in Supabase:

```sql
CREATE TABLE candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name TEXT NOT NULL,
    current_role TEXT,
    company TEXT,
    email TEXT UNIQUE,
    phone TEXT,
    linkedin_url TEXT,
    portfolio_url TEXT,
    skills TEXT[],
    experience JSONB,
    education JSONB,
    source_completeness NUMERIC,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

---

## ⚠️ Troubleshooting & Known Challenges

| Challenge                      | Solution / Mitigation                                                                                       |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| **Complex Resume Layouts**     | The sub-agent uses pdfplumber paired with LLM visual/structural extraction to handle multi-column layouts.  |
| **LinkedIn Rate Limits & Anti-Bot Security** | Uses rotating proxies, randomized user agents, and browser session delays within Agent 2.      |
| **OCR Misreadings on Scanned PDFs** | Pydantic regex patterns validate email, phone, and date formats before saving; LLMs handle character repair contextually. |
| **Persistent Null Fields**     | The Validation Agent flags remaining nulls and routes them to a manual/heuristic backfill queue before export. |

---

## 📄 License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.
