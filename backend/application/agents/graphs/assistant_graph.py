import json

from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from backend.application.agents.graphs.prompts.assistant_prompt import SYSTEM_PROMPT
from backend.application.agents.graphs.tools.assistant_tools import ASSISTANT_TOOLS, check_onboarding_status, \
    save_creator_profile, get_knowledge_gaps, save_to_knowledge_base
from backend.application.agents.graphs.tools.telegram_tools import send_message_to_user, broadcast_to_usernames, \
    list_telegram_templates, create_telegram_template, send_telegram_messages_from_template
from backend.application.agents.graphs.tools.email_tools import EMAIL_TOOLS
from backend.application.agents.graphs.tools.template_tools import TEMPLATE_TOOLS
from backend.config import settings
from backend.domain.entities.capture_entity import KNOWN_FIELDS, MAX_SLICES, CaptureSession

from backend.infrastructure.repositories.capture_repository import capture_repository


model = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0.1)
model_with_tools = model.bind_tools(
    [
        *ASSISTANT_TOOLS,
        send_message_to_user,
        broadcast_to_usernames,
        list_telegram_templates,
        create_telegram_template,
        send_telegram_messages_from_template,
        *EMAIL_TOOLS,
        *TEMPLATE_TOOLS,
    ],
    parallel_tool_calls=False
)


class State(MessagesState):
    fields: list
    target: int
    records: list
    slices_done: int
    capture_tool_id: str   # declared so LangGraph persists it; was _tool_id (dropped)


def agent_node(state: State) -> dict:
    messages = [SystemMessage(SYSTEM_PROMPT)] + state["messages"]
    return {"messages": [model_with_tools.invoke(messages)]}


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
        tool_id = new_call["id"]
        records, done = [], 0
    else:
        fields  = state.get("fields", ["tiktok_username"])
        target  = state.get("target", 0)
        tool_id = state.get("capture_tool_id")
        records = list(state.get("records", []))
        done    = state.get("slices_done", 0)

    # Stop conditions checked in CODE (authoritative).
    if len(records) >= target or done >= MAX_SLICES:
        return _finish(records, fields, target, done, tool_id, state,
                       stopped="target reached" if len(records) >= target
                               else "safety limit")

    # Request ONE more slice from the client.
    result = interrupt({
        "action": "record_screen",
        "mode": "records",
        "fields": fields,
        "target": target,
        "have": len(records),
        "slice": done,
        "tool_call_id": tool_id,
    })
    new = (result or {}).get("records", [])
    found = (result or {}).get("found", True)
    records.extend(new)

    if not found:
        return _finish(records, fields, target, done + 1, tool_id, state,
                       stopped="no chat on screen")

    # Persist progress and loop again (route_after_capture re-enters this node).
    return {"fields": fields, "target": target, "records": records,
            "slices_done": done + 1, "capture_tool_id": tool_id}


def _finish(records, fields, target, done, tool_id, state, stopped="target reached"):
    final_records = records[:target]

    # Persist the completed session for later inspection via GET /captures.
    # Additive — does not change the loop's control flow or its response
    # to the agent.
    try:
        capture_repository.save_session(CaptureSession(
            fields=fields, target=target, records=final_records,
            slices_done=done, capture_tool_id=tool_id, stopped_reason=stopped,
        ))
    except Exception:
        pass   # persistence failures must never break the conversation

    payload = json.dumps({
        "records": final_records,
        "collected": len(final_records),
        "target": target,
        "fields": fields,
        "stopped": stopped,
    })[:8000]
    tid = tool_id or state.get("capture_tool_id")
    return {"fields": fields, "target": target, "records": records,
            "slices_done": done,
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


_ONBOARDING_TOOLS = {"check_onboarding_status", "save_creator_profile"}
_TELEGRAM_TOOLS   = {"send_message_to_user", "broadcast_to_usernames",
                     "list_telegram_templates", "create_telegram_template",
                     "send_telegram_messages_from_template"}
_EMAIL_TOOLS    = {"connect_email_account", "list_connected_senders",
                   "list_email_templates", "create_email_template",
                   "send_emails_from_template"}
_TEMPLATE_TOOLS  = {"draft_template"}
_KNOWLEDGE_TOOLS = {"get_knowledge_gaps", "save_to_knowledge_base"}
_DIRECT_TOOLS    = _ONBOARDING_TOOLS | _TELEGRAM_TOOLS | _EMAIL_TOOLS | _TEMPLATE_TOOLS | _KNOWLEDGE_TOOLS


def route_after_agent(state: State) -> str:
    calls = getattr(state["messages"][-1], "tool_calls", None) or []
    if any(c["name"] == "start_capture" for c in calls):
        return "capture"
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


def build_assistant_graph(checkpointer):
    b = StateGraph(State)
    b.add_node("agent",    agent_node)
    b.add_node("capture",  capture_node)
    b.add_node("ask",      ask_node)
    b.add_node("telegram", ToolNode([
        check_onboarding_status, save_creator_profile,
        get_knowledge_gaps, save_to_knowledge_base,
        send_message_to_user, broadcast_to_usernames,
        list_telegram_templates, create_telegram_template,
        send_telegram_messages_from_template,
        *EMAIL_TOOLS,
        *TEMPLATE_TOOLS,
    ]))
    b.add_edge(START, "agent")
    b.add_conditional_edges("agent", route_after_agent,
                             ["capture", "ask", "telegram", END])
    b.add_conditional_edges("capture", route_after_capture, ["capture", "agent"])
    b.add_edge("ask",      "agent")
    b.add_edge("telegram", "agent")   # LLM sees delivery result and reports it
    return b.compile(checkpointer=checkpointer)
