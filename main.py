import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
import json


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

RAW_DATA_FILE = BASE_DIR / "education_extracted.txt"
PROMPT_FILE = BASE_DIR / "filter_prompt.txt"
OUTPUT_FILE = BASE_DIR / "filter_results.txt"
SELECTED_URLS_FILE = BASE_DIR / "selected_urls.json"
MODEL_NAME = "gemini-3.5-flash"

# Delay between Gemini requests
# Increase this if you encounter rate-limit errors.
DELAY_BETWEEN_REQUESTS = 2

# Number of retry attempts if Gemini temporarily fails
MAX_RETRIES = 3

# Wait before retrying
RETRY_DELAY = 5


# ============================================================
# LOAD ENVIRONMENT
# ============================================================

load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY environment variable is missing. "
        "Please add GEMINI_API_KEY=your_key to .env"
    )


# ============================================================
# GEMINI CLIENT
# ============================================================

client = genai.Client(
    api_key=GEMINI_API_KEY
)


# ============================================================
# LOAD FILTER PROMPT
# ============================================================

def load_prompt():
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {PROMPT_FILE}"
        )

    with open(
        PROMPT_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        return f.read()


# ============================================================
# LOAD RAW LINKEDIN DATA
# ============================================================

def load_raw_data():
    if not RAW_DATA_FILE.exists():
        raise FileNotFoundError(
            f"Raw data file not found: {RAW_DATA_FILE}"
        )

    with open(
        RAW_DATA_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        return f.read()


# ============================================================
# SPLIT PROFILES
# ============================================================

def split_profiles(raw_data):
    """
    Splits linkedin_profiles_data.txt into individual profiles.

    Expected format:

    PROFILE 1
    ========
    ...
    PROFILE 2
    ========
    ...
    """

    pattern = r"(?m)^PROFILE\s+(\d+)\s*$"

    matches = list(
        re.finditer(
            pattern,
            raw_data
        )
    )

    profiles = []

    if not matches:
        print("[ERROR] No profiles found in raw data.")
        return profiles

    for index, match in enumerate(matches):

        profile_number = match.group(1)

        start = match.start()

        if index + 1 < len(matches):
            end = matches[index + 1].start()
        else:
            end = len(raw_data)

        profile_text = raw_data[start:end].strip()

        profiles.append(
            {
                "number": profile_number,
                "text": profile_text
            }
        )

    return profiles


# ============================================================
# EXTRACT URL FROM PROFILE
# ============================================================

def extract_profile_url(profile_text):

    match = re.search(
        r"https?://(?:www\.)?linkedin\.com/in/[^\s]+",
        profile_text,
        re.IGNORECASE
    )

    if match:
        return match.group(0).rstrip(".,)")

    return "Not Found"

# ============================================================
# SAVE SELECTED PROFILE URL
# ============================================================

def save_selected_url(
    profile_id,
    profile_url
):

    try:
        with open(
            SELECTED_URLS_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

    except (
        FileNotFoundError,
        json.JSONDecodeError
    ):

        data = []

    data.append({
        "id": profile_id,
        "url": profile_url
    })

    with open(
        SELECTED_URLS_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# EXTRACT NAME FROM GEMINI RESULT
# ============================================================

def extract_name(result):

    # NAME: Nikhilesh Gunnam
    match = re.search(
        r"(?im)^\s*\**\s*NAME\s*\**\s*:\s*(.+)$",
        result
    )

    if match:
        return match.group(1).strip().strip("*")

    # Profile Owner: Nikhilesh Gunnam
    match = re.search(
        r"(?im)^\s*[\*\-\s]*\**\s*PROFILE\s+OWNER\s*\**\s*:\s*(.+)$",
        result
    )

    if match:
        return match.group(1).strip().strip("*")

    return "Unknown"


# ============================================================
# EXTRACT DECISION
# ============================================================

def extract_decision(result):

    # Normalize response
    text = result.upper()

    # Remove markdown formatting
    text = re.sub(r"[*_`#]", "", text)

    # Check FINAL DECISION / DECISION
    match = re.search(
        r"(?:FINAL\s+DECISION|DECISION)\s*:\s*(KEEP|REJECT)\b",
        text
    )

    if match:
        return match.group(1)

    # Check RESULT: KEEP / RESULT: REJECT
    match = re.search(
        r"\bRESULT\s*:\s*(KEEP|REJECT)\b",
        text
    )

    if match:
        return match.group(1)

    # Check standalone KEEP / REJECT after FINAL DECISION or RESULT
    match = re.search(
        r"(?:FINAL\s+DECISION|RESULT)\s*:?\s*(?:\n\s*)*(KEEP|REJECT)\b",
        text
    )

    if match:
        return match.group(1)

    return "UNKNOWN"

# ============================================================
# CALL GEMINI
# ============================================================

def extract_with_gemini(
    raw_profile,
    base_prompt
):

    prompt = base_prompt.replace(
        "{PROFILE_TEXT}",
        raw_profile
    )

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            print(
                f"[GEMINI] Attempt {attempt}/{MAX_RETRIES}"
            )


            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt
            )

            if not response:
                raise RuntimeError(
                    "Gemini returned an empty response."
                )

            result = response.text

            if not result:
                raise RuntimeError(
                    "Gemini response contains no text."
                )

            return result.strip()

        except Exception as e:

            print(
                f"[GEMINI ERROR] {type(e).__name__}: {e}"
            )

            if attempt < MAX_RETRIES:

                print(
                    f"[RETRY] Waiting {RETRY_DELAY}s..."
                )

                time.sleep(RETRY_DELAY)

            else:

                print(
                    "[GEMINI] Maximum retries reached."
                )

    return None


# ============================================================
# SAVE RESULT IMMEDIATELY
# ============================================================

def save_result(
    profile_number,
    profile_url,
    result
):

    with open(
        OUTPUT_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            "\n"
            + "=" * 80
            + "\n"
        )

        f.write(
            f"PROFILE {profile_number}\n"
        )

        f.write(
            f"URL: {profile_url}\n"
        )

        f.write(
            "=" * 80
            + "\n\n"
        )

        if result:

            f.write(result)

        else:

            f.write(
                "FILTER ERROR\n"
            )

        f.write("\n\n")


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 80)
    print("LINKEDIN UG → FOREIGN PG FILTER")
    print("=" * 80)

    print(
        f"[INIT] Raw data: {RAW_DATA_FILE}"
    )
    

    print(
        f"[INIT] Prompt: {PROMPT_FILE}"
    )

    print(
        f"[INIT] Model: {MODEL_NAME}"
    )

    print(
        f"[INIT] Output: {OUTPUT_FILE}"
    )

    print("=" * 80)


    # --------------------------------------------------------
    # LOAD PROMPT
    # --------------------------------------------------------

    base_prompt = load_prompt()

    print(
        "[INIT] Filter prompt loaded successfully."
    )

    # --------------------------------------------------------
    # CLEAR SELECTED URLS FILE
    # --------------------------------------------------------

    with open(
        SELECTED_URLS_FILE,
        "w",
        encoding="utf-8"
        ) as f:

        json.dump(
            [],
            f,
            indent=2
        )
    # --------------------------------------------------------
    # LOAD RAW DATA
    # --------------------------------------------------------

    raw_data = load_raw_data()

    print(
        f"[INIT] Raw data loaded: {len(raw_data)} characters"
    )
    print("\n========== RAW DATA PREVIEW ==========\n")
    print(raw_data[:2000])
    print("\n======================================\n")

    # --------------------------------------------------------
    # SPLIT PROFILES
    # --------------------------------------------------------

    profiles = split_profiles(
        raw_data
    )

    print(
        f"[INIT] Profiles found: {len(profiles)}"
    )

    if not profiles:
        print(
            "[STOP] No profiles to process."
        )
        return


    print("=" * 80)


    # --------------------------------------------------------
    # PROCESS PROFILES
    # --------------------------------------------------------

    total = len(profiles)

    kept = 0
    rejected = 0
    errors = 0
    selected_id = 1

    for index, profile in enumerate(
        profiles,
        start=1
    ):

        profile_number = profile["number"]
        profile_text = profile["text"]

        profile_url = extract_profile_url(
            profile_text
        )


        print()
        print("=" * 80)

        print(
            f"[PROFILE {index}/{total}] "
            f"Processing PROFILE {profile_number}"
        )

        print(
            f"[URL] {profile_url}"
        )

        print(
            f"[TEXT] {len(profile_text)} characters"
        )

        print("=" * 80)


        # ----------------------------------------------------
        # SEND TO GEMINI
        # ----------------------------------------------------

        result = extract_with_gemini(
            profile_text,
            base_prompt
        )
        print("\n========== GEMINI RAW RESPONSE ==========\n")
        print(result)
        print("\n=========================================\n")


        # ----------------------------------------------------
        # HANDLE GEMINI FAILURE
        # ----------------------------------------------------

        if result is None:

            errors += 1

            print(
                "[RESULT] ERROR"
            )

            save_result(
                profile_number,
                profile_url,
                None
            )

            continue


        # ----------------------------------------------------
        # GET DECISION
        # ----------------------------------------------------

        decision = extract_decision(
            result
        )

        name = extract_name(
            result
        )


        print(
            f"[NAME] {name}"
        )

        print(
            f"[DECISION] {decision}"
        )


        if decision == "KEEP":

            kept += 1
            save_selected_url(
            selected_id,
            profile_url
            )

            print(
            f"[SELECTED] ID: {selected_id}"
            )

            print(
            f"[SELECTED] URL: {profile_url}"
            )

            selected_id += 1

        elif decision == "REJECT":

            rejected += 1

        else:

            errors += 1


        # ----------------------------------------------------
        # SAVE IMMEDIATELY
        # ----------------------------------------------------

        save_result(
            profile_number,
            profile_url,
            result
        )

        print(
            f"[SAVED] Result saved to {OUTPUT_FILE.name}"
        )


        # ----------------------------------------------------
        # DELAY
        # ----------------------------------------------------

        if index < total:

            print(
                f"[WAIT] Sleeping "
                f"{DELAY_BETWEEN_REQUESTS}s..."
            )

            time.sleep(
                DELAY_BETWEEN_REQUESTS
            )


    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    print()
    print("=" * 80)
    print("FILTERING COMPLETED")
    print("=" * 80)

    print(
        f"Total profiles : {total}"
    )

    print(
        f"KEEP           : {kept}"
    )

    print(
        f"REJECT         : {rejected}"
    )

    print(
        f"ERROR/UNKNOWN  : {errors}"
    )

    print(
        f"Output file    : {OUTPUT_FILE}"
    )

    print("=" * 80)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()