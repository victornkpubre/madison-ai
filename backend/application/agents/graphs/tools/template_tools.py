"""
template_tools.py
═════════════════════
LangChain @tool wrapper around NotificationService's conversational
template drafting.
"""
from langchain_core.tools import tool

from backend.composition import notification_service


@tool
async def draft_template(channel: str, purpose: str) -> str:
    """
    Draft a new email or Telegram message template, grounded in the
    creator's profile and actual audience analysis (not generic copy).
    Show the result to the creator before saving it with
    create_email_template / create_telegram_template.

    Args:
        channel: 'email' or 'telegram'
        purpose: what the template is for, e.g. 'welcome new followers'
    """
    result = await notification_service.draft_template(channel, purpose)
    if result.get("subject"):
        return f"Subject: {result['subject']}\n\n{result['body']}"
    return result["body"]


TEMPLATE_TOOLS = [draft_template]
