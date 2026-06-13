"""
checker/change_detector.py  (v2 — smart API monitoring)

Monitors 3 real signals to detect PCM result upload BEFORE the portal
shows it visually:

1. cetcell.mahacet.org public result pages  — checks if PCM result page exists
2. scorecard.mhexam.com  — tries PCM endpoint patterns (like the PCB one)
3. Portal API / JS bundle hash  — detects backend deployments

Based on observed infrastructure:
  - PCB scorecard: scorecard.mhexam.com/MAH-PCB-<token>/
  - PCB PDF:       mhcet25.s3.ap-south-1.amazonaws.com/scorecard/...
  - PCM scorecard: scorecard.mhexam.com/MAH-PCM-<token>/  ← target
"""

import requests
import hashlib
import json
import re
from pathlib import Path
from datetime import datetime

STATE_FILE = Path(__file__).parent.parent / "portal_change_state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json,*/*",
}

# ── Targets to monitor ────────────────────────────────────────────────────────

# 1. CET Cell public result/download pages (no login)
CETCELL_RESULT_URLS = [
    "https://cetcell.mahacet.org/mht-cet-result/",
    "https://cetcell.mahacet.org/mht-cet-2026-result/",
    "https://cetcell.mahacet.org/result/",
    "https://cetcell.mahacet.org/wp-json/wp/v2/posts?per_page=5&_fields=title,link,date",
]

# SPECIFIC phrases that indicate a PCM RESULT DECLARATION
# NOT generic mentions of "pcm" as a course name
PCM_RESULT_DECLARED_PHRASES = [
    "result declared for mht-cet (pcm",
    "result declared for mht-cet(pcm",
    "mht-cet (pcm) result declared",
    "mht-cet(pcm) result declared",
    "pcm result declared",
    "pcm score card available",
    "pcm scorecard available",
    "score card available in candidate",   # + context "pcm" nearby
    "pcm group first attempt result",
    "pcm group second attempt result",
    "result summary:mht-cet 2026 (pcm",
    "result summary : mht-cet 2026 (pcm",
    "result summary:mht-cet(pcm",
    "pcm 2026 result",
    "mht-cet 2026 pcm result",
]

# 2. scorecard.mhexam.com endpoint patterns for PCM
# We must GET (not HEAD) and verify the response contains scorecard content
MHEXAM_PCM_PATTERNS = [
    "https://scorecard.mhexam.com/MAH-PCM/",
    "https://scorecard.mhexam.com/MAH-PCM-2026/",
    "https://scorecard.mhexam.com/pcm/",
]

# Content that proves a scorecard endpoint is real (not a generic 200)
MHEXAM_REAL_CONTENT = [
    "scorecard", "score card", "mht-cet", "mhcet",
    "s3.amazonaws.com", "download", "pdf",
]

# 3. Portal JS bundle — changes when backend deploys new frontend
PORTAL_JS_URL = "https://portal-2026.maharashtracet.org/"



def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _safe_get(url: str, timeout: int = 10) -> requests.Response | None:
    try:
        return requests.get(url, headers=HEADERS, timeout=timeout,
                           allow_redirects=True)
    except Exception:
        return None


def _safe_head(url: str, timeout: int = 8) -> requests.Response | None:
    try:
        return requests.head(url, headers=HEADERS, timeout=timeout,
                            allow_redirects=True)
    except Exception:
        return None


# ── Check 1: cetcell.mahacet.org result/API pages ────────────────────────────

def _check_cetcell_result_pages(state: dict) -> dict:
    """Check CET Cell website for SPECIFIC PCM result declaration phrases."""
    result = {
        "pcm_found": False,
        "new_pcm_content": False,
        "details": [],
        "changed_urls": [],
    }
    prev_hashes = state.get("cetcell_hashes", {})
    new_hashes  = {}

    for url in CETCELL_RESULT_URLS:
        resp = _safe_get(url)
        if not resp:
            continue

        text     = resp.text.lower()
        content  = resp.content
        cur_hash = hashlib.md5(content).hexdigest()
        new_hashes[url] = cur_hash

        # Only match SPECIFIC result-declaration phrases — not generic 'pcm'
        found_phrases = [p for p in PCM_RESULT_DECLARED_PHRASES if p in text]
        if found_phrases:
            result["pcm_found"] = True
            result["details"].append({
                "url": url,
                "phrases": found_phrases,
                "status": resp.status_code,
            })

        # Check if page changed since last run
        if url in prev_hashes and prev_hashes[url] != cur_hash:
            result["changed_urls"].append(url)
            result["new_pcm_content"] = result["new_pcm_content"] or bool(found_phrases)

    state["cetcell_hashes"] = new_hashes
    return result


# ── Check 2: scorecard.mhexam.com PCM endpoint ───────────────────────────────

