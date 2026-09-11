from pathlib import Path
from datetime import datetime
import shutil
import py_compile
import re
import sys

MODELS = Path("app/models.py")

if not MODELS.exists():
    print("ERROR: app/models.py not found")
    sys.exit(1)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

backup = MODELS.with_suffix(
    MODELS.suffix + f".bak-whatsapp-fields-{stamp}"
)

shutil.copy2(MODELS, backup)

print(f"Backup created: {backup}")

text = MODELS.read_text(encoding="utf-8")

# ---------------------------------------------------
# Customer
# ---------------------------------------------------

customer_field = """
    whatsapp_number = Column(String(50), nullable=True)
"""

if "whatsapp_number = Column(String(50)" not in text:

    text = re.sub(
        r"(class Customer\(.*?\):.*?)(\n\s+created_at\s*=)",
        r"\1\n"
        + customer_field
        + r"\2",
        text,
        count=1,
        flags=re.S,
    )

    print("Added Customer.whatsapp_number")

# ---------------------------------------------------
# Contact
# ---------------------------------------------------

contact_fields = """
    mobile_number = Column(String(50), nullable=True)
    whatsapp_number = Column(String(50), nullable=True)
"""

if "mobile_number = Column(String(50)" not in text:

    text = re.sub(
        r"(class Contact\(.*?\):.*?)(\n\s+created_at\s*=)",
        r"\1\n"
        + contact_fields
        + r"\2",
        text,
        count=1,
        flags=re.S,
    )

    print("Added Contact mobile/whatsapp fields")

MODELS.write_text(text, encoding="utf-8")

# ---------------------------------------------------
# Validation
# ---------------------------------------------------

try:
    py_compile.compile(str(MODELS), doraise=True)
    print("models.py compiled OK")

except Exception as exc:
    print(exc)
    shutil.copy2(backup, MODELS)
    print("Original restored")
    sys.exit(1)

print()
print("NEXT STEP:")
print("Run database migration")
`