import sys
import time
import random
import re
import csv
import os
import json
import urllib.parse
from datetime import datetime
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ============================================================
# UNIVERSITY WHITELIST LOADING
# ============================================================
UNIVERSITIES_JSON_PATH = "us_universities.json"

def load_us_universities(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError("us_universities.json must contain a list")

        return data

    except FileNotFoundError:
        raise Exception(
            f"University whitelist not found at {path}. "
            f"Create it before running the scraper."
        )

    except json.JSONDecodeError as e:
        raise Exception(f"University whitelist JSON is invalid: {e}")

US_UNIVERSITIES = load_us_universities(UNIVERSITIES_JSON_PATH)
print(f"Loaded {len(US_UNIVERSITIES)} US universities from whitelist")

# ============================================================
# ACCOUNTS & SESSION CONFIGURATION
# ============================================================
ACCOUNTS_JSON_PATH = "accounts.json"

def load_accounts(path=ACCOUNTS_JSON_PATH):
    """
    Loads list of LinkedIn accounts and session IDs/credentials from accounts.json.
    """
    default_accounts = [
        {"id": "Account 1", "username": "", "password": "", "session_dir": "linkedin_session_1", "li_at": ""},
        {"id": "Account 2", "username": "", "password": "", "session_dir": "linkedin_session_2", "li_at": ""},
        {"id": "Account 3", "username": "", "password": "", "session_dir": "linkedin_session_3", "li_at": ""}
    ]
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                accounts = json.load(f)
                if isinstance(accounts, list) and len(accounts) > 0:
                    return accounts
        except Exception as e:
            print(f"⚠️ Could not load {path}: {e}. Using default accounts configuration.")
    return default_accounts

# ============================================================
# KEYWORDS & PATTERNS
# ============================================================
TECH_KEYWORDS = [
    "Python", "Java", "JavaScript", "TypeScript", "React", "Angular", "Vue", "Svelte",
    "Node.js", "Express", "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform",
    "SQL", "PostgreSQL", "MySQL", "MongoDB", "Redis", "Cassandra", "Elasticsearch",
    "Machine Learning", "Data Science", "Deep Learning", "TensorFlow", "PyTorch", 
    "DevOps", "CI/CD", "Jenkins", "Git", "Linux", "C++", "C#", ".NET", "Ruby", "Rails",
    "PHP", "Laravel", "Swift", "Kotlin", "Go", "Golang", "Rust", "Scala", "Spring", 
    "Django", "Flask", "FastAPI", "Hadoop", "Spark", "Kafka", "Tableau", "Power BI", 
    "Salesforce", "ServiceNow", "Cybersecurity", "Blockchain", "Web3", "HTML", "CSS"
]
VISA_KEYWORDS = ["H1B", "H-1B", "OPT", "CPT", "EAD", "Green Card", "US Citizen", "Citizen"]

# ============================================================
# EXTRACTOR & HELPER FUNCTIONS
# ============================================================

def extract_name(url, page_text):
    """Extracts a clean name from the LinkedIn page title / heading or falls back to URL slug."""
    # Try to find name in page heading first
    heading_match = re.search(r"^([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})", page_text.strip())
    if heading_match:
        candidate = heading_match.group(1).strip()
        if len(candidate.split()) >= 2:
            return candidate
    # Fallback: slug from URL
    match = re.search(r"linkedin\.com/in/([^/?#]+)", url)
    if match:
        slug = match.group(1)
        # Remove trailing digits / IDs
        slug = re.sub(r'-[a-f0-9]{6,}$', '', slug)
        return slug.replace("-", " ").title()
    return "Unknown"

def extract_email(text):
    """Extract email including obfuscated formats like 'name at domain dot com'."""
    # Direct format
    emails = re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    valid = [e for e in emails if not re.search(r"\.(png|jpg|gif|css|js)$", e, re.IGNORECASE)]
    if valid:
        return valid[0]
    # Obfuscated: "name at domain dot com"
    obf = re.search(
        r"([A-Za-z0-9._%+\-]+)\s+(?:at|AT)\s+([A-Za-z0-9.\-]+)\s+(?:dot|DOT)\s+([A-Za-z]{2,})",
        text
    )
    if obf:
        return f"{obf.group(1)}@{obf.group(2)}.{obf.group(3)}"
    return "N/A"

def extract_contact(text):
    phone = re.search(
        r"(?:\+91[\s\-]?)?[6-9]\d{9}|"
        r"\+1[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}|"
        r"\(\d{3}\)\s?\d{3}[\-\s]?\d{4}",
        text
    )
    return phone.group().strip() if phone else "N/A"

def extract_technologies(text):
    combined = text.lower()
    found = [tech for tech in TECH_KEYWORDS if tech.lower() in combined]
    return ", ".join(found) if found else "N/A"

def extract_resume_links(text):
    """Extracts links/references to Resumes or CVs (Google Drive, Dropbox, Notion, PDFs, Canva, etc.)."""
    resume_links = re.findall(
        r"(https?://(?:drive\.google\.com|docs\.google\.com|dropbox\.com|notion\.site|cutt\.ly|bit\.ly|canva\.com)[^\s\)]+|[^\s\)]+\.pdf)",
        text,
        re.IGNORECASE
    )
    if resume_links:
        return ", ".join(sorted(set(resume_links)))
    # Check text reference
    if re.search(r"\b(resume|cv|curriculum vitae)\b", text, re.IGNORECASE):
        return "Resume mentioned in profile"
    return "N/A"

def extract_visa(text):
    for visa in VISA_KEYWORDS:
        if visa.upper() in text.upper():
            return visa
    return "OPT / Seeking Sponsor"

def extract_year(text):
    """Extract graduation year, preferring recent years (2024-2027)."""
    combined = text.upper()
    # Prefer recent grad years first
    match = re.search(r"\b(202[4-7])\b", combined)
    if match:
        return match.group(1)
    # Fallback short form: '24, '25, '26, '27
    match_short = re.search(r"'(2[4-7])\b", combined)
    if match_short:
        return "20" + match_short.group(1)
    # Broader fallback
    years = re.findall(r"\b(20(?:1[5-9]|2[0-7]))\b", text)
    return sorted(set(years), reverse=True)[0] if years else "N/A"

def verify_strict_postgrad(text):
    """
    Strictly validates the candidate holds or is pursuing a Master's / postgraduate degree.
    Returns (is_postgrad: bool, degree_label: str)
    Merged from feature/linkedin-scraper branch.
    """
    combined = text.upper()
    masters_indicators = [
        "MS IN", "M.S. IN", "M.S IN", "MASTER OF", "MASTER'S", "MASTER DEGR",
        "MBA", "MEM ", "MENG", "M.ENG", "POSTGRADUATE", "POST-GRADUATE",
        "MS GRADUATE", "MS GRAD", "MASTER GRADUATE", "MASTER'S GRADUATE",
        "MASTER OF SCIENCE", "MASTER OF ENGINEERING", "MASTER OF BUSINESS"
    ]
    pattern_match = re.search(r"\b(MS|M\.S\.|MASTER|MBA|MEM|MENG|M\.ENG)\b", combined)
    has_masters = any(sig in combined for sig in masters_indicators)

    if not (has_masters or pattern_match):
        return False, None

    degree = "Master's Degree"
    if "MBA" in combined:
        degree = "MBA"
    elif "MASTER OF SCIENCE" in combined or "MS IN" in combined or "M.S." in combined:
        degree = "Master of Science (MS)"
    elif "MASTER OF ENGINEERING" in combined or "MENG" in combined or "M.ENG" in combined:
        degree = "Master of Engineering (M.Eng)"
    elif "MEM" in combined:
        degree = "Master of Engineering Management"
    return True, degree

def extract_university(text):
    """
    Extracts US university from profile text.
    First checks against the us_universities.json whitelist.
    Falls back to hardcoded known US university shortcuts.
    Finally falls back to regex pattern for university lines.
    """
    # 1. Whitelist match
    for uni in US_UNIVERSITIES:
        if not uni or not isinstance(uni, str):
            continue
        uni_clean = uni.strip()
        pattern = rf"\b{re.escape(uni_clean)}\b"
        if re.search(pattern, text, re.IGNORECASE):
            return uni_clean

    # 2. Hardcoded shortcode overrides (from feature/linkedin-scraper)
    text_upper = text.upper()
    shortcuts = {
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
    }
    for keyword, full_name in shortcuts.items():
        if keyword in text_upper:
            return full_name

    # 3. Regex fallback - look for any line containing university/college keywords
    us_acronyms = ["MIT", "UCLA", "SUNY", "CUNY", "SDSU", "UMBC", "UMD", "UIUC", "UIC", "SJSU"]
    indian_keywords = [
        "Delhi", "Mumbai", "Pune", "Anna", "Amity", "SRM", "VIT", "BITS", "IIT", "NIT",
        "Manipal", "JNTU", "KIIT", "Chandigarh", "Osmania", "Madras", "Kharagpur",
        "Kanpur", "Roorkee", "Guwahati", "Indore", "Bangalore", "Hyderabad",
        "Noida", "Vellore", "Pilani", "Symbiosis", "NMIMS", "Jadavpur", "Sathyabama",
        "Banasthali", "Galgotias", "India"
    ]
    segments = re.split(r'[,|•\n]', text)
    for seg in segments:
        seg = seg.strip()
        has_uni_word = re.search(r"\b(University|College|Institute of Technology|Polytechnic)\b", seg, re.IGNORECASE)
        has_acronym = any(re.search(rf"\b{acr}\b", seg) for acr in us_acronyms)
        if (has_uni_word or has_acronym) and 10 < len(seg) < 100:
            is_indian = any(re.search(rf"\b{ind}\b", seg, re.IGNORECASE) for ind in indian_keywords)
            if not is_indian:
                return seg.strip()

    return "N/A"

def extract_summary(page_text):
    clean_text = re.sub(r'\s+', ' ', page_text).strip()
    return clean_text[:400] + "..." if len(clean_text) > 400 else clean_text

def fetch_profile_posts(page, url):
    """
    Navigates to profile's recent activity / posts page iff email is missing on main profile.
    Reads post content and attempts to extract an email address from candidate posts.
    """
    activity_url = f"{url.rstrip('/')}/recent-activity/all/"
    try:
        print(f"   📰 Reading posts from activity page: {activity_url}")
        page.goto(activity_url, wait_until="domcontentloaded")
        human_delay(2, 4)
        
        for _ in range(3):
            page.evaluate("window.scrollBy(0, 600);")
            time.sleep(random.uniform(0.5, 1.2))

        posts_text = page.inner_text("body")
        extracted_email = extract_email(posts_text)

        clean_posts = re.sub(r'\s+', ' ', posts_text).strip()
        posts_summary = clean_posts[:500] + "..." if len(clean_posts) > 500 else clean_posts
        
        return posts_summary, extracted_email
    except Exception as e:
        print(f"   ⚠️ Error reading posts: {e}")
        return "N/A", "N/A"

def human_delay(min_sec=3, max_sec=7):
    """Wait for a random amount of time to look human."""
    time.sleep(random.uniform(min_sec, max_sec))

# ============================================================
# RATE LIMIT & BLOCK DETECTION
# ============================================================
def is_rate_limited(page):
    """
    Checks if current page exhibits LinkedIn rate limits, security checkpoints, or search blockages.
    Returns (True, reason) or (False, "").
    """
    try:
        current_url = page.url.lower()
        if any(term in current_url for term in ["checkpoint", "challenge", "login", "captcha", "unusual-activity", "authwall"]):
            return True, "Security Checkpoint / Challenge Page"

        body_text = page.inner_text("body").lower()
        rate_limit_phrases = [
            "reached the monthly search limit",
            "commercial use limit",
            "try searching again later",
            "security verification",
            "account restricted",
            "temporarily restricted",
            "unable to load search results",
            "out of search results"
        ]
        for phrase in rate_limit_phrases:
            if phrase in body_text:
                return True, f"Rate limit detected: '{phrase}'"
    except Exception:
        pass
    return False, ""

# ============================================================
# BROWSER CONTEXT & SESSION LAUNCHER
# ============================================================
def launch_account_context(p, account):
    """
    Launches browser context for a specific account, setting up persistent session and li_at cookie if provided.
    """
    session_dir_name = account.get("session_dir", "linkedin_session_1")
    session_dir = os.path.join(os.getcwd(), session_dir_name)
    
    browser = p.chromium.launch_persistent_context(
        user_data_dir=session_dir,
        headless=False,
        viewport={"width": 1280, "height": 800},
        args=["--disable-blink-features=AutomationControlled"]
    )
    
    li_at_cookie = account.get("li_at", "").strip()
    if li_at_cookie:
        try:
            browser.add_cookies([{
                "name": "li_at",
                "value": li_at_cookie,
                "domain": ".www.linkedin.com",
                "path": "/"
            }])
            print(f"   🔑 Injected li_at session cookie for '{account.get('id')}'")
        except Exception as e:
            print(f"   ⚠️ Failed to set li_at cookie for '{account.get('id')}': {e}")

    page = browser.new_page()
    return browser, page

def check_login_status(page, browser, account):
    """Verifies authentication for the active account and attempts automated login if credentials are provided."""
    print(f"\nChecking login status for account '{account.get('id')}'...")
    try:
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        human_delay(2, 4)
        
        limited, reason = is_rate_limited(page)
        if limited and "login" not in page.url:
            print(f"⚠️ Account '{account.get('id')}' hit checkpoint or block on login: {reason}")
            return False

        if "login" in page.url or "checkpoint" in page.url:
            username = account.get("username", "").strip()
            password = account.get("password", "").strip()
            if username and password:
                print(f"🔑 Attempting automated credential login for '{account.get('id')}'...")
                try:
                    page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
                    time.sleep(2)
                    page.fill("input#username", username)
                    time.sleep(0.5)
                    page.fill("input#password", password)
                    time.sleep(0.5)
                    page.click("button[type='submit']")
                    time.sleep(5)
                except Exception as login_err:
                    print(f"❌ Auto-login attempt failed: {login_err}")

            if "login" in page.url or "checkpoint" in page.url:
                print(f"\n⚠️ YOU ARE NOT LOGGED IN for '{account.get('id')}'.")
                print("Please log in manually in the browser window that just opened.")
                print("Checking status every 3 seconds (up to 90 seconds)...")
                
                for attempt in range(30):
                    time.sleep(3)
                    try:
                        if page.is_closed():
                            print("❌ Page was closed.")
                            return False
                        current_url = page.url
                        if "feed" in current_url or "linkedin.com/in" in current_url:
                            print(f"🎉 Successfully logged in to '{account.get('id')}'! Re-saving session.")
                            return True
                    except Exception:
                        print("❌ Browser or page was closed.")
                        return False
                print(f"❌ Login timeout for '{account.get('id')}'.")
                return False
        return True
    except Exception as e:
        print(f"❌ Error checking login status for '{account.get('id')}': {e}")
        return False

# ============================================================
# LINKEDIN NATIVE SEARCH & SCRAPE (MULTI-ACCOUNT)
# ============================================================
def run_campaign(keyword_query, num_leads=5, output_file="campaign_results.csv"):
    accounts = load_accounts()
    account_idx = 0
    current_account = accounts[account_idx]
    
    print(f"\n========================================================")
    print(f"🚀 STARTING ADVANCED CAMPAIGN (MULTI-ACCOUNT ROTATION)")
    print(f"👤 Configured Accounts : {len(accounts)}")
    print(f"🔍 Search Query        : '{keyword_query}'")
    print(f"🎯 Target Leads        : {num_leads} (Batch limit)")
    print(f"========================================================\n")

    collected_urls = []
    seen_urls = set()

    # ----------------------------------------------------
    # 0. CROSS-RUN DEDUPLICATION
    # ----------------------------------------------------
    if os.path.exists(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if "linkedin_url" in row:
                        clean = row["linkedin_url"].split("?")[0].rstrip("/")
                        seen_urls.add(clean)
            print(f"📦 Loaded {len(seen_urls)} previously scraped profiles to avoid duplicates.")
        except Exception as e:
            print(f"⚠️ Could not read previous results for deduplication: {e}")

    with sync_playwright() as p:
        browser, page = launch_account_context(p, current_account)

        def rotate_account():
            nonlocal account_idx, current_account, browser, page
            try:
                browser.close()
            except Exception:
                pass
            
            account_idx += 1
            if account_idx >= len(accounts):
                print("\n❌ ALL CONFIGURED LINKEDIN ACCOUNTS HAVE BEEN RATE LIMITED OR EXHAUSTED!")
                return False
            
            current_account = accounts[account_idx]
            print(f"\n🔄 ROTATING TO ACCOUNT [{account_idx + 1}/{len(accounts)}]: '{current_account.get('id')}'")
            browser, page = launch_account_context(p, current_account)
            
            if not check_login_status(page, browser, current_account):
                print(f"⚠️ Account '{current_account.get('id')}' failed login check. Attempting next account...")
                return rotate_account()
            return True

        # Check initial account login status
        if not check_login_status(page, browser, current_account):
            print(f"⚠️ Initial account '{current_account.get('id')}' failed login check. Rotating...")
            if not rotate_account():
                return

        # ----------------------------------------------------
        # 1. SEARCH AND COLLECT URLS
        # ----------------------------------------------------
        print("\n🔎 Initiating LinkedIn Native Search...")
        # ----------------------------------------------------
        # 1. SEARCH AND COLLECT URLS (MULTI-QUERY TARGETING EMAILS & RESUMES)
        # ----------------------------------------------------
        print("\n🔎 Initiating High-Yield LinkedIn Native Search...")
        
        # High-yield search queries targeting candidates with public emails, contacts, or resumes
        if isinstance(keyword_query, list):
            target_queries = keyword_query
        elif keyword_query and "gmail" in keyword_query.lower():
            target_queries = [keyword_query]
        else:
            target_queries = [
                '("MS" OR "Master" OR "MBA" OR "M.S.") AND ("United States" OR "USA") AND ("@gmail.com" OR "gmail" OR "email" OR "contact")',
                '("MS" OR "Master" OR "Postgraduate") AND ("Open to Work" OR "OPT") AND ("United States" OR "USA")',
                '("MS Graduate" OR "Master\'s Graduate") AND ("United States" OR "USA") AND ("email" OR "contact")',
                '("MS in" OR "Master of Science") AND ("OPT" OR "Open to Work") AND ("USA" OR "United States")'
            ]

        for q_idx, query_str in enumerate(target_queries, 1):
            if len(collected_urls) >= num_leads or account_idx >= len(accounts):
                break

            print(f"\n🎯 [Query {q_idx}/{len(target_queries)}] Searching: '{query_str}'")
            encoded_query = urllib.parse.quote(query_str)
            current_page = 1

            while current_page <= 5 and len(collected_urls) < num_leads and account_idx < len(accounts):
                search_url = f"https://www.linkedin.com/search/results/people/?keywords={encoded_query}&page={current_page}"
                print(f"   -> [{current_account.get('id')}] Scraping search page {current_page}...")
                
                try:
                    page.goto(search_url, wait_until="domcontentloaded")
                    human_delay(3, 6)
                    
                    limited, reason = is_rate_limited(page)
                    if limited:
                        print(f"   ⚠️ RATE LIMIT DETECTED on '{current_account.get('id')}': {reason}")
                        if not rotate_account():
                            break
                        continue

                    for _ in range(3):
                        page.evaluate("window.scrollBy(0, 500);")
                        human_delay(1, 2)
                    
                    links = page.locator('a[href*="/in/"]').all()
                    found_on_page = 0
                    
                    for link in links:
                        href = link.get_attribute("href")
                        if href:
                            clean_url = href.split("?")[0].rstrip("/")
                            if "linkedin.com" not in clean_url:
                                clean_url = "https://www.linkedin.com" + clean_url
                                
                            if clean_url not in collected_urls and clean_url not in seen_urls and len(collected_urls) < num_leads:
                                collected_urls.append(clean_url)
                                found_on_page += 1

                    print(f"      Found {found_on_page} NEW profiles on page {current_page}. (Total Queue: {len(collected_urls)}/{num_leads})")

                    if found_on_page == 0:
                        human_delay(2, 4)
                        break

                    current_page += 1
                    
                except Exception as e:
                    print(f"   ❌ Error during search: {e}")
                    limited, reason = is_rate_limited(page)
                    if limited:
                        print(f"   ⚠️ RATE LIMIT DETECTED on '{current_account.get('id')}': {reason}")
                        if not rotate_account():
                            break
                        continue
                    else:
                        break

        print(f"\n✅ Finished searching. Proceeding to extract {len(collected_urls)} profiles.")

        # ----------------------------------------------------
        # 2. SCRAPE PROFILES WITH STEALTH, FILTERING & ROTATION
        # ----------------------------------------------------
        print("\n🕵️‍♂️ Starting Profile Data Extraction...")
        all_candidates = []
        file_exists = os.path.exists(output_file)
        fieldnames = ["name", "degree", "summary", "contact", "email", "technology", "visa", "year", "university", "resume", "posts", "linkedin_url", "scraped_at"]

        if not file_exists:
            try:
                with open(output_file, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
            except PermissionError:
                print(f"❌ FATAL ERROR: Please close '{output_file}' in Excel or your text editor before running!")
                browser.close()
                return

        for i, url in enumerate(collected_urls, 1):
            if url in seen_urls:
                continue

            profile_success = False
            
            while not profile_success and account_idx < len(accounts):
                print(f"\n[{i}/{len(collected_urls)}] [{current_account.get('id')}] Extracting: {url}")
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    human_delay(2, 4)

                    limited, reason = is_rate_limited(page)
                    if limited:
                        print(f"   ⚠️ RATE LIMIT DETECTED on '{current_account.get('id')}': {reason}")
                        if not rotate_account():
                            break
                        continue

                    for _ in range(2):
                        page.evaluate("window.scrollBy(0, document.body.scrollHeight/4);")
                        time.sleep(random.uniform(0.5, 1.5))
                        page.evaluate("window.scrollBy(0, -150);")
                        human_delay(1, 3)
                    
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight/1.5);")
                    human_delay(2, 4)

                    # Contact modal
                    contact_info_text = ""
                    try:
                        contact_link = page.locator("a#top-card-text-details-contact-info")
                        if contact_link.count() > 0:
                            contact_link.click()
                            time.sleep(2)
                            dialog = page.locator("div[role='dialog']")
                            if dialog.count() > 0:
                                contact_info_text = dialog.inner_text()
                            close_btn = page.locator("button[aria-label='Dismiss']")
                            if close_btn.count() > 0:
                                close_btn.click()
                                time.sleep(1)
                    except Exception:
                        pass

                    page_text = page.inner_text("body") + " \n " + contact_info_text

                    university = extract_university(page_text)
                    technology = extract_technologies(page_text)
                    is_postgrad, degree_label = verify_strict_postgrad(page_text)

                    if university == "N/A":
                        print(f"   ⏭️ SKIPPING: No valid US University found in whitelist.")
                    elif not is_postgrad:
                        print(f"   ⏭️ SKIPPING: No Master's / postgraduate degree signal found in profile.")
                    else:
                        email = extract_email(page_text)
                        resume_info = extract_resume_links(page_text)
                        posts_content = "N/A"

                        # IFF email could not be retrieved from main profile, read posts!
                        if email == "N/A":
                            print(f"   🔍 Email not found on main profile. Reading candidate's recent posts...")
                            posts_text, post_email = fetch_profile_posts(page, url)
                            posts_content = posts_text
                            if post_email != "N/A":
                                email = post_email
                                print(f"   📧 Found email in candidate's posts: {email}")

                        candidate = {
                            "name": extract_name(url, page_text),
                            "degree": degree_label,
                            "summary": extract_summary(page_text),
                            "contact": extract_contact(page_text),
                            "email": email,
                            "technology": technology,
                            "visa": extract_visa(page_text),
                            "year": extract_year(page_text),
                            "university": university,
                            "resume": resume_info,
                            "posts": posts_content,
                            "linkedin_url": url,
                            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }

                        all_candidates.append(candidate)
                        seen_urls.add(url)
                        
                        try:
                            with open(output_file, "a", newline="", encoding="utf-8") as f:
                                writer = csv.DictWriter(f, fieldnames=fieldnames)
                                writer.writerow(candidate)
                            print(f"   -> SAVED: {candidate['name']} | Email: {candidate['email']} | Tech: {candidate['technology']} | Uni: {candidate['university']}")
                        except PermissionError:
                            print(f"   ❌ Could not save {candidate['name']}! Please close '{output_file}' in Excel immediately!")

                    profile_success = True

                except Exception as e:
                    print(f"   ❌ Error scraping profile: {e}")
                    limited, reason = is_rate_limited(page)
                    if limited:
                        print(f"   ⚠️ RATE LIMIT DETECTED on '{current_account.get('id')}': {reason}")
                        if not rotate_account():
                            break
                        continue
                    else:
                        profile_success = True

                    delay = random.uniform(12, 22)
                    time.sleep(delay)

        try:
            browser.close()
        except Exception:
            pass

    print(f"\n🎉 Campaign Complete! Successfully verified and saved {len(all_candidates)} new leads.")

# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    LEAD_COUNT = 10  # Batch target per run
    run_campaign(keyword_query=None, num_leads=LEAD_COUNT)