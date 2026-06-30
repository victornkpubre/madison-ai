"""
email_tools.py
═════════════════════
LangChain @tool wrappers around NotificationService's email methods.
"""
from langchain_core.tools import tool

from composition import notification_service


@tool
async def connect_email_account(email: str, password: str, display_name: str = "") -> str:
    """
    Connect an ADDITIONAL email account for sending. The default sending
    account is configured in the app's .env file (EMAIL_ADDRESS /
    EMAIL_APP_PASSWORD) and loaded automatically at startup, so you usually
    do NOT need this tool. Only use it if the creator explicitly wants to add
    another account. Never ask the creator to type or paste a password into
    the chat — credentials belong in .env, not in conversation. `password`
    must be an app password generated from the account's security settings,
    not the account's real password. SMTP/IMAP host and port are
    auto-detected from the email's domain.
    """
    result = await notification_service.connect_email_account(email, password, display_name)
    if result["ok"]:
        return f"Connected {email} via {result['host']}:{result['port']}."
    return f"Could not connect {email}: {result.get('error', 'unknown error')}"


@tool
def list_connected_senders() -> str:
    """List email accounts currently connected for sending."""
    accounts = notification_service.list_connected_senders()
    if not accounts:
        return "No email accounts connected yet."
    return "\n".join(f"- {a['email']}" for a in accounts)


@tool
def list_email_templates() -> str:
    """List saved email templates (name, subject, and a preview of the body)."""
    templates = notification_service.list_email_templates()
    if not templates:
        return "No email templates saved yet."
    return "\n".join(
        f"- {t['name']} | subject: {t.get('subject', '')} | {t['body'][:80]}"
        for t in templates
    )


@tool
def create_email_template(name: str, subject: str, body: str) -> str:
    """
    Save a new email template. Use {{first_name}}, {{creator_name}},
    {{creator_bio}}, {{creator_cta}} as placeholders for personalisation.
    """
    notification_service.create_email_template(name, subject, body)
    return f"Saved email template '{name}'."


@tool
async def send_emails_from_template(emails: list[str], template_name: str, from_email: str) -> str:
    """
    Send a saved email template to a list of email addresses from a
    connected sender account.
    """
    result = await notification_service.send_emails_from_template(emails, template_name, from_email)
    if not result.get("ok", True):
        return result.get("error", "Failed to send emails.")
    parts = [f"Sent {result['sent']}/{result['total']}."]
    if result["failed"]:
        parts.append(f"Failed: {result['failed']}.")
    return " ".join(parts)


EMAIL_TOOLS = [
    connect_email_account,
    list_connected_senders,
    list_email_templates,
    create_email_template,
    send_emails_from_template,
]
