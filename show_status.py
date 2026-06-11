"""Quick status and log viewer."""
from database.db import init_db, get_recent_logs, get_status
import os, glob

init_db()

print("=" * 55)
print("  CURRENT STATUS")
print("=" * 55)
s = get_status()
print(f"  checker_running : {s.checker_running}")
print(f"  alert_sent      : {s.alert_sent}")
print(f"  last_login      : {s.last_login_status}")
print(f"  last_error      : {s.last_error}")
print(f"  total_checks    : {s.total_checks}")
print(f"  pcm_found       : {s.pcm_found}")
print(f"  last_checked    : {s.last_checked}")

print()
print("=" * 55)
print("  LAST 10 CHECKS FROM DATABASE")
print("=" * 55)
logs = get_recent_logs(10)
if not logs:
    print("  No checks recorded yet.")
else:
    for log in logs:
        lid = log.get("id", "?")
        ts  = log.get("timestamp", "?")
        ls  = log.get("login_status", "?")
        pcm = log.get("pcm_found", False)
        err = log.get("error_message") or "-"
        print(f"  [{lid}] {ts}")
        print(f"        login={ls}  pcm_found={pcm}")
        print(f"        error={err[:80]}")
        print()

print()
print("=" * 55)
print("  SCREENSHOTS SAVED")
print("=" * 55)
shots = sorted(glob.glob("screenshots/*.png"))
if not shots:
    print("  No screenshots yet.")
else:
    for s in shots[-8:]:
        size = os.path.getsize(s)
        name = os.path.basename(s)
        print(f"  {name}  ({size//1024} KB)")
