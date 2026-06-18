"""
test_assist.py  —  full graph + FastAPI flow trace for the creator-assistant.

Displays every SSE event emitted by main.py:
  [fastapi]    endpoint received, graph called
  [node_enter] a graph node started (state snapshot)
  [node_exit]  a graph node finished (return value)
  [route]      routing transition between nodes
  [llm_start]  the LLM was invoked (model + message types)
  [tool_call]  the LLM called a tool (name + args)
  [token]      streaming text token
  [interrupt]  graph paused via interrupt()
  [done]       graph reached END

Usage:
    FAKE_CAPTURE=1 python test_assist.py "capture 5 tiktok usernames and telegram"
    python test_assist.py          # interactive prompt
"""
import os
import sys
import json
import uuid
import requests

BASE     = os.getenv("BACKEND", "http://localhost:8000")
USE_FAKE = bool(os.getenv("FAKE_CAPTURE"))

try:
    if USE_FAKE:
        raise ImportError
    from app.utils import capture
    HAVE_CAPTURE = True
except Exception:
    HAVE_CAPTURE = False


# ── formatting ────────────────────────────────────────────────────────────────

W = 64

def hr(ch="═"):   print(ch * W)
def sep():        hr("─")
def hdr(t):       hr(); print(f"  {t}"); hr()
def note(m):      print(f"  ┆  {m}")
def arrow(m):     print(f"  →  {m}")
def indent(m, n=6): print(" " * n + m)


# ── capture helper ────────────────────────────────────────────────────────────

def do_capture(value: dict) -> dict:
    fields    = value.get("fields", ["tiktok_username"])
    target    = int(value.get("target", 0) or 0)
    have      = int(value.get("have",   0) or 0)
    remaining = max(target - have, 1)
    if HAVE_CAPTURE:
        return capture.capture_records(
            fields, target=remaining, slice_index=value.get("slice", 0))
    recs = [{f: f"{f}_{have + i}" for f in fields} for i in range(remaining)]
    note(f"fake capture  →  {len(recs)} record(s) generated")
    return {"records": recs, "found": True}


# ── SSE iterator ──────────────────────────────────────────────────────────────

def stream_events(url: str, body: dict):
    with requests.post(url, json=body, stream=True,
                       headers={"Accept": "text/event-stream"}, timeout=120) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8")
            if line.startswith("data:"):
                yield json.loads(line[5:].strip())


# ── route reason inference ────────────────────────────────────────────────────

def _route_reason(from_n: str, to_n: str, loop: bool, ctx: dict) -> str:
    calls = ctx.get("last_tool_calls", [])
    if from_n == "agent":
        if "start_capture" in calls:
            return "start_capture in tool_calls"
        if "ask_creator" in calls:
            return "ask_creator in tool_calls"
        return "tool calls present"
    if from_n == "capture":
        if loop:
            return "no ToolMessage yet  (progress update only)"
        return "ToolMessage found  →  capture complete"
    if from_n == "ask":
        return "fixed edge  ask → agent"
    if from_n == "tools":
        return "tool executed  →  back to agent"
    return ""


# ── per-event display functions ───────────────────────────────────────────────

def _show_fastapi(ev: dict):
    print()
    note(f"[fastapi]    {ev.get('endpoint')}  |  "
         f"graph={ev.get('graph')}  "
         f"thread={ev.get('thread_id')}")
    note(f"             input={ev.get('input', '')}")


def _show_node_enter(ev: dict):
    node  = ev.get("node", "?")
    run   = ev.get("run", 1)
    state = ev.get("state", {})
    print()
    sep()
    note(f"[node_enter] {node}  (run {run})")
    if state:
        parts = []
        for k, v in state.items():
            parts.append(f"{k}={v!r}")
        note(f"             state: {', '.join(parts)}")


def _show_node_exit(ev: dict, ctx: dict):
    node = ev.get("node", "?")
    ret  = ev.get("returned", {})
    note(f"[node_exit]  {node}  returned:")
    if not ret:
        note("             (empty)")
        return
    msgs = ret.pop("messages", None)
    if msgs:
        for i, m in enumerate(msgs):
            label = "messages :" if i == 0 else "          "
            note(f"             {label}  {m}")
    for k, v in ret.items():
        note(f"             {k:<12}  {v}")
    if msgs is not None:
        ret["messages"] = msgs   # restore for ctx tracking
    # track whether last exit produced a ToolMessage
    ctx["last_exit_had_tool_msg"] = any(
        "ToolMessage" in str(m) for m in (msgs or []))


def _show_route(ev: dict, ctx: dict):
    from_n = ev.get("from_node", "?")
    to_n   = ev.get("to_node",   "?")
    loop   = ev.get("loop", False)
    reason = _route_reason(from_n, to_n, loop, ctx)
    sep()
    arrow(f"route: {from_n}  →  {to_n}  ({reason})")
    ctx["last_tool_calls"] = []   # consumed by this route


