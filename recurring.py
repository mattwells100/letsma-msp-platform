#!/usr/bin/env python3
"""
apply_recurring_invoicing.py  -  Letsma MSP Platform
------------------------------------------------------------------
Pulls ACTIVE recurring billing items into the monthly invoice run.

Run from the repo root (the folder containing `app/`):

    cd ~/Downloads/letsma-msp-platform/msp-app
    python apply_recurring_invoicing.py

What it changes (ONLY app/services/billing_service.py):
  * Adds date-advance helpers + RecurringBillingItem import.
  * Adds recurring items as invoice lines inside
    generate_monthly_invoice_for_customer (after the licence block).
  * Advances each billed item's next_invoice_date after the invoice
    is committed.

Safety:
  * Reuses your EXISTING per-customer/per-period idempotency guard
    (billing_period_start) - re-running the same month skips the whole
    customer, so next_invoice_date is never double-advanced.
  * Idempotent: safe to run twice (guarded by a marker check).
  * Backs up billing_service.py before editing.
  * Validates the result parses as Python before finishing.

NO database migration is required.
"""
import os, sys, shutil, datetime

APP = "app"
SVC = os.path.join(APP, "services", "billing_service.py")

if not os.path.isfile(SVC):
    print("ERROR: %s not found. cd into the repo root (msp-app) first." % SVC)
    sys.exit(1)

def read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write(p, c):
    with open(p, "w", encoding="utf-8") as f:
        f.write(c)

src = read(SVC)

if "RecurringBillingItem" in src:
    print("[skip] recurring invoicing already applied - nothing to do.")
    sys.exit(0)

# --- backup ---
bak = SVC + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(SVC, bak)
print("[backup] %s -> %s" % (SVC, bak))

# ------------------------------------------------------------------
# EDIT 1: import + date helpers, inserted right after the models import
# ------------------------------------------------------------------
IMPORT_ANCHOR = "    LicenseAssignment, LicensePrice, InvoiceStatus,\n)"
IMPORT_BLOCK = IMPORT_ANCHOR + '''
from app.models import RecurringBillingItem
import calendar as _rb_calendar


def _rb_add_months(d, n):
    """Add n months to a date, clamping the day to the target month's length."""
    idx = d.month - 1 + n
    year = d.year + idx // 12
    month = idx % 12 + 1
    day = min(d.day, _rb_calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


def _rb_advance(current, frequency, period_end):
    """
    Advance a recurring item's next_invoice_date forward by its frequency,
    rolling past period_end so a just-billed item is not billed again on the
    next run (handles overdue items that were multiple periods behind too).
    """
    step = {"MONTHLY": 1, "QUARTERLY": 3, "ANNUALLY": 12}.get(
        (frequency or "MONTHLY").upper(), 1
    )
    pe = period_end.date() if hasattr(period_end, "date") else period_end
    new_date = current
    # always advance at least once, then keep rolling until on/after period_end
    new_date = _rb_add_months(new_date, step)
    while new_date < pe:
        new_date = _rb_add_months(new_date, step)
    return new_date'''

if IMPORT_ANCHOR not in src:
    print("[ERROR] could not find the models import anchor. Aborting (no changes written).")
    sys.exit(1)
src = src.replace(IMPORT_ANCHOR, IMPORT_BLOCK, 1)

# ------------------------------------------------------------------
# EDIT 2: collect recurring items into line_items_data, just before the
#         "nothing to bill" check.
# ------------------------------------------------------------------
COLLECT_ANCHOR = "    if not line_items_data:\n        return None  # nothing to bill this customer this period"
COLLECT_BLOCK = '''    # Recurring billing items (Adobe, Exclaimer, domain renewals, etc.) that
    # are active and due on/before this period. sale_price is the ex-VAT sell.
    billed_recurring = []
    recurring_items = db.query(RecurringBillingItem).filter(
        RecurringBillingItem.customer_id == customer.id,
        RecurringBillingItem.is_active == True,
        RecurringBillingItem.next_invoice_date < period_end,
    ).all()
    for ri in recurring_items:
        line_items_data.append((
            ri.description,
            _round2(float(ri.quantity)),
            _round2(float(ri.sale_price)),
        ))
        billed_recurring.append(ri)

''' + COLLECT_ANCHOR

if COLLECT_ANCHOR not in src:
    print("[ERROR] could not find the 'nothing to bill' anchor. Aborting (no changes written).")
    sys.exit(1)
src = src.replace(COLLECT_ANCHOR, COLLECT_BLOCK, 1)

# ------------------------------------------------------------------
# EDIT 3: advance next_invoice_date after orders are marked billed,
#         just before db.commit().
# ------------------------------------------------------------------
ADVANCE_ANCHOR = "    for order in unbilled_orders:\n        order.invoiced = True\n        order.invoice_id = invoice.id"
ADVANCE_BLOCK = ADVANCE_ANCHOR + '''

    for ri in billed_recurring:
        ri.next_invoice_date = _rb_advance(ri.next_invoice_date, ri.billing_frequency, period_end)'''

if ADVANCE_ANCHOR not in src:
    print("[ERROR] could not find the order-billing anchor. Aborting (no changes written).")
    sys.exit(1)
src = src.replace(ADVANCE_ANCHOR, ADVANCE_BLOCK, 1)

# --- validate + write ---
import ast
try:
    ast.parse(src)
except SyntaxError as e:
    print("[ERROR] resulting file would not parse (%s). No changes written." % e)
    sys.exit(1)

write(SVC, src)
print("[ok] recurring items now included in the monthly invoice run.")
print("""
==================================================================
 DONE (no migration needed). Next steps:

   git add -A
   git commit -m "Include active recurring billing items in monthly invoice run"
   git checkout main && git pull origin main
   git merge add-email-to-ticket
   git push origin main
   git checkout add-email-to-ticket

 Test after deploy (pick a month with a due recurring item):
   - add an active recurring item to a test customer
   - POST /api/billing/generate-monthly-invoices?year=YYYY&month=MM
   - confirm the recurring line appears on that customer's invoice
   - confirm the item's Next Invoice date rolled forward
   - re-run the same month -> customer skipped, date NOT advanced again
==================================================================
""")
