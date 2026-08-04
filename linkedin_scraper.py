"""SeleniumBase CDP (UC) + Playwright LinkedIn people-search scraper.

Chromium is launched by seleniumbase's sb_cdp driver (undetected, can solve
Cloudflare/LinkedIn captchas), and Playwright attaches to that same browser
over CDP.
"""

from __future__ import annotations

from encodings.aliases import aliases
import time
import random
import urllib.parse
from pathlib import Path


from seleniumbase import sb_cdp
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from config import (
    HEADLESS,
    LINKEDIN_EMAIL,
    LINKEDIN_PASSWORD,
    MAX_DELAY,
    MAX_PAGES_PER_UNIVERSITY,
    MIN_DELAY,
    STORAGE_STATE,
    USER_AGENT,
)

GOOGLE_SEARCH_URL = "https://www.google.com/search"


def _pause(factor: float = 1.0) -> None:
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY) * factor)


class LinkedInScraper:
    def __init__(self) -> None:
        self._pw = None
        self.sb = None                      # seleniumbase CDP driver
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

    # ---------- lifecycle ----------
    def start(self, proxy= None) -> None:
        # 1) SeleniumBase launches an undetected Chrome and exposes a CDP endpoint.
        self.sb = sb_cdp.Chrome(
                "about:blank",
                proxy=proxy,
                use_chromium=True,
                headless=HEADLESS,
                agent=USER_AGENT,
                incognito=False,
        )
        endpoint_url = self.sb.get_endpoint_url()

        
        # 2) Playwright attaches to that exact browser (no new browser is spawned).
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(endpoint_url)
        self._context = self._browser.contexts[0]

        # Restore cookies from a previous run (storage_state cannot be passed to
        # an already-running browser, so we replay the cookies instead).
        state_path = Path(STORAGE_STATE)
        if state_path.exists():
            import json

            try:
                cookies = json.loads(state_path.read_text()).get("cookies", [])
                if cookies:
                    self._context.add_cookies(cookies)
            except Exception as exc:  # corrupt/legacy state file
                print("[state] could not reuse saved session:", exc)

        self._context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()

    def _new_page(self) -> Page:
        assert self._context
        return self._context.new_page()

    def close(self) -> None:
        if self._context:
            try:
                self._context.storage_state(path=STORAGE_STATE)
            except Exception:
                pass
        if self._browser:
            self._browser.close()          # detaches CDP only
        if self._pw:
            self._pw.stop()
        if self.sb:
            self.sb.driver.stop()                # actually closes Chrome

    
        
    # ---------- captcha / challenge handling (SeleniumBase side) ----------
    def _solve_challenge(self, timeout: int = 20) -> None:
        """Hand control to SeleniumBase to click through a captcha / Cloudflare
        turnstile in the SAME tab Playwright is driving."""
        try:
            self.sb.sleep(5)
            self.sb.solve_captcha()
            self.sb.sleep(5)
            # LinkedIn/duckduckgo disable inputs while verifying.
            self.sb.wait_for_element_absent("input[disabled]", timeout=timeout)
            self.sb.sleep(2)
        except Exception as exc:
            print("[captcha] solve attempt finished/failed:", exc)

    def solve_challenge(self, timeout: int = 20) -> None:
        self._solve_challenge(timeout)

    @staticmethod
    def _looks_blocked(url: str) -> bool:
        return any(
            x in url.lower()
            for x in ("blocked", "challenge", "captcha", "sorry/index")
        )
    def check_and_solve_if_blocked(self, page: Page) -> None:
        if not self._looks_blocked(page.url):
            return

        print("[captcha] Challenge detected.")

        try:
            self._accept_bing_consent(page)
        except Exception:
            pass

        self.solve_challenge()

        print("Current URL:", page.url)
        print("Search Count:", page.locator("#search").count())
        print("Page Title:", page.title())

        print("[captcha] Challenge solved (or attempted).")

    # ---------- auth ----------
    def login(self, no_login: bool = False) -> None:
        if no_login or not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
            print("[auth] skipping LinkedIn login (no credentials or --no-login)")
            return

        page = self.page
        assert page

        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        _pause(0.4)

        if "/feed" in page.url and page.locator(
            "input.search-global-typeahead__input"
        ).count():
            print("[auth] reusing saved session")
            return

        print("[auth] logging in with credentials from .env")
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

        self.check_and_solve_if_blocked(page)
            

        page.fill("#username", LINKEDIN_EMAIL)
        _pause(0.2)
        page.fill("#password", LINKEDIN_PASSWORD)
        _pause(0.2)
        page.click("button[type=submit]")
        page.wait_for_load_state("domcontentloaded")
        _pause(0.5)

        # Captcha / checkpoint -> solved automatically instead of waiting on input().
        for attempt in range(3):
            if not self._looks_blocked(page.url):
                break

            print(f"[auth] challenge detected ({attempt + 1}/3)")
            self.check_and_solve_if_blocked(page)
            page.wait_for_load_state("domcontentloaded")
            _pause(0.6)

        
        if self._looks_blocked(page.url):
            raise Exception("GOOGLE_CAPTCHA")
            # Fresh page after restarting browser
            page = self.page
            assert page

            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

            page.fill("#username", LINKEDIN_EMAIL)
            _pause(0.2)

            page.fill("#password", LINKEDIN_PASSWORD)
            _pause(0.2)

            page.click("button[type=submit]")
            page.wait_for_load_state("domcontentloaded")
        self._context.storage_state(path=STORAGE_STATE)
        print("[auth] session saved to", STORAGE_STATE)

    # ---------- scrolling ----------
    def scroll_results(self, page: Page) -> None:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(random.uniform(0.8, 1.4))
        page.evaluate("window.scrollTo(0, 0)")

    # ---------- extraction ----------
    def _accept_bing_consent(self, page: Page) -> None:
        buttons = page.locator("button")
        for i in range(buttons.count()):
            try:
                label = (buttons.nth(i).inner_text()).strip().lower()
            except Exception:
                continue
            if any(term in label for term in ["i agree", "accept all", "agree"]):
                try:
                    buttons.nth(i).click()
                    _pause(0.4)
                    return
                except Exception:
                    continue

    def _extract_google_results(self, page: Page) -> list[dict]:
        return page.evaluate(
        """() => {

            const trimTrailingSlashes = (value) => {
                while (value.endsWith('/')) {
                    value = value.slice(0, -1);
                }
                return value;
            };

            const rows = [];

            const anchors = Array.from(
                document.querySelectorAll('a[href*="linkedin.com/in/"]')
            );

            for (const anchor of anchors) {

                let href = anchor.getAttribute("href") || "";

                if (href.startsWith("/url?")) {
                    const params = new URLSearchParams(
                        href.slice(href.indexOf("?"))
                    );
                    href = params.get("q") || "";
                }

                if (!href || !href.includes("linkedin.com/in/"))
                    continue;

                const url = trimTrailingSlashes(
                    href.split("?")[0]
                );

                const text =
                    anchor.closest("div")?.innerText.trim() ||
                    anchor.innerText.trim();

                rows.push({
                    url: url,
                    text: text,
                });
            }

            return rows;

        }"""
    )

    def collect_blob(self, rows: list[dict]) -> str:
        return "\n---\n".join(f"URL: {row['url']}\nCARD: {row['text']}" for row in rows)

    def search_university(
        self, university: str, aliases: list[str] | None = None
    ) -> list[str]:
        """Google-search each university term; return one text blob per results page."""
        assert self._context
        blobs: list[str] = []

        terms = [university] + [
            a
            for a in (aliases or [])
            if a.strip().casefold() != university.casefold()
        ]

        for term in terms:
            query = f'site:linkedin.com/in "{term}"'
            for page_no in range(MAX_PAGES_PER_UNIVERSITY):
                page = self._new_page()
                try:
                    params = {"q": query,"num" : 10,"start": str(page_no * 10)}
                    url = f"{GOOGLE_SEARCH_URL}?{urllib.parse.urlencode(params)}"
                    page.goto(url, wait_until="domcontentloaded")
                    self.check_and_solve_if_blocked(page)
                    if self._looks_blocked(page.url):
                        raise Exception("GOOGLE_CAPTCHA")
                    

                    if not page.locator("#search").count():
                        print(f"    [{term}] page {page_no + 1}: no results renderd, stopping")
                        break

                    rows = self._extract_google_results(page)
                    self.check_and_solve_if_blocked(page)
                    if self._looks_blocked(page.url):
                        raise Exception("GOOGLE_CAPTCHA")
                    if not rows:
                        print(f"    [{term}] page {page_no + 1}: no results rendered, stopping")
                        break

                    self.scroll_results(page)
                    self.check_and_solve_if_blocked(page)
                    if self._looks_blocked(page.url):
                        raise Exception("GOOGLE_CAPTCHA")
                    blob = self.collect_blob(rows)
                    if not blob.strip():
                        break

                    blobs.append(blob)
                    print(f"    [{term}] page {page_no + 1}: captured {len(rows)} LinkedIn links")
                    _pause()
                finally:
                    page.close()

        return blobs