"""
test_email.py  —  end-to-end test for capture → template → email send flow.

Steps:
  1. Set a creator profile (used by the default_intro template)
  2. Connect an email account via SMTP
  3. Show available templates
  4. Run: "capture 5 emails and send a welcome message"
  5. Respond when the assistant asks which template to use
  6. See delivery results

Usage:
    FAKE_CAPTURE=1 FAKE_SEND=1 python test_email.py   # full dry run
    python test_email.py --setup-only                  # setup only, no assist
"""

import os
import sys
import json
import uuid
import argparse
import requests

BASE             = os.getenv("BACKEND", "http://localhost:8000")
USE_FAKE_CAPTURE = bool(os.getenv("FAKE_CAPTURE"))
USE_FAKE_SEND    = bool(os.getenv("FAKE_SEND"))

# ── formatting ────────────────────────────────────────────────────────────────

W = 64
def hr(ch="="):  print(ch * W)
def sep():       hr("-")
def hdr(t):      hr(); print(f"  {t}"); hr()
def ok(m):       print(f"  OK  {m}")
def fail(m):     print(f"  XX  {m}")
def note(m):     print(f"  |   {m}")
def arrow(m):    print(f"  ->  {m}")

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def post(path, body):
    r = requests.post(f"{BASE}{path}", json=body, timeout=30)
    r.raise_for_status()
    return r.json()

def get(path):
    r = requests.get(f"{BASE}{path}", timeout=10)
    r.raise_for_status()
    return r.json()

def stream_events(url, body):
    with requests.post(url, json=body, stream=True,
                       headers={"Accept": "text/event-stream"}, timeout=120) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8")
            if line.startswith("data:"):
                yield json.loads(line[5:].strip())

# ── fake capture ──────────────────────────────────────────────────────────────

def do_capture(interrupt_val):
    fields    = interrupt_val.get("fields", ["email"])
    target    = int(interrupt_val.get("target", 5))
    have      = int(interrupt_val.get("have", 0))
    remaining = max(target - have, 1)

    if USE_FAKE_CAPTURE:
        recs = []
        for i in range(remaining):
            rec = {}
            for f in fields:
                if f == "email":
                    rec[f] = f"viewer{have+i}@example.com"
                else:
                    rec[f] = f"{f}_{have+i}"
            recs.append(rec)
        note(f"fake capture -> {len(recs)} records:")
        for rec in recs:
            note(f"  {rec}")
        return {"records": recs, "found": True}

    raise NotImplementedError("Set FAKE_CAPTURE=1 for testing without real capture.")

# ── step 1: creator profile ───────────────────────────────────────────────────

def setup_creator_profile():
    hdr("STEP 1 -- Set creator profile")

    existing = get("/creator/profile")
    if existing.get("name"):
        note(f"Profile already set: {existing['name']}")
        note(f"  bio: {existing.get('bio', '')}")
        note(f"  cta: {existing.get('cta', '')}")
        change = input("  Update it? [y/N]: ").strip().lower()
        if change != "y":
            return existing

    print()
    name  = input("  Your name:               ").strip() or "the creator"
    bio   = input("  One-line bio:            ").strip() or "I creators content on TikTok."
    cta   = input("  Call to action:          ").strip() or "Follow me on TikTok!"
    email = input("  Sender email (optional): ").strip() or None

    result = post("/creator/profile",
                  {"name": name, "bio": bio, "cta": cta, "email": email})
    if result.get("ok"):
        ok(f"Profile saved for '{name}'")
    return result.get("profile", {})

# ── step 2: connect email ─────────────────────────────────────────────────────

def setup_email_account():
    hdr("STEP 2 -- Connect email account (SMTP)")

    accounts      = get("/auth/connected-accounts").get("accounts", [])
    smtp_accounts = [a for a in accounts if a.get("provider") == "smtp"]

    if smtp_accounts:
        note("Already connected:")
        for a in smtp_accounts:
            note(f"  {a['email']}")
        change = input("  Add another? [y/N]: ").strip().lower()
        if change != "y":
            return smtp_accounts[0]["email"]

    if USE_FAKE_SEND:
        note("FAKE_SEND=1 -- skipping real connection")
        return "fake@example.com"

    print()
    email    = input("  Email address:  ").strip()
    password = input("  App password:   ").strip()
    name     = input("  Display name:   ").strip() or None

    note("Testing credentials...")
    result = post("/email/connect",
                  {"email": email, "password": password, "display_name": name})
    if result.get("ok"):
        ok(result["message"])
        return email
    else:
        fail(f"Connection failed: {result.get('error')}")
        note("For Gmail: myaccount.google.com/apppasswords")
        sys.exit(1)

# ── step 3: show templates ────────────────────────────────────────────────────

