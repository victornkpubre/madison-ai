from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from backend.config import settings
from backend.infrastructure.ai.supervisor_graph import build_main_graph
from backend.infrastructure.database.db import create_all_tables
from backend.interface.api import assistant, captures, creators, ideas

DATABASE_URL = settings.database_url


@asynccontextmanager
async def lifespan(app: FastAPI):
    if DATABASE_URL:
        pool = AsyncConnectionPool(conninfo=DATABASE_URL, open=False, kwargs={"autocommit": True})
        await pool.open()
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        app.state.pool = pool

        await create_all_tables()
    else:
        checkpointer = MemorySaver()

    app.state.main_graph = build_main_graph(checkpointer)
    yield
    if DATABASE_URL:
        await app.state.pool.close()


app = FastAPI(lifespan=lifespan)
app.include_router(assistant.router)
app.include_router(captures.router)
app.include_router(creators.router)
app.include_router(ideas.router)
