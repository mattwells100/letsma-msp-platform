from pathlib import Path
from datetime import datetime
import shutil

FILE = Path("app/routers/teams_bot.py")

if not FILE.exists():
    raise SystemExit(f"{FILE} not found")

backup = Path(
    f"{FILE}.bak-intent-debug-{datetime.now():%Y%m%d-%H%M%S}"
)
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

old = """    intent, meta = detect_intent(text)
"""

new = """    intent, meta = detect_intent(text)

    print(
        f"[TEAMS_INTENT] "
        f"intent={intent} "
        f"text={text!r} "
        f"meta={meta}"
    )
"""

if "[TEAMS_INTENT]" not in text:
    text = text.replace(old, new, 1)

help_old = """    if intent == TeamsIntent.HELP:
        return _reply(
"""

help_new = """    if intent == TeamsIntent.HELP:
        print("[TEAMS_INTENT] HELP_TRIGGERED")
        return _reply(
"""

if "HELP_TRIGGERED" not in text:
    text = text.replace(help_old, help_new, 1)

show_old = """    if intent == TeamsIntent.SHOW_TICKETS:
        tickets = (
"""

show_new = """    if intent == TeamsIntent.SHOW_TICKETS:
        print("[TEAMS_INTENT] SHOW_TICKETS_TRIGGERED")

        tickets = (
"""

if "SHOW_TICKETS_TRIGGERED" not in text:
    text = text.replace(show_old, show_new, 1)

status_old = """    if intent == TeamsIntent.GET_STATUS:
        ticket_number = meta["ticket_number"]
"""

status_new = """    if intent == TeamsIntent.GET_STATUS:
        print(
            f"[TEAMS_INTENT] "
            f"GET_STATUS_TRIGGERED "
            f"ticket={meta.get('ticket_number')}"
        )

        ticket_number = meta["ticket_number"]
"""

if "GET_STATUS_TRIGGERED" not in text:
    text = text.replace(status_old, status_new, 1)

FILE.write_text(text, encoding="utf-8")

print("[OK] Intent diagnostics added")
print(f"[OK] Backup: {backup}")