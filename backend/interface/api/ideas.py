"""
ideas.py (interface/api)
═══════════════════════════
Idea-generator data endpoints. Conversational idea collection goes
through POST /chat; these endpoints expose stored data for inspection.

  POST /ideas/signals
  GET  /ideas/profile
  GET  /ideas/analytics
"""
from __future__ import annotations

from fastapi import APIRouter

from composition import idea_service
from interface.schemas.idea_schema import SignalIngestRequest

router = APIRouter()


@router.post("/ideas/signals")
async def ingest_signals(req: SignalIngestRequest):
    """
    Ingest raw audience messages for analysis.
    Call this with Telegram messages, email replies, or captured chat content.
    The analyze_audience() tool in the idea graph will process them.
    """
    count = 0
    for msg in req.messages:
        if msg.strip():
            idea_service.ingest_signal(msg.strip(), req.source, req.session_id)
            count += 1
    return {"ok": True, "ingested": count, "source": req.source}


@router.get("/ideas/profile")
async def get_idea_profile():
    """Return the current creator idea profile."""
    return idea_service.load_profile().strategy_dict()


@router.get("/ideas/analytics")
async def get_topic_analytics():
    """Return topic analytics sorted by frequency."""
    return {"topics": idea_service.load_topic_analytics(50)}