def show_templates():
    hdr("STEP 3 -- Available email templates")

    result    = get("/templates?channel=email")
    templates = result.get("templates", [])

    for t in templates:
        label = " <- default" if t.get("is_default") else ""
        print(f"\n  [{t['name']}]{label}")
        if t.get("subject"):
            note(f"Subject: {t['subject']}")
        note(f"Preview: {t['body'][:100]}...")
        if t.get("variables"):
            note(f"Variables: {', '.join(t['variables'])}")

    return templates

# ── step 4: run the assist flow ───────────────────────────────────────────────

def run_assist(sender_email):
    hdr("STEP 4 -- Assistant: capture emails + send")

    thread_id = str(uuid.uuid4())
    url       = f"{BASE}/assist"
    body      = {
        "thread_id": thread_id,
        "message":   "capture 5 email addresses and send them a welcome email",
    }

    print()
    note(f"thread_id: {thread_id[:8]}...")
    note(f'prompt: "{body["message"]}"')

    while True:
        print()
        sep()
        note("SSE stream:")
        sep()

        interrupt_val = None
        streaming     = False

        for ev in stream_events(url, body):
            t = ev.get("type")

            if t == "fastapi":
                note(f"[fastapi]  {ev.get('endpoint')}  graph={ev.get('graph')}")
                note(f"           input={ev.get('input', '')}")

            elif t == "node_enter":
                print()
                sep()
                note(f"[node_enter]  {ev['node']}  (run {ev.get('run', 1)})")
                state = ev.get("state", {})
                if state:
                    note(f"  state: " + ", ".join(f"{k}={v!r}" for k,v in state.items()))

            elif t == "node_exit":
                ret = ev.get("returned", {})
                note(f"[node_exit]   {ev['node']}")
                for k, v in ret.items():
                    if isinstance(v, list):
                        for item in v:
                            note(f"  {k}: {item}")
                    else:
                        note(f"  {k}: {v}")

            elif t == "route":
                sep()
                arrow(f"route: {ev['from_node']}  ->  {ev['to_node']}")

            elif t == "llm_start":
                note(f"[llm_start]  {ev.get('model')}  "
                     f"[{', '.join(ev.get('messages', []))}]")

            elif t == "tool_call":
                note(f"[tool_call]  {ev['name']}(")
                for k, v in ev.get("args", {}).items():
                    note(f"  {k}={v!r}")
                note(f")  id={ev.get('call_id', '')}")

            elif t == "token":
                if not streaming:
                    print()
                    note("[token]  LLM response:")
                    print()
                    print("  ", end="", flush=True)
                    streaming = True
                print(ev["content"], end="", flush=True)

            elif t == "interrupt":
                if streaming:
                    print()
                    streaming = False
                interrupt_val = ev["value"]
                action = interrupt_val.get("action", "")
                print()
                sep()
                note(f"[interrupt]  GRAPH PAUSED  action={action}")
                for k, v in interrupt_val.items():
                    note(f"  {k:<16} {str(v)[:70]}")

            elif t == "done":
                if streaming:
                    print()
                    streaming = False
                print()
                sep()
                note("[done]  graph reached END")

        print()
        sep()

        if interrupt_val is None:
            print()
            hdr("COMPLETE")
            return

        action = interrupt_val.get("action", "")
        print()

        if action == "ask_user":
            question = interrupt_val.get("question", "?")
            print(f"  Q: {question}")
            print()

            # Only show templates if the question is about templates
            q_lower = question.lower()
            if any(w in q_lower for w in ("template", "send", "message")):
                templates = get("/templates?channel=email").get("templates", [])
                if templates:
                    print("  Available templates:")
                    for tmpl in templates:
                        label = " (default)" if tmpl.get("is_default") else ""
                        print(f"    * {tmpl['name']}{label}")
                    print()

            answer = input("  your answer: ").strip()
            if not answer:
                answer = "default_intro"
            value = {"answer": answer}

        elif action == "record_screen":
            fields_l = interrupt_val.get("fields", [])
            have     = int(interrupt_val.get("have", 0))
            target   = int(interrupt_val.get("target", 5))
            print(f"  Capturing {fields_l}  ({have}/{target})...")
            value = do_capture(interrupt_val)

        else:
            note(f"unhandled interrupt: {action}")
            return

        url  = f"{BASE}/assist/resume"
        body = {"thread_id": thread_id, "value": value}

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup-only", action="store_true",
                    help="Set profile and show templates, then exit")
    args = ap.parse_args()

    try:
        requests.get(f"{BASE}/docs", timeout=3)
    except requests.ConnectionError:
        print(f"\n  Server not running. Start it:\n  uvicorn main:application --reload\n")
        sys.exit(1)

    creator   = setup_creator_profile()
    print()
    sender    = setup_email_account()
    print()
    templates = show_templates()

    if args.setup_only:
        print()
        hdr("Setup complete")
        note(f"Creator  : {creator.get('name', '?')}")
        note(f"Sender   : {sender}")
        note(f"Templates: {len(templates)} available")
        return

    print()
    run_assist(sender)


if __name__ == "__main__":
    main()
