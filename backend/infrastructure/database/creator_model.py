"""
creator_model.py
══════════════════
SQLAlchemy ORM models backing the creator domain: the public creator
profile (single row) and the knowledge base entries the creator teaches
the viewer-reply agent.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.db import Base


class CreatorProfileModel(Base):
    """Unified creator profile. Single row (id = 1). Holds both the public
    identity (name, bio, cta, email) and the content-strategy fields (niche,
    sub_niche, target_audience, platforms, content_style, monetization) that
    previously lived in the separate creator_idea_profile table."""
    __tablename__ = "creator_profile"

    id:         Mapped[int]            = mapped_column(Integer, primary_key=True, default=1)
    name:       Mapped[Optional[str]]  = mapped_column(String(255))
    bio:        Mapped[Optional[str]]  = mapped_column(Text)
    cta:        Mapped[Optional[str]]  = mapped_column(Text)
    email:      Mapped[Optional[str]]  = mapped_column(String(320))
    # ── content strategy (merged in from the former CreatorIdeaProfile) ──────
    niche:           Mapped[Optional[str]] = mapped_column(Text)
    sub_niche:       Mapped[Optional[str]] = mapped_column(Text)
    target_audience: Mapped[Optional[str]] = mapped_column(Text)
    platforms:       Mapped[Optional[str]] = mapped_column(Text)
    content_style:   Mapped[Optional[str]] = mapped_column(Text)
    monetization:    Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())


class CreatorKnowledgeModel(Base):
    """Facts the creator has taught the viewer-reply agent."""
    __tablename__ = "creator_knowledge"
    __table_args__ = (UniqueConstraint("topic"),)

    id:         Mapped[str]      = mapped_column(String(36), primary_key=True,
                                                  default=lambda: str(uuid.uuid4()))
    topic:      Mapped[str]      = mapped_column(Text, nullable=False)
    content:    Mapped[str]      = mapped_column(Text, nullable=False)
    source:     Mapped[str]      = mapped_column(String(50), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
