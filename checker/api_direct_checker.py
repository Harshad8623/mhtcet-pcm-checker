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

# PCM-specific phrases in JSON response
PCM_JSON_PHRASES = [
    "mht-cet (pcm",
    "mht-cet(pcm",
    "pcm group",
    "mhtcet_pcm",
    "pcm_group",
    "pcm-group",
    '"pcm"',
]

# Phrases that confirm it's a scorecard/result (not a config value)
SCORECARD_CONFIRM = [
    "scorecard", "score_card", "score-card",
    "result", "attempt", "download", "available",
]


def _load_cookies() -> dict:
    """
    Load cookies from Playwright's saved session state (JSON format).
    Playwright saves: {"cookies": [{"name":..., "value":..., "domain":...}]}
    """
    if not SESSION_FILE.exists():
        return {}
    try:
        data = json.loads(SESSION_FILE.read_text())
        cookies = {}
        for c in data.get("cookies", []):
            domain = c.get("domain", "")
            if "maharashtracet" in domain or "mhexam" in domain:
                cookies[c["name"]] = c["value"]
        return cookies
    except Exception as e:
        logger.warning(f"[API-DIRECT] Could not load session cookies: {e}")
        return {}


def _load_discovered_apis() -> list[str]:
    """Load any API endpoints discovered by Playwright network interception."""
    discovery_file = Path(__file__).parent.parent / "discovered_api_endpoints.json"
    if not discovery_file.exists():
        return []
    try:
        endpoints = json.loads(discovery_file.read_text())
        return [e["url"] for e in endpoints]
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
        "endpoint_hit": str|None, # which URL returned data
        "raw_snippet": str,       # first 200 chars of response
        "error": str|None,
        "checked_at": str,
      }
    """
    result = {
        "success":      False,
        "pcm_found":    False,
        "authenticated": False,
        "endpoint_hit": None,
        "raw_snippet":  "",
        "error":        None,
        "checked_at":   datetime.utcnow().isoformat(),
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

            if resp.status_code == 401 or resp.status_code == 403:
                # Session expired — need fresh Playwright login
                logger.debug(f"[API-DIRECT] {url} → {resp.status_code} (session expired)")
                continue

            if resp.status_code == 404:
                logger.debug(f"[API-DIRECT] {url} → 404")
                continue

            # Got a response — check if it's JSON with data
            ct = resp.headers.get("content-type", "")
            body_raw = resp.text.strip()

            if not body_raw or body_raw in ("{}", "[]", "null"):
                logger.debug(f"[API-DIRECT] {url} → empty body")
                continue

            result["authenticated"] = True
            result["endpoint_hit"]  = url
            result["raw_snippet"]   = body_raw[:300]

            body_low = body_raw.lower()

            # Check for PCM phrases in JSON response
            has_pcm = any(p in body_low for p in PCM_JSON_PHRASES)
            has_scorecard_ctx = any(w in body_low for w in SCORECARD_CONFIRM)

            if has_pcm and has_scorecard_ctx:
                result["pcm_found"] = True
                logger.warning(
                    f"[API-DIRECT] *** PCM FOUND in API response! "
                    f"URL: {url} | Snippet: {body_raw[:100]} ***"
                )
            else:
                logger.info(
                    f"[API-DIRECT] {url} → {resp.status_code} | "
                    f"PCM: {has_pcm} | SC-ctx: {has_scorecard_ctx} | "
                    f"Snippet: {body_raw[:80]}"
                )

            result["success"] = True
            break  # Found a working endpoint — no need to try others

        except requests.Timeout:
            logger.debug(f"[API-DIRECT] {url} → timeout")
        except Exception as e:
            logger.debug(f"[API-DIRECT] {url} → error: {e}")

    if not result["success"] and not result["error"]:
        result["error"] = "No API endpoint returned usable data (session may need refresh)"

    return result
