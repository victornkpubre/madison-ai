
from langchain_core.tools import tool

from backend.application.agents.graphs.audience_analysis_graph import analyze_audience as _analyze_audience
from backend.application.agents.graphs.idea_generation_graph import generate_ideas as _generate_ideas
from backend.composition import idea_service


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
    Return which profile fields have been collected and which are still missing.
    Call this to track progress and decide what to ask next.
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
    Return a summary of the content topics already covered.
    Use this to identify gaps and avoid suggesting already-done topics.
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
async def generate_ideas() -> str:
    """
    Generate content ideas for videos, pictures, live stream activities,
    and digital services. Uses the creator's profile, content history,
    and audience intelligence to produce targeted, data-driven suggestions.
    Call this after the profile is complete and analyze_audience() has run.
    """
    return await _generate_ideas()


IDEA_TOOLS = [
    save_profile_field,
    get_profile_status,
    add_content_item,
    get_content_history_summary,
    analyze_audience,
    generate_ideas,
]
