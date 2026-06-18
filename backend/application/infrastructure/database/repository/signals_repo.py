from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.infrastructure.database.models import AudienceSignal


class SignalRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert(self, content: str, source: str = "telegram",
                     session_id: str = "") -> None:
        self.session.add(
            AudienceSignal(content=content, source=source,
                           session_id=session_id or "")
        )
        await self.session.commit()

    async def list_unanalysed(self, limit: int = 200) -> list[dict]:
        result = await self.session.execute(
            select(AudienceSignal.id, AudienceSignal.content,
                   AudienceSignal.timestamp)
            .where(AudienceSignal.signal_type.is_(None))
            .order_by(AudienceSignal.timestamp.desc())
            .limit(limit)
        )
        return [{"id": r.id, "content": r.content,
                 "timestamp": r.timestamp}
                for r in result.all()]

    async def set_topic(self, signal_id: str,
                        signal_type: str, topic: str) -> None:
        await self.session.execute(
            update(AudienceSignal)
            .where(AudienceSignal.id == signal_id)
            .values(signal_type=signal_type, topic=topic)
        )
        await self.session.commit()

    async def list_by_topic(self, topic: str,
                             signal_types: list[str] | None = None,
                             limit: int = 5) -> list[str]:
        types = signal_types or ["question", "request"]
        result = await self.session.execute(
            select(AudienceSignal.content)
            .where(AudienceSignal.topic == topic,
                   AudienceSignal.signal_type.in_(types))
            .order_by(AudienceSignal.timestamp.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
