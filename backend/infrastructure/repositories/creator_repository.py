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

from config import settings
from domain.entities.creator_entity import CreatorKnowledgeEntry, CreatorProfile, PROFILE_FIELDS
from domain.repository.creator_repository_interface import ICreatorRepository
from infrastructure.database.creator_model import CreatorKnowledgeModel, CreatorProfileModel
from infrastructure.database.db import get_async_session, get_sync_session


class CreatorRepository(ICreatorRepository):

    def __init__(self):
        # In-memory fallbacks, used only when settings.database_url is unset.
        self._profile_mem: dict = {}
        self._knowledge_mem: list[dict] = []

    # ── profile ────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_profile(row) -> CreatorProfile:
        return CreatorProfile(
            name=row.name, bio=row.bio, cta=row.cta, email=row.email,
            niche=row.niche, sub_niche=row.sub_niche,
            target_audience=row.target_audience, platforms=row.platforms,
            content_style=row.content_style, monetization=row.monetization,
        )

    def _mem_to_profile(self) -> CreatorProfile:
        allowed = set(CreatorProfile().as_dict().keys())
        return CreatorProfile(**{k: v for k, v in self._profile_mem.items()
                                 if k in allowed})

    async def get_profile(self) -> CreatorProfile:
        if settings.database_url:
            async with get_async_session() as s:
                row = (await s.execute(
                    select(CreatorProfileModel).where(CreatorProfileModel.id == 1)
                )).scalar_one_or_none()
            return self._row_to_profile(row) if row else CreatorProfile()
        return self._mem_to_profile()

    def get_profile_sync(self) -> CreatorProfile:
        """Synchronous read of the unified profile. Exists so the idea
        repository (whose profile methods are sync) can read the same row
        without crossing the async boundary."""
        if settings.database_url:
            with get_sync_session() as s:
                row = s.execute(
                    select(CreatorProfileModel).where(CreatorProfileModel.id == 1)
                ).scalar_one_or_none()
            return self._row_to_profile(row) if row else CreatorProfile()
        return self._mem_to_profile()

    async def save_profile(self, profile: CreatorProfile) -> None:
        # Only writes the identity half — strategy fields are written field-by-
        # field via upsert_profile_field, so an identity save never clobbers them.
        identity = profile.identity_dict()
        if settings.database_url:
            async with get_async_session() as s:
                await s.execute(
                    pg_insert(CreatorProfileModel)
                    .values(id=1, **identity, updated_at=func.now())
                    .on_conflict_do_update(
                        index_elements=["id"],
                        set_=dict(**identity, updated_at=func.now()),
                    )
                )
                await s.commit()
        else:
            self._profile_mem.update(identity)

    def upsert_profile_field(self, field: str, value: str) -> None:
        """Write a single profile field (identity or strategy) to the unified
        row. Used by the idea generator to save strategy fields one at a time."""
        allowed = set(CreatorProfile().as_dict().keys())
        if field not in allowed:
            raise ValueError(f"Unknown profile field: {field!r}")
        if settings.database_url:
            with get_sync_session() as s:
                s.execute(
                    pg_insert(CreatorProfileModel)
                    .values(id=1, **{field: value}, updated_at=func.now())
                    .on_conflict_do_update(
                        index_elements=["id"],
                        set_={field: value, "updated_at": func.now()},
                    )
                )
                s.commit()
        else:
            self._profile_mem[field] = value

    async def clear_profile(self) -> None:
        """Null out every identity + strategy field on the single profile row
        (or the in-memory dict). Knowledge base / captures / audience
        analysis are separate tables and are not touched here."""
        blank = {f: None for f in PROFILE_FIELDS}
        if settings.database_url:
            async with get_async_session() as s:
                await s.execute(
                    pg_insert(CreatorProfileModel)
                    .values(id=1, **blank, updated_at=func.now())
                    .on_conflict_do_update(
                        index_elements=["id"],
                        set_=dict(**blank, updated_at=func.now()),
                    )
                )
                await s.commit()
        else:
            self._profile_mem = {}

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

    async def clear_knowledge(self) -> None:
        """Delete every knowledge-base entry (full wipe)."""
        if settings.database_url:
            from sqlalchemy import delete
            async with get_async_session() as s:
                await s.execute(delete(CreatorKnowledgeModel))
                await s.commit()
        else:
            self._knowledge_mem = []


# Process-wide singleton — see application/creators/creator_service.py
creator_repository = CreatorRepository()
