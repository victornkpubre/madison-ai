from fastapi import APIRouter
from telegram_tools import save_telegram_user, client
from idea_tools import ingest_signal

router = APIRouter()

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
        save_telegram_user(chat_id, first_name, last_name, username)

    # ── Step 2: ingest non-command messages as audience signals ──────────────
    if chat_id and text and not text.startswith("/"):
        ingest_signal(text, source="telegram")

    # ── Step 3: route /start ─────────────────────────────────────────────────
    if text.startswith("/start"):
        # Future: extract deep-link session_id and run registration_graph.
        # For now send a welcome so the user knows the bot is active.
        try:
            full_name = " ".join(filter(None, [first_name, last_name])) or "there"
            await client.send_message(
                chat_id,
                f"👋 Hi {full_name}! You're now registered.\n"
                f"The creator will reach you here during the session."
            )
        except Exception:
            pass   # never let a failed welcome break the webhook response

    return {"ok": True}

