from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Ticket, TicketComment, TicketSource
from app.services.ticket_numbering import next_ticket_number
from app.services.teams_intent_service import detect_intent, TeamsIntent
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

    intent, meta = detect_intent(text)

    if intent == TeamsIntent.HELP:
        return _reply(
            "I can help with:\n\n"
            "• Create a ticket\n"
            "• Show my tickets\n"
            "• Status of 1087\n"
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
                f"#{t.ticket_number} {t.subject}\n"
                f"Status: {t.status.value}"
            )

        return _reply(
            "Your recent tickets:\n\n"
            + "\n\n".join(lines)
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
            f"Ticket #{ticket.ticket_number}\n\n"
            f"Subject: {ticket.subject}\n"
            f"Status: {ticket.status.value}\n"
            f"Last updated: "
            f"{ticket.updated_at:%d %b %Y %H:%M}"
        )

    if not text:
        return _reply("Please enter a ticket description.")

    sender = (payload.get("from") or {}).get("name") or "Teams user"
    conversation_id = (payload.get("conversation") or {}).get("id")
    service_url = payload.get("serviceUrl")

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
            f"Added to ticket #{existing.ticket_number}.\n\n"
            f"A technician will follow up."
        )

    ticket = Ticket(
        ticket_number=next_ticket_number(db),
        subject=text[:100],
        description=text,
        source=TicketSource.TEAMS,
        reporter_name=sender,
        conversation_id=conversation_id,
        external_ref=service_url,
    )

    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    try:
        prompt = (
            "Return exactly one JSON object with no Markdown. "
            "The keys must be category, subcategory, priority, "
            "estimated_minutes, confidence and reason.\n\n"
            "Allowed categories and subcategories:\n"
            f"{json.dumps(AI_TICKET_CATEGORIES)}\n\n"
            "Priority must be Low, Normal, High or Critical. "
            "Confidence must be Low, Medium or High. "
            "estimated_minutes must be between 5 and 480. "
            "Use only the supplied ticket evidence and do not invent facts."
            "\n\n"
            f"Ticket description:\n{text}"
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
        f"\u2705 Ticket #{ticket.ticket_number} created",
        "",
        f"Category: {ticket.category or 'Pending'}",
        f"Subcategory: {ticket.subcategory or 'Pending'}",
        f"Estimated: {ticket.estimated_minutes or '-'} mins",
        "",
        "A technician will be in touch.",
    ]

    return _reply("\n".join(lines))
