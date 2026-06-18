from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.infrastructure.database.models import TelegramUser


class TelegramRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, chat_id: int, first_name: str,
                     last_name: str | None = None,
                     username:  str | None = None) -> None:
        await self.session.execute(
            pg_insert(TelegramUser)
            .values(telegram_chat_id=chat_id, first_name=first_name,
                    last_name=last_name, username=username, last_seen=func.now())
            .on_conflict_do_update(
                index_elements=["telegram_chat_id"],
                set_=dict(first_name=first_name, last_name=last_name,
                          username=username, last_seen=func.now()),
            )
        )
        await self.session.commit()

    async def get_chat_id(self, username: str) -> int | None:
        clean = username.lower().lstrip("@")
        result = await self.session.execute(
            select(TelegramUser.telegram_chat_id)
            .where(TelegramUser.username == clean)
        )
        return result.scalar_one_or_none()

    async def list_all(self, limit: int = 50) -> list[dict]:
        result = await self.session.execute(
            select(TelegramUser)
            .order_by(TelegramUser.registered_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [{"chat_id":       r.telegram_chat_id,
                 "first_name":    r.first_name,
                 "last_name":     r.last_name,
                 "username":      r.username,
                 "registered_at": str(r.registered_at),
                 "last_seen":     str(r.last_seen)}
                for r in rows]
