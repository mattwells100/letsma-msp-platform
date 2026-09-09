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

original = FILE.read_text(encoding="utf-8")
lines = original.splitlines(keepends=True)

# These headings identify temporary diagnostic print blocks added during
# Teams payload and Azure OpenAI classification troubleshooting.
debug_headings = {
    "TEAMS PAYLOAD",
    "RAW CLASSIFICATION RESPONSE",
    "RAW CLASSIFICATION",
    "PARSED CLASSIFICATION",
    "SUGGESTION DICT",
}

cleaned = []
removed_lines = []
i = 0

while i < len(lines):
    stripped = lines[i].strip()

    # Expected diagnostic shape:
    # print("=" * 80)
    # print("DEBUG HEADING")
    # print(...)
    # print("=" * 80)
    if stripped == 'print("=" * 80)' and i + 1 < len(lines):
        next_stripped = lines[i + 1].strip()
        matched_heading = next(
            (
                heading
                for heading in debug_headings
                if next_stripped == f'print("{heading}")'
            ),
            None,
        )

        if matched_heading:
            block_start = i
            i += 2

            while i < len(lines):
                if lines[i].strip() == 'print("=" * 80)':
                    i += 1
                    break
                i += 1

            removed_lines.extend(lines[block_start:i])

            # Remove one blank line left by the diagnostic block, but do not
            # disturb the surrounding executable code or indentation.
            if i < len(lines) and not lines[i].strip():
                i += 1
            continue

    cleaned.append(lines[i])
    i += 1

updated = "".join(cleaned)

if not removed_lines:
    print("[OK] No recognised temporary debug blocks were found.")
    print("[OK] No source changes were made.")
    backup.unlink(missing_ok=True)
    raise SystemExit(0)

FILE.write_text(updated, encoding="utf-8")

errors = []
verify = FILE.read_text(encoding="utf-8")

for heading in debug_headings:
    if f'print("{heading}")' in verify:
        errors.append(f"Debug heading still present: {heading}")

compile_result = subprocess.run(
    [sys.executable, "-m", "py_compile", str(FILE)],
    capture_output=True,
    text=True,
)

if compile_result.returncode != 0:
    errors.append(
        "Compilation failed:\n"
        + compile_result.stdout
        + compile_result.stderr
    )

if errors:
    shutil.copy2(backup, FILE)
    print("[FAILED] Cleanup was rolled back automatically.")
    for error in errors:
        print(error)
    raise SystemExit(1)

removed_headings = [
    heading
    for heading in sorted(debug_headings)
    if f'print("{heading}")' in "".join(removed_lines)
]

print("[OK] Temporary Teams debug logging removed")
print(f"[OK] Removed {len(removed_lines)} diagnostic source lines")
for heading in removed_headings:
    print(f"[OK] Removed: {heading}")
print("[OK] teams_bot.py compiles successfully")
print(f"[OK] Backup: {backup}")
print("[INFO] Concise failure logging was retained for operational diagnostics")
