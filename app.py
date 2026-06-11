"""
app.py — MHTCET Result Available Checker
Main entry point: Flask web app + APScheduler + Playwright automation

Run: python app.py
Dashboard: http://localhost:5000
"""

import os
import sys
import json
import logging
import threading
import subprocess
from datetime import datetime, timedelta

# Force UTF-8 output on Windows to handle special characters in logs
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# ── Local modules ──────────────────────────────────────────────────────────────
from database.db import (
    init_db, get_status, update_status, log_check,
    log_notification, get_recent_logs, reset_alert
)
from notifications.twilio_call import make_phone_call
from notifications.whatsapp import (
    send_whatsapp,
    MSG_PCM_FOUND, MSG_LOGIN_FAILED, MSG_PORTAL_CHANGED,
    MSG_WEBSITE_DOWN, MSG_CHECKER_STARTED, MSG_TEST
)

# Path to the subprocess checker script
SUBPROCESS_CHECKER = os.path.join(os.path.dirname(__file__), "checker", "run_check_subprocess.py")

# ── Logging Setup ──────────────────────────────────────────────────────────────
import logging.handlers
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            "logs/checker.log", maxBytes=5 * 1024 * 1024, backupCount=3
        )
    ]
)
logger = logging.getLogger("mhtcet.app")

# ── Environment ────────────────────────────────────────────────────────────────
EMAIL = os.getenv("MHTCET_EMAIL", "")
PASSWORD = os.getenv("MHTCET_PASSWORD", "")
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE = os.getenv("TWILIO_PHONE_NUMBER", "")
TWILIO_WA = os.getenv("TWILIO_WHATSAPP_NUMBER", "+14155238886")
MY_PHONE = os.getenv("YOUR_PHONE_NUMBER", "")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
LOGIN_URL = os.getenv("LOGIN_URL", "https://portal-2026.mahacet.org")

# ── Flask App ──────────────────────────────────────────────────────────────────
app = Flask(
    __name__,
    template_folder="dashboard/templates",
    static_folder="dashboard/static"
)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "mhtcet-secret-2026")

