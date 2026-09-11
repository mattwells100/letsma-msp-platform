from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.services.teams_ticket_state import TeamsTicketDraft, TicketDraftState
from app.services.teams_contact_resolution_service import (
    ContactResolutionStatus,
    resolve_contact,
)
from app.services.teams_ticket_state_service import teams_ticket_state_service


@dataclass(frozen=True)
class ContactCollectionResult:
    status: str
    message: str
    draft_state: str
    contact_id: str | None = None
    contact_name: str | None = None
    candidates: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "draft_state": self.draft_state,
            "contact_id": self.contact_id,
            "contact_name": self.contact_name,
            "candidates": self.candidates,
        }


def collect_contact(
    db: Session,
    draft: TeamsTicketDraft,
    contact_hint: str | None,
    *,
    candidate_limit: int = 5,
) -> ContactCollectionResult:
    if not draft.customer_id:
        draft.state = TicketDraftState.COLLECTING_CUSTOMER
        teams_ticket_state_service.save(draft)
        return ContactCollectionResult(
            status="customer_required",
            message="Which customer is this ticket for?",
            draft_state=draft.state.value,
        )

    resolution = resolve_contact(
        db=db,
        customer_id=draft.customer_id,
        contact_hint=contact_hint,
        limit=candidate_limit,
    )

    if resolution.status == ContactResolutionStatus.EMPTY:
        draft.state = TicketDraftState.COLLECTING_CONTACT
        teams_ticket_state_service.save(draft)
        return ContactCollectionResult(
            status="empty",
            message="Who is experiencing the issue? Give me a contact name or say 'general issue'.",
            draft_state=draft.state.value,
        )

    if resolution.status == ContactResolutionStatus.NOT_FOUND:
        draft.state = TicketDraftState.COLLECTING_CONTACT
        teams_ticket_state_service.save(draft)
        return ContactCollectionResult(
            status="not_found",
            message="I couldn't find that contact. Try another name or say 'general issue'.",
            draft_state=draft.state.value,
        )

    if resolution.status == ContactResolutionStatus.AMBIGUOUS:
        draft.state = TicketDraftState.COLLECTING_CONTACT
        teams_ticket_state_service.save(draft)
        candidates = [item.as_dict() for item in resolution.candidates]
        choices = []
        for index, item in enumerate(resolution.candidates, start=1):
            label = f"{index}. {item.name}"
            if item.email:
                label += f" ({item.email})"
            choices.append(label)
        message = "I found multiple matching contacts. Reply with the full name or email."
        if choices:
            message += "\n\n" + "\n".join(choices)
        return ContactCollectionResult(
            status="ambiguous",
            message=message,
            draft_state=draft.state.value,
            candidates=candidates,
        )

    if resolution.status == ContactResolutionStatus.GENERAL_ISSUE:
        draft.clear_contact()
        draft.state = TicketDraftState.COLLECTING_ISSUE
        teams_ticket_state_service.save(draft)
        return ContactCollectionResult(
            status="general_issue",
            message="Understood. This is a general issue. Please describe the problem.",
            draft_state=draft.state.value,
        )

    draft.contact_id = resolution.contact_id
    draft.contact_name = resolution.contact_name
    draft.state = TicketDraftState.COLLECTING_ISSUE
    teams_ticket_state_service.save(draft)

    return ContactCollectionResult(
        status="matched",
        message=f"Contact matched: {resolution.contact_name}. Please describe the issue.",
        draft_state=draft.state.value,
        contact_id=draft.contact_id,
        contact_name=draft.contact_name,
        candidates=[item.as_dict() for item in resolution.candidates],
    )
