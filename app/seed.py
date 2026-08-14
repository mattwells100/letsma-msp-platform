"""Populates the database with sample demo data so the portal isn't empty on first run."""
from datetime import datetime, timedelta

from app.database import SessionLocal, engine, Base
from app import models
from app.config import settings
from app.services.security import hash_password


def run():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(models.Customer).count() > 0:
            print("Seed data already present - skipping.")
            return

        admin = models.Technician(
            name="Matt Wells",
            email=settings.ADMIN_EMAIL,
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            role="Admin",
        )
        db.add(admin)

        acme = models.Customer(
            name="The Officers Mess",
            trading_name="The Officers Mess Ltd",
            address="1 Mess Lane, Caterham, Surrey",
            phone="+44 1883 000000",
            email="ops@officersmess.example",
            account_manager="Matt Wells",
            whatsapp_number="447700900123",
            m365_tenant_id="",  # fill with the customer's real Entra tenant ID to enable license sync
            status="Active",
        )
        mary = models.Customer(
            name="The Mary Woolstonecraft",
            trading_name="Mary Woolstonecraft Serviced Offices",
            address="12 Wollstonecraft Rd, London",
            phone="+44 20 7000 0000",
            email="admin@marywoolstonecraft.example",
            account_manager="Matt Wells",
            status="Active",
        )
        db.add_all([acme, mary])
        db.flush()

        contact = models.Contact(customer_id=acme.id, name="Amanda Bentley", email="amanda@officersmess.example",
                                  whatsapp_number="447700900123", role="Office Manager", is_primary=True)
        db.add(contact)
        db.flush()

        t1 = models.Ticket(
            ticket_number=1001,
            customer_id=acme.id, contact_id=contact.id,
            subject="Guest WiFi down in Reception", description="Guests reporting no internet since 9am.",
            priority=models.TicketPriority.HIGH, source=models.TicketSource.WHATSAPP,
            sla_due_at=datetime.utcnow() + timedelta(hours=4),
        )
        t2 = models.Ticket(
            ticket_number=1002,
            customer_id=mary.id,
            subject="New starter - needs M365 Business Standard license",
            description="Please assign a license and set up mailbox for new starter Jordan Pike.",
            priority=models.TicketPriority.NORMAL, source=models.TicketSource.TEAMS,
            sla_due_at=datetime.utcnow() + timedelta(hours=8),
        )
        db.add_all([t1, t2])

        inv = models.Invoice(customer_id=acme.id, currency="GBP", subtotal=250.0, tax_total=50.0, total=300.0,
                              due_date=datetime.utcnow() + timedelta(days=14), status=models.InvoiceStatus.DRAFT)
        db.add(inv)
        db.flush()
        db.add(models.InvoiceLineItem(invoice_id=inv.id, description="Monthly Helpdesk & Support (10 users)",
                                       quantity=1, unit_price=250.0))

        ep1 = models.Endpoint(customer_id=acme.id, hostname="OM-RECEPTION-PC", os_name="Windows 11 Pro",
                               agent_version="1.0.0", status=models.EndpointStatus.ONLINE, last_seen=datetime.utcnow())
        ep2 = models.Endpoint(customer_id=mary.id, hostname="MW-SERVER01", os_name="Windows Server 2022",
                               agent_version="1.0.0", status=models.EndpointStatus.WARNING,
                               last_seen=datetime.utcnow() - timedelta(minutes=5))
        db.add_all([ep1, ep2])

        db.commit()
        print("Seed data created.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
