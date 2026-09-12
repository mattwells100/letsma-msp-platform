from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from enum import Enum
from typing import Optional


class TicketDraftState(str, Enum):

    IDLE = "IDLE"

    COLLECTING_CUSTOMER = "COLLECTING_CUSTOMER"

    COLLECTING_CONTACT = "COLLECTING_CONTACT"

    COLLECTING_ISSUE = "COLLECTING_ISSUE"

    CLASSIFYING = "CLASSIFYING"

    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"

    CREATING = "CREATING"

    COMPLETED = "COMPLETED"

    CANCELLED = "CANCELLED"


@dataclass
class TeamsTicketDraft:

    conversation_id: str
    user_id: str

    state: TicketDraftState = TicketDraftState.IDLE

    intent: str = "create_ticket"

    customer_id: Optional[str] = None
    customer_name: Optional[str] = None

    contact_id: Optional[str] = None
    contact_name: Optional[str] = None

    subject: Optional[str] = None
    description: Optional[str] = None

    category: Optional[str] = None
    subcategory: Optional[str] = None

    priority: str = "Normal"

    estimated_minutes: int = 30

    classification_confidence: Optional[str] = None

    original_message: Optional[str] = None

    created_ticket_id: Optional[str] = None
    created_ticket_number: Optional[str] = None

    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    def touch(self) -> None:

        self.updated_at = datetime.now(UTC)

    def is_complete(self) -> bool:

        return self.state == TicketDraftState.COMPLETED

    def is_cancelled(self) -> bool:

        return self.state == TicketDraftState.CANCELLED

    def can_confirm(self) -> bool:

        return all(
            [
                self.subject,
                self.description,
            ]
        )

    def expires_at(self) -> datetime:

        return self.updated_at + timedelta(
            minutes=30
        )

    def is_expired(self) -> bool:

        return datetime.now(UTC) > self.expires_at()

    def clear_contact(self) -> None:

        self.contact_id = None
        self.contact_name = None

    def reset(self) -> None:

        self.state = TicketDraftState.IDLE

        self.customer_id = None
        self.customer_name = None

        self.contact_id = None
        self.contact_name = None

        self.subject = None
        self.description = None

        self.category = None
        self.subcategory = None

        self.priority = "Normal"

        self.estimated_minutes = 30

        self.classification_confidence = None

        self.created_ticket_id = None
        self.created_ticket_number = None

        self.touch()
