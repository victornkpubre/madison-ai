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

from backend.application.services.creator_service import CreatorService
from backend.application.services.idea_service import IdeaService
from backend.application.services.notification_service import NotificationService
from backend.infrastructure.ai.templates import template_repository
from backend.infrastructure.integrations.email_client import email_repository
from backend.infrastructure.integrations.telegram_client import telegram_repository
from backend.infrastructure.repositories.creator_repository import creator_repository
from backend.infrastructure.repositories.idea_repository import idea_repository

creator_service = CreatorService(creator_repository)
idea_service = IdeaService(idea_repository)
notification_service = NotificationService(
    telegram_repository, email_repository, template_repository, creator_service, idea_service,
)
