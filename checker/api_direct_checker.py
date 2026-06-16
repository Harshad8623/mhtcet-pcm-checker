"""
checker/api_direct_checker.py

Direct API checker for portal-2026.maharashtracet.org/api/scorecards
Uses saved session cookies (from Playwright login) to query the API
without launching a browser — fastest + most accurate method.

URL discovered: portal-2026.maharashtracet.org/api/scorecards
  - Returns white page without auth (confirmed by user)
  - Returns JSON scorecard list with auth (our target)
"""

import requests
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

SESSION_FILE   = Path(__file__).parent.parent / "session_state.json"
PORTAL_ORIGIN  = "https://portal-2026.maharashtracet.org"

# Known API endpoints to try (from network interception discovery)
SCORECARD_APIS = [
    f"{PORTAL_ORIGIN}/api/scorecards",
    f"{PORTAL_ORIGIN}/api/scorecard",
    f"{PORTAL_ORIGIN}/api/score-cards",
    f"{PORTAL_ORIGIN}/api/results",
    f"{PORTAL_ORIGIN}/api/result",
    f"{PORTAL_ORIGIN}/api/candidate/scorecards",
    f"{PORTAL_ORIGIN}/api/candidate/scorecard",
    f"{PORTAL_ORIGIN}/api/v1/scorecards",
    f"{PORTAL_ORIGIN}/api/v1/scorecard",
]

# PCM Attempt 2 specific phrases in JSON response
# CRITICAL: Generic phrases like 'mht-cet (pcm', 'pcm group' match
# Attempt 1 data which is already in the API. Only keep Attempt 2
# specific strings that cannot appear until Attempt 2 is released.
PCM_JSON_PHRASES = [
    "mht-cet (pcm) 2026 (attempt 2)",
    "mht-cet (pcm) attempt 2",
    "pcm attempt 2",
    "pcm group attempt 2",
    "pcm second attempt",
    # Note: removed bare "attempt 2" — too broad, matches any config/metadata JSON
]

# Phrases that confirm it's a scorecard/result (not a config value)
# For Attempt 2 we REQUIRE 'attempt 2' or 'second' to be present
SCORECARD_CONFIRM = [
    "scorecard", "score_card", "score-card",
    "result", "download", "available",
]

# Extra guard: response must also contain '2' or 'second' to rule out Attempt 1
ATTEMPT2_CONFIRM = ["attempt 2", "attempt_2", "attempt-2", "second attempt", "2nd attempt"]

# BUG FIX #2: Track session expiry separately so we don't loop through
# all 9 URLs when the first 401 already tells us the session is dead.
SESSION_EXPIRED_CODES = {401, 403}


def _load_cookies() -> dict:
    """
    Load cookies from Playwright's saved session state (JSON format).
    Playwright saves: {"cookies": [{"name":..., "value":..., "domain":...}]}
    """
    if not SESSION_FILE.exists():
        return {}
    try:
        # BUG FIX #3: Must specify encoding='utf-8' — session file may contain
        # Unicode chars (Thai, Devanagari) that fail with default cp1252 on Windows.
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        cookies = {}
        for c in data.get("cookies", []):
            domain = c.get("domain", "")
            if "maharashtracet" in domain or "mhexam" in domain:
                cookies[c["name"]] = c["value"]
        return cookies
    except Exception as e:
        logger.warning(f"[API-DIRECT] Could not load session cookies: {e}")
        return {}


def _load_discovered_apis() -> list:
    """Load any API endpoints discovered by Playwright network interception."""
    discovery_file = Path(__file__).parent.parent / "discovered_api_endpoints.json"
    if not discovery_file.exists():
        return []
    try:
        endpoints = json.loads(discovery_file.read_text(encoding="utf-8"))
        return [e["url"] for e in endpoints if isinstance(e, dict) and "url" in e]
    except Exception:
        return []


