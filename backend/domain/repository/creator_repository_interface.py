"""
creator_repository_interface.py
═══════════════════════
Abstract contract for persisting creator profiles and creator knowledge
entries. The application layer (creator_service.py) depends on this
interface, not on any concrete database technology. The concrete
implementation lives in infrastructure/repositories/creator_repository.py
and may store data in Postgres (via SQLAlchemy) or, when no DATABASE_URL
is configured, in memory.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from domain.entities.creator_entity import CreatorKnowledgeEntry, CreatorProfile


class ICreatorRepository(ABC):

    # ── profile ────────────────────────────────────────────────────────────
    @abstractmethod
    async def get_profile(self) -> CreatorProfile:
        """Return the stored creator profile (empty CreatorProfile if unset)."""
        raise NotImplementedError

    @abstractmethod
    def get_profile_sync(self) -> CreatorProfile:
        """Synchronous read of the unified profile, for sync callers."""
        raise NotImplementedError

    @abstractmethod
    async def save_profile(self, profile: CreatorProfile) -> None:
        """Persist the creator profile's identity fields (single-row upsert)."""
        raise NotImplementedError

    @abstractmethod
    def upsert_profile_field(self, field: str, value: str) -> None:
        """Write a single profile field (identity or strategy) to the unified row."""
        raise NotImplementedError

    @abstractmethod
    async def clear_profile(self) -> None:
        """Reset every profile field (identity AND content-strategy) back to
        empty, so onboarding starts over from scratch. Leaves the knowledge
        base, captured records, and audience analysis untouched — those are
        separate stores and this is a profile reset, not a full wipe."""
        raise NotImplementedError

    # ── knowledge base ─────────────────────────────────────────────────────
    @abstractmethod
    def list_knowledge(self, limit: int = 60) -> list[CreatorKnowledgeEntry]:
        """Return the most recently updated knowledge entries."""
        raise NotImplementedError

    @abstractmethod
    def upsert_knowledge(self, topic: str, content: str, source: str = "manual") -> None:
        """Create or update a knowledge entry, keyed by (normalised) topic."""
        raise NotImplementedError

    @abstractmethod
    async def delete_knowledge(self, topic: str) -> None:
        """Remove a knowledge entry by topic."""
        raise NotImplementedError

    @abstractmethod
    async def clear_knowledge(self) -> None:
        """Remove ALL knowledge entries — the full-wipe counterpart to
        delete_knowledge (which removes a single topic)."""
        raise NotImplementedError