def _show_llm_start(ev: dict):
    model = ev.get("model", "?")
    msgs  = ev.get("messages", [])
    note(f"[llm_start]  {model}  messages=[{', '.join(msgs)}]")


def _show_tool_call(ev: dict, ctx: dict):
    name    = ev.get("name", "?")
    call_id = ev.get("call_id", "")
    args    = ev.get("args", {})
    note(f"[tool_call]  {name}(")
    for k, v in args.items():
        note(f"               {k}={v!r}")
    note(f"             )  call_id={call_id}")
    ctx.setdefault("last_tool_calls", []).append(name)


def _show_interrupt(ev: dict):
    val    = ev.get("value", {})
    action = val.get("action", "?")
    print()
    sep()
    note(f"[interrupt]  GRAPH PAUSED  action={action}")
    for k, v in val.items():
        note(f"             {k:<16} {str(v)[:70]}")


def _show_done():
    print()
    sep()
    note("[done]       graph reached END")


# ── main stream processor ─────────────────────────────────────────────────────

def process_stream(url: str, body: dict) -> dict | None:
    """Consume the SSE stream, print each event, return interrupt value or None."""
    print()
    sep()
    note("SSE stream open")
    sep()

    ctx: dict = {
        "streaming":            False,
        "last_tool_calls":      [],
        "last_exit_had_tool_msg": False,
    }
    interrupt_val = None

    for ev in stream_events(url, body):
        t = ev.get("type")

        if t == "fastapi":
            _show_fastapi(ev)

        elif t == "node_enter":
            _show_node_enter(ev)

        elif t == "node_exit":
            _show_node_exit(ev, ctx)

        elif t == "route":
            _show_route(ev, ctx)

        elif t == "llm_start":
            _show_llm_start(ev)

        elif t == "tool_call":
            _show_tool_call(ev, ctx)

        elif t == "token":
            if not ctx["streaming"]:
                print()
                note("[token]      LLM streaming response:")
                print()
                print("  ", end="", flush=True)
                ctx["streaming"] = True
            print(ev["content"], end="", flush=True)

        elif t == "interrupt":
            if ctx["streaming"]:
                print()
                ctx["streaming"] = False
            interrupt_val = ev["value"]
            _show_interrupt(ev)

        elif t == "done":
            if ctx["streaming"]:
                print()
                ctx["streaming"] = False
            _show_done()

    print()
    sep()
    return interrupt_val


# ── main run loop ─────────────────────────────────────────────────────────────

def run(prompt: str):
    thread_id = str(uuid.uuid4())
    url       = f"{BASE}/assist"
    body      = {"thread_id": thread_id, "message": prompt}
    req_num   = 0

    while True:
        req_num += 1
        print()

        # ── print request header ───────────────────────────────────────────
        if req_num == 1:
            hdr(f"REQUEST {req_num}  →  POST /assist")
            print(f"  {'thread_id':<14} {thread_id[:8]}…")
            print(f"  {'message':<14} {prompt!r}")
        else:
            hdr(f"REQUEST {req_num}  →  POST /assist/resume")
            print(f"  {'thread_id':<14} {thread_id[:8]}…")
            val = body.get("value", {})
            if "records" in val:
                print(f"  {'value.records':<14} {len(val['records'])} record(s)")
                print(f"  {'value.found':<14} {val.get('found', True)}")
            elif "answer" in val:
                print(f"  {'value.answer':<14} {val['answer']!r}")
            else:
                print(f"  {'value':<14} {json.dumps(val)}")

        # ── stream ─────────────────────────────────────────────────────────
        interrupt_val = process_stream(url, body)

        if interrupt_val is None:
            print()
            hdr("✓  COMPLETE  —  graph ran to END")
            return

        # ── handle the interrupt ───────────────────────────────────────────
        action = interrupt_val.get("action", "")
        print()

        if action == "ask_user":
            question = interrupt_val.get("question", "")
            print(f"  ❓  {question}")
            answer = input("      your answer: ").strip()
            value  = {"answer": answer}

        elif action == "record_screen":
            fields_l = interrupt_val.get("fields", [])
            have     = int(interrupt_val.get("have", 0) or 0)
            target   = int(interrupt_val.get("target", 0) or 0)
            print(f"  📷  capturing {fields_l}  ({have}/{target})…")
            value = do_capture(interrupt_val)

        else:
            note(f"unhandled interrupt action: {action}")
            return

        url  = f"{BASE}/assist/resume"
        body = {"thread_id": thread_id, "value": value}


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) or input("prompt: ")
    run(prompt)
