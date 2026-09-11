from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.teams_ticket_state import (
    TeamsTicketDraft,
    TicketDraftState,
)

from app.services.teams_customer_resolution_service import (
    CustomerResolutionStatus,
    resolve_customer,
)

from app.services.teams_ticket_state_service import (
    teams_ticket_state_service,
)


@dataclass(frozen=True)
class CustomerCollectionResult:

    status: str
    message: str
    draft_state: str

    customer_id: str | None = None
    customer_name: str | None = None

    candidates: list[dict] = field(
        default_factory=list
    )

    def as_dict(self) -> dict:

        return {
            "status": self.status,
            "message": self.message,
            "draft_state": self.draft_state,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "candidates": self.candidates,
        }


def _save(
    draft: TeamsTicketDraft,
) -> None:

    teams_ticket_state_service.save(
        draft
    )


def collect_customer(
    db: Session,
    draft: TeamsTicketDraft,
    customer_hint: str | None,
    *,
    candidate_limit: int = 5,
) -> CustomerCollectionResult:

    resolution = resolve_customer(
        db=db,
        customer_hint=customer_hint,
        candidate_limit=candidate_limit,
    )

    if (
        resolution.status
        == CustomerResolutionStatus.EMPTY
    ):

        draft.state = (
            TicketDraftState.COLLECTING_CUSTOMER
        )

        _save(draft)

        return CustomerCollectionResult(
            status="empty",
            message=(
                "Which customer is this ticket for?"
            ),
            draft_state=draft.state.value,
        )

    if (
        resolution.status
        == CustomerResolutionStatus.NOT_FOUND
    ):

        draft.state = (
            TicketDraftState.COLLECTING_CUSTOMER
        )

        _save(draft)

        return CustomerCollectionResult(
            status="not_found",
            message=(
                "I couldn't find that customer. "
                "Please provide another name."
            ),
            draft_state=draft.state.value,
        )

    if (
        resolution.status
        == CustomerResolutionStatus.AMBIGUOUS
    ):

        draft.state = (
            TicketDraftState.COLLECTING_CUSTOMER
        )

        _save(draft)

        candidates = [
            item.as_dict()
            for item in resolution.candidates
        ]

        lines = []

        for index, item in enumerate(
            resolution.candidates,
            start=1,
        ):

            line = f"{index}. {item.name}"

            if item.trading_name:
                line += (
                    f" ({item.trading_name})"
                )

            lines.append(line)

        choices_text = "\n".join(lines)

        return CustomerCollectionResult(
            status="ambiguous",
            message=(
                "I found multiple matching "
                "customers.\n\n"
                "Reply with the number or "
                "full customer name.\n\n"
                f"{choices_text}"
            ),
            draft_state=draft.state.value,
            candidates=candidates,
        )

    previous_customer = draft.customer_id

    draft.customer_id = (
        resolution.customer_id
    )

    draft.customer_name = (
        resolution.customer_name
    )

    if previous_customer != draft.customer_id:

        draft.clear_contact()

    draft.state = (
        TicketDraftState.COLLECTING_CONTACT
    )

    _save(draft)

    return CustomerCollectionResult(
        status="matched",
        message=(
            f"Customer matched: "
            f"{resolution.customer_name}.\n\n"
            "Who is experiencing the issue?\n"
            "Provide a contact name or "
            "say 'general issue'."
        ),
        draft_state=draft.state.value,
        customer_id=draft.customer_id,
        customer_name=draft.customer_name,
        candidates=[
            item.as_dict()
            for item in resolution.candidates
        ],
    )