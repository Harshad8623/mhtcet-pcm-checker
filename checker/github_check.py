"""
checker/github_check.py
Standalone PCM checker for GitHub Actions.
Runs ALL 3 checks:
  1. Playwright scorecard check (login + Score Card popup)
  2. cetcell.mahacet.org public notice monitor
  3. Portal change detector (mhexam.com + JS bundle)
Sends Twilio alerts if PCM scorecard is found by ANY check.
"""
import subprocess
import sys
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ── Helper: send alerts ───────────────────────────────────────────────────────
def send_alerts(wa_body: str, twiml: str):
    from twilio.rest import Client
    sid      = os.environ["TWILIO_ACCOUNT_SID"]
    token    = os.environ["TWILIO_AUTH_TOKEN"]
    from_num = os.environ["TWILIO_PHONE_NUMBER"]
    to_num   = os.environ["YOUR_PHONE_NUMBER"]
    wa_from  = os.environ.get("TWILIO_WHATSAPP_NUMBER", "+14155238886")

    client = Client(sid, token)
    try:
        call = client.calls.create(twiml=twiml, to=to_num, from_=from_num)
        print(f"[OK] Call sent! SID: {call.sid} -> {to_num}")
    except Exception as e:
        print(f"[ERROR] Call failed: {e}")

    try:
        msg = client.messages.create(
            body=wa_body, from_=f"whatsapp:{wa_from}", to=f"whatsapp:{to_num}"
        )
        print(f"[OK] WhatsApp sent! SID: {msg.sid} -> {to_num}")
    except Exception as e:
        print(f"[ERROR] WhatsApp failed: {e}")


print("=" * 60)
print(f"[CHECK] MHT-CET PCM Checker — GitHub Actions")
print(f"[CHECK] Starting at {time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
print("=" * 60)

pcm_found_by = None  # which check found PCM

# ══════════════════════════════════════════════════════════════════════════════
# CHECK 1: Playwright scorecard (login + Score Card popup)
# ══════════════════════════════════════════════════════════════════════════════
print("\n[1/3] Running Playwright scorecard check...")
script = Path(__file__).parent / "run_check_subprocess.py"

proc = subprocess.run(
    [sys.executable, str(script)],
    capture_output=True, text=True, timeout=300, cwd=ROOT
)

if proc.stderr:
    for line in proc.stderr.strip().splitlines():
        print(f"  {line}")

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
    print("[ERROR] Could not parse scorecard result JSON.")
    print(proc.stdout[-500:])
else:
    print(f"[1/3] Login: {result_json.get('login_status')} | PCM: {result_json.get('pcm_found')}")
    if result_json.get("pcm_found"):
        pcm_found_by = "Playwright scorecard check"

# ══════════════════════════════════════════════════════════════════════════════
# CHECK 2: Public notice monitor (cetcell.mahacet.org)
# ══════════════════════════════════════════════════════════════════════════════
print("\n[2/3] Running public notice monitor...")
try:
    sys.path.insert(0, str(ROOT))
    from checker.public_monitor import check_public_notices
    r2 = check_public_notices()
    print(f"[2/3] Success: {r2['success']} | New PCM notice: {r2['new_pcm_notice']} | Keywords: {r2['pcm_keywords_found']}")
    if r2.get("new_pcm_notice"):
        pcm_found_by = pcm_found_by or f"Public notice: {r2['pcm_keywords_found']}"
except Exception as e:
    print(f"[2/3] ERROR: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# CHECK 3: Portal change detector
# ══════════════════════════════════════════════════════════════════════════════
print("\n[3/3] Running portal change detector...")
try:
    from checker.change_detector import check_portal_changes
    r3 = check_portal_changes()
    print(f"[3/3] Success: {r3['success']} | PCM found: {r3['pcm_found_anywhere']} | Summary: {r3['change_summary']}")
    if r3.get("pcm_found_anywhere"):
        pcm_found_by = pcm_found_by or f"Change detector: {r3['change_summary']}"
except Exception as e:
    print(f"[3/3] ERROR: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# RESULT
# ══════════════════════════════════════════════════════════════════════════════
if not pcm_found_by:
    print("\n[OK] PCM scorecard not available yet. Will check again at next scheduled run.")
    sys.exit(0)

# PCM FOUND!
print("\n" + "🚨" * 30)
print(f"*** MHT-CET PCM SCORECARD DETECTED! ***")
print(f"*** Source: {pcm_found_by} ***")
print("🚨" * 30 + "\n")

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
wa_body = (
    "🚨 *MHT-CET PCM SCORECARD IS NOW AVAILABLE!* 🚨\n\n"
    "✅ Your PCM score card is LIVE RIGHT NOW!\n\n"
    f"🔍 Detected by: {pcm_found_by}\n\n"
    "👉 Login here IMMEDIATELY:\n"
    "https://portal-2026.maharashtracet.org\n\n"
    "📋 Steps:\n"
    "1. Login with your email & password\n"
    "2. Click 'Score Card'\n"
    "3. Click 'Get Score Card' next to PCM\n"
    "4. Download your scorecard!\n\n"
    "⚡ DO NOT DELAY — Download NOW!"
)

send_alerts(wa_body, twiml)
print("\n[DONE] All alerts dispatched!")
sys.exit(0)
