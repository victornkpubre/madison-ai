"""
capture_model.py
══════════════════
SQLAlchemy ORM model for persisted capture sessions.

NOTE — this table is new. In the original flat codebase, captured viewer
records lived only inside LangGraph's checkpointed graph state for the
duration of a single assistant conversation (assistant_graph.py's
`records` field) and were never written to a durable table of their own.

Persisting a summary of each completed capture session here is additive:
it does not change the capture loop's behaviour, it just gives the
creator a durable, queryable record of what has been captured over time
(exposed via GET /captures).
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.db import Base


class CaptureSessionModel(Base):
    __tablename__ = "capture_sessions"

    id:             Mapped[str]            = mapped_column(String(36), primary_key=True,
                                                            default=lambda: str(uuid.uuid4()))
    fields:         Mapped[str]            = mapped_column(Text, nullable=False)   # comma-separated
    target:         Mapped[int]            = mapped_column(Integer, default=0)
    collected:      Mapped[int]            = mapped_column(Integer, default=0)
    records_json:   Mapped[str]            = mapped_column(Text, default="[]")
    stopped_reason: Mapped[Optional[str]]  = mapped_column(String(100))
    created_at:     Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())
