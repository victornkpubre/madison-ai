from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from database.engine import get_db

async def get_session(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    return db

def get_graph(request: Request):
    return request.app.state.main_graph