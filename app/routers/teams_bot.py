from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Ticket, TicketComment, TicketSource
from app.services.ticket_numbering import next_ticket_number
from app.services.teams_reply_service import send_teams_reply
from app.services.teams_intent_service import detect_intent, TeamsIntent
from app.services.teams_conversation_memory import (
    get_remembered_ticket_number,
    remember_ticket_number,
)
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



@router.post("/messages")
async def receive_message(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await request.json()

    if payload.get("type") != "message":
        return _reply("")

    text = (payload.get("text") or "").strip()

    sender = (payload.get("from") or {}).get("name") or "Teams user"
    conversation_id = (payload.get("conversation") or {}).get("id")
    service_url = payload.get("serviceUrl")

    intent, meta = detect_intent(text)

    print(
        f"[TEAMS_INTENT] "
        f"intent={intent} "
        f"text={text!r} "
        f"meta={meta}"
    )

    if intent == TeamsIntent.HELP:
        print("[TEAMS_INTENT] HELP_TRIGGERED")

        await send_teams_reply(
            db=db,
            ticket=_conversation_ticket(
                conversation_id,
                service_url,
            ),
            message=(
                "I can help with:\n\n"
                "• Create a ticket\n"
                "• Show my tickets\n"
                "• Status of 1087\n"
                "• What's happening with ticket 1087?"
            ),
        )

        return {}

    if intent == TeamsIntent.SHOW_TICKETS:
        print("[TEAMS_INTENT] SHOW_TICKETS_TRIGGERED")

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

        # MEMORY_TICKET_LIST
        if tickets:
            remember_ticket_number(
                db=db,
                conversation_id=conversation_id,
                ticket_number=tickets[0].ticket_number,
            )

        lines = []

        for t in tickets:
            lines.append(
                f"#{t.ticket_number} {t.subject}\n"
                f"Status: {t.status.value}"
            )

        await send_teams_reply(
            db=db,
            ticket=_conversation_ticket(
                conversation_id,
                service_url,
            ),
            message=(
                "Your recent tickets:\n\n"
                + "\n\n".join(lines)
            ),
        )
        return {}


    if intent == TeamsIntent.GET_STATUS:
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

        # MEMORY_STATUS_LOOKUP
        remember_ticket_number(
            db=db,
            conversation_id=conversation_id,
            ticket_number=ticket.ticket_number,
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
            message="\n".join(details),
        )

        return {}

    # MEMORY_FOLLOW_UP_HANDLERS
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
                f"#{remembered_ticket.ticket_number}\n\n"
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
                    f"\n\n"
                    f"{latest_comment.message}"
                    f"\n\n"
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
                    f"\n\n"
                    f"Last ticket update: {updated_text}"
                )

        await send_teams_reply(
            db=db,
            ticket=remembered_ticket,
            message=response_message,
        )

        return {}

    if not text:
        return _reply("Please enter a ticket description.")

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

    # MEMORY_NEW_TICKET
    remember_ticket_number(
        db=db,
        conversation_id=conversation_id,
        ticket_number=ticket.ticket_number,
    )

    try:
        await send_teams_reply(
            db=db,
            ticket=ticket,
            message=(
                f"✅ Ticket #{ticket.ticket_number} Created\n\n"
                f"Issue:\n"
                f"{ticket.subject}\n\n"
                f"Status: New\n\n"
                f"You can ask:\n"
                f"• Show my tickets\n"
                f"• Status of {ticket.ticket_number}"
            ),
        )
    except Exception as ex:
        print(
            f"[TEAMS] Ticket created reply failed: {ex}"
        )

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
