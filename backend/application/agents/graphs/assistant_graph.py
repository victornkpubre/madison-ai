import json
import uuid

from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from langchain_core.messages import SystemMessage, ToolMessage

from application.agents.graphs.prompts.assistant_prompt import SYSTEM_PROMPT
from application.agents.graphs.tools.assistant_tools import ASSISTANT_TOOLS, check_onboarding_status, \
    save_creator_profile, reset_creator_profile, start_stream_capture, capture_other_post, \
    start_inspiration_hunt, get_knowledge_gaps, clear_knowledge_base, \
    save_to_knowledge_base, list_knowledge_base, get_content_strategy_profile
from application.agents.graphs.tools.telegram_tools import send_message_to_user, broadcast_to_usernames, \
    list_telegram_templates, create_telegram_template, send_telegram_messages_from_template
from application.agents.graphs.tools.email_tools import EMAIL_TOOLS
from application.agents.graphs.tools.template_tools import TEMPLATE_TOOLS
from application.agents.graphs.tools.idea_tools import generate_stream_report, suggest_search_keywords, \
    analyze_other_stream
from application.agents.graphs.tools.lead_tools import LEAD_TOOLS
from application.agents.resilience import invoke_llm
from domain.entities.capture_entity import KNOWN_FIELDS, MAX_SLICES, CaptureSession
from composition import idea_service

from infrastructure.repositories.capture_repository import capture_repository


_TOOLS = [
    *ASSISTANT_TOOLS,
    send_message_to_user,
    broadcast_to_usernames,
    list_telegram_templates,
    create_telegram_template,
    send_telegram_messages_from_template,
    generate_stream_report,
    suggest_search_keywords,
    analyze_other_stream,
    *EMAIL_TOOLS,
    *TEMPLATE_TOOLS,
    *LEAD_TOOLS,
]
_agent_bind = lambda m: m.bind(temperature=0.1).bind_tools(_TOOLS, parallel_tool_calls=False)

# Continuous inspiration hunt tuning. The hunt auto-captures whatever post the
# creator is scrolling past, one frame at a time, until `target` relevant posts
# are found or the creator stops it. These bound that loop so it can never run
# away: MAX_SLICES caps total capture attempts (a creator who stops scrolling
# can't loop forever), MAX_MISSES ends the hunt after a run of unreadable / no-
# window frames (they closed or switched away from the app), and SLICE_DELAY is
# how long the client waits before each NON-first shot so the grab lands on a
# freshly-scrolled post instead of re-capturing the same one.
INSPIRATION_MAX_SLICES = 40
INSPIRATION_MAX_MISSES = 4
INSPIRATION_SLICE_DELAY = 3.0

# When a LIVE-chat capture (records or messages) finds no chat overlay, the
# failure is genuinely ambiguous: either the creator's own overlay wasn't
# visible, OR they never wanted to read their own chat at all and actually meant
# to grab inspiration from ANOTHER creator's post — a flow that needs no overlay.
# The loop can't tell which, so it hands the agent this explicit next_step
# instead of a bare "no chat found", which the agent otherwise tends to answer
# by blindly re-running the same wrong capture (the exact loop we saw a creator
# get stuck in).
_NO_CHAT_NEXT_STEP = (
    "This tool reads the creator's OWN live chat overlay, so 'no chat found' "
    "means that overlay wasn't on screen. Do NOT silently retry. First confirm "
    "what the creator actually wanted: if they were after inspiration or content "
    "ideas from ANOTHER creator's post/video, this is the wrong tool — that flow "
    "(capture_other_post or the inspiration hunt) screenshots the whole window "
    "and needs no chat overlay, so switch to it. Only retry this capture if the "
    "creator confirms they really are trying to read their own live chat."
)


class State(MessagesState):
    fields: list
    target: int
    records: list
    slices_done: int
    capture_tool_id: str   # declared so LangGraph persists it; was _tool_id (dropped)
    platform: str
    stream_target: int
    stream_messages: list
    stream_slices_done: int
    stream_capture_tool_id: str
    stream_session_id: str
    stream_platform: str
    inspiration_target: int
    inspiration_platform: str
    inspiration_relevant: list
    inspiration_checked: int
    inspiration_tool_id: str    # tool_call_id of the active continuous hunt
    inspiration_seen: list      # dedup keys for every distinct post already scanned
    inspiration_slices: int     # total capture attempts this hunt (bounds the loop)
    inspiration_misses: int     # consecutive unreadable/not-found frames


