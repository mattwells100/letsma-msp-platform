from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys

FILE = Path("app/routers/teams_bot.py")

if not FILE.exists():
    raise SystemExit(f"Missing {FILE}")

backup = Path(f"{FILE}.bak-fix-sprint1-{datetime.now():%Y%m%d-%H%M%S}")
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

old_block = """    text = (payload.get("text") or "").strip()

    intent, meta = detect_intent(text)
"""

new_block = """    text = (payload.get("text") or "").strip()

    sender = (payload.get("from") or {}).get("name") or "Teams user"
    conversation_id = (payload.get("conversation") or {}).get("id")
    service_url = payload.get("serviceUrl")

    intent, meta = detect_intent(text)
"""

if old_block not in text:
    raise SystemExit(
        "Could not find expected Sprint 1 intent block"
    )

text = text.replace(old_block, new_block, 1)

# Remove duplicate definitions later in the file
duplicate_block = """
    sender = (payload.get("from") or {}).get("name") or "Teams user"
    conversation_id = (payload.get("conversation") or {}).get("id")
    service_url = payload.get("serviceUrl")
"""

first = text.find(duplicate_block)
if first != -1:
    second = text.find(duplicate_block, first + 1)
    if second != -1:
        text = text[:second] + text[second + len(duplicate_block):]

FILE.write_text(text, encoding="utf-8")

# Verify compile
result = subprocess.run(
    [sys.executable, "-m", "py_compile", str(FILE)],
    capture_output=True,
    text=True,
)

if result.returncode != 0:
    shutil.copy2(backup, FILE)
    print("[FAILED] Compile error, rollback performed")
    print(result.stderr)
    raise SystemExit(1)

print("[OK] Sprint 1 conversation_id ordering fixed")
print("[OK] Duplicate sender/conversation_id block removed")
print(f"[OK] Backup: {backup}")