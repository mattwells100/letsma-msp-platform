# migrate_contact_metadata.py

from sqlalchemy import text
from app.database import SessionLocal

db = SessionLocal()

try:

    db.execute(text("""
        CREATE TABLE IF NOT EXISTS contact_metadata (
            id VARCHAR(64) PRIMARY KEY,
            contact_id VARCHAR(64) NOT NULL UNIQUE,
            graph_user_id VARCHAR(255),
            whatsapp_number VARCHAR(255),
            notes TEXT,
            preferred_contact_method VARCHAR(255),
            vip_contact BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            CONSTRAINT fk_contact_metadata_contact
            FOREIGN KEY(contact_id)
            REFERENCES contacts(id)
            ON DELETE CASCADE
        )
    """))

    db.commit()

    print("SUCCESS")

finally:
    db.close()