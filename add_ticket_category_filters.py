from pathlib import Path
from datetime import datetime
import shutil

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

# =====================================================
# Patch tickets API
# =====================================================

api_file = Path("app/routers/tickets.py")

text = api_file.read_text(encoding="utf-8")
shutil.copy2(api_file, f"{api_file}.bak-{stamp}")

old = """def list_tickets(
    status: Optional[str] = None,
    customer_id: Optional[str] = None,
    unassigned_only: bool = False,
    db: Session = Depends(get_db),
):"""

new = """def list_tickets(
    status: Optional[str] = None,
    customer_id: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    unclassified: bool = False,
    unassigned_only: bool = False,
    db: Session = Depends(get_db),
):"""

if old in text:
    text = text.replace(old, new, 1)

old = """    if customer_id:
        q = q.filter(models.Ticket.customer_id == customer_id)

    if unassigned_only:
        q = q.filter(models.Ticket.customer_id.is_(None))
"""

new = """    if customer_id:
        q = q.filter(models.Ticket.customer_id == customer_id)

    if category:
        q = q.filter(models.Ticket.category == category)

    if subcategory:
        q = q.filter(models.Ticket.subcategory.ilike(f"%{subcategory}%"))

    if unclassified:
        q = q.filter(models.Ticket.category.is_(None))

    if unassigned_only:
        q = q.filter(models.Ticket.customer_id.is_(None))
"""

if old in text:
    text = text.replace(old, new, 1)

api_file.write_text(text, encoding="utf-8")

# =====================================================
# Patch tickets.html
# =====================================================

ui_file = Path("app/templates/tickets.html")

text = ui_file.read_text(encoding="utf-8")
shutil.copy2(ui_file, f"{ui_file}.bak-{stamp}")

filter_block = """
<div class="row mb-3">

    <div class="col-md-3">
        <select id="categoryFilter"
                class="form-select"
                onchange="applyFilters()">
            <option value="">All Categories</option>
            <option>Microsoft 365</option>
            <option>Cyber Security</option>
            <option>Device Support</option>
            <option>Network</option>
            <option>Backup and Recovery</option>
            <option>Application Support</option>
            <option>User Administration</option>
            <option>Billing and Licensing</option>
            <option>General Support</option>
        </select>
    </div>

    <div class="col-md-3">
        <input
            id="subcategoryFilter"
            class="form-control"
            placeholder="Subcategory"
            onchange="applyFilters()">
    </div>

    <div class="col-md-2">
        <div class="form-check mt-2">
            <input class="form-check-input"
                   type="checkbox"
                   id="unclassifiedFilter"
                   onchange="applyFilters()">
            <label class="form-check-label">
                Unclassified
            </label>
        </div>
    </div>

</div>
"""

marker = """<div class="card stat-card p-3">"""

if marker in text and "categoryFilter" not in text:
    text = text.replace(
        marker,
        filter_block + "\n" + marker,
        1
    )

js = """
<script>

function applyFilters() {

    const params =
        new URLSearchParams(window.location.search);

    const category =
        document.getElementById(
            "categoryFilter"
        ).value;

    const subcategory =
        document.getElementById(
            "subcategoryFilter"
        ).value;

    const unclassified =
        document.getElementById(
            "unclassifiedFilter"
        ).checked;

    if (category) {
        params.set("category", category);
    } else {
        params.delete("category");
    }

    if (subcategory) {
        params.set("subcategory", subcategory);
    } else {
        params.delete("subcategory");
    }

    if (unclassified) {
        params.set("unclassified", "true");
    } else {
        params.delete("unclassified");
    }

    window.location =
        "/tickets?" + params.toString();
}

</script>
"""

if "function applyFilters()" not in text:
    text += "\n" + js

ui_file.write_text(text, encoding="utf-8")

print("[OK] Category filters added")
print("[OK] Subcategory filter added")
print("[OK] Unclassified filter added")
print("[OK] Backups created")