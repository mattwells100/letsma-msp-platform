from __future__ import annotations

from dataclasses import dataclass
import re

from app.services.teams_ticket_state import TeamsTicketDraft, TicketDraftState
from app.services.teams_ticket_state_service import teams_ticket_state_service


@dataclass(frozen=True)
class IssueCollectionResult:
    status: str
    message: str
    draft_state: str
    subject: str | None = None
    description: str | None = None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "draft_state": self.draft_state,
            "subject": self.subject,
            "description": self.description,
        }


def build_ticket_subject(description: str, *, max_length: int = 120) -> str:
    text = " ".join((description or "").strip().split())
    text = re.sub(
        r"^(please\s+)?(create|log|raise|open)\s+(a\s+)?(new\s+)?(ticket|support request)\s*(for|about|regarding|:)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    if not text:
        return "Support request"
    sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip(" .")
    if len(sentence) <= max_length:
        return sentence
    shortened = sentence[: max_length - 1].rsplit(" ", 1)[0].strip()
    return (shortened or sentence[: max_length - 1]).rstrip(" .") + "…"


def collect_issue(draft: TeamsTicketDraft, issue_text: str | None) -> IssueCollectionResult:
    description = (issue_text or "").strip()
    if len(description) < 5:
        draft.state = TicketDraftState.COLLECTING_ISSUE
        teams_ticket_state_service.save(draft)
        return IssueCollectionResult(
            status="issue_required",
            message="Please describe the issue in a little more detail.",
            draft_state=draft.state.value,
        )

    draft.description = description
    draft.subject = build_ticket_subject(description)
    draft.state = TicketDraftState.CLASSIFYING
    teams_ticket_state_service.save(draft)
    return IssueCollectionResult(
        status="collected",
        message="Issue captured. I am preparing the ticket classification.",
        draft_state=draft.state.value,
        subject=draft.subject,
        description=draft.description,
    )
