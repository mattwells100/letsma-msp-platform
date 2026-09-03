"""
app/scheduler.py

Runs scheduled background polling jobs using APScheduler (already listed
in requirements.txt). Started once from app/main.py on application startup.

Jobs:
  - helpdesk_mailbox_poll: polls helpdesk@letsma.co.uk, turns new emails
    into support tickets. Runs every 5 minutes.
  - orders_mailbox_poll: polls orders@letsma.co.uk, turns new supplier
    order confirmation emails into draft (needs_review) AmazonOrder
    records. Runs every 5 minutes.
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
    if not settings.HELPDESK_GRAPH_CLIENT_ID:
        # Purchasing email ingest currently reuses the helpdesk app
        # registration's credentials - skip silently if that isn't
        # configured yet, same convention as the helpdesk job above.
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