async def agent_node(state: State) -> dict:
    messages = [SystemMessage(SYSTEM_PROMPT)] + state["messages"]
    response = await invoke_llm(messages, bind=_agent_bind, use_cache=False)
    return {"messages": [response]}


def capture_node(state: State) -> dict:
    """Drive the capture loop. Initialises from the start_capture tool call the
    FIRST time it sees a new call, then accumulates records in state across
    re-entries until `target` is reached."""
    last = state["messages"][-1]

    # Is there a start_capture tool call on the latest message?
    new_call = None
    if getattr(last, "tool_calls", None):
        new_call = next((c for c in last.tool_calls if c["name"] == "start_capture"), None)

    # A NEW capture = a tool call whose id we haven't started yet. Otherwise we're
    # mid-loop and must read the running totals from state (never reset them).
    if new_call and new_call["id"] != state.get("capture_tool_id"):
        args = new_call.get("args", {})
        fields = [f for f in args.get("fields", []) if f in KNOWN_FIELDS] or ["tiktok_username"]
        target = int(args.get("target", 0) or 0)
        platform = (args.get("platform") or "tiktok").strip().lower()
        tool_id = new_call["id"]
        records, done = [], 0
    else:
        fields   = state.get("fields", ["tiktok_username"])
        target   = state.get("target", 0)
        platform = state.get("platform", "tiktok")
        tool_id  = state.get("capture_tool_id")
        records  = list(state.get("records", []))
        done     = state.get("slices_done", 0)

    # Stop conditions checked in CODE (authoritative).
    if len(records) >= target or done >= MAX_SLICES:
        return _finish(records, fields, target, done, tool_id, state, platform,
                       stopped="target reached" if len(records) >= target
                               else "safety limit")

    # Request ONE more slice from the client.
    result = interrupt({
        "action": "record_screen",
        "mode": "records",
        "fields": fields,
        "platform": platform,
        "target": target,
        "have": len(records),
        "slice": done,
        "tool_call_id": tool_id,
    })
    new = (result or {}).get("records", [])
    found = (result or {}).get("found", True)
    error = (result or {}).get("error")
    records.extend(new)

    # An extraction/API failure on the client (e.g. a bad ANTHROPIC_API_KEY)
    # must NOT be reported as "no chat found" — that misdiagnosis hides the
    # real cause. Surface it so the agent can tell the creator what to fix.
    if error:
        return _finish(records, fields, target, done + 1, tool_id, state, platform,
                       stopped=f"capture failed on the client: {error}")
    if not found:
        return _finish(records, fields, target, done + 1, tool_id, state, platform,
                       stopped=f"no chat found on screen for {platform}",
                       next_step=_NO_CHAT_NEXT_STEP)

    # Persist progress and loop again (route_after_capture re-enters this node).
    return {"fields": fields, "target": target, "platform": platform, "records": records,
            "slices_done": done + 1, "capture_tool_id": tool_id}


def _finish(records, fields, target, done, tool_id, state, platform="tiktok",
            stopped="target reached", next_step=""):
    final_records = records[:target]

    # Persist the completed session for later inspection via GET /captures.
    # Additive — does not change the loop's control flow or its response
    # to the agent. NOTE: platform is carried on the CaptureSession object
    # for the in-conversation payload below, but capture_sessions' DB table/
    # model doesn't have a platform column yet, so it isn't persisted there
    # — only the JSON payload the agent sees mentions it for now.
    try:
        capture_repository.save_session(CaptureSession(
            fields=fields, target=target, records=final_records,
            slices_done=done, capture_tool_id=tool_id, stopped_reason=stopped,
            platform=platform,
        ))
    except Exception:
        pass   # persistence failures must never break the conversation

    payload_dict = {
        "records": final_records,
        "collected": len(final_records),
        "target": target,
        "fields": fields,
        "platform": platform,
        "stopped": stopped,
    }
    if next_step:
        payload_dict["next_step"] = next_step
    payload = json.dumps(payload_dict)[:8000]
    tid = tool_id or state.get("capture_tool_id")
    return {"fields": fields, "target": target, "records": records,
            "slices_done": done,
            "messages": [ToolMessage(content=payload, tool_call_id=tid)]}


