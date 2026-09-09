from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys

FILE = Path("app/routers/tickets.py")

if not FILE.exists():
    raise SystemExit(f"Missing {FILE}")

backup = Path(f"{FILE}.bak-{datetime.now():%Y%m%d-%H%M%S}")
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

marker = """    if (
        ticket.source == models.TicketSource.TEAMS
        and not comment.is_internal_note
    ):
"""

debug_block = """
    print(
        f"TEAMS_CHECK "
        f"ticket={ticket.id} "
        f"source={ticket.source} "
        f"is_internal={comment.is_internal_note}"
    )

"""

if "TEAMS_CHECK" not in text:
    if marker not in text:
        raise SystemExit("Could not find Teams reply block")
    text = text.replace(marker, debug_block + marker, 1)

FILE.write_text(text, encoding="utf-8")

errors = []

updated = FILE.read_text(encoding="utf-8")

if "TEAMS_CHECK" not in updated:
    errors.append("Debug block not inserted")

result = subprocess.run(
    [sys.executable, "-m", "py_compile", str(FILE)],
    capture_output=True,
    text=True,
)

if result.returncode != 0:
    errors.append(
        "Compile failed:\n"
        + result.stdout
        + result.stderr
    )

if errors:
    shutil.copy2(backup, FILE)
    print("[FAILED] rolled back")
    for err in errors:
        print(err)
    raise SystemExit(1)

print("[OK] TEAMS_CHECK logging added")
print(f"[OK] Backup: {backup}")