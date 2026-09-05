"""
app/services/billing_service.py

Generates one consolidated monthly Invoice per customer, combining:
  - Contract customers: a fixed monthly support fee line.
  - PAYG customers: a helpdesk labour line, summing all unbilled billable
    TimeEntry hours in the period (using each entry's rate override if
    set, otherwise the customer's payg_hourly_rate).
  - Both billing types: one line per unbilled purchase order assigned to
    the customer (from ANY supplier - Amazon, CDW, Ingram Micro, etc, via
    the general purchasing module), with the customer's amazon_markup_percent
    applied on top of the cost price.
  - Both billing types: a license line, if license_billing_mode is not
    "none" - either all currently-assigned licenses, or only the SKUs
    listed in licensed_skus_billed, priced via LicensePrice - preferring
    a price matching the customer's own license_term_commitment
    (monthly/annual), falling back to whichever term IS configured if
    only one exists. SKUs with no price configured anywhere are skipped
    with a warning rather than silently billed as zero.

All money values are rounded to 2 decimal places at the point each line
item is created, and the invoice's subtotal/tax/total are computed by
summing those already-rounded line amounts - this avoids floating-point
drift accumulating across many small lines.
"""
from datetime import datetime
from collections import defaultdict

from app.models import (
    Customer, Invoice, InvoiceLineItem, TimeEntry, AmazonOrder,
    LicenseAssignment, LicensePrice, InvoiceStatus,
)


def _round2(value: float) -> float:
    return round(value + 1e-9, 2)  # tiny epsilon guards against classic float repr issues, e.g. round(2.675, 2)


def _get_license_price(db, customer: Customer, sku_part_number: str):
    """
    Finds the best-matching monthly-equivalent sell price for a customer
    + SKU, preferring a price entered in the SAME commitment term as the
    customer's own license_term_commitment (annual-commitment pricing is
    typically discounted vs monthly, so these are genuinely different
    amounts) - customer-specific override (matching term) > customer
    override (other term) > global default (matching term) > global
    default (other term) > None if nothing is configured at all.

    This fallback chain means a SKU with only ONE price configured (the
    common case, and all data predating the monthly/annual term feature)
    continues to work exactly as before, regardless of what term any
    given customer is on.
    """
    customer_id = customer.id
    term = (customer.license_term_commitment or "monthly")
    other_term = "annual" if term == "monthly" else "monthly"

    row = db.query(LicensePrice).filter_by(
        customer_id=customer_id, sku_part_number=sku_part_number, price_term=term
    ).first()
    if row:
        return row.monthly_unit_price
    row = db.query(LicensePrice).filter_by(
        customer_id=customer_id, sku_part_number=sku_part_number, price_term=other_term
    ).first()
    if row:
        return row.monthly_unit_price

    row = db.query(LicensePrice).filter_by(
        customer_id=None, sku_part_number=sku_part_number, price_term=term
    ).first()
    if row:
        return row.monthly_unit_price
    row = db.query(LicensePrice).filter_by(
        customer_id=None, sku_part_number=sku_part_number, price_term=other_term
    ).first()
    if row:
        return row.monthly_unit_price
    return None  # no price configured anywhere - caller must handle (skip + warn)


