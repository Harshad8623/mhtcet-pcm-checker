"""
checker/public_monitor.py
Monitors cetcell.mahacet.org every 60 seconds for PCM-related announcements.
No login required — uses plain HTTP requests.
"""
import requests
import hashlib
import json
import re
from pathlib import Path
from datetime import datetime

PUBLIC_URL  = "https://cetcell.mahacet.org/"
STATE_FILE  = Path(__file__).parent.parent / "public_monitor_state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Keywords that indicate a PCM result/notice
# SPECIFIC phrases that prove a PCM notice/result was posted
# Must be UNIQUE to PCM — not present in any other CET result announcement
PCM_KEYWORDS = [
    "result declared for mht-cet (pcm",
    "mht-cet (pcm) result declared",
    "pcm result declared",
    "pcm score card available in candidate",
    "pcm scorecard available in candidate",
    "result summary:mht-cet 2026 (pcm",
    "result summary : mht-cet 2026 (pcm",
    "result summary:mht-cet(pcm",
    "pcm group first attempt result",
    "mht-cet (pcm) 2026 (attempt 1) result",
    "mht-cet (pcm group",
]


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _extract_announcements(html: str) -> list[str]:
    """Extract announcement/ticker/notice text from the page."""
    items = []

    # Ticker items (marquee / announcement bar)
    ticker = re.findall(
        r'<(?:marquee|li|a|span|td)[^>]*>(.*?)</(?:marquee|li|a|span|td)>',
        html, re.IGNORECASE | re.DOTALL
    )
    for t in ticker:
        clean = re.sub(r'<[^>]+>', '', t).strip()
        if clean and len(clean) > 5:
            items.append(clean)

    # Also grab all visible text links
    links = re.findall(r'<a[^>]*>([^<]{10,})</a>', html, re.IGNORECASE)
    items.extend(links)

    # Deduplicate and return lowercase
    seen = set()
    result = []
    for item in items:
        item_lower = item.strip().lower()
        if item_lower and item_lower not in seen:
            seen.add(item_lower)
            result.append(item_lower)
    return result


def check_public_notices() -> dict:
    """
    Fetch cetcell.mahacet.org and check for PCM-related new notices.
    Returns result dict.
    """
    result = {
        "success": False,
        "new_pcm_notice": False,
        "pcm_keywords_found": [],
        "new_notices": [],
        "page_changed": False,
        "error": None,
        "checked_at": datetime.utcnow().isoformat(),
    }

    try:
        resp = requests.get(PUBLIC_URL, timeout=20, headers=HEADERS)
        resp.raise_for_status()
        html      = resp.text
        html_low  = html.lower()
        page_hash = hashlib.md5(html_low.encode()).hexdigest()

        # Load previous state
        state = _load_state()
        prev_hash     = state.get("page_hash", "")
        prev_notices  = set(state.get("known_notices", []))

        result["page_changed"] = (prev_hash != page_hash)

        # Extract current announcements
        current_notices = set(_extract_announcements(html))

        # Find genuinely NEW notices (not seen before)
        new_notices = current_notices - prev_notices
        result["new_notices"] = list(new_notices)[:10]

        # Check ALL page text for PCM keywords
        found_kws = [kw for kw in PCM_KEYWORDS if kw in html_low]
        result["pcm_keywords_found"] = found_kws

        # Only alert if PCM keyword is in a NEW notice OR
        # if PCM keyword appears and wasn't in previous page
        prev_had_pcm = state.get("had_pcm", False)
        current_has_pcm = bool(found_kws)
        result["new_pcm_notice"] = current_has_pcm and not prev_had_pcm

        # Save updated state
        _save_state({
            "page_hash":     page_hash,
            "known_notices": list(current_notices),
            "had_pcm":       current_has_pcm,
            "last_checked":  result["checked_at"],
        })

        result["success"] = True

    except requests.exceptions.RequestException as e:
        result["error"] = f"HTTP error: {str(e)}"
    except Exception as e:
        result["error"] = f"Unexpected error: {str(e)}"

    return result
