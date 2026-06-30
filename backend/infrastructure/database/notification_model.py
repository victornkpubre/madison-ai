"""
notification_model.py
══════════════════════
SQLAlchemy ORM models backing the notifications integrations: the
Telegram user registry, connected SMTP/IMAP email accounts, and saved
message templates.

These tables are owned conceptually by the integrations that use them
(infrastructure/integrations/telegram_client.py, email_client.py, and
infrastructure/ai/templates.py) but declared together here so schema
creation has one obvious home.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.db import Base


class TelegramUserModel(Base):
    __tablename__ = "telegram_users"

    id:               Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int]            = mapped_column(BigInteger, unique=True, nullable=False)
    first_name:       Mapped[Optional[str]]  = mapped_column(String(255))
    last_name:        Mapped[Optional[str]]  = mapped_column(String(255))
    username:         Mapped[Optional[str]]  = mapped_column(String(255))
    registered_at:    Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen:        Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmailAccountModel(Base):
    __tablename__ = "email_accounts"

    id:           Mapped[str]            = mapped_column(String(36), primary_key=True,
                                                          default=lambda: str(uuid.uuid4()))
    email:        Mapped[str]            = mapped_column(String(320), unique=True, nullable=False)
    provider:     Mapped[str]            = mapped_column(String(20),  nullable=False)  # always "smtp"
    display_name: Mapped[Optional[str]]  = mapped_column(String(255))
    access_token: Mapped[str]            = mapped_column(Text, nullable=False)          # SMTP password
    smtp_host:    Mapped[Optional[str]]  = mapped_column(String(255))
    smtp_port:    Mapped[Optional[int]]  = mapped_column(Integer)
    imap_host:    Mapped[Optional[str]]  = mapped_column(String(255))
    imap_port:    Mapped[Optional[int]]  = mapped_column(Integer)
    created_at:   Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:   Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageTemplateModel(Base):
    __tablename__ = "message_templates"
    __table_args__ = (UniqueConstraint("name"),)

    id:         Mapped[str]            = mapped_column(String(36), primary_key=True,
                                                        default=lambda: str(uuid.uuid4()))
    name:       Mapped[str]            = mapped_column(Text, nullable=False)
    channel:    Mapped[str]            = mapped_column(String(50),  default="email")
    subject:    Mapped[Optional[str]]  = mapped_column(Text)
    body:       Mapped[str]            = mapped_column(Text, nullable=False)
    variables:  Mapped[Optional[str]]  = mapped_column(Text)   # JSON list stored as text
    is_default: Mapped[bool]           = mapped_column(Integer, default=0)
    created_at: Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())
