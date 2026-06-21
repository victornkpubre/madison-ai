"""
email_repository_interface.py
═════════════════════
Abstract port for SMTP/IMAP email integration: connecting an account,
verifying credentials, and sending mail.

NotificationService depends on this interface, not on
infrastructure/integrations/email_client.py directly.

infrastructure/integrations/email_client.py (EmailRepository) is the
concrete adapter.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class IEmailRepository(ABC):

    @abstractmethod
    def get_smtp_preset(self, email: str) -> dict:
        """Look up the SMTP/IMAP host+port preset for an email's domain."""
        raise NotImplementedError

    @abstractmethod
    async def verify_smtp_credentials(self, email: str, password: str,
                                       smtp_host: str, smtp_port: int) -> dict:
        """Attempt an SMTP login to confirm the credentials are valid."""
        raise NotImplementedError

    @abstractmethod
    def save_smtp_account(self, email: str, password: str,
                           display_name: str | None = None,
                           smtp_host: str | None = None, smtp_port: int = 587,
                           imap_host: str | None = None, imap_port: int = 993) -> None:
        """Persist a connected email account."""
        raise NotImplementedError

    @abstractmethod
    def get_smtp_account(self, email: str) -> dict | None:
        """Return a connected account's stored config, or None."""
        raise NotImplementedError

    @abstractmethod
    def list_email_accounts(self) -> list[dict]:
        """Return all connected email accounts."""
        raise NotImplementedError

    @abstractmethod
    async def send_smtp(self, account_email: str, to_email: str, subject: str, body: str,
                         to_name: str = "", reply_to: str | None = None,
                         html_body: str | None = None) -> dict:
        """Send an email via the given connected account."""
        raise NotImplementedError


