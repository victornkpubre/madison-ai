"""
lead_repository_interface.py
═════════════════════════════
Abstract contract for persisting manually-entered leads (see
domain/entities/lead_entity.py). LeadService depends on this interface,
not on any concrete database technology — same pattern as
ICreatorRepository / IIdeaRepository. The concrete adapter lives in
infrastructure/repositories/lead_repository.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from domain.entities.lead_entity import Lead


class ILeadRepository(ABC):

    @abstractmethod
    def add_lead(self, name: str, contact_type: str, contact_value: str,
                 notes: str = "", source: str = "manual") -> Lead:
        """Create a new lead record."""
        raise NotImplementedError

    @abstractmethod
    def list_leads(self, limit: int = 100) -> list[Lead]:
        """Return the most recently added leads first."""
        raise NotImplementedError

    @abstractmethod
    def find_lead(self, identifier: str) -> Optional[Lead]:
        """Look up a lead by id, name, or contact value (case-insensitive).
        Returns the most recently added match if more than one exists."""
        raise NotImplementedError

    @abstractmethod
    def delete_lead(self, identifier: str) -> bool:
        """Delete a lead by id, name, or contact value. Returns True if a
        matching lead was found and removed."""
        raise NotImplementedError
