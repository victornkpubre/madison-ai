"""
lead_model.py
═════════════
SQLAlchemy ORM model for manually-entered leads — see
domain/entities/lead_entity.py and infrastructure/repositories/lead_repository.py.

Deliberately a separate table from capture_sessions (capture_model.py):
that table holds batches of records pulled from the live-stream chat
overlay; this one holds individual contacts the creator typed in
themselves (a friend referral, a DM, someone met in person).
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.db import Base


class LeadModel(Base):
    __tablename__ = "leads"

    id:            Mapped[str]           = mapped_column(String(36), primary_key=True,
                                                          default=lambda: str(uuid.uuid4()))
    name:          Mapped[str]           = mapped_column(Text, nullable=False)
    contact_type:  Mapped[str]           = mapped_column(String(20), nullable=False)  # email|telegram|phone|other
    contact_value: Mapped[str]           = mapped_column(Text, nullable=False)
    notes:         Mapped[Optional[str]] = mapped_column(Text)
    source:        Mapped[str]           = mapped_column(String(50), default="manual")
    created_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())
