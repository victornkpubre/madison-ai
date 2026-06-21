"""
template_repository_interface.py
═════════════════════
Abstract port for message-template management (subject/body copy with
{{variable}} placeholders, used for both email and Telegram sends).

NotificationService depends on this interface, not on
infrastructure/ai/templates.py directly, so the storage backend
(in-memory dict vs SQLAlchemy) can be swapped without touching
application logic — same role ICreatorRepository plays for
CreatorService.

infrastructure/ai/templates.py (TemplateRepository) is the concrete
adapter.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class ITemplateRepository(ABC):

    @abstractmethod
    def list_for_channel(self, channel: str | None = None) -> list[dict]:
        """Return stored templates, optionally filtered to one channel ('email' | 'telegram')."""
        raise NotImplementedError

    @abstractmethod
    def get(self, name: str) -> dict | None:
        """Return a single template by name, or None if it doesn't exist."""
        raise NotImplementedError

    @abstractmethod
    def save(self, name: str, channel: str, body: str,
              subject: str | None = None, is_default: bool = False) -> dict:
        """Create or overwrite a template."""
        raise NotImplementedError

    @abstractmethod
    def build_context(self, contact: dict, creator_profile: dict) -> dict:
        """Build the {{variable}} -> value mapping for a given contact + creator profile."""
        raise NotImplementedError

    @abstractmethod
    def render(self, template: dict, context: dict) -> dict:
        """Render a template's subject/body against a context dict."""
        raise NotImplementedError