def generate_monthly_invoice_for_customer(db, customer: Customer, period_start: datetime, period_end: datetime):
    """
    Builds (but does not push to Xero) one draft Invoice for the given
    customer covering [period_start, period_end). Returns a dict with the
    created Invoice and a list of human-readable warnings (e.g. "SKU X has
    no price configured, skipped") so the caller can surface them to the
    user rather than having costs silently go unbilled with no trace.

    Returns None (no invoice created) if there is nothing to bill - i.e.
    a PAYG customer with zero unbilled hours/purchases and no license
    billing configured. Contract customers always get an invoice (the
    support fee is due regardless of usage), unless the fee is exactly 0.

    Idempotency: if an invoice already exists for this customer with the
    exact same billing_period_start, this function returns None instead
    of creating a duplicate. This is essential for contract customers in
    particular - their monthly support fee line has no other "already
    billed" marker the way individual TimeEntry/purchase order rows do,
    so without this check, running the generator twice for the same
    month would double-bill the fixed fee.
    """
    already_generated = db.query(Invoice).filter_by(
        customer_id=customer.id, billing_period_start=period_start
    ).first()
    if already_generated:
        return None

    warnings = []
    line_items_data = []  # list of (description, quantity, unit_price) tuples

    if customer.billing_type == "contract":
        if customer.monthly_support_fee and customer.monthly_support_fee > 0:
            line_items_data.append((
                f"Monthly Support Fee - {period_start.strftime('%B %Y')}",
                1, _round2(customer.monthly_support_fee),
            ))
        unbilled_entries = []  # contract customers' time entries don't drive their invoice total
    else:  # payg
        unbilled_entries = db.query(TimeEntry).filter(
            TimeEntry.customer_id == customer.id,
            TimeEntry.billable == True,
            TimeEntry.invoiced == False,
            TimeEntry.work_date >= period_start,
            TimeEntry.work_date < period_end,
        ).all()
        total_hours = sum(e.hours for e in unbilled_entries)
        if total_hours > 0:
            # Entries may have different effective rates (per-entry override
            # vs the customer's default) - group by rate so each distinct
            # rate gets its own clean invoice line rather than one blended
            # (and harder to audit) average-rate line.
            hours_by_rate = defaultdict(float)
            for e in unbilled_entries:
                rate = e.hourly_rate_override if e.hourly_rate_override is not None else customer.payg_hourly_rate
                hours_by_rate[rate] += e.hours
            for rate, hours in hours_by_rate.items():
                line_items_data.append((
                    f"Helpdesk Labour - {period_start.strftime('%B %Y')} ({hours:g} hrs @ £{rate:.2f}/hr)",
                    _round2(hours), _round2(rate),
                ))

    # Purchase orders (any supplier - Amazon, CDW, Ingram Micro, manual entries, etc.)
    unbilled_orders = db.query(AmazonOrder).filter(
        AmazonOrder.customer_id == customer.id,
        AmazonOrder.invoiced == False,
        AmazonOrder.order_date >= period_start,
        AmazonOrder.order_date < period_end,
    ).all()
    markup_multiplier = 1 + (customer.amazon_markup_percent or 0) / 100
    for order in unbilled_orders:
        billed_price = _round2(order.total * markup_multiplier)
        desc = order.description or f"Order {order.amazon_order_id}"
        supplier_label = order.supplier or "Amazon"
        line_items_data.append((f"{supplier_label} purchase - {desc} (#{order.amazon_order_id})", 1, billed_price))

    if customer.license_billing_mode and customer.license_billing_mode != "none":
        assignments = db.query(LicenseAssignment).filter_by(customer_id=customer.id).all()
        counts_by_sku = defaultdict(int)
        friendly_names = {}
        for a in assignments:
            if customer.license_billing_mode == "selected":
                selected_skus = [s.strip() for s in (customer.licensed_skus_billed or "").split(",") if s.strip()]
                if a.sku_part_number not in selected_skus:
                    continue
            counts_by_sku[a.sku_part_number] += 1
            friendly_names[a.sku_part_number] = a.friendly_name or a.sku_part_number

        for sku, count in counts_by_sku.items():
            price = _get_license_price(db, customer, sku)
            if price is None:
                warnings.append(f"No price configured for licence SKU '{sku}' - skipped, not billed.")
                continue
            line_items_data.append((
                f"Microsoft 365 Licensing - {friendly_names[sku]} ({count} seat{'s' if count != 1 else ''})",
                count, _round2(price),
            ))

    if not line_items_data:
        return None  # nothing to bill this customer this period

    subtotal = _round2(sum(qty * unit_price for _, qty, unit_price in line_items_data))
    tax_total = _round2(subtotal * 0.20)
    total = _round2(subtotal + tax_total)

    invoice = Invoice(
        customer_id=customer.id,
        currency="GBP",
        subtotal=subtotal,
        tax_total=tax_total,
        total=total,
        issue_date=period_end,
        due_date=None,
        status=InvoiceStatus.DRAFT,
        billing_period_start=period_start,
        billing_period_end=period_end,
    )
    db.add(invoice)
    db.flush()  # get invoice.id before creating line items / marking entries billed

    for description, qty, unit_price in line_items_data:
        db.add(InvoiceLineItem(invoice_id=invoice.id, description=description, quantity=qty, unit_price=unit_price))

    for e in unbilled_entries:
        e.invoiced = True
        e.invoice_id = invoice.id

    for order in unbilled_orders:
        order.invoiced = True
        order.invoice_id = invoice.id

    db.commit()
    db.refresh(invoice)
    return {"invoice": invoice, "warnings": warnings}


def generate_monthly_invoices_for_all_customers(db, period_start: datetime, period_end: datetime):
    """Runs generate_monthly_invoice_for_customer for every active
    customer, returning a summary list so the caller can report what was
    created, what was skipped (nothing to bill), and any per-customer
    warnings."""
    results = []
    customers = db.query(Customer).filter_by(status="Active").all()
    for customer in customers:
        outcome = generate_monthly_invoice_for_customer(db, customer, period_start, period_end)
        if outcome is None:
            results.append({"customer": customer.name, "invoice_created": False, "warnings": []})
        else:
            results.append({
                "customer": customer.name,
                "invoice_created": True,
                "invoice_id": outcome["invoice"].id,
                "total": outcome["invoice"].total,
                "warnings": outcome["warnings"],
            })
    return results
