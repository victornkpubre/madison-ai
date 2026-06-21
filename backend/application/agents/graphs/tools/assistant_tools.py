from langchain_core.tools import tool

from backend.application.services.assistant_service import assistant_service


# ── onboarding + knowledge-gap tools ──────────────────────────────────────────
@tool
async def check_onboarding_status() -> str:
    """
    Returns the status of:
      - creator profile (name, bio, cta)
      - knowledge base (number of entries)
    """
    status = await assistant_service.check_onboarding_status()
    return status.describe()


@tool
async def save_creator_profile(name: str, bio: str, cta: str,
                                email: str = "") -> str:
    """
    Collect these conversationally — one or two questions at a time, not a form.
    Args:
        name:  what the creator wants to be called, e.g. 'Victor'
        bio:   one sentence about what they create,
               e.g. 'I help people pay off debt on any income'
        cta:   a call to action for messages,
               e.g. 'Follow me on TikTok @victor for daily tips'
        email: their connected sender email (optional — skip if not known)
    """
    return await assistant_service.save_creator_profile(name, bio, cta, email)


@tool
def get_knowledge_gaps() -> str:
    """
    Find topics your audience is actively asking about that have no answer
    in your knowledge base yet.

    Returns each gap with the EXACT questions viewers sent — pulled directly
    from the audience signals database. Nothing is generated or suggested.
    Use this to discover what information to add next.
    """
    return assistant_service.get_knowledge_gaps()


@tool
def save_to_knowledge_base(topic: str, answer: str) -> str:
    """
    Save the creator's own answer to the knowledge base.

    This must ONLY be called with the creator's exact words.
    Never call this with LLM-drafted content — the knowledge base
    must contain what the creator actually said, not a generated answer.

    Args:
        topic:  short label for this piece of knowledge, e.g. 'filming setup'
        answer: the creator's own answer, exactly as they said it
    """
    return assistant_service.save_to_knowledge_base(topic, answer)


# ── capture tools (intercepted by graph nodes, not executed directly) ────────

@tool
def start_capture(fields: list[str], target: int) -> str:
    """Begin capturing viewer records from the creator's TikTok LIVE chat.
    fields: which fields to collect, from tiktok_username, telegram, age, location.
    target: how many records to collect. Only call this once you know BOTH the
    fields and the target count — otherwise call ask_creator first."""
    return ""   # intercepted by capture_node


@tool
def ask_creator(question: str) -> str:
    """Ask the creator a question and wait for their answer. Use this when you do
    not yet know which fields to capture or how many records they want."""
    return ""   # intercepted by ask_node

ASSISTANT_TOOLS = [start_capture, ask_creator,
     check_onboarding_status, save_creator_profile,
     get_knowledge_gaps, save_to_knowledge_base]