"""
checker/change_detector.py
Monitors portal-2026.maharashtracet.org for backend changes that signal
result upload (page size change, new content, response header changes).
Runs without login — checks public page.
"""
import requests
import hashlib
import json
from pathlib import Path
from datetime import datetime

PORTAL_URL = "https://portal-2026.maharashtracet.org/"
STATE_FILE = Path(__file__).parent.parent / "portal_change_state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Size change threshold (bytes) that's considered significant
SIGNIFICANT_BYTES = 800


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def check_portal_changes() -> dict:
    """
    Fetch the portal and detect backend changes.
    Returns result dict with change details.
    """
    result = {
        "success": False,
        "changed": False,
        "significant_change": False,
        "size_delta": 0,
        "size_bytes": 0,
        "etag_changed": False,
        "last_modified_changed": False,
        "error": None,
        "checked_at": datetime.utcnow().isoformat(),
        "change_summary": "",
    }

    try:
        resp = requests.get(PORTAL_URL, timeout=20, headers=HEADERS)
        resp.raise_for_status()

        html         = resp.text
        content_hash = hashlib.md5(html.encode()).hexdigest()
        size         = len(html.encode())

        # Capture response headers that signal content updates
        etag          = resp.headers.get("ETag", "")
        last_modified = resp.headers.get("Last-Modified", "")
        cache_control = resp.headers.get("Cache-Control", "")

        # Load previous state
        state    = _load_state()
        prev     = state.get("snapshots", [])
        prev_snap = prev[-1] if prev else {}

        prev_hash     = prev_snap.get("hash", "")
        prev_size     = prev_snap.get("size", 0)
        prev_etag     = prev_snap.get("etag", "")
        prev_lm       = prev_snap.get("last_modified", "")

        # Detect changes
        hash_changed = prev_hash and prev_hash != content_hash
        size_delta   = abs(size - prev_size) if prev_size else 0
        etag_changed = bool(prev_etag and prev_etag != etag)
        lm_changed   = bool(prev_lm and prev_lm != last_modified)

        result["changed"]               = hash_changed
        result["size_delta"]            = size_delta
        result["size_bytes"]            = size
        result["etag_changed"]          = etag_changed
        result["last_modified_changed"] = lm_changed

        # Significant = large size change OR ETag changed OR Last-Modified changed
        result["significant_change"] = (
            (hash_changed and size_delta >= SIGNIFICANT_BYTES) or
            etag_changed or
            lm_changed
        )

        if result["significant_change"]:
            parts = []
            if size_delta >= SIGNIFICANT_BYTES:
                parts.append(f"page size changed by {size_delta} bytes")
            if etag_changed:
                parts.append("ETag changed")
            if lm_changed:
                parts.append(f"Last-Modified changed to {last_modified}")
            result["change_summary"] = "; ".join(parts)

        # Save new snapshot (keep last 5)
        new_snap = {
            "hash":          content_hash,
            "size":          size,
            "etag":          etag,
            "last_modified": last_modified,
            "checked_at":    result["checked_at"],
        }
        snapshots = (prev + [new_snap])[-5:]
        _save_state({"snapshots": snapshots})

        result["success"] = True

    except requests.exceptions.RequestException as e:
        result["error"] = f"HTTP error: {str(e)}"
    except Exception as e:
        result["error"] = f"Unexpected error: {str(e)}"

    return result