def check_api_direct() -> dict:
    """
    Query the portal's scorecard API directly using saved session cookies.

    Returns:
      {
        "success": bool,
        "pcm_found": bool,
        "authenticated": bool,    # True if session cookies worked
        "session_expired": bool,  # True if got 401/403
        "endpoint_hit": str|None, # which URL returned data
        "raw_snippet": str,       # first 300 chars of response
        "error": str|None,
        "checked_at": str,
      }
    """
    result = {
        "success":         False,
        "pcm_found":       False,
        "authenticated":   False,
        "session_expired": False,
        "endpoint_hit":    None,
        "raw_snippet":     "",
        "error":           None,
        "checked_at":      datetime.utcnow().isoformat(),
    }

    cookies = _load_cookies()
    if not cookies:
        result["error"] = "No session cookies found — Playwright login needed first"
        logger.debug("[API-DIRECT] No session cookies. Run Playwright check first.")
        return result

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{PORTAL_ORIGIN}/",
        "Origin": PORTAL_ORIGIN,
    }

    # Combine known + discovered URLs (discovered ones first — higher priority)
    discovered = _load_discovered_apis()
    all_urls = discovered + [u for u in SCORECARD_APIS if u not in discovered]

    for url in all_urls:
        try:
            resp = requests.get(
                url, headers=headers, cookies=cookies,
                timeout=8, allow_redirects=True
            )

            # BUG FIX #4: Stop looping on 401/403 — session is expired for ALL urls.
            # No point trying the other 8 endpoints with a dead session.
            if resp.status_code in SESSION_EXPIRED_CODES:
                result["session_expired"] = True
                result["error"] = f"Session expired (HTTP {resp.status_code}) — needs fresh Playwright login"
                logger.info(f"[API-DIRECT] Session expired ({resp.status_code}). Will refresh on next Playwright run.")
                return result

            if resp.status_code == 404:
                logger.debug(f"[API-DIRECT] {url} → 404")
                continue

            # BUG FIX #5: Also skip non-200 codes (500, 502, etc.) — don't
            # treat server errors as "authenticated but empty".
            if resp.status_code >= 400:
                logger.debug(f"[API-DIRECT] {url} → {resp.status_code} (skipping)")
                continue

            body_raw = resp.text.strip()

            # BUG FIX #6: Check for HTML response — the white page IS HTML,
            # not JSON. If the response looks like HTML, skip it (not authenticated).
            if body_raw.startswith("<!") or body_raw.lower().startswith("<html"):
                logger.debug(f"[API-DIRECT] {url} → HTML response (not authenticated)")
                continue

            if not body_raw or body_raw in ("{}", "[]", "null"):
                logger.debug(f"[API-DIRECT] {url} → empty body")
                continue

            result["authenticated"] = True
            result["endpoint_hit"]  = url
            result["raw_snippet"]   = body_raw[:300]

            body_low = body_raw.lower()

            # Check for PCM Attempt 2 in JSON response
            # ALL THREE must be true to avoid false-alerting on Attempt 1 data
            has_pcm       = any(p in body_low for p in PCM_JSON_PHRASES)
            has_sc_ctx    = any(w in body_low for w in SCORECARD_CONFIRM)
            has_attempt2  = any(a in body_low for a in ATTEMPT2_CONFIRM)

            if has_pcm and has_sc_ctx and has_attempt2:
                result["pcm_found"] = True
                logger.warning(
                    f"[API-DIRECT] *** PCM ATTEMPT 2 FOUND in API response! "
                    f"URL: {url} | Snippet: {body_raw[:100]} ***"
                )
            else:
                logger.info(
                    f"[API-DIRECT] {url} → {resp.status_code} | "
                    f"PCM: {has_pcm} | SC: {has_sc_ctx} | A2: {has_attempt2} | "
                    f"Snippet: {body_raw[:80]}"
                )

            result["success"] = True
            break  # Found a working endpoint — no need to try others

        except requests.Timeout:
            logger.debug(f"[API-DIRECT] {url} → timeout")
        except Exception as e:
            logger.debug(f"[API-DIRECT] {url} → error: {e}")

    if not result["success"] and not result["error"]:
        result["error"] = "No API endpoint returned usable JSON data (session may need refresh)"

    return result
