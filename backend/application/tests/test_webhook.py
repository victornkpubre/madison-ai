"""
test_webhook.py  —  test the Telegram /start webhook handler locally.

Sends a fake Telegram update directly to the running FastAPI server.
No real Telegram account or bot token needed — this tests the handler logic
and the user registry in isolation.

Usage:
    python test_webhook.py                          # default fake user
    python test_webhook.py --username marcus_dev    # custom username
    python test_webhook.py --chat-id 99887766       # custom chat id

Then check the registry:
    python test_webhook.py --check                  # list all saved users

For real Telegram testing (ngrok):
    1. pip install pyngrok   (or download ngrok from ngrok.com)
    2. ngrok http 8000
    3. python test_webhook.py --set-webhook https://xxxx.ngrok.io
    4. Open Telegram, message your bot /start
"""

import argparse
import json
import sys
import time
import requests

BASE = "http://localhost:8000"


# ── fake Telegram update builders ─────────────────────────────────────────────

def make_start_payload(chat_id: int, username: str,
                       first_name: str, last_name: str = "") -> dict:
    """Build a Telegram update that looks exactly like a real /start message."""
    from_block = {
        "id":            chat_id,
        "is_bot":        False,
        "first_name":    first_name,
        "language_code": "en",
    }
    if last_name:
        from_block["last_name"] = last_name
    if username:
        from_block["username"] = username

    return {
        "update_id": int(time.time()),
        "message": {
            "message_id": 1,
            "from":  from_block,
            "chat": {
                "id":         chat_id,
                "first_name": first_name,
                "username":   username,
                "type":       "private",
            },
            "date": int(time.time()),
            "text": "/start",
        },
    }


def make_text_payload(chat_id: int, username: str,
                      first_name: str, text: str,
                      last_name: str = "") -> dict:
    """Build a plain text message update (non-command)."""
    p = make_start_payload(chat_id, username, first_name, last_name)
    p["message"]["text"] = text
    return p


# ── test helpers ───────────────────────────────────────────────────────────────

W = 60

def hr(ch="─"): print(ch * W)
def hdr(t):     hr("═"); print(f"  {t}"); hr("═")
def ok(m):      print(f"  ✓  {m}")
def fail(m):    print(f"  ✗  {m}")
def info(m):    print(f"  ┆  {m}")


