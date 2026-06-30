import warnings
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from config import settings
from infrastructure.ai.supervisor_graph import build_main_graph
from infrastructure.database.db import create_all_tables
from interface.api import assistant, captures, creators, database, ideas, leads

# Cosmetic only: langchain-openai's with_structured_output() (used by the
# supervisor's router LLM) trips a pydantic serialization warning on every
# call when its response metadata is traced by astream_events. Harmless —
# the routing decision is still parsed and used correctly — just noisy.
warnings.filterwarnings("ignore", message=".*PydanticSerializationUnexpectedValue.*")

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
app.include_router(database.router)
app.include_router(ideas.router)
app.include_router(leads.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
