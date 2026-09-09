from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys

FILE = Path("app/routers/teams_bot.py")

backup = f"{FILE}.bak-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

target = "suggestion = _parse_ticket_classification(raw_result)"

if target not in text:
    raise SystemExit(
        f"Could not find target line:\n{target}"
    )

replacement = """
        print("=" * 80)
        print("RAW CLASSIFICATION RESPONSE")
        print(repr(raw_result))
        print("=" * 80)

        suggestion = _parse_ticket_classification(raw_result)
"""

text = text.replace(target, replacement.strip("\n"), 1)

FILE.write_text(text, encoding="utf-8")

verify = FILE.read_text(encoding="utf-8")

if "RAW CLASSIFICATION RESPONSE" not in verify:
    raise SystemExit("Verification failed")

print("[OK] Patch applied")
print("[OK] Backup:", backup)

result = subprocess.run(
    [sys.executable, "-m", "py_compile", str(FILE)],
    capture_output=True,
    text=True,
)

if result.returncode != 0:
    print(result.stderr)
    raise SystemExit("Compile failed")

print("[OK] Compile successful")