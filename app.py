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
from checker.public_monitor import check_public_notices
from checker.change_detector import check_portal_changes
from checker.api_direct_checker import check_api_direct

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
_check_lock   = threading.Lock()
_monitor_lock = threading.Lock()
_detector_lock = threading.Lock()
_api_lock      = threading.Lock()


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
                timeout=180,   # 3 min — Railway containers can be slow
                cwd=os.path.dirname(__file__)
            )
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()

            # Always log stderr so Railway logs show the real error
            if stderr:
                for line in stderr.splitlines():
                    if line.strip():
                        logger.warning(f"[SUBPROCESS] {line}")

            if not stdout:
                err_detail = stderr[-500:] if stderr else "no stderr either"
                raise ValueError(
                    f"Subprocess returned no output (exit={proc.returncode}). "
                    f"Last stderr: {err_detail}"
                )

            # Parse JSON — use last line in case there's extra output
            result = None
            for line in reversed(stdout.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        result = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue
            if result is None:
                raise ValueError(f"Could not parse JSON from subprocess output: {stdout[:300]}")

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
                    # BUG FIX: Only send website-down alert ONCE (at exactly 3 errors)
                    # Previously fired every 5 min after 3 errors = 78 duplicate WhatsApps
                    if consecutive == 3:
                        _send_whatsapp_safe(MSG_WEBSITE_DOWN, "whatsapp_error")
            return

        # ── Handle portal changed ─────────────────────────────────────────
        # BUG FIX #7: Do NOT stop the whole scheduler on portal_changed.
        # portal_changed just means the UI layout may have shifted — not a
        # result declaration. Keep running so we still catch the real result.
        if portal_changed:
            logger.warning("[CHECK] Portal UI changed — layout may have shifted. Continuing checks.")
            log_check(
                login_status=login_status,
                pcm_found=False,
                error_message="Portal UI changed (layout shift)",
                screenshot_path=screenshot
            )
            _send_whatsapp_safe(MSG_PORTAL_CHANGED, "whatsapp_info")
            # DO NOT pause scheduler or stop checker here
            # BUG FIX FINAL: return here to avoid double log_check below
            return

        # ── React to final result ─────────────────────────────────────────
        # BUG FIX: pcm_found was already read from result on line 178.
        # Removed duplicate re-read here to keep a single source of truth.
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


# ── Public Notice Monitor ─────────────────────────────────────────────────────

def run_public_monitor():
    """
    Check cetcell.mahacet.org every 60s for new PCM notices.
    Alerts via call + WhatsApp if a new PCM notice is detected.
    """
    if not _monitor_lock.acquire(blocking=False):
        return  # Already running

    try:
        result = check_public_notices()

        if not result["success"]:
            logger.warning(f"[PUBLIC] Monitor error: {result['error']}")
            return

        if result["page_changed"]:
            logger.info(f"[PUBLIC] cetcell.mahacet.org changed! New notices: {result['new_notices'][:3]}")
        else:
            logger.debug("[PUBLIC] cetcell.mahacet.org — no changes.")

        if result["new_pcm_notice"]:
            logger.warning(f"[PUBLIC] *** NEW PCM NOTICE DETECTED! Keywords: {result['pcm_keywords_found']} ***")

            wa_msg = (
                "🚨 *NEW PCM NOTICE on CET Cell Website!* 🚨\n\n"
                "A new PCM-related announcement was detected at:\n"
                "https://cetcell.mahacet.org/\n\n"
                f"Keywords found: {', '.join(result['pcm_keywords_found'])}\n\n"
                "👉 Check the Score Card on:\n"
                "https://portal-2026.maharashtracet.org\n\n"
                "⚡ Login NOW and download your PCM scorecard!"
            )
            twiml = (
                "<Response><Say voice='alice' language='en-IN'>"
                "Alert! A new PCM related notice has been posted on the CET Cell website. "
                "Please check cetcell dot mahacet dot org immediately. "
                "Your PCM scorecard may now be available!"
                "</Say></Response>"
            )
            _send_whatsapp_safe(wa_msg, "public_pcm_notice")
            _make_call_with_twiml(twiml, "public_notice_call")

    except Exception as e:
        logger.exception(f"[PUBLIC] Unexpected error: {e}")
    finally:
        _monitor_lock.release()


def run_change_detector():
    """
    Detect significant backend changes on portal-2026.maharashtracet.org.
    Also checks cetcell result pages and mhexam.com PCM endpoints.
    Alerts via call + WhatsApp on significant changes or PCM detection.
    """
    if not _detector_lock.acquire(blocking=False):
        return  # Already running

    try:
        result = check_portal_changes()

        if not result["success"]:
            logger.warning(f"[CHANGE] Detector error: {result['error']}")
            return

        # ── PCM directly found (mhexam endpoint live / cetcell has PCM) ──────
        if result.get("pcm_found_anywhere"):
            logger.warning(
                f"[CHANGE] *** PCM RESULT DETECTED via change detector! "
                f"Summary: {result['change_summary']} ***"
            )
            wa_msg = (
                "🚨 *MHT-CET PCM RESULT DETECTED!* 🚨\n\n"
                "PCM scorecard infrastructure is LIVE!\n\n"
                f"Signal: {result['change_summary']}\n\n"
                "👉 Login NOW:\n"
                "https://portal-2026.maharashtracet.org\n\n"
                "Click Score Card → Get Score Card (PCM) ⚡"
            )
            twiml = (
                "<Response><Say voice='alice' language='en-IN'>"
                "Alert! Alert! The MHT CET PCM result infrastructure is now live! "
                "Your PCM scorecard is available. "
                "Login to the portal immediately and download your scorecard NOW!"
                "</Say></Response>"
            )
            _send_whatsapp_safe(wa_msg, "pcm_detected_change")
            _make_call_with_twiml(twiml, "pcm_detected_call")
            return

        # ── Significant structural change (new deploy, bundle update) ────────
        if result["significant_change"]:
            logger.warning(
                f"[CHANGE] *** SIGNIFICANT PORTAL CHANGE DETECTED! "
                f"Summary: {result['change_summary']} | "
                f"Size delta: {result['size_delta']} bytes ***"
            )
            wa_msg = (
                "⚠️ *MHT-CET Portal Backend Change Detected!* ⚠️\n\n"
                "The portal has changed significantly — results may be uploading!\n\n"
                f"Change: {result['change_summary']}\n\n"
                "👉 Check NOW:\n"
                "https://portal-2026.maharashtracet.org\n\n"
                "⚡ Login and check Score Card section immediately!"
            )
            twiml = (
                "<Response><Say voice='alice' language='en-IN'>"
                "Warning! The MHT CET portal has changed significantly. "
                "This may indicate that results are being uploaded right now. "
                "Please login to portal 2026 dot maharashtracet dot org immediately "
                "and check the Score Card section!"
                "</Say></Response>"
            )
            _send_whatsapp_safe(wa_msg, "portal_change_alert")
            _make_call_with_twiml(twiml, "change_detector_call")

        elif result["changed"]:
            logger.info(f"[CHANGE] Minor portal change (size delta: {result['size_delta']} bytes) — ignoring.")
        else:
            logger.debug("[CHANGE] Portal unchanged.")

    except Exception as e:
        logger.exception(f"[CHANGE] Unexpected error: {e}")
    finally:
        _detector_lock.release()


def _fire_alerts():
    """Send all Twilio alerts and mark as done."""
    # 1. WhatsApp
    wa_result = _send_whatsapp_safe(MSG_PCM_FOUND, "whatsapp_found")
    logger.info(f"WhatsApp result: {wa_result}")

    # 2. Phone call
    call_result = _make_call_safe()
    logger.info(f"Call result: {call_result}")

    # 3. Mark alert as sent in DB — dashboard shows correct state
    update_status(alert_sent=True, pcm_found=True, checker_running=False)

    # 4. Pause ONLY the scorecard checker — keep public monitor + change detector running
    #    (they may detect the result via a different signal while scorecard check is paused)
    try:
        job = scheduler.get_job("mhtcet_check")
        if job:
            job.pause()
            logger.info("[OK] Scorecard check job paused (public monitor + change detector still active).")
    except Exception:
        scheduler.pause()  # fallback
    logger.info("[OK] PCM alerts sent.")


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


def _make_call_with_twiml(twiml: str, notif_type: str = "call") -> dict:
    """Make a phone call with custom TwiML message."""
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_PHONE, MY_PHONE]):
        logger.warning("Call skipped - Twilio credentials not configured.")
        return {"success": False, "error": "Credentials not configured"}
    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        call = client.calls.create(twiml=twiml, to=MY_PHONE, from_=TWILIO_PHONE)
        log_notification(notif_type=notif_type, success=True,
                         message=f"Call SID: {call.sid}")
        logger.info(f"[CALL] {notif_type} sent → {MY_PHONE} (SID: {call.sid})")
        return {"success": True, "sid": call.sid}
    except Exception as e:
        log_notification(notif_type=notif_type, success=False, error=str(e))
        logger.error(f"[CALL] {notif_type} failed: {e}")
        return {"success": False, "error": str(e)}


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

    # BUG FIX G: _fire_alerts() pauses only the mhtcet_check job, not the whole
    # scheduler. So scheduler.state is still RUNNING (1), and the resume() below
    # never fires. Must explicitly resume the individual paused job.
    if scheduler.state == 2:       # whole scheduler paused
        scheduler.resume()
    elif scheduler.state == 0:     # scheduler not started yet
        _start_scheduler()
    else:
        # Scheduler is running — just resume the specific job if it was paused
        try:
            job = scheduler.get_job("mhtcet_check")
            if job and job.next_run_time is None:
                job.resume()
                logger.info("[START] mhtcet_check job resumed.")
        except Exception as ex:
            logger.warning(f"[START] Could not resume job: {ex}")

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

