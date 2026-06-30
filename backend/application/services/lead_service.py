"""
lead_service.py
═══════════════
Application service for manually-entered leads: capture (collected from
text — a friend referral, a DM, someone met in person — rather than the
live-stream OCR capture pipeline in assistant_graph.py / capture_repository.py)
plus drafting and sending a personalized follow-up.

Depends on ILeadRepository, IEmailRepository, and ITelegramRepository (never
on the concrete infrastructure modules directly), and on IdeaService for the
creator's profile + content history — the same data reply_graph.py's
build_system_prompt() and idea_generation_graph.py's draft_ideas() already
read from, so a lead follow-up is grounded the same way the rest of the
app's outbound copy is.
"""
from __future__ import annotations

from typing import Optional

from application.agents.resilience import invoke_llm
from application.services.idea_service import IdeaService
from application.services.lead_schemas import DraftedFollowup
from domain.entities.lead_entity import CONTACT_TYPES, Lead
from domain.repository.email_repository_interface import IEmailRepository
from domain.repository.lead_repository_interface import ILeadRepository
from domain.repository.telegram_repository_interface import ITelegramRepository


# Reserved example/placeholder values that can never be a real lead. RFC 2606
# reserves the example.* domains and the .test / .invalid / .example /
# .localhost TLDs precisely so they're safe stand-ins — so if one turns up as a
# lead's contact, the value was invented (a model filling a required field it
# wasn't actually given), not collected from the creator. We refuse to persist
# it rather than later email a fake address and report a phantom success.
_RESERVED_CONTACT_SUFFIXES = (
    "@example.com", "@example.net", "@example.org",
    ".example", ".test", ".invalid", ".localhost",
)
_PLACEHOLDER_CONTACTS = {
    "test@example.com", "user@example.com", "name@example.com",
    "email@example.com", "john@example.com", "jane@example.com",
    "1234567890", "+1234567890", "0000000000", "1111111111",
    "555-555-5555", "5555555555", "n/a", "none", "unknown", "tbd",
}


def _looks_like_placeholder(contact_value: str) -> bool:
    """True if contact_value is a reserved example domain or a canonical stub —
    i.e. a value no real lead would have, so it was almost certainly fabricated."""
    v = (contact_value or "").strip().lower()
    if v in _PLACEHOLDER_CONTACTS:
        return True
    return any(v.endswith(suffix) for suffix in _RESERVED_CONTACT_SUFFIXES)


