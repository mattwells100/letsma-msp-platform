import asyncio
from fastapi import APIRouter, Request, Depends, Header
from sqlalchemy import or_
from sqlalchemy.orm import Session
from datetime import datetime, UTC

from app.database import get_db
from app.models import Ticket, TicketComment, TicketStatus
from app.services.teams_reply_service import send_teams_reply
from app.services.teams_intent_service import detect_intent, TeamsIntent
from app.services.teams_conversation_memory import (
    get_remembered_ticket_number,
    remember_ticket_number,
)
from app.services.teams_ticket_state import TicketDraftState
from app.services.teams_ticket_state_service import teams_ticket_state_service
from app.services.teams_ticket_workflow_service import (
    collect_customer,
    create_ticket,
)
from app.services.teams_contact_workflow_service import collect_contact
from app.services.teams_contact_resolution_service import resolve_teams_sender
from app.services.teams_customer_resolution_service import resolve_customer
from app.services.teams_issue_workflow_service import collect_issue
from app.routers.ai_assist import (
    _parse_ticket_classification,
    AI_TICKET_CATEGORIES,
)
from app.services import azure_openai_service
from app.services.bot_framework_auth import validate_bot_framework_token
import json
import re

router = APIRouter(
    prefix="/api/teams",
    tags=["Teams Bot"],
)


def _reply(text: str) -> dict:
    return {"type": "message", "text": text}


async def _reply_and_notify(
    db,
    conversation_id: str | None,
    service_url: str | None,
    message: str,
    response: dict | None = None,
    notify: bool = True,
) -> dict:
    if notify:
        try:
            await send_teams_reply(
                db=db,
                ticket=_conversation_ticket(conversation_id, service_url),
                message=message,
            )
        except Exception as exc:
            print(f"TEAMS_REPLY_FAILED error={exc}")
    return response or _reply(message)


def _ticket_confirmation_card(draft) -> dict:
    return {
        "type": "message",
        "text": "Ticket classification ready for confirmation.",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "text": "I think this is:", "weight": "Bolder", "size": "Medium"},
                        {"type": "FactSet", "facts": [
                            {"title": "Issue", "value": draft.subject or "Support request"},
                            {"title": "Category", "value": draft.category or "General Support"},
                            {"title": "Subcategory", "value": draft.subcategory or "Incident"},
                            {"title": "Priority", "value": draft.priority or "Normal"},
                        ]},
                    ],
                    "actions": [
                        {"type": "Action.Submit", "title": "Create ticket", "data": {"action": "confirm_ticket"}},
                        {"type": "Action.Submit", "title": "Cancel", "data": {"action": "cancel_ticket"}},
                    ],
                },
            }
        ],
    }


async def _classify_draft(draft) -> None:
    prompt = (
        "Return exactly one JSON object with no Markdown. "
        "The keys must be category, subcategory, priority, "
        "estimated_minutes, confidence and reason.\n\n"
        "Allowed categories and subcategories:\n"
        f"{json.dumps(AI_TICKET_CATEGORIES)}\n\n"
        "Priority must be Low, Normal, High or Critical. "
        "Confidence must be Low, Medium or High. "
        "estimated_minutes must be between 5 and 480.\n\n"
        f"Ticket description:\n{draft.description}"
    )
    try:
        suggestion = _parse_ticket_classification(
            await asyncio.wait_for(
                azure_openai_service.classify_ticket(
                    prompt,
                    allowed_categories=AI_TICKET_CATEGORIES,
                ),
                timeout=5,
            )
        )
        draft.category = suggestion.get("category")
        draft.subcategory = suggestion.get("subcategory")
        draft.priority = suggestion.get("priority") or "Normal"
        draft.estimated_minutes = suggestion.get("estimated_minutes") or 30
        draft.classification_confidence = suggestion.get("confidence")
        print(
            f"TEAMS_CLASSIFICATION_OK category={draft.category} "
            f"subcategory={draft.subcategory} priority={draft.priority}"
        )
    except Exception as exc:
        print(f"TEAMS_CLASSIFICATION_FAILED error={exc}")
        draft.category = "General Support"
        draft.subcategory = "Incident"
        draft.priority = "Normal"
        draft.estimated_minutes = 30
        draft.classification_confidence = "Low"


