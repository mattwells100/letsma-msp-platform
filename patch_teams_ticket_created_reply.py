from pathlib import Path
from datetime import datetime
import shutil

FILE = Path("app/routers/teams_bot.py")

if not FILE.exists():
    raise SystemExit(f"{FILE} not found")

backup = Path(
    f"{FILE}.bak-ticket-created-{datetime.now():%Y%m%d-%H%M%S}"
)
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

# Locate the point immediately after AI classification
anchor = """
    db.commit()
    db.refresh(ticket)
"""

if anchor not in text:
    raise SystemExit(
        "Could not locate ticket creation block"
    )

# Avoid double patching
if "Ticket #{ticket.ticket_number} Created" in text:
    raise SystemExit(
        "Ticket-created reply already appears to exist"
    )

insert = """
    db.commit()
    db.refresh(ticket)

    try:
        await send_teams_reply(
            db=db,
            ticket=ticket,
            message=(
                f"✅ Ticket #{ticket.ticket_number} Created\\n\\n"
                f"Issue:\\n"
                f"{ticket.subject}\\n\\n"
                f"Status: New\\n\\n"
                f"You can ask:\\n"
                f"• Show my tickets\\n"
                f"• Status of {ticket.ticket_number}"
            ),
        )
    except Exception as ex:
        print(
            f"[TEAMS] Ticket created reply failed: {ex}"
        )
"""

text = text.replace(anchor, insert, 1)

FILE.write_text(text, encoding="utf-8")

print("[OK] Ticket created notification added")
print(f"[OK] Backup: {backup}")
