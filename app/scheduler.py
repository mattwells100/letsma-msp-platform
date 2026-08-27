"""
app/scheduler.py

Runs the helpdesk mailbox poll automatically every few minutes using
APScheduler (already listed in requirements.txt). Started once from
app/main.py on application startup.
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import SessionLocal
from app.services.email_ingestion_service import poll_and_process_helpdesk_inbox
from app.config import settings

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def _scheduled_poll_job():
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


def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(_scheduled_poll_job, "interval", minutes=5, id="helpdesk_mailbox_poll")
        scheduler.start()
