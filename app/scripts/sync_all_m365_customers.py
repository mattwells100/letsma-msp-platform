import asyncio
import logging
import sys
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import Customer
from app.services.graph_service import (
    sync_contacts_for_customer,
    sync_licenses_for_customer,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

logger = logging.getLogger("daily_m365_sync")


async def sync_customer(db, customer):
    customer_name = customer.name or customer.id

    result = {
        "customer": customer_name,
        "licences": None,
        "contacts": None,
        "errors": [],
    }

    logger.info("Starting Microsoft 365 sync for %s", customer_name)

    try:
        result["licences"] = await sync_licenses_for_customer(
            db,
            customer,
        )

        logger.info(
            "Licence sync completed for %s: %s",
            customer_name,
            result["licences"],
        )
    except Exception as exc:
        db.rollback()

        message = "Licence sync failed: " + str(exc)
        result["errors"].append(message)

        logger.exception(
            "Licence sync failed for %s",
            customer_name,
        )

    try:
        result["contacts"] = await sync_contacts_for_customer(
            db,
            customer,
        )

        logger.info(
            "Contact sync completed for %s: %s",
            customer_name,
            result["contacts"],
        )
    except Exception as exc:
        db.rollback()

        message = "Contact sync failed: " + str(exc)
        result["errors"].append(message)

        logger.exception(
            "Contact sync failed for %s",
            customer_name,
        )

    if result["errors"]:
        logger.error(
            "Microsoft 365 sync completed with errors for %s",
            customer_name,
        )
    else:
        logger.info(
            "Microsoft 365 sync completed successfully for %s",
            customer_name,
        )

    return result


async def main():
    started_at = datetime.now(timezone.utc)
    db = SessionLocal()

    try:
        customers = (
            db.query(Customer)
            .filter(Customer.m365_tenant_id.isnot(None))
            .filter(Customer.m365_tenant_id != "")
            .order_by(Customer.name)
            .all()
        )

        logger.info(
            "Daily Microsoft 365 sync started for %s customer(s)",
            len(customers),
        )

        results = []

        for customer in customers:
            result = await sync_customer(db, customer)
            results.append(result)

        successful = sum(
            1 for result in results if not result["errors"]
        )

        failed = len(results) - successful

        finished_at = datetime.now(timezone.utc)
        duration = finished_at - started_at

        logger.info(
            "Daily Microsoft 365 sync finished. "
            "Customers: %s, Successful: %s, Failed: %s, Duration: %s",
            len(results),
            successful,
            failed,
            duration,
        )

        if failed:
            sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())