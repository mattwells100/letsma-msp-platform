from sqlalchemy import text

from app.database import SessionLocal

db = SessionLocal()

try:

    db.execute(text("""
        ALTER TABLE customers
        ADD COLUMN IF NOT EXISTS whatsapp_number VARCHAR(50)
    """))

    db.execute(text("""
        ALTER TABLE contacts
        ADD COLUMN IF NOT EXISTS mobile_number VARCHAR(50)
    """))

    db.execute(text("""
        ALTER TABLE contacts
        ADD COLUMN IF NOT EXISTS whatsapp_number VARCHAR(50)
    """))

    db.commit()

    print("SUCCESS")

finally:
    db.close()
