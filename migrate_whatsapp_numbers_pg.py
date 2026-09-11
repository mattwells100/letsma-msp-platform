from sqlalchemy import create_engine, text

DATABASE_URL = "postgresql+psycopg2://...."

engine = create_engine(DATABASE_URL)

with engine.begin() as conn:
    conn.execute(text("""
        ALTER TABLE customers
        ADD COLUMN IF NOT EXISTS whatsapp_number VARCHAR(255)
    """))

    conn.execute(text("""
        ALTER TABLE contacts
        ADD COLUMN IF NOT EXISTS whatsapp_number VARCHAR(255)
    """))

print("SUCCESS")