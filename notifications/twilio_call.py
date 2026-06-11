"""
notifications/twilio_call.py — Make a phone call via Twilio when PCM scorecard is available.
"""

import os
import logging
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

logger = logging.getLogger("mhtcet.notif.call")

LOGIN_URL = os.getenv("LOGIN_URL", "https://cetcell.mahacet.org")

TWIML_ALERT = """
<Response>
  <Say voice="alice" language="en-IN">
    Attention! Attention!
    Your MHT CET PCM Scorecard is now available.
    Please login immediately and download it.
    I repeat — Your MHT CET P C M Score Card is now available.
    Please login to {url} and download it immediately.
    Good luck!
  </Say>
  <Pause length="1"/>
  <Say voice="alice" language="en-IN">
    This is an automated alert from your MHT CET Checker system.
    PCM Scorecard is now available. Login now!
  </Say>
</Response>
""".strip().replace("{url}", LOGIN_URL)


def make_phone_call(to: str, from_: str, account_sid: str, auth_token: str) -> dict:
    """
    Make a Twilio phone call to alert user about PCM scorecard.

    Returns:
        { "success": bool, "sid": str | None, "error": str | None }
    """
    result = {"success": False, "sid": None, "error": None}

    try:
        client = Client(account_sid, auth_token)
        call = client.calls.create(
            twiml=TWIML_ALERT,
            to=to,
            from_=from_
        )
        logger.info(f"[Call] Initiated. SID: {call.sid} -> {to}")
        result["success"] = True
        result["sid"] = call.sid

    except TwilioRestException as e:
        result["error"] = f"Twilio error: {e.msg}"
        logger.error(f"Twilio call failed: {e.msg}")

    except Exception as e:
        result["error"] = str(e)
        logger.exception("Unexpected error making phone call.")

    return result
