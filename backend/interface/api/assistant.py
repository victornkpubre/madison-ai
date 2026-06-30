"""
assistant.py (interface/api)
═════════════════════════════
The creator-assistant facing router:

  Universal conversation entry points (dispatched by the supervisor graph
  to whichever sub-agent should handle them):
    POST /chat
    POST /resume

  Telegram opt-in:
    POST /telegram-webhook
    GET  /debug/telegram-users

  Email account + template management (used by the assistant's email
  tools, see application/notifications/notification_service.py):
    GET  /auth/connected-accounts
    POST /templates
    GET  /templates
    GET  /templates/{name}
    POST /email/connect
    POST /email/poll/{account_email}
"""
from __future__ import annotations

import datetime as dt
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage
from fastapi.responses import StreamingResponse

from config import settings
from composition import idea_service
from infrastructure.ai import templates as templates_store
from infrastructure.integrations import email_client, telegram_client
from interface.dependencies import resume_command, stream_graph
from interface.schemas.assistant_schema import (
    ChatRequest, ResumeRequest, SmtpConnectRequest, TemplateRequest,
)

router = APIRouter()

_MAIN_NODES = frozenset({"supervisor",
                          "assist_agent", "idea_agent", "reply_agent"})

# Which node's chat-model calls are the actual user-facing reply (and so
# should stream token-by-token). NOT "assist_agent"/"idea_agent"/"reply_agent"
# — those are only the OUTER supervisor's registration names for three
# separately-compiled subgraphs (assist_graph / idea_graph / reply_graph).
# Each of those subgraphs names its own internal ReAct-loop node "agent"
# (see assistant_graph.py / ideation_graph.py / reply_graph.py) — and
# astream_events() reports metadata for whichever node is CURRENTLY
# executing, which for a nested subgraph is the inner node's own name, not
# the outer one (verified empirically: a separately-compiled subgraph
# invoked via plain .ainvoke() still reports its own node names). So
# filtering on "assist_agent" etc. matched nothing and silently dropped
# every real reply — routing/tool-call events still showed (those ARE
# keyed on the outer name), making it look like the agent went silent
# after doing real work, when actually every token of its answer was being
# thrown away. "agent" is unique to these three top-level loops — no
# internal helper graph (audience_analysis_graph, idea_generation_graph)
# uses that name for any of its own nodes.
_STREAMING_NODES = frozenset({"agent"})


# ── main chat endpoints ────────────────────────────────────────────────────────
# All messages — creator commands, viewer replies, idea requests — go through
# the single main_graph. The supervisor node routes to the right sub-agent.

@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    """
    Universal entry point for all agent conversations.
    The supervisor routes to assist_agent, idea_agent, or reply_agent
    based on the message content and whether chat_id is present.
    """
    main_graph = request.app.state.main_graph
    # recursion_limit defaults to 25 — too low for a turn that legitimately
    # chains several tool calls (e.g. saving 8 FAQ answers = 16+ supersteps).
    # Raised so normal multi-tool turns don't trip it; runaway loops are still
    # bounded and now surface as a graceful message (see stream_graph).
    config = {"configurable": {"thread_id": req.thread_id}, "recursion_limit": 60}
    graph_input = {
        "messages": [HumanMessage(req.message)],
        "chat_id":  req.chat_id,
    }
    ep = {
        "endpoint":  "POST /chat",
        "thread_id": req.thread_id[:8] + "…",
        "graph":     "main_graph",
        "input":     f"HumanMessage({req.message[:50]!r})",
    }
    return StreamingResponse(
        stream_graph(main_graph, graph_input, config, ep, _MAIN_NODES, _STREAMING_NODES),
        media_type="text/event-stream")


@router.post("/resume")
async def resume(req: ResumeRequest, request: Request):
    """
    Resume any interrupted graph — capture slices, creator questions,
    viewer reply approvals, or idea generator prompts.
    The same endpoint handles all interrupt types because the thread_id
    and checkpoint identify exactly which sub-agent was paused.
    """
    main_graph = request.app.state.main_graph
    config = {"configurable": {"thread_id": req.thread_id}, "recursion_limit": 60}
    val    = req.value or {}
    if "records" in val:
        inp = (f"Command(resume={{records: {len(val['records'])}, "
               f"found: {val.get('found', True)}}})")
    elif "answer" in val:
        inp = f"Command(resume={{answer: {val['answer'][:40]!r}}})"
    else:
        inp = f"Command(resume={req.action!r})"
    ep = {
        "endpoint":  "POST /resume",
        "thread_id": req.thread_id[:8] + "…",
        "graph":     "main_graph",
        "input":      inp,
    }
    return StreamingResponse(
        stream_graph(main_graph, resume_command(req), config, ep, _MAIN_NODES, _STREAMING_NODES),
        media_type="text/event-stream")


