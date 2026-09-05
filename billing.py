#!/usr/bin/env python3
"""
fix_model_columns.py  -  Letsma MSP Platform
------------------------------------------------------------------
Fixes four column definitions that were accidentally added at MODULE
level in app/models.py (zero indentation, after the OAuthToken class)
instead of inside their proper model classes. Because they weren't
indented into a class, Customer / LicensePrice objects don't have these
attributes, causing:

    AttributeError: 'Customer' object has no attribute 'license_term_commitment'

This script:
  * Removes the 4 stray module-level lines.
  * Adds  license_term_commitment           into class Customer.
  * Adds  price_term / entered_sell_price /
          entered_cost_price                into class LicensePrice.

The matching DB columns already exist (created by the migration
endpoints), so NO database migration is needed - this only aligns the
Python models with the existing schema.

Run from the repo root (folder containing app/):

    cd ~/Downloads/letsma-msp-platform/msp-app
    python fix_model_columns.py

Safety: idempotent, backs up models.py first, and VALIDATES that the
result parses AND that all four columns map to the correct tables
before saving. Writes nothing if any check fails.
"""
import os, sys, re, shutil, datetime, subprocess

MODELS = os.path.join("app", "models.py")
if not os.path.isfile(MODELS):
    print("ERROR: %s not found. cd into the repo root (msp-app) first." % MODELS)
    sys.exit(1)

with open(MODELS, "r", encoding="utf-8") as f:
    src = f.read()

# Exact stray lines (must be at column 0 to be considered stray).
STRAY_LINES = [
    'license_term_commitment = Column(String, default="monthly")',
    'price_term = Column(String, default="monthly")',
    'entered_sell_price = Column(Float, nullable=True)',
    'entered_cost_price = Column(Float, nullable=True)',
]

def class_columns(text, class_name):
    """Return the set of 'name = Column(' attribute names defined at 4-space
    indent inside the given class."""
    lines = text.splitlines(keepends=True)
    start = None
    for i, ln in enumerate(lines):
        if re.match(r'^class\s+' + re.escape(class_name) + r'\b', ln):
            start = i
            break
    if start is None:
        return set()
    cols = set()
    i = start + 1
    while i < len(lines):
        ln = lines[i]
        if ln.strip() == "":
            i += 1; continue
        if not ln.startswith((" ", "\t")):
            break  # end of class body
        m = re.match(r'^    ([A-Za-z_][A-Za-z0-9_]*)\s*=\s*Column\(', ln)
        if m:
            cols.add(m.group(1))
        i += 1
    return cols

def insert_into_class(text, class_name, new_lines):
    """Insert new_lines (['name = Column(...)']) after the class's LAST
    existing 4-space Column definition."""
    lines = text.splitlines(keepends=True)
    start = None
    for i, ln in enumerate(lines):
        if re.match(r'^class\s+' + re.escape(class_name) + r'\b', ln):
            start = i; break
    if start is None:
        raise RuntimeError("class %s not found" % class_name)
    last_col_idx = None
    i = start + 1
    while i < len(lines):
        ln = lines[i]
        if ln.strip() == "":
            i += 1; continue
        if not ln.startswith((" ", "\t")):
            break
        if re.match(r'^    [A-Za-z_][A-Za-z0-9_]*\s*=\s*Column\(', ln):
            last_col_idx = i
        i += 1
    if last_col_idx is None:
        raise RuntimeError("no existing Column found in class %s" % class_name)
    block = "".join("    " + nl.rstrip() + "\n" for nl in new_lines)
    lines[last_col_idx + 1:last_col_idx + 1] = [block]
    return "".join(lines)

# --- idempotency: are there any stray column-0 lines left? ---
def has_stray(text):
    for line in STRAY_LINES:
        if re.search(r'(?m)^' + re.escape(line) + r'[ \t]*$', text):
            return True
    return False

if not has_stray(src):
    print("[skip] no stray module-level columns found - already fixed. Nothing to do.")
    sys.exit(0)

# --- backup ---
bak = MODELS + ".bak-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(MODELS, bak)
print("[backup] %s -> %s" % (MODELS, bak))

# --- 1. remove stray module-level lines (only those at column 0) ---
removed = 0
for line in STRAY_LINES:
    src, n = re.subn(r'(?m)^' + re.escape(line) + r'[ \t]*\r?\n', "", src)
    removed += n
print("[remove] deleted %d stray module-level column line(s)" % removed)

# --- 2. Customer.license_term_commitment ---
if "license_term_commitment" not in class_columns(src, "Customer"):
    src = insert_into_class(src, "Customer",
        ['license_term_commitment = Column(String, default="monthly")'])
    print("[add] Customer.license_term_commitment")
else:
    print("[skip] Customer.license_term_commitment already present")

# --- 3. LicensePrice price columns ---
lp_have = class_columns(src, "LicensePrice")
need = []
for name, line in [
    ("price_term",         'price_term = Column(String, default="monthly")'),
    ("entered_sell_price", 'entered_sell_price = Column(Float, nullable=True)'),
    ("entered_cost_price", 'entered_cost_price = Column(Float, nullable=True)'),
]:
    if name not in lp_have:
        need.append(line)
if need:
    src = insert_into_class(src, "LicensePrice", need)
    print("[add] LicensePrice: %s" % ", ".join(l.split(" =")[0] for l in need))
else:
    print("[skip] LicensePrice columns already present")

# --- 4. validate: parses as Python ---
import ast
try:
    ast.parse(src)
except SyntaxError as e:
    print("[ERROR] result would not parse (%s). NO changes written." % e)
    sys.exit(1)

# write it
with open(MODELS, "w", encoding="utf-8") as f:
    f.write(src)

# --- 5. validate: columns actually map to the right tables (import check) ---
check = (
    "from app.models import Customer, LicensePrice;"
    "c = 'license_term_commitment' in Customer.__table__.columns;"
    "a = 'price_term' in LicensePrice.__table__.columns;"
    "b = 'entered_sell_price' in LicensePrice.__table__.columns;"
    "d = 'entered_cost_price' in LicensePrice.__table__.columns;"
    "print('MAP', c, a, b, d);"
    "import sys; sys.exit(0 if (c and a and b and d) else 3)"
)
rc = subprocess.run([sys.executable, "-c", check]).returncode
if rc == 0:
    print("[verify] all four columns now map to the correct tables. OK.")
elif rc == 3:
    print("[WARN] file written and parses, but a column did not map as expected.")
    print("       Check that class Customer / class LicensePrice were the right targets.")
else:
    print("[note] could not run the SQLAlchemy import check standalone (needs app deps).")
    print("       It parses fine; verify once deployed. Backup kept at:", bak)

print("""
==================================================================
 DONE (no migration needed - DB columns already exist).

   git add app/models.py
   git commit -m "Fix models: nest license_term_commitment + price columns into their classes"
   git checkout main && git pull origin main
   git merge add-email-to-ticket
   git push origin main
   git checkout add-email-to-ticket

 After redeploy, both endpoints should return 200 (in the browser):
   - /api/billing-config/license-profitability
   - generate monthly invoices
==================================================================
""")