class LeadService:

    def __init__(self, repo: ILeadRepository, idea_service: IdeaService,
                 email_repo: IEmailRepository, telegram_repo: ITelegramRepository):
        self._repo = repo
        self._idea = idea_service
        self._email = email_repo
        self._telegram = telegram_repo

    # ── capture ────────────────────────────────────────────────────────────
    def add_lead(self, name: str, contact_type: str, contact_value: str,
                 notes: str = "", source: str = "manual") -> str:
        name = (name or "").strip()
        contact_value = (contact_value or "").strip()
        if not name or not contact_value:
            return "✗ Not saved: a name and a way to contact them are both required."
        if _looks_like_placeholder(contact_value):
            return (
                f"✗ Not saved: \"{contact_value}\" looks like a placeholder/example "
                "value, not a real contact. The creator said they have the lead's "
                "details but may not have given you the actual address/number yet — "
                "ask them for the lead's real email, Telegram, or phone, then retry."
            )

        contact_type = (contact_type or "other").strip().lower()
        if contact_type not in CONTACT_TYPES:
            contact_type = "other"

        lead = self._repo.add_lead(name=name, contact_type=contact_type,
                                   contact_value=contact_value,
                                   notes=(notes or "").strip(), source=source)
        return f"✓ Saved lead: {lead.display()}"

    def list_leads(self, limit: int = 50) -> str:
        leads = self._repo.list_leads(limit)
        if not leads:
            return "No leads saved yet."
        lines = [f"{len(leads)} lead(s):"]
        lines += [f"{i}. {l.display()}" for i, l in enumerate(leads, 1)]
        return "\n".join(lines)

    def delete_lead(self, identifier: str) -> str:
        ok = self._repo.delete_lead((identifier or "").strip())
        return (f"✓ Deleted lead '{identifier}'." if ok
                else f"✗ No lead found matching '{identifier}'.")

    # ── follow-up ──────────────────────────────────────────────────────────
    async def draft_followup(self, identifier: str, purpose: str = "") -> dict:
        """Draft a follow-up grounded in the creator's profile and, if any
        exists, their content history. With no content history, the prompt
        explicitly tells the model not to invent or reference any — the
        draft stays a general, friendly introduction instead."""
        lead = self._repo.find_lead(identifier)
        if not lead:
            return {"ok": False, "error": f"No lead found matching '{identifier}'."}

        profile = self._idea.load_profile()   # unified row: identity + strategy fields
        history = self._idea.load_content_references(limit=5)
        history_text = "\n".join(
            f"- {h.title} ({h.content_type or 'content'})" for h in history
        )
        history_block = (
            f"Recent content the creator could optionally reference:\n{history_text}\n\n"
            if history_text else
            "The creator has no content history recorded yet — do NOT invent or "
            "reference any specific video, stream, or post. Keep this a general, "
            "friendly introduction instead.\n\n"
        )

        drafter_bind = lambda m: m.bind(temperature=0.4).with_structured_output(DraftedFollowup)
        prompt = (
            f"Draft a short, warm follow-up message to a lead the creator collected "
            f"manually (e.g. a friend's referral, a DM, someone met in person) — "
            f"this person has NOT necessarily seen the creator's content before, so "
            f"don't assume they already follow or watch them.\n\n"
            f"Lead's name: {lead.name}\n"
            f"How they came to be a lead: {lead.source}\n"
            f"Notes about them: {lead.notes or 'none provided'}\n\n"
            f"Creator's name: {profile.name or 'the creator'}\n"
            f"Creator's bio: {profile.bio or ''}\n"
            f"Creator's call to action: {profile.cta or ''}\n"
            f"Creator's niche: {profile.niche or ''}"
            f"{f' ({profile.sub_niche})' if profile.sub_niche else ''}\n\n"
            f"{history_block}"
            + (f"Purpose of this message: {purpose}\n\n" if purpose else "")
            + "Write in a warm, low-pressure, personal tone — one or two short "
              "paragraphs. If notes about the lead mention a specific interest, "
              "reference it naturally. "
            + ("Include a short subject line."
               if lead.contact_type == "email" else
               "This will be sent as a short chat message — leave subject null.")
        )
        result = await invoke_llm(prompt, bind=drafter_bind, use_cache=False)
        return {"ok": True, "lead": lead, "subject": result.subject, "body": result.body}

    async def send_followup(self, identifier: str, body: str,
                            subject: Optional[str] = None,
                            from_email: Optional[str] = None) -> dict:
        """Deliver an already-approved message. Email leads send through a
        connected sender account; Telegram leads only deliver if that person
        has already tapped the bot's /start link — same constraint as
        broadcast_to_usernames in telegram_tools.py."""
        lead = self._repo.find_lead(identifier)
        if not lead:
            return {"ok": False, "error": f"No lead found matching '{identifier}'."}

        if lead.contact_type == "email":
            if not from_email:
                accounts = self._email.list_email_accounts()
                if not accounts:
                    return {"ok": False, "channel": "email",
                            "error": "No email account connected yet — connect one first."}
                from_email = accounts[0]["email"]
            result = await self._email.send_smtp(
                account_email=from_email, to_email=lead.contact_value,
                subject=subject or f"Hi {lead.name.split()[0]}!", body=body,
            )
            return {"ok": result.get("ok", False), "channel": "email",
                    "to": lead.contact_value, "error": result.get("error")}

        if lead.contact_type == "telegram":
            result = await self._telegram.deliver(lead.contact_value, body)
            error = None
            if not result.get("ok"):
                error = ("not registered — they must tap the bot's /start link first"
                         if result.get("reason") == "not_registered"
                         else result.get("reason", "unknown error"))
            return {"ok": result.get("ok", False), "channel": "telegram",
                    "to": lead.contact_value, "error": error}

        return {"ok": False, "channel": lead.contact_type,
                "error": f"No send channel for contact type '{lead.contact_type}' "
                         f"— only email and telegram are supported for delivery."}
