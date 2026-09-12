"""Shared new-user provisioning planning for Teams, WhatsApp, and email.

This module deliberately plans and validates provisioning without calling
Microsoft Graph or Vuzion. External side effects belong behind the validated
plan and explicit production credentials.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re


_NEW_USER_PATTERNS = (
    "new user",
    "new starter",
    "new employee",
    "new joiner",
    "onboard",
    "user account",
    "create an account",
    "create a user",
    "set up an account",
)


@dataclass(frozen=True)
class UserProvisioningRequest:
    channel: str
    customer_id: str | None
    customer_name: str | None
    full_name: str | None
    upn: str | None
    job_title: str | None
    department: str | None
    license_hint: str | None
    source_text: str
    sender: str | None = None

    @property
    def is_new_user_request(self) -> bool:
        text = self.source_text.casefold()
        return any(pattern in text for pattern in _NEW_USER_PATTERNS)


@dataclass(frozen=True)
class UserProvisioningPlan:
    request: UserProvisioningRequest
    tenant_id: str
    group_ids: tuple[str, ...]
    license_sku: str
    cloudblue_customer_id: str | None
    missing_fields: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready_for_execution(self) -> bool:
        return not self.missing_fields


def _find_value(text: str, labels: tuple[str, ...]) -> str | None:
    pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{pattern})\s*[:=-]\s*([^\n,;]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def build_request(
    *,
    channel: str,
    source_text: str,
    customer_id: str | None = None,
    customer_name: str | None = None,
    sender: str | None = None,
    full_name: str | None = None,
    upn: str | None = None,
    job_title: str | None = None,
    department: str | None = None,
    license_hint: str | None = None,
) -> UserProvisioningRequest:
    """Normalize explicit fields and common labelled values from any channel."""
    text = source_text or ""
    return UserProvisioningRequest(
        channel=channel.casefold(),
        customer_id=customer_id,
        customer_name=customer_name,
        full_name=full_name or _find_value(text, ("name", "full name")),
        upn=upn or _find_value(text, ("upn", "email", "username")),
        job_title=job_title or _find_value(text, ("job title", "title", "role")),
        department=department or _find_value(text, ("department", "team")),
        license_hint=license_hint or _find_value(text, ("license", "licence")),
        source_text=text,
        sender=sender,
    )


def build_plan(
    request: UserProvisioningRequest,
    *,
    customer_policy: dict,
) -> UserProvisioningPlan:
    """Validate customer-specific tenant, groups, and license policy."""
    missing = []
    if not request.is_new_user_request:
        missing.append("new_user_request")
    if not request.customer_id:
        missing.append("customer_id")
    if not request.full_name:
        missing.append("full_name")
    if not request.upn:
        missing.append("upn")
    if not request.job_title:
        missing.append("job_title")
    if not request.department:
        missing.append("department")

    tenant_id = customer_policy.get("tenant_id")
    if not tenant_id:
        missing.append("tenant_id")

    group_ids = tuple(customer_policy.get("group_ids") or ())
    if not group_ids:
        missing.append("group_ids")

    license_sku = customer_policy.get("license_sku") or request.license_hint
    if not license_sku:
        missing.append("license_sku")

    return UserProvisioningPlan(
        request=request,
        tenant_id=tenant_id or "",
        group_ids=group_ids,
        license_sku=license_sku or "",
        cloudblue_customer_id=customer_policy.get("cloudblue_customer_id"),
        missing_fields=tuple(dict.fromkeys(missing)),
    )