def stream_capture_node(state: State) -> dict:
    """Drive the stream-message capture loop. Mirrors capture_node exactly,
    but collects raw chat message text (not specific fields) and tags every
    captured message with a fresh session_id so generate_stream_report() can
    later pull exactly this capture's messages, not the whole signal pool."""
    last = state["messages"][-1]

    new_call = None
    if getattr(last, "tool_calls", None):
        new_call = next((c for c in last.tool_calls if c["name"] == "start_stream_capture"), None)

    if new_call and new_call["id"] != state.get("stream_capture_tool_id"):
        args = new_call.get("args", {})
        target = int(args.get("target", 0) or 0)
        platform = (args.get("platform") or "tiktok").strip().lower()
        tool_id = new_call["id"]
        msgs, done = [], 0
        session_id = str(uuid.uuid4())
    else:
        target     = state.get("stream_target", 0)
        platform   = state.get("stream_platform", "tiktok")
        tool_id    = state.get("stream_capture_tool_id")
        msgs       = list(state.get("stream_messages", []))
        done       = state.get("stream_slices_done", 0)
        session_id = state.get("stream_session_id", "")

    # Stop conditions checked in CODE (authoritative) — same pattern as capture_node.
    if len(msgs) >= target or done >= MAX_SLICES:
        return _finish_stream(msgs, target, done, tool_id, session_id, state,
                              stopped="target reached" if len(msgs) >= target
                                      else "safety limit")

    # Request ONE more slice from the client.
    result = interrupt({
        "action": "record_screen",
        "mode": "messages",
        "platform": platform,
        "target": target,
        "have": len(msgs),
        "slice": done,
        "tool_call_id": tool_id,
    })
    new = (result or {}).get("messages", [])
    found = (result or {}).get("found", True)
    error = (result or {}).get("error")
    msgs.extend(new)

    # See capture_node: a client-side extraction/API failure is reported as
    # itself, not silently downgraded to "no chat found".
    if error:
        return _finish_stream(msgs, target, done + 1, tool_id, session_id, state,
                              stopped=f"capture failed on the client: {error}")
    if not found:
        return _finish_stream(msgs, target, done + 1, tool_id, session_id, state,
                              stopped=f"no chat found on screen for {platform}",
                              next_step=_NO_CHAT_NEXT_STEP)

    # Persist progress and loop again (route_after_stream_capture re-enters this node).
    return {"stream_target": target, "stream_platform": platform, "stream_messages": msgs,
            "stream_slices_done": done + 1, "stream_capture_tool_id": tool_id,
            "stream_session_id": session_id}


def _finish_stream(msgs, target, done, tool_id, session_id, state, stopped="target reached",
                   next_step=""):
    final_msgs = msgs[:target]
    platform = state.get("stream_platform", "tiktok")

    # Ingest each captured chat-type message into audience_signals, tagged
    # with this session's id. system/join/gift rows aren't viewer commentary
    # worth analysing, so they're skipped — only real chat text goes in.
    ingested = 0
    for m in final_msgs:
        text = (m.get("text") or "").strip()
        if text and m.get("type", "chat") == "chat":
            try:
                idea_service.ingest_signal(text, source=platform, session_id=session_id)
                ingested += 1
            except Exception:
                pass   # one bad row must never break the capture loop

    payload_dict = {
        "session_id": session_id,
        "platform":   platform,
        "captured":   len(final_msgs),
        "ingested":   ingested,
        "target":     target,
        "stopped":    stopped,
    }
    if next_step:
        payload_dict["next_step"] = next_step
    payload = json.dumps(payload_dict)[:8000]
    tid = tool_id or state.get("stream_capture_tool_id")
    return {"stream_target": target, "stream_platform": platform, "stream_messages": msgs,
            "stream_slices_done": done, "stream_session_id": session_id,
            "messages": [ToolMessage(content=payload, tool_call_id=tid)]}


def ask_node(state: State) -> dict:
    last = state["messages"][-1]
    call = next(c for c in last.tool_calls if c["name"] == "ask_creator")
    answer = interrupt({"action": "ask_user",
                        "question": call.get("args", {}).get("question", ""),
                        "tool_call_id": call["id"]})
    if isinstance(answer, dict):
        answer = answer.get("answer", "")
    return {"messages": [ToolMessage(content=str(answer), tool_call_id=call["id"])]}


