from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys

FILE = Path("app/routers/teams_bot.py")
if not FILE.exists():
    raise SystemExit(f"File not found: {FILE}")

backup = Path(f"{FILE}.bak-{datetime.now():%Y%m%d-%H%M%S}")
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

# Capture serviceUrl alongside conversation_id
old_conv = 'conversation_id = (payload.get("conversation") or {}).get("id")'
new_conv = (
    'conversation_id = (payload.get("conversation") or {}).get("id")\n'
    '    service_url = payload.get("serviceUrl")'
)
if old_conv in text and "service_url = payload.get" not in text:
    text = text.replace(old_conv, new_conv, 1)

# Store serviceUrl in external_ref on ticket creation
old_ticket = (
    "        source=TicketSource.TEAMS,\n"
    "        reporter_name=sender,\n"
    "        conversation_id=conversation_id,\n"
    "    )"
)
new_ticket = (
    "        source=TicketSource.TEAMS,\n"
    "        reporter_name=sender,\n"
    "        conversation_id=conversation_id,\n"
    "        external_ref=service_url,\n"
    "    )"
)
if old_ticket in text and "external_ref=service_url" not in text:
    text = text.replace(old_ticket, new_ticket, 1)

FILE.write_text(text, encoding="utf-8")

verify = FILE.read_text(encoding="utf-8")
errors = []
if "service_url = payload.get" not in verify:
    errors.append("serviceUrl capture missing")
if "external_ref=service_url" not in verify:
    errors.append("external_ref assignment missing")

result = subprocess.run(
    [sys.executable, "-m", "py_compile", str(FILE)],
    capture_output=True, text=True,
)
if result.returncode != 0:
    errors.append("Compile failed:\n" + result.stdout + result.stderr)

if errors:
    shutil.copy2(backup, FILE)
    print("[FAILED] Rolled back automatically.")
    for e in errors:
        print(e)
    raise SystemExit(1)

print("[OK] serviceUrl captured into external_ref on Teams tickets")
print("[OK] Compiles successfully")
print(f"[OK] Backup: {backup}")
