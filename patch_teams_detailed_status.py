from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys

FILE = Path("app/routers/teams_bot.py")

if not FILE.exists():
    raise SystemExit(f"Missing {FILE}")

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup = Path(f"{FILE}.bak-detailed-status-{stamp}")
shutil.copy2(FILE, backup)

original = FILE.read_text(encoding="utf-8")
text = original

# -------------------------------------------------------------------
# Replace the complete GET_STATUS handler.
# The SHOW_TICKETS condition is used as the end boundary if GET_STATUS
# appears before it. Otherwise the normal new-ticket flow boundary is
# used.
# -------------------------------------------------------------------

start_marker = "    if intent == TeamsIntent.GET_STATUS:\n"

if start_marker not in text:
    raise SystemExit("Could not find GET_STATUS handler")

start = text.index(start_marker)

possible_end_markers = [
    "\n    if not text:\n",
    "\n    if intent == TeamsIntent.NEW_TICKET:\n",
]

end = None
for marker in possible_end_markers:
    position = text.find(marker, start + len(start_marker))
    if position != -1:
        end = position
        break

if end is None:
    raise SystemExit("Could not find the end of the GET_STATUS handler")

new_handler = '''    if intent == TeamsIntent.GET_STATUS:
        ticket_number = meta.get("ticket_number")

        print(
            f"[TEAMS_INTENT] GET_STATUS_TRIGGERED "
            f"ticket={ticket_number} "
            f"conversation={conversation_id}"
        )

        ticket = (
            db.query(Ticket)
            .filter(
                Ticket.ticket_number == ticket_number,
                Ticket.conversation_id == conversation_id,
                Ticket.deleted_at.is_(None),
            )
            .first()
        )

        if not ticket:
            await send_teams_reply(
                db=db,
                ticket=_conversation_ticket(
                    conversation_id,
                    service_url,
                ),
                message=(
                    f"I could not find ticket #{ticket_number} "
                    f"in this Teams conversation."
                ),
            )
            return {}

        def _display_value(value, fallback="Not set"):
            if value is None:
                return fallback
            return getattr(value, "value", str(value))

        def _display_datetime(value, fallback="Not set"):
            if value is None:
                return fallback
            return value.strftime("%d %b %Y %H:%M")

        status_text = _display_value(ticket.status)
        priority_text = _display_value(ticket.priority, "Normal")

        category_text = getattr(ticket, "category", None) or "Unclassified"
        subcategory_text = getattr(ticket, "subcategory", None)

        if subcategory_text:
            classification_text = (
                f"{category_text} > {subcategory_text}"
            )
        else:
            classification_text = category_text

        assigned_value = getattr(ticket, "assigned_to", None)
        assigned_text = _display_value(
            assigned_value,
            "Not yet assigned",
        )

        created_text = _display_datetime(
            getattr(ticket, "created_at", None)
        )
        updated_text = _display_datetime(
            getattr(ticket, "updated_at", None)
        )

        resolved_value = getattr(ticket, "resolved_at", None)
        resolved_text = _display_datetime(
            resolved_value,
            "Not resolved",
        )

        details = [
            f"Ticket #{ticket.ticket_number}",
            "",
            f"Issue: {ticket.subject}",
            f"Status: {status_text}",
            f"Priority: {priority_text}",
            f"Category: {classification_text}",
            f"Assigned to: {assigned_text}",
            f"Created: {created_text}",
            f"Last updated: {updated_text}",
        ]

        if resolved_value is not None:
            details.append(f"Resolved or closed: {resolved_text}")

        await send_teams_reply(
            db=db,
            ticket=ticket,
            message="\\n".join(details),
        )

        return {}
'''

text = text[:start] + new_handler + text[end:]

FILE.write_text(text, encoding="utf-8")

# -------------------------------------------------------------------
# Verification
# -------------------------------------------------------------------

errors = []
updated = FILE.read_text(encoding="utf-8")

required = [
    "GET_STATUS_TRIGGERED",
    "Ticket.conversation_id == conversation_id",
    "Priority:",
    "Category:",
    "Assigned to:",
    "Created:",
    "Last updated:",
    "Resolved or closed:",
    "await send_teams_reply(",
]

for item in required:
    if item not in updated:
        errors.append(f"Missing expected code: {item}")

# Confirm exactly one GET_STATUS handler remains.
handler_count = updated.count(
    "if intent == TeamsIntent.GET_STATUS:"
)
if handler_count != 1:
    errors.append(
        f"Expected one GET_STATUS handler, found {handler_count}"
    )

compile_result = subprocess.run(
    [sys.executable, "-m", "py_compile", str(FILE)],
    capture_output=True,
    text=True,
)

if compile_result.returncode != 0:
    errors.append(
        "Compile failed:\n"
        + compile_result.stdout
        + compile_result.stderr
    )

if errors:
    shutil.copy2(backup, FILE)
    print("[FAILED] Changes rolled back")
    for error in errors:
        print(error)
    raise SystemExit(1)

print("[OK] Detailed Teams ticket status response added")
print("[OK] Ticket lookup restricted to the current conversation")
print("[OK] Missing optional fields are handled safely")
print("[OK] teams_bot.py compiles")
print(f"[OK] Backup: {backup}")
