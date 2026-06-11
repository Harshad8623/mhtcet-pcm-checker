"""
checker/browser.py — Playwright browser lifecycle manager with session persistence.
"""

import os
import logging
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

logger = logging.getLogger("mhtcet.browser")

_playwright = None
_browser: Browser = None
_context: BrowserContext = None

SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "session_state.json")


def get_browser_context() -> BrowserContext:
    """Return a persistent browser context (reuse session across checks)."""
    global _playwright, _browser, _context

    if _context is not None:
        try:
            # Quick health check — if this fails, context is dead
            _context.pages
            return _context
        except Exception:
            logger.warning("Browser context was stale. Recreating.")
            _context = None
            _browser = None

    logger.info("Launching Playwright Chromium browser...")
    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
        ]
    )

    # Load saved session if it exists
    if os.path.exists(SESSION_FILE):
        logger.info("Loading saved browser session...")
        _context = _browser.new_context(
            storage_state=SESSION_FILE,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
        )
    else:
        _context = _browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
        )

    # Mask automation signals
    _context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    return _context


def save_session(context: BrowserContext):
    """Persist cookies/storage for session reuse."""
    try:
        context.storage_state(path=SESSION_FILE)
        logger.info("Browser session saved.")
    except Exception as e:
        logger.error(f"Failed to save session: {e}")


def close_browser():
    """Gracefully close browser resources."""
    global _playwright, _browser, _context
    try:
        if _context:
            _context.close()
        if _browser:
            _browser.close()
        if _playwright:
            _playwright.stop()
        logger.info("Browser closed cleanly.")
    except Exception as e:
        logger.error(f"Error closing browser: {e}")
    finally:
        _context = None
        _browser = None
        _playwright = None


def new_page() -> Page:
    """Open a fresh page from the current context."""
    ctx = get_browser_context()
    return ctx.new_page()
