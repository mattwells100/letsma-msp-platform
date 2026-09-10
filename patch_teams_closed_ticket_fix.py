from pathlib import Path
from datetime import datetime
import shutil

FILE = Path("app/routers/teams_bot.py")

if not FILE.exists():
    raise SystemExit(f"{FILE} not found")

backup = Path(
    f"{FILE}.bak-closed-ticket-fix-{datetime.now():%Y%m%d-%H%M%S}"
)
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

old = """
    existing = None
    if conversation_id:
        existing = (
            db.query(Ticket)
            .filter(Ticket.conversation_id == conversation_id)
            .filter(Ticket.deleted_at.is_(None))
            .order_by(Ticket.created_at.desc())
            .first()
        )
"""

new = """
    existing = None
    if conversation_id:
        existing = (
            db.query(Ticket)
            .filter(Ticket.conversation_id == conversation_id)
            .filter(Ticket.deleted_at.is_(None))
            .order_by(Ticket.created_at.desc())
            .first()
        )

        if existing:
            status_value = str(existing.status).upper()

            if any(
                s in status_value
                for s in [
                    "CLOSED",
                    "RESOLVED",
                    "COMPLETE",
                    "COMPLETED",
                ]
            ):
                print(
                    f"[TEAMS] Existing ticket "
                    f"{existing.ticket_number} "
                    f"is closed, creating new ticket"
                )
                existing = None
"""

if old not in text:
    raise SystemExit(
        "Could not locate existing ticket lookup block"
    )

text = text.replace(old, new, 1)

FILE.write_text(text, encoding="utf-8")

print("[OK] Closed-ticket check added")
print(f"[OK] Backup: {backup}")