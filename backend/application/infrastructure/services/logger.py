# ── state / message reports ───────────────────────────────────────────────

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

