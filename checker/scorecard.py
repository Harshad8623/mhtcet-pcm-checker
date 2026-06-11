"""
checker/scorecard.py — PCM scorecard detection logic.
"""

import os
import logging
import time
from datetime import datetime
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger("mhtcet.scorecard")

SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "..", "screenshots")

# Keywords that indicate PCM scorecard is present on the page
PCM_KEYWORDS = [
    "mht-cet (pcm)",
    "mht cet (pcm)",
    "mhtcet (pcm)",
    "pcm scorecard",
    "pcm score card",
    "get score card",
    "download score card",
    "download scorecard",
]

# Selectors to navigate to the scorecard section
SCORECARD_SELECTORS = [
    "a:has-text('Score Card')",
    "a:has-text('Scorecard')",
    "button:has-text('Score Card')",
    "a[href*='scorecard']",
    "a[href*='score-card']",
    "li:has-text('Score Card') a",
]


def _screenshot(page: Page, name: str) -> str:
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(SCREENSHOTS_DIR, f"{name}_{ts}.png")
    try:
        page.screenshot(path=path, full_page=True)
        logger.info(f"Screenshot: {path}")
    except Exception:
        path = None
    return path


def check_pcm_scorecard(page: Page) -> dict:
    """
    Navigate to the scorecard section and check if PCM scorecard is available.

    Returns:
        {
            "found": bool,
            "page_text": str,
            "screenshot": str | None,
            "error": str | None,
            "portal_changed": bool
        }
    """
    result = {
        "found": False,
        "page_text": "",
        "screenshot": None,
        "error": None,
        "portal_changed": False
    }

    try:
        # Try to navigate to scorecard section
        scorecard_link = None
        for sel in SCORECARD_SELECTORS:
            try:
                el = page.query_selector(sel)
                if el:
                    scorecard_link = el
                    break
            except Exception:
                continue

        if scorecard_link:
            logger.info("Found scorecard nav link, clicking...")
            scorecard_link.click()
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except PlaywrightTimeout:
                pass
            time.sleep(2)
        else:
            logger.info("No scorecard nav link found — checking current page content...")

        page_text = page.inner_text("body")
        result["page_text"] = page_text
        page_lower = page_text.lower()

        logger.info(f"Scanning page for PCM keywords...")
        logger.debug(f"Page snippet: {page_text[:500]}")

        # Primary check: look for PCM-specific keywords
        pcm_match = any(kw in page_lower for kw in PCM_KEYWORDS)

        # Secondary check: look for PCM + scorecard combo anywhere on page
        has_pcm = "pcm" in page_lower
        has_scorecard = any(w in page_lower for w in ["score card", "scorecard", "get score"])
        combo_match = has_pcm and has_scorecard

        if pcm_match or combo_match:
            logger.info("🎯 PCM Scorecard DETECTED on the page!")
            result["found"] = True
            result["screenshot"] = _screenshot(page, "pcm_found")
        else:
            logger.info("PCM Scorecard not yet available.")

            # Check if portal has changed (no expected elements at all)
            if not any(w in page_lower for w in ["mht", "cet", "scorecard", "score", "candidate", "result"]):
                logger.warning("⚠️ Portal may have changed — expected content not found.")
                result["portal_changed"] = True
                result["screenshot"] = _screenshot(page, "portal_changed")
                result["error"] = "Portal UI changed — expected content not found on page."

    except PlaywrightTimeout:
        result["error"] = "Timeout while checking scorecard page."
        result["screenshot"] = _screenshot(page, "scorecard_timeout")
        logger.error("Timeout in scorecard check.")

    except Exception as e:
        result["error"] = f"Scorecard check failed: {str(e)}"
        result["screenshot"] = _screenshot(page, "scorecard_exception")
        logger.exception("Exception in scorecard check.")

    finally:
        try:
            page.close()
        except Exception:
            pass

    return result
