from __future__ import annotations

from backend.domain.entities.creator_entity import CreatorProfile, CreatorKnowledgeEntry
from backend.domain.repository.creator_repository_interface import ICreatorRepository


class CreatorService:

    def __init__(self, repo: ICreatorRepository):
        self._repo = repo

    # ── profile ────────────────────────────────────────────────────────────
    async def get_profile(self) -> CreatorProfile:
        return await self._repo.get_profile()

    async def save_profile(self, name: str, bio: str, cta: str,
                            email: str | None = None) -> CreatorProfile:
        profile = CreatorProfile(name=name, bio=bio, cta=cta, email=email)
        await self._repo.save_profile(profile)
        return profile

    # ── knowledge base ─────────────────────────────────────────────────────
    def list_knowledge(self, limit: int = 60) -> list[CreatorKnowledgeEntry]:
        return self._repo.list_knowledge(limit)

    def save_knowledge(self, topic: str, content: str, source: str = "manual") -> None:
        self._repo.upsert_knowledge(topic, content, source)

    async def delete_knowledge(self, topic: str) -> None:
        await self._repo.delete_knowledge(topic)
