"""
reply_graph.py
══════════════
The StreamEye Viewer-Reply agent — for content creators, not businesses.

The knowledge base is built from three sources the creator already has:
  1. creator_knowledge entries — anything the creator wants the agent to know:
       their story, niche opinions, common answers, links, resources.
       Added conversationally via POST /knowledge or through chat.
  2. content_history — the creator's past videos, posts, and live sessions
       (already collected by the idea generator). The agent can say
       "I covered this in my video on X — here's what I said..."
  3. creator_idea_profile — niche, style, audience, monetization. Used to
       build the system prompt so the agent speaks in the creator's voice.

The HITL approval flow is unchanged:
  agent (draft) -> confirm (creator approves/edits/rejects) -> deliver

Viewer messages that arrive at the Telegram webhook can be routed here
by POSTing to /chat with the viewer's chat_id and message text.

Lives under infrastructure/ai/ alongside supervisor_graph.py — it's
graph-orchestration plumbing wired together by the supervisor, not a
feature with its own domain/application slice.
"""
from __future__ import annotations

from typing import Optional

from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from backend.config import settings
from backend.composition import creator_service, idea_service
from backend.application.agents.graphs.tools.telegram_tools import send_telegram_message


# ── dynamic system prompt ─────────────────────────────────────────────────────

def build_system_prompt() -> str:
    """
    Build the agent's system prompt from the creator's stored profile.
    Falls back to sensible defaults if the profile is incomplete.

    NOTE: the original reply-agent prompt was built from the basic
    CreatorProfile (name/bio/cta) loaded via idea_tools' in-memory/DB
    profile loader — that loader actually returned the *idea* profile
    (niche/style/audience/monetization), which is what this prompt has
    always described. We preserve that behaviour exactly, just sourced
    from idea_service instead of a module-level helper.
    """
    p = idea_service.load_profile()

    niche    = p.niche or "content creator"
    style    = p.content_style or "warm, genuine, and conversational"
    audience = p.target_audience or "their community"
    monetize = p.monetization or "not specified"
    sub      = p.sub_niche

    niche_desc = f"{niche} creator" + (f" focusing on {sub}" if sub else "")

    return (
        f"You are the AI community assistant for a {niche_desc}.\n"
        f"You respond to viewer messages on behalf of the creator.\n\n"

        f"Creator context:\n"
        f"  Communication style : {style}\n"
        f"  Audience            : {audience}\n"
        f"  Monetization        : {monetize}\n\n"

        "Your job is to give viewers accurate, helpful replies that sound like\n"
        "the creator themselves — not a brand or a bot.\n\n"

        "Rules:\n"
        "- Always call retrieve_knowledge() first to find relevant information.\n"
        "- If the creator has content about the topic, mention it by name.\n"
        "- If you do not know something, say so honestly — never invent facts.\n"
        "- Match the creator's communication style exactly.\n"
        "- Content creators are human. Replies should feel personal, not polished.\n"
        "- Keep replies short — this is a chat, not a blog post.\n"
        "- Never mention prices, links, or products that are not in the knowledge base.\n"
        "- If the viewer is asking to buy something and monetization is not set up, "
        "  suggest they follow the creator for updates."
    )


# ── retrieval tool ────────────────────────────────────────────────────────────