def _check_mhexam_pcm(state: dict) -> dict:
    """
    Try PCM scorecard endpoint patterns on mhexam.com.
    MUST verify real scorecard content in response body — not just HTTP 200.
    """
    result = {
        "pcm_endpoint_live": False,
        "live_url": None,
        "details": [],
    }
    prev_status = state.get("mhexam_pcm_status", {})
    new_status  = {}

    for url in MHEXAM_PCM_PATTERNS:
        resp = _safe_get(url, timeout=10)  # GET, not HEAD
        if not resp:
            new_status[url] = "error"
            continue

        status = resp.status_code
        body   = resp.text.lower()
        new_status[url] = status

        # Verify real scorecard content in body (prevents generic 200 false positives)
        has_real_content = any(kw in body for kw in MHEXAM_REAL_CONTENT)

        # Check if redirected to S3 (definitive proof)
        redirected_to_s3 = (
            "s3.amazonaws.com" in resp.url or
            "s3.ap-south-1" in resp.url or
            any("s3" in str(r.url) for r in resp.history)
        )

        if (status in (200, 301, 302, 307, 308)) and (has_real_content or redirected_to_s3):
            result["pcm_endpoint_live"] = True
            result["live_url"] = url
            result["details"].append({
                "url": url,
                "status": status,
                "redirected_to": resp.url,
                "has_real_content": has_real_content,
            })

        # Only flag as changed if it WAS 404 and now has real content
        prev = prev_status.get(url)
        if prev == 404 and status != 404 and has_real_content:
            result["pcm_endpoint_live"] = True
            result["live_url"] = url

    state["mhexam_pcm_status"] = new_status
    return result


# ── Check 3: Portal JS bundle hash (deploy detection) ────────────────────────

def _check_portal_bundle(state: dict) -> dict:
    """
    Fetch the portal index.html and extract JS bundle filename hashes.
    React apps use content-hashed filenames (e.g., main.abc123.js).
    If the hash in the filename changes → new deploy → possible result upload.
    """
    result = {
        "bundle_changed": False,
        "prev_bundle": state.get("bundle_hash", ""),
        "new_bundle": "",
        "size_delta": 0,
    }

    resp = _safe_get(PORTAL_JS_URL, timeout=15)
    if not resp:
        return result

    html = resp.text

    # Extract JS bundle filenames with their content hashes
    # React build output: /static/js/main.abc123def.chunk.js
    bundle_refs = re.findall(
        r'(static/(?:js|css)/\w+\.[a-f0-9]{8,}\.\w+)',
        html
    )
    bundle_signature = "|".join(sorted(set(bundle_refs)))
    bundle_hash = hashlib.md5(bundle_signature.encode()).hexdigest() if bundle_refs else ""

    # Page size tracking
    cur_size  = len(resp.content)
    prev_size = state.get("portal_size", 0)
    size_delta = abs(cur_size - prev_size)
    state["portal_size"] = cur_size

    prev_bundle = state.get("bundle_hash", "")
    if prev_bundle and prev_bundle != bundle_hash:
        result["bundle_changed"] = True

    result["new_bundle"]  = bundle_hash
    result["size_delta"]  = size_delta
    state["bundle_hash"]  = bundle_hash

    return result


# ── Main entry point ──────────────────────────────────────────────────────────

def check_portal_changes() -> dict:
    """
    Run all 3 change detection checks.
    Returns aggregated result dict.
    """
    result = {
        "success": False,
        "changed": False,
        "significant_change": False,
        "pcm_found_anywhere": False,
        "size_delta": 0,
        "etag_changed": False,
        "last_modified_changed": False,
        "change_summary": "",
        "checked_at": datetime.utcnow().isoformat(),
        "details": {},
        "error": None,
    }

    try:
        state = _load_state()

        # ── Run all 3 checks ─────────────────────────────────────────────────
        cetcell = _check_cetcell_result_pages(state)
        mhexam  = _check_mhexam_pcm(state)
        bundle  = _check_portal_bundle(state)

        result["details"] = {
            "cetcell": cetcell,
            "mhexam":  mhexam,
            "bundle":  bundle,
        }

        # ── Aggregate significance ───────────────────────────────────────────
        summaries = []

        # PCM found in cetcell pages (only with specific declaration phrases)
        if cetcell["pcm_found"]:
            result["pcm_found_anywhere"] = True
            result["significant_change"] = True
            summaries.append(f"PCM result declared on cetcell: {cetcell['details']}")

        # cetcell page changed (log only, not alert-worthy alone)
        if cetcell["changed_urls"]:
            result["changed"] = True
            summaries.append(f"cetcell pages updated: {cetcell['changed_urls'][:2]}")

        # mhexam PCM endpoint live WITH real content
        if mhexam["pcm_endpoint_live"]:
            result["pcm_found_anywhere"] = True
            result["significant_change"] = True
            summaries.append(f"PCM scorecard endpoint LIVE with content: {mhexam['live_url']}")

        # Portal JS bundle changed (new deploy)
        if bundle["bundle_changed"]:
            result["changed"] = True
            result["significant_change"] = True
            summaries.append("Portal JS bundle changed — new backend deploy!")

        # Page size change
        result["size_delta"] = bundle["size_delta"]
        if bundle["size_delta"] > 800:
            result["changed"] = True
            summaries.append(f"Portal page size +{bundle['size_delta']} bytes")

        result["change_summary"] = " | ".join(summaries) if summaries else "No changes"
        result["success"] = True

        # ── Deduplication: don't re-alert on same signal ─────────────────────
        alert_sent_for = state.get("alert_sent_for", [])
        if result["pcm_found_anywhere"]:
            if "pcm_found" in alert_sent_for:
                result["pcm_found_anywhere"] = False  # already alerted — skip
                result["change_summary"] += " (alert already sent — skipping duplicate)"
            else:
                alert_sent_for.append("pcm_found")
                state["alert_sent_for"] = alert_sent_for

        if result["significant_change"] and not result["pcm_found_anywhere"]:
            sig_key = f"sig_{result['change_summary'][:40]}"
            if sig_key in alert_sent_for:
                result["significant_change"] = False  # already alerted
            else:
                alert_sent_for.append(sig_key)
                state["alert_sent_for"] = alert_sent_for

        # Save updated state
        _save_state(state)

    except Exception as e:
        result["error"] = f"Change detector error: {str(e)}"

    return result
