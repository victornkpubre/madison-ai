"""
dependencies.py
══════════════════
Shared interface-layer plumbing for any endpoint that streams a LangGraph
run back to the client over SSE. Originally inline in main.py — moved
here since both POST /chat and POST /resume (interface/api/assistant.py)
need it, and it's pure presentation/transport logic, not business logic.
"""
from __future__ import annotations

import json

from langgraph.types import Command

from backend.config import settings


# ── state / message summarisers ───────────────────────────────────────────────

def _msg_label(msg) -> str:
    """One-line description of a LangChain message."""
    name = type(msg).__name__
    tcs  = getattr(msg, "tool_calls", None) or []
    if tcs:
        calls = ", ".join(tc.get("name", "?") for tc in tcs)
        return f"AIMessage(tool_calls=[{calls}])"
    content = str(getattr(msg, "content", ""))
    preview = content[:60] + ("…" if len(content) > 60 else "")
    return f"{name}({preview!r})" if preview else name


def _state_summary(s: object) -> dict:
    """Compact summary of the state dict passed into a node."""
    if not isinstance(s, dict):
        return {}
    out: dict = {}
    msgs = s.get("messages")
    if msgs is not None:
        out["messages"] = len(msgs) if isinstance(msgs, list) else 1
    for k in ("fields", "target", "slices_done", "capture_tool_id"):
        v = s.get(k)
        if v is not None:
            out[k] = v
    recs = s.get("records")
    if recs is not None:
        out["records"] = len(recs) if isinstance(recs, list) else recs
    return out


def _return_summary(r: object) -> dict:
    """Compact summary of the dict a node returned."""
    if not isinstance(r, dict):
        return {}
    out: dict = {}
    msgs = r.get("messages")
    if msgs is not None:
        lst = msgs if isinstance(msgs, list) else [msgs]
        out["messages"] = [_msg_label(m) for m in lst]
    for k in ("fields", "target", "slices_done", "capture_tool_id"):
        v = r.get(k)
        if v is not None:
            out[k] = v
    recs = r.get("records")
    if recs is not None:
        out["records"] = f"{len(recs)} record(s)" if isinstance(recs, list) else recs
    return out


# ── SSE helper ────────────────────────────────────────────────────────────────

def sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


# ── core streamer (emits graph operations as SSE events) ──────────────────────

async def stream_graph(graph, graph_input, config,
                       endpoint_info: dict | None = None,
                       node_names: frozenset = frozenset()):
    """
    Run any compiled LangGraph and forward a rich event stream to the client.

    SSE event types emitted:
      fastapi      – request metadata (endpoint, graph, input summary)
      node_enter   – a graph node started  (node, run number, state summary)
      node_exit    – a graph node finished (node, return value summary)
      route        – routing transition inferred from node sequence
      llm_start    – LLM was invoked      (model name, message types)
      tool_call    – LLM decided to call a tool (name, call_id, args)
      token        – streaming text chunk from the LLM
      interrupt    – graph paused via interrupt()
      done         – graph reached END
    """
    if endpoint_info:
        yield sse({"type": "fastapi", **endpoint_info})

    node_runs: dict[str, int] = {}
    last_node: str | None = None

    async for event in graph.astream_events(graph_input, config, version="v2"):
        ev  = event["event"]
        nm  = event.get("name", "")
        dat = event.get("data", {})

        # ── node enters ────────────────────────────────────────────────────
        if ev == "on_chain_start" and nm in node_names:
            node_runs[nm] = node_runs.get(nm, 0) + 1
            if last_node is not None:
                yield sse({"type": "route",
                           "from_node": last_node,
                           "to_node":   nm,
                           "loop":      last_node == nm})
            last_node = nm
            yield sse({"type":  "node_enter",
                       "node":  nm,
                       "run":   node_runs[nm],
                       "state": _state_summary(dat.get("input"))})

        # ── node exits ─────────────────────────────────────────────────────
        elif ev == "on_chain_end" and nm in node_names:
            yield sse({"type":     "node_exit",
                       "node":     nm,
                       "returned": _return_summary(dat.get("output"))})

        # ── LLM call starts ────────────────────────────────────────────────
        elif ev == "on_chat_model_start":
            raw  = dat.get("messages") or []
            msgs = raw[0] if raw and isinstance(raw[0], list) else raw
            yield sse({"type":     "llm_start",
                       "model":    event.get("metadata", {}).get(
                                       "ls_model_name", settings.openai_model),
                       "messages": [type(m).__name__ for m in msgs]})

        # ── LLM chose to call tools ────────────────────────────────────────
        elif ev == "on_chat_model_end":
            out = dat.get("output")
            for tc in (getattr(out, "tool_calls", None) or []):
                tid = tc.get("id", "")
                yield sse({"type":    "tool_call",
                           "name":    tc.get("name"),
                           "call_id": (tid[:16] + "…") if len(tid) > 16 else tid,
                           "args":    tc.get("args", {})})

        # ── token streaming ────────────────────────────────────────────────
        elif ev == "on_chat_model_stream":
            chunk = dat.get("chunk")
            if chunk and getattr(chunk, "content", None):
                yield sse({"type": "token", "content": chunk.content})

    # After stream: interrupt waiting or graph complete.
    snapshot = await graph.aget_state(config)
    pending  = [i for task in snapshot.tasks for i in (task.interrupts or [])]
    if pending:
        yield sse({"type": "interrupt", "value": pending[0].value})
    else:
        yield sse({"type": "done"})


def resume_command(req) -> Command:
    """Build a LangGraph Command(resume=...) from a ResumeRequest."""
    if req.value is not None:
        return Command(resume=req.value)
    return Command(resume={"action": req.action, "text": req.text})