def run_api_direct_check():
    """
    Job 4: Fastest + most accurate check.
    Calls portal-2026.maharashtracet.org/api/scorecards directly using
    saved Playwright session cookies — no browser needed.
    Runs every 90 seconds after first Playwright login.
    """
    if not _api_lock.acquire(blocking=False):
        logger.debug("[API-DIRECT] Previous check still running, skipping.")
        return
    try:
        status = get_status()
        if not status.checker_running:
            return
        if status.alert_sent:
            logger.debug("[API-DIRECT] Alert already sent, skipping.")
            return

        result = check_api_direct()

        # Session expired — skip silently, Playwright will refresh it
        if result.get("session_expired"):
            logger.info("[API-DIRECT] Session expired — waiting for Playwright to refresh.")
            return

        if not result["authenticated"]:
            logger.debug(f"[API-DIRECT] Not authenticated yet: {result['error']}")
            return

        logger.info(
            f"[API-DIRECT] endpoint={result['endpoint_hit']} | "
            f"PCM={result['pcm_found']} | "
            f"snippet={result['raw_snippet'][:60]}"
        )

        if result["pcm_found"]:
            logger.warning("[API-DIRECT] *** PCM FOUND via direct API! ALERTING NOW! ***")
            _fire_alerts()

    except Exception as e:
        logger.exception(f"[API-DIRECT] Unexpected error: {e}")
    finally:
        _api_lock.release()


