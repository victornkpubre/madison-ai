"""
templates.py
============
Message template management for StreamEye.

Templates support {{variable}} placeholders resolved at send time from
contact data and the creator's profile.

Built-in variables available in every template:
  {{first_name}}   — contact's first name
  {{last_name}}    — contact's last name (blank if not available)
  {{email}}        — contact's email address
  {{creator_name}} — from creator profile
  {{creator_bio}}  — from creator profile
  {{creator_cta}}  — creator's call to action

Templates are persisted to the database when DATABASE_URL is set,
otherwise stored in-memory for the life of the server process.
"""
import re
from datetime import datetime, timezone

from config import settings
from domain.repository.template_repository_interface import ITemplateRepository

# ── in-memory store ───────────────────────────────────────────────────────────
# name → {name, channel, subject, body, variables, is_default, created_at}
_templates: dict[str, dict] = {}


# ── defaults ──────────────────────────────────────────────────────────────────

DEFAULT_EMAIL_INTRO = {
    "name":       "default_intro",
    "channel":    "email",
    "subject":    "Great connecting with you on {{creator_name}}'s stream!",
    "body":       (
        "Hi {{first_name}},\n\n"
        "It was great having you join {{creator_name}}'s TikTok Live today!\n\n"
        "{{creator_bio}}\n\n"
        "I'd love to stay connected — reply to this email anytime or "
        "join the next session.\n\n"
        "{{creator_cta}}\n\n"
        "Best,\n"
        "{{creator_name}}"
    ),
    "variables":  ["first_name", "creator_name", "creator_bio", "creator_cta"],
    "is_default": True,
    "created_at": "built-in",
}

DEFAULT_TELEGRAM_WELCOME = {
    "name":       "default_telegram_welcome",
    "channel":    "telegram",
    "subject":    None,
    "body":       (
        "👋 Hi {{first_name}}! Thanks for joining {{creator_name}}'s session.\n\n"
        "{{creator_bio}}\n\n"
        "{{creator_cta}}"
    ),
    "variables":  ["first_name", "creator_name", "creator_bio", "creator_cta"],
    "is_default": True,
    "created_at": "built-in",
}

_BUILT_INS = [DEFAULT_EMAIL_INTRO, DEFAULT_TELEGRAM_WELCOME]


# ── persistence ───────────────────────────────────────────────────────────────

def save_template(name: str,
                  channel: str,
                  body: str,
                  subject: str | None = None,
                  is_default: bool = False) -> dict:
    """
    Save a message template.
    Variables are auto-detected from {{placeholder}} patterns in the body and subject.
    """
    text      = (subject or "") + " " + body
    variables = sorted(set(re.findall(r"\{\{(\w+)\}\}", text)))

    record = {
        "name":       name,
        "channel":    channel,
        "subject":    subject,
        "body":       body,
        "variables":  variables,
        "is_default": is_default,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if settings.database_url:
        import psycopg, json as _json
        with psycopg.connect(settings.database_url, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO message_templates
                    (name, channel, subject, body, variables, is_default)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE
                    SET channel    = EXCLUDED.channel,
                        subject    = EXCLUDED.subject,
                        body       = EXCLUDED.body,
                        variables  = EXCLUDED.variables,
                        is_default = EXCLUDED.is_default,
                        updated_at = NOW()
                """,
                (name, channel, subject, body,
                 _json.dumps(variables), is_default),
            )
    else:
        _templates[name] = record

    return record


def get_template(name: str) -> dict | None:
    """Retrieve a template by name, including built-ins."""
    # Built-ins are always available regardless of DB
    for t in _BUILT_INS:
        if t["name"] == name:
            return t

    if settings.database_url:
        import psycopg, json as _json
        with psycopg.connect(settings.database_url) as conn:
            row = conn.execute(
                "SELECT name, channel, subject, body, variables, is_default "
                "FROM message_templates WHERE name = %s",
                (name,),
            ).fetchone()
        if not row:
            return None
        return {"name": row[0], "channel": row[1], "subject": row[2],
                "body": row[3], "variables": row[4], "is_default": row[5]}

    return _templates.get(name)


def list_templates_for_channel(channel: str | None = None) -> list[dict]:
    """
    Return all templates, optionally filtered by channel.
    Built-ins always appear first.
    """
    built_ins = [t for t in _BUILT_INS
                 if channel is None or t["channel"] == channel]

    if settings.database_url:
        import psycopg
        with psycopg.connect(settings.database_url) as conn:
            if channel:
                rows = conn.execute(
                    "SELECT name, channel, subject, body, variables, is_default "
                    "FROM message_templates WHERE channel = %s ORDER BY created_at",
                    (channel,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT name, channel, subject, body, variables, is_default "
                    "FROM message_templates ORDER BY created_at"
                ).fetchall()
        stored = [{"name": r[0], "channel": r[1], "subject": r[2],
                   "body": r[3], "variables": r[4], "is_default": r[5]}
                  for r in rows]
    else:
        stored = [t for t in _templates.values()
                  if channel is None or t["channel"] == channel]

    # Merge: built-ins first, then user-created, deduplicating by name
    seen  = {t["name"] for t in built_ins}
    extra = [t for t in stored if t["name"] not in seen]
    return built_ins + extra


# ── rendering ─────────────────────────────────────────────────────────────────

def render_template(template: dict, context: dict) -> dict:
    """
    Replace {{variable}} placeholders in subject and body.

    context keys:
      first_name, last_name, email      — from the contact
      creator_name, creator_bio,
      creator_cta                        — from the creator profile
    """
    def _replace(text: str | None) -> str:
        if not text:
            return ""
        for key, value in context.items():
            text = text.replace(f"{{{{{key}}}}}", str(value or ""))
        # Leave any unreplaced placeholders blank rather than showing {{...}}
        text = re.sub(r"\{\{\w+\}\}", "", text)
        return text.strip()

    return {
        **template,
        "subject_rendered": _replace(template.get("subject")),
        "body_rendered":    _replace(template.get("body", "")),
    }


def build_context(contact: dict, creator_profile: dict) -> dict:
    """
    Build the template rendering context from a contact record
    and the creator profile.

    contact keys accepted: email, first_name, last_name, display_name
    If first_name is missing, it is inferred from the email address.
    """
    email        = contact.get("email", "")
    display_name = contact.get("display_name") or contact.get("from_name", "")

    # Infer first name from display name or email local part
    first_name = (contact.get("first_name")
                  or (display_name.split()[0] if display_name else "")
                  or email.split("@")[0].split(".")[0].capitalize())

    return {
        "first_name":    first_name,
        "last_name":     contact.get("last_name", ""),
        "email":         email,
        "creator_name":  creator_profile.get("name", "the creator"),
        "creator_bio":   creator_profile.get("bio", ""),
        "creator_cta":   creator_profile.get("cta", ""),
    }


# ── ITemplateRepository adapter ─────────────────────────────────────────────
# Thin wrapper so NotificationService depends on the interface, not this
# module directly. The flat functions above stay public and untouched.

class TemplateRepository(ITemplateRepository):

    def list_for_channel(self, channel: str | None = None) -> list[dict]:
        return list_templates_for_channel(channel)

    def get(self, name: str) -> dict | None:
        return get_template(name)

    def save(self, name: str, channel: str, body: str,
             subject: str | None = None, is_default: bool = False) -> dict:
        return save_template(name, channel, body, subject, is_default)

    def build_context(self, contact: dict, creator_profile: dict) -> dict:
        return build_context(contact, creator_profile)

    def render(self, template: dict, context: dict) -> dict:
        return render_template(template, context)


template_repository = TemplateRepository()
