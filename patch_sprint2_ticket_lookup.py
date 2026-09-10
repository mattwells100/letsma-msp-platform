#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime
import shutil
import re
import py_compile

STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")

ROOT = Path(".")

FILES = [
    Path("app/services/teams_classifier.py"),
    Path("app/routers/teams.py"),
]

for f in FILES:
    if f.exists():
        backup = f"{f}.bak-{STAMP}"
        shutil.copy2(f, backup)
        print(f"[BACKUP] {backup}")

# ------------------------------------------------------------------
# Create lookup service
# ------------------------------------------------------------------

lookup_service = Path("app/services/teams_ticket_lookup.py")

lookup_service.write_text(
'''from sqlalchemy.orm import Session

from app.models import Ticket


def get_ticket(ticket_id: int, db: Session):
    return (
        db.query(Ticket)
        .filter(Ticket.id == ticket_id)
        .first()
    )


def get_recent_user_tickets(
    email: str,
    db: Session,
    limit: int = 5,
):
    return (
        db.query(Ticket)
        .filter(Ticket.contact_email == email)
        .order_by(Ticket.updated_at.desc())
        .limit(limit)
        .all()
    )
''',
encoding="utf-8"
)

print("[OK] teams_ticket_lookup.py created")

# ------------------------------------------------------------------
# Extend classifier
# ------------------------------------------------------------------

classifier = Path("app/services/teams_classifier.py")

if classifier.exists():

    text = classifier.read_text(encoding="utf-8")

    if "LOOKUP_MY_TICKETS" not in text:

        text += '''

import re

def detect_lookup_intent(text: str):
    msg = text.lower().strip()

    if any(
        x in msg
        for x in [
            "show my tickets",
            "my tickets",
            "my open tickets",
        ]
    ):
        return {
            "intent": "lookup_my_tickets"
        }

    match = re.search(
        r"ticket\\s+#?(\\d+)",
        msg
    )

    if match:
        return {
            "intent": "lookup_ticket",
            "ticket_id": int(match.group(1))
        }

    return None
'''

        classifier.write_text(text, encoding="utf-8")

        print("[OK] classifier patched")

# ------------------------------------------------------------------
# Teams router import
# ------------------------------------------------------------------

router = Path("app/routers/teams.py")

if router.exists():

    text = router.read_text(encoding="utf-8")

    if "teams_ticket_lookup" not in text:

        text = (
            "from app.services.teams_ticket_lookup "
            "import get_ticket, get_recent_user_tickets\n"
            + text
        )

    router.write_text(text, encoding="utf-8")

    print("[OK] lookup imports added")

# ------------------------------------------------------------------
# Verification
# ------------------------------------------------------------------

required = [
    Path("app/services/teams_ticket_lookup.py"),
]

failed = False

for f in required:
    if not f.exists():
        failed = True
        print(f"[FAIL] Missing {f}")

# ------------------------------------------------------------------
# Compile
# ------------------------------------------------------------------

for f in [
    Path("app/services/teams_ticket_lookup.py"),
    Path("app/services/teams_classifier.py"),
]:
    if f.exists():
        try:
            py_compile.compile(
                str(f),
                doraise=True,
            )
            print(f"[COMPILE OK] {f}")
        except Exception as ex:
            failed = True
            print(f"[COMPILE FAIL] {f}: {ex}")

if failed:
    print("\\n[FAILED] Review output above")
else:
    print("\\n[SUCCESS] Sprint 2 lookup components installed")