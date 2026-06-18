"""
test_ideas.py  —  Test the StreamEye Idea Generator end to end.

Simulates a full conversation:
  1. Creator describes themselves naturally
  2. Shares recent content history
  3. Seeds some fake audience signals
  4. Agent analyses signals and generates ideas

Usage:
    python test_ideas.py                 # interactive conversation
    python test_ideas.py --seed-signals  # seed fake audience signals first
    python test_ideas.py --quick         # scripted demo (no typing required)
"""

import os
import sys
import json
import uuid
import argparse
import requests

BASE = os.getenv("BACKEND", "http://localhost:8000")

# ── formatting ─────────────────────────────────────────────────────────────────

W = 66
def hr(ch="="):  print(ch * W)
def sep():       hr("-")
def hdr(t):      hr(); print(f"  {t}"); hr()
def note(m):     print(f"  |   {m}")
def arrow(m):    print(f"  ->  {m}")

# ── HTTP helpers ───────────────────────────────────────────────────────────────

def post(path, body):
    r = requests.post(f"{BASE}{path}", json=body, timeout=60)
    r.raise_for_status()
    return r.json()

def get(path):
    r = requests.get(f"{BASE}{path}", timeout=10)
    r.raise_for_status()
    return r.json()

def stream_events(url, body):
    with requests.post(url, json=body, stream=True,
                       headers={"Accept": "text/event-stream"}, timeout=180) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8")
            if line.startswith("data:"):
                yield json.loads(line[5:].strip())

# ── fake audience signals for testing ─────────────────────────────────────────

FAKE_SIGNALS = [
    "How do you stay consistent with posting every day?",
    "Can you make a video about morning routines?",
    "What camera do you use for your videos?",
    "I tried your recipe and it was amazing!",
    "Please do a tutorial on editing videos",
    "How do you deal with negative comments?",
    "What application do you use to edit on your phone?",
    "Can you do a Q&A about how you started?",
    "Your content has really helped me stay motivated",
    "Would love a collab with other creators in your niche",
    "What microphone do you recommend for beginners?",
    "How long does it take you to film each video?",
    "Please make a video about budgeting tips",
    "I love your energy! How do you stay so positive?",
    "Can you do a day in my life video?",
    "Your last video changed my perspective completely",
    "When is your next live stream?",
    "Do you offer 1-on-1 coaching?",
    "How do you grow on TikTok in 2025?",
    "Can you review products in your niche?",
    "I always skip ads but I watch yours all the way through",
    "The editing on your recent video was fire",
    "Please do more beginner content",
    "Would pay for a course from you honestly",
    "How many hours do you work per week on content?",
]

# ── display SSE events ────────────────────────────────────────────────────────

def show_stream(url, body):
    sep()
    note("SSE stream:")
    sep()

    interrupt_val = None
    streaming     = False

    for ev in stream_events(url, body):
        t = ev.get("type")

        if t == "fastapi":
            note(f"[fastapi]  {ev.get('endpoint')}  graph={ev.get('graph')}")

        elif t == "node_enter":
            note(f"[node_enter]  {ev['node']}  (run {ev.get('run',1)})")

        elif t == "node_exit":
            ret = ev.get("returned", {})
            msgs = ret.get("messages", [])
            if msgs:
                for m in msgs:
                    preview = str(m)[:80]
                    note(f"  tool result: {preview}{'...' if len(str(m)) > 80 else ''}")

        elif t == "tool_call":
            note(f"[tool_call]  {ev['name']}(")
            for k, v in ev.get("args", {}).items():
                preview = str(v)[:60] + ("..." if len(str(v)) > 60 else "")
                note(f"               {k}={preview!r}")
            note(f"             )")

        elif t == "token":
            if not streaming:
                print()
                note("[response]")
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

        elif t == "done":
            if streaming:
                print()
                streaming = False
            print()
            sep()
            note("[done]  graph reached END")

    sep()
    return interrupt_val

# ── main conversation loop ────────────────────────────────────────────────────

def run_conversation(quick=False):
    thread_id  = str(uuid.uuid4())
    url        = f"{BASE}/ideas/chat"

    # Quick mode: scripted answers for demo
    QUICK_ANSWERS = [
        "I make personal finance content for millennials who are stressed about money. "
        "I post on TikTok and YouTube. My style is conversational and practical — "
        "no fluff, just real advice. I make money through an online course and brand deals.",

        "My sub-niche is debt payoff and budgeting for people earning under 50k a year.",

        "Recent videos: 1) How I paid off 20k in debt (video), "
        "2) Zero based budgeting explained (video), "
        "3) Best budgeting apps 2025 (video), "
        "4) My monthly spending breakdown photo series (photo), "
        "5) Live Q&A on investing basics (live)",

        "done — please generate the ideas",
    ]
    quick_idx  = [0]

    # Start message
    start_msg  = ("Hi! I want to generate content ideas for my creator business. "
                  "Help me figure out what to make next.")

    hdr(f"IDEA GENERATOR  —  thread {thread_id[:8]}...")
    print()
    note(f"Starting conversation: {start_msg!r}")
    print()

    body = {"thread_id": thread_id, "message": start_msg}

    while True:
        interrupt = show_stream(url, body)
        print()

        if interrupt is None:
            hdr("COMPLETE — Idea generation session finished")
            return

        action   = interrupt.get("action", "")
        question = interrupt.get("question", "")

        if action == "ask_user":
            print(f"  Agent: {question}")
            print()
            if quick and quick_idx[0] < len(QUICK_ANSWERS):
                answer = QUICK_ANSWERS[quick_idx[0]]
                quick_idx[0] += 1
                print(f"  [QUICK MODE] answering: {answer[:60]}...")
            else:
                answer = input("  You: ").strip()
                if not answer:
                    answer = "I'm not sure, please continue"
            value = {"answer": answer}
        else:
            note(f"Unhandled interrupt: {action}")
            return

        url  = f"{BASE}/ideas/chat/resume"
        body = {"thread_id": thread_id, "value": value}

# ── entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-signals", action="store_true",
                    help="Seed fake audience signals before running")
    ap.add_argument("--quick",        action="store_true",
                    help="Use scripted answers for a demo run")
    ap.add_argument("--analytics",    action="store_true",
                    help="Show current topic analytics and exit")
    args = ap.parse_args()

    try:
        requests.get(f"{BASE}/docs", timeout=3)
    except requests.ConnectionError:
        print(f"\n  Server not running. Start it:\n  uvicorn main:application --reload\n")
        sys.exit(1)

    if args.analytics:
        hdr("Topic Analytics")
        data = get("/ideas/analytics")
        topics = data.get("topics", [])
        if not topics:
            note("No topics analysed yet. Run with --seed-signals first.")
        for t in topics:
            trend = "up" if t.get("velocity", 0) > 0.3 else "flat"
            print(f"  {t['topic']:<28} freq={t['frequency']:<4} "
                  f"curiosity={t.get('curiosity_score',0):.0%}  "
                  f"sentiment={t.get('sentiment',0):+.2f}  {trend}")
        return

    if args.seed_signals:
        hdr("Seeding fake audience signals")
        result = post("/ideas/signals",
                      {"messages": FAKE_SIGNALS, "source": "tiktok_chat",
                       "session_id": "test_session"})
        note(f"Ingested {result['ingested']} signals from {result['source']}")
        print()

    run_conversation(quick=args.quick)


if __name__ == "__main__":
    main()
