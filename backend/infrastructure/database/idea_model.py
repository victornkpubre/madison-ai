"""
idea_model.py
══════════════
SQLAlchemy ORM models backing the idea-generator domain: the content
strategy profile, content history, raw audience signals, and the topic
analytics derived from them.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime, Float, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.database.db import Base


class CreatorIdeaProfileModel(Base):
    """Idea-generator profile — niche, style, audience. Single row (id = 1)."""
    __tablename__ = "creator_idea_profile"

    id:              Mapped[int]            = mapped_column(Integer, primary_key=True, default=1)
    niche:           Mapped[Optional[str]]  = mapped_column(Text)
    sub_niche:       Mapped[Optional[str]]  = mapped_column(Text)
    target_audience: Mapped[Optional[str]]  = mapped_column(Text)
    platforms:       Mapped[Optional[str]]  = mapped_column(Text)
    content_style:   Mapped[Optional[str]]  = mapped_column(Text)
    monetization:    Mapped[Optional[str]]  = mapped_column(Text)
    updated_at:      Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContentHistoryModel(Base):
    """Past videos, posts, and live sessions — used to avoid idea repetition."""
    __tablename__ = "content_history"

    id:           Mapped[str]            = mapped_column(String(36), primary_key=True,
                                                          default=lambda: str(uuid.uuid4()))
    title:        Mapped[str]            = mapped_column(Text, nullable=False)
    topic:        Mapped[Optional[str]]  = mapped_column(Text)
    content_type: Mapped[Optional[str]]  = mapped_column(String(50))   # video|photo|live|digital
    platform:     Mapped[Optional[str]]  = mapped_column(String(100))
    posted_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at:   Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())


class AudienceSignalModel(Base):
    """Raw viewer messages collected for audience intelligence analysis."""
    __tablename__ = "audience_signals"

    id:          Mapped[str]            = mapped_column(String(36), primary_key=True,
                                                         default=lambda: str(uuid.uuid4()))
    content:     Mapped[str]            = mapped_column(Text, nullable=False)
    source:      Mapped[str]            = mapped_column(String(50),  default="telegram")
    session_id:  Mapped[str]            = mapped_column(String(255), default="")
    signal_type: Mapped[Optional[str]]  = mapped_column(String(50))   # question|request|positive|negative|neutral
    topic:       Mapped[Optional[str]]  = mapped_column(Text)
    timestamp:   Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())


class TopicAnalyticModel(Base):
    """Per-topic metrics derived from audience signal analysis."""
    __tablename__ = "topic_analytics"
    __table_args__ = (UniqueConstraint("topic"),)

    id:              Mapped[str]   = mapped_column(String(36), primary_key=True,
                                                    default=lambda: str(uuid.uuid4()))
    topic:           Mapped[str]   = mapped_column(Text, nullable=False)
    frequency:       Mapped[int]   = mapped_column(Integer, default=1)
    velocity:        Mapped[float] = mapped_column(Float,   default=0.0)
    curiosity_score: Mapped[float] = mapped_column(Float,   default=0.0)
    question_count:  Mapped[int]   = mapped_column(Integer, default=0)
    request_count:   Mapped[int]   = mapped_column(Integer, default=0)
    sentiment:       Mapped[float] = mapped_column(Float,   default=0.0)
    last_seen:       Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AudienceAnalysisModel(Base):
    """Latest synthesized audience summary + content/knowledge gaps produced
    by audience_analysis_graph. Single row (id = 1) — each new analysis
    overwrites the last; idea_generation_graph reads it back to ground
    generate_ideas(). Gaps are stored as a newline-joined string rather than
    a separate table since they're only ever read back as a whole list."""
    __tablename__ = "audience_analysis"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, default=1)
    summary:    Mapped[str]      = mapped_column(Text, nullable=False, default="")
    gaps:       Mapped[str]      = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
