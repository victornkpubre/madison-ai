"""
idea_schema.py
════════════════
Pydantic request models for the idea-generator data endpoints
(see interface/api/ideas.py).
"""
from pydantic import BaseModel


class SignalIngestRequest(BaseModel):
    messages:   list[str]
    source:     str = "telegram"
    session_id: str = ""
