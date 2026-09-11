from typing import Dict

from app.models.teams_ticket_state import (
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