# ── Scheduler ─────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
_check_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════════
#  CORE CHECKER LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def run_check():
    """Main check cycle: runs Playwright in subprocess to avoid greenlet thread issues."""
    if not _check_lock.acquire(blocking=False):
        logger.info("Previous check still running, skipping this cycle.")
        return

    try:
        # ── Guard: skip if alert already sent or checker manually stopped ──
        status = get_status()
        if status.alert_sent:
            logger.info("[IDLE] Alert already sent. Checker is idle until reset.")
            return

        if not status.checker_running:
            logger.info("[IDLE] Checker is stopped. Skipping cycle.")
            return

        logger.info("=" * 60)
        logger.info(f"[CHECK] Starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # ── Update next check time ─────────────────────────────────────────
        next_check_time = datetime.now() + timedelta(seconds=CHECK_INTERVAL)
        update_status(next_check=next_check_time)

        # ── Run Playwright in a subprocess (avoids greenlet thread error) ──
        logger.info("[BROWSER] Launching Playwright subprocess...")
        try:
            proc = subprocess.run(
                [sys.executable, SUBPROCESS_CHECKER],
                capture_output=True,
                text=True,
                timeout=120,   # Max 2 min per check
                cwd=os.path.dirname(__file__)
            )
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()

            if stderr:
                # Filter out routine warnings
                real_errors = [l for l in stderr.splitlines()
                               if "DeprecationWarning" not in l
                               and "RequestsDependencyWarning" not in l
                               and l.strip()]
                if real_errors:
                    logger.warning(f"[SUBPROCESS STDERR] {chr(10).join(real_errors[:5])}")

            if not stdout:
                raise ValueError("Subprocess returned no output. Check SUBPROCESS_CHECKER path.")

            result = json.loads(stdout)

        except subprocess.TimeoutExpired:
            result = {
                "success": False,
                "login_status": "error",
                "pcm_found": False,
                "error": "Check timed out after 120 seconds.",
                "screenshot": None,
                "portal_changed": False,
            }
        except json.JSONDecodeError as e:
            result = {
                "success": False,
                "login_status": "error",
                "pcm_found": False,
                "error": f"Subprocess JSON parse error: {e}. Output: {stdout[:200]}",
                "screenshot": None,
                "portal_changed": False,
            }

        # ── Log the result ────────────────────────────────────────────────
        login_status = result.get("login_status", "error")
        pcm_found    = result.get("pcm_found", False)
        error_msg    = result.get("error")
        screenshot   = result.get("screenshot")
        portal_changed = result.get("portal_changed", False)

        logger.info(f"[RESULT] login={login_status} | pcm_found={pcm_found} | error={error_msg}")

        # ── Handle login failure ──────────────────────────────────────────
        if login_status in ("failed", "error") and not pcm_found:
            log_check(
                login_status=login_status,
                pcm_found=False,
                error_message=error_msg,
                screenshot_path=screenshot
            )
            if error_msg:
                if "credentials" in error_msg.lower() or "login failed" in error_msg.lower():
                    _send_whatsapp_safe(MSG_LOGIN_FAILED, "whatsapp_error")
                elif "timeout" in error_msg.lower() or "unreachable" in error_msg.lower():
                    consecutive = get_status().consecutive_errors or 0
                    if consecutive >= 3:
                        _send_whatsapp_safe(MSG_WEBSITE_DOWN, "whatsapp_error")
            return

        # ── Handle portal changed ─────────────────────────────────────────
        if portal_changed:
            logger.warning("Portal UI changed!")
            log_check(
                login_status=login_status,
                pcm_found=False,
                error_message=error_msg,
                screenshot_path=screenshot
            )
            _send_whatsapp_safe(MSG_PORTAL_CHANGED, "whatsapp_error")
            update_status(checker_running=False)
            scheduler.pause()
            return

        # ── React to final result ─────────────────────────────────────────
        pcm_found = result.get("pcm_found", False)

        log_check(
            login_status="success",
            pcm_found=pcm_found,
            screenshot_path=result.get("screenshot")
        )

        if pcm_found:
            logger.info("*** PCM SCORECARD FOUND! Sending alerts... ***")
            _fire_alerts()
        else:
            logger.info("[--] PCM Scorecard not available yet. Will check again.")

    except Exception as e:
        logger.exception(f"Unhandled exception in run_check: {e}")
        log_check(
            login_status="error",
            pcm_found=False,
            error_message=str(e)
        )
    finally:
        _check_lock.release()


def _fire_alerts():
    """Send all Twilio alerts and mark as done."""
    # 1. WhatsApp
    wa_result = _send_whatsapp_safe(MSG_PCM_FOUND, "whatsapp_found")
    logger.info(f"WhatsApp result: {wa_result}")

    # 2. Phone call
    call_result = _make_call_safe()
    logger.info(f"Call result: {call_result}")

    # 3. Mark alert as sent — no more notifications
    update_status(alert_sent=True, pcm_found=True, checker_running=False)
    scheduler.pause()
    logger.info("[OK] All alerts sent. Checker paused.")


def _send_whatsapp_safe(message: str, notif_type: str) -> dict:
    """Send WhatsApp and log the result."""
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_WA, MY_PHONE]):
        logger.warning("WhatsApp skipped - Twilio credentials not configured.")
        return {"success": False, "error": "Credentials not configured"}

    result = send_whatsapp(
        to=MY_PHONE,
        from_=TWILIO_WA,
        account_sid=TWILIO_SID,
        auth_token=TWILIO_TOKEN,
        message=message
    )
    log_notification(
        notif_type=notif_type,
        success=result["success"],
        message=message[:200],
        error=result.get("error")
    )
    return result


def _make_call_safe() -> dict:
    """Make a phone call and log the result."""
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_PHONE, MY_PHONE]):
        logger.warning("Call skipped - Twilio credentials not configured.")
        return {"success": False, "error": "Credentials not configured"}

    result = make_phone_call(
        to=MY_PHONE,
        from_=TWILIO_PHONE,
        account_sid=TWILIO_SID,
        auth_token=TWILIO_TOKEN
    )
    log_notification(
        notif_type="call",
        success=result["success"],
        message="PCM Scorecard phone call alert",
        error=result.get("error")
    )
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  FLASK ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html", login_url=LOGIN_URL)


@app.route("/api/status")
def api_status():
    status = get_status()

    # ── Get next run time directly from APScheduler (always accurate) ──
    next_check_secs = None
    try:
        job = scheduler.get_job("mhtcet_check")
        if job and job.next_run_time:
            import pytz
            ist = pytz.timezone("Asia/Kolkata")
            now_ist = datetime.now(ist)
            delta = (job.next_run_time - now_ist).total_seconds()
            next_check_secs = max(0, int(delta))
    except Exception:
        pass

    # ── Format last_checked in IST ─────────────────────────────────────
    last_checked_str = "Never"
    if status.last_checked:
        try:
            import pytz
            ist = pytz.timezone("Asia/Kolkata")
            lc = status.last_checked
            # Make timezone-aware if naive
            if lc.tzinfo is None:
                lc = ist.localize(lc)
            last_checked_str = lc.strftime("%d %b %Y %I:%M:%S %p")
        except Exception:
            last_checked_str = status.last_checked.strftime("%d %b %Y %I:%M:%S %p")

    return jsonify({
        "checker_running": status.checker_running,
        "pcm_found": status.pcm_found,
        "alert_sent": status.alert_sent,
        "last_checked": last_checked_str,
        "next_check_secs": next_check_secs,
        "last_login_status": status.last_login_status or "—",
        "last_error": status.last_error or "",
        "total_checks": status.total_checks or 0,
        "consecutive_errors": status.consecutive_errors or 0,
        "check_interval": CHECK_INTERVAL,
    })


