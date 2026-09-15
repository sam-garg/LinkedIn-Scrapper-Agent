# LinkedIn Profile URL Discovery Tool

A modular, Playwright-based tool for discovering and collecting LinkedIn profile URLs using a **user-authenticated browser session**.

---

## 1. Project Overview

This tool searches LinkedIn for profiles matching keyword queries, extracts profile URLs directly from the search result cards, and saves the results to text and CSV files.

**It does NOT navigate to individual profiles, scrape profile details, or perform any qualification/filtering.** All validation is deferred to a downstream processing pipeline.

**The user logs in manually.** The tool never stores your LinkedIn credentials, never injects session cookies, and never attempts to bypass security checkpoints or rate limits.

---

## 2. Features

- **High Speed**: Does not open individual profiles, only paginates through search results.
- **Persistent browser session**: Log in once, reuse the session on every run.
- **Broad query support**: Search with arbitrary keyword queries or use a preconfigured postgraduate discovery set.
- **University query expansion**: Automatically generates additional search queries for university targets.
- **Cross-run deduplication**: Normalises and dedups discovered URLs against `data/output/linkedin_urls.txt`.
- **Checkpoint & restriction detection**: Stops cleanly and saves collected data if a CAPTCHA, login wall, or rate limit is encountered.
- **Lightweight data collection**: Optionally captures card-visible fields (name, headline, location) when present.

---

## 3. Architecture

```
linkedin-scraper/
├── src/
│   ├── __init__.py        Package marker
│   ├── main.py            CLI entry point and run orchestration
│   ├── config.py          Settings loader (settings.json + .env)
│   ├── models.py          DiscoveredProfile dataclass
│   ├── browser.py         Playwright session management
│   ├── linkedin.py        LinkedIn restriction detection
│   ├── search.py          People-search URL construction + URL/card collection
│   ├── exporters.py       CSV and TXT writers
│   ├── utils.py           URL normalisation, dedup, and logging setup
│   └── exceptions.py      Custom exception hierarchy
├── config/
│   ├── settings.json      All configurable application settings
│   └── universities.json  US university list (used for query expansion)
├── data/
│   ├── browser_profile/   Playwright persistent browser profile (auto-created)
│   └── output/
│       ├── linkedin_urls.txt   List of discovered URLs (one per line)
│       └── linkedin_leads.csv  Lightweight lead details
├── tests/
│   ├── test_extractors.py  Card extraction unit tests
│   ├── test_leads.py       Exporter unit tests
│   ├── test_login.py       Authentication unit tests
│   ├── test_search.py      Search and limit passthrough unit tests
│   └── test_utils.py       Utility unit tests
├── .env.example           Environment variable template
├── requirements.txt       Python dependencies
└── README.md              This file
```

Data flow:

```
CLI args
  → config.py (load settings)
  → browser.py (launch Chromium with persistent profile)
  → browser.py (verify/wait for LinkedIn login)
  → search.py (build search URLs → paginate and collect card URLs/details)
  → exporters.py (append URLs to TXT, save lightweight details to CSV)
```

---

## 4. Installation

### Requirements

- Python 3.11 or later
- Windows, macOS, or Linux

### Step 1 — Clone or download

```cmd
cd C:\Users\YourName\Desktop
# Place the linkedin-scraper folder here
cd linkedin-scraper
```

### Step 2 — Create a virtual environment

```cmd
python -m venv .venv
.venv\Scripts\activate
```

### Step 3 — Install Python dependencies

```cmd
pip install -r requirements.txt
```

### Step 4 — Install Playwright browsers

```cmd
playwright install chromium
```

### Step 5 — Copy the environment file

```cmd
copy .env.example .env
```

---

## 5. First-Time LinkedIn Login

The first time you run the scraper, LinkedIn will not have an active session:

1. Run any command (see examples below).
2. A **Chromium browser window opens** and navigates to LinkedIn.
3. **Log in manually** in that browser window — enter your email, password, and complete any 2FA if prompted.
4. Once you are on the LinkedIn feed, the tool detects the login and continues automatically.
5. Your session is saved in `data/browser_profile/` for future runs.

---

## 6. CLI Commands

### Postgraduate Query Discovery (Recommended)

Uses a broad postgraduate discovery query set (e.g. MS, Master's, MBA) and expands them with target universities:

```cmd
python -m src.main --postgraduate --limit 100
```

### Basic query search

```cmd
python -m src.main --query "MBA" --limit 50
```

### With location filter

```cmd
python -m src.main --query "Software Engineer" --limit 50 --location "United States"
```

### Disable cross-run deduplication

```cmd
python -m src.main --query "Product Manager" --limit 20 --no-dedup
```

### Help

```cmd
python -m src.main --help
```

---

## 7. Configuration

### .env

Copy `.env.example` to `.env` and edit as needed:

```env
SCRAPER_HEADLESS=false         # true = no visible browser window
DEFAULT_LIMIT=10               # default number of profiles per run
LINKEDIN_EMAIL=your_email      # optional: for auto-login
LINKEDIN_PASSWORD=your_pass    # optional: for auto-login
LINKEDIN_AUTO_LOGIN=false      # true = fill login form automatically
```

### config/settings.json

Contains settings for:
- Timeouts
- Delays between search result pages
- Search page limits
- LinkedIn restriction detection body phrases and URL signals

---

## 8. Output Format

### Plain Text — `data/output/linkedin_urls.txt`

A plain-text file containing one canonical profile URL per line:

```
https://www.linkedin.com/in/person1
https://www.linkedin.com/in/person2
```

### CSV — `data/output/linkedin_leads.csv`

Contains lightweight, card-visible fields extracted directly from the search result card (no profile navigation performed):

| Column | Description |
|---|---|
| `linkedin_url` | Normalised canonical profile URL |
| `name` | Person's name |
| `headline` | Professional headline |
| `location` | Location string |
| `search_query` | Query that discovered the profile |
| `scraped_at` | Discovery timestamp |

*Note: Missing fields default to `N/A`.*

---

## 9. Troubleshooting

- **`ModuleNotFoundError: No module named 'src'`**: Make sure you run the commands from the `linkedin-scraper` project root directory.
- **Login required redirect**: Session expired. Log in again manually when the browser opens.
- **Checkpoints/CAPTCHAs**: If LinkedIn challenges the session, complete the verification manually in the browser and the tool will continue.
