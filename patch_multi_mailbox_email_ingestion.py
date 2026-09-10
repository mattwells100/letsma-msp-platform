#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime
import shutil
import py_compile

STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")

CONFIG = Path("app/config.py")
SERVICE = Path("app/services/email_ingestion_service.py")

for f in (CONFIG, SERVICE):
    backup = f"{f}.bak-{STAMP}"
    shutil.copy2(f, backup)
    print(f"[BACKUP] {backup}")

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

cfg = CONFIG.read_text(encoding="utf-8")

if "MATT_MAILBOX_ADDRESS" not in cfg:
    cfg = cfg.replace(
        'HELPDESK_MAILBOX_ADDRESS: str = os.getenv("HELPDESK_MAILBOX_ADDRESS", "helpdesk@letsma.co.uk")',
        '''HELPDESK_MAILBOX_ADDRESS: str = os.getenv("HELPDESK_MAILBOX_ADDRESS", "helpdesk@letsma.co.uk")
    MATT_MAILBOX_ADDRESS: str = os.getenv("MATT_MAILBOX_ADDRESS", "matt.wells@letsma.co.uk")
    CALLAN_MAILBOX_ADDRESS: str = os.getenv("CALLAN_MAILBOX_ADDRESS", "callan.allen@letsma.co.uk")'''
    )

CONFIG.write_text(cfg, encoding="utf-8")
print("[OK] mailbox settings added")

# --------------------------------------------------
# SERVICE
# --------------------------------------------------

svc = SERVICE.read_text(encoding="utf-8")

if "MONITORED_MAILBOXES" not in svc:

    marker = "# ---------------------------------------------------------------------------\n# Polling entry point"

    inject = '''
MONITORED_MAILBOXES = [
    settings.HELPDESK_MAILBOX_ADDRESS,
    settings.MATT_MAILBOX_ADDRESS,
    settings.CALLAN_MAILBOX_ADDRESS,
]

# ---------------------------------------------------------------------------
# Multi-mailbox polling entry point
'''

    svc = svc.replace(marker, inject + marker)

old_block = '''async def poll_and_process_helpdesk_inbox(db: Session) -> dict:'''

if old_block in svc:

    start = svc.find(old_block)

    replacement = '''
async def poll_and_process_helpdesk_inbox(db: Session) -> dict:
    token = await _get_helpdesk_app_token()

    all_results = []
    total_messages = 0

    async with httpx.AsyncClient() as client:

        for mailbox in MONITORED_MAILBOXES:

            resp = await client.get(
                f"{GRAPH_BASE}/users/{mailbox}/mailFolders/inbox/messages"
                f"?$top=50"
                f"&$select=id,subject,from,body,receivedDateTime,conversationId,isRead",
                headers={"Authorization": f"Bearer {token}"},
            )

            resp.raise_for_status()

            messages = [
                m for m in resp.json().get("value", [])
                if not m.get("isRead")
            ]

            total_messages += len(messages)

            for message in messages:

                result = await process_single_email(
                    db,
                    token,
                    message
                )

                result["mailbox"] = mailbox

                all_results.append(result)

    return {
        "messages_found": total_messages,
        "results": all_results,
    }
'''

    end_marker = "return {\"messages_found\": len(messages), \"results\": results}"
    if end_marker in svc:
        start2 = svc.find(old_block)
        end2 = svc.find(end_marker) + len(end_marker)
        svc = svc[:start2] + replacement + svc[end2:]

SERVICE.write_text(svc, encoding="utf-8")
print("[OK] service updated")

# --------------------------------------------------
# COMPILE
# --------------------------------------------------

failed = False

for f in (CONFIG, SERVICE):
    try:
        py_compile.compile(str(f), doraise=True)
        print(f"[COMPILE OK] {f}")
    except Exception as ex:
        failed = True
        print(f"[COMPILE FAIL] {f}: {ex}")

if failed:
    print("\\n[FAILED]")
else:
    print("\\n[SUCCESS] Multi-mailbox email ingestion installed")