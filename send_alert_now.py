"""Emergency alert — PCM Scorecard is AVAILABLE NOW."""
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from twilio.rest import Client

sid        = os.getenv("TWILIO_ACCOUNT_SID")
token      = os.getenv("TWILIO_AUTH_TOKEN")
from_phone = os.getenv("TWILIO_PHONE_NUMBER")
to_phone   = os.getenv("YOUR_PHONE_NUMBER")
wa_from    = os.getenv("TWILIO_WHATSAPP_NUMBER", "+14155238886")

client = Client(sid, token)

# ── Phone Call ─────────────────────────────────────────────────────────────────
twiml = (
    "<Response>"
    "<Say voice='alice' language='en-IN'>"
    "Alert! Alert! Alert! "
    "Your MHT CET PCM Scorecard is NOW AVAILABLE! "
    "Login immediately to portal 2026 dot maharashtracet dot org and download it now! "
    "I repeat, MHT CET PCM Scorecard is NOW AVAILABLE. Login and download NOW!"
    "</Say>"
    "<Pause length='1'/>"
    "<Say voice='alice' language='en-IN'>"
    "PCM Scorecard is available. Go to Score Card section. Click Get Score Card. Download NOW!"
    "</Say>"
    "</Response>"
)

try:
    call = client.calls.create(twiml=twiml, to=to_phone, from_=from_phone)
    print(f"[OK] CALL SENT! SID: {call.sid} -> {to_phone}")
except Exception as e:
    print(f"[ERROR] Call failed: {e}")

# ── WhatsApp ───────────────────────────────────────────────────────────────────
wa_body = (
    "🚨 *MHT-CET PCM SCORECARD IS NOW AVAILABLE!* 🚨\n\n"
    "✅ Your score card is LIVE RIGHT NOW!\n\n"
    "👉 Login here IMMEDIATELY:\n"
    "https://portal-2026.maharashtracet.org\n\n"
    "📋 Steps:\n"
    "1. Login with your email & password\n"
    "2. Click 'Score Card'\n"
    "3. Click 'Get Score Card'\n"
    "4. Download your PCM Scorecard!\n\n"
    "⚡ DO NOT DELAY — Download NOW!"
)

try:
    msg = client.messages.create(
        body=wa_body,
        from_=f"whatsapp:{wa_from}",
        to=f"whatsapp:{to_phone}"
    )
    print(f"[OK] WHATSAPP SENT! SID: {msg.sid} -> {to_phone}")
except Exception as e:
    print(f"[ERROR] WhatsApp failed: {e}")

print("\nDONE. Check your phone!")
