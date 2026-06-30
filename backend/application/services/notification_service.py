"""
notification_service.py
══════════════════════════
Business logic for outbound notifications: Telegram delivery/broadcast/
relay, email account connection + template-based sending, and
conversational template drafting for both channels.

Depends on ITelegramRepository, IEmailRepository, ITemplateRepository,
CreatorService, and IdeaService — never on telegram_client / email_client /
templates directly. The concrete adapters are wired in by composition.py.

No @tool decorators and no langchain_core.tools import here — that glue
lives in application/agents/graphs/tools/telegram_tools.py, email_tools.py,
and template_tools.py, which call this service and format its return
values into LLM-facing strings. Same split idea_tools.py has from
idea_service.py.

Methods return plain result dicts rather than pre-formatted strings —
presentation belongs in the tool layer, which has the full docstring
context for the LLM.
"""
from __future__ import annotations

from application.agents.resilience import invoke_llm
from application.services.creator_service import CreatorService
from application.services.idea_service import IdeaService
from application.services.notification_schemas import DraftedTemplate
from domain.repository.email_repository_interface import IEmailRepository
from domain.repository.telegram_repository_interface import ITelegramRepository
from domain.repository.template_repository_interface import ITemplateRepository


class NotificationService:

    def __init__(self, telegram_repo: ITelegramRepository, email_repo: IEmailRepository,
                 template_repo: ITemplateRepository, creator_service: CreatorService,
                 idea_service: IdeaService):
        self._telegram = telegram_repo
        self._email = email_repo
        self._templates = template_repo
        self._creator = creator_service
        self._idea = idea_service

    # ── Telegram ─────────────────────────────────────────────────────────────
    async def send_to_username(self, username: str, text: str) -> dict:
        return await self._telegram.deliver(username, text)

    async def broadcast_to_usernames(self, usernames: list[str], text: str) -> dict:
        sent, not_registered, failed = 0, [], []
        for username in usernames:
            result = await self._telegram.deliver(username, text)
            if result["ok"]:
                sent += 1
            elif result.get("reason") == "not_registered":
                not_registered.append(username.lstrip("@"))
            else:
                failed.append({"username": username.lstrip("@"),
                               "reason": result.get("reason", "unknown")})
        return {"sent": sent, "total": len(usernames),
                "not_registered": not_registered, "failed": failed}

    async def relay_between_viewers(self, from_username: str, to_username: str, text: str) -> dict:
        # from_username is accepted for routing/logging by callers; delivery
        # only needs the recipient.
        return await self._telegram.deliver(to_username, f"💬 Message from your match:\n\n{text}")

    async def send_to_chat_id(self, chat_id: int, text: str) -> dict:
        return await self._telegram.send_to_chat_id(chat_id, text)

    # ── Email accounts ──────────────────────────────────────────────────────
    async def connect_email_account(self, email: str, password: str, display_name: str = "") -> dict:
        password = password.replace(" ", "")
        preset = self._email.get_smtp_preset(email)
        test = await self._email.verify_smtp_credentials(
            email, password, preset["smtp_host"], preset["smtp_port"])
        if not test["ok"]:
            return {"ok": False, "error": test["error"]}

        self._email.save_smtp_account(
            email=email, password=password,
            display_name=display_name or email.split("@")[0].capitalize(),
            smtp_host=preset["smtp_host"], smtp_port=preset["smtp_port"],
            imap_host=preset["imap_host"], imap_port=preset["imap_port"],
        )
        return {"ok": True, "host": preset["smtp_host"], "port": preset["smtp_port"]}

    def list_connected_senders(self) -> list[dict]:
        return self._email.list_email_accounts()

    # ── Templates: email ─────────────────────────────────────────────────────
    def list_email_templates(self) -> list[dict]:
        return self._templates.list_for_channel("email")

    def create_email_template(self, name: str, subject: str, body: str) -> dict:
        return self._templates.save(name, "email", body, subject)

    async def send_emails_from_template(self, emails: list[str],
                                        template_name: str, from_email: str) -> dict:
        template = self._templates.get(template_name)
        if not template:
            return {"ok": False, "error": f"Template '{template_name}' not found."}

        account = self._email.get_smtp_account(from_email)
        if not account:
            return {"ok": False, "error": f"No email account connected for {from_email}."}

        creator_profile = (await self._creator.get_profile()).as_dict()

        sent, failed = 0, []
        for email in emails:
            context = self._templates.build_context({"email": email}, creator_profile)
            rendered = self._templates.render(template, context)
            result = await self._email.send_smtp(
                account_email=from_email, to_email=email,
                subject=rendered["subject_rendered"], body=rendered["body_rendered"],
            )
            if result["ok"]:
                sent += 1
            else:
                failed.append({"email": email, "error": result.get("error", "unknown")})

        return {"ok": True, "sent": sent, "total": len(emails), "failed": failed}

    # ── Templates: telegram ──────────────────────────────────────────────────
    def list_telegram_templates(self) -> list[dict]:
        return self._templates.list_for_channel("telegram")

    def create_telegram_template(self, name: str, body: str) -> dict:
        # Telegram messages have no subject line.
        return self._templates.save(name, "telegram", body, subject=None)

    async def send_telegram_messages_from_template(self, usernames: list[str],
                                                    template_name: str) -> dict:
        template = self._templates.get(template_name)
        if not template:
            return {"ok": False, "error": f"Template '{template_name}' not found."}

        creator_profile = (await self._creator.get_profile()).as_dict()

        sent, not_registered, failed = 0, [], []
        for username in usernames:
            clean = username.lstrip("@")
            # No richer identity to draw on here (the Telegram interface is
            # deliberately scoped to send-only — see telegram_repository_interface.py),
            # so the username itself stands in for first_name if the template uses it.
            context = self._templates.build_context(
                {"first_name": clean, "email": ""}, creator_profile)
            rendered = self._templates.render(template, context)
            result = await self._telegram.deliver(username, rendered["body_rendered"])
            if result["ok"]:
                sent += 1
            elif result.get("reason") == "not_registered":
                not_registered.append(clean)
            else:
                failed.append({"username": clean, "reason": result.get("reason", "unknown")})

        return {"ok": True, "sent": sent, "total": len(usernames),
                "not_registered": not_registered, "failed": failed}

    # ── Conversational template drafting (email or telegram) ────────────────
    async def draft_template(self, channel: str, purpose: str) -> dict:
        """Draft new template copy grounded in the creator's profile and the
        latest audience analysis/trending topics. Returns a draft for the
        creator to review — nothing is persisted here. Call
        create_email_template / create_telegram_template separately once
        the creator approves (or edits) the wording."""
        creator_profile = (await self._creator.get_profile()).as_dict()
        idea_profile = self._idea.load_profile().strategy_dict()
        latest_analysis = self._idea.load_latest_audience_analysis()
        audience_summary = latest_analysis["summary"] if latest_analysis else \
            "No audience analysis recorded yet."
        top_topics = self._idea.load_topic_analytics(5)
        topics_text = ", ".join(t["topic"] for t in top_topics) or "none recorded yet"

        drafter_bind = lambda m: m.bind(temperature=0.4).with_structured_output(DraftedTemplate)
        prompt = (
            f"Draft a {channel} message template for this creator.\n\n"
            f"Creator name: {creator_profile.get('name', 'the creator')}\n"
            f"Bio: {creator_profile.get('bio', '')}\n"
            f"Call to action: {creator_profile.get('cta', '')}\n\n"
            f"Niche: {idea_profile.get('niche', '')} ({idea_profile.get('sub_niche', '')})\n"
            f"Target audience: {idea_profile.get('target_audience', '')}\n"
            f"Communication style: {idea_profile.get('content_style', '')}\n\n"
            f"Audience intelligence summary: {audience_summary}\n"
            f"Trending topics among viewers: {topics_text}\n\n"
            f"Purpose of this template: {purpose}\n\n"
            f"Write in the creator's communication style, speaking to their stated "
            f"audience and grounded in what the audience intelligence above says they "
            f"actually care about. "
            + ("Include a subject line. " if channel == "email" else
               "This is Telegram — there is no subject line, leave it null. ")
            + "Use {{first_name}}, {{creator_name}}, {{creator_bio}}, {{creator_cta}} as "
              "placeholders for personalization — do not hardcode the creator's own name "
              "or bio into the body text."
        )
        # use_cache=False: drafting is meant to vary (temperature=0.4) — a creator
        # asking again with the same purpose should get a fresh draft, not a
        # stale cached one from an earlier identical request.
        result = await invoke_llm(prompt, bind=drafter_bind, use_cache=False)
        return {"channel": channel, "subject": result.subject, "body": result.body}
