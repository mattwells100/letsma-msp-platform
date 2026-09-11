from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
import unicodedata

from sqlalchemy.orm import Session

from app import models


class ContactResolutionStatus(str, Enum):

    MATCHED = "matched"

    AMBIGUOUS = "ambiguous"

    NOT_FOUND = "not_found"

    GENERAL_ISSUE = "general_issue"

    EMPTY = "empty"


GENERAL_ISSUE_TERMS = {
    "general issue",
    "company wide",
    "company-wide",
    "everyone",
    "all users",
    "multiple users",
}


@dataclass(frozen=True)
class ContactCandidate:

    contact_id: str

    name: str

    email: str | None = None

    score: int = 0

    def as_dict(self) -> dict:

        return {
            "contact_id": self.contact_id,
            "name": self.name,
            "email": self.email,
            "score": self.score,
        }


@dataclass(frozen=True)
class ContactResolution:

    status: ContactResolutionStatus

    query: str

    contact_id: str | None = None

    contact_name: str | None = None

    confidence: str | None = None

    candidates: list[ContactCandidate] = field(
        default_factory=list
    )

    @property
    def matched(self) -> bool:

        return (
            self.status
            == ContactResolutionStatus.MATCHED
        )


def normalise_contact_hint(
    value: str | None,
) -> str:

    if not value:
        return ""

    text = unicodedata.normalize(
        "NFKC",
        str(value),
    )

    text = text.strip().casefold()

    text = re.sub(
        r"[^a-z0-9@.]+",
        " ",
        text,
    )

    return " ".join(text.split())


def resolve_contact(
    db: Session,
    customer_id: str,
    contact_hint: str | None,
    *,
    limit: int = 5,
) -> ContactResolution:

    original = (
        contact_hint or ""
    ).strip()

    hint = normalise_contact_hint(
        original
    )

    if not hint:

        return ContactResolution(
            status=ContactResolutionStatus.EMPTY,
            query=original,
        )

    if hint in GENERAL_ISSUE_TERMS:

        return ContactResolution(
            status=ContactResolutionStatus.GENERAL_ISSUE,
            query=original,
        )

    contacts = (
        db.query(models.Contact)
        .filter(
            models.Contact.customer_id
            == customer_id
        )
        .all()
    )

    candidates: list[
        ContactCandidate
    ] = []

    for contact in contacts:

        name = normalise_contact_hint(
            getattr(contact, "name", "")
        )

        email = normalise_contact_hint(
            getattr(contact, "email", "")
        )

        score = 0

        if name == hint:

            score = 100

        elif email == hint:

            score = 100

        elif name.startswith(hint):

            score = 85

        elif hint in name:

            score = 70

        elif hint in email:

            score = 70

        if score:

            candidates.append(
                ContactCandidate(
                    contact_id=str(contact.id),
                    name=contact.name,
                    email=getattr(
                        contact,
                        "email",
                        None,
                    ),
                    score=score,
                )
            )

    candidates.sort(
        key=lambda item: (
            -item.score,
            item.name.casefold(),
        )
    )

    candidates = candidates[:limit]

    exact = [
        candidate
        for candidate in candidates
        if candidate.score >= 100
    ]

    if len(exact) == 1:

        match = exact[0]

        return ContactResolution(
            status=ContactResolutionStatus.MATCHED,
            query=original,
            contact_id=match.contact_id,
            contact_name=match.name,
            confidence="high",
            candidates=[match],
        )

    if len(candidates) == 1:

        match = candidates[0]

        return ContactResolution(
            status=ContactResolutionStatus.MATCHED,
            query=original,
            contact_id=match.contact_id,
            contact_name=match.name,
            confidence="medium",
            candidates=[match],
        )

    if candidates:

        return ContactResolution(
            status=ContactResolutionStatus.AMBIGUOUS,
            query=original,
            candidates=candidates,
        )

    return ContactResolution(
        status=ContactResolutionStatus.NOT_FOUND,
        query=original,
    )