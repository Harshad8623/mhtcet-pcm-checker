"""
checker/login.py — MHTCET portal login automation using Playwright.
"""

import os
import logging
import time
from datetime import datetime
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from checker.browser import new_page, save_session, get_browser_context

logger = logging.getLogger("mhtcet.login")

LOGIN_URL = os.getenv("LOGIN_URL", "https://portal-2026.mahacet.org")
SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "..", "screenshots")

# Selectors — update these if the portal UI changes
SELECTORS = {
    "email": [
        "input[type='email']",
        "input[name='email']",
        "input[id*='email']",
        "input[placeholder*='Email']",
        "input[placeholder*='email']",
    ],
    "password": [
        "input[type='password']",
        "input[name='password']",
        "input[id*='password']",
    ],
    "submit": [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Login')",
        "button:has-text('Sign In')",
        "button:has-text('Submit')",
    ],
    "error": [
        ".alert-danger",
        ".error-message",
        "[class*='error']",
        "[class*='alert']",
        "div:has-text('Invalid')",
        "div:has-text('incorrect')",
    ],
}


def _screenshot(page: Page, name: str) -> str:
    """Save a screenshot and return its path."""
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(SCREENSHOTS_DIR, f"{name}_{ts}.png")
    try:
        page.screenshot(path=path, full_page=True)
        logger.info(f"Screenshot saved: {path}")
    except Exception as e:
        logger.warning(f"Could not save screenshot: {e}")
        path = None
    return path


def _try_selector(page: Page, selectors: list, timeout=5000):
    """Try multiple selectors, return the first one found."""
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=timeout)
            if el:
                return el
        except Exception:
            continue
    return None


def attempt_login(email: str, password: str) -> dict:
    """
    Attempt to log in to the MHTCET portal.

    Returns:
        {
            "success": bool,
            "page": Page | None,
            "screenshot": str | None,
            "error": str | None,
            "page_title": str
        }
    """
    page = new_page()
    screenshot_path = None
    result = {"success": False, "page": None, "screenshot": None, "error": None, "page_title": ""}

    try:
        logger.info(f"Navigating to: {LOGIN_URL}")
        page.goto(LOGIN_URL, timeout=30000, wait_until="domcontentloaded")
        time.sleep(2)  # Let JS render

        result["page_title"] = page.title()
        logger.info(f"Page title: {result['page_title']}")

        # Check if already logged in (session reuse)
        page_text = page.inner_text("body")
        if _is_logged_in(page_text, page):
            logger.info("✅ Already logged in via saved session!")
            result["success"] = True
            result["page"] = page
            return result

        # Find & fill email
        email_el = _try_selector(page, SELECTORS["email"])
        if not email_el:
            screenshot_path = _screenshot(page, "login_no_email_field")
            raise ValueError("Could not find email input field. Portal UI may have changed.")

        email_el.click()
        email_el.fill(email)
        logger.info("Email entered.")

        # Find & fill password
        pass_el = _try_selector(page, SELECTORS["password"])
        if not pass_el:
            screenshot_path = _screenshot(page, "login_no_password_field")
            raise ValueError("Could not find password input field.")

        pass_el.click()
        pass_el.fill(password)
        logger.info("Password entered.")

        # Submit
        submit_el = _try_selector(page, SELECTORS["submit"])
        if not submit_el:
            screenshot_path = _screenshot(page, "login_no_submit_btn")
            raise ValueError("Could not find submit button.")

        submit_el.click()
        logger.info("Login form submitted, waiting for response...")

        # Wait for navigation
        try:
            page.wait_for_load_state("domcontentloaded", timeout=20000)
        except PlaywrightTimeout:
            pass

        time.sleep(3)

        # Check for error messages
        page_text = page.inner_text("body")
        for err_sel in SELECTORS["error"]:
            try:
                err_el = page.query_selector(err_sel)
                if err_el:
                    err_text = err_el.inner_text().strip()
                    if err_text and len(err_text) < 200:
                        screenshot_path = _screenshot(page, "login_error")
                        raise ValueError(f"Login failed: {err_text}")
            except ValueError:
                raise
            except Exception:
                continue

        # Confirm login success
        if _is_logged_in(page_text, page):
            logger.info("✅ Login successful!")
            save_session(get_browser_context())
            result["success"] = True
            result["page"] = page
        else:
            screenshot_path = _screenshot(page, "login_unknown_state")
            raise ValueError("Login state unclear — dashboard not detected after submit.")

    except ValueError as ve:
        result["error"] = str(ve)
        result["screenshot"] = screenshot_path
        logger.error(f"Login error: {ve}")
        try:
            page.close()
        except Exception:
            pass

    except PlaywrightTimeout:
        result["error"] = "Connection timeout — MHTCET portal is unreachable."
        result["screenshot"] = _screenshot(page, "login_timeout")
        logger.error("Playwright timeout during login.")
        try:
            page.close()
        except Exception:
            pass

    except Exception as e:
        result["error"] = f"Unexpected error during login: {str(e)}"
        result["screenshot"] = _screenshot(page, "login_exception")
        logger.exception("Unexpected login exception.")
        try:
            page.close()
        except Exception:
            pass

    return result


def _is_logged_in(page_text: str, page: Page) -> bool:
    """Heuristic check: are we on a logged-in dashboard page?"""
    logged_in_signals = [
        "score card", "scorecard", "dashboard", "logout",
        "log out", "candidate", "welcome", "my profile",
        "mht cet", "mhtcet", "download",
    ]
    lower = page_text.lower()
    # Must NOT see login-page indicators
    login_signals = ["sign in", "forgot password", "create account"]
    if any(s in lower for s in login_signals) and not any(s in lower for s in ["logout", "log out"]):
        return False
    return any(s in lower for s in logged_in_signals)
