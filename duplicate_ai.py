from pathlib import Path
from datetime import datetime
import shutil

p = Path("app/routers/ai_assist.py")

text = p.read_text(encoding="utf-8")

backup = f"{p}.bak-cleanup-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

duplicate = """
    # Persist classification on ticket

    ticket.category = suggestion.get("category")
    ticket.subcategory = suggestion.get("subcategory")
    ticket.estimated_minutes = suggestion.get("estimated_minutes")

    db.add(ticket)
    db.commit()
    db.refresh(ticket)
"""

if duplicate in text:
    text = text.replace(duplicate, "", 1)
    p.write_text(text, encoding="utf-8")
    print("[OK] Removed duplicate classification save block")
    print(f"[OK] Backup created: {backup}")
else:
    print("[WARN] Duplicate block not found")