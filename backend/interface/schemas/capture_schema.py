"""
capture_schema.py
════════════════════
Response model for GET /captures (see interface/api/captures.py).

New — the original codebase never exposed completed capture sessions
over REST; they only existed transiently inside the assistant graph's
state. This schema describes the durable record now written by
infrastructure/repositories/capture_repository.py.
"""
from pydantic import BaseModel


class CaptureSessionResponse(BaseModel):
    id: str | None = None
    fields: list[str]
    target: int
    collected: int
    records: list[dict]
    stopped_reason: str | None = None
    created_at: str | None = None
