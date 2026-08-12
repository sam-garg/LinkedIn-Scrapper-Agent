import json
import os
import re
import time

from playwright.sync_api import sync_playwright
from google import genai
from dotenv import load_dotenv


# =========================================================
# CONFIG
# =========================================================

INPUT_FILE = "linkedin_urls.json"

PROMPT_FILE = "extraction_prompt.txt"

RAW_OUTPUT_FILE = "linkedin_profiles_data.txt"
FINAL_OUTPUT_FILE = "extracted_profiles.txt"
ERROR_FILE = "profile_errors.txt"

STORAGE_STATE = "storage_state.json"

#MODEL_NAME = "gemini-2.5-flash-lite"

WAIT_AFTER_PROFILE_LOAD = 15
PAGE_TIMEOUT = 60000


# =========================================================
# GEMINI
# =========================================================
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY environment variable is missing."
    )

client = genai.Client(
    api_key=GEMINI_API_KEY
)

# =========================================================
# LOAD PROMPT
# =========================================================

def load_prompt():

    with open(
        PROMPT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        return f.read()


# =========================================================
# LOAD URLS
# =========================================================

def load_urls():

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        data = json.load(f)

    urls = []

    if isinstance(data, list):

        for item in data:

            if isinstance(item, str):

                urls.append(item)

            elif (
                isinstance(item, dict)
                and "url" in item
            ):

                urls.append(item["url"])

    return urls


# =========================================================
# CLEAN URL
# =========================================================

def clean_url(url):

    match = re.search(
        r"https?://[^\s\])]+",
        url
    )

    if match:
        return match.group(0)

    return url


# =========================================================
# RAW EXTRACTION
# =========================================================

def extract_raw_text(page):

    print(
        "\n[EXTRACT] Extracting raw profile text..."
    )

    try:

        main = page.locator("main")

        if main.count() > 0:

            text = main.inner_text(
                timeout=15000
            ).strip()

        else:

            text = page.locator(
                "body"
            ).inner_text(
                timeout=15000
            ).strip()

        # Only remove excessive blank lines.
        # Do NOT classify or restructure the content.

        text = re.sub(
            r"\n{3,}",
            "\n\n",
            text
        ).strip()

        print(
            f"[EXTRACT] Characters: {len(text)}"
        )

        return text

    except Exception as e:

        print(
            "[EXTRACT] Failed:",
            e
        )

        return ""


# =========================================================
# GEMINI EXTRACTION
# =========================================================

def extract_with_gemini(
    raw_text,
    base_prompt
):

    prompt = base_prompt.replace(
        "{PROFILE_TEXT}",
        raw_text
    )

    print(
        "\n[GEMINI] Extracting required fields..."
    )

    interaction = client.interactions.create(
        model="gemini-3.5-flash",
        input=prompt
    )

    result = interaction.output_text.strip()

    return result 

# =========================================================
# SAVE RAW PROFILE
# =========================================================

def save_raw_profile(
    profile_number,
    url,
    raw_text
):

    with open(
        RAW_OUTPUT_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write("=" * 80)
        f.write("\n")

        f.write(
            f"PROFILE {profile_number}\n"
        )

        f.write("=" * 80)
        f.write("\n\n")

        f.write(
            f"URL:\n{url}\n\n"
        )

        f.write(raw_text)

        f.write("\n\n")


# =========================================================
# SAVE GEMINI RESULT
# =========================================================

def save_final_profile(
    profile_number,
    url,
    result
):

    with open(
        FINAL_OUTPUT_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write("=" * 80)
        f.write("\n")

        f.write(
            f"PROFILE {profile_number}\n"
        )

        f.write("=" * 80)
        f.write("\n\n")

        f.write(
            f"URL:\n{url}\n\n"
        )

        f.write(result)

        f.write("\n\n")


# =========================================================
# MAIN
# =========================================================

def main():

    urls = load_urls()

    base_prompt = load_prompt()

    print(
        f"[INIT] URLs: {len(urls)}"
    )

    print(
        f"[INIT] Prompt loaded from: "
        f"{PROMPT_FILE}"
    )


    # -----------------------------------------------------
    # CLEAR OUTPUT FILES
    # -----------------------------------------------------

    with open(
        RAW_OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "RAW LINKEDIN PROFILE DATA\n"
        )

        f.write(
            "=" * 80
            + "\n\n"
        )


    with open(
        FINAL_OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "EXTRACTED LINKEDIN PROFILE DATA\n"
        )

        f.write(
            "=" * 80
            + "\n\n"
        )


    with open(
        ERROR_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "PROFILE ERRORS\n"
        )

        f.write(
            "=" * 80
            + "\n\n"
        )


    extracted_count = 0
    error_count = 0


    # =====================================================
    # PLAYWRIGHT
    # =====================================================

    with sync_playwright() as p:

        print(
            "\n[PLAYWRIGHT] Launching browser..."
        )

        browser = p.chromium.launch(
            headless=False
        )

        context = browser.new_context(
            storage_state=STORAGE_STATE
        )


        # =================================================
        # PROFILES
        # =================================================

        for index, raw_url in enumerate(
            urls,
            start=1
        ):

            url = clean_url(raw_url)

            print("\n")
            print("=" * 80)

            print(
                f"[{index}/{len(urls)}]"
            )

            print(url)

            print("=" * 80)


            page = context.new_page()


            try:

                # -----------------------------------------
                # OPEN PROFILE
                # -----------------------------------------

                print(
                    "[PROFILE] Opening..."
                )

                start = time.perf_counter()

                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=PAGE_TIMEOUT
                )

                elapsed = (
                    time.perf_counter()
                    - start
                )

                print(
                    f"[PROFILE] Loaded after "
                    f"{elapsed:.2f}s"
                )

                if response:

                    print(
                        "[PROFILE] HTTP:",
                        response.status
                    )

                print(
                    "[PROFILE] URL:",
                    page.url
                )


                # -----------------------------------------
                # WAIT
                # -----------------------------------------

                print(
                    f"[PROFILE] Waiting "
                    f"{WAIT_AFTER_PROFILE_LOAD}s..."
                )

                time.sleep(
                    WAIT_AFTER_PROFILE_LOAD
                )


                # -----------------------------------------
                # AUTH WALL CHECK
                # -----------------------------------------

                current_url = page.url.lower()

                title = ""

                try:

                    title = page.title().lower()

                except Exception:

                    pass


                if (
                    "/login" in current_url
                    or "/authwall" in current_url
                    or "sign up | linkedin" in title
                ):

                    print(
                        "\n❌ AUTH WALL / LOGIN"
                    )

                    error_count += 1

                    with open(
                        ERROR_FILE,
                        "a",
                        encoding="utf-8"
                    ) as f:

                        f.write(
                            f"PROFILE {index}\n"
                        )

                        f.write(
                            f"URL: {url}\n"
                        )

                        f.write(
                            "Reason: LinkedIn auth wall\n\n"
                        )

                    continue


                # -----------------------------------------
                # RAW TEXT
                # -----------------------------------------

                raw_text = extract_raw_text(
                    page
                )


                if not raw_text:

                    print(
                        "❌ Empty profile"
                    )

                    error_count += 1

                    continue


                # -----------------------------------------
                # SAVE RAW DATA
                # -----------------------------------------

                save_raw_profile(
                    index,
                    url,
                    raw_text
                )


                # -----------------------------------------
                # GEMINI
                # -----------------------------------------

                extracted = extract_with_gemini(
                    raw_text,
                    base_prompt
                )


                # -----------------------------------------
                # PRINT RESULT
                # -----------------------------------------

                print("\n")
                print(
                    "========== EXTRACTED DATA =========="
                )

                print(extracted)

                print(
                    "====================================="
                )


                # -----------------------------------------
                # SAVE RESULT
                # -----------------------------------------

                save_final_profile(
                    index,
                    url,
                    extracted
                )


                extracted_count += 1


                print(
                    "\n✅ PROFILE COMPLETED"
                )


            except Exception as e:

                error_count += 1

                print(
                    "\n❌ PROFILE ERROR:",
                    type(e).__name__,
                    str(e)
                )

                with open(
                    ERROR_FILE,
                    "a",
                    encoding="utf-8"
                ) as f:

                    f.write(
                        f"PROFILE {index}\n"
                    )

                    f.write(
                        f"URL: {url}\n"
                    )

                    f.write(
                        f"Error: {type(e).__name__}\n"
                    )

                    f.write(
                        f"Message: {str(e)}\n\n"
                    )


            finally:

                print(
                    "[PROFILE] Closing page..."
                )

                page.close()


        # =================================================
        # SUMMARY
        # =================================================

        print("\n")
        print("=" * 80)

        print(
            f"✅ Completed: {extracted_count}"
        )

        print(
            f"❌ Errors: {error_count}"
        )

        print(
            f"📄 Raw data: {RAW_OUTPUT_FILE}"
        )

        print(
            f"📄 Extracted data: {FINAL_OUTPUT_FILE}"
        )

        print(
            f"📄 Errors: {ERROR_FILE}"
        )

        print("=" * 80)


        context.close()
        browser.close()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()