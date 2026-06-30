
from langchain_core.tools import tool

from application.agents.graphs.audience_analysis_graph import analyze_audience as _analyze_audience
from application.agents.graphs.idea_generation_graph import generate_ideas as _generate_ideas
from composition import idea_service


@tool
async def save_profile_field(field: str, value: str) -> str:
    """
    Save a single creator profile field.
    Call this as each piece of profile information is gathered.

    Args:
        field: one of niche, sub_niche, target_audience, platforms,
               content_style, monetization
        value: the extracted value from the creator's answer
    """
    return await idea_service.save_profile_field(field, value)


@tool
async def get_profile_status() -> str:
    """
    Return which profile fields are already saved in the database and which are
    still missing. Call this FIRST, before asking the creator for any profile
    information — a profile may already exist from a previous session. Use the
    result to avoid re-asking for fields that are already on file, and to decide
    what (if anything) is still left to collect.
    """
    return await idea_service.get_profile_status()


@tool
async def add_content_item(title: str, topic: str,
                     content_type: str, platform: str = "") -> str:
    """
    Add a piece of historical content to the creator's content library.
    This helps the idea generator avoid repetition and understand coverage gaps.

    Args:
        title:        title or description of the content piece
        topic:        the main topic or theme (keep it concise, 3-5 words)
        content_type: one of video, photo, live, digital
        platform:     where it was posted (optional)
    """
    return await idea_service.add_content_item(title, topic, content_type, platform)


@tool
async def get_content_history_summary() -> str:
    """
    Return a summary of the content already recorded in the database.
    Call this before asking the creator to describe their content — history may
    already exist from a previous session. Use it to avoid re-collecting items
    that are already stored, and to identify gaps and avoid suggesting
    already-done topics.
    """
    return await idea_service.get_content_history_summary()


@tool
async def analyze_audience() -> str:
    """
    Analyse all stored audience signals to compute topic intelligence.
    Updates topic_analytics with frequency, velocity, curiosity score,
    question and request aggregations, and sentiment trends.
    Call this before generate_ideas() to get the richest idea set.
    """
    return await _analyze_audience()


@tool
async def generate_stream_report(session_id: str) -> str:
    """
    Produce a report (topics, sentiment, content/knowledge gaps) scoped to
    ONE capture session's worth of TikTok LIVE chat — not the general
    audience pool. session_id comes from start_stream_capture()'s result.
    Call this right after a stream capture finishes, in the same turn —
    don't make the creator ask for it separately.
    """
    return await _analyze_audience(session_id=session_id)


@tool
async def suggest_search_keywords(platform: str = "") -> str:
    """
    Suggest search terms for finding OTHER creators' content relevant to
    this creator's own niche — step one of the keyword-guided "find
    inspiration" flow. Grounded in the creator's profile and content
    history, so it skips topics they've already covered.

    Returns just the keyword list — relay it to the creator in your own
    words, not a fixed script: search each term, open whatever catches their
    eye, skim the comments. Set the expectation that you'll start capturing
    as they browse and keep checking posts until at least the target number
    of RELEVANT ones (default 4) are collected, or they're satisfied and say
    stop explicitly — don't ask them to signal when they're "ready to start
    checking posts". Once they say they're looking at their first post,
    that's the cue to call start_inspiration_hunt next, not this tool again.

    platform: which app the creator will search on, e.g. "tiktok",
    "instagram". Optional; defaults to "tiktok".
    """
    return await idea_service.suggest_search_keywords(platform)


@tool
async def generate_ideas() -> str:
    """
    Generate content ideas for videos, pictures, live stream activities,
    and digital services. Uses the creator's profile, content history,
    and audience intelligence to produce targeted, data-driven suggestions.
    Call this after the profile is complete and analyze_audience() has run.
    """
    return await _generate_ideas()


@tool
async def analyze_other_stream(stream_notes: str, platform: str = "") -> str:
    """
    Analyse ANOTHER creator's live stream — not this creator's own — to spark
    content ideas. Call this whenever the creator says they're watching or
    checking out someone else's stream and wants to know what it's about,
    whether it's worth their attention, or what ideas it gives them.

    Pass whatever was captured or noticed from that other stream: pasted
    chat messages, or the creator's own description of what's happening.
    This does NOT touch the creator's own audience data, content history,
    or profile — it only reads them for grounding, never writes to them.

    Returns: what the stream is about, a short report, whether it's relevant
    to this creator's own niche/audience (with reasoning), and 2-4 related
    content ideas.

    Args:
        stream_notes: captured chat text or a description of what's
                      happening on the other stream
        platform:     optional — which platform it's on (tiktok, kick,
                      whatnot, twitch, etc.)
    """
    result = await idea_service.analyze_other_stream(stream_notes, platform)
    lines = [
        f"Topic: {result['topic']}",
        f"\nReport: {result['summary']}",
        f"\nRelevant to your content? {'Yes' if result['relevant'] else 'No'} "
        f"— {result['relevance_reason']}",
        "\nRelated ideas for you:",
    ]
    lines += [f"  {i}. {idea}" for i, idea in enumerate(result["ideas"], 1)]
    return "\n".join(lines)


IDEA_TOOLS = [
    save_profile_field,
    get_profile_status,
    add_content_item,
    get_content_history_summary,
    analyze_audience,
    generate_ideas,
    analyze_other_stream,
]
