"""
idea_repository_interface.py
═════════════════════
Abstract port for idea-generator persistence: the content-strategy
profile, content history, audience signals, and topic analytics.

IdeaService depends on this interface, not on the concrete
IdeaRepository, so the persistence backend (in-memory dict/list vs
SQLAlchemy) can be swapped without touching application logic — same
role ICreatorRepository plays for CreatorService.

infrastructure/repositories/idea_repository.py is the concrete adapter.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from domain.entities.creator_entity import CreatorProfile
from domain.entities.idea_entity import ContentHistoryItem


class IIdeaRepository(ABC):

    # ── creator profile (unified) ──────────────────────────────────────────
    @abstractmethod
    def upsert_profile_field(self, field: str, value: str) -> None: ...

    @abstractmethod
    def load_profile(self) -> CreatorProfile: ...

    # ── content history ───────────────────────────────────────────────────
    @abstractmethod
    def insert_content_item(self, title: str, topic: str,
                            content_type: str, platform: str = "") -> None: ...

    @abstractmethod
    def load_content_topics(self, limit: int = 50) -> list[str]: ...

    @abstractmethod
    def load_content_references(self, limit: int = 30) -> list[ContentHistoryItem]: ...

    @abstractmethod
    def load_content_history_summary(self, limit: int = 50) -> list[dict]: ...

    # ── audience signals ──────────────────────────────────────────────────
    @abstractmethod
    def insert_signal(self, content: str, source: str = "telegram",
                      session_id: str = "") -> None: ...

    @abstractmethod
    def load_unanalysed_signals(self, limit: int = 200) -> list[dict]: ...

    @abstractmethod
    def load_signals_by_session(self, session_id: str, limit: int = 500) -> list[dict]: ...

    @abstractmethod
    def update_signal_topic(self, signal: dict, signal_type: str, topic: str) -> None: ...

    @abstractmethod
    def load_signals_by_topic(self, topic: str,
                              signal_types: list[str] | None = None,
                              limit: int = 5) -> list[str]: ...

    # ── topic analytics ───────────────────────────────────────────────────
    @abstractmethod
    def upsert_topic_analytics(self, topic: str, frequency: int,
                               velocity: float, curiosity_score: float,
                               question_count: int, request_count: int,
                               sentiment: float) -> None: ...

    @abstractmethod
    def load_topic_analytics(self, limit: int = 20) -> list[dict]: ...

    # ── audience analysis (synthesized summary, distinct from raw signals) ──
    @abstractmethod
    def save_audience_analysis(self, summary: str, gaps: list[str]) -> None: ...

    @abstractmethod
    def load_latest_audience_analysis(self) -> dict | None: ...
