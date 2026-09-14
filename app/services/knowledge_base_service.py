from datetime import datetime

from sqlalchemy.orm import Session

from app import models


def _first_public_resolution(ticket):
    if not getattr(ticket, "comments", None):
        return ""

    public_comments = [
        comment.message.strip()
        for comment in ticket.comments
        if not getattr(comment, "is_internal_note", False)
        and getattr(comment, "message", "").strip()
    ]
    if not public_comments:
        return ""
    return public_comments[-1]


def _summary_from_ticket(ticket):
    resolution = _first_public_resolution(ticket)
    if resolution:
        return resolution[:400]

    description = (getattr(ticket, "description", "") or "").strip()
    if description:
        return description[:400]
    return (getattr(ticket, "subject", "") or "").strip()


def upsert_knowledge_article(db: Session, ticket):
    if not ticket or not ticket.category or not ticket.subcategory:
        return None

    if not getattr(ticket, "customer_id", None):
        return None

    if getattr(ticket, "status", None) not in (
        models.TicketStatus.RESOLVED,
        models.TicketStatus.CLOSED,
    ):
        return None

    resolution = _first_public_resolution(ticket)
    if not resolution:
        return None

    title = f"{ticket.category}: {ticket.subcategory} fix"
    summary = _summary_from_ticket(ticket)

    article = (
        db.query(models.KnowledgeArticle)
        .filter_by(source_ticket_id=ticket.id)
        .first()
    )

    if article is None:
        article = models.KnowledgeArticle(
            customer_id=ticket.customer_id,
            source_ticket_id=ticket.id,
            category=ticket.category,
            subcategory=ticket.subcategory,
            title=title,
            summary=summary,
            resolution=resolution,
            confidence="Medium",
        )
        db.add(article)
    else:
        article.customer_id = ticket.customer_id
        article.category = ticket.category
        article.subcategory = ticket.subcategory
        article.title = title
        article.summary = summary
        article.resolution = resolution
        article.updated_at = datetime.utcnow()

    return article


def list_customer_knowledge_articles(db: Session, customer_id: str, limit: int = 5):
    if not customer_id:
        return []

    return (
        db.query(models.KnowledgeArticle)
        .filter_by(customer_id=customer_id)
        .order_by(models.KnowledgeArticle.updated_at.desc())
        .limit(limit)
        .all()
    )
