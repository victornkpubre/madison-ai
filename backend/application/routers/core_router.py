from fastapi import APIRouter

from backend.application.requests import KnowledgeEntry, BulkKnowledgeRequest, SignalIngestRequest
from backend.config import settings
from database import delete_knowledge
from graph import load_knowledge_entries, save_knowledge_entry, save_knowledge_entry
from idea_tools import ingest_signal
from idea_tools import load_profile
from idea_tools import load_topic_analytics

router = APIRouter()

# ── creator knowledge base ───────────────────────────────────────────────────
# The viewer-reply agent searches these entries when drafting replies.
# Add anything the creator wants the agent to know: their story, common
# answers, opinions in their niche, content links, resources, etc.

@router.post("/knowledge")
async def add_knowledge_entry(req: KnowledgeEntry):
    """
    Add or update a knowledge entry for the viewer-reply agent.
    The agent uses these to answer viewer questions accurately.

    Examples of useful entries:
      topic='my setup'      content='I film on iPhone 15 Pro, edit in CapCut'
      topic='my story'      content='Started creating in 2022 after losing my job...'
      topic='next stream'   content='Every Friday at 8pm UK time on TikTok Live'
      topic='my course'     content='I teach budget meal prep. Join at mylink.com/course'
    """
    save_knowledge_entry(req.topic, req.content, source="manual")
    return {"ok": True, "topic": req.topic}


@router.post("/knowledge/bulk")
async def add_knowledge_bulk(req: BulkKnowledgeRequest):
    """Add multiple knowledge entries at once."""
    for e in req.entries:
        save_knowledge_entry(e.topic, e.content, source="bulk")
    return {"ok": True, "count": len(req.entries)}


@router.get("/knowledge")
async def list_knowledge():
    """Return all stored knowledge entries."""
    return {"entries": load_knowledge_entries(100)}


@router.delete("/knowledge/{topic}")
async def delete_knowledge_entry(topic: str):
    """Delete a knowledge entry by topic."""
    if settings.database_url:
        await delete_knowledge(topic)
    return {"ok": True, "deleted": topic}

# ── idea generator data endpoints ────────────────────────────────────────────
# Conversational idea collection goes through POST /chat.
# These endpoints expose stored data for inspection.

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
            ingest_signal(msg.strip(), req.source, req.session_id)
            count += 1
    return {"ok": True, "ingested": count, "source": req.source}


@router.get("/ideas/profile")
async def get_idea_profile():
    """Return the current creator idea profile."""
    return load_profile()


@router.get("/ideas/analytics")
async def get_topic_analytics():
    """Return topic analytics sorted by frequency."""
    return {"topics": load_topic_analytics(50)}
