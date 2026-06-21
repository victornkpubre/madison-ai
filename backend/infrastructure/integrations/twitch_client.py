"""
twitch_client.py
══════════════════
Placeholder integration for Twitch chat capture.

No Twitch integration is implemented yet — this module exists so the
folder structure has a clear, obvious home for it when that work starts,
mirroring the shape of telegram_client.py.

Wire this up by:
  1. Connecting to Twitch's IRC-based chat (or the newer EventSub /
     Helix chat endpoints) for a given channel.
  2. Feeding captured messages into the same audience-signal pipeline
     used by Telegram (see application/ideas/idea_tools.ingest_signal /
     application/ideas/idea_service.ingest_signal).
"""
from __future__ import annotations


class TwitchClient:
    """Not implemented. Placeholder for a future Twitch chat client."""

    def __init__(self, client_id: str | None = None, access_token: str | None = None):
        self.client_id = client_id
        self.access_token = access_token

    async def fetch_chat_messages(self, channel: str) -> list[dict]:
        raise NotImplementedError(
            "Twitch chat integration is not implemented yet. "
            "See the module docstring for the intended wiring."
        )


client = TwitchClient()
