"""
lead_entity.py
══════════════
A lead collected from TEXT — a friend referral, a DM, someone met in
person — as opposed to domain/entities/capture_entity.py's CaptureSession,
which is populated by reading the live-stream chat overlay. Both end up
feeding the same outreach tools (Telegram / email), but they enter the
system through different doors and so get their own small entity here
rather than being shoehorned into CaptureRecord.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

CONTACT_TYPES: tuple[str, ...] = ("email", "telegram", "phone", "other")


@dataclass
class Lead:
    """A single manually-entered lead.

    notes is free text the creator gives about this person — how they were
    referred, what they're interested in, where they were met. It is the
    only piece of per-lead context available to ground a follow-up message
    in something more specific than the creator's profile alone.
    """
    name: str
    contact_type: str          # one of CONTACT_TYPES
    contact_value: str         # the email / telegram username / phone number itself
    notes: str = ""
    source: str = "manual"     # manual | referral (creator can say which)
    id: Optional[str] = None
    created_at: Optional[datetime] = None

    def matches(self, identifier: str) -> bool:
        """Loose lookup so the creator can refer to a lead by name, id, or
        contact value in chat without needing to know which one was used."""
        ident = (identifier or "").strip().lower()
        if not ident:
            return False
        return ident in {
            (self.id or "").lower(),
            self.name.strip().lower(),
            self.contact_value.strip().lower(),
        }

    def display(self) -> str:
        note = f" — {self.notes}" if self.notes else ""
        return f"{self.name} ({self.contact_type}: {self.contact_value}){note}"
