#!/usr/bin/env python3
"""
apply_ticket_soft_delete.py  -  Letsma MSP Platform
------------------------------------------------------------------
Adds SOFT DELETE for helpdesk tickets (preserves audit history):

  * models.py       -> Ticket.deleted_at (nullable; NULL = active)
  * admin_migrate.py-> migrate-ticket-soft-delete-schema endpoint
  * tickets.py      -> DELETE /api/tickets/{id} (stamps deleted_at)
                       + list_tickets hides soft-deleted tickets
  * portal.py       -> hide soft-deleted tickets from the Helpdesk
                       list, dashboard open-count, and customer detail
                       (best-effort: warns instead of aborting if an
                       anchor isn't found, so the core still applies)

Run from the repo root (folder containing app/):

    cd ~/Downloads/letsma-msp-platform/msp-app
    python apply_ticket_soft_delete.py

Then deploy and run the migration:

    curl -X POST \\
      https://letsma-msp-5122.azurewebsites.net/api/admin/migrate-ticket-soft-delete-schema \\
      -H "X-Agent-Key: $AGENT_KEY"

Safety: idempotent, backs up each file, validates Python parses.
"""
import os, sys, shutil, datetime, ast

def _read(p): 
    with open(p, "r", encoding="utf-8") as f: return f.read()
def _write(p, c):
    with open(p, "w", encoding="utf-8") as f: f.write(c)
def _backup(p):
    b = p + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, b); print("  [backup] %s -> %s" % (p, b))

def patch(path, old, new, label, marker, required=True):
    """Replace unique `old` with `new`. Skip if `marker` already present.
    If required and anchor missing/ambiguous -> abort. Else warn + continue."""
    if not os.path.isfile(path):
        print("  [ERROR] %s not found" % path); sys.exit(1)
    src = _read(path)
    if marker in src:
        print("  [skip]  %s: already patched" % label); return
    n = src.count(old)
    if n != 1:
        msg = "anchor %s (%d matches)" % ("not found" if n == 0 else "not unique", n)
        if required:
            print("  [ERROR] %s: %s - aborting." % (label, msg)); sys.exit(1)
        print("  [WARN]  %s: %s - skipped (non-critical)." % (label, msg)); return
    out = src.replace(old, new, 1)
    try: ast.parse(out)
    except SyntaxError as e:
        print("  [ERROR] %s: would not parse (%s) - not written." % (label, e)); sys.exit(1)
    _backup(path); _write(path, out); print("  [ok]    %s" % label)

def append(path, block, label, marker):
    if not os.path.isfile(path):
        print("  [ERROR] %s not found" % path); sys.exit(1)
    src = _read(path)
    if marker in src:
        print("  [skip]  %s: already present" % label); return
    out = src.rstrip() + "\n" + block
    try: ast.parse(out)
    except SyntaxError as e:
        print("  [ERROR] %s: would not parse (%s) - not written." % (label, e)); sys.exit(1)
    _backup(path); _write(path, out); print("  [ok]    %s" % label)

APP = "app"

# ---------------------------------------------------------------
print("\n== 1/4  app/models.py ==")
patch(
    os.path.join(APP, "models.py"),
    "    sla_due_at = Column(DateTime, nullable=True)",
    "    sla_due_at = Column(DateTime, nullable=True)\n"
    "    deleted_at = Column(DateTime, nullable=True)  # soft-delete marker; NULL = active",
    "Ticket.deleted_at",
    marker="deleted_at = Column(DateTime, nullable=True)  # soft-delete marker",
)

# ---------------------------------------------------------------
print("\n== 2/4  app/routers/admin_migrate.py ==")
MIG = '''

@router.post("/migrate-ticket-soft-delete-schema")
def migrate_ticket_soft_delete_schema(db: Session = Depends(get_db), _=Depends(_check_admin_key)):
    """Adds tickets.deleted_at for soft-deleting helpdesk tickets while
    preserving history. Safe to re-run."""
    db.execute(text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP"))
    db.commit()
    return {"status": "ok", "statements_run": 1}
'''
append(os.path.join(APP, "routers", "admin_migrate.py"), MIG,
       "migrate-ticket-soft-delete-schema", marker="migrate-ticket-soft-delete-schema")

