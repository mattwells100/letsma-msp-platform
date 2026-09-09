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

new_source = '''from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Ticket, TicketComment, TicketSource
from app.services.ticket_numbering import next_ticket_number
from app.routers.ai_assist import (
    _parse_ticket_classification,
    AI_TICKET_CATEGORIES,
)
from app.services import azure_openai_service
import json

router = APIRouter(
    prefix="/api/teams",
    tags=["Teams Bot"],
)


def _reply(text: str) -> dict:
    return {"type": "message", "text": text}


@router.post("/messages")
async def receive_message(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await request.json()

    if payload.get("type") != "message":
        return _reply("")

    text = (payload.get("text") or "").strip()

    if not text:
        return _reply("Please enter a ticket description.")

    sender = (payload.get("from") or {}).get("name") or "Teams user"
    conversation_id = (payload.get("conversation") or {}).get("id")

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
        comment = TicketComment(
            ticket_id=existing.id,
            author=sender,
            message=text,
            is_internal_note=False,
        )
        db.add(comment)
        db.commit()

        return _reply(
            f"Added to ticket #{existing.ticket_number}.\\n\\n"
            f"A technician will follow up."
        )

    ticket = Ticket(
        ticket_number=next_ticket_number(db),
        subject=text[:100],
        description=text,
        source=TicketSource.TEAMS,
        reporter_name=sender,
        conversation_id=conversation_id,
    )

    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    try:
        prompt = (
            "Return exactly one JSON object with no Markdown. "
            "The keys must be category, subcategory, priority, "
            "estimated_minutes, confidence and reason.\\n\\n"
            "Allowed categories and subcategories:\\n"
            f"{json.dumps(AI_TICKET_CATEGORIES)}\\n\\n"
            "Priority must be Low, Normal, High or Critical. "
            "Confidence must be Low, Medium or High. "
            "estimated_minutes must be between 5 and 480. "
            "Use only the supplied ticket evidence and do not invent facts."
            "\\n\\n"
            f"Ticket description:\\n{text}"
        )

        raw_result = await azure_openai_service.classify_ticket(
            prompt,
            allowed_categories=AI_TICKET_CATEGORIES,
        )

        suggestion = _parse_ticket_classification(raw_result)

        ticket.category = suggestion.get("category")
        ticket.subcategory = suggestion.get("subcategory")
        ticket.estimated_minutes = suggestion.get("estimated_minutes")

        db.add(ticket)
        db.commit()
        db.refresh(ticket)

    except Exception as exc:
        print(
            "TEAMS_CLASSIFICATION_FAILED "
            f"ticket={ticket.ticket_number} error={exc}"
        )

    lines = [
        f"\\u2705 Ticket #{ticket.ticket_number} created",
        "",
        f"Category: {ticket.category or 'Pending'}",
        f"Subcategory: {ticket.subcategory or 'Pending'}",
        f"Estimated: {ticket.estimated_minutes or '-'} mins",
        "",
        "A technician will be in touch.",
    ]

    return _reply("\\n".join(lines))
'''

FILE.write_text(new_source, encoding="utf-8")

verify = FILE.read_text(encoding="utf-8")

checks = {
    'payload.get("type") != "message"': "message-type guard",
    "TicketComment": "duplicate-comment support",
    "conversation_id": "conversation threading",
    "TEAMS_CLASSIFICATION_FAILED": "concise failure logging",
    "classify_ticket(": "AI classifier call",
}

errors = [
    f"Missing expected content: {label}"
    for needle, label in checks.items()
    if needle not in verify
]

if 'print("=" * 80)' in verify:
    errors.append("Verbose debug logging still present")

result = subprocess.run(
    [sys.executable, "-m", "py_compile", str(FILE)],
    capture_output=True,
    text=True,
)
if result.returncode != 0:
    errors.append("Compilation failed:\n" + result.stdout + result.stderr)

if errors:
    shutil.copy2(backup, FILE)
    print("[FAILED] Rolled back automatically.")
    for e in errors:
        print(e)
    raise SystemExit(1)

print("[OK] Teams bot handler rebuilt")
print("[OK] Ignores non-message activities (typing / conversationUpdate)")
print("[OK] Threads follow-up messages into the existing ticket")
print("[OK] Stores conversation_id for duplicate protection")
print("[OK] Retains AI classification")
print("[OK] Reply now uses real line breaks")
print("[OK] Verbose debug logging removed")
print("[OK] Compiles successfully")
print(f"[OK] Backup: {backup}")
