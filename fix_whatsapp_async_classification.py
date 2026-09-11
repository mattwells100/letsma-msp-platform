from pathlib import Path
from datetime import datetime
import py_compile
import shutil
import sys

SERVICE = Path("app/services/whatsapp_service.py")
ROUTER = Path("app/routers/webhooks_whatsapp.py")

FILES = [SERVICE, ROUTER]

for file_path in FILES:
    if not file_path.exists():
        print(f"[ERROR] Missing file: {file_path}")
        sys.exit(1)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backups = {}

for file_path in FILES:
    backup = Path(str(file_path) + f".bak-async-fix-{stamp}")
    shutil.copy2(file_path, backup)
    backups[file_path] = backup
    print(f"[BACKUP] {backup}")

try:
    service_text = SERVICE.read_text(encoding="utf-8")

    # --------------------------------------------------------------
    # 1. Make the WhatsApp payload handler asynchronous
    # --------------------------------------------------------------

    sync_signature = (
        "def handle_inbound_payload("
        "db: Session, payload: dict"
        ") -> list[tuple[Ticket, bool]]:"
    )

    async_signature = (
        "async def handle_inbound_payload("
        "db: Session, payload: dict"
        ") -> list[tuple[Ticket, bool]]:"
    )

    if sync_signature in service_text:
        service_text = service_text.replace(
            sync_signature,
            async_signature,
            1,
        )
        print("[OK] Converted handle_inbound_payload to async")
    elif async_signature in service_text:
        print("[OK] handle_inbound_payload is already async")
    else:
        raise RuntimeError(
            "Could not locate handle_inbound_payload function signature"
        )

    # --------------------------------------------------------------
    # 2. Replace asyncio.run(classify_ticket(...)) with await
    # --------------------------------------------------------------

    old_call = """raw_result = asyncio.run(
                            azure_openai_service.classify_ticket(
                                prompt,
                                allowed_categories=AI_TICKET_CATEGORIES,
                            )
                        )"""

    new_call = """raw_result = await azure_openai_service.classify_ticket(
                            prompt,
                            allowed_categories=AI_TICKET_CATEGORIES,
                        )"""

    if old_call in service_text:
        service_text = service_text.replace(old_call, new_call, 1)
        print("[OK] Replaced asyncio.run with await")
    elif (
        "raw_result = await azure_openai_service.classify_ticket("
        in service_text
    ):
        print("[OK] Classifier is already awaited")
    else:
        raise RuntimeError(
            "Could not locate the WhatsApp asyncio.run classification call"
        )

    # Remove asyncio import when no longer used elsewhere.
    remaining_asyncio_usage = service_text.count("asyncio.")

    if remaining_asyncio_usage == 0:
        service_text = service_text.replace("import asyncio\n", "")
        print("[OK] Removed unused asyncio import")

    SERVICE.write_text(service_text, encoding="utf-8")

    # --------------------------------------------------------------
    # 3. Make the webhook router await the async handler
    # --------------------------------------------------------------

    router_text = ROUTER.read_text(encoding="utf-8")

    call_variants = [
        (
            "results = whatsapp_service.handle_inbound_payload(db, payload)",
            "results = await whatsapp_service.handle_inbound_payload("
            "db, payload)",
        ),
        (
            "tickets = whatsapp_service.handle_inbound_payload(db, payload)",
            "tickets = await whatsapp_service.handle_inbound_payload("
            "db, payload)",
        ),
        (
            "result = whatsapp_service.handle_inbound_payload(db, payload)",
            "result = await whatsapp_service.handle_inbound_payload("
            "db, payload)",
        ),
        (
            "whatsapp_service.handle_inbound_payload(db, payload)",
            "await whatsapp_service.handle_inbound_payload(db, payload)",
        ),
    ]

    router_changed = False

    if "await whatsapp_service.handle_inbound_payload(" in router_text:
        print("[OK] Webhook router already awaits handler")
    else:
        for old, new in call_variants:
            if old in router_text:
                router_text = router_text.replace(old, new, 1)
                router_changed = True
                print("[OK] Updated webhook router to await handler")
                break

        if not router_changed:
            raise RuntimeError(
                "Could not locate handle_inbound_payload call in "
                "webhooks_whatsapp.py"
            )

    ROUTER.write_text(router_text, encoding="utf-8")

    # --------------------------------------------------------------
    # 4. Compile validation
    # --------------------------------------------------------------

    for file_path in FILES:
        py_compile.compile(str(file_path), doraise=True)
        print(f"[COMPILE OK] {file_path}")

    # --------------------------------------------------------------
    # 5. Import validation
    # --------------------------------------------------------------

    import app.main

    print("[IMPORT OK] app.main")

except Exception as exc:
    print(f"[FAILED] {exc}")
    print("[ROLLBACK] Restoring original files")

    for original, backup in backups.items():
        shutil.copy2(backup, original)
        print(f"[RESTORED] {original}")

    sys.exit(1)

print()
print("[SUCCESS] WhatsApp async classification flow repaired")
print()
print("Review:")
print("  git diff -- app/services/whatsapp_service.py")
print("  git diff -- app/routers/webhooks_whatsapp.py")
print()
print("Commit only the two application files:")
print("  git add app/services/whatsapp_service.py")
print("  git add app/routers/webhooks_whatsapp.py")
print(
    '  git commit -m "Fix async WhatsApp ticket classification"'
)
print("  git push")