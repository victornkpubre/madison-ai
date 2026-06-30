"""
captures.py (interface/api)
══════════════════════════════
New — read-only access to completed capture sessions.

The capture loop itself only ever runs through POST /chat + POST /resume
(it's driven entirely by interrupts inside the assistant graph). This
endpoint just exposes the durable record that capture_node now writes
via infrastructure/repositories/capture_repository.py once a session
finishes, so the creator (or the desktop app) can review what's been
captured without re-parsing chat history.

  GET /captures
"""
from __future__ import annotations

from fastapi import APIRouter

from infrastructure.repositories.capture_repository import capture_repository
from interface.schemas.capture_schema import CaptureSessionResponse

router = APIRouter()


@router.get("/captures", response_model=list[CaptureSessionResponse])
async def list_captures(limit: int = 20):
    """Return the most recently completed capture sessions."""
    return capture_repository.list_recent(limit)
