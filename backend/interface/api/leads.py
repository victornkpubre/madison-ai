"""
leads.py (interface/api)
═════════════════════════
Manually-entered lead endpoints — leads collected from text (referrals,
DMs, in-person contacts) rather than the live-stream OCR capture pipeline
exposed in captures.py. Conversational add/list/delete/follow-up is also
available via chat through application/agents/graphs/tools/lead_tools.py;
these endpoints expose the same underlying data over REST, same role
creators.py plays for the profile/knowledge base.

  POST   /leads
  GET    /leads
  DELETE /leads/{identifier}
"""
from __future__ import annotations

from fastapi import APIRouter

from infrastructure.repositories.lead_repository import lead_repository
from interface.schemas.lead_schema import LeadRequest, LeadResponse

router = APIRouter()


def _to_response(lead) -> LeadResponse:
    return LeadResponse(
        id=lead.id, name=lead.name, contact_type=lead.contact_type,
        contact_value=lead.contact_value, notes=lead.notes or None,
        source=lead.source, created_at=str(lead.created_at) if lead.created_at else None,
    )


@router.post("/leads", response_model=LeadResponse)
async def add_lead_endpoint(req: LeadRequest):
    """Manually save a lead — same effect as the add_lead chat tool."""
    lead = lead_repository.add_lead(req.name, req.contact_type, req.contact_value,
                                    req.notes or "")
    return _to_response(lead)


@router.get("/leads", response_model=list[LeadResponse])
async def list_leads_endpoint(limit: int = 100):
    """Return the most recently added leads first."""
    return [_to_response(l) for l in lead_repository.list_leads(limit)]


@router.delete("/leads/{identifier}")
async def delete_lead_endpoint(identifier: str):
    """Delete a lead by id, name, or contact value."""
    ok = lead_repository.delete_lead(identifier)
    return {"ok": ok, "deleted": identifier if ok else None}
