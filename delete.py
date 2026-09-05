#!/usr/bin/env python3
"""
apply_delete_fixes.py  -  Letsma MSP Platform
------------------------------------------------------------------
Fixes two ForeignKeyViolation 500s when deleting:

  1. DELETE /api/billing/invoices/{id}   (app/routers/billing.py)
     - blocked by AmazonOrder.invoice_id and TimeEntry.invoice_id
       still referencing the invoice.
     - FIX: before deleting the invoice, "unbill" those children
       (invoiced=False, invoice_id=None) so the purchases/time
       entries go back into the unbilled pool. (InvoiceLineItems
       already cascade-delete.)

  2. DELETE /api/purchases/{order_id}     (app/routers/purchases.py)
     - blocked by ProcessedPurchaseEmail.order_id referencing the
       order.
     - FIX: delete the ProcessedPurchaseEmail dedup row(s) first,
       then delete the order. (Line items already cascade-delete.)
       NOTE: removing the dedup row means that supplier email can be
       re-ingested on the next poll - intended for clearing junk rows.

Run from the repo root (folder containing app/):

    cd ~/Downloads/letsma-msp-platform/msp-app
    python apply_delete_fixes.py

Safety: idempotent, backs up each file before editing, validates the
result parses as Python. NO database migration needed.
"""
import os, sys, shutil, datetime, ast

def edit(path, old, new, label):
    if not os.path.isfile(path):
        print("ERROR: %s not found. cd into the repo root first." % path)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if new.strip() in src:
        print("[skip] %s: already patched" % label)
        return

    if old not in src:
        print("[ERROR] %s: anchor not found - NOT modified." % label)
        print("        (Has the file changed since this script was written?)")
        sys.exit(1)

    if src.count(old) != 1:
        print("[ERROR] %s: anchor is not unique (%d matches) - NOT modified."
              % (label, src.count(old)))
        sys.exit(1)

    bak = path + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, bak)
    print("[backup] %s -> %s" % (path, bak))

    new_src = src.replace(old, new, 1)
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print("[ERROR] %s: result would not parse (%s). No changes written." % (label, e))
        sys.exit(1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_src)
    print("[ok] %s: patched" % label)


# ---------------------------------------------------------------
# 1. billing.py - unbill children before deleting the invoice
# ---------------------------------------------------------------
BILLING = os.path.join("app", "routers", "billing.py")
billing_old = '''    if invoice.xero_invoice_id:
        raise HTTPException(400, "Invoice already pushed to Xero - cannot discard here.")
    db.delete(invoice)
    db.commit()'''
billing_new = '''    if invoice.xero_invoice_id:
        raise HTTPException(400, "Invoice already pushed to Xero - cannot discard here.")
    # Unbill any children that reference this invoice so the FK constraints
    # don't block the delete - purchases/time entries return to the unbilled
    # pool rather than being destroyed. (InvoiceLineItems cascade-delete.)
    for order in db.query(models.AmazonOrder).filter_by(invoice_id=invoice.id).all():
        order.invoiced = False
        order.invoice_id = None
    for entry in db.query(models.TimeEntry).filter_by(invoice_id=invoice.id).all():
        entry.invoiced = False
        entry.invoice_id = None
    db.flush()
    db.delete(invoice)
    db.commit()'''

# ---------------------------------------------------------------
# 2. purchases.py - remove dedup email rows before deleting the order
# ---------------------------------------------------------------
PURCHASES = os.path.join("app", "routers", "purchases.py")
purchases_old = '''    if order.invoiced:
        raise HTTPException(400, "Cannot delete a purchase that has already been invoiced")
    db.delete(order)
    db.commit()'''
purchases_new = '''    if order.invoiced:
        raise HTTPException(400, "Cannot delete a purchase that has already been invoiced")
    # Remove the processed-email dedup row(s) that reference this order first,
    # otherwise the FK constraint blocks the delete. (Line items cascade.)
    # Note: clearing the dedup record means the source email can be
    # re-ingested on the next poll - intended for clearing junk rows.
    db.query(models.ProcessedPurchaseEmail).filter_by(order_id=order.id).delete()
    db.flush()
    db.delete(order)
    db.commit()'''

print("\n== 1/2  app/routers/billing.py ==")
edit(BILLING, billing_old, billing_new, "delete_invoice")

print("\n== 2/2  app/routers/purchases.py ==")
edit(PURCHASES, purchases_old, purchases_new, "delete_purchase")

print("""
==================================================================
 DONE (no migration needed). Next steps:

   git add app/routers/billing.py app/routers/purchases.py
   git commit -m "Fix delete FK violations: unbill invoice children; clear purchase dedup rows"
   git checkout main && git pull origin main
   git merge add-email-to-ticket
   git push origin main
   git checkout add-email-to-ticket

 After redeploy:
   - Discard a draft invoice with assigned purchases -> 200, and the
     purchases reappear as "Unbilled".
   - Delete the junk GBP 0.00 email-ingested purchase -> 200.
==================================================================
""")
