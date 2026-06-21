"""
creator_schema.py
═══════════════════
Pydantic request/response models for the creator profile and knowledge
base endpoints (see interface/api/creators.py).
"""
from pydantic import BaseModel


class CreatorProfileRequest(BaseModel):
    name:  str
    bio:   str
    cta:   str            # e.g. "Follow me @victor on TikTok"
    email: str | None = None   # connected sender email for outbound messages


class KnowledgeEntry(BaseModel):
    topic:   str
    content: str


class BulkKnowledgeRequest(BaseModel):
    entries: list[KnowledgeEntry]