async def post_screenshot_node(state: State) -> dict:
    """Single-shot screenshot capture + vision analysis of ANOTHER creator's
    post/video page — not the creator's own live chat, and not a multi-slice
    loop like capture_node/stream_capture_node above. One frame is enough,
    so this is modeled on ask_node's shape instead: call interrupt() once,
    use whatever comes back, done. No extra State fields needed for the
    same reason ask_node needs none — re-entry after resume re-runs this
    node from the top, reaches the same interrupt() call, and this time gets
    the resume value back instead of pausing again.

    The vision extraction + relevance/idea reasoning both live in
    idea_service.analyze_other_post_screenshot() — this node's only job is
    the interrupt/resume plumbing and turning the result into a ToolMessage.
    """
    last = state["messages"][-1]
    call = next(c for c in last.tool_calls if c["name"] == "capture_other_post")
    platform = (call.get("args", {}).get("platform") or "tiktok").strip().lower()
    tool_id = call["id"]

    result = interrupt({
        "action": "record_screen",
        "mode": "post_screenshot",
        "platform": platform,
        "tool_call_id": tool_id,
    })
    image_b64 = (result or {}).get("image_b64")
    found = (result or {}).get("found", bool(image_b64))
    error = (result or {}).get("error")

    if error:
        payload = f"Screenshot capture failed on the client: {error}"
    elif not found or not image_b64:
        payload = (f"Couldn't find a {platform} window on screen to screenshot — "
                   f"make sure it's open and visible, not minimized.")
    else:
        try:
            analysis = await idea_service.analyze_other_post_screenshot(image_b64, platform)
            payload = json.dumps(analysis)[:8000]
        except Exception as e:
            payload = f"Captured the screenshot, but analysis failed: {e}"

    return {"messages": [ToolMessage(content=payload, tool_call_id=tool_id)]}


def _post_key(analysis: dict) -> str:
    """Stable-enough identity for a captured post so the same one lingered on
    across consecutive shots isn't counted twice. The caption is the strongest
    signal; fall back to the topic label when no caption was read."""
    extraction = analysis.get("extraction", {}) or {}
    caption = (extraction.get("caption") or "").strip().lower()
    if caption:
        return caption[:120]
    return (analysis.get("topic") or "").strip().lower()


def _relevant_record(analysis: dict) -> dict:
    """Pack one relevant post's metadata, engagement, comments, and ideas for
    the tally — analyze_other_post_screenshot already extracts all of it, and
    it's both what makes the final summary useful and what tells two posts
    apart. Comments are capped so several posts still fit the payload cap."""
    extraction = analysis.get("extraction", {}) or {}
    return {
        "topic": analysis.get("topic"),
        "summary": analysis.get("summary"),
        "relevance_reason": analysis.get("relevance_reason", ""),
        "ideas": analysis.get("ideas", []),
        "caption": extraction.get("caption", ""),
        "hashtags": extraction.get("hashtags", []),
        "engagement": {
            "likes": extraction.get("like_count"),
            "comments": extraction.get("comment_count"),
            "saves": extraction.get("save_count"),
        },
        "comments": (extraction.get("comments") or [])[:5],
    }


def _finish_inspiration(relevant, target, checked, tool_id, state, stopped):
    """End a continuous hunt and hand the agent the full collected results to
    present. Mirrors _finish/_finish_stream's shape for the other capture loops."""
    payload = json.dumps({
        "relevant_found": len(relevant),
        "target": target,
        "checked": checked,
        "results": relevant,
        "stopped": stopped,
        "status": "hunt complete — present these results now; do not capture more",
    })[:8000]
    tid = tool_id or state.get("inspiration_tool_id")
    return {"inspiration_target": target, "inspiration_relevant": relevant,
            "inspiration_checked": checked,
            "messages": [ToolMessage(content=payload, tool_call_id=tid)]}


