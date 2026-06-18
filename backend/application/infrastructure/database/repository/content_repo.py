from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.infrastructure.database.models import ContentHistory


class ContentRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert(self, title: str, topic: str,
                     content_type: str, platform: str = "") -> None:
        self.session.add(
            ContentHistory(title=title, topic=topic,
                           content_type=content_type,
                           platform=platform or None)
        )
        await self.session.commit()

    async def list_topics(self, limit: int = 50) -> list[str]:
        result = await self.session.execute(
            select(ContentHistory.topic)
            .where(ContentHistory.topic.isnot(None))
            .distinct()
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_references(self, limit: int = 30) -> list[dict]:
        result = await self.session.execute(
            select(ContentHistory.title, ContentHistory.topic,
                   ContentHistory.content_type)
            .order_by(ContentHistory.created_at.desc())
            .limit(limit)
        )
        return [{"title": r.title, "topic": r.topic,
                 "type": r.content_type}
                for r in result.all()]

    async def list_summary(self, limit: int = 50) -> list[dict]:
        result = await self.session.execute(
            select(ContentHistory.content_type, ContentHistory.topic)
            .order_by(ContentHistory.created_at.desc())
            .limit(limit)
        )
        return [{"content_type": r.content_type, "topic": r.topic}
                for r in result.all()]
