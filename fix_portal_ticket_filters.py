from pathlib import Path
from datetime import datetime
import shutil

p = Path("app/routers/portal.py")

txt = p.read_text(encoding="utf-8")

backup = f"{p}.bak-filter-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

# Replace route signature
old = """@router.get("/tickets")
def tickets_page(request: Request, unassigned_only: bool = False, db: Session = Depends(get_db), _=Depends(require_login_page)):
"""

new = """@router.get("/tickets")
def tickets_page(
    request: Request,
    category: str | None = None,
    subcategory: str | None = None,
    unclassified: bool = False,
    unassigned_only: bool = False,
    db: Session = Depends(get_db),
    _=Depends(require_login_page),
):
"""

txt = txt.replace(old, new)

# Replace query block
old = """    query = db.query(models.Ticket).filter(models.Ticket.deleted_at.is_(None))
    if unassigned_only:
        query = query.filter(models.Ticket.customer_id.is_(None))
"""

new = """    query = db.query(models.Ticket).filter(models.Ticket.deleted_at.is_(None))

    if category:
        query = query.filter(
            models.Ticket.category == category
        )

    if subcategory:
        query = query.filter(
            models.Ticket.subcategory.ilike(
                f"%{subcategory}%"
            )
        )

    if unclassified:
        query = query.filter(
            models.Ticket.category.is_(None)
        )

    if unassigned_only:
        query = query.filter(
            models.Ticket.customer_id.is_(None)
        )
"""

txt = txt.replace(old, new)

# Inject values into template context
old = """        "request": request, "tickets": tickets, "active_page": "tickets",
        "unassigned_only": unassigned_only, "unassigned_count": unassigned_count,
"""

new = """        "request": request,
        "tickets": tickets,
        "active_page": "tickets",
        "category": category,
        "subcategory": subcategory,
        "unclassified": unclassified,
        "unassigned_only": unassigned_only,
        "unassigned_count": unassigned_count,
"""

txt = txt.replace(old, new)

p.write_text(txt, encoding="utf-8")

print("[OK] Portal ticket filters wired up")
print(f"[OK] Backup created: {backup}")