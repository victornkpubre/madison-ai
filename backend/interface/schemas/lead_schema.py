"""
lead_schema.py
══════════════
Pydantic request/response models for the manual leads endpoints
(see interface/api/leads.py).
"""
from __future__ import annotations

from pydantic import BaseModel


class LeadRequest(BaseModel):
    name: str
    contact_type: str            # email | telegram | phone | other
    contact_value: str
    notes: str | None = None


class LeadResponse(BaseModel):
    id: str | None = None
    name: str
    contact_type: str
    contact_value: str
    notes: str | None = None
    source: str
    created_at: str | None = None