# ── Telegram webhook ─────────────────────────────────────────────────────────
# Path is /telegram-webhook to distinguish from future /google-chat-webhook etc.
@router.post("/telegram-webhook")
async def telegram_webhook(update: dict):
    """
    Receives every inbound Telegram update.

    Collects from the Telegram `from` object:
      chat_id    — always present (Telegram's stable numeric identifier)
      first_name — always present (required on account creation)
      last_name  — optional, NULL when not set on the account
      username   — optional, NULL when the account has no @handle

    Two responsibilities:
      1. Save the sender on EVERY message — this is the only moment we
         learn the chat_id needed to contact them later.
      2. Route /start to the registration flow.
    """
    message    = update.get("message", {})
    text       = (message.get("text") or "").strip()
    chat_id    = message.get("chat", {}).get("id")
    from_obj   = message.get("from") or {}

    # ── extract all available identity fields ─────────────────────────────
    first_name = from_obj.get("first_name") or ""          # always present
    last_name  = from_obj.get("last_name")  or None        # NULL placeholder
    username   = (from_obj.get("username") or "").lower() or None  # NULL placeholder

    # ── Step 1: persist the sender on every message ────────────────────────
    if chat_id:
        telegram_client.save_telegram_user(chat_id, first_name, last_name, username)

    # ── Step 2: ingest non-command messages as audience signals ──────────────
    if chat_id and text and not text.startswith("/"):
        idea_service.ingest_signal(text, source="telegram")

    # ── Step 3: route /start ─────────────────────────────────────────────────
    if text.startswith("/start"):
        # Future: extract deep-link session_id and run registration_graph.
        # For now send a welcome so the user knows the bot is active.
        try:
            full_name = " ".join(filter(None, [first_name, last_name])) or "there"
            await telegram_client.client.send_message(
                chat_id,
                f"👋 Hi {full_name}! You're now registered.\n"
                f"The creator will reach you here during the session."
            )
        except Exception:
            pass   # never let a failed welcome break the webhook response

    return {"ok": True}


# ── debug (remove in production) ──────────────────────────────────────────────
@router.get("/debug/telegram-users")
async def debug_telegram_users():
    """Return all registered Telegram users. Development only — remove before deploy."""
    users = await telegram_client.list_telegram_users()
    return {
        "source": "postgres" if settings.database_url else "memory",
        "count":  len(users),
        "users":  users,
    }


# ── email account management ──────────────────────────────────────────────────
@router.get("/auth/connected-accounts")
async def list_connected_accounts():
    """Return all connected email accounts (no credentials exposed)."""
    try:
        return {"accounts": email_client.list_email_accounts()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── template management ───────────────────────────────────────────────────────

@router.post("/templates")
async def create_template_endpoint(req: TemplateRequest):
    """Save a message template."""
    t = templates_store.save_template(req.name, req.channel, req.body, req.subject)
    return {"ok": True, "template": t}


@router.get("/templates")
async def list_templates_endpoint(channel: str | None = None):
    """List all templates, optionally filtered by channel."""
    return {"templates": templates_store.list_templates_for_channel(channel)}


@router.get("/templates/{name}")
async def get_template_endpoint(name: str):
    """Get a single template by name."""
    t = templates_store.get_template(name)
    if not t:
        return JSONResponse({"error": f"Template '{name}' not found"}, status_code=404)
    return t


# ── SMTP connect (no OAuth required) ─────────────────────────────────────────

@router.post("/email/connect")
async def email_connect(req: SmtpConnectRequest):
    """
    Connect an email account using SMTP/IMAP credentials (app password).
    No OAuth, no Google Cloud, no Azure — works with any email provider.

    For Gmail:   generate an app password at myaccount.google.com/apppasswords
    For Outlook: generate one at account.microsoft.com → Security → App passwords

    SMTP host/port are auto-detected from the email domain if not provided:
      @gmail.com      → smtp.gmail.com:587
      @outlook.com    → smtp.office365.com:587
      @yahoo.com      → smtp.mail.yahoo.com:587
      anything else   → smtp.<domain>:587
    """
    preset = email_client.get_smtp_preset(req.email)
    host   = req.smtp_host or preset["smtp_host"]
    port   = req.smtp_port or preset["smtp_port"]

    # Test the credentials before storing them
    test = await email_client.verify_smtp_credentials(req.email, req.password, host, port)
    if not test["ok"]:
        return {"ok": False, "error": test["error"]}

    email_client.save_smtp_account(
        email        = req.email,
        password     = req.password,
        display_name = req.display_name,
        smtp_host    = host,
        smtp_port    = port,
        imap_host    = req.imap_host or preset["imap_host"],
        imap_port    = req.imap_port or preset["imap_port"],
    )
    return {
        "ok":      True,
        "message": f"Connected {req.email} via SMTP ({host}:{port})",
        "email":   req.email,
    }


# ── Email inbox polling ───────────────────────────────────────────────────────
# Call POST /email/poll/{account_email} on a schedule (e.g. every 30s via
# APScheduler or a cron job) to pick up replies and route them.

@router.post("/email/poll/{account_email:path}")
async def poll_email(account_email: str, since_minutes: int = 5):
    """
    Fetch emails received in the last `since_minutes` for a connected account.
    Uses IMAPClient over SSL. Hook this into a scheduler to pick up replies.
    """
    if not email_client.get_smtp_account(account_email):
        return {"ok": False,
                "error": f"No account connected for {account_email}"}

    since    = datetime.now(timezone.utc) - dt.timedelta(minutes=since_minutes)
    messages = await email_client.poll_imap_inbox(account_email, after_datetime=since)
    return {"ok": True, "provider": "imap",
            "count": len(messages), "messages": messages}
