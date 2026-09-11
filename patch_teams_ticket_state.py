# patch_teams_ticket_state.py

from pathlib import Path
from datetime import datetime
import shutil
import sys
import py_compile

FILES = {
    "app/services/teams_ticket_state.py": r'''
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
                self.customer_id,
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
''',

    "app/services/teams_ticket_state_service.py": r'''
from typing import Dict

from app.services.teams_ticket_state import (
    TeamsTicketDraft,
)


class TeamsTicketStateService:

    def __init__(self):

        self._drafts: Dict[
            str,
            TeamsTicketDraft
        ] = {}

    def get(
        self,
        conversation_id: str,
    ) -> TeamsTicketDraft | None:

        draft = self._drafts.get(
            conversation_id
        )

        if draft and draft.is_expired():

            self.clear(
                conversation_id
            )

            return None

        return draft

    def save(
        self,
        draft: TeamsTicketDraft,
    ) -> None:

        draft.touch()

        self._drafts[
            draft.conversation_id
        ] = draft

    def clear(
        self,
        conversation_id: str,
    ) -> None:

        self._drafts.pop(
            conversation_id,
            None,
        )

    def create(
        self,
        conversation_id: str,
        user_id: str,
    ) -> TeamsTicketDraft:

        draft = TeamsTicketDraft(
            conversation_id=conversation_id,
            user_id=user_id,
        )

        self.save(draft)

        return draft


teams_ticket_state_service = (
    TeamsTicketStateService()
)
'''
}

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

backups = []

for file_path, content in FILES.items():

    path = Path(file_path)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if path.exists():

        backup = Path(
            str(path)
            + f".bak-teams-state-{stamp}"
        )

        shutil.copy2(path, backup)

        backups.append(
            (path, backup)
        )

        print(
            f"Backup created: {backup}"
        )

    path.write_text(
        content.lstrip(),
        encoding="utf-8"
    )

try:

    py_compile.compile(
        "app/services/teams_ticket_state.py",
        doraise=True
    )

    py_compile.compile(
        "app/services/teams_ticket_state_service.py",
        doraise=True
    )

except Exception as exc:

    print()
    print("COMPILE FAILED")
    print(exc)

    for path, backup in backups:

        shutil.copy2(
            backup,
            path
        )

    print()
    print("Rollback complete")

    sys.exit(1)

print()
print("SUCCESS")
print()
print("Created:")
for file_path in FILES:
    print(" -", file_path)

print()
print("Validate:")
print("python -m py_compile app/services/teams_ticket_state.py")
print("python -m py_compile app/services/teams_ticket_state_service.py")
print('python -c "import app.main; print(\'IMPORT OK\')"')
