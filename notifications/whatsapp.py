"""
notifications/whatsapp.py — Send WhatsApp messages via Twilio.
"""

import os
import logging
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

logger = logging.getLogger("mhtcet.notif.whatsapp")

LOGIN_URL = os.getenv("LOGIN_URL", "https://cetcell.mahacet.org")

# ── Message Templates ──────────────────────────────────────────────────────────

MSG_PCM_FOUND = (
    "🚨 *MHTCET ALERT* 🚨\n\n"
    "✅ *PCM Attempt 2 Scorecard is NOW AVAILABLE!*\n\n"
    "📋 MHT-CET (PCM) 2026 Attempt 2 Score Card can be downloaded.\n\n"
    f"🔗 Login immediately: {LOGIN_URL}\n\n"
    "⏰ Don't delay — download your Attempt 2 scorecard now!\n"
    "_This is an automated alert from your MHTCET Checker._"
)

MSG_LOGIN_FAILED = (
    "⚠️ *MHTCET Checker — Login Failed*\n\n"
    "❌ Could not log in to the portal.\n"
    "Please verify your credentials in the `.env` file.\n\n"
    "_Checker will retry automatically._"
)

MSG_PORTAL_CHANGED = (
    "🟡 *MHTCET Checker — Portal UI Changed*\n\n"
    "⚠️ The portal layout has shifted slightly (common before result uploads).\n\n"
    "📸 A screenshot has been saved to the `screenshots/` folder.\n"
    "🔍 The checker is still running and monitoring automatically.\n\n"
    "_No action needed — you will be alerted when PCM result is found._"
)

MSG_WEBSITE_DOWN = (
    "📡 *MHTCET Checker — Website Unreachable*\n\n"
    "🌐 The MHTCET portal is currently unreachable (timeout/network error).\n"
    "_Will retry in 5 minutes._"
)

MSG_CHECKER_STARTED = (
    "✅ *MHTCET Checker Started*\n\n"
    "🤖 Your MHTCET PCM **Attempt 2** Scorecard checker is now running.\n"
    f"🔍 Monitoring: {LOGIN_URL}\n"
    "📲 You will be notified via WhatsApp & Phone Call when PCM Attempt 2 Scorecard is available.\n\n"
    "_Stay tuned!_"
)

MSG_TEST = (
    "🧪 *MHTCET Checker — Test Notification*\n\n"
    "✅ WhatsApp notifications are working correctly!\n"
    "_If you receive this, Twilio is configured properly._"
)


def send_whatsapp(
    to: str,
    from_: str,
    account_sid: str,
    auth_token: str,
    message: str
) -> dict:
    """
    Send a WhatsApp message via Twilio.

    Args:
        to: Recipient number (will be prefixed with 'whatsapp:' if needed)
        from_: Twilio WhatsApp number (will be prefixed with 'whatsapp:' if needed)
        account_sid, auth_token: Twilio credentials
        message: Text to send

    Returns:
        { "success": bool, "sid": str | None, "error": str | None }
    """
    result = {"success": False, "sid": None, "error": None}

    def _wa(num: str) -> str:
        return f"whatsapp:{num}" if not num.startswith("whatsapp:") else num

    try:
        client = Client(account_sid, auth_token)
        msg = client.messages.create(
            body=message,
            from_=_wa(from_),
            to=_wa(to)
        )
        logger.info(f"[WhatsApp] Sent OK. SID: {msg.sid} -> {to}")
        result["success"] = True
        result["sid"] = msg.sid

    except TwilioRestException as e:
        result["error"] = f"Twilio error: {e.msg}"
        logger.error(f"WhatsApp send failed: {e.msg}")

    except Exception as e:
        result["error"] = str(e)
        logger.exception("Unexpected error sending WhatsApp.")

    return result