def _start_scheduler():
    # ── Job 1: Portal login + scorecard checker (every 5 min) ────────────────
    scheduler.add_job(
        func=run_check,
        trigger=IntervalTrigger(seconds=CHECK_INTERVAL, timezone="Asia/Kolkata"),
        id="mhtcet_check",
        name="MHTCET Scorecard Check",
        replace_existing=True,
        misfire_grace_time=60
    )

    # ── Job 2: Public website notice monitor (every 60 seconds) ──────────────
    scheduler.add_job(
        func=run_public_monitor,
        trigger=IntervalTrigger(seconds=60, timezone="Asia/Kolkata"),
        id="public_notice_monitor",
        name="CET Cell Public Notice Monitor",
        replace_existing=True,
        misfire_grace_time=30
    )

    # ── Job 3: Portal change detector (every 2 minutes) ───────────────────────
    scheduler.add_job(
        func=run_change_detector,
        trigger=IntervalTrigger(seconds=120, timezone="Asia/Kolkata"),
        id="portal_change_detector",
        name="Portal Backend Change Detector",
        replace_existing=True,
        misfire_grace_time=30
    )

    # ── Job 4: Direct API check using session cookies (every 90 seconds) ─────
    # Fastest + most accurate — calls /api/scorecards directly, no browser.
    # Only useful after first Playwright login saves session_state.json.
    scheduler.add_job(
        func=run_api_direct_check,
        trigger=IntervalTrigger(seconds=90, timezone="Asia/Kolkata"),
        id="api_direct_check",
        name="Direct API Scorecard Check",
        replace_existing=True,
        misfire_grace_time=30
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
