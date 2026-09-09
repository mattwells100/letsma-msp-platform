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

replacement = """
        print("=" * 80)
        print("RAW CLASSIFICATION")
        print(repr(raw_result))
        print("=" * 80)

        suggestion = _parse_ticket_classification(raw_result)

        print("=" * 80)
        print("SUGGESTION DICT")
        print(repr(suggestion))
        print("=" * 80)
"""

if target not in text:
    raise SystemExit(f"Could not find target: {target}")

text = text.replace(target, replacement, 1)

FILE.write_text(text, encoding="utf-8")

verify = FILE.read_text(encoding="utf-8")

assert "SUGGESTION DICT" in verify

result = subprocess.run(
    [sys.executable, "-m", "py_compile", str(FILE)],
    capture_output=True,
    text=True,
)

if result.returncode:
    print(result.stderr)
    raise SystemExit("Compile failed")

print("[OK] Patch applied")
print("[OK] Compile successful")
print("[OK] Backup:", backup)