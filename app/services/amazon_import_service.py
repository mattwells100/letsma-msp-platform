"""
app/services/amazon_import_service.py  (NEW FILE)

Parses an Amazon Business order-history CSV export (Business Analytics ->
Orders report) into AmazonOrder + AmazonOrderLineItem records. Orders are
imported UNASSIGNED (customer_id = None) - a technician assigns each one
to the correct customer afterwards from the review screen.

Column names are matched flexibly (case-insensitive, several common
aliases) since Amazon Business lets you customise which columns appear
in an exported report, so exact naming can vary between exports. If a
required column can't be found at all, a clear error is raised naming
exactly which column is missing, rather than silently importing garbage
or crashing with a raw KeyError deep in the parsing loop.

Amazon Order IDs are globally unique, so re-importing the same CSV (or a
CSV with overlapping date ranges) is safe - any order ID already present
in the database is skipped rather than duplicated.
"""
import csv
import io
from datetime import datetime

from app.models import AmazonOrder, AmazonOrderLineItem

# Maps our internal field name -> list of acceptable column header aliases
# (checked case-insensitively). Add more aliases here if a real export
# uses different wording than expected.
COLUMN_ALIASES = {
    "order_id": ["order id", "order number", "amazon order id"],
    "order_date": ["order date", "date", "purchase date"],
    "item_name": ["item name", "product name", "title", "description"],
    "quantity": ["quantity", "qty", "item quantity"],
    "unit_price": ["unit price", "item price", "price per unit"],
    "total_owed": ["total owed", "item subtotal", "total charged", "item total"],
}


def _find_column(fieldnames, aliases):
    lower_fieldnames = {f.strip().lower(): f for f in fieldnames}
    for alias in aliases:
        if alias in lower_fieldnames:
            return lower_fieldnames[alias]
    return None


def _parse_amount(value: str) -> float:
    """Strips currency symbols/commas ('£45.99', '$1,234.50') and parses safely."""
    if not value:
        return 0.0
    cleaned = value.strip().replace("£", "").replace("$", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_date(value: str):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None  # unrecognised date format - order still imports, just with order_date=None


def import_amazon_orders_csv(db, csv_file_content: str) -> dict:
    """
    Parses the given CSV text and creates unassigned AmazonOrder +
    AmazonOrderLineItem records for every order not already present.
    Returns a summary dict: {"orders_created": int, "orders_skipped_duplicate": int,
    "line_items_created": int, "errors": [str, ...]}
    """
    reader = csv.DictReader(io.StringIO(csv_file_content))
    if not reader.fieldnames:
        return {"orders_created": 0, "orders_skipped_duplicate": 0, "line_items_created": 0,
                "errors": ["CSV file appears to be empty or has no header row."]}

    col_map = {}
    missing = []
    for field, aliases in COLUMN_ALIASES.items():
        found = _find_column(reader.fieldnames, aliases)
        if found:
            col_map[field] = found
        else:
            missing.append(f"'{field}' (expected one of: {', '.join(aliases)})")

    if missing:
        return {"orders_created": 0, "orders_skipped_duplicate": 0, "line_items_created": 0,
                "errors": [f"CSV is missing required column(s): {'; '.join(missing)}. "
                           f"Found columns: {', '.join(reader.fieldnames)}"]}

    # Group rows by order ID first (one order can have multiple line-item rows)
    orders_by_id = {}
    for row in reader:
        order_id = row.get(col_map["order_id"], "").strip()
        if not order_id:
            continue
        orders_by_id.setdefault(order_id, []).append(row)

    orders_created = 0
    orders_skipped = 0
    line_items_created = 0
    errors = []

    for order_id, rows in orders_by_id.items():
        existing = db.query(AmazonOrder).filter_by(amazon_order_id=order_id).first()
        if existing:
            orders_skipped += 1
            continue

        first_row = rows[0]
        order_date = _parse_date(first_row.get(col_map["order_date"], ""))

        line_items = []
        order_total = 0.0
        for row in rows:
            qty = _parse_amount(row.get(col_map["quantity"], "1") or "1")
            unit_price = _parse_amount(row.get(col_map["unit_price"], "0"))
            item_total = _parse_amount(row.get(col_map["total_owed"], "0")) or (qty * unit_price)
            order_total += item_total
            line_items.append({
                "description": row.get(col_map["item_name"], "").strip() or "Item",
                "quantity": qty or 1.0,
                "unit_price": unit_price,
            })

        summary_description = line_items[0]["description"] if len(line_items) == 1 else f"{len(line_items)} items"

        order = AmazonOrder(
            amazon_order_id=order_id,
            order_date=order_date,
            total=round(order_total, 2),
            description=summary_description,
            source="csv_import",
        )
        db.add(order)
        db.flush()

        for li in line_items:
            db.add(AmazonOrderLineItem(order_id=order.id, **li))
            line_items_created += 1

        orders_created += 1

    db.commit()
    return {
        "orders_created": orders_created,
        "orders_skipped_duplicate": orders_skipped,
        "line_items_created": line_items_created,
        "errors": errors,
    }
