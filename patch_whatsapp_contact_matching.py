from pathlib import Path
from datetime import datetime
import shutil
import py_compile
import sys

FILE = Path("app/services/whatsapp_service.py")

backup = FILE.with_suffix(
    FILE.suffix + f".bak-contact-matching-{datetime.now():%Y%m%d-%H%M%S}"
)
shutil.copy2(FILE, backup)

text = FILE.read_text(encoding="utf-8")

old = """
    contact = db.query(Contact).filter(Contact.whatsapp_number == wa_number).first()
    if contact:
        return contact.customer, contact
    customer = db.query(Customer).filter(Customer.whatsapp_number == wa_number).first()
    if customer:
        return customer, None
"""

new = """
    # Exact WhatsApp number
    contact = db.query(Contact).filter(
        Contact.whatsapp_number == wa_number
    ).first()
    if contact:
        return contact.customer, contact

    # Exact mobile number
    contact = db.query(Contact).filter(
        Contact.mobile_phone == wa_number
    ).first()
    if contact:
        return contact.customer, contact

    # Exact business phone
    contact = db.query(Contact).filter(
        Contact.business_phone == wa_number
    ).first()
    if contact:
        return contact.customer, contact

    customer = db.query(Customer).filter(
        Customer.whatsapp_number == wa_number
    ).first()
    if customer:
        return customer, None
"""

if old not in text:
    print("Could not locate first match block")
    sys.exit(1)

text = text.replace(old, new, 1)

old2 = """
    for c in db.query(Contact).filter(Contact.whatsapp_number.isnot(None)).all():
        if _normalise_number(c.whatsapp_number) == target:
            return c.customer, c
"""

new2 = """
    for c in db.query(Contact).all():

        if (
            c.whatsapp_number
            and _normalise_number(c.whatsapp_number) == target
        ):
            return c.customer, c

        if (
            c.mobile_phone
            and _normalise_number(c.mobile_phone) == target
        ):
            return c.customer, c

        if (
            c.business_phone
            and _normalise_number(c.business_phone) == target
        ):
            return c.customer, c
"""

text = text.replace(old2, new2, 1)

FILE.write_text(text, encoding="utf-8")

py_compile.compile(str(FILE), doraise=True)

print("SUCCESS")