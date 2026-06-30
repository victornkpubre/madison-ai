"""
composition.py
═══════════════
Single composition root: builds every application-layer service from its
concrete repository implementation and exposes the process-wide singletons.

Why this file exists: application/services/*.py define each service
against its abstract repository interfaces only (IIdeaRepository,
ICreatorRepository, ITelegramRepository, IEmailRepository,
ITemplateRepository) and import nothing from infrastructure/ — that's the
whole point of depending on an interface instead of a concrete class.
Something still has to construct the concrete adapters and wire them in
exactly once; this is that outermost wiring point. Routers, LangGraph
nodes, and tool wrappers should import their service singletons from
here, not from application/services/<name>_service.py directly.
"""
from __future__ import annotations

from config import settings
from application.services.creator_service import CreatorService
from application.services.idea_service import IdeaService
from application.services.lead_service import LeadService
from application.services.notification_service import NotificationService
from infrastructure.ai.templates import template_repository
from infrastructure.integrations.email_client import email_repository
from infrastructure.integrations.telegram_client import telegram_repository
from infrastructure.repositories.creator_repository import creator_repository
from infrastructure.repositories.idea_repository import idea_repository
from infrastructure.repositories.lead_repository import lead_repository

creator_service = CreatorService(creator_repository)
idea_service = IdeaService(idea_repository)
notification_service = NotificationService(
    telegram_repository, email_repository, template_repository, creator_service, idea_service,
)
# Reuses the same email/telegram adapters as NotificationService — a lead
# follow-up is sent through the same connected accounts and opt-in rules,
# just addressed to a manually-entered contact instead of a captured one.
lead_service = LeadService(lead_repository, idea_service, email_repository, telegram_repository)


def _seed_default_email_sender() -> None:
    """Register the .env-configured sending account as a connected sender at
    startup. This is the safe alternative to typing the app password into the
    chat: the credential lives only in EMAIL_ADDRESS / EMAIL_APP_PASSWORD in the
    .env file, and from here every send path (lead follow-ups, template sends)
    resolves it automatically with no in-chat connect step. No network call —
    save_smtp_account just stores the credentials; an invalid password surfaces
    later as a normal SMTP auth error on the first send, not a startup failure.
    SMTP/IMAP host and port are auto-detected from the email's domain."""
    if not (settings.email_address and settings.email_app_password):
        return
    try:
        email_repository.save_smtp_account(
            email=settings.email_address,
            password=settings.email_app_password,
            display_name=settings.email_display_name or None,
        )
    except Exception as exc:
        # Never let seeding break startup — e.g. the DB isn't migrated yet. The
        # account simply won't be pre-registered; the creator can still connect
        # one, and the next attempt will re-seed.
        print(f"[composition] could not seed default email sender: {exc}")


_seed_default_email_sender()