# ---------------------------------------------------------------
print("\n== 3/4  app/routers/tickets.py ==")
# 3a. hide soft-deleted in the API list
patch(
    os.path.join(APP, "routers", "tickets.py"),
    "    q = db.query(models.Ticket)\n    if status:",
    "    q = db.query(models.Ticket).filter(models.Ticket.deleted_at.is_(None))\n    if status:",
    "list_tickets soft-delete filter",
    marker="db.query(models.Ticket).filter(models.Ticket.deleted_at.is_(None))",
)
# 3b. soft-delete endpoint
DEL = '''

@router.delete("/{ticket_id}")
def delete_ticket(ticket_id: str, db: Session = Depends(get_db)):
    """
    Soft-delete a helpdesk ticket: stamps deleted_at so it is hidden from
    all lists but preserved for audit/history (comments, time entries and
    any email-ingestion links are all kept intact). Re-runnable.
    """
    ticket = db.query(models.Ticket).get(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.deleted_at is None:
        ticket.deleted_at = datetime.utcnow()
        db.commit()
    return {"status": "ok", "deleted": ticket_id}
'''
append(os.path.join(APP, "routers", "tickets.py"), DEL,
       "delete_ticket endpoint", marker="def delete_ticket(")

# ---------------------------------------------------------------
print("\n== 4/4  app/routers/portal.py (best-effort filters) ==")
P = os.path.join(APP, "routers", "portal.py")
# 4a. dashboard open-tickets count
patch(P,
    '''        "open_tickets": db.query(models.Ticket).filter(
            models.Ticket.status.in_(["New", "In Progress", "Waiting on Customer"])
        ).count(),''',
    '''        "open_tickets": db.query(models.Ticket).filter(
            models.Ticket.status.in_(["New", "In Progress", "Waiting on Customer"])
        ).filter(models.Ticket.deleted_at.is_(None)).count(),''',
    "dashboard open_tickets filter",
    marker='.filter(models.Ticket.deleted_at.is_(None)).count()',
    required=False,
)
# 4b. dashboard recent_tickets
patch(P,
    "    recent_tickets = db.query(models.Ticket).order_by(models.Ticket.created_at.desc()).limit(8).all()",
    "    recent_tickets = db.query(models.Ticket).filter(models.Ticket.deleted_at.is_(None)).order_by(models.Ticket.created_at.desc()).limit(8).all()",
    "dashboard recent_tickets filter",
    marker="recent_tickets = db.query(models.Ticket).filter(models.Ticket.deleted_at.is_(None))",
    required=False,
)
# 4c. Helpdesk list page
patch(P,
    "    query = db.query(models.Ticket)\n    if unassigned_only:",
    "    query = db.query(models.Ticket).filter(models.Ticket.deleted_at.is_(None))\n    if unassigned_only:",
    "tickets_page list filter",
    marker="query = db.query(models.Ticket).filter(models.Ticket.deleted_at.is_(None))",
    required=False,
)
# 4d. unassigned_count on the Helpdesk page
patch(P,
    "    unassigned_count = db.query(models.Ticket).filter(models.Ticket.customer_id.is_(None)).count()",
    "    unassigned_count = db.query(models.Ticket).filter(models.Ticket.customer_id.is_(None)).filter(models.Ticket.deleted_at.is_(None)).count()",
    "tickets_page unassigned_count filter",
    marker="filter(models.Ticket.customer_id.is_(None)).filter(models.Ticket.deleted_at.is_(None))",
    required=False,
)
# 4e. customer detail tickets
patch(P,
    "    tickets = db.query(models.Ticket).filter_by(customer_id=customer_id).order_by(models.Ticket.created_at.desc()).all()",
    "    tickets = db.query(models.Ticket).filter_by(customer_id=customer_id).filter(models.Ticket.deleted_at.is_(None)).order_by(models.Ticket.created_at.desc()).all()",
    "customer_detail tickets filter",
    marker="filter_by(customer_id=customer_id).filter(models.Ticket.deleted_at.is_(None))",
    required=False,
)

print("""
==================================================================
 BACKEND DONE. Next:

   git add -A
   git commit -m "Add soft-delete for helpdesk tickets"
   git checkout main && git pull origin main
   git merge add-email-to-ticket
   git push origin main
   git checkout add-email-to-ticket

 Then run the migration (after redeploy):
   curl -X POST \\
     https://letsma-msp-5122.azurewebsites.net/api/admin/migrate-ticket-soft-delete-schema \\
     -H "X-Agent-Key: $AGENT_KEY"
   Expected: {"status":"ok","statements_run":1}

 UI button is added separately once you share the ticket template.
==================================================================
""")
