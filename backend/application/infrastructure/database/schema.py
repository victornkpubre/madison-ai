"""
db/schema.py
============
Table creation and safe column migrations.
Called once at server startup from the lifespan function in main.py.
"""

from sqlalchemy import text

from .engine import async_engine
from .models import Base


async def create_all_tables() -> None:
    """
    Create every table defined in models.py. Safe to call on every startup —
    uses CREATE IF NOT EXISTS internally. ALTER TABLE statements add new columns
    to existing tables without touching existing data.
    """
    if not async_engine:
        return

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        for stmt in [
            "ALTER TABLE telegram_users ADD COLUMN IF NOT EXISTS last_name   VARCHAR(255)",
            "ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS smtp_host   VARCHAR(255)",
            "ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS smtp_port   INTEGER",
            "ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS imap_host   VARCHAR(255)",
            "ALTER TABLE email_accounts ADD COLUMN IF NOT EXISTS imap_port   INTEGER",
        ]:
            await conn.execute(text(stmt))
