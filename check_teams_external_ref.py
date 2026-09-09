from sqlalchemy import create_engine, text

DATABASE_URL = (
    "postgresql+psycopg2://letsmaadmin:"
    "REPLACE_PASSWORD@"
    "letsma-msp-pg-29455.postgres.database.azure.com:5432/"
    "letsma_msp?sslmode=require"
)

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    rows = conn.execute(text(
        "SELECT ticket_number, source, conversation_id, external_ref "
        "FROM tickets "
        "WHERE source = 'TEAMS' "
        "ORDER BY created_at DESC "
        "LIMIT 5"
    ))
    for r in rows:
        print(dict(r._mapping))
