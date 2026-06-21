"""
youtube_client.py
═══════════════════
Placeholder integration for YouTube Live chat capture.

StreamEye currently only supports TikTok LIVE (captured by the companion
PyQt5 desktop app via OpenCV/EasyOCR) and Telegram/email for outbound
messaging. There is no YouTube integration implemented yet — this module
exists so the folder structure has a clear, obvious home for it when that
work starts, mirroring the shape of telegram_client.py.

Wire this up by:
  1. Implementing OAuth or an API-key flow against the YouTube Data API
     (liveChatMessages.list) to pull chat messages for an active broadcast.
  2. Feeding captured messages into the same audience-signal pipeline
     used by Telegram (see application/ideas/idea_tools.ingest_signal /
     application/ideas/idea_service.ingest_signal).
"""
from __future__ import annotations


class YouTubeClient:
    """Not implemented. Placeholder for a future YouTube Live chat client."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def fetch_live_chat_messages(self, live_chat_id: str) -> list[dict]:
        raise NotImplementedError(
            "YouTube Live chat integration is not implemented yet. "
            "See the module docstring for the intended wiring."
        )


client = YouTubeClient()
