from pathlib import Path
from datetime import datetime
import shutil
import re
import subprocess
import sys

FILE = Path("app/routers/teams_bot.py")

if not FILE.exists():
    raise SystemExit(f"File not found: {FILE}")

backup = f"{FILE}.bak-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

old_text = text

pattern = re.compile(
    r"raw_result\s*=\s*await\s+azure_openai_service\.draft_ticket_reply\s*\((.*?)\)",
    re.DOTALL,
)

replacement = """raw_result = await azure_openai_service.classify_ticket(
            text
        )"""

text, count = pattern.subn(replacement, text, count=1)

if count != 1:
    raise SystemExit(
        f"Expected to replace 1 draft_ticket_reply call, found {count}"
    )

FILE.write_text(text, encoding="utf-8")

verify = FILE.read_text(encoding="utf-8")

if "draft_ticket_reply(" in verify:
    raise SystemExit(
        "Verification failed: draft_ticket_reply still exists"
    )

if "classify_ticket(" not in verify:
    raise SystemExit(
        "Verification failed: classify_ticket not found"
    )

print("[OK] Replacement completed")
print("[OK] Backup created:", backup)

print("\nCompiling...\n")

result = subprocess.run(
    [sys.executable, "-m", "py_compile", str(FILE)],
    capture_output=True,
    text=True,
)

if result.returncode != 0:
    print(result.stdout)
    print(result.stderr)
    raise SystemExit("Compile failed")

print("[OK] Compile successful")
print("[OK] teams_bot.py ready to commit")