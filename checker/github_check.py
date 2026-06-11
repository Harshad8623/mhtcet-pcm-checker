"""
checker/github_check.py
Standalone PCM checker for GitHub Actions.
Runs the Playwright check and sends Twilio alerts if PCM scorecard is found.
"""
import subprocess
import sys
import json
import os
import time
from pathlib import Path

# ── Run the Playwright checker ──────────────────────────────────────────────
print("=" * 60)
print(f"[CHECK] MHT-CET PCM Checker — GitHub Actions")
print(f"[CHECK] Starting check at {time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
print("=" * 60)

script = Path(__file__).parent / "run_check_subprocess.py"

proc = subprocess.run(
    [sys.executable, str(script)],
    capture_output=True,
    text=True,
    timeout=300,
    cwd=Path(__file__).parent.parent
)

# Print stderr logs for visibility in GitHub Actions log
if proc.stderr:
    for line in proc.stderr.strip().splitlines():
        print(f"  {line}")

# Parse JSON result from stdout
result_json = None
for line in reversed(proc.stdout.strip().splitlines()):
    line = line.strip()
    if line.startswith("{"):
        try:
            result_json = json.loads(line)
            break
        except json.JSONDecodeError:
            continue

if not result_json:
    print("[ERROR] Could not parse result JSON. Raw stdout:")
    print(proc.stdout[-500:])
    sys.exit(1)

print(f"\n[RESULT] {json.dumps(result_json, indent=2)}")

login_status = result_json.get("login_status", "error")
pcm_found    = result_json.get("pcm_found", False)
error        = result_json.get("error")

# ── Handle result ────────────────────────────────────────────────────────────
if error:
    print(f"[WARN] Check error: {error}")

if login_status in ("failed", "error") and not pcm_found:
    print(f"[SKIP] Login/check failed: {error}")
    sys.exit(0)   # Don't fail the workflow for transient errors

if not pcm_found:
    print("[OK] PCM scorecard not available yet. Will check again at next scheduled run.")
    sys.exit(0)

# ── PCM FOUND — Send alerts! ─────────────────────────────────────────────────
print("\n" + "🚨" * 30)
print("*** MHT-CET PCM SCORECARD IS AVAILABLE! ***")
print("🚨" * 30 + "\n")

from twilio.rest import Client

sid       = os.environ["TWILIO_ACCOUNT_SID"]
token     = os.environ["TWILIO_AUTH_TOKEN"]
from_num  = os.environ["TWILIO_PHONE_NUMBER"]
to_num    = os.environ["YOUR_PHONE_NUMBER"]
wa_from   = os.environ.get("TWILIO_WHATSAPP_NUMBER", "+14155238886")

client = Client(sid, token)

# ── Phone Call ───────────────────────────────────────────────────────────────
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
    "Go to Score Card section. Click Get Score Card. Download your PCM scorecard NOW!"
    "</Say>"
    "</Response>"
)

try:
    call = client.calls.create(twiml=twiml, to=to_num, from_=from_num)
    print(f"[OK] Phone call initiated! SID: {call.sid} -> {to_num}")
except Exception as e:
    print(f"[ERROR] Call failed: {e}")

# ── WhatsApp ─────────────────────────────────────────────────────────────────
wa_body = (
    "🚨 *MHT-CET PCM SCORECARD IS NOW AVAILABLE!* 🚨\n\n"
    "✅ Your PCM score card is LIVE RIGHT NOW!\n\n"
    "👉 Login here IMMEDIATELY:\n"
    "https://portal-2026.maharashtracet.org\n\n"
    "📋 Steps:\n"
    "1. Login with your email & password\n"
    "2. Click 'Score Card'\n"
    "3. Click 'Get Score Card' next to PCM\n"
    "4. Download your scorecard!\n\n"
    "⚡ DO NOT DELAY — Download NOW!"
)

try:
    msg = client.messages.create(
        body=wa_body,
        from_=f"whatsapp:{wa_from}",
        to=f"whatsapp:{to_num}"
    )
    print(f"[OK] WhatsApp sent! SID: {msg.sid} -> {to_num}")
except Exception as e:
    print(f"[ERROR] WhatsApp failed: {e}")

print("\n[DONE] All alerts dispatched!")
sys.exit(0)
