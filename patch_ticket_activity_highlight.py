from pathlib import Path
from datetime import datetime
import shutil, subprocess, sys

PORTAL = Path("app/routers/portal.py")
TPL = Path("app/templates/tickets.html")
for p in (PORTAL, TPL):
    if not p.exists():
        raise SystemExit(f"Missing {p}")

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
pbak = Path(f"{PORTAL}.bak-{stamp}")
tbak = Path(f"{TPL}.bak-{stamp}")
shutil.copy2(PORTAL, pbak)
shutil.copy2(TPL, tbak)

# 1. portal.py: sort by updated_at desc
ptext = PORTAL.read_text(encoding="utf-8")
old_sort = "tickets = query.order_by(models.Ticket.created_at.desc()).all()"
new_sort = "tickets = query.order_by(models.Ticket.updated_at.desc()).all()"
if old_sort not in ptext and new_sort not in ptext:
    raise SystemExit("Could not find ticket order_by line")
if old_sort in ptext:
    ptext = ptext.replace(old_sort, new_sort, 1)
PORTAL.write_text(ptext, encoding="utf-8")

# 2. tickets.html: add "Last Update" header + cell with recency highlight
ttext = TPL.read_text(encoding="utf-8")

# 2a. header: insert a Last Update column before the Delete header
hdr_anchor = '<th>Updated</th>'
if hdr_anchor in ttext and 'data-lastupdate-col' not in ttext:
    ttext = ttext.replace(
        hdr_anchor,
        '<th data-lastupdate-col>Last Update</th><th>Updated</th>',
        1,
    )

# 2b. row cell: add a highlighted "Last Update" cell using ukdatetime + recency
# We look for the existing Updated cell and inject a new cell before it.
row_anchor = "<td class=\"small text-muted\">{{ t.updated_at|ukdatetime('%d %b %Y %H:%M') }}</td>"
row_new = (
    '<td class="small">'
    '{% set _delta = (now - t.updated_at).total_seconds() if now is defined else 999999 %}'
    '{% if _delta < 86400 %}'
    '<span class="badge bg-success">🟢 {{ t.updated_at|ukdatetime(\'%d %b %H:%M\') }}</span>'
    '{% else %}'
    '<span class="text-muted">{{ t.updated_at|ukdatetime(\'%d %b %H:%M\') }}</span>'
    '{% endif %}'
    '</td>'
    "<td class=\"small text-muted\">{{ t.updated_at|ukdatetime('%d %b %Y %H:%M') }}</td>"
)
if row_anchor in ttext and 'set _delta' not in ttext:
    ttext = ttext.replace(row_anchor, row_new, 1)

# 2c. colspan bump for the empty-state row (13 -> 14) if present
ttext = ttext.replace('colspan="13"', 'colspan="14"')

TPL.write_text(ttext, encoding="utf-8")

# verify + compile
errors = []
if "updated_at.desc()" not in PORTAL.read_text(encoding="utf-8"):
    errors.append("portal sort not applied")
if "data-lastupdate-col" not in TPL.read_text(encoding="utf-8"):
    errors.append("Last Update header not added")
if "set _delta" not in TPL.read_text(encoding="utf-8"):
    errors.append("Last Update cell not added")

r = subprocess.run([sys.executable, "-m", "py_compile", str(PORTAL)],
                   capture_output=True, text=True)
if r.returncode != 0:
    errors.append("portal compile failed:\n" + r.stdout + r.stderr)

if errors:
    shutil.copy2(pbak, PORTAL)
    shutil.copy2(tbak, TPL)
    print("[FAILED] rolled back")
    for e in errors:
        print(e)
    raise SystemExit(1)

print("[OK] Ticket list now sorts by last update")
print("[OK] Last Update column added with 24h highlight")
print(f"[OK] Backups: {pbak.name}, {tbak.name}")
print("[NOTE] Requires a 'now' value in template context (see next step).")
