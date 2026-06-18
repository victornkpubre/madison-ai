from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.infrastructure.database.models import TopicAnalytic


class AnalyticsRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, topic: str, frequency: int,
                     velocity: float, curiosity_score: float,
                     question_count: int, request_count: int,
                     sentiment: float) -> None:
        await self.session.execute(
            pg_insert(TopicAnalytic)
            .values(topic=topic, frequency=frequency,
                    velocity=velocity, curiosity_score=curiosity_score,
                    question_count=question_count, request_count=request_count,
                    sentiment=round(sentiment, 3), last_seen=func.now())
            .on_conflict_do_update(
                index_elements=["topic"],
                set_=dict(
                    frequency       = TopicAnalytic.frequency      + frequency,
                    velocity        = velocity,
                    curiosity_score = curiosity_score,
                    question_count  = TopicAnalytic.question_count + question_count,
                    request_count   = TopicAnalytic.request_count  + request_count,
                    sentiment       = round(sentiment, 3),
                    last_seen       = func.now(),
                ),
            )
        )
        await self.session.commit()

    async def list_top(self, limit: int = 20) -> list[dict]:
        result = await self.session.execute(
            select(TopicAnalytic)
            .order_by(TopicAnalytic.frequency.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [{"topic":           r.topic,
                 "frequency":       r.frequency,
                 "velocity":        r.velocity,
                 "curiosity_score": r.curiosity_score,
                 "question_count":  r.question_count,
                 "request_count":   r.request_count,
                 "sentiment":       r.sentiment}
                for r in rows]
