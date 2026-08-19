import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


# =========================================================
# CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

URLS_FILE = BASE_DIR / "linkedin_urls.json"
STORAGE_STATE = BASE_DIR / "storage_state.json"

EDUCATION_OUTPUT_FILE = BASE_DIR / "education_extracted.txt"

PAGE_TIMEOUT = 60000

# Wait after profile opens
WAIT_AFTER_PROFILE_LOAD = 5

# Small wait after locating/loading Education
WAIT_AFTER_EDUCATION = 2


# =========================================================
# LOAD URLS
# =========================================================

def load_urls():

    if not URLS_FILE.exists():
        raise FileNotFoundError(
            f"URLs file not found: {URLS_FILE}"
        )

    with open(
        URLS_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        data = json.load(f)

    # -----------------------------------------------------
    # Support:
    #
    # [
    #     "https://linkedin.com/in/...",
    #     "https://linkedin.com/in/..."
    # ]
    #
    # and also:
    #
    # {
    #     "urls": [...]
    # }
    # -----------------------------------------------------

    if isinstance(data, list):

        urls = data

    elif isinstance(data, dict):

        if "urls" in data:

            urls = data["urls"]

        else:

            raise ValueError(
                "JSON dictionary found, but 'urls' key is missing."
            )

    else:

        raise ValueError(
            "linkedin_urls.json must contain a list or "
            "a dictionary with an 'urls' key."
        )

    cleaned_urls = []

    for item in urls:

        if isinstance(item, dict):

            url = item.get("url")

        elif isinstance(item, str):

            url = item

        else:

            continue

        if not url:
            continue

        url = url.strip()

        if url:
            cleaned_urls.append(url)

    return cleaned_urls


# =========================================================
# CLEAN URL
# =========================================================

def clean_url(url):

    url = url.strip()

    # Remove query parameters
    url = url.split("?")[0]

    # Remove trailing slash
    url = url.rstrip("/")

    return url + "/"


# =========================================================
# DEBUG SCROLL + EDUCATION EXTRACTION
# =========================================================

def debug_scroll_and_check_education(page):

    print("\n[DEBUG] Finding scrollable elements...")

    scrollables = page.evaluate("""
    () => {
        const elements = [...document.querySelectorAll('*')];

        return elements
            .map((el, index) => {
                const style = getComputedStyle(el);

                return {
                    index: index,
                    tag: el.tagName,
                    id: el.id,
                    className: typeof el.className === 'string'
                        ? el.className.substring(0, 150)
                        : '',
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                    overflowY: style.overflowY
                };
            })
            .filter(el =>
                el.scrollHeight > el.clientHeight + 100 &&
                (
                    el.overflowY === 'auto' ||
                    el.overflowY === 'scroll'
                )
            )
            .sort(
                (a, b) =>
                    (b.scrollHeight - b.clientHeight) -
                    (a.scrollHeight - a.clientHeight)
            )
            .slice(0, 20);
    }
    """)

    print(
        f"[DEBUG] Scrollable elements found: "
        f"{len(scrollables)}"
    )

    for i, element in enumerate(scrollables):

        print(
            f"\n[DEBUG] SCROLLABLE #{i + 1}"
        )

        print(
            f"  Tag        : {element['tag']}"
        )

        print(
            f"  ID         : {element['id']}"
        )

        print(
            f"  Class      : {element['className']}"
        )

        print(
            f"  ScrollHeight: {element['scrollHeight']}"
        )

        print(
            f"  ClientHeight: {element['clientHeight']}"
        )

        print(
            f"  OverflowY   : {element['overflowY']}"
        )

    # -----------------------------------------------------
    # FIND WORKSPACE
    # -----------------------------------------------------

    workspace = page.locator(
        "main#workspace"
    )

    if workspace.count() == 0:

        print(
            "[DEBUG] ❌ Workspace not found."
        )

        return ""

    print(
        "\n[DEBUG] Testing workspace scrolling..."
    )

    education_section = None

    # -----------------------------------------------------
    # SCROLL WORKSPACE
    # -----------------------------------------------------

    for i in range(1, 15):

        workspace.evaluate("""
            el => {
                el.scrollTop = el.scrollTop + 700;
            }
        """)

        time.sleep(1.5)

        scroll_position = workspace.evaluate(
            "el => el.scrollTop"
        )

        workspace_height = workspace.evaluate(
            "el => el.scrollHeight"
        )

        page_text = page.locator(
            "body"
        ).inner_text(
            timeout=10000
        )

        # -------------------------------------------------
        # IMPORTANT:
        #
        # Do NOT search for the word "Education" anywhere
        # in the profile.
        #
        # Search for an exact h2 heading instead.
        # -------------------------------------------------

        headings = page.locator("h2")

        try:

            heading_count = headings.count()

        except Exception:

            heading_count = 0

        for j in range(heading_count):

            try:

                heading = headings.nth(j)

                heading_text = heading.inner_text(
                    timeout=2000
                ).strip()

                if heading_text.lower() == "education":

                    print(
                        "\n[DEBUG] ✅ EDUCATION HEADING FOUND"
                    )

                    try:

                        heading.scroll_into_view_if_needed()

                    except Exception:

                        pass

                    time.sleep(
                        WAIT_AFTER_EDUCATION
                    )

                    # -------------------------------------
                    # Get actual Education section
                    # -------------------------------------

                    section = heading.locator(
                        "xpath=ancestor::section[1]"
                    )

                    if section.count() > 0:

                        education_section = section

                    else:

                        education_section = heading.locator(
                            "xpath=.."
                        )

                    break

            except Exception:

                continue

        print(
            f"[DEBUG] Scroll {i}/14 | "
            f"Position={scroll_position} | "
            f"Height={workspace_height} | "
            f"Chars={len(page_text)} | "
            f"Education="
            f"{'YES' if education_section else 'NO'}"
        )

        if education_section:

            break

    # -----------------------------------------------------
    # EDUCATION NOT FOUND
    # -----------------------------------------------------

    if education_section is None:

        print(
            "\n[DEBUG] ❌ EDUCATION NOT FOUND"
        )

        # Save current raw page text for debugging

        with open(
            BASE_DIR / "debug_full_profile.txt",
            "w",
            encoding="utf-8"
        ) as f:

            f.write(page_text)

        print(
            "[DEBUG] Raw text saved to "
            "debug_full_profile.txt"
        )

        return ""

    # -----------------------------------------------------
    # PAGE DIMENSIONS
    # -----------------------------------------------------

    body_info = page.evaluate("""
    () => ({
        bodyScrollHeight: document.body.scrollHeight,
        bodyClientHeight: document.body.clientHeight,
        documentScrollHeight: document.documentElement.scrollHeight,
        documentClientHeight: document.documentElement.clientHeight
    })
    """)

    print(
        "\n[DEBUG] PAGE DIMENSIONS:"
    )

    print(
        f"  Body scrollHeight: "
        f"{body_info['bodyScrollHeight']}"
    )

    print(
        f"  Body clientHeight: "
        f"{body_info['bodyClientHeight']}"
    )

    print(
        f"  Document scrollHeight: "
        f"{body_info['documentScrollHeight']}"
    )

    print(
        f"  Document clientHeight: "
        f"{body_info['documentClientHeight']}"
    )

    # -----------------------------------------------------
    # EXTRACT ACTUAL EDUCATION SECTION
    # -----------------------------------------------------

    try:

        education_text = education_section.inner_text(
            timeout=15000
        ).strip()

    except Exception as e:

        print(
            "[DEBUG] ❌ Education extraction failed:",
            e
        )

        return ""

    # Remove excessive blank lines

    education_text = re.sub(
        r"\n{3,}",
        "\n\n",
        education_text
    ).strip()

    # -----------------------------------------------------
    # DISPLAY EDUCATION
    # -----------------------------------------------------

    print(
        "\n========== EDUCATION =========="
    )

    print(
        education_text
    )

    print(
        "==============================="
    )

    # -----------------------------------------------------
    # SAVE FULL RAW PROFILE FOR DEBUGGING
    # -----------------------------------------------------

    try:

        page_text = page.locator(
            "body"
        ).inner_text(
            timeout=10000
        )

    except Exception:

        page_text = ""

    print(
        f"\n[DEBUG] Characters: "
        f"{len(page_text)}"
    )

    print(
        "[DEBUG] Education: YES"
    )

    with open(
        BASE_DIR / "debug_full_profile.txt",
        "w",
        encoding="utf-8"
    ) as f:

        f.write(page_text)

    print(
        "[DEBUG] Raw text saved to "
        "debug_full_profile.txt"
    )

    return education_text


# =========================================================
# SAVE EDUCATION DATA
# =========================================================

def save_education(
    index,
    url,
    education_text
):

    with open(
        EDUCATION_OUTPUT_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            "\n"
        )

        f.write(
            "=" * 80
        )

        f.write(
            "\n"
        )

        f.write(
            f"PROFILE {index}"
        )

        f.write(
            "\n"
        )

        f.write(
            "=" * 80
        )

        f.write(
            "\n\n"
        )

        f.write(
            "URL:\n"
        )

        f.write(
            url
        )

        f.write(
            "\n\n"
        )

        f.write(
            "EDUCATION:\n"
        )

        f.write(
            education_text
        )

        f.write(
            "\n"
        )


# =========================================================
# MAIN
# =========================================================

def main():

    print(
        "=" * 80
    )

    print(
        "LINKEDIN EDUCATION EXTRACTOR"
    )

    print(
        "=" * 80
    )

    print(
        f"[INIT] URLs file: {URLS_FILE}"
    )

    print(
        f"[INIT] Storage state: {STORAGE_STATE}"
    )

    print(
        f"[INIT] Output: {EDUCATION_OUTPUT_FILE}"
    )

    print(
        "=" * 80
    )

    # -----------------------------------------------------
    # LOAD URLS
    # -----------------------------------------------------

    urls = load_urls()

    print(
        f"[INIT] URLs loaded: {len(urls)}"
    )

    # -----------------------------------------------------
    # CHECK STORAGE STATE
    # -----------------------------------------------------

    if not STORAGE_STATE.exists():

        raise FileNotFoundError(
            f"storage_state.json not found: "
            f"{STORAGE_STATE}"
        )

    # -----------------------------------------------------
    # CLEAR OLD OUTPUT
    # -----------------------------------------------------

    with open(
        EDUCATION_OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "LINKEDIN EDUCATION EXTRACTION\n"
        )

        f.write(
            "=" * 80
        )

        f.write(
            "\n"
        )

    extracted_count = 0
    not_found_count = 0
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

            url = clean_url(
                raw_url
            )

            print(
                "\n"
            )

            print(
                "=" * 80
            )

            print(
                f"[{index}/{len(urls)}]"
            )

            print(
                url
            )

            print(
                "=" * 80
            )

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
                        EDUCATION_OUTPUT_FILE,
                        "a",
                        encoding="utf-8"
                    ) as f:

                        f.write(
                            "\n"
                        )

                        f.write(
                            "=" * 80
                        )

                        f.write(
                            "\n"
                        )

                        f.write(
                            f"PROFILE {index}"
                        )

                        f.write(
                            "\n"
                        )

                        f.write(
                            f"URL: {url}"
                        )

                        f.write(
                            "\n"
                        )

                        f.write(
                            "STATUS: AUTH WALL / LOGIN"
                        )

                        f.write(
                            "\n"
                        )

                    continue

                # -----------------------------------------
                # EDUCATION EXTRACTION
                # -----------------------------------------

                education_text = (
                    debug_scroll_and_check_education(
                        page
                    )
                )

                if education_text:

                    save_education(
                        index,
                        url,
                        education_text
                    )

                    extracted_count += 1

                    print(
                        "\n✅ EDUCATION EXTRACTED AND SAVED"
                    )

                else:

                    not_found_count += 1

                    print(
                        "\n❌ EDUCATION NOT FOUND"
                    )

                print(
                    "\n[DEBUG] Test completed "
                    "for this profile."
                )

            except Exception as e:

                error_count += 1

                print(
                    "\n❌ PROFILE ERROR:",
                    type(e).__name__,
                    str(e)
                )

                with open(
                    EDUCATION_OUTPUT_FILE,
                    "a",
                    encoding="utf-8"
                ) as f:

                    f.write(
                        "\n"
                    )

                    f.write(
                        "=" * 80
                    )

                    f.write(
                        "\n"
                    )

                    f.write(
                        f"PROFILE {index}"
                    )

                    f.write(
                        "\n"
                    )

                    f.write(
                        "=" * 80
                    )

                    f.write(
                        "\n\n"
                    )

                    f.write(
                        "URL:\n"
                    )

                    f.write(
                        url
                    )

                    f.write(
                        "\n\n"
                    )

                    f.write(
                        f"STATUS: ERROR - "
                        f"{type(e).__name__}\n"
                    )

                    f.write(
                        f"MESSAGE: {str(e)}\n"
                    )

            finally:

                print(
                    "[PROFILE] Closing page..."
                )

                page.close()

        # =================================================
        # SUMMARY
        # =================================================

        print(
            "\n"
        )

        print(
            "=" * 80
        )

        print(
            "EDUCATION EXTRACTION COMPLETED"
        )

        print(
            "=" * 80
        )

        print(
            f"Total profiles : {len(urls)}"
        )

        print(
            f"Education found: {extracted_count}"
        )

        print(
            f"Not found      : {not_found_count}"
        )

        print(
            f"Errors         : {error_count}"
        )

        print(
            f"Output file    : {EDUCATION_OUTPUT_FILE}"
        )

        print(
            "=" * 80
        )

        context.close()

        browser.close()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()