def post_webhook(payload: dict) -> dict:
    r = requests.post(f"{BASE}/telegram-webhook", json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def get_users() -> dict:
    r = requests.get(f"{BASE}/debug/telegram-users", timeout=10)
    r.raise_for_status()
    return r.json()


# ── test cases ─────────────────────────────────────────────────────────────────
def test_start(chat_id: int, username: str, first_name: str, last_name: str = ""):
    hdr("TEST 1 — /start registers the user")
    payload = make_start_payload(chat_id, username, first_name, last_name)

    print()
    info("Sending fake /start payload:")
    info(f"  chat_id    = {chat_id}")
    info(f"  first_name = {first_name}")
    info(f"  last_name  = {last_name or '(not set)'}")
    info(f"  username   = {'@'+username if username else '(not set)'}")
    print()

    hr()
    result = post_webhook(payload)
    info(f"Webhook response: {result}")
    hr()
    print()

    if result.get("ok"):
        ok("Webhook returned {ok: true}")
    else:
        fail(f"Unexpected response: {result}")
        return

    # Verify the user was actually saved
    users_resp = get_users()
    users      = users_resp.get("users", [])
    source     = users_resp.get("source", "?")
    found      = any(
        str(u.get("chat_id")) == str(chat_id) or
        u.get("username", "").lower() == username.lower()
        for u in users
    )

    print()
    info(f"Registry source: {source}")
    info(f"Total users saved: {users_resp.get('count', 0)}")
    print()

    if found:
        ok(f"@{username} (chat_id={chat_id}) is in the registry ✓")
    else:
        fail(f"@{username} was NOT found in the registry after /start")
        info("Check the server logs for errors in save_telegram_user()")


def test_plain_message(chat_id: int, username: str, first_name: str):
    print()
    hdr("TEST 2 — plain message also registers the user")
    # Use a different chat_id to test a new user
    alt_id   = chat_id + 1
    alt_user = username + "_2"

    payload = make_text_payload(alt_id, alt_user, first_name + "2",
                                "Hey, what's going on in the stream?")
    info(f"Sending plain text message as @{alt_user} (chat_id={alt_id})")
    print()
    hr()
    result = post_webhook(payload)
    info(f"Webhook response: {result}")
    hr()
    print()

    users_resp = get_users()
    users      = users_resp.get("users", [])
    found      = any(str(u.get("chat_id")) == str(alt_id) for u in users)

    if found:
        ok(f"Plain message user @{alt_user} was also registered ✓")
    else:
        fail(f"Plain message from @{alt_user} did NOT register the user")
        info("save_telegram_user() should be called for every inbound message")


def test_repeat_start(chat_id: int, username: str, first_name: str):
    print()
    hdr("TEST 3 — repeat /start updates last_seen, no duplicate row")

    count_before = get_users().get("count", 0)
    post_webhook(make_start_payload(chat_id, username, first_name))
    post_webhook(make_start_payload(chat_id, username, first_name))
    count_after  = get_users().get("count", 0)

    info(f"Users before: {count_before}  |  Users after two more /start: {count_after}")
    print()

    if count_after == count_before:
        ok("Duplicate /start did not creators extra rows (upsert working) ✓")
    else:
        fail("User count grew on repeat /start — check the ON CONFLICT clause")


def cmd_check():
    hdr("Registered Telegram users")
    resp  = get_users()
    users = resp.get("users", [])
    print()
    info(f"Source : {resp.get('source', '?')}")
    info(f"Count  : {resp.get('count', 0)}")
    print()
    if not users:
        info("No users registered yet. Run: python test_webhook.py")
        return
    hr()
    print(f"  {'chat_id':<14} {'first_name':<16} {'last_name':<16} {'username'}")
    hr()
    for u in users:
        uname = ("@" + u["username"]) if u.get("username") else "(no username)"
        lname = u.get("last_name") or "(not set)"
        print(f"  {str(u.get('chat_id','')):<14} "
              f"{u.get('first_name') or '':<16} "
              f"{lname:<16} "
              f"{uname}")
    hr()


def cmd_set_webhook(ngrok_url: str):
    """Register the ngrok tunnel as the Telegram webhook."""
    from config import settings
    token = settings.telegram_bot_token
    if not token:
        token = input("Bot token (not found in .env): ").strip()
    url   = f"https://api.telegram.org/bot{token}/setWebhook"
    webhook_url = ngrok_url.rstrip("/") + "/telegram-webhook"
    r = requests.post(url, json={"url": webhook_url})
    data = r.json()
    hdr("Set Telegram webhook")
    if data.get("ok"):
        ok(f"Webhook set to: {webhook_url}")
        info("Now open Telegram, find your bot, and send /start")
        info("Then run: python test_webhook.py --check")
    else:
        fail(f"Failed: {data.get('description', data)}")


# ── entry point ────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--username",    default="victor_test")
    ap.add_argument("--chat-id",     type=int, default=123456789)
    ap.add_argument("--first-name",  default="Victor")
    ap.add_argument("--check",       action="store_true",
                    help="List all saved users and exit")
    ap.add_argument("--set-webhook", metavar="NGROK_URL",
                    help="Register ngrok URL as the Telegram webhook")
    args = ap.parse_args()

    # Verify the server is running first
    try:
        requests.get(f"{BASE}/docs", timeout=3)
    except requests.ConnectionError:
        print(f"\n  Server not running. Start it first:\n"
              f"  uvicorn main:app --reload\n")
        sys.exit(1)

    if args.check:
        cmd_check()
        return

    if args.set_webhook:
        cmd_set_webhook(args.set_webhook)
        return

    # Run all three tests
    test_start(args.chat_id, args.username, args.first_name)
    test_plain_message(args.chat_id, args.username, args.first_name)
    test_repeat_start(args.chat_id, args.username, args.first_name)

    print()
    hdr("Summary")
    print()
    info("To see all saved users:   python test_webhook.py --check")
    info("To test with real Telegram:")
    info("  1. ngrok http 8000")
    info("  2. python test_webhook.py --set-webhook https://xxxx.ngrok.io")
    info("  3. Send /start to your bot in Telegram")
    info("  4. python test_webhook.py --check")
    print()


if __name__ == "__main__":
    main()
