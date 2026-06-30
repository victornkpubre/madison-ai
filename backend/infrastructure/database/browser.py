"""
browser.py
══════════
Read-only database browser backing the desktop app's Database page.

Exposes a curated, whitelisted set of views over the domain tables so the
creator can inspect their stored data — creator profile (identity plus
content strategy), captures, captured contacts, Telegram users, email
accounts, and message templates — without a SQL client.

Read-only by design: there are no write or delete paths here. Sensitive
columns (notably the SMTP password stored in email_accounts.access_token)
are never selected.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from infrastructure.database.capture_model import CaptureSessionModel
from infrastructure.database.creator_model import CreatorProfileModel
from infrastructure.database.db import async_engine, get_async_session
from infrastructure.database.notification_model import (
    EmailAccountModel, MessageTemplateModel, TelegramUserModel,
)


# Each entry: key, label, model, ordered display columns.
# access_token is deliberately omitted from email_accounts.
_TABLE_VIEWS = [
    ("creator_profile", "Creator Profile", CreatorProfileModel,
     ["id", "name", "bio", "cta", "email",
      "niche", "sub_niche", "target_audience", "platforms",
      "content_style", "monetization", "updated_at"]),
    ("captures", "Captures", CaptureSessionModel,
     ["id", "fields", "target", "collected", "stopped_reason", "created_at"]),
    ("telegram_users", "Telegram", TelegramUserModel,
     ["id", "telegram_chat_id", "first_name", "last_name", "username",
      "registered_at", "last_seen"]),
    ("email_accounts", "Email", EmailAccountModel,
     ["id", "email", "provider", "display_name", "smtp_host", "smtp_port",
      "imap_host", "imap_port", "created_at"]),
    ("templates", "Templates", MessageTemplateModel,
     ["id", "name", "channel", "subject", "body", "is_default", "created_at"]),
]

_VIEW_BY_KEY = {key: (label, model, cols) for key, label, model, cols in _TABLE_VIEWS}

# Captured contacts is special-cased: it flattens CaptureSessionModel's
# records_json (one row per captured viewer) rather than mapping 1:1 to a
# table. Captured records are dicts keyed by capture_entity.KNOWN_FIELDS —
# all five are surfaced here (not just tiktok_username/telegram/email) since
# start_capture lets the creator collect age and location too.
_CONTACTS_KEY = "contacts"
_CONTACTS_LABEL = "Captured Contacts"
_CONTACTS_COLUMNS = ["tiktok_username", "telegram", "email", "age", "location", "captured_at"]


def list_views() -> list[dict]:
    """Return the available views as {key, label} in display order."""
    out: list[dict] = []
    for key, label, _model, _cols in _TABLE_VIEWS:
        out.append({"key": key, "label": label})
        # Surface captured contacts right after the capture sessions.
        if key == "captures":
            out.append({"key": _CONTACTS_KEY, "label": _CONTACTS_LABEL})
    return out


def _stringify(value: Any) -> Any:
    """Coerce a DB value to something JSON-serialisable for the table grid."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


async def load_view(key: str) -> dict:
    """Return {'columns': [...], 'rows': [[...]]} for one view key.

    Unknown keys and a missing DATABASE_URL both yield an empty result
    rather than an error, so the desktop grid simply shows nothing.
    """
    if not async_engine:
        return {"columns": [], "rows": []}

    if key == _CONTACTS_KEY:
        return await _load_contacts()

    entry = _VIEW_BY_KEY.get(key)
    if not entry:
        return {"columns": [], "rows": []}
    _label, model, columns = entry

    stmt = select(*[getattr(model, c) for c in columns])
    # Newest first when the table has a sortable timestamp / id.
    for cand in ("created_at", "registered_at", "updated_at", "id"):
        if cand in columns:
            stmt = stmt.order_by(getattr(model, cand).desc())
            break

    async with get_async_session() as session:
        result = await session.execute(stmt)
        rows = [[_stringify(v) for v in row] for row in result.all()]
    return {"columns": columns, "rows": rows}


async def _load_contacts() -> dict:
    """Flatten every capture session's records_json into one contact list."""
    async with get_async_session() as session:
        result = await session.execute(
            select(CaptureSessionModel.records_json, CaptureSessionModel.created_at)
            .order_by(CaptureSessionModel.created_at.desc())
        )
        sessions = result.all()

    rows: list[list] = []
    for records_json, created_at in sessions:
        try:
            records = json.loads(records_json or "[]")
        except (json.JSONDecodeError, TypeError):
            records = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            rows.append([
                rec.get("tiktok_username") or rec.get("tiktok_name"),
                rec.get("telegram"),
                rec.get("email"),
                rec.get("age"),
                rec.get("location"),
                _stringify(created_at),
            ])
    return {"columns": _CONTACTS_COLUMNS, "rows": rows}