@tool
def retrieve_knowledge(query: str) -> str:
    """
    Search the creator's knowledge base and content library for information
    relevant to a viewer's question.

    Searches three sources:
      1. Creator knowledge entries  — FAQs, opinions, resources, personal facts
      2. Content library            — past videos, posts, live sessions
      3. Common audience questions  — patterns from previous viewer messages

    Args:
        query: the viewer's question or topic to look up.
    """
    query_lower = query.lower()
    words       = set(query_lower.split())

    # ── score knowledge entries ────────────────────────────────────────────
    entries = creator_service.list_knowledge()
    scored  = []
    for e in entries:
        text  = (e.topic + " " + e.content).lower()
        score = sum(1 for w in words if w in text)
        if score > 0:
            scored.append((score, f"[Knowledge] {e.content}"))

    # ── score content references ───────────────────────────────────────────
    refs = idea_service.load_content_references()
    for r in refs:
        text  = ((r.title or "") + " " + (r.topic or "")).lower()
        score = sum(1 for w in words if w in text)
        if score > 0:
            label = (r.content_type or "content").capitalize()
            scored.append((score, f"[{label}] '{r.title}' "
                                   f"— topic: {r.topic or 'general'}"))

    # ── sort by relevance and return top results ───────────────────────────
    scored.sort(key=lambda x: -x[0])
    results = [text for _, text in scored[:6]]

    if not results:
        # Nothing matched — return a few recent entries as generic context
        fallback = [f"[Knowledge] {e.content}" for e in entries[:3]]
        fallback += [f"[{(r.content_type or 'Content').capitalize()}] '{r.title}'"
                     for r in refs[:3]]
        results = fallback or ["No knowledge entries found. "
                               "Add entries via POST /knowledge."]

    return "\n".join(results)


@tool
def add_knowledge(topic: str, content: str) -> str:
    """
    Add a new entry to the creator's knowledge base.
    Use this during setup or when the creator shares information that should
    be available when replying to viewers.

    Args:
        topic:   short label for this piece of knowledge, e.g. 'editing setup'
        content: the full information to store, e.g. 'I edit on a MacBook Pro
                 using CapCut. I record on an iPhone 15 Pro.'
    """
    creator_service.save_knowledge(topic, content, source="agent")
    return f"✓ Saved: '{topic}' — '{content[:60]}{'...' if len(content) > 60 else ''}'"


# ── model ─────────────────────────────────────────────────────────────────────

model = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key,
                   temperature=0.4)
model_with_tools = model.bind_tools([retrieve_knowledge, add_knowledge],
                                    parallel_tool_calls=False)


# ── state ─────────────────────────────────────────────────────────────────────

class State(MessagesState):
    chat_id:     str            # viewer's Telegram chat_id
    decision:    Optional[str]  # approve | edit | reject
    final_reply: Optional[str]  # text actually delivered


# ── nodes ─────────────────────────────────────────────────────────────────────

def agent_node(state: State) -> dict:
    """LLM reasoning step. Retrieves knowledge then drafts a reply."""
    messages = [SystemMessage(build_system_prompt())] + state["messages"]
    response = model_with_tools.invoke(messages)
    return {"messages": [response]}


def confirm_node(state: State) -> dict:
    """
    Pause for creator approval.
    The creator can approve the draft, edit it with different text,
    or reject it entirely.
    """
    draft    = state["messages"][-1].content
    decision = interrupt({
        "chat_id":        state["chat_id"],
        "proposed_reply": draft,
    })
    return {
        "decision":    decision["action"],
        "final_reply": decision.get("text") or draft,
    }


async def deliver_node(state: State) -> dict:
    """Send the approved reply to the viewer's Telegram chat."""
    result = await send_telegram_message.ainvoke({
        "chat_id": state["chat_id"],
        "text":    state["final_reply"],
    })
    return {"messages": [SystemMessage(f"[delivered] {result}")]}


# ── routing ───────────────────────────────────────────────────────────────────

def route_after_agent(state: State) -> str:
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else "confirm"


def route_after_confirm(state: State) -> str:
    return "deliver" if state["decision"] in ("approve", "edit") else END


# ── compile ───────────────────────────────────────────────────────────────────

def build_reply_graph(checkpointer):
    builder = StateGraph(State)
    builder.add_node("agent",   agent_node)
    builder.add_node("tools",   ToolNode([retrieve_knowledge, add_knowledge]))
    builder.add_node("confirm", confirm_node)
    builder.add_node("deliver", deliver_node)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", route_after_agent, ["tools", "confirm"])
    builder.add_edge("tools", "agent")
    builder.add_conditional_edges("confirm", route_after_confirm, ["deliver", END])
    builder.add_edge("deliver", END)

    return builder.compile(checkpointer=checkpointer)
