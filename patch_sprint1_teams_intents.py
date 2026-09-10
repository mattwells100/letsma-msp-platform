from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys

ROOT = Path(".")

INTENT_FILE = ROOT / "app/services/teams_intent_service.py"
BOT_FILE = ROOT / "app/routers/teams_bot.py"

if not BOT_FILE.exists():
    raise SystemExit("teams_bot.py not found")

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup = Path(f"{BOT_FILE}.bak-{stamp}")
shutil.copy2(BOT_FILE, backup)

# ------------------------------------------------------------------
# 1. Create intent service
# ------------------------------------------------------------------

intent_code = '''from enum import Enum
import re


class TeamsIntent(str, Enum):
    NEW_TICKET = "NEW_TICKET"
    SHOW_TICKETS = "SHOW_TICKETS"
    GET_STATUS = "GET_STATUS"
    HELP = "HELP"


_STATUS_PATTERNS = [
    r"status\\s+(?:of\\s+)?(?:ticket\\s+)?#?(\\d+)",
    r"ticket\\s+#?(\\d+)",
    r"what.?s\\s+happening\\s+with\\s+(?:ticket\\s+)?#?(\\d+)",
]


_SHOW_TICKET_PHRASES = [
    "show my tickets",
    "my tickets",
    "open tickets",
    "show tickets",
    "list tickets",
]


_HELP_PHRASES = [
    "help",
    "what can you do",
    "commands",
]


def detect_intent(text: str):
    text_lower = text.lower().strip()

    for phrase in _SHOW_TICKET_PHRASES:
        if phrase in text_lower:
            return TeamsIntent.SHOW_TICKETS, {}

    for phrase in _HELP_PHRASES:
        if text_lower == phrase:
            return TeamsIntent.HELP, {}

    for pattern in _STATUS_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            return (
                TeamsIntent.GET_STATUS,
                {"ticket_number": int(match.group(1))}
            )

    return TeamsIntent.NEW_TICKET, {}
'''

INTENT_FILE.write_text(intent_code, encoding="utf-8")

# ------------------------------------------------------------------
# 2. Patch teams_bot.py
# ------------------------------------------------------------------

text = BOT_FILE.read_text(encoding="utf-8")

# import
if "from app.services.teams_intent_service import" not in text:
    text = text.replace(
        "from app.services.ticket_numbering import next_ticket_number",
        "from app.services.ticket_numbering import next_ticket_number\n"
        "from app.services.teams_intent_service import detect_intent, TeamsIntent",
        1,
    )

# inject intent handling after text extraction

old = '    text = (payload.get("text") or "").strip()\n'

new = '''    text = (payload.get("text") or "").strip()

    intent, meta = detect_intent(text)

    if intent == TeamsIntent.HELP:
        return _reply(
            "I can help with:\\n\\n"
            "• Create a ticket\\n"
            "• Show my tickets\\n"
            "• Status of 1087\\n"
            "• What's happening with ticket 1087?"
        )

    if intent == TeamsIntent.SHOW_TICKETS:
        tickets = (
            db.query(Ticket)
            .filter(
                Ticket.conversation_id == conversation_id,
                Ticket.deleted_at.is_(None),
            )
            .order_by(Ticket.updated_at.desc())
            .limit(10)
            .all()
        )

        if not tickets:
            return _reply(
                "You do not currently have any tickets."
            )

        lines = []

        for t in tickets:
            lines.append(
                f"#{t.ticket_number} {t.subject}\\n"
                f"Status: {t.status.value}"
            )

        return _reply(
            "Your recent tickets:\\n\\n"
            + "\\n\\n".join(lines)
        )

    if intent == TeamsIntent.GET_STATUS:
        ticket_number = meta["ticket_number"]

        ticket = (
            db.query(Ticket)
            .filter(
                Ticket.ticket_number == ticket_number,
                Ticket.deleted_at.is_(None),
            )
            .first()
        )

        if not ticket:
            return _reply(
                f"Ticket #{ticket_number} was not found."
            )

        return _reply(
            f"Ticket #{ticket.ticket_number}\\n\\n"
            f"Subject: {ticket.subject}\\n"
            f"Status: {ticket.status.value}\\n"
            f"Last updated: "
            f"{ticket.updated_at:%d %b %Y %H:%M}"
        )
'''

if "detect_intent(text)" not in text:
    if old not in text:
        raise SystemExit("Could not find text extraction point")
    text = text.replace(old, new, 1)

BOT_FILE.write_text(text, encoding="utf-8")

# ------------------------------------------------------------------
# verify
# ------------------------------------------------------------------

errors = []

for file in [INTENT_FILE, BOT_FILE]:
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(file)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        errors.append(result.stderr)

if errors:
    shutil.copy2(backup, BOT_FILE)
    print("[FAILED] rolled back")
    for err in errors:
        print(err)
    raise SystemExit(1)

print("[OK] Sprint 1 intent service created")
print("[OK] Teams bot patched")
print(f"[OK] Backup: {backup}")