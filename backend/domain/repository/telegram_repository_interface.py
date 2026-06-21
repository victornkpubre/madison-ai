"""
telegram_repository_interface.py
═════════════════════
Abstract port for outbound Telegram delivery (NOT the registry of opted-in
users — that's plain persistence handled directly by
infrastructure/integrations/telegram_client.py's save_telegram_user /
list_telegram_users, deliberately scoped out of this interface since it
isn't a "send a notification" concern).

NotificationService depends on this interface, not on
infrastructure/integrations/telegram_client.py directly.

infrastructure/integrations/telegram_client.py (TelegramRepository) is
the concrete adapter.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class ITelegramRepository(ABC):

    @abstractmethod
    async def deliver(self, username: str, text: str) -> dict:
        """Send `text` to a Telegram username that has previously opted in."""
        raise NotImplementedError

    @abstractmethod
    async def send_to_chat_id(self, chat_id: int, text: str) -> dict:
        """Send `text` directly to a known Telegram chat_id."""
        raise NotImplementedError
