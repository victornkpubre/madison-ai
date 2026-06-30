"""
telegram_tools.py
═════════════════════
LangChain @tool wrappers around NotificationService's Telegram methods.
Each tool formats the service's plain result dict into a string for the
LLM — the service layer stays presentation-free (see
application/services/notification_service.py).
"""
from langchain_core.tools import tool

from composition import notification_service


@tool
async def send_message_to_user(username: str, text: str) -> str:
    """
    Send a Telegram message to a single viewer who has already opted in
    (tapped the bot's /start link). `username` is the TikTok/Telegram
    username captured earlier, with or without the leading @.
    """
    clean = username.lstrip("@")
    result = await notification_service.send_to_username(clean, text)
    if result["ok"]:
        return f"Delivered to @{clean}."
    if result.get("reason") == "not_registered":
        return (f"@{clean} has not started the bot yet — "
                 f"ask the creator to share the /start link.")
    return f"Failed to deliver to @{clean}: {result.get('reason', 'unknown error')}"


@tool
async def broadcast_to_usernames(usernames: list[str], text: str) -> str:
    """
    Send the same Telegram message to a list of usernames. Only delivers
    to viewers who have already tapped the bot's /start link — anyone else
    is reported back as not yet registered.
    """
    result = await notification_service.broadcast_to_usernames(usernames, text)
    parts = [f"Delivered {result['sent']}/{result['total']}."]
    if result["not_registered"]:
        parts.append(f"Not yet registered: {', '.join(result['not_registered'])}.")
    if result["failed"]:
        parts.append(f"Failed: {result['failed']}.")
    return " ".join(parts)


@tool
def list_telegram_templates() -> str:
    """List saved Telegram message templates (name + a preview of the body)."""
    templates = notification_service.list_telegram_templates()
    if not templates:
        return "No Telegram templates saved yet."
    return "\n".join(f"- {t['name']}: {t['body'][:80]}" for t in templates)


@tool
def create_telegram_template(name: str, body: str) -> str:
    """
    Save a new Telegram message template. Telegram messages have no
    subject line. Use {{first_name}}, {{creator_name}}, {{creator_bio}},
    {{creator_cta}} as placeholders for personalisation.
    """
    notification_service.create_telegram_template(name, body)
    return f"Saved Telegram template '{name}'."


@tool
async def send_telegram_messages_from_template(usernames: list[str], template_name: str) -> str:
    """
    Send a saved Telegram template to a list of usernames, personalising
    each send. Only delivers to viewers who have already tapped the bot's
    /start link.
    """
    result = await notification_service.send_telegram_messages_from_template(usernames, template_name)
    if not result.get("ok", True):
        return result.get("error", "Failed to send template.")
    parts = [f"Delivered {result['sent']}/{result['total']}."]
    if result["not_registered"]:
        parts.append(f"Not yet registered: {', '.join(result['not_registered'])}.")
    if result["failed"]:
        parts.append(f"Failed: {result['failed']}.")
    return " ".join(parts)


@tool
async def send_telegram_message(chat_id: int, text: str) -> str:
    """
    Send a Telegram message directly to a known chat_id. Used by the
    auto-reply pipeline (reply_graph.py), not the conversational assistant.
    """
    result = await notification_service.send_to_chat_id(chat_id, text)
    return "Delivered." if result["ok"] else f"Failed: {result.get('reason', 'unknown error')}"


TELEGRAM_TOOLS = [
    send_message_to_user,
    broadcast_to_usernames,
    list_telegram_templates,
    create_telegram_template,
    send_telegram_messages_from_template,
]
