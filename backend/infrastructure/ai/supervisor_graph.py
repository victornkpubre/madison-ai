"""
supervisor_graph.py
===================
The single entry point for all StreamEye agents.

Architecture
────────────
One compiled graph (main_graph) with a supervisor node that reads each
incoming message and routes to one of three sub-graphs:

  assist_agent — creator commands (capture, email, send, knowledge, templates)
  idea_agent   — content strategy (profile collection, idea generation)
  reply_agent  — viewer messages (knowledge lookup, approval, Telegram delivery)

Sub-graphs are nodes of the parent graph. They are compiled WITHOUT a
checkpointer — the parent's checkpointer owns all state persistence,
including interrupts fired inside any sub-graph.

State
─────
MainState carries every field used by any sub-graph. When LangGraph passes
state into a sub-graph node, it filters to the fields that exist in the
sub-graph's own schema. Updates the sub-graph returns are merged back into
the parent state. Every field must be declared here or it will be lost.

Interrupt / resume
──────────────────
When a sub-graph calls interrupt() the signal propagates to the parent.
The parent's checkpointer saves the full state including which sub-graph
node is active. On resume, Command(resume=value) restores the checkpoint
and continues from inside the sub-graph — the supervisor is not re-entered
until the sub-graph fully completes its current turn.

Routing
───────
  chat_id present in state → viewer message → reply_agent (no LLM needed)
  creator message          → supervisor LLM classifies intent
    "idea / content / generate / audience / strategy" → idea_agent
    everything else                                   → assist_agent
  after sub-agent response → supervisor runs again → FINISH if done
"""

from __future__ import annotations

from typing import Optional, Literal

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import BaseModel

from backend.config import settings

# Import sub-graph builders — sub-graphs are built without checkpointers
from backend.application.agents.graphs.assistant_graph import build_assistant_graph
from backend.infrastructure.ai.reply_graph import build_reply_graph
from backend.application.agents.graphs.ideation_graph import build_idea_graph


# ── unified state ─────────────────────────────────────────────────────────────
# All fields from all three sub-graphs must be declared here so LangGraph
# persists them correctly through the parent checkpointer.

class MainState(MessagesState):
    # ── routing ────────────────────────────────────────────────────────────
    next_agent: str          # supervisor's routing decision for this turn

    # ── reply_agent (infrastructure/ai/reply_graph.py) ─────────────────────
    chat_id:     str         # Telegram chat_id of the viewer; empty for creator
    decision:    Optional[str]   # approve | edit | reject
    final_reply: Optional[str]   # text actually delivered to viewer

    # ── assist_agent (application/assistant/assistant_graph.py) ────────────
    fields:          list    # which fields to capture e.g. ['email','telegram']
    target:          int     # how many records to collect
    records:         list    # accumulated records across capture slices
    slices_done:     int     # number of capture interrupts so far
    capture_tool_id: str     # persisted tool_call_id for the active capture

    # idea_agent (application/ideas/ideation_graph.py) uses only messages —
    # no extra fields needed


# ── supervisor LLM ────────────────────────────────────────────────────────────

class RouteDecision(BaseModel):
    next: Literal["assist_agent", "idea_agent", "reply_agent", "FINISH"]


_SUPERVISOR_PROMPT = (
    "You are the StreamEye message router. Read the conversation and decide "
    "which agent should handle the LATEST human message.\n\n"

    "Agents:\n"
    "  assist_agent — creator commands: capture viewers, send emails or Telegram\n"
    "                 messages, connect accounts, fill knowledge gaps, manage\n"
    "                 templates, list connected senders\n"
    "  idea_agent   — content strategy: collecting creator profile information,\n"
    "                 analysing audience, generating content ideas for videos,\n"
    "                 photos, live activities, or digital services\n"
    "  reply_agent  — ONLY for messages FROM viewers (never for the creator);\n"
    "                 drafts a reply and sends it to their Telegram chat\n\n"

    "Rules:\n"
    "  1. If chat_id is present in state this is a viewer message — always\n"
    "     return reply_agent, no further reasoning needed.\n"
    "  2. If the last AI message looks like a complete response with no pending\n"
    "     action, return FINISH.\n"
    "  3. Keywords for idea_agent: idea, content, generate, strategy, niche,\n"
    "     audience, what should I make, topic, content plan.\n"
    "  4. Everything else goes to assist_agent.\n\n"

    "Return only the routing decision — no explanation."
)

_router_llm = (
    ChatOpenAI(model=settings.openai_model,
               api_key=settings.openai_api_key,
               temperature=0)
    .with_structured_output(RouteDecision)
)


# ── supervisor node ────────────────────────────────────────────────────────────

def supervisor_node(state: MainState) -> dict:
    """
    Decide which sub-agent handles the next turn.

    Fast-path: if chat_id is set the message came from a viewer — route
    directly to reply_agent without spending an LLM call.

    Otherwise: ask the router LLM to classify the creator's intent.
    """
    # Viewer message — skip LLM entirely
    if state.get("chat_id"):
        return {"next_agent": "reply_agent"}

    messages = [SystemMessage(_SUPERVISOR_PROMPT)] + list(state["messages"])
    decision = _router_llm.invoke(messages)
    return {"next_agent": decision.next}


def route_from_supervisor(state: MainState) -> str:
    """Conditional edge: maps next_agent to a node name or END."""
    nxt = state.get("next_agent", "FINISH")
    return nxt if nxt != "FINISH" else END


# ── build ─────────────────────────────────────────────────────────────────────

def build_main_graph(checkpointer):
    """
    Compile the supervisor graph.

    Sub-graphs are compiled WITHOUT a checkpointer — they run inside the
    parent's execution context and the parent's checkpointer manages all
    state and interrupt persistence.
    """
    assist_graph = build_assistant_graph(checkpointer=None)
    idea_graph   = build_idea_graph(checkpointer=None)
    reply_graph  = build_reply_graph(checkpointer=None)

    builder = StateGraph(MainState)

    # ── nodes ────────────────────────────────────────────────────────────────
    builder.add_node("supervisor",   supervisor_node)
    builder.add_node("assist_agent", assist_graph)
    builder.add_node("idea_agent",   idea_graph)
    builder.add_node("reply_agent",  reply_graph)

    # ── edges ─────────────────────────────────────────────────────────────────
    # Every request starts at the supervisor
    builder.add_edge(START, "supervisor")

    # Supervisor routes to one of the three agents or END
    builder.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        ["assist_agent", "idea_agent", "reply_agent", END],
    )

    # After each sub-agent completes its turn, return to supervisor.
    # The supervisor then decides whether to route again or finish.
    builder.add_edge("assist_agent", "supervisor")
    builder.add_edge("idea_agent",   "supervisor")
    builder.add_edge("reply_agent",  "supervisor")

    # Only the parent gets the checkpointer
    return builder.compile(checkpointer=checkpointer)
