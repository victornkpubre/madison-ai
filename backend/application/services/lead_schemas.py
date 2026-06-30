"""
lead_schemas.py
═══════════════
Structured-output contract for the lead follow-up drafting LLM call made
by LeadService. Kept separate from domain/entities/lead_entity.py: this is
an LLM I/O shape, not a persisted domain entity — same split idea_schemas.py
has from idea_entity.py.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DraftedFollowup(BaseModel):
    subject: Optional[str] = Field(
        default=None,
        description="Short email subject line; null when this is a Telegram/chat send (no subject line)",
    )
    body: str = Field(description="The full follow-up message body")
