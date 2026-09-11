from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
import unicodedata

from sqlalchemy.orm import Session

from app import models


class CustomerResolutionStatus(str, Enum):
    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    EMPTY = "empty"


@dataclass(frozen=True)
class CustomerCandidate:
    customer_id: str
    name: str
    trading_name: str | None = None
    match_type: str = "candidate"
    score: int = 0

    def as_dict(self) -> dict:
        return {
            "customer_id": self.customer_id,
            "name": self.name,
            "trading_name": self.trading_name,
            "match_type": self.match_type,
            "score": self.score,
        }


@dataclass(frozen=True)
class CustomerResolution:
    status: CustomerResolutionStatus
    query: str
    customer_id: str | None = None
    customer_name: str | None = None
    match_type: str | None = None
    confidence: str | None = None
    candidates: list[CustomerCandidate] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return self.status == CustomerResolutionStatus.MATCHED

    def as_dict(self) -> dict:
        return {
            "status": self.status.value,
            "query": self.query,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "match_type": self.match_type,
            "confidence": self.confidence,
            "candidates": [item.as_dict() for item in self.candidates],
        }


def normalise_customer_hint(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def find_customer_candidates(
    db: Session,
    customer_hint: str | None,
    *,
    limit: int = 5,
) -> list[CustomerCandidate]:
    hint = normalise_customer_hint(customer_hint)
    if not hint:
        return []

    limit = max(1, min(int(limit), 20))
    customers = (
        db.query(models.Customer)
        .order_by(models.Customer.name.asc())
        .limit(500)
        .all()
    )

    ranked: dict[str, CustomerCandidate] = {}
    for customer in customers:
        names = [("name", customer.name)]
        if getattr(customer, "trading_name", None):
            names.append(("trading_name", customer.trading_name))

        best = None
        for field_name, raw_name in names:
            value = normalise_customer_hint(raw_name)
            if value == hint:
                score = 100 if field_name == "name" else 98
                match_type = f"exact_{field_name}"
            elif value.startswith(hint):
                score = 85 if field_name == "name" else 83
                match_type = f"prefix_{field_name}"
            elif hint in value:
                score = 70 if field_name == "name" else 68
                match_type = f"partial_{field_name}"
            else:
                continue

            candidate = CustomerCandidate(
                customer_id=str(customer.id),
                name=customer.name,
                trading_name=getattr(customer, "trading_name", None),
                match_type=match_type,
                score=score,
            )
            if best is None or candidate.score > best.score:
                best = candidate

        if best is not None:
            ranked[best.customer_id] = best

    return sorted(
        ranked.values(),
        key=lambda item: (-item.score, item.name.casefold()),
    )[:limit]


def resolve_customer(
    db: Session,
    customer_hint: str | None,
    *,
    candidate_limit: int = 5,
) -> CustomerResolution:
    original = (customer_hint or "").strip()
    if not normalise_customer_hint(original):
        return CustomerResolution(CustomerResolutionStatus.EMPTY, original)

    candidates = find_customer_candidates(db, original, limit=candidate_limit)
    if not candidates:
        return CustomerResolution(CustomerResolutionStatus.NOT_FOUND, original)

    exact = [item for item in candidates if item.score >= 98]
    if len(exact) == 1:
        match = exact[0]
        return CustomerResolution(
            status=CustomerResolutionStatus.MATCHED,
            query=original,
            customer_id=match.customer_id,
            customer_name=match.name,
            match_type=match.match_type,
            confidence="high",
            candidates=[match],
        )

    if len(candidates) == 1:
        match = candidates[0]
        return CustomerResolution(
            status=CustomerResolutionStatus.MATCHED,
            query=original,
            customer_id=match.customer_id,
            customer_name=match.name,
            match_type=match.match_type,
            confidence="medium",
            candidates=[match],
        )

    return CustomerResolution(
        status=CustomerResolutionStatus.AMBIGUOUS,
        query=original,
        confidence="low",
        candidates=candidates,
    )
