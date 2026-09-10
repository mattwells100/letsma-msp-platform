from pathlib import Path
from datetime import datetime
import shutil

FILE = Path("app/routers/teams_bot.py")

backup = Path(
    f"{FILE}.bak-teams-reply-{datetime.now():%Y%m%d-%H%M%S}"
)
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

# ------------------------------------------------------------------
# import send_teams_reply
# ------------------------------------------------------------------

if "from app.services.teams_reply_service import send_teams_reply" not in text:
    text = text.replace(
        "from app.services.ticket_numbering import next_ticket_number",
        "from app.services.ticket_numbering import next_ticket_number\n"
        "from app.services.teams_reply_service import send_teams_reply",
        1,
    )

# ------------------------------------------------------------------
# helper ticket object
# ------------------------------------------------------------------

helper = '''

def _conversation_ticket(
    conversation_id,
    service_url,
):
    class _TempTicket:
        pass

    t = _TempTicket()
    t.conversation_id = conversation_id
    t.external_ref = service_url
    return t

'''

if "_conversation_ticket(" not in text:
    text = text.replace(
        'def _reply(text: str) -> dict:\n    return {"type": "message", "text": text}\n',
        'def _reply(text: str) -> dict:\n    return {"type": "message", "text": text}\n'
        + helper,
        1,
    )

# ------------------------------------------------------------------
# HELP
# ------------------------------------------------------------------

old = """
    if intent == TeamsIntent.HELP:
        print("[TEAMS_INTENT] HELP_TRIGGERED")
        return _reply(
            "I can help with:\\n\\n"
            "• Create a ticket\\n"
            "• Show my tickets\\n"
            "• Status of 1087\\n"
            "• What's happening with ticket 1087?"
        )
"""

new = """
    if intent == TeamsIntent.HELP:
        print("[TEAMS_INTENT] HELP_TRIGGERED")

        await send_teams_reply(
            db=db,
            ticket=_conversation_ticket(
                conversation_id,
                service_url,
            ),
            message=(
                "I can help with:\\n\\n"
                "• Create a ticket\\n"
                "• Show my tickets\\n"
                "• Status of 1087\\n"
                "• What's happening with ticket 1087?"
            ),
        )

        return {}
"""

text = text.replace(old, new)

# ------------------------------------------------------------------
# show my tickets
# ------------------------------------------------------------------

text = text.replace(
    '        return _reply(\n            "Your recent tickets:\\n\\n"\n            + "\\n\\n".join(lines)\n        )',
    '''        await send_teams_reply(
            db=db,
            ticket=_conversation_ticket(
                conversation_id,
                service_url,
            ),
            message=(
                "Your recent tickets:\\n\\n"
                + "\\n\\n".join(lines)
            ),
        )
        return {}
''',
)

# ------------------------------------------------------------------
# ticket not found
# ------------------------------------------------------------------

text = text.replace(
    '''            return _reply(
                f"Ticket #{ticket_number} was not found."
            )''',
    '''            await send_teams_reply(
                db=db,
                ticket=_conversation_ticket(
                    conversation_id,
                    service_url,
                ),
                message=f"Ticket #{ticket_number} was not found.",
            )
            return {}''',
)

# ------------------------------------------------------------------
# ticket status
# ------------------------------------------------------------------

text = text.replace(
    '''        return _reply(
            f"Ticket #{ticket.ticket_number}\\n\\n"
            f"Subject: {ticket.subject}\\n"
            f"Status: {ticket.status.value}\\n"
            f"Last updated: "
            f"{ticket.updated_at:%d %b %Y %H:%M}"
        )''',
    '''        await send_teams_reply(
            db=db,
            ticket=_conversation_ticket(
                conversation_id,
                service_url,
            ),
            message=(
                f"Ticket #{ticket.ticket_number}\\n\\n"
                f"Subject: {ticket.subject}\\n"
                f"Status: {ticket.status.value}\\n"
                f"Last updated: "
                f"{ticket.updated_at:%d %b %Y %H:%M}"
            ),
        )
        return {}''',
)

FILE.write_text(text, encoding="utf-8")

print("[OK] Sprint 1 responses changed to proactive Teams replies")
print(f"[OK] Backup: {backup}")