async def inspiration_hunt_node(state: State) -> dict:
    """Continuous inspiration capture. Mirrors capture_node's one-interrupt-per-
    entry loop (route_after_inspiration_hunt re-enters this node for each shot):
    each entry grabs ONE full-window screenshot of whatever post the creator is
    scrolling past, analyses it, and keeps the relevant, non-duplicate ones
    until `target` are collected, the creator stops, or a safety limit is hit.
    The creator scrolls freely the whole time — the client waits slice_delay
    between shots so each grab lands on a fresh post rather than re-reading the
    same one. The creator stops it from the client (a resume carrying stop=True)
    rather than via a tool call, since the agent isn't in the loop while it runs."""
    last = state["messages"][-1]

    new_call = None
    if getattr(last, "tool_calls", None):
        new_call = next((c for c in last.tool_calls if c["name"] == "start_inspiration_hunt"), None)

    # A NEW hunt = a start_inspiration_hunt call whose id we haven't begun yet.
    # Otherwise we're mid-loop and must read the running tallies from state.
    if new_call and new_call["id"] != state.get("inspiration_tool_id"):
        args = new_call.get("args", {})
        target = max(1, int(args.get("target") or 4))
        platform = (args.get("platform") or "tiktok").strip().lower()
        tool_id = new_call["id"]
        relevant, seen, slices, misses = [], [], 0, 0
    else:
        target   = state.get("inspiration_target") or 4
        platform = state.get("inspiration_platform") or "tiktok"
        tool_id  = state.get("inspiration_tool_id")
        relevant = list(state.get("inspiration_relevant", []))
        seen     = list(state.get("inspiration_seen", []))
        slices   = state.get("inspiration_slices", 0)
        misses   = state.get("inspiration_misses", 0)

    # Authoritative stop conditions, checked in CODE.
    if len(relevant) >= target:
        return _finish_inspiration(relevant, target, len(seen), tool_id, state, "target reached")
    if slices >= INSPIRATION_MAX_SLICES:
        return _finish_inspiration(relevant, target, len(seen), tool_id, state, "reached the scan limit")

    # Ask the client for ONE screenshot. The first shot fires immediately (the
    # creator is already on a post); later shots wait slice_delay so the creator
    # has time to scroll to a new post before it's grabbed.
    result = interrupt({
        "action": "record_screen",
        "mode": "post_screenshot",
        "continuous": True,
        "platform": platform,
        "slice_delay": 0 if slices == 0 else INSPIRATION_SLICE_DELAY,
        "relevant_found": len(relevant),
        "target": target,
        "tool_call_id": tool_id,
    })
    image_b64 = (result or {}).get("image_b64")
    found = (result or {}).get("found", bool(image_b64))
    error = (result or {}).get("error")
    stop = bool((result or {}).get("stop"))

    if stop:
        return _finish_inspiration(relevant, target, len(seen), tool_id, state,
                                   "stopped early by the creator")

    looped = {"inspiration_target": target, "inspiration_platform": platform,
              "inspiration_relevant": relevant, "inspiration_seen": seen,
              "inspiration_slices": slices + 1, "inspiration_tool_id": tool_id,
              "inspiration_checked": len(seen)}

    # An unreadable frame (client error or no window) is treated as transient:
    # count it toward the miss streak and keep looping, but end the hunt once a
    # run of them says the creator has closed or left the app.
    if error or not found or not image_b64:
        misses += 1
        if misses >= INSPIRATION_MAX_MISSES:
            return _finish_inspiration(relevant, target, len(seen), tool_id, state,
                                       f"couldn't see the {platform} window — make sure it's open")
        return {**looped, "inspiration_misses": misses}

    try:
        analysis = await idea_service.analyze_other_post_screenshot(image_b64, platform)
    except Exception:
        misses += 1
        if misses >= INSPIRATION_MAX_MISSES:
            return _finish_inspiration(relevant, target, len(seen), tool_id, state,
                                       "analysis kept failing")
        return {**looped, "inspiration_misses": misses}

    misses = 0   # a readable frame resets the miss streak
    key = _post_key(analysis)
    if key and key in seen:
        # Same post still on screen — don't double-count; loop for a new one.
        return {**looped, "inspiration_misses": misses}
    if key:
        seen.append(key)
    if bool(analysis.get("relevant")):
        relevant.append(_relevant_record(analysis))

    # Persist progress and loop again (route_after_inspiration_hunt re-enters).
    return {"inspiration_target": target, "inspiration_platform": platform,
            "inspiration_relevant": relevant, "inspiration_seen": seen,
            "inspiration_slices": slices + 1, "inspiration_misses": misses,
            "inspiration_tool_id": tool_id, "inspiration_checked": len(seen)}


_ONBOARDING_TOOLS = {"check_onboarding_status", "save_creator_profile", "reset_creator_profile"}
_TELEGRAM_TOOLS   = {"send_message_to_user", "broadcast_to_usernames",
                     "list_telegram_templates", "create_telegram_template",
                     "send_telegram_messages_from_template"}
