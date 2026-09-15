from playwright.sync_api import sync_playwright


with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=False
    )

    context = browser.new_context()

    page = context.new_page()

    page.goto(
        "https://www.linkedin.com/login",
        wait_until="domcontentloaded"
    )

    print("\nLogin to LinkedIn in the browser.")
    print("After login is complete, come back here.")
    input("\nPress ENTER after successful login...")

    context.storage_state(
        path="storage_state.json"
    )

    print("\n✅ Session saved to storage_state.json")

    browser.close()