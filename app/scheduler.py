"""
app/scheduler.py

Runs scheduled background polling jobs using APScheduler (already listed
in requirements.txt). Started once from app/main.py on application startup.

Jobs:
  - helpdesk_mailbox_poll: polls helpdesk@letsma.co.uk, turns new emails
    into support tickets, sends auto-reply/confirmation emails to
    customers. Runs every 5 minutes. Gated on HELPDESK_GRAPH_CLIENT_ID -
    deliberately left unconfigured in production until you're confident
    it won't send unintended emails to real customers.
  - orders_mailbox_poll: polls orders@letsma.co.uk, turns new supplier
    order confirmation emails into draft (needs_review) AmazonOrder
    records. NEVER sends any email to anyone - purely internal record
    creation, landing in a human-review queue before anything is
    billable. Runs every 5 minutes. Gated on its OWN setting
    (ORDERS_EMAIL_INGEST_ENABLED), completely independent of the
    helpdesk job above - populating Graph credentials for one does NOT
    silently turn on the other.
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import SessionLocal
from app.services.email_ingestion_service import poll_and_process_helpdesk_inbox
from app.services.purchase_email_ingestion_service import poll_and_process_orders_inbox
from app.config import settings

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def _scheduled_helpdesk_poll_job():
    if not settings.HELPDESK_GRAPH_CLIENT_ID:
        return  # email-to-ticket not configured yet - skip silently rather than error every run
    db = SessionLocal()
    try:
        result = await poll_and_process_helpdesk_inbox(db)
        if result["messages_found"] > 0:
            logger.info(f"Helpdesk mailbox poll processed {result['messages_found']} email(s): {result['results']}")
    except Exception as e:
        logger.error(f"Helpdesk mailbox poll failed: {e}")
    finally:
        db.close()


async def _scheduled_orders_poll_job():
    # Deliberately independent of HELPDESK_GRAPH_CLIENT_ID / the helpdesk
    # job's enable check above. This job never sends any email to anyone
    # (it only reads the orders mailbox and creates internal draft
    # records), so it's safe to enable separately from - and without
    # ever risking triggering - the helpdesk auto-reply/confirmation
    # email feature.
    if not settings.ORDERS_EMAIL_INGEST_ENABLED:
        return
    if not settings.ORDERS_GRAPH_CLIENT_ID or not settings.ORDERS_GRAPH_TENANT_ID or not settings.ORDERS_GRAPH_CLIENT_SECRET:
        logger.warning(
            "orders_mailbox_poll is enabled (ORDERS_EMAIL_INGEST_ENABLED=true) but "
            "ORDERS_GRAPH_* credentials are not fully configured - skipping this run."
        )
        return
    db = SessionLocal()
    try:
        result = await poll_and_process_orders_inbox(db)
        if result["messages_found"] > 0:
            logger.info(f"Orders mailbox poll processed {result['messages_found']} email(s): {result['results']}")
    except Exception as e:
        logger.error(f"Orders mailbox poll failed: {e}")
    finally:
        db.close()


def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(_scheduled_helpdesk_poll_job, "interval", minutes=5, id="helpdesk_mailbox_poll")
        scheduler.add_job(_scheduled_orders_poll_job, "interval", minutes=5, id="orders_mailbox_poll")
        scheduler.start()
