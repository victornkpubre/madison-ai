"""
notification_schemas.py
═════════════════════
Structured-output schema(s) used by NotificationService when asking the
LLM for a draft, via with_structured_output(...).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DraftedTemplate(BaseModel):
    subject: str | None = Field(
        default=None,
        description="Email subject line. Leave null for Telegram (no subject).",
    )
    body: str = Field(description="The drafted message body.")
