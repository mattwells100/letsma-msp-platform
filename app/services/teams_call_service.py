from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CallInteraction, Contact, Customer

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


@dataclass
class PhoneMatch:
    customer: Customer | None = None
    contact: Contact | None = None


def normalize_phone_number(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(character for character in str(raw) if character.isdigit())
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = "44" + digits[1:]
    return digits or None


def match_contact_by_phone(db: Session, phone_number: str | None) -> PhoneMatch:
    target = normalize_phone_number(phone_number)
    if not target:
        return PhoneMatch()

    contacts = db.query(Contact).all()
    for contact in contacts:
        for candidate in (contact.mobile_phone, contact.business_phone, contact.phone):
            if normalize_phone_number(candidate) == target:
                return PhoneMatch(customer=contact.customer, contact=contact)

    customers = db.query(Customer).all()
    for customer in customers:
        for candidate in (customer.phone, customer.mobile_phone, customer.whatsapp_number):
            if normalize_phone_number(candidate) == target:
                return PhoneMatch(customer=customer, contact=None)

    return PhoneMatch()


def _teams_calls_setting(name: str, fallback: str = "") -> str:
    return getattr(settings, f"TEAMS_CALLS_{name}", "") or getattr(settings, f"GRAPH_{name}", fallback)


def _graph_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason_phrase
    if isinstance(payload, dict):
        error = payload.get("error")
        description = payload.get("error_description")
        if isinstance(error, dict):
            return error.get("message") or str(error)
        if error and description:
            return f"{error}: {description}"
        if error:
            return str(error)
    return str(payload)


def _raise_graph_error(response: httpx.Response, context: str) -> None:
    if response.is_success:
        return
    detail = _graph_error_detail(response)
    raise ValueError(f"{context} failed ({response.status_code}): {detail}")


async def _get_teams_calls_token() -> str:
    tenant_id = _teams_calls_setting("TENANT_ID")
    client_id = _teams_calls_setting("CLIENT_ID")
    client_secret = _teams_calls_setting("CLIENT_SECRET")
    if not tenant_id or not client_id or not client_secret:
        raise ValueError("Teams call Graph credentials are not configured.")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        _raise_graph_error(response, "Teams calls token request")
        return response.json()["access_token"]


def _parse_graph_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _extract_phone(value: Any) -> str | None:
    if isinstance(value, dict):
        phone = value.get("phone") or value.get("phoneNumber") or value.get("telephoneNumber")
        if isinstance(phone, dict):
            return phone.get("id") or phone.get("number") or phone.get("displayName")
        if phone:
            return str(phone)
        identity = value.get("identity") or value.get("participant") or value.get("user")
        if identity is not value:
            return _extract_phone(identity)
        for child in value.values():
            found = _extract_phone(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _extract_phone(child)
            if found:
                return found
    return None


def _extract_participant_phones(record: dict[str, Any]) -> tuple[str | None, str | None]:
    caller = _extract_phone(record.get("caller") or record.get("organizer") or record.get("from"))
    callee = _extract_phone(record.get("callee") or record.get("to"))

    if caller and callee:
        return caller, callee

    participants = record.get("participants_v2") or record.get("participants") or []
    phones = []
    if isinstance(participants, dict):
        participants = participants.get("value", [])
    if isinstance(participants, list):
        for participant in participants:
            phone = _extract_phone(participant)
            if phone and phone not in phones:
                phones.append(phone)
    if not caller and phones:
        caller = phones[0]
    if not callee and len(phones) > 1:
        callee = phones[1]
    return caller, callee


def _call_times(record: dict[str, Any]) -> tuple[datetime | None, datetime | None, int]:
    start_time = _parse_graph_datetime(record.get("startDateTime"))
    end_time = _parse_graph_datetime(record.get("endDateTime"))
    duration = record.get("duration")
    if isinstance(duration, int):
        duration_seconds = duration
    elif isinstance(duration, str) and duration.isdigit():
        duration_seconds = int(duration)
    else:
        duration_seconds = 0
    if start_time and end_time:
        return start_time, end_time, max(0, int((end_time - start_time).total_seconds()))
    return start_time, end_time, duration_seconds


def _structure_call_record(record: dict[str, Any], db: Session) -> dict[str, Any]:
    caller_phone, callee_phone = _extract_participant_phones(record)
    caller_match = match_contact_by_phone(db, caller_phone)
    callee_match = match_contact_by_phone(db, callee_phone)
    start_time, end_time, duration_seconds = _call_times(record)

    if caller_match.customer:
        matched = caller_match
        direction = "inbound"
        phone_number = caller_phone
    elif callee_match.customer:
        matched = callee_match
        direction = "outbound"
        phone_number = callee_phone
    else:
        matched = PhoneMatch()
        direction = "unknown"
        phone_number = caller_phone or callee_phone

    return {
        "teams_call_id": str(record.get("id") or record.get("callId")),
        "customer_id": matched.customer.id if matched.customer else None,
        "contact_id": matched.contact.id if matched.contact else None,
        "phone_number": normalize_phone_number(phone_number) or phone_number,
        "direction": direction,
        "answered": duration_seconds > 0 and bool(end_time),
        "duration_seconds": duration_seconds,
        "start_time": start_time,
        "end_time": end_time,
    }


async def get_call_records(since: datetime | None = None) -> list[dict[str, Any]]:
    token = await _get_teams_calls_token()
    since = since or datetime.utcnow() - timedelta(minutes=15)
    until = datetime.utcnow()
    headers = {"Authorization": f"Bearer {token}"}
    records: list[dict[str, Any]] = []

    async with httpx.AsyncClient() as client:
        records.extend(await _fetch_graph_collection(client, _call_records_url(since), headers, "Teams call records request"))
        records.extend(await _fetch_graph_collection(client, _direct_routing_calls_url(since, until), headers, "Teams direct routing calls request"))

    return records


async def _fetch_graph_collection(client: httpx.AsyncClient, url: str, headers: dict[str, str], context: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    while url:
        response = await client.get(url, headers=headers)
        _raise_graph_error(response, context)
        payload = response.json()
        records.extend(payload.get("value", []))
        url = payload.get("@odata.nextLink")
    return records


def _call_records_url(since: datetime) -> str:
    filter_value = _graph_datetime_literal(since)
    return f"{GRAPH_BASE}/communications/callRecords?$filter=startDateTime ge {filter_value}"


def _direct_routing_calls_url(since: datetime, until: datetime) -> str:
    from_value = _graph_datetime_literal(since)
    to_value = _graph_datetime_literal(until)
    return f"{GRAPH_BASE}/communications/callRecords/getDirectRoutingCalls(fromDateTime={from_value},toDateTime={to_value})"


def _graph_datetime_literal(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat() + "Z"


def _normalise_call_record(record: dict[str, Any]) -> dict[str, Any]:
    if "callerNumber" not in record and "calleeNumber" not in record:
        return record
    normalised = dict(record)
    if not normalised.get("callId"):
        normalised["callId"] = f"direct-routing:{record.get('id') or record.get('correlationId')}"
    normalised["caller"] = {"phone": record.get("callerNumber")}
    normalised["callee"] = {"phone": record.get("calleeNumber")}
    return normalised


def _record_call_id(record: dict[str, Any]) -> str:
    return str(record.get("callId") or record.get("id") or "")


def assign_call_interaction(db: Session, call_id: str, customer_id: str, contact_id: str | None = None) -> CallInteraction:
    interaction = db.get(CallInteraction, call_id)
    if not interaction:
        raise ValueError("Call interaction not found")

    customer = db.get(Customer, customer_id)
    if not customer:
        raise ValueError("Customer not found")

    contact = None
    if contact_id:
        contact = db.query(Contact).filter_by(id=contact_id, customer_id=customer.id).first()
        if not contact:
            raise ValueError("Contact not found for selected customer")

    interaction.customer_id = customer.id
    interaction.contact_id = contact.id if contact else None
    db.commit()
    db.refresh(interaction)
    return interaction


def process_call_record(db: Session, record: dict[str, Any]) -> CallInteraction | None:
    record = _normalise_call_record(record)
    teams_call_id = _record_call_id(record)
    if not teams_call_id:
        return None
    existing = db.query(CallInteraction).filter_by(teams_call_id=teams_call_id).first()
    if existing:
        return existing

    data = _structure_call_record(record, db)
    interaction = CallInteraction(**data)
    db.add(interaction)
    db.commit()
    db.refresh(interaction)
    return interaction


async def sync_recent_calls(db: Session, since: datetime | None = None) -> dict[str, Any]:
    records = await get_call_records(since=since)
    created = 0
    skipped = 0
    interactions: list[CallInteraction] = []
    for record in records:
        normalised = _normalise_call_record(record)
        before = db.query(CallInteraction).filter_by(teams_call_id=_record_call_id(normalised)).first()
        interaction = process_call_record(db, normalised)
        if interaction:
            interactions.append(interaction)
        if before:
            skipped += 1
        elif interaction:
            created += 1
    return {"records_found": len(records), "created": created, "skipped_duplicates": skipped, "interaction_ids": [item.id for item in interactions]}