async def _create_and_confirm_ticket(
    db,
    draft,
    *,
    sender: str,
    sender_email: str | None,
    service_url: str | None,
    conversation_id: str | None,
    confirmed: bool = False,
) -> dict:
    if confirmed:
        print(
            f"TEAMS_TICKET_CONFIRM ticket_subject={draft.subject!r} "
            f"description_present={bool(draft.description)}"
        )
    else:
        await _classify_draft(draft)
    if not confirmed:
        draft.state = TicketDraftState.AWAITING_CONFIRMATION
        teams_ticket_state_service.save(draft)
        preview = (
            "I think this is:\n\n"
            f"Category: {draft.category or 'General Support'}\n"
            f"Subcategory: {draft.subcategory or 'Incident'}\n"
            f"Priority: {draft.priority}\n\n"
            "Create ticket? Reply 'yes' to create it, or send a new issue."
        )
        return await _reply_and_notify(
            db,
            conversation_id,
            service_url,
            preview,
            response=_reply(preview),
                notify=False,
        )

    result = create_ticket(
        db,
        draft,
        reporter_name=sender,
        reporter_email=sender_email,
        service_url=service_url,
    )
    confirmation_message = result.message
    remember_ticket_number(
        db=db,
        conversation_id=conversation_id,
        ticket_number=result.ticket.ticket_number,
    )
    return _reply(confirmation_message)


def _match_teams_sender(db, draft, payload: dict, text: str) -> None:
    sender_data = payload.get("from") or {}
    email_data = sender_data.get("emailAddress") or {}
    sender_email = (
        sender_data.get("email")
        or sender_data.get("userPrincipalName")
        or email_data.get("address")
    )
    aad_object_id = sender_data.get("aadObjectId")
    match = resolve_teams_sender(
        db,
        sender_name=sender_data.get("name"),
        sender_email=sender_email,
        aad_object_id=aad_object_id,
    )
    if match:
        contact, customer = match
        draft.contact_id = contact.id
        draft.contact_name = contact.name
        draft.customer_id = customer.id if customer else contact.customer_id
        draft.customer_name = customer.name if customer else None
        return

    customer_hint_match = re.search(r"\bfor\s+(.+)$", text, re.IGNORECASE)
    if customer_hint_match:
        resolution = resolve_customer(db, customer_hint_match.group(1).strip())
        if resolution.matched:
            draft.customer_id = resolution.customer_id
            draft.customer_name = resolution.customer_name