@app.route("/api/logs")
def api_logs():
    logs = get_recent_logs(25)
    return jsonify(logs)


@app.route("/api/start", methods=["POST"])
def api_start():
    status = get_status()
    if status.checker_running:
        return jsonify({"ok": False, "msg": "Checker is already running."})
    if status.alert_sent:
        return jsonify({"ok": False, "msg": "Alert already sent! Reset first."})

    update_status(checker_running=True)
    if scheduler.state == 2:  # paused
        scheduler.resume()
    elif scheduler.state == 0:  # stopped
        _start_scheduler()

    logger.info("[START] Checker STARTED via dashboard.")
    _send_whatsapp_safe(MSG_CHECKER_STARTED, "whatsapp_info")
    return jsonify({"ok": True, "msg": "Checker started!"})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    update_status(checker_running=False)
    if scheduler.running:
        scheduler.pause()
    logger.info("[STOP] Checker STOPPED via dashboard.")
    return jsonify({"ok": True, "msg": "Checker stopped."})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    reset_alert()
    logger.info("[RESET] Alert status reset via dashboard.")
    return jsonify({"ok": True, "msg": "Alert reset. You can restart the checker now."})


@app.route("/api/test-notification", methods=["POST"])
def api_test():
    """
    Test Twilio notifications WITHOUT touching alert_sent or checker state.
    This way tests don't block future real checks.
    """
    notif_type = request.json.get("type", "whatsapp") if request.is_json else "whatsapp"
    results = {}

    if notif_type in ("whatsapp", "both"):
        # Send directly — bypass _send_whatsapp_safe which logs to DB and sets flags
        from notifications.whatsapp import send_whatsapp
        res = send_whatsapp(
            to=MY_PHONE,
            from_=TWILIO_WA,
            account_sid=TWILIO_SID,
            auth_token=TWILIO_TOKEN,
            message=MSG_TEST
        )
        results["whatsapp"] = res
        logger.info(f"[TEST] WhatsApp test sent: {res}")

    if notif_type in ("call", "both"):
        # Send directly — bypass _make_call_safe
        from notifications.twilio_call import make_phone_call
        res = make_phone_call(
            to=MY_PHONE,
            from_=TWILIO_PHONE,
            account_sid=TWILIO_SID,
            auth_token=TWILIO_TOKEN
        )
        results["call"] = res
        logger.info(f"[TEST] Call test sent: {res}")

    return jsonify({"ok": True, "results": results})


@app.route("/api/run-now", methods=["POST"])
def api_run_now():
    """Trigger an immediate check (runs in background thread)."""
    t = threading.Thread(target=run_check, daemon=True)
    t.start()
    return jsonify({"ok": True, "msg": "Check triggered!"})


# ══════════════════════════════════════════════════════════════════════════════
#  STARTUP
# ══════════════════════════════════════════════════════════════════════════════

def _start_scheduler():
    scheduler.add_job(
        func=run_check,
        trigger=IntervalTrigger(seconds=CHECK_INTERVAL, timezone="Asia/Kolkata"),
        id="mhtcet_check",
        name="MHTCET Scorecard Check",
        replace_existing=True,
        misfire_grace_time=60
    )
    if not scheduler.running:
        scheduler.start()


def validate_config():
    """Warn if required env vars are missing."""
    missing = []
    if not EMAIL:
        missing.append("MHTCET_EMAIL")
    if not PASSWORD:
        missing.append("MHTCET_PASSWORD")
    if not TWILIO_SID:
        missing.append("TWILIO_ACCOUNT_SID")
    if not TWILIO_TOKEN:
        missing.append("TWILIO_AUTH_TOKEN")
    if not MY_PHONE:
        missing.append("YOUR_PHONE_NUMBER")
    if missing:
        logger.warning(f"[WARN] Missing env vars: {', '.join(missing)}")
        logger.warning("   Copy .env.example to .env and fill in your credentials.")
    else:
        logger.info("[OK] All environment variables loaded.")


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  MHTCET Result Available Checker — Starting Up")
    logger.info("=" * 60)

    validate_config()
    init_db()
    _start_scheduler()

    port = int(os.getenv("PORT", 5000))
    logger.info(f"[WEB] Dashboard: http://localhost:{port}")
    logger.info(f"[CFG] Check interval: every {CHECK_INTERVAL}s")
    logger.info(f"[CFG] Monitoring: {LOGIN_URL}")

    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
