from langchain_core.tools import tool

from application.services.assistant_service import assistant_service


# ── onboarding + knowledge-gap tools ──────────────────────────────────────────
@tool
async def check_onboarding_status() -> str:
    """
    Returns the status of:
      - creator profile (name, bio, cta)
      - knowledge base (number of entries)
    """
    try:
        status = await assistant_service.check_onboarding_status()
        return status.describe()
    except Exception as e:
        # Never raise from a tool: a raised error becomes an error ToolMessage the
        # agent retries indefinitely, blowing the recursion limit. Degrade so the
        # agent can still greet the creator and continue onboarding manually.
        return (f"Could not read onboarding status ({e}). "
                f"Assume nothing is set up yet and proceed with onboarding.")


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
async def reset_creator_profile() -> str:
    """
    Clear the creator's profile completely — name, bio, cta, email, niche,
    sub_niche, target_audience, platforms, content_style, and monetization
    all reset to empty, so onboarding starts over from name and content type.

    Does NOT touch the knowledge base, captured records, or audience
    analysis — those live in separate tables and are untouched by this.

    CRITICAL: this is destructive and cannot be undone. Always confirm with
    ask_creator first — tell them exactly what will be cleared (their whole
    profile: identity + content strategy) and what will NOT be touched
    (knowledge base, captures, audience analysis) — before calling this.

    If the creator wants their knowledge base wiped too, that is a SEPARATE
    action: also call clear_knowledge_base. Do not claim the knowledge base
    was cleared unless you actually called clear_knowledge_base.
    """
    return await assistant_service.reset_creator_profile()


@tool
async def clear_knowledge_base() -> str:
    """
    Permanently delete EVERY entry in the creator's knowledge base. This is
    the whole knowledge base, not one topic (use the per-topic delete for a
    single entry). Does NOT touch the creator's profile or captured records.

    CRITICAL: destructive and cannot be undone. Always confirm with
    ask_creator first, naming exactly what is wiped (all knowledge entries)
    and what is not (profile, captures). When the creator asks to wipe
    EVERYTHING — profile and knowledge base — call BOTH reset_creator_profile
    and this tool; reset_creator_profile alone leaves the knowledge base intact.
    """
    return await assistant_service.clear_knowledge_base()


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
def list_knowledge_base() -> str:
    """
    List the entries currently saved in the creator's knowledge base — each
    entry's topic and the saved answer.

    Use this whenever the creator asks what is in their knowledge base, what
    answers their viewer bot already has, or wants to review existing entries
    before adding or changing one. Read from this instead of saying you can't
    see their entries.
    """
    return assistant_service.list_knowledge_entries()


@tool
def get_content_strategy_profile() -> str:
    """
    Return the creator's SAVED content-strategy (idea) profile values — niche,
    sub_niche, target_audience, platforms, content_style, monetization.

    This reads the actual saved values, not just which fields are missing. Use
    it whenever the creator asks about their niche, sub-niche, target audience,
    or any other saved profile detail. Read from this instead of claiming the
    field hasn't been defined.
    """
    return assistant_service.get_content_strategy_profile()


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
def start_capture(fields: list[str], target: int, platform: str) -> str:
    """Begin capturing viewer records from the creator's OWN LIVE chat overlay,
    to build a contact list. This reads the creator's own chat and needs that
    overlay visible — it is NOT for looking at another creator's post or for
    finding content ideas/inspiration (that's capture_other_post or the
    inspiration hunt, which screenshot the whole window and never touch the chat
    overlay). Don't use this for an inspiration/ideas request.
    fields: which fields to collect, from tiktok_username, telegram, age, location.
    target: how many records to collect.
    platform: which platform they're streaming on — one of "tiktok", "kick",
    "whatnot", "twitch".
    Only call this once you know fields, target, AND platform — otherwise call
    ask_creator first."""
    return ""   # intercepted by capture_node


@tool
def start_stream_capture(target: int, platform: str) -> str:
    """Begin capturing raw chat messages from the creator's OWN LIVE chat (not
    specific fields — the actual message text), to analyze and produce a
    stream report (topics, sentiment, content/knowledge gaps). This reads the
    creator's own chat overlay and needs it visible — it is NOT for another
    creator's post or for finding content ideas/inspiration (that's
    capture_other_post or the inspiration hunt). Don't use this for an
    inspiration/ideas request.
    target: how many chat messages to capture before stopping.
    platform: which platform they're streaming on — one of "tiktok", "kick",
    "whatnot", "twitch".
    ALWAYS ask the creator for BOTH target and platform first — never guess
    or default either, even a 'reasonable' one. Only call this once you have
    both."""
    return ""   # intercepted by stream_capture_node


@tool
def capture_other_post(platform: str = "") -> str:
    """Take ONE screenshot of ANOTHER creator's post or video page that's
    currently open on the creator's OWN screen right now — not their own
    live chat, and not a multi-post hunt — then analyze it: what it's
    about, whether it's relevant to this creator's own niche, and what
    content ideas it gives. Reads the caption, hashtags, engagement counts,
    and visible comments straight from the screenshot.

    Use this for a single, specific post the creator is looking at right
    now and wants a one-off read on. If they instead want to search broadly
    and collect several relevant ideas, that's start_inspiration_hunt — a
    continuous hunt that auto-captures posts as the creator scrolls until it
    has enough relevant ones; a different flow, not this tool.

    If the creator instead describes or pastes in what they're seeing as
    TEXT rather than having you look at their screen, that's
    analyze_other_stream — yet another tool.

    platform: which app is on screen — e.g. "tiktok", "instagram", "kick",
    "whatnot", "twitch". Optional; defaults to "tiktok" if not given, but
    ask if it's genuinely ambiguous which app they mean.
    """
    return ""   # intercepted by post_screenshot_node


@tool
def start_inspiration_hunt(platform: str = "", target: int = 4) -> str:
    """Begin a CONTINUOUS keyword-guided inspiration hunt. Once started, the
    system automatically captures whatever post the creator scrolls past, one
    after another, keeping only the ones genuinely relevant to this creator's
    niche — until `target` relevant posts are collected or the creator stops it.
    The creator does NOT confirm each post: they just keep browsing while the
    capture runs in the background, and they can stop any time with the Stop
    control. There is no per-post tool to call — this single call drives the
    whole loop and returns only when the hunt is finished.

    Call this ONCE, right when the creator says they're looking at their first
    post (typically just after suggest_search_keywords and after they've
    searched and opened something). When it returns, present the collected
    results: for each relevant post its topic/what it was about, its engagement
    metrics and a couple of notable comments, and the content ideas it inspired.

    platform: which app, e.g. "tiktok", "instagram". Defaults to "tiktok".
    target: how many RELEVANT posts to collect before stopping. Defaults
    to 4 — only ask the creator if they want a different number, don't
    default to something else yourself.
    """
    return ""   # intercepted by inspiration_hunt_node (drives the continuous loop)


@tool
def ask_creator(question: str) -> str:
    """Ask the creator a question and wait for their answer. Use this when you do
    not yet know which fields to capture or how many records they want."""
    return ""   # intercepted by ask_node

ASSISTANT_TOOLS = [start_capture, start_stream_capture, capture_other_post,
     start_inspiration_hunt, ask_creator,
     check_onboarding_status, save_creator_profile, reset_creator_profile,
     clear_knowledge_base,
     get_knowledge_gaps, save_to_knowledge_base,
     list_knowledge_base, get_content_strategy_profile]