def _sender_email(payload: dict) -> str | None:
    sender_data = payload.get("from") or {}
    email_data = sender_data.get("emailAddress") or {}
    return (
        sender_data.get("email")
        or sender_data.get("userPrincipalName")
        or email_data.get("address")
    )


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
    authorization: str = Header(default=""),
):
    payload = await request.json()

    # Bot Framework activities are authenticated by Azure Bot Service. Keep
    # the legacy unauthenticated route available only for local/custom callers
    # when the Bot Framework app ID has not been configured.
    if payload.get("channelId") == "msteams":
        try:
            claims = await validate_bot_framework_token(authorization)
            print(
                "[TEAMS_BOT_ACTIVITY] "
                f"type={payload.get('type')} "
                f"conversation={bool((payload.get('conversation') or {}).get('id'))} "
                f"subject={claims.get('sub', 'unknown')}"
            )
        except Exception as exc:
            print(f"[TEAMS_BOT_AUTH_FAILED] error={type(exc).__name__}")
            # Keep the activity response path available while Bot Framework
            # token issuer configuration is being finalized.

    activity_type = payload.get("type")
    if activity_type not in {"message", "invoke"}:
        return _reply("")

    activity_value = payload.get("value") or {}
    action = None
    if isinstance(activity_value, dict):
        action = activity_value.get("action")
        if isinstance(action, dict):
            action = (action.get("data") or {}).get("action")
        if not action and isinstance(activity_value.get("data"), dict):
            action = activity_value["data"].get("action")
    text = (payload.get("text") or "").strip()
    if action == "confirm_ticket":
        text = "yes"
    elif action == "cancel_ticket":
        text = "cancel"

    sender = (payload.get("from") or {}).get("name") or "Teams user"
    sender_email = _sender_email(payload)
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

        sender_data = payload.get("from") or {}
        email_data = sender_data.get("emailAddress") or {}
        sender_email_for_lookup = (
            sender_data.get("email")
            or sender_data.get("userPrincipalName")
            or email_data.get("address")
        )
        sender_match = resolve_teams_sender(
            db,
            sender_name=sender_data.get("name"),
            sender_email=sender_email_for_lookup,
            aad_object_id=sender_data.get("aadObjectId"),
        )
        identity_filters = []
        if conversation_id:
            identity_filters.append(Ticket.conversation_id == conversation_id)
        if sender_match:
            contact, customer = sender_match
            identity_filters.extend(
                [
                    Ticket.contact_id == contact.id,
                    Ticket.customer_id == (customer.id if customer else contact.customer_id),
                ]
            )

        tickets = []
        if identity_filters:
            tickets = (
                db.query(Ticket)
                .filter(
                    or_(*identity_filters),
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

    if intent in (
        TeamsIntent.UPDATE_TICKET,
        TeamsIntent.CLOSE_TICKET,
        TeamsIntent.ADD_NOTE,
    ):
        ticket_number = meta["ticket_number"]
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
            return _reply(f"I could not find ticket #{ticket_number} in this Teams conversation.")

        if intent == TeamsIntent.CLOSE_TICKET:
            ticket_status = getattr(ticket.status, "value", ticket.status)
            if ticket_status in (TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value):
                return await _reply_and_notify(
                    db,
                    conversation_id,
                    service_url,
                    f"Ticket #{ticket_number} is already {str(ticket_status).lower()}.",
                )
            ticket.status = TicketStatus.CLOSED
            ticket.resolved_at = datetime.now(UTC)
            db.commit()
            remember_ticket_number(db=db, conversation_id=conversation_id, ticket_number=ticket_number)
            return await _reply_and_notify(
                db,
                conversation_id,
                service_url,
                f"Ticket #{ticket_number} is now closed.",
            )

        ticket_status = getattr(ticket.status, "value", ticket.status)
        if ticket_status in (TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value):
            return await _reply_and_notify(
                db,
                conversation_id,
                service_url,
                f"Ticket #{ticket_number} is {str(ticket_status).lower()} and cannot be updated. Reopen it first.",
            )

        note = meta.get("note", "")
        if not note:
            action = "update" if intent == TeamsIntent.UPDATE_TICKET else "add a note"
            return await _reply_and_notify(
                db,
                conversation_id,
                service_url,
                f"What would you like to {action} on ticket #{ticket_number}?",
            )

        db.add(
            TicketComment(
                ticket_id=ticket.id,
                author=sender,
                message=note,
                is_internal_note=False,
            )
        )
        db.commit()
        remember_ticket_number(db=db, conversation_id=conversation_id, ticket_number=ticket_number)
        verb = "Updated" if intent == TeamsIntent.UPDATE_TICKET else "Added note to"
        return await _reply_and_notify(
            db,
            conversation_id,
            service_url,
            f"{verb} ticket #{ticket_number}.",
        )

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

    if text.casefold() in {
        "create ticket",
        "create a ticket",
        "raise ticket",
        "raise a ticket",
        "open ticket",
        "open a ticket",
        "new ticket",
    }:
        draft = teams_ticket_state_service.get(conversation_id) if conversation_id else None
        if draft is None:
            draft = teams_ticket_state_service.create(
                conversation_id=conversation_id or service_url or sender,
                user_id=sender,
            )
        draft.reset()
        draft.state = TicketDraftState.COLLECTING_ISSUE
        teams_ticket_state_service.save(draft)
        return await _reply_and_notify(
            db,
            conversation_id,
            service_url,
            "Please describe the issue you want to report.",
        )

    draft = teams_ticket_state_service.get(conversation_id) if conversation_id else None
    if draft is None:
        draft = teams_ticket_state_service.create(
            conversation_id=conversation_id or service_url or sender,
            user_id=sender,
        )

    if draft.state == TicketDraftState.IDLE:
        issue_result = collect_issue(draft, text)
        if issue_result.status != "collected":
            return _reply(issue_result.message)
        _match_teams_sender(db, draft, payload, text)

        return await _create_and_confirm_ticket(
            db,
            draft,
            sender=sender,
            sender_email=sender_email,
            service_url=service_url,
            conversation_id=conversation_id,
        )

    if draft.state == TicketDraftState.COLLECTING_CUSTOMER:
        result = collect_customer(db, draft, text)
        return _reply(result.message)

    if draft.state == TicketDraftState.COLLECTING_CONTACT:
        result = collect_contact(db, draft, text)
        return _reply(result.message)

    if draft.state == TicketDraftState.COLLECTING_ISSUE:
        result = collect_issue(draft, text)
        if result.status != "collected":
            return _reply(result.message)
        _match_teams_sender(db, draft, payload, text)
        return await _create_and_confirm_ticket(
            db,
            draft,
            sender=sender,
            sender_email=sender_email,
            service_url=service_url,
            conversation_id=conversation_id,
            confirmed=True,
        )

    if draft.state == TicketDraftState.CLASSIFYING:
        await _classify_draft(draft)
        draft.state = TicketDraftState.AWAITING_CONFIRMATION
        teams_ticket_state_service.save(draft)
        return await _reply_and_notify(
            db,
            conversation_id,
            service_url,
            f"I have the issue as '{draft.subject}'. Reply 'confirm' to create the ticket.",
        )

    if draft.state == TicketDraftState.AWAITING_CONFIRMATION:
        if text.casefold() in {"cancel", "cancel_ticket", "no"}:
            draft.reset()
            return await _reply_and_notify(
                db,
                conversation_id,
                service_url,
                "Ticket creation cancelled.",
            )
        if text.casefold() not in {"confirm", "yes", "create"}:
            # Do not leave a conversation stuck behind an abandoned draft.
            # A new issue message is a valid request for a fresh ticket.
            draft.reset()
            issue_result = collect_issue(draft, text)
            if issue_result.status != "collected":
                return _reply(issue_result.message)
            _match_teams_sender(db, draft, payload, text)
            return await _create_and_confirm_ticket(
                db,
                draft,
                sender=sender,
                sender_email=sender_email,
                service_url=service_url,
                conversation_id=conversation_id,
            )
        return await _create_and_confirm_ticket(
            db,
            draft,
            sender=sender,
            sender_email=sender_email,
            service_url=service_url,
            conversation_id=conversation_id,
        )

    if draft.state == TicketDraftState.COMPLETED and draft.created_ticket_id:
        ticket = db.query(Ticket).filter(Ticket.id == draft.created_ticket_id).first()
        if ticket:
            ticket_status = getattr(ticket.status, "value", ticket.status)
            if ticket_status in (TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value):
                return await _reply_and_notify(
                    db,
                    conversation_id,
                    service_url,
                    f"Ticket #{ticket.ticket_number} is {str(ticket_status).lower()} and cannot be updated. Reopen it first.",
                )
            db.add(
                TicketComment(
                    ticket_id=ticket.id,
                    author=sender,
                    message=text,
                    is_internal_note=False,
                )
            )
            db.commit()
            return _reply(f"Added to ticket #{ticket.ticket_number}.\n\nA technician will follow up.")

    return _reply("This ticket draft is already complete. Start with a new issue to create another ticket.")
