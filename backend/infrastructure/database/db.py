"""
db.py
═════
SQLAlchemy engine, session factories, and schema management for StreamEye.

Two engines are kept side by side:
  async_engine / get_async_session — for FastAPI endpoints and async tools
  sync_engine  / get_sync_session  — for tool functions that run inside
                                      thread pools (LangChain @tool calls)

Both are None when DATABASE_URL is not set — repositories fall back to
in-memory storage in that case (see infrastructure/repositories/*).
"""

from contextlib import asynccontextmanager, contextmanager
from typing import Optional

import sqlalchemy
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import settings


def _sa_url(raw: Optional[str]) -> Optional[str]:
    """Rewrite a plain postgres:// URL to the psycopg3 driver form SQLAlchemy needs."""
    if not raw:
        return None
    for prefix in ("postgresql://", "postgres://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg://" + raw[len(prefix):]
    return raw


_DB_URL = settings.database_url

async_engine = (
    create_async_engine(_sa_url(_DB_URL), echo=False, pool_pre_ping=True)
    if _DB_URL else None
)

sync_engine = (
    sqlalchemy.create_engine(_sa_url(_DB_URL), echo=False, pool_pre_ping=True)
    if _DB_URL else None
)

_AsyncFactory = (
    async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)
    if async_engine else None
)

_SyncFactory = (
    sessionmaker(sync_engine, expire_on_commit=False)
    if sync_engine else None
)


@asynccontextmanager
async def get_async_session():
    """Async session for FastAPI endpoints and async LangGraph tools."""
    if not _AsyncFactory:
        raise RuntimeError("DATABASE_URL not set — no async session available")
    async with _AsyncFactory() as session:
        yield session


@contextmanager
def get_sync_session():
    """Sync session for tool functions that run inside thread pools."""
    if not _SyncFactory:
        raise RuntimeError("DATABASE_URL not set — no sync session available")
    with _SyncFactory() as session:
        yield session


class Base(DeclarativeBase):
    pass


async def create_all_tables() -> None:
    """
    Create every table registered on Base.metadata. Safe to call on every
    startup — uses CREATE IF NOT EXISTS internally. Also runs ALTER TABLE
    migrations for columns added after initial deployment.

    Importing the model modules below (for their side effect of registering
    classes on Base.metadata) is required before create_all can see them.
    """
    if not async_engine:
        return

    # Ensure every ORM model module has been imported so its table is
    # registered on Base.metadata before we create_all.
    from backend.infrastructure.database import (  # noqa: F401
        capture_model, creator_model, idea_model, notification_model,
    )

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in [
            "ALTER TABLE telegram_users   ADD COLUMN IF NOT EXISTS last_name   VARCHAR(255)",
            "ALTER TABLE email_accounts   ADD COLUMN IF NOT EXISTS smtp_host   VARCHAR(255)",
            "ALTER TABLE email_accounts   ADD COLUMN IF NOT EXISTS smtp_port   INTEGER",
            "ALTER TABLE email_accounts   ADD COLUMN IF NOT EXISTS imap_host   VARCHAR(255)",
            "ALTER TABLE email_accounts   ADD COLUMN IF NOT EXISTS imap_port   INTEGER",
        ]:
            await conn.execute(text(stmt))
