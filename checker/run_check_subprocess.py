"""
checker/run_check_subprocess.py
Runs a single login+scorecard check in a standalone subprocess.
Returns JSON result to stdout. Called by app.py via subprocess.run().
"""

import sys
import os
import json
import time
from pathlib import Path

# ── Load .env ──────────────────────────────────────────────────────────────────
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

EMAIL     = os.getenv("MHTCET_EMAIL", "")
PASSWORD  = os.getenv("MHTCET_PASSWORD", "")
LOGIN_URL = os.getenv("LOGIN_URL", "https://portal-2026.maharashtracet.org")

# The confirmed MHT-CET 2026 candidate portal (React SPA)
PORTAL_URL = "https://portal-2026.maharashtracet.org/"

SCREENSHOTS_DIR = Path(__file__).parent.parent / "screenshots"
SESSION_FILE    = Path(__file__).parent.parent / "session_state.json"

# PCM scorecard keywords — ONLY match when PCM text is explicitly present
# DO NOT include 'get score card' alone — PCB also has that button!
PCM_KEYWORDS = [
    "mht-cet (pcm)",       # exact card label when PCM is released
    "mht cet (pcm)",
    "mhtcet (pcm)",
    "PCM"
    "MHT-CET (PCM) 2026"
    "MHT-CET (PCM) 2026 (Attempt 1)"
    "pcm scorecard",
    "pcm score card",
    "pcm group",
    "pcm result",
    "(pcm) 2026",
    "pcm attempt",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def save_screenshot(page, name: str) -> str:
    SCREENSHOTS_DIR.mkdir(exist_ok=True)
    from datetime import datetime
    ts   = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = str(SCREENSHOTS_DIR / f"{name}_{ts}.png")
    try:
        page.screenshot(path=path, full_page=True)
    except Exception:
        path = None
    return path


def wait_for_react(page, timeout=15000):
    """Wait for React SPA to fully render."""
    try:
        page.wait_for_selector("input, button, form, [class]", timeout=timeout)
    except Exception:
        pass
    time.sleep(2)


def find_input(page, selectors, timeout=5000):
    """Return first visible matching element."""
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                return el
        except Exception:
            continue
    return None


# ── Main Check ─────────────────────────────────────────────────────────────────

def run():
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

    result = {
        "success": False,
        "login_status": "error",
        "pcm_found": False,
        "error": None,
        "screenshot": None,
        "portal_changed": False,
        "page_title": "",
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        ctx_args = dict(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
        )
        if SESSION_FILE.exists():
            ctx_args["storage_state"] = str(SESSION_FILE)
            print("[INFO] Loaded saved session.", file=sys.stderr)

        context = browser.new_context(**ctx_args)
        context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = context.new_page()

        try:
            # ── STEP 1: Load portal ──────────────────────────────────────────
            print(f"[STEP1] Loading: {PORTAL_URL}", file=sys.stderr)
            try:
                page.goto(PORTAL_URL, timeout=35000, wait_until="domcontentloaded")
            except PwTimeout:
                result["error"] = "Portal timed out — check internet connection."
                result["screenshot"] = save_screenshot(page, "timeout")
                print(json.dumps(result))
                return

            # Wait for React hydration
            print("[STEP1] Waiting for React...", file=sys.stderr)
            wait_for_react(page, timeout=15000)
            result["page_title"] = page.title()
            save_screenshot(page, "step1_portal_loaded")
            print(f"[STEP1] Title: {result['page_title']}", file=sys.stderr)

            body = page.inner_text("body").lower()
            print(f"[STEP1] Page text (150): {body[:150]}", file=sys.stderr)

            # ── Session error detection — auto-clear bad sessions ────────────
            session_error = (
                "something went wrong" in body or
                "please try login again" in body or
                "session expired" in body or
                "try again" in body and "sign in" not in body and "registered email" not in body
            )
            if session_error and SESSION_FILE.exists():
                print("[STEP1] Bad/expired session detected — clearing and retrying...", file=sys.stderr)
                SESSION_FILE.unlink()
                # Reload the page fresh (no session cookies)
                try:
                    page.goto(PORTAL_URL, timeout=35000, wait_until="domcontentloaded")
                    wait_for_react(page, timeout=15000)
                    body = page.inner_text("body").lower()
                    print(f"[STEP1] After session clear (150): {body[:150]}", file=sys.stderr)
                except Exception:
                    pass

            # ── STEP 2: Check if already logged in ──────────────────────────
            # Only true if the sign-in form is NOT visible and dashboard IS visible
            sign_in_visible = "sign in" in body and ("registered email" in body or "password" in body)
            already_logged_in = (
                not sign_in_visible and not session_error and (
                    "hi, user" in body or
                    "logout" in body or "log out" in body or
                    ("score card" in body) or
                    ("scorecard" in body) or
                    ("dashboard" in body)
                )
            )

            if already_logged_in:
                print("[STEP2] Session reuse — already logged in.", file=sys.stderr)
                result["login_status"] = "success"
                # Wait for dashboard cards to fully render (React may still be loading)
                print("[STEP2] Waiting for dashboard to fully render...", file=sys.stderr)
                try:
                    page.wait_for_selector("text=Score Card", timeout=10000)
                    print("[STEP2] Dashboard fully loaded.", file=sys.stderr)
                except Exception:
                    # Dashboard didn't show Score Card — take screenshot for debug
                    save_screenshot(page, "step2_partial_dashboard")
                    # Give it a bit more time
                    time.sleep(3)
                    print("[STEP2] Dashboard wait timed out — proceeding anyway.", file=sys.stderr)

            else:
                # ── STEP 3: Find and fill login form ────────────────────────
                print("[STEP3] Looking for login form...", file=sys.stderr)

                pwd_selectors = [
                    "input[type='password']",
                    "input[name='password']",
                    "input[id*='password' i]",
                    "input[placeholder*='Password' i]",
                ]
                id_selectors = [
                    "input[type='email']",
                    "input[type='text']",
                    "input[name='email']",
                    "input[name='username']",
                    "input[name='applicationId']",
                    "input[name='application_id']",
                    "input[id*='email' i]",
                    "input[id*='user' i]",
                    "input[id*='application' i]",
                    "input[placeholder*='Email' i]",
                    "input[placeholder*='Application' i]",
                    "input[placeholder*='User' i]",
                    "input[placeholder*='ID' i]",
                    "input[placeholder*='Enter' i]",
                ]

                # Try clicking a "Candidate Login" or "Login" link if form not visible
                pwd_el = find_input(page, pwd_selectors, timeout=4000)
                if not pwd_el:
                    print("[STEP3] No password field — trying login button...", file=sys.stderr)
                    for text in ["Candidate Login", "Login", "Sign In"]:
                        try:
                            btn = page.get_by_text(text, exact=False).first
                            if btn and btn.is_visible():
                                print(f"[STEP3] Clicking '{text}'...", file=sys.stderr)
                                btn.click()
                                wait_for_react(page, timeout=10000)
                                save_screenshot(page, "step3_after_btn_click")
                                break
                        except Exception:
                            continue
                    pwd_el = find_input(page, pwd_selectors, timeout=6000)

                # Still no form? Save debug HTML
                if not pwd_el:
                    save_screenshot(page, "no_login_form_found")
                    try:
                        html = page.content()
                        debug_path = SCREENSHOTS_DIR / "debug_page.html"
                        SCREENSHOTS_DIR.mkdir(exist_ok=True)
                        debug_path.write_text(html, encoding="utf-8")
                        print(f"[DEBUG] HTML saved: {debug_path}", file=sys.stderr)
                    except Exception:
                        pass
                    raise ValueError(
                        "Login form not found on portal. "
                        "See screenshots/step1_portal_loaded_*.png and "
                        "screenshots/debug_page.html to debug."
                    )

                id_el = find_input(page, id_selectors, timeout=4000)
                if not id_el:
                    save_screenshot(page, "no_id_field")
                    raise ValueError(
                        "Application ID / Email field not found. "
                        "Password field was found but not the ID field."
                    )

                # Fill credentials
                print(f"[STEP3] Filling ID={EMAIL[:4]}*** and password...", file=sys.stderr)
                id_el.click()
                id_el.fill(EMAIL)
                time.sleep(0.4)

                pwd_el.click()
                pwd_el.fill(PASSWORD)
                time.sleep(0.4)

                save_screenshot(page, "step3_form_filled")

                # Submit
                submit_selectors = [
                    "button[type='submit']",
                    "input[type='submit']",
                    "button:has-text('Login')",
                    "button:has-text('Sign In')",
                    "button:has-text('Submit')",
                    "button:has-text('Log In')",
                ]
                submit_el = find_input(page, submit_selectors, timeout=5000)
                if not submit_el:
                    save_screenshot(page, "no_submit_btn")
                    raise ValueError("Submit/Login button not found on form.")

                print("[STEP3] Submitting...", file=sys.stderr)
                submit_el.click()
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
                except PwTimeout:
                    pass
                wait_for_react(page, timeout=10000)
                save_screenshot(page, "step3_after_submit")
                result["page_title"] = page.title()

                body = page.inner_text("body").lower()
                print(f"[STEP3] Post-login text (200): {body[:200]}", file=sys.stderr)

                # Check for inline error messages
                for err_sel in [".alert-danger", ".error-message", "[class*='error']",
                                 ".alert", "p[class*='err']", "[class*='Error']"]:
                    try:
                        el = page.query_selector(err_sel)
                        if el and el.is_visible():
                            txt = el.inner_text().strip()
                            if txt and any(w in txt.lower() for w in
                                           ["invalid", "incorrect", "wrong", "failed",
                                            "not found", "doesn't match"]):
                                save_screenshot(page, "login_rejected")
                                raise ValueError(
                                    f"Portal rejected login: {txt[:150]}\n"
                                    f"Check Application ID '{EMAIL}' and password in .env"
                                )
                    except ValueError:
                        raise
                    except Exception:
                        pass

                # Confirm login success — sign in form must be GONE
                sign_in_gone = "sign in" not in body or ("registered email" not in body and "password" not in body)
                logged_in = sign_in_gone and (
                    "hi, user" in body or
                    "logout" in body or "log out" in body or
                    "score card" in body or
                    "scorecard" in body or
                    "dashboard" in body or
                    "welcome" in body or
                    # portal shows office address + copyright ONLY on the dashboard, not login
                    ("office address" in body and "registered email" not in body) or
                    # any text after successful login that's not on the login page
                    ("candidate" in body and "registered email" not in body)
                )

                if logged_in:
                    result["login_status"] = "success"
                    print("[STEP3] *** LOGIN SUCCESS! ***", file=sys.stderr)
                    try:
                        context.storage_state(path=str(SESSION_FILE))
                        print("[STEP3] Session saved for reuse.", file=sys.stderr)
                    except Exception:
                        pass
                else:
                    save_screenshot(page, "login_unknown_state")
                    raise ValueError(
                        "Login form submitted but dashboard not detected. "
                        f"Application ID used: '{EMAIL}' — verify this is correct. "
                        "See screenshots/step3_after_submit_*.png"
                    )

            # ── STEP 4: Open Score Card section & check for PCM ─────────────
            print("[STEP4] Looking for Score Card / Get Score Card link...", file=sys.stderr)

            # Try multiple selectors — prioritise the 'Get Score Card' arrow link
            # visible in the dashboard card, then fall back to 'Score Card' heading
            scorecard_btn = None
            for sel in [
                "a:has-text('Get Score Card')",   # the blue arrow link in the card
                "text=Get Score Card",
                "a:has-text('Score Card')",
                "button:has-text('Score Card')",
            ]:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        scorecard_btn = el
                        print(f"[STEP4] Found with selector: {sel}", file=sys.stderr)
                        break
                except Exception:
                    continue

            if scorecard_btn:
                print("[STEP4] Clicking via JS to open popup...", file=sys.stderr)
                try:
                    page.evaluate("(el) => el.click()", scorecard_btn)
                    # Wait for modal content — 'Technical Education' only appears in popup
                    try:
                        page.wait_for_selector(
                            "text=Technical Education",
                            timeout=8000, state="visible"
                        )
                        print("[STEP4] Popup opened — 'Technical Education' visible.", file=sys.stderr)
                    except Exception:
                        time.sleep(3)
                        print("[STEP4] Popup wait timed out — reading page as-is.", file=sys.stderr)
                except Exception as e:
                    time.sleep(3)
                    print(f"[STEP4] Click error (continuing): {e}", file=sys.stderr)
            else:
                print("[STEP4] Score Card button not found — reading dashboard body.", file=sys.stderr)


            # Read page/modal content safely
            try:
                body_text  = page.inner_text("body", timeout=8000)
            except Exception:
                body_text = ""
            body_lower = body_text.lower()
            print(f"[STEP4] Score card popup text (300): {body_lower[:300]}", file=sys.stderr)
            save_screenshot(page, "step4_scorecard_popup")


            # ── PCM detection: ONLY flag if PCM text explicitly present ──────
            # PCB also has 'get score card' so we MUST check for PCM specifically
            pcm_found = any(kw in body_lower for kw in PCM_KEYWORDS)

            # Extra check: scan all visible text elements for PCM scorecard cards
            if not pcm_found:
                for sel in ["div", "li", "p", "span", "td", "h3", "h4"]:
                    try:
                        els = page.query_selector_all(sel)
                        for el in els[:50]:
                            try:
                                txt = el.inner_text().strip().lower()
                                # Must have 'pcm' AND something score-related
                                # and must NOT be a PCB-only element
                                if ("pcm" in txt and
                                    any(w in txt for w in ["score", "result", "attempt"]) and
                                    "pcb" not in txt):  # ignore PCB elements
                                    pcm_found = True
                                    print(f"[STEP4] PCM element: '{txt[:80]}'",
                                          file=sys.stderr)
                                    break
                            except Exception:
                                continue
                        if pcm_found:
                            break
                    except Exception:
                        continue

            if pcm_found:
                result["pcm_found"] = True
                result["screenshot"] = save_screenshot(page, "PCM_SCORECARD_AVAILABLE")
                print("[ALERT] *** PCM SCORECARD IS AVAILABLE! ***", file=sys.stderr)
            else:
                result["screenshot"] = save_screenshot(page, "step4_no_pcm_yet")
                print("[STEP4] PCM not available yet (only PCB shown). Waiting...",
                      file=sys.stderr)

            result["success"] = True

        except ValueError as ve:
            result["error"] = str(ve)
            result["login_status"] = (
                "failed" if any(w in str(ve).lower() for w in
                                ["login", "credential", "application id",
                                 "rejected", "invalid"])
                else "error"
            )

        except PwTimeout:
            result["error"] = "Connection timeout - portal unreachable."
            result["login_status"] = "error"
            try:
                result["screenshot"] = save_screenshot(page, "timeout")
            except Exception:
                pass

        except Exception as e:
            result["error"] = f"Unexpected error: {str(e)}"
            result["login_status"] = "error"
            try:
                result["screenshot"] = save_screenshot(page, "exception")
            except Exception:
                pass

        finally:
            try:
                browser.close()
            except Exception:
                pass

    print(json.dumps(result))


if __name__ == "__main__":
    run()
