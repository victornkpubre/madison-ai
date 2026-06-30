"""
supervisor_graph.py
===================
The single entry point for all StreamEye agents.

Architecture
────────────
One compiled graph (main_graph) with a supervisor node that reads each
incoming message and routes to one of three sub-graphs:

  assist_agent — creator commands (capture, email, send, knowledge, templates,
                 leads, and the screen-based "find inspiration" flow)
  idea_agent   — content strategy (profile collection, idea generation,
                 text-based other-creator analysis)
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
  after sub-agent response → supervisor runs again → FINISH deterministically
    (the last message is no longer the fresh HumanMessage, so no LLM call
    is needed to decide the turn is over)
"""

from __future__ import annotations

from typing import Optional, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import BaseModel

from application.agents.resilience import invoke_llm

# Import sub-graph builders — sub-graphs are built without checkpointers
from application.agents.graphs.assistant_graph import build_assistant_graph
from infrastructure.ai.reply_graph import build_reply_graph
from application.agents.graphs.ideation_graph import build_idea_graph


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
    platform:        str     # platform for the active records capture

    # assist_agent — live stream-message capture (for stream reports)
    stream_target:          int
    stream_messages:        list
    stream_slices_done:     int
    stream_capture_tool_id: str
    stream_session_id:      str
    stream_platform:        str

    # assist_agent — continuous inspiration hunt (other creators' posts).
    # These tally across interrupt/resume cycles, so they MUST be declared
    # here or each resume would reset the hunt's running totals to empty.
    inspiration_target:    int
    inspiration_platform:  str
    inspiration_relevant:  list
    inspiration_checked:   int
    inspiration_tool_id:   str
    inspiration_seen:      list
    inspiration_slices:    int
    inspiration_misses:    int

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
    "                 templates, manage manually-entered leads (add/list/delete,\n"
    "                 draft and send a lead follow-up), and the full \"find\n"
    "                 inspiration from other creators\" flow — suggesting search\n"
    "                 keywords, screenshotting one post, or running a\n"
    "                 keyword-guided hunt across several posts\n"
    "  idea_agent   — content strategy: collecting creator profile information,\n"
    "                 analysing audience, generating content ideas for videos,\n"
    "                 photos, live activities, or digital services; also reading\n"
    "                 TEXT the creator pastes/describes about another creator's\n"
    "                 stream — but not anything involving their screen, that's\n"
    "                 assist_agent even if the topic is \"another creator\"\n"
    "  reply_agent  — ONLY for messages FROM viewers (never for the creator);\n"
    "                 drafts a reply and sends it to their Telegram chat\n\n"

    "Rules:\n"
    "  1. If chat_id is present in state this is a viewer message — always\n"
    "     return reply_agent, no further reasoning needed.\n"
    "  2. Keywords for idea_agent: idea, content, generate, strategy, niche,\n"
    "     audience, what should I make, topic, content plan — and ONLY when\n"
    "     paired with pasted/described text, not a screen action: another\n"
    "     creator's stream, competitor stream.\n"
    "  3. Keywords for assist_agent: lead, leads, add a lead, follow up, capture,\n"
    "     email, telegram, template, knowledge base, inspiration, trend,\n"
    "     trending, search keyword, another creator's post, screenshot.\n"
    "     'inspiration' alone, with no pasted text alongside it, ALWAYS means\n"
    "     assist_agent — that single word is the known ambiguous case where the\n"
    "     creator hasn't typed anything to analyse yet, so the keyword-guided\n"
    "     screen flow is what they mean, not analyze_other_stream.\n"
    "  4. Everything else goes to assist_agent.\n\n"

    "You are only ever asked to classify a fresh, unanswered message — never\n"
    "asked to judge whether a turn is 'done'. Always return one of\n"
    "assist_agent, idea_agent, or reply_agent.\n\n"

    "Return only the routing decision — no explanation."
)

_supervisor_bind = lambda m: m.bind(temperature=0).with_structured_output(RouteDecision)


# ── supervisor node ────────────────────────────────────────────────────────────

async def supervisor_node(state: MainState) -> dict:
    """
    Decide which sub-agent handles the next turn — or whether the turn is
    already finished.

    Stop condition (checked first, deterministic): a sub-agent has already
    produced output in response to the latest message once the last entry
    in state['messages'] is no longer that fresh HumanMessage. Finish
    immediately in that case. This used to be a judgement call left to the
    router LLM ("does this look like a complete response?"), which was
    unreliable enough that the same turn could route through assist_agent
    two or three times in a row — each pass re-running the welcome/
    onboarding flow — before the LLM happened to say FINISH. The same gap
    let reply_agent loop back on itself after delivering, since chat_id
    stays set in state for the rest of the thread.

    Otherwise: viewer message → reply_agent, no LLM call needed.
    Otherwise: ask the router LLM to classify the creator's intent, behind
    the shared fallback chain / circuit breaker / retry / cache stack — this
    used to be a bare ChatOpenAI call with no protection at all, even though
    every creator message passes through it.
    """
    messages = state["messages"]
    if messages and not isinstance(messages[-1], HumanMessage):
        return {"next_agent": "FINISH"}

    # Viewer message — skip LLM entirely
    if state.get("chat_id"):
        return {"next_agent": "reply_agent"}

    decision = await invoke_llm(
        [SystemMessage(_SUPERVISOR_PROMPT)] + list(messages),
        bind=_supervisor_bind, cache_tag="route_decision",
    )
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
