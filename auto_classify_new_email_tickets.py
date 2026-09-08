from pathlib import Path
from datetime import datetime
import shutil

p = Path("app/services/email_ingestion_service.py")

text = p.read_text(encoding="utf-8")

backup = f"{p}.bak-auto-classify-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

marker = """
    processed = ProcessedEmail(
        graph_message_id=graph_message_id, sender_email=effective_email, subject=effective_subject,
        ticket_id=ticket.id, was_excluded=False,
        auto_reply_sent=False,  # updated below only if actually sent
    )
    db.add(processed)
    db.commit()
"""

insert = """
    processed = ProcessedEmail(
        graph_message_id=graph_message_id, sender_email=effective_email, subject=effective_subject,
        ticket_id=ticket.id, was_excluded=False,
        auto_reply_sent=False,  # updated below only if actually sent
    )
    db.add(processed)
    db.commit()

    # -------------------------------------------------
    # Automatic AI categorisation
    # -------------------------------------------------
    try:
        from app.routers.ai_assist import categorise_ticket

        await categorise_ticket(
            ticket_id=ticket.id,
            db=db,
        )

        print(
            f"AUTO_CLASSIFIED "
            f"ticket={ticket.ticket_number}"
        )

    except Exception as exc:
        print(
            f"AUTO_CLASSIFICATION_FAILED "
            f"ticket={ticket.ticket_number} "
            f"error={exc}"
        )
"""

if marker not in text:
    raise SystemExit(
        "Could not find insertion point"
    )

text = text.replace(marker, insert, 1)

p.write_text(text, encoding="utf-8")

print("[OK] Auto-classification patch applied")
print(f"[OK] Backup written: {backup}")