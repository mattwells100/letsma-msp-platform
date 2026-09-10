from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys

BOT = Path("app/routers/teams_bot.py")
INTENTS = Path("app/services/teams_intent_service.py")
MEMORY = Path("app/services/teams_conversation_memory.py")

for path in (BOT, INTENTS):
    if not path.exists():
        raise SystemExit(f"Missing {path}")

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
bot_backup = Path(f"{BOT}.bak-memory-{stamp}")
intent_backup = Path(f"{INTENTS}.bak-memory-{stamp}")
memory_existed = MEMORY.exists()
memory_backup = None

shutil.copy2(BOT, bot_backup)
shutil.copy2(INTENTS, intent_backup)

if memory_existed:
    memory_backup = Path(f"{MEMORY}.bak-memory-{stamp}")
    shutil.copy2(MEMORY, memory_backup)

try:
    # ---------------------------------------------------------------
    # 1. Database-backed conversation memory service
    # ---------------------------------------------------------------

    memory_code = '''"""Database-backed memory for Teams ticket conversations."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    insert,
    select,
    update,
)
from sqlalchemy.orm import Session


_metadata = MetaData()

teams_conversation_states = Table(
    "teams_conversation_states",
    _metadata,
    Column("conversation_id", String(512), primary_key=True),
    Column("ticket_number", Integer, nullable=False),
    Column("updated_at", DateTime, nullable=False, default=datetime.utcnow),
)


def _ensure_table(db: Session) -> None:
    """Create the small state table if it does not already exist."""
    _metadata.create_all(
        bind=db.get_bind(),
        tables=[teams_conversation_states],
        checkfirst=True,
    )


def remember_ticket_number(
    db: Session,
    conversation_id: Optional[str],
    ticket_number: Optional[int],
) -> None:
    """Remember the most recently referenced ticket for a conversation."""
    if not conversation_id or ticket_number is None:
        return

    _ensure_table(db)

    existing = db.execute(
        select(teams_conversation_states.c.conversation_id).where(
            teams_conversation_states.c.conversation_id == conversation_id
        )
    ).first()

    now = datetime.utcnow()

    if existing:
        db.execute(
            update(teams_conversation_states)
            .where(
                teams_conversation_states.c.conversation_id
                == conversation_id
            )
            .values(
                ticket_number=int(ticket_number),
                updated_at=now,
            )
        )
    else:
        db.execute(
            insert(teams_conversation_states).values(
                conversation_id=conversation_id,
                ticket_number=int(ticket_number),
                updated_at=now,
            )
        )

    db.commit()


def get_remembered_ticket_number(
    db: Session,
    conversation_id: Optional[str],
) -> Optional[int]:
    """Return the last ticket referenced in this Teams conversation."""
    if not conversation_id:
        return None

    _ensure_table(db)

    row = db       select(teams_conversation_states.c.ticket_number).where(
            teams_conversation_states.c.conversation_id == conversation_id
        )
    ).first()

    return int(row[0]) if row else None
'''

    MEMORY.write_text(memory_code, encoding="utf-8")

    # ---------------------------------------------------------------
    # 2. Add conversational intents
    # ---------------------------------------------------------------

    intent_text = INTENTS.read_text(encoding="utf-8")

    enum_anchor = '    HELP = "HELP"\n'
    enum_addition = (
        '    HELP = "HELP"\n'
        '    WHEN_CLOSED = "WHEN_CLOSED"\n'
        '    WHO_ASSIGNED = "WHO_ASSIGNED"\n'
        '    LATEST_UPDATE = "LATEST_UPDATE"\n'
    )

    if "WHEN_CLOSED" not in intent_text:
        if enum_anchor not in intent_text:
            raise RuntimeError("Could not find TeamsIntent HELP enum")
        intent_text = intent_text.replace(
            enum_anchor,
            enum_addition,
            1,
        )

    detection_anchor = "    text_lower = text.lower().strip()\n"
    detection_code = '''    text_lower = text.lower().strip()

    when_closed_phrases = (
        "when was it closed",
        "when did it close",
        "when was the ticket closed",
        "when was this closed",
    )
    if any(phrase in text_lower for phrase in when_closed_phrases):
        return TeamsIntent.WHEN_CLOSED, {}

    assigned_phrases = (
        "who is working on it",
        "who's working on it",
        "who is assigned",
        "who is assigned to it",
        "who worked on it",
        "who owns it",
    )
    if any(phrase in text_lower for phrase in assigned_phrases):
        return TeamsIntent.WHO_ASSIGNED, {}

    latest_update_phrases = (
        "latest update",
        "what is the latest update",
        "what's the latest update",
        "any update",
        "any updates",
    )
    if any(phrase in text_lower for phrase in latest_update_phrases):
        return TeamsIntent.LATEST_UPDATE, {}
'''

    if "when_closed_phrases" not in intent_text:
        if detection_anchor not in intent_text:
            raise RuntimeError("Could not find intent normalisation line")
        intent_text = intent_text.replace(
            detection_anchor,
            detection_code,
            1,
        )

    INTENTS.write_text(intent_text, encoding="utf-8")

    # ---------------------------------------------------------------
    # 3. Patch Teams bot
    # ---------------------------------------------------------------

    bot_text = BOT.read_text(encoding="utf-8")

    memory_import = (
        "from app.services.teams_conversation_memory import (\n"
        "    get_remembered_ticket_number,\n"
        "    remember_ticket_number,\n"
        ")\n"
    )

    import_anchor = (
        "from app.services.teams_intent_service "
        "import detect_intent, TeamsIntent\n"
    )

    if "get_remembered_ticket_number" not in bot_text:
        if import_anchor not in bot_text:
            raise RuntimeError("Could not find Teams intent import")
        bot_text = bot_text.replace(
            import_anchor,
            import_anchor + memory_import,
            1,
        )

    # Remember a ticket after an explicit detailed status lookup.
    details_anchor = "        details = [\n"
    remember_status = '''        remember_ticket_number(
            db,
            conversation_id,
            ticket.ticket_number,
        )

        details = [
'''

    if (
        "remember_ticket_number(\n"
        "            db,\n"
        "            conversation_id,\n"
        "            ticket.ticket_number" not in bot_text
    ):
        if details_anchor not in bot_text:
            raise RuntimeError(
                "Could not find detailed status response block"
            )
        bot_text = bot_text.replace(
            details_anchor,
            remember_status,
            1,
        )

    # Remember the most recent ticket returned by "show my tickets".
    lines_anchor = "        lines = []\n"
    remember_list = '''        remember_ticket_number(
            db,
            conversation_id,
            tickets[0].ticket_number,
        )

        lines = []
'''

    if "tickets[0].ticket_number" not in bot_text:
        if lines_anchor not in bot_text:
            raise RuntimeError("Could not find ticket list lines block")
        bot_text = bot_text.replace(
            lines_anchor,
            remember_list,
            1,
        )

    # Add follow-up handlers before the normal ticket creation flow.
    flow_anchor = "    if not text:\n"

    follow_up_handlers = '''    if intent in (
        TeamsIntent.WHEN_CLOSED,
        TeamsIntent.WHO_ASSIGNED,
        TeamsIntent.LATEST_UPDATE,
    ):
        remembered_number = get_remembered_ticket_number(
            db,
            conversation_id,
        )

        if remembered_number is None:
            await send_teams_reply(
                db=db,
                ticket=_conversation_ticket(
                    conversation_id,
                    service_url,
                ),
                message=(
                    "Please reference a ticket first, for example: "
                    "'status of 1098'."
                ),
            )
            return {}

        remembered_ticket = (
            db.query(Ticket)
            .filter(
                Ticket.ticket_number == remembered_number,
                Ticket.conversation_id == conversation_id,
                Ticket.deleted_at.is_(None),
            )
            .first()
        )

        if not remembered_ticket:
            await send_teams_reply(
                db=db,
                ticket=_conversation_ticket(
                    conversation_id,
                    service_url,
                ),
                message=(
                    f"I could not find ticket #{remembered_number} "
                    f"in this Teams conversation."
                ),
            )
            return {}

        if intent == TeamsIntent.WHEN_CLOSED:
            closed_at = getattr(
                remembered_ticket,
                "resolved_at",
                None,
            )

            if closed_at:
                response_message = (
                    f"Ticket #{remembered_ticket.ticket_number} "
                    f"was resolved or closed on "
                    f"{closed_at:%d %b %Y %H:%M}."
                )
            else:
                status_value = getattr(
                    remembered_ticket.status,
                    "value",
                    str(remembered_ticket.status),
                )
                response_message = (
                    f"Ticket #{remembered_ticket.ticket_number} "
                    f"does not have a closure date recorded. "
                    f"Current status: {status_value}."
                )

        elif intent == TeamsIntent.WHO_ASSIGNED:
            assigned = getattr(
                remembered_ticket,
                "assigned_to",
                None,
            )
            assigned_text = (
                getattr(assigned, "value", str(assigned))
                if assigned
                else "Not yet assigned"
            )
            response_message = (
                f"Ticket #{remembered_ticket.ticket_number}\\n\\n"
                f"Assigned to: {assigned_text}"
            )

        else:
            latest_comment = (
                db.query(TicketComment)
                .filter(
                    TicketComment.ticket_id
                    == remembered_ticket.id
                )
                .order_by(
                    TicketComment.created_at.desc()
                )
                .first()
            )

            if latest_comment:
                updated_at = getattr(
                    latest_comment,
                    "created_at",
                    None,
                )
                updated_text = (
                    updated_at.strftime("%d %b %Y %H:%M")
                    if updated_at
                    else "Time not recorded"
                )
                response_message = (
                    f"Latest update on ticket "
                    f"#{remembered_ticket.ticket_number}:\\n\\n"
                    f"{latest_comment.message}\\n\\n"
                    f"Posted: {updated_text}"
                )
            else:
                response_message = (
                    f"Ticket #{remembered_ticket.ticket_number} "
                    f"does not have any comments yet. "
                    f"Last ticket update: "
                    f"{remembered_ticket.updated_at:%d %b %Y %H:%M}"
                )

        await send_teams_reply(
            db=db,
            ticket=remembered_ticket,
            message=response_message,
        )
        return {}

'''

    if "remembered_number = get_remembered_ticket_number" not in bot_text:
        if flow_anchor not in bot_text:
            raise RuntimeError(
                "Could not find normal ticket creation flow"
            )
        bot_text = bot_text.replace(
            flow_anchor,
            follow_up_handlers + flow_anchor,
            1,
        )

    # Remember newly created tickets.
    refresh_anchor = "    db.refresh(ticket)\n"
    remember_created = '''    db.refresh(ticket)

    remember_ticket_number(
        db,
        conversation_id,
        ticket.ticket_number,
    )
'''

    if "ticket.ticket_number,\n    )\n\n    try:" not in bot_text:
        if refresh_anchor not in bot_text:
            raise RuntimeError(
                "Could not find new-ticket refresh point"
            )
        bot_text = bot_text.replace(
            refresh_anchor,
            remember_created,
            1,
        )

    BOT.write_text(bot_text, encoding="utf-8")

    # ---------------------------------------------------------------
    # 4. Compile and verify
    # ---------------------------------------------------------------

    errors = []

    for path in (MEMORY, INTENTS, BOT):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            errors.append(
                f"Compile failed for {path}:\n"
                f"{result.stdout}{result.stderr}"
            )

    bot_check = BOT.read_text(encoding="utf-8")
    intent_check = INTENTS.read_text(encoding="utf-8")
    memory_check = MEMORY.read_text(encoding="utf-8")

    required_bot = [
        "get_remembered_ticket_number",
        "remember_ticket_number",
        "TeamsIntent.WHEN_CLOSED",
        "TeamsIntent.WHO_ASSIGNED",
        "TeamsIntent.LATEST_UPDATE",
        "latest_comment",
    ]

    for needle in required_bot:
        if needle not in bot_check:
            errors.append(f"Missing from teams_bot.py: {needle}")

    required_intents = [
        "WHEN_CLOSED",
        "WHO_ASSIGNED",
        "LATEST_UPDATE",
        "when_closed_phrases",
    ]

    for needle in required_intents:
        if needle not in intent_check:
            errors.append(
                f"Missing from teams_intent_service.py: {needle}"
            )

    if "teams_conversation_states" not in memory_check:
        errors.append("Conversation state table definition missing")

    if errors:
        raise RuntimeError("\n".join(errors))

except Exception as exc:
    shutil.copy2(bot_backup, BOT)
    shutil.copy2(intent_backup, INTENTS)

    if memory_existed and memory_backup:
        shutil.copy2(memory_backup, MEMORY)
    elif MEMORY.exists():
        MEMORY.unlink()

    print("[FAILED] Changes rolled back")
    print(exc)
    raise SystemExit(1)

print("[OK] Database-backed Teams conversation memory added")
print("[OK] Last ticket remembered after lookup, listing and creation")
print("[OK] 'When was it closed?' added")
print("[OK] 'Who is working on it?' added")
print("[OK] 'Latest update' added")
print("[OK] All modified files compile")
print(f"[OK] Bot backup: {bot_backup}")
print(f"[OK] Intent backup: {intent_backup}")