_EMAIL_TOOLS    = {"connect_email_account", "list_connected_senders",
                   "list_email_templates", "create_email_template",
                   "send_emails_from_template"}
_TEMPLATE_TOOLS  = {"draft_template"}
_LEAD_TOOLS      = {"add_lead", "list_leads", "delete_lead",
                    "draft_lead_followup", "send_lead_followup"}
_KNOWLEDGE_TOOLS = {"get_knowledge_gaps", "save_to_knowledge_base",
                    "list_knowledge_base", "get_content_strategy_profile",
                    "clear_knowledge_base"}
_STREAM_TOOLS    = {"generate_stream_report"}
_INSPIRATION_DIRECT_TOOLS = {"suggest_search_keywords", "analyze_other_stream"}
_DIRECT_TOOLS    = (_ONBOARDING_TOOLS | _TELEGRAM_TOOLS | _EMAIL_TOOLS | _TEMPLATE_TOOLS
                    | _LEAD_TOOLS | _KNOWLEDGE_TOOLS | _STREAM_TOOLS | _INSPIRATION_DIRECT_TOOLS)


def route_after_agent(state: State) -> str:
    calls = getattr(state["messages"][-1], "tool_calls", None) or []
    if any(c["name"] == "start_capture" for c in calls):
        return "capture"
    if any(c["name"] == "start_stream_capture" for c in calls):
        return "stream_capture"
    if any(c["name"] == "capture_other_post" for c in calls):
        return "post_screenshot"
    if any(c["name"] == "start_inspiration_hunt" for c in calls):
        return "inspiration_hunt"
    if any(c["name"] == "ask_creator" for c in calls):
        return "ask"
    if any(c["name"] in _DIRECT_TOOLS for c in calls):
        return "telegram"   # ToolNode handles all direct-execute tools
    return END


def route_after_capture(state: State) -> str:
    """If the last message is a ToolMessage, capture finished -> back to agent to
    summarise. Otherwise we just stored a slice -> loop for the next slice."""
    last = state["messages"][-1]
    return "agent" if isinstance(last, ToolMessage) else "capture"


def route_after_stream_capture(state: State) -> str:
    """Same shape as route_after_capture, for the stream-message loop."""
    last = state["messages"][-1]
    return "agent" if isinstance(last, ToolMessage) else "stream_capture"


def route_after_inspiration_hunt(state: State) -> str:
    """Same shape as route_after_capture, for the continuous inspiration loop:
    a ToolMessage means the hunt finished -> back to agent to present results;
    anything else is a stored slice -> loop for the next screenshot."""
    last = state["messages"][-1]
    return "agent" if isinstance(last, ToolMessage) else "inspiration_hunt"


def build_assistant_graph(checkpointer):
    b = StateGraph(State)
    b.add_node("agent",          agent_node)
    b.add_node("capture",        capture_node)
    b.add_node("stream_capture", stream_capture_node)
    b.add_node("post_screenshot", post_screenshot_node)
    b.add_node("inspiration_hunt", inspiration_hunt_node)
    b.add_node("ask",            ask_node)
    b.add_node("telegram", ToolNode([
        check_onboarding_status, save_creator_profile, reset_creator_profile,
        clear_knowledge_base,
        get_knowledge_gaps, save_to_knowledge_base,
        list_knowledge_base, get_content_strategy_profile,
        send_message_to_user, broadcast_to_usernames,
        list_telegram_templates, create_telegram_template,
        send_telegram_messages_from_template,
        generate_stream_report,
        suggest_search_keywords,
        analyze_other_stream,
        *EMAIL_TOOLS,
        *TEMPLATE_TOOLS,
        *LEAD_TOOLS,
    ]))
    b.add_edge(START, "agent")
    b.add_conditional_edges("agent", route_after_agent,
                             ["capture", "stream_capture", "post_screenshot",
                              "inspiration_hunt", "ask", "telegram", END])
    b.add_conditional_edges("capture", route_after_capture, ["capture", "agent"])
    b.add_conditional_edges("stream_capture", route_after_stream_capture,
                             ["stream_capture", "agent"])
    b.add_conditional_edges("inspiration_hunt", route_after_inspiration_hunt,
                             ["inspiration_hunt", "agent"])
    b.add_edge("post_screenshot", "agent")
    b.add_edge("ask",      "agent")
    b.add_edge("telegram", "agent")   # LLM sees delivery result and reports it
    return b.compile(checkpointer=checkpointer)
