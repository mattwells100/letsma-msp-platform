
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Ticket


class EmailTicketIngestService:

    LOOKBACK_DAYS = 30

    def is_helpdesk_email(
        self,
        subject: str,
        body: str
    ) -> bool:
        """
        Placeholder AI filter.

        Replace with Azure OpenAI classification.
        """

        text = f"{subject} {body}".lower()

        helpdesk_keywords = [
            "outlook",
            "office",
            "microsoft 365",
            "password",
            "vpn",
            "sharepoint",
            "onedrive",
            "printer",
            "email issue",
            "cannot access",
            "can't access",
            "login issue",
            "helpdesk",
            "laptop",
            "computer",
        ]

        return any(
            word in text
            for word in helpdesk_keywords
        )

    def ticket_exists(
        self,
        db: Session,
        internet_message_id: str,
        conversation_id: str
    ):

        existing = (
            db.query(Ticket)
            .filter(
                Ticket.email_message_id == internet_message_id
            )
            .first()
        )

        if existing:
            return existing

        existing = (
            db.query(Ticket)
            .filter(
                Ticket.email_conversation_id == conversation_id
            )
            .first()
        )

        return existing

    def create_ticket_from_email(
        self,
        db: Session,
        customer_id,
        sender_email,
        subject,
        body,
        internet_message_id,
        conversation_id
    ):

        existing = self.ticket_exists(
            db,
            internet_message_id,
            conversation_id
        )

        if existing:
            return existing

        ticket = Ticket(
            subject=subject,
            description=body,
            source="Email",
            contact_email=sender_email,
            customer_id=customer_id,
            email_message_id=internet_message_id,
            email_conversation_id=conversation_id
        )

        db.add(ticket)
        db.commit()
        db.refresh(ticket)

        return ticket

    def process_message(
        self,
        db: Session,
        message
    ):

        subject = message.get("subject", "")
        body = message.get("body", "")

        if not self.is_helpdesk_email(
            subject,
            body
        ):
            return None

        return self.create_ticket_from_email(
            db=db,
            customer_id=None,
            sender_email=message.get(
                "sender_email"
            ),
            subject=subject,
            body=body,
            internet_message_id=message.get(
                "internet_message_id"
            ),
            conversation_id=message.get(
                "conversation_id"
            )
        )


service = EmailTicketIngestService()
