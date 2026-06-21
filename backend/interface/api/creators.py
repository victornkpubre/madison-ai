"""
creators.py (interface/api)
══════════════════════════════
Creator profile and knowledge-base endpoints.

  POST/GET /creator/profile
  POST     /knowledge
  POST     /knowledge/bulk
  GET      /knowledge
  DELETE   /knowledge/{topic}
"""
from __future__ import annotations

from fastapi import APIRouter

from backend.composition import creator_service
from backend.interface.schemas.creator_schema import (
    BulkKnowledgeRequest, CreatorProfileRequest, KnowledgeEntry,
)

router = APIRouter()


# ── creator profile ───────────────────────────────────────────────────────────

@router.post("/creator/profile")
async def set_creator_profile(req: CreatorProfileRequest):
    """Save the creator profile used in default message templates."""
    profile = await creator_service.save_profile(req.name, req.bio, req.cta, req.email)
    return {"ok": True, "profile": profile.as_dict()}


@router.get("/creator/profile")
async def get_creator_profile_endpoint():
    """Return the stored creator profile."""
    profile = await creator_service.get_profile()
    return profile.as_dict()


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
    creator_service.save_knowledge(req.topic, req.content, source="manual")
    return {"ok": True, "topic": req.topic}


@router.post("/knowledge/bulk")
async def add_knowledge_bulk(req: BulkKnowledgeRequest):
    """Add multiple knowledge entries at once."""
    for e in req.entries:
        creator_service.save_knowledge(e.topic, e.content, source="bulk")
    return {"ok": True, "count": len(req.entries)}


@router.get("/knowledge")
async def list_knowledge():
    """Return all stored knowledge entries."""
    entries = creator_service.list_knowledge(100)
    return {"entries": [{"topic": e.topic, "content": e.content} for e in entries]}


@router.delete("/knowledge/{topic}")
async def delete_knowledge_entry(topic: str):
    """Delete a knowledge entry by topic."""
    await creator_service.delete_knowledge(topic)
    return {"ok": True, "deleted": topic}
