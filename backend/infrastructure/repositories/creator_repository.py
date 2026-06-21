"""
creator_repository.py
═══════════════════════
Concrete implementation of ICreatorRepository.

When DATABASE_URL is configured, reads and writes go through SQLAlchemy
2.0 (CreatorProfileModel / CreatorKnowledgeModel). Otherwise the
repository transparently falls back to process-local in-memory storage,
so the rest of the application never has to branch on settings.database_url
itself — that knowledge is fully contained here.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import func

from backend.config import settings
from backend.domain.entities.creator_entity import CreatorKnowledgeEntry, CreatorProfile
from backend.domain.repository.creator_repository_interface import ICreatorRepository
from backend.infrastructure.database.creator_model import CreatorKnowledgeModel, CreatorProfileModel
from backend.infrastructure.database.db import get_async_session, get_sync_session


class CreatorRepository(ICreatorRepository):

    def __init__(self):
        # In-memory fallbacks, used only when settings.database_url is unset.
        self._profile_mem: dict = {}
        self._knowledge_mem: list[dict] = []

    # ── profile ────────────────────────────────────────────────────────────

    async def get_profile(self) -> CreatorProfile:
        if settings.database_url:
            async with get_async_session() as s:
                row = (await s.execute(
                    select(CreatorProfileModel).where(CreatorProfileModel.id == 1)
                )).scalar_one_or_none()
            if not row:
                return CreatorProfile()
            return CreatorProfile(name=row.name, bio=row.bio,
                                   cta=row.cta, email=row.email)
        return CreatorProfile(**self._profile_mem) if self._profile_mem else CreatorProfile()

    async def save_profile(self, profile: CreatorProfile) -> None:
        if settings.database_url:
            async with get_async_session() as s:
                await s.execute(
                    pg_insert(CreatorProfileModel)
                    .values(id=1, name=profile.name, bio=profile.bio, cta=profile.cta,
                            email=profile.email, updated_at=func.now())
                    .on_conflict_do_update(
                        index_elements=["id"],
                        set_=dict(name=profile.name, bio=profile.bio, cta=profile.cta,
                                  email=profile.email, updated_at=func.now()),
                    )
                )
                await s.commit()
        else:
            self._profile_mem = profile.as_dict()

    # ── knowledge base ─────────────────────────────────────────────────────

    def list_knowledge(self, limit: int = 60) -> list[CreatorKnowledgeEntry]:
        if settings.database_url:
            with get_sync_session() as s:
                rows = s.execute(
                    select(CreatorKnowledgeModel.topic, CreatorKnowledgeModel.content)
                    .order_by(CreatorKnowledgeModel.updated_at.desc())
                    .limit(limit)
                ).all()
            return [CreatorKnowledgeEntry(topic=r.topic, content=r.content) for r in rows]
        return [CreatorKnowledgeEntry(topic=e["topic"], content=e["content"],
                                       source=e.get("source", "manual"))
                for e in self._knowledge_mem[:limit]]

    def upsert_knowledge(self, topic: str, content: str, source: str = "manual") -> None:
        clean_topic = topic.lower().strip()
        if settings.database_url:
            with get_sync_session() as s:
                s.execute(
                    pg_insert(CreatorKnowledgeModel)
                    .values(topic=clean_topic, content=content,
                            source=source, updated_at=func.now())
                    .on_conflict_do_update(
                        index_elements=["topic"],
                        set_=dict(content=content, source=source, updated_at=func.now()),
                    )
                )
                s.commit()
        else:
            existing = next((k for k in self._knowledge_mem
                             if k["topic"] == clean_topic), None)
            if existing:
                existing["content"] = content
            else:
                self._knowledge_mem.append({"topic": clean_topic,
                                            "content": content, "source": source})

    async def delete_knowledge(self, topic: str) -> None:
        clean_topic = topic.lower().strip()
        if settings.database_url:
            from sqlalchemy import delete
            async with get_async_session() as s:
                await s.execute(
                    delete(CreatorKnowledgeModel)
                    .where(CreatorKnowledgeModel.topic == clean_topic)
                )
                await s.commit()
        else:
            self._knowledge_mem = [k for k in self._knowledge_mem
                                   if k["topic"] != clean_topic]


# Process-wide singleton — see application/creators/creator_service.py
creator_repository = CreatorRepository()
