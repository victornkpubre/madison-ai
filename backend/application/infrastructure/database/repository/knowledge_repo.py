from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.infrastructure.database.models import CreatorKnowledge


class KnowledgeRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, topic: str, content: str,
                     source: str = "manual") -> None:
        await self.session.execute(
            pg_insert(CreatorKnowledge)
            .values(topic=topic.lower().strip(), content=content,
                    source=source, updated_at=func.now())
            .on_conflict_do_update(
                index_elements=["topic"],
                set_=dict(content=content, source=source,
                          updated_at=func.now()),
            )
        )
        await self.session.commit()

    async def list_all(self, limit: int = 60) -> list[dict]:
        result = await self.session.execute(
            select(CreatorKnowledge.topic, CreatorKnowledge.content)
            .order_by(CreatorKnowledge.updated_at.desc())
            .limit(limit)
        )
        return [{"topic": r.topic, "content": r.content}
                for r in result.all()]

    async def delete(self, topic: str) -> None:
        await self.session.execute(
            delete(CreatorKnowledge)
            .where(CreatorKnowledge.topic == topic.lower())
        )
        await self.session.commit()
