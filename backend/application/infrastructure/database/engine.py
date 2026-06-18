"""
db/engine.py
============
Async SQLAlchemy engine, session factory, and two session helpers.

  get_db()       — async generator for FastAPI Depends (one session per request)
  open_session() — async context manager for tool functions and background tasks
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import settings


def _sa_url(raw: str | None) -> str | None:
    if not raw:
        return None
    for prefix in ("postgresql://", "postgres://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg://" + raw[len(prefix):]
    return raw


engine = (
    create_async_engine(_sa_url(settings.database_url), echo=False, pool_pre_ping=True)
    if settings.database_url else None
)

SessionFactory = (
    async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    if engine else None
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency — yields a session for the lifetime of one request.
    All repository calls in a single endpoint share this session, so they
    can be committed or rolled back together.

    Usage:
        @router.post("/knowledge")
        async def add_entry(req: ..., db: AsyncSession = Depends(get_db)):
            repo = KnowledgeRepository(db)
            await repo.upsert(req.topic, req.content)
    """
    if not SessionFactory:
        raise RuntimeError("DATABASE_URL not set — no session available")
    async with SessionFactory() as session:
        yield session


@asynccontextmanager
async def open_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for tool functions and background tasks that run outside
    a FastAPI request and cannot use Depends(get_db).

    Usage:
        @tool
        async def save_something(content: str) -> str:
            async with open_session() as db:
                repo = SignalRepository(db)
                await repo.insert(content)
            return "saved"
    """
    if not SessionFactory:
        raise RuntimeError("DATABASE_URL not set — no session available")
    async with SessionFactory() as session:
        yield session
