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
intents_backup = Path(f"{INTENTS}.bak-memory-{stamp}")

shutil.copy2(BOT, bot_backup)
shutil.copy2(INTENTS, intents_backup)

memory_existed = MEMORY.exists()
memory_backup = None

if memory_existed:
    memory_backup = Path(f"{MEMORY}.bak-memory-{stamp}")
    shutil.copy2(MEMORY, memory_backup)


def rollback(message: str) -> None:
    shutil.copy2(bot_backup, BOT)
    shutil.copy2(intents_backup, INTENTS)

    if memory_existed and memory_backup:
        shutil.copy2(memory_backup, MEMORY)
    elif MEMORY.exists():
        MEMORY.unlink()

    print("[FAILED] Changes rolled back")
    print(message)
    raise SystemExit(1)


try:
    # ===============================================================
    # 1. Conversation memory service
    # ===============================================================

    memory_code = '''"""Database-backed conversational memory for the Teams bot."""

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


metadata = MetaData()

teams_conversation_states = Table(
    "teams_conversation_states",
    metadata,
    Column("conversation_id", String(512), primary_key=True),
    Column("ticket_number", Integer, nullable=False),
    Column(
        "updated_at",
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    ),
)


def _ensure_table(db: Session) -> None:
    """Create the conversation state table if it does not exist."""
    metadata.create_all(
        bind=db.get_bind(),
        tables=[teams_conversation_states],
        checkfirst=True,
    )


def remember_ticket_number(
    db: Session,
    conversation_id: Optional[str],
    ticket_number: Optional[int],
) -> None:
    """Remember the most recently referenced ticket."""
    if not conversation_id or ticket_number is None:
        return

    _ensure_table(db)

    existing = db.execute(
        select(
            teams_conversation_states.c.conversation_id
        ).where(
            teams_conversation_states.c.conversation_id
            == conversation_id
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
    """Return the last ticket referenced in a Teams conversation."""
    if not conversation_id:
        return None

    _ensure_table(db)

    row = db.execute(
ect(
            teams_conversation_states.c.ticket_number
        ).where(
            teams_conversation_states.c.conversation_id
            == conversation_id
        )
    ).first()

    if not row:
        return None

    return int(row[0])
'''

    MEMORY.write_text(memory_code, encoding="utf-8")

    # ===============================================================
    # 2. Add new intents
    # ===============================================================

    intent_text = INTENTS.read_text(encoding="utf-8")

    if "WHEN_CLOSED" not in intent_text:
        enum_anchor = '    HELP = "HELP"\n'

        if enum_anchor not in intent_text:
            raise RuntimeError(
                "Could not locate HELP in TeamsIntent enum"
            )

        intent_text = intent_text.replace(
            enum_anchor,
            (
                '    HELP = "HELP"\n'
                '    WHEN_CLOSED = "WHEN_CLOSED"\n'
                '    WHO_ASSIGNED = "WHO_ASSIGNED"\n'
                '    LATEST_UPDATE = "LATEST_UPDATE"\n'
            ),
            1,
        )

    if "when_closed_phrases" not in intent_text:
        detection_anchor = (
            "    text_lower = text.lower().strip()\n"
        )

        if detection_anchor not in intent_text:
            raise RuntimeError(
                "Could not locate intent normalisation line"
            )

        detection_code = '''    text_lower = text.lower().strip()

    when_closed_phrases = (
        "when was it closed",
        "when did it close",
        "when was the ticket closed",
        "when was this closed",
        "what date was it closed",
    )

    if any(
        phrase in text_lower
        for phrase in when_closed_phrases
    ):
        return TeamsIntent.WHEN_CLOSED, {}

    assigned_phrases = (
        "who is working on it",
        "who's working on it",
        "who is assigned",
        "who is assigned to it",
        "who worked on it",
        "who owns it",
    )

    if any(
        phrase in text_lower
        for phrase in assigned_phrases
    ):
        return TeamsIntent.WHO_ASSIGNED, {}

    latest_update_phrases = (
        "latest update",
        "what is the latest update",
        "what's the latest update",
        "any update",
        "any updates",
        "what happened last",
    )

    if any(
        phrase in text_lower
        for phrase in latest_update_phrases
    ):
        return TeamsIntent.LATEST_UPDATE, {}
'''

        intent_text = intent_text.replace(
            detection_anchor,
            detection_code,
            1,
        )

    INTENTS.write_text(intent_text, encoding="utf-8")

    # ===============================================================
    # 3. Patch teams_bot.py imports
    # ===============================================================

    bot_text = BOT.read_text(encoding="utf-8")

    memory_import = '''from app.services.teams_conversation_memory import (
    get_remembered_ticket_number,
    remember_ticket_number,
)
'''

    if (
        "from app.services.teams_conversation_memory import"
        not in bot_text
    ):
        import_anchor = (
            "from app.services.teams_intent_service "
            "import detect_intent, TeamsIntent\n"
        )

        if import_anchor not in bot_text:
            raise RuntimeError(
                "Could not locate Teams intent import"
            )

        bot_text = bot_text.replace(
            import_anchor,
            import_anchor + memory_import,
            1,
        )

    # ===============================================================
    # 4. Remember explicit status lookups
    # ===============================================================

    if "MEMORY_STATUS_LOOKUP" not in bot_text:
        status_anchor = "        details = [\n"

        if status_anchor not in bot_text:
            raise RuntimeError(
                "Could not locate detailed status details list"
            )

        status_memory = '''        # MEMORY_STATUS_LOOKUP
        remember_ticket_number(
            db=db,
            conversation_id=conversation_id,
            ticket_number=ticket.ticket_number,
        )

        details = [
'''

        bot_text = bot_text.replace(
            status_anchor,
            status_memory,
            1,
        )

    # ===============================================================
    # 5. Remember the newest ticket from show-my-tickets
    # ===============================================================

    if "MEMORY_TICKET_LIST" not in bot_text:
        list_anchor = "        lines = []\n"

        if list_anchor not in bot_text:
            raise RuntimeError(
                "Could not locate show-my-tickets lines list"
            )

        list_memory = '''        # MEMORY_TICKET_LIST
        if tickets:
            remember_ticket_number(
                db=db,
                conversation_id=conversation_id,
                ticket_number=tickets[0].ticket_number,
            )

        lines = []
'''

        bot_text = bot_text.replace(
            list_anchor,
            list_memory,
            1,
        )

    # ===============================================================
    # 6. Add conversational follow-up handlers
    # ===============================================================

    if "MEMORY_FOLLOW_UP_HANDLERS" not in bot_text:
        flow_anchor = "    if not text:\n"

        if flow_anchor not in bot_text:
            raise RuntimeError(
                "Could not locate normal ticket creation flow"
            )

        follow_up_handlers = '''    # MEMORY_FOLLOW_UP_HANDLERS
    if intent in (
        TeamsIntent.WHEN_CLOSED,
        TeamsIntent.WHO_ASSIGNED,
        TeamsIntent.LATEST_UPDATE,
    ):
        remembered_number = get_remembered_ticket_number(
            db=db,
            conversation_id=conversation_id,
        )

        if remembered_number is None:
            await send_teams_reply(
                db=db,
                ticket=_conversation_ticket(
                    conversation_id,
                    service_url,
                ),
                message=(
                    "Please reference a ticket first, "
                    "for example: status of 1098."
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
                    f"I could not find ticket "
                    f"#{remembered_number} "
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
                    f"Ticket "
                    f"#{remembered_ticket.ticket_number} "
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
                    f"Ticket "
                    f"#{remembered_ticket.ticket_number} "
                    f"does not have a closure date recorded. "
                    f"Current status: {status_value}."
                )

        elif intent == TeamsIntent.WHO_ASSIGNED:
            assigned = getattr(
                remembered_ticket,
                "assigned_to",
                None,
            )

            if assigned:
                assigned_text = getattr(
                    assigned,
                    "value",
                    str(assigned),
                )
            else:
                assigned_text = "Not yet assigned"

            response_message = (
                f"Ticket "
                f"#{remembered_ticket.ticket_number}\\n\\n"
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
                comment_time = getattr(
                    latest_comment,
                    "created_at",
                    None,
                )

                if comment_time:
                    comment_time_text = (
                        comment_time.strftime(
                            "%d %b %Y %H:%M"
                        )
                    )
                else:
                    comment_time_text = (
                        "Time not recorded"
                    )

                response_message = (
                    f"Latest update on ticket "
                    f"#{remembered_ticket.ticket_number}:"
                    f"\\n\\n"
                    f"{latest_comment.message}"
                    f"\\n\\n"
                    f"Posted: {comment_time_text}"
                )
            else:
                updated_at = getattr(
                    remembered_ticket,
                    "updated_at",
                    None,
                )

                if updated_at:
                    updated_text = updated_at.strftime(
                        "%d %b %Y %H:%M"
                    )
                else:
                    updated_text = "Not recorded"

                response_message = (
                    f"Ticket "
                    f"#{remembered_ticket.ticket_number} "
                    f"does not have any comments yet."
                    f"\\n\\n"
                    f"Last ticket update: {updated_text}"
                )

        await send_teams_reply(
            db=db,
            ticket=remembered_ticket,
            message=response_message,
        )

        return {}

'''

        bot_text = bot_text.replace(
            flow_anchor,
            follow_up_handlers + flow_anchor,
            1,
        )

    # ===============================================================
    # 7. Remember newly created tickets
    # ===============================================================

    if "MEMORY_NEW_TICKET" not in bot_text:
        new_ticket_anchor = (
            "    db.refresh(ticket)\n"
        )

        if new_ticket_anchor not in bot_text:
            raise RuntimeError(
                "Could not locate new-ticket refresh"
            )

        new_ticket_memory = '''    db.refresh(ticket)

    # MEMORY_NEW_TICKET
    remember_ticket_number(
        db=db,
        conversation_id=conversation_id,
        ticket_number=ticket.ticket_number,
    )
'''

        bot_text = bot_text.replace(
            new_ticket_anchor,
            new_ticket_memory,
            1,
        )

    BOT.write_text(bot_text, encoding="utf-8")

    # ===============================================================
    # 8. Compile verification
    # ===============================================================

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

    memory_text = MEMORY.read_text(encoding="utf-8")
    intent_verify = INTENTS.read_text(encoding="utf-8")
    bot_verify = BOT.read_text(encoding="utf-8")

    required_memory = [
        "def remember_ticket_number(",
        "def get_remembered_ticket_number(",
        "return int(row[0])",
    ]

    required_intents = [
        'WHEN_CLOSED = "WHEN_CLOSED"',
        'WHO_ASSIGNED = "WHO_ASSIGNED"',
        'LATEST_UPDATE = "LATEST_UPDATE"',
        "when_closed_phrases",
    ]

    required_bot = [
        "MEMORY_STATUS_LOOKUP",
        "MEMORY_TICKET_LIST",
        "MEMORY_FOLLOW_UP_HANDLERS",
        "MEMORY_NEW_TICKET",
        "get_remembered_ticket_number",
    ]

    for needle in required_memory:
        if needle not in memory_text:
            errors.append(
                f"Missing from memory service: {needle}"
            )

    for needle in required_intents:
        if needle not in intent_verify:
            errors.append(
                f"Missing from intent service: {needle}"
            )

    for needle in required_bot:
        if needle not in bot_verify:
            errors.append(
                f"Missing from Teams bot: {needle}"
            )

    if errors:
        raise RuntimeError("\n".join(errors))

except Exception as exc:
    rollback(str(exc))

print("[OK] Database-backed Teams conversation memory added")
print("[OK] Explicit ticket status lookups are remembered")
print("[OK] Ticket listings remember the newest ticket")
print("[OK] Newly created tickets are remembered")
print("[OK] 'When was it closed?' added")
print("[OK] 'Who is working on it?' added")
print("[OK] 'Latest update' added")
print("[OK] All files compile")
print(f"[OK] Bot backup: {bot_backup}")
print(f"[OK] Intents backup: {intents_backup}")
