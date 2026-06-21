"""
idea_repository.py
═════════════════════
Persistence for the idea-generator domain: the content-strategy profile,
content history, raw audience signals, topic analytics, and the latest
synthesized audience analysis.

Same dual-mode pattern as CreatorRepository: SQLAlchemy when DATABASE_URL
is set, in-memory dict/list storage otherwise. Implements IIdeaRepository
and is consumed through that interface by application/services/idea_service.py.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import func

from backend.config import settings
from backend.domain.repository.idea_repository_interface import IIdeaRepository
from backend.domain.entities.idea_entity import (
    AudienceSignal, ContentHistoryItem, CreatorIdeaProfile, TopicAnalytic,
)
from backend.infrastructure.database.db import get_async_session, get_sync_session
from backend.infrastructure.database.idea_model import (
    AudienceAnalysisModel, AudienceSignalModel, ContentHistoryModel,
    CreatorIdeaProfileModel, TopicAnalyticModel,
)


class IdeaRepository(IIdeaRepository):

    def __init__(self):
        self._profile_mem: dict = {}
        self._content_history_mem: list[dict] = []
        self._signals_mem: list[dict] = []
        self._topic_analytics_mem: dict[str, dict] = {}
        self._audience_analysis_mem: dict | None = None

    # ── creator idea profile ──────────────────────────────────────────────

    def upsert_profile_field(self, field: str, value: str) -> None:
        allowed = set(CreatorIdeaProfile().as_dict().keys())
        if field not in allowed:
            raise ValueError(f"Unknown profile field: {field!r}")

        if settings.database_url:
            with get_sync_session() as s:
                s.execute(
                    pg_insert(CreatorIdeaProfileModel)
                    .values(id=1, **{field: value}, updated_at=func.now())
                    .on_conflict_do_update(
                        index_elements=["id"],
                        set_={field: value, "updated_at": func.now()},
                    )
                )
                s.commit()
        else:
            self._profile_mem[field] = value

    def load_profile(self) -> CreatorIdeaProfile:
        if settings.database_url:
            with get_sync_session() as s:
                row = s.execute(
                    select(CreatorIdeaProfileModel).where(CreatorIdeaProfileModel.id == 1)
                ).scalar_one_or_none()
            if not row:
                return CreatorIdeaProfile()
            return CreatorIdeaProfile(
                niche=row.niche, sub_niche=row.sub_niche,
                target_audience=row.target_audience, platforms=row.platforms,
                content_style=row.content_style, monetization=row.monetization,
            )
        return CreatorIdeaProfile(**self._profile_mem)

    # ── content history ───────────────────────────────────────────────────

    def insert_content_item(self, title: str, topic: str,
                            content_type: str, platform: str = "") -> None:
        if settings.database_url:
            with get_sync_session() as s:
                s.add(ContentHistoryModel(title=title, topic=topic,
                                          content_type=content_type,
                                          platform=platform or None))
                s.commit()
        else:
            self._content_history_mem.append({
                "title": title, "topic": topic,
                "content_type": content_type, "platform": platform,
            })

    def load_content_topics(self, limit: int = 50) -> list[str]:
        if settings.database_url:
            with get_sync_session() as s:
                return list(s.execute(
                    select(ContentHistoryModel.topic)
                    .where(ContentHistoryModel.topic.isnot(None))
                    .distinct()
                    .limit(limit)
                ).scalars().all())
        return [item["topic"] for item in self._content_history_mem if item.get("topic")][:limit]

    def load_content_references(self, limit: int = 30) -> list[ContentHistoryItem]:
        if settings.database_url:
            with get_sync_session() as s:
                rows = s.execute(
                    select(ContentHistoryModel.title, ContentHistoryModel.topic,
                           ContentHistoryModel.content_type)
                    .order_by(ContentHistoryModel.created_at.desc())
                    .limit(limit)
                ).all()
            return [ContentHistoryItem(title=r.title, topic=r.topic,
                                       content_type=r.content_type) for r in rows]
        return [ContentHistoryItem(title=i["title"], topic=i.get("topic"),
                                   content_type=i.get("content_type"))
                for i in self._content_history_mem[:limit]]

    def load_content_history_summary(self, limit: int = 50) -> list[dict]:
        if settings.database_url:
            with get_sync_session() as s:
                rows = s.execute(
                    select(ContentHistoryModel.content_type, ContentHistoryModel.topic)
                    .order_by(ContentHistoryModel.created_at.desc())
                    .limit(limit)
                ).all()
            return [{"content_type": r.content_type, "topic": r.topic} for r in rows]
        return [{"content_type": i["content_type"], "topic": i.get("topic")}
                for i in self._content_history_mem[:limit]]

    # ── audience signals ──────────────────────────────────────────────────

    def insert_signal(self, content: str, source: str = "telegram",
                      session_id: str = "") -> None:
        if settings.database_url:
            with get_sync_session() as s:
                s.add(AudienceSignalModel(content=content, source=source,
                                          session_id=session_id or ""))
                s.commit()
        else:
            self._signals_mem.append({
                "content": content, "source": source,
                "session_id": session_id,
                "timestamp": datetime.utcnow(),
            })

    def load_unanalysed_signals(self, limit: int = 200) -> list[dict]:
        if settings.database_url:
            with get_sync_session() as s:
                rows = s.execute(
                    select(AudienceSignalModel.id, AudienceSignalModel.content,
                           AudienceSignalModel.timestamp)
                    .where(AudienceSignalModel.signal_type.is_(None))
                    .order_by(AudienceSignalModel.timestamp.desc())
                    .limit(limit)
                ).all()
            return [{"id": r.id, "content": r.content, "timestamp": r.timestamp} for r in rows]
        return [s for s in self._signals_mem if not s.get("signal_type")][:limit]

    def update_signal_topic(self, signal: dict, signal_type: str, topic: str) -> None:
        """
        Mark a signal as analysed.

        `signal` is one of the dicts returned by load_unanalysed_signals().
        In DB mode it must contain an "id" key. In memory mode it IS the
        live dict stored in _signals_mem (not a copy), so mutating it here
        updates the underlying store directly — no positional bookkeeping
        needed.
        """
        if settings.database_url:
            with get_sync_session() as s:
                s.execute(
                    update(AudienceSignalModel)
                    .where(AudienceSignalModel.id == signal["id"])
                    .values(signal_type=signal_type, topic=topic)
                )
                s.commit()
        else:
            signal["signal_type"] = signal_type
            signal["topic"] = topic

    def load_signals_by_topic(self, topic: str,
                              signal_types: list[str] | None = None,
                              limit: int = 5) -> list[str]:
        types = signal_types or ["question", "request"]
        if settings.database_url:
            with get_sync_session() as s:
                return list(s.execute(
                    select(AudienceSignalModel.content)
                    .where(AudienceSignalModel.topic == topic,
                           AudienceSignalModel.signal_type.in_(types))
                    .order_by(AudienceSignalModel.timestamp.desc())
                    .limit(limit)
                ).scalars().all())
        return [
            s["content"] for s in self._signals_mem
            if s.get("topic") == topic and s.get("signal_type") in types
        ][:limit]

    # ── topic analytics ───────────────────────────────────────────────────

    def upsert_topic_analytics(self, topic: str, frequency: int,
                               velocity: float, curiosity_score: float,
                               question_count: int, request_count: int,
                               sentiment: float) -> None:
        if settings.database_url:
            with get_sync_session() as s:
                s.execute(
                    pg_insert(TopicAnalyticModel)
                    .values(topic=topic, frequency=frequency, velocity=velocity,
                            curiosity_score=curiosity_score,
                            question_count=question_count, request_count=request_count,
                            sentiment=round(sentiment, 3), last_seen=func.now())
                    .on_conflict_do_update(
                        index_elements=["topic"],
                        set_=dict(
                            frequency       = TopicAnalyticModel.frequency      + frequency,
                            velocity        = velocity,
                            curiosity_score = curiosity_score,
                            question_count  = TopicAnalyticModel.question_count + question_count,
                            request_count   = TopicAnalyticModel.request_count  + request_count,
                            sentiment       = round(sentiment, 3),
                            last_seen       = func.now(),
                        ),
                    )
                )
                s.commit()
        else:
            self._topic_analytics_mem[topic] = {
                "topic": topic,
                "frequency":       frequency,
                "velocity":        round(velocity, 3),
                "curiosity_score": round(curiosity_score, 3),
                "question_count":  question_count,
                "request_count":   request_count,
                "sentiment":       round(sentiment, 3),
            }

    def load_topic_analytics(self, limit: int = 20) -> list[dict]:
        if settings.database_url:
            with get_sync_session() as s:
                rows = s.execute(
                    select(TopicAnalyticModel)
                    .order_by(TopicAnalyticModel.frequency.desc())
                    .limit(limit)
                ).scalars().all()
            return [{"topic": r.topic, "frequency": r.frequency,
                     "velocity": r.velocity, "curiosity_score": r.curiosity_score,
                     "question_count": r.question_count,
                     "request_count": r.request_count,
                     "sentiment": r.sentiment}
                    for r in rows]
        return sorted(self._topic_analytics_mem.values(),
                      key=lambda x: -x.get("frequency", 0))[:limit]

    # ── audience analysis ───────────────────────────────────────────────────

    def save_audience_analysis(self, summary: str, gaps: list[str]) -> None:
        gaps_text = "\n".join(gaps)
        if settings.database_url:
            with get_sync_session() as s:
                s.execute(
                    pg_insert(AudienceAnalysisModel)
                    .values(id=1, summary=summary, gaps=gaps_text, updated_at=func.now())
                    .on_conflict_do_update(
                        index_elements=["id"],
                        set_={"summary": summary, "gaps": gaps_text, "updated_at": func.now()},
                    )
                )
                s.commit()
        else:
            self._audience_analysis_mem = {"summary": summary, "gaps": gaps}

    def load_latest_audience_analysis(self) -> dict | None:
        if settings.database_url:
            with get_sync_session() as s:
                row = s.execute(
                    select(AudienceAnalysisModel).where(AudienceAnalysisModel.id == 1)
                ).scalar_one_or_none()
            if not row:
                return None
            return {"summary": row.summary, "gaps": row.gaps.split("\n") if row.gaps else []}
        return self._audience_analysis_mem


# Process-wide singleton — wired into IdeaService by backend/composition.py
idea_repository = IdeaRepository()
