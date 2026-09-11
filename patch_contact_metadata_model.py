from pathlib import Path
from datetime import datetime
import shutil
import py_compile
import sys

MODELS = Path("app/models.py")

if not MODELS.exists():
    print("ERROR: app/models.py not found")
    sys.exit(1)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

backup = Path(
    str(MODELS) + f".bak-contact-metadata-{stamp}"
)

shutil.copy2(MODELS, backup)

print(f"Backup created: {backup}")

text = MODELS.read_text(encoding="utf-8")

# --------------------------------------------------
# Add relationship to Contact
# --------------------------------------------------

relationship_block = """
    metadata_record = relationship(
        "ContactMetadata",
        uselist=False,
        back_populates="contact",
        cascade="all, delete-orphan",
    )
"""

if "metadata_record = relationship(" not in text:

    marker = """
    customer = relationship("Customer", back_populates="contacts")
"""

    if marker not in text:
        print("Could not locate Contact relationship section")
        shutil.copy2(backup, MODELS)
        sys.exit(1)

    text = text.replace(
        marker,
        marker + "\n" + relationship_block
    )

    print("Added Contact.metadata_record relationship")

# --------------------------------------------------
# Add ContactMetadata model
# --------------------------------------------------

if "class ContactMetadata(" not in text:

    insert_before = """
class Technician(Base):
"""

    model = '''

class ContactMetadata(Base):
    __tablename__ = "contact_metadata"

    id = Column(String, primary_key=True, default=gen_id)

    contact_id = Column(
        String,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    graph_user_id = Column(
        String,
        nullable=True,
        index=True,
    )

    whatsapp_number = Column(
        String,
        nullable=True,
    )

    notes = Column(
        Text,
        nullable=True,
    )

    preferred_contact_method = Column(
        String,
        nullable=True,
    )

    vip_contact = Column(
        Boolean,
        default=False,
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    contact = relationship(
        "Contact",
        back_populates="metadata_record",
    )

'''

    if insert_before not in text:
        print("Could not locate Technician insertion point")
        shutil.copy2(backup, MODELS)
        sys.exit(1)

    text = text.replace(
        insert_before,
        model + "\n" + insert_before
    )

    print("Added ContactMetadata model")

MODELS.write_text(text, encoding="utf-8")

try:
    py_compile.compile(
        str(MODELS),
        doraise=True,
    )

    print("models.py compiled OK")

except Exception as exc:
    print(exc)
    shutil.copy2(backup, MODELS)
    print("Original restored")
    sys.exit(1)

print()
print("SUCCESS")
print()
print("Next create migration:")
print("migrate_contact_metadata.py")