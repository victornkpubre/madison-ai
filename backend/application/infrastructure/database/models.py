"""
SQLAlchemy ORM models for every table, grouped by domain.

  identity        — TelegramUser
  email           — EmailAccount, MessageTemplate
  creator         — CreatorProfile, CreatorIdeaProfile, CreatorKnowledge
  content/audience — ContentHistory, AudienceSignal, TopicAnalytic
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, DateTime, Float, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ── identity ──────────────────────────────────────────────────────────────────

class TelegramUser(Base):
    __tablename__ = "telegram_users"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int]           = mapped_column(BigInteger, unique=True, nullable=False)
    first_name:       Mapped[Optional[str]] = mapped_column(String(255))
    last_name:        Mapped[Optional[str]] = mapped_column(String(255))
    username:         Mapped[Optional[str]] = mapped_column(String(255))
    registered_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen:        Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── email ─────────────────────────────────────────────────────────────────────

class EmailAccount(Base):
    __tablename__ = "email_accounts"

    id:           Mapped[str]           = mapped_column(String(36), primary_key=True,
                                                         default=lambda: str(uuid.uuid4()))
    email:        Mapped[str]           = mapped_column(String(320), unique=True, nullable=False)
    provider:     Mapped[str]           = mapped_column(String(20),  nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    access_token: Mapped[str]           = mapped_column(Text, nullable=False)   # SMTP password
    smtp_host:    Mapped[Optional[str]] = mapped_column(String(255))
    smtp_port:    Mapped[Optional[int]] = mapped_column(Integer)
    imap_host:    Mapped[Optional[str]] = mapped_column(String(255))
    imap_port:    Mapped[Optional[int]] = mapped_column(Integer)
    created_at:   Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:   Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageTemplate(Base):
    __tablename__ = "message_templates"
    __table_args__ = (UniqueConstraint("name"),)

    id:         Mapped[str]           = mapped_column(String(36), primary_key=True,
                                                       default=lambda: str(uuid.uuid4()))
    name:       Mapped[str]           = mapped_column(Text, nullable=False)
    channel:    Mapped[str]           = mapped_column(String(50), default="email")
    subject:    Mapped[Optional[str]] = mapped_column(Text)
    body:       Mapped[str]           = mapped_column(Text, nullable=False)
    variables:  Mapped[Optional[str]] = mapped_column(Text)
    is_default: Mapped[int]           = mapped_column(Integer, default=0)
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── creator ───────────────────────────────────────────────────────────────────

class CreatorProfile(Base):
    """Public profile — name, bio, cta. Single row (id = 1)."""
    __tablename__ = "creator_profile"

    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, default=1)
    name:       Mapped[Optional[str]] = mapped_column(String(255))
    bio:        Mapped[Optional[str]] = mapped_column(Text)
    cta:        Mapped[Optional[str]] = mapped_column(Text)
    email:      Mapped[Optional[str]] = mapped_column(String(320))
    updated_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())


class CreatorIdeaProfile(Base):
    """Idea-generator profile — niche, style, audience. Single row (id = 1)."""
    __tablename__ = "creator_idea_profile"

    id:              Mapped[int]           = mapped_column(Integer, primary_key=True, default=1)
    niche:           Mapped[Optional[str]] = mapped_column(Text)
    sub_niche:       Mapped[Optional[str]] = mapped_column(Text)
    target_audience: Mapped[Optional[str]] = mapped_column(Text)
    platforms:       Mapped[Optional[str]] = mapped_column(Text)
    content_style:   Mapped[Optional[str]] = mapped_column(Text)
    monetization:    Mapped[Optional[str]] = mapped_column(Text)
    updated_at:      Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())


class CreatorKnowledge(Base):
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


# ── content and audience ──────────────────────────────────────────────────────

class ContentHistory(Base):
    """Past videos, posts, and live sessions."""
    __tablename__ = "content_history"

    id:           Mapped[str]           = mapped_column(String(36), primary_key=True,
                                                         default=lambda: str(uuid.uuid4()))
    title:        Mapped[str]           = mapped_column(Text, nullable=False)
    topic:        Mapped[Optional[str]] = mapped_column(Text)
    content_type: Mapped[Optional[str]] = mapped_column(String(50))
    platform:     Mapped[Optional[str]] = mapped_column(String(100))
    posted_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at:   Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())


class AudienceSignal(Base):
    """Raw viewer messages collected for audience intelligence analysis."""
    __tablename__ = "audience_signals"

    id:          Mapped[str]           = mapped_column(String(36), primary_key=True,
                                                        default=lambda: str(uuid.uuid4()))
    content:     Mapped[str]           = mapped_column(Text, nullable=False)
    source:      Mapped[str]           = mapped_column(String(50), default="telegram")
    session_id:  Mapped[str]           = mapped_column(String(255), default="")
    signal_type: Mapped[Optional[str]] = mapped_column(String(50))
    topic:       Mapped[Optional[str]] = mapped_column(Text)
    timestamp:   Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())


class TopicAnalytic(Base):
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
