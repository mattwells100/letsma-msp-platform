from pathlib import Path
from datetime import datetime
import shutil, subprocess, sys

FILE = Path("app/routers/webhooks_whatsapp.py")
if not FILE.exists():
    raise SystemExit(f"Missing {FILE}")

backup = Path(f"{FILE}.bak-{datetime.now():%Y%m%d-%H%M%S}")
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

if "import json" not in text:
    text = text.replace(
        "from app.services import whatsapp_service",
        "from app.services import whatsapp_service\nimport json",
        1,
    )

anchor = "    payload = await request.json()\n"
inject = (
    "    payload = await request.json()\n"
    '    print("WHATSAPP_INBOUND " + json.dumps(payload)[:2000])\n'
)
if "WHATSAPP_INBOUND" not in text:
    if anchor not in text:
        raise SystemExit("anchor not found")
    text = text.replace(anchor, inject, 1)

FILE.write_text(text, encoding="utf-8")

errors = []
if "WHATSAPP_INBOUND" not in FILE.read_text(encoding="utf-8"):
    errors.append("debug line missing")

r = subprocess.run([sys.executable, "-m", "py_compile", str(FILE)],
                   capture_output=True, text=True)
if r.returncode != 0:
    errors.append("compile failed:\n" + r.stdout + r.stderr)

if errors:
    shutil.copy2(backup, FILE)
    print("[FAILED] rolled back")
    for e in errors:
        print(e)
    raise SystemExit(1)

print("[OK] WhatsApp payload logging added")
print(f"[OK] Backup: {backup}")
