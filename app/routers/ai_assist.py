"""
app/routers/ai_assist.py

AI-assisted helpdesk features, starting with drafting suggested ticket
replies via Azure OpenAI. Deliberately kept as a SEPARATE router from
tickets.py so this addition can't risk breaking anything already
working there.

IMPORTANT: this endpoint only ever RETURNS a suggested draft string - it
never creates a TicketComment, never sends anything to a customer, and
never modifies the ticket in any way. A technician must explicitly copy
the draft into a reply and submit it themselves via the existing
ticket-comment endpoint.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.services import azure_openai_service

router = APIRouter(prefix="/api/ai-assist", tags=["AI Assist"])

AI_TICKET_CATEGORIES = {
    "Microsoft 365": [
        "Outlook",
        "Exchange Online",
        "Teams",
        "SharePoint",
        "OneDrive",
        "Licence Management",
        "MFA and Authentication",
        "Entra ID",
        "Other",
    ],
    "Cyber Security": [
        "Microsoft Defender",
        "Phishing",
        "Malware",
        "Account Compromise",
        "Conditional Access",
        "Security Alert",
        "Other",
    ],
    "Device Support": [
        "Windows",
        "Mobile Device",
        "Printer",
        "Hardware",
        "Performance",
        "Updates",
        "Other",
    ],
    "Network": [
        "Internet",
        "Wi-Fi",
        "VPN",
        "DNS",
        "Firewall",
        "Other",
    ],
    "Backup and Recovery": [
        "Backup Failure",
        "File Restore",
        "Disaster Recovery",
        "Other",
    ],
    "Application Support": [
        "Line of Business Application",
        "Third-Party Application",
        "Installation",
        "Other",
    ],
    "User Administration": [
        "New User",
        "Leaver",
        "Password Reset",
        "Permissions",
        "Shared Mailbox",
        "Other",
    ],
    "Billing and Licensing": [
        "Invoice Query",
        "Licence Change",
        "Subscription",
        "Other",
    ],
    "General Support": [
        "How-To",
        "Service Request",
        "Incident",
        "Other",
    ],
}


def _parse_ticket_classification(raw_value: str) -> dict:
    cleaned = (raw_value or "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start < 0 or end <= start:
        preview = cleaned[:1000] if cleaned else "(empty response)"
        raise ValueError(
            f"AI response did not contain a JSON object. Raw response: {preview}"
        )

    value = json.loads(cleaned[start:end + 1])

    category = str(value.get("category", "")).strip()
    subcategory = str(value.get("subcategory", "")).strip()

    # Normalise common unicode hyphens returned by GPT
    category = (
        category
        .replace("‑", "-")
        .replace("–", "-")
        .replace("—", "-")
    )

    subcategory = (
        subcategory
        .replace("‑", "-")
        .replace("–", "-")
        .replace("—", "-")
    )

    priority = str(value.get("priority", "Normal")).strip()
    confidence = str(value.get("confidence", "Low")).strip()
    reason = str(value.get("reason", "")).strip()

    if category not in AI_TICKET_CATEGORIES:
        raise ValueError(f"Unsupported category: {category}")

    if subcategory not in AI_TICKET_CATEGORIES[category]:
        raise ValueError(
            f"Unsupported subcategory '{subcategory}' "
            f"for '{category}'"
        )

    if priority not in {"Low", "Normal", "High", "Critical"}:
        raise ValueError(f"Unsupported priority: {priority}")

    if confidence not in {"Low", "Medium", "High"}:
        raise ValueError(f"Unsupported confidence: {confidence}")

    try:
        minutes = int(value.get("estimated_minutes", 30))
    except (TypeError, ValueError):
        minutes = 30

    return {
        "category": category,
        "subcategory": subcategory,
        "priority": priority,
        "estimated_minutes": max(5, min(480, minutes)),
        "confidence": confidence,
        "reason": reason or "No reason supplied.",
    }



@router.post("/tickets/{ticket_id}/draft-reply")
async def draft_ticket_reply(ticket_id: str, db: Session = Depends(get_db)):
    ticket = db.query(models.Ticket).get(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    customer = db.query(models.Customer).get(ticket.customer_id)
    customer_name = customer.name if customer else "Unknown customer"

    comments = (
        db.query(models.TicketComment)
        .filter_by(ticket_id=ticket_id)
        .order_by(models.TicketComment.created_at.asc())
        .all()
    )
    comments_data = [
        {"author": c.author, "message": c.message, "is_internal_note": c.is_internal_note}
        for c in comments
    ]

    try:
        draft = await azure_openai_service.draft_ticket_reply(
            ticket_subject=ticket.subject,
            ticket_description=ticket.description,
            customer_name=customer_name,
            comments=comments_data,
        )
    except RuntimeError as e:
        # Azure OpenAI not configured yet - a clear, actionable message rather than a raw 500
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(502, f"Azure OpenAI request failed: {e}")

    return {"ticket_id": ticket_id, "draft_reply": draft}

@router.post("/tickets/{ticket_id}/suggest-fix")
async def suggest_ticket_fix(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """Return an AI-generated troubleshooting suggestion.

    This endpoint is advisory only. It does not modify the ticket,
    create a comment, or send anything to the customer.
    """
    ticket = db.query(models.Ticket).get(ticket_id)

    if not ticket:
        raise HTTPException(404, "Ticket not found")

    if ticket.deleted_at is not None:
        raise HTTPException(404, "Ticket not found")

    customer = (
        db.query(models.Customer).get(ticket.customer_id)
        if ticket.customer_id
        else None
    )
    customer_name = customer.name if customer else "Unknown customer"

    comments = (
        db.query(models.TicketComment)
        .filter_by(ticket_id=ticket_id)
        .order_by(models.TicketComment.created_at.asc())
        .all()
    )

    comments_data = [
        {
            "author": comment.author,
            "message": comment.message,
            "is_internal_note": comment.is_internal_note,
        }
        for comment in comments
    ]

    analysis_request = (
        "Act as a senior Microsoft 365 and MSP support engineer. "
        "Analyse this support issue and produce a practical suggested fix. "
        "Include these clearly labelled sections:\n"
        "Problem summary:\n"
        "Likely cause:\n"
        "Recommended checks:\n"
        "Recommended fix:\n"
        "Customer reply:\n"
        "Confidence: Low, Medium, or High\n\n"
        "Do not claim that diagnostic checks have already been performed. "
        "Do not invent passwords, licences, device details, tenant settings, "
        "or test results. Keep the customer reply professional and concise.\n\n"
        f"Original ticket description:\n{ticket.description or 'No description supplied.'}"
    )

    try:
        suggestion = await azure_openai_service.draft_ticket_reply(
            ticket_subject=f"Technical fix analysis: {ticket.subject}",
            ticket_description=analysis_request,
            customer_name=customer_name,
            comments=comments_data,
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(
            502,
            f"Azure OpenAI request failed: {exc}",
        )

    return {
        "success": True,
        "ticket_id": ticket_id,
        "suggestion": {
            "analysis": suggestion,
            "customer_reply": suggestion,
        },
    }

@router.post("/tickets/{ticket_id}/categorise")
async def categorise_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    """Return an advisory AI ticket classification."""
    ticket = db.query(models.Ticket).get(ticket_id)

    if not ticket or getattr(ticket, "deleted_at", None) is not None:
        raise HTTPException(404, "Ticket not found")

    customer = (
        db.query(models.Customer).get(ticket.customer_id)
        if ticket.customer_id
        else None
    )

    comments = (
        db.query(models.TicketComment)
        .filter_by(ticket_id=ticket_id)
        .order_by(models.TicketComment.created_at.asc())
        .all()
    )

    comments_data = [
        {
            "author": comment.author,
            "message": comment.message,
            "is_internal_note": comment.is_internal_note,
        }
        for comment in comments
    ]

    prompt = (
        "Return exactly one JSON object with no Markdown. "
        "The keys must be category, subcategory, priority, "
        "estimated_minutes, confidence and reason.\n\n"
        "Allowed categories and subcategories:\n"
        f"{json.dumps(AI_TICKET_CATEGORIES)}\n\n"
        "Priority must be Low, Normal, High or Critical. "
        "Confidence must be Low, Medium or High. "
        "estimated_minutes must be between 5 and 480. "
        "Use only the supplied ticket evidence and do not invent facts.\n\n"
        f"Ticket description:\n"
        f"{ticket.description or 'No description supplied.'}"
    )

    try:
        raw_result = await azure_openai_service.classify_ticket(
            prompt
        )
          

        suggestion = _parse_ticket_classification(raw_result)

    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            502,
            f"AI returned an invalid classification: {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            502,
            f"Azure OpenAI request failed: {exc}",
        )

    ticket.category = suggestion.get("category")
    ticket.subcategory = suggestion.get("subcategory")
    ticket.estimated_minutes = suggestion.get("estimated_minutes")

    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    return {
        "success": True,
        "ticket_id": ticket_id,
        "suggestion": suggestion,
    }

