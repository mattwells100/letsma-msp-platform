from pathlib import Path
from datetime import datetime
import shutil

p = Path("app/routers/tickets.py")

text = p.read_text(encoding="utf-8")

backup = f"{p}.bak-filter-fix-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

old = """    if customer_id:
        q = q.filter(models.Ticket.customer_id == customer_id)

    if unassigned_only:
        q = q.filter(models.Ticket.customer_id.is_(None))
"""

new = """    if customer_id:
        q = q.filter(models.Ticket.customer_id == customer_id)

    if category:
        q = q.filter(
            models.Ticket.category == category
        )

    if subcategory:
        q = q.filter(
            models.Ticket.subcategory.ilike(
                f"%{subcategory}%"
            )
        )

    if unclassified:
        q = q.filter(
            models.Ticket.category.is_(None)
        )

    if unassigned_only:
        q = q.filter(models.Ticket.customer_id.is_(None))
"""

if old not in text:
    print("FAILED: block not found")
    exit(1)

text = text.replace(old, new, 1)

p.write_text(text, encoding="utf-8")

print("[OK] Category filter logic inserted")
print(f"[OK] Backup: {backup}")