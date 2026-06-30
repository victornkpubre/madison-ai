"""
telegram_client.py
═══════════════════
Telegram Bot API HTTP client + the user registry that maps Telegram
username -> chat_id.

User registry
──────────────
Telegram only allows the bot to message users who have started it first.
This module owns the registry:

  save_telegram_user(chat_id, first_name, last_name, username)
      Called from the webhook every time ANY message arrives.
      Upserts to `telegram_users` table (or the in-memory fallback).

  get_chat_id(username) -> int | None
      Resolves a username to a chat_id before sending.
      Returns None if the user has never messaged the bot.

deliver(username, text)
      Resolve username -> chat_id then send, returning a typed result dict.
      Used by application/notifications/notification_service.py to build
      the LLM-facing tool functions.
"""
from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import func

from config import settings
from domain.repository.telegram_repository_interface import ITelegramRepository
from infrastructure.database.db import get_sync_session
from infrastructure.database.notification_model import TelegramUserModel

TELEGRAM_TOKEN = settings.telegram_bot_token

# ── in-memory fallback (used when DATABASE_URL is not set) ────────────────────
# Primary store: chat_id (int) → {username, first_name, last_name}
# Username index: username (str) → chat_id  (for get_chat_id() lookups)
_user_data: dict[int, dict] = {}
_users:     dict[str, int]  = {}


# ── typed failures ────────────────────────────────────────────────────────────

class TelegramRateLimited(Exception):
    """Telegram returned 429 — wait `retry_after` seconds before retrying."""
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"rate limited, retry after {retry_after}s")


class TelegramBlocked(Exception):
    """Telegram returned 403 — the user has blocked or removed the bot."""
    def __init__(self, chat_id):
        self.chat_id = chat_id
        super().__init__(f"chat {chat_id} blocked the bot")


# ── user registry ─────────────────────────────────────────────────────────────

def save_telegram_user(chat_id: int,
                       first_name: str | None,
                       last_name:  str | None = None,
                       username:   str | None = None) -> None:
    """
    Persist a Telegram user so the bot can reach them later.
    Called from the webhook on EVERY inbound message — not just /start.
    """
    clean = (username or "").lower().lstrip("@") or None

    if settings.database_url:
        with get_sync_session() as s:
            s.execute(
                pg_insert(TelegramUserModel)
                .values(telegram_chat_id=chat_id, first_name=first_name or "",
                        last_name=last_name, username=clean, last_seen=func.now())
                .on_conflict_do_update(
                    index_elements=["telegram_chat_id"],
                    set_=dict(first_name=first_name or "", last_name=last_name,
                              username=clean, last_seen=func.now()),
                )
            )
            s.commit()
    else:
        _user_data[chat_id] = {
            "first_name": first_name or "",
            "last_name":  last_name,
            "username":   clean,
        }
        if clean:
            _users[clean] = chat_id


def get_chat_id(username: str) -> int | None:
    """Resolve a Telegram username to a chat_id. Returns None if not registered."""
    clean = username.lower().lstrip("@")
    if settings.database_url:
        with get_sync_session() as s:
            return s.execute(
                select(TelegramUserModel.telegram_chat_id)
                .where(TelegramUserModel.username == clean)
            ).scalar_one_or_none()
    return _users.get(clean)


async def list_telegram_users(limit: int = 50) -> list[dict]:
    """Used by the GET /debug/telegram-users endpoint."""
    if settings.database_url:
        from infrastructure.database.db import get_async_session
        async with get_async_session() as s:
            rows = (await s.execute(
                select(TelegramUserModel)
                .order_by(TelegramUserModel.registered_at.desc())
                .limit(limit)
            )).scalars().all()
        return [{"chat_id": r.telegram_chat_id, "first_name": r.first_name,
                 "last_name": r.last_name, "username": r.username,
                 "registered_at": str(r.registered_at),
                 "last_seen": str(r.last_seen)}
                for r in rows]
    return [
        {"chat_id":    cid,
         "first_name": d.get("first_name"),
         "last_name":  d.get("last_name"),
         "username":   d.get("username")}
        for cid, d in _user_data.items()
    ][:limit]


# ── low-level HTTP client ─────────────────────────────────────────────────────

class TelegramClient:
    def __init__(self, token: str = TELEGRAM_TOKEN):
        self.base = f"https://api.telegram.org/bot{token}"

    async def send_message(self, chat_id: int, text: str) -> dict:
        """POST sendMessage. Raises typed errors on 429 / 403."""
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{self.base}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
        if r.status_code == 429:
            retry = r.json().get("parameters", {}).get("retry_after", 1)
            raise TelegramRateLimited(retry)
        if r.status_code == 403:
            raise TelegramBlocked(chat_id)
        r.raise_for_status()
        return r.json()


client = TelegramClient()


# ── delivery helper ────────────────────────────────────────────────────────

async def deliver(username: str, text: str) -> dict:
    """
    Resolve username → chat_id, then send.

    Returns a result dict:
      {"ok": True,  "chat_id": int}
      {"ok": False, "reason": "not_registered", "username": str}
      {"ok": False, "reason": "blocked",        "username": str}
      {"ok": False, "reason": "rate_limited",   "retry_after": int}
      {"ok": False, "reason": "api_error",      "error": str}
    """
    clean   = username.lower().lstrip("@")
    chat_id = get_chat_id(clean)

    if chat_id is None:
        return {
            "ok":       False,
            "reason":   "not_registered",
            "username": clean,
        }

    try:
        await client.send_message(chat_id, text)
        return {"ok": True, "chat_id": chat_id}
    except TelegramBlocked:
        return {"ok": False, "reason": "blocked",      "username": clean}
    except TelegramRateLimited as e:
        return {"ok": False, "reason": "rate_limited", "retry_after": e.retry_after}
    except Exception as e:
        return {"ok": False, "reason": "api_error",    "error": str(e)}


# ── ITelegramRepository adapter ────────────────────────────────────────────
# Thin wrapper so NotificationService depends on the interface, not this
# module directly. The flat functions above stay public and untouched —
# the Telegram webhook (interface/api/assistant.py) still calls
# save_telegram_user / list_telegram_users directly for registry
# bookkeeping, which isn't a "send a notification" concern.

class TelegramRepository(ITelegramRepository):

    async def deliver(self, username: str, text: str) -> dict:
        return await deliver(username, text)

    async def send_to_chat_id(self, chat_id: int, text: str) -> dict:
        try:
            await client.send_message(chat_id, text)
            return {"ok": True}
        except TelegramBlocked:
            return {"ok": False, "reason": "blocked", "chat_id": chat_id}
        except TelegramRateLimited as e:
            return {"ok": False, "reason": "rate_limited", "retry_after": e.retry_after}
        except Exception as e:
            return {"ok": False, "reason": "api_error", "error": str(e)}


telegram_repository = TelegramRepository()
