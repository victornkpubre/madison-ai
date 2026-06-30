"""
lead_repository.py
═══════════════════
Concrete implementation of ILeadRepository.

Same dual-mode pattern as every other repository in this codebase:
SQLAlchemy (sync session — matches capture_repository.py /
creator_repository.py's knowledge-base methods, since these are called
from sync-style LangChain @tool functions) when DATABASE_URL is set,
otherwise an in-memory list for the life of the process.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, func, or_, select

from config import settings
from domain.entities.lead_entity import Lead
from domain.repository.lead_repository_interface import ILeadRepository
from infrastructure.database.db import get_sync_session
from infrastructure.database.lead_model import LeadModel


class LeadRepository(ILeadRepository):

    def __init__(self):
        self._leads_mem: list[dict] = []

    @staticmethod
    def _row_to_lead(row) -> Lead:
        return Lead(id=row.id, name=row.name, contact_type=row.contact_type,
                    contact_value=row.contact_value, notes=row.notes or "",
                    source=row.source, created_at=row.created_at)

    def add_lead(self, name: str, contact_type: str, contact_value: str,
                 notes: str = "", source: str = "manual") -> Lead:
        if settings.database_url:
            with get_sync_session() as s:
                row = LeadModel(name=name, contact_type=contact_type,
                                contact_value=contact_value, notes=notes or None,
                                source=source)
                s.add(row)
                s.commit()
                s.refresh(row)
                return self._row_to_lead(row)
        record = {
            "id": str(uuid.uuid4()), "name": name, "contact_type": contact_type,
            "contact_value": contact_value, "notes": notes, "source": source,
            "created_at": datetime.now(timezone.utc),
        }
        self._leads_mem.append(record)
        return Lead(**record)

    def list_leads(self, limit: int = 100) -> list[Lead]:
        if settings.database_url:
            with get_sync_session() as s:
                rows = s.execute(
                    select(LeadModel).order_by(LeadModel.created_at.desc()).limit(limit)
                ).scalars().all()
            return [self._row_to_lead(r) for r in rows]
        return [Lead(**r) for r in list(reversed(self._leads_mem))[:limit]]

    def find_lead(self, identifier: str) -> Optional[Lead]:
        ident = (identifier or "").strip().lower()
        if not ident:
            return None
        if settings.database_url:
            with get_sync_session() as s:
                row = s.execute(
                    select(LeadModel)
                    .where(or_(LeadModel.id == identifier,
                               func.lower(LeadModel.name) == ident,
                               func.lower(LeadModel.contact_value) == ident))
                    .order_by(LeadModel.created_at.desc())
                ).scalars().first()
            return self._row_to_lead(row) if row else None
        for r in reversed(self._leads_mem):
            lead = Lead(**r)
            if lead.matches(identifier):
                return lead
        return None

    def delete_lead(self, identifier: str) -> bool:
        lead = self.find_lead(identifier)
        if not lead:
            return False
        if settings.database_url:
            with get_sync_session() as s:
                s.execute(delete(LeadModel).where(LeadModel.id == lead.id))
                s.commit()
            return True
        before = len(self._leads_mem)
        self._leads_mem = [r for r in self._leads_mem if r["id"] != lead.id]
        return len(self._leads_mem) < before


# Process-wide singleton — wired into LeadService by backend/composition.py
lead_repository = LeadRepository()
