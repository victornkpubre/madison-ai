"""
lead_tools.py
═════════════
LangChain @tool wrappers around LeadService — manual lead capture
(collected from text: a friend referral, a DM, someone met in person)
plus profile/content-history-grounded follow-up drafting and sending.

Distinct from the live-stream OCR capture in assistant_tools.py
(start_capture / start_stream_capture): those read the chat overlay while
the creator is live; these let the creator type in a contact directly,
for the cases capture can't reach.
"""
from __future__ import annotations

from langchain_core.tools import tool

from composition import lead_service


@tool
def add_lead(name: str, contact_type: str, contact_value: str, notes: str = "") -> str:
    """
    Manually save a lead the creator collected OUTSIDE the live-stream
    capture flow — e.g. someone referred by a friend, a DM, a contact made
    in person. Use this whenever the creator describes a specific person to
    add, rather than asking you to capture from their stream.

    NEVER invent, guess, or use placeholder/example values for any field.
    The creator saying "I have their email and number" is NOT the same as
    them giving you those values — if the actual address/username/number
    has not appeared in the conversation, you do not have it. ask_creator
    for the exact value and wait for their reply BEFORE calling this. Do not
    fill contact_value with stand-ins like test@example.com, name@example.com,
    +1234567890, or "n/a"; a lead saved with a fake contact will later be
    emailed/messaged to nowhere and falsely reported as sent.

    Args:
        name:          the lead's name
        contact_type:  one of 'email', 'telegram', 'phone', 'other'
        contact_value: the actual email address / telegram username / phone number
        notes:         anything the creator knows about them — how they were
                       referred, what they're interested in, where they were
                       met. Optional, but meaningfully improves any follow-up
                       message drafted later — capture it whenever the
                       creator mentions it, even in passing.
    """
    return lead_service.add_lead(name, contact_type, contact_value, notes)


@tool
def list_leads() -> str:
    """List all manually-saved leads — name, contact info, and any notes."""
    return lead_service.list_leads()


@tool
def delete_lead(identifier: str) -> str:
    """Delete a manually-saved lead by name, contact value, or id."""
    return lead_service.delete_lead(identifier)


@tool
async def draft_lead_followup(identifier: str, purpose: str = "") -> str:
    """
    Draft a personalized follow-up message for one saved lead, grounded in
    the creator's own profile (name, bio, CTA, niche) and, if any exists,
    their recent content history. If the creator has no content history
    yet, the draft stays a general, friendly introduction rather than
    referencing content that doesn't exist.

    Always show this draft to the creator and get their approval (or
    edits) before calling send_lead_followup — never send unreviewed text.

    Args:
        identifier: the lead's name (or contact value) as saved via add_lead
        purpose:    optional — what this follow-up is for, e.g. 'thank them
                    for the referral and invite them to my next stream'
    """
    result = await lead_service.draft_followup(identifier, purpose)
    if not result.get("ok"):
        return f"✗ {result['error']}"
    subj = f"Subject: {result['subject']}\n\n" if result.get("subject") else ""
    return f"{subj}{result['body']}"


@tool
async def send_lead_followup(identifier: str, body: str, subject: str = "") -> str:
    """
    Send an APPROVED follow-up message to a saved lead, via email or
    Telegram depending on how their contact was saved. Only call this after
    the creator has reviewed and approved the drafted text from
    draft_lead_followup (or written their own) — never send freshly
    generated text without that approval step.

    Telegram leads only deliver if that person has already tapped the
    bot's /start link, same as broadcast_to_usernames. If that fails, tell
    the creator and suggest emailing instead if an email is on file.
    """
    result = await lead_service.send_followup(identifier, body, subject or None)
    if result.get("ok"):
        return f"✓ Sent via {result['channel']} to {result['to']}."
    return f"✗ Could not send via {result.get('channel', 'unknown channel')}: {result.get('error')}"


LEAD_TOOLS = [add_lead, list_leads, delete_lead, draft_lead_followup, send_lead_followup]
