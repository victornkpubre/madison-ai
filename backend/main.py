
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from langgraph.checkpoint.memory import MemorySaver
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from infrastructure import create_all_tables
from config import settings

DATABASE_URL = settings.database_url

_MAIN_NODES = frozenset({"supervisor",
                          "assist_agent", "idea_agent", "reply_agent"})


@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_graph
    if DATABASE_URL:
        pool = AsyncConnectionPool(conninfo=DATABASE_URL, open=False, kwargs={"autocommit": True})
        await pool.open()
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        app.state.pool = pool

        await create_all_tables()
    else:
        checkpointer = MemorySaver()

    main_graph = build_main_graph(checkpointer)
    yield
    if DATABASE_URL:
        await app.state.pool.close()


app = FastAPI(lifespan=lifespan)
app.include_router()

