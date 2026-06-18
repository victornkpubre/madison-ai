"""
idea_graph.py
=============
The StreamEye Idea Generator agent.

Conversational flow:
  1. Profile collection — the LLM asks questions and saves each field with
     save_profile_field(). It calls get_profile_status() to track progress.

  2. Content history — the LLM asks about recent content and calls
     add_content_item() for each piece. Uses get_content_history_summary()
     to confirm what has been captured.

  3. Audience analysis — calls analyze_audience() to process stored signals
     (messages and chat content already captured via webhooks and capture runs).

  4. Idea generation — calls generate_ideas() which synthesises everything
     and returns a formatted idea set.

The agent is conversational throughout. It extracts structured data from
natural language ("I make fitness content for women" → niche=fitness,
target_audience=women) rather than asking for structured input.
"""

from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

from config import settings
from idea_tools import IDEA_TOOLS

# ── system prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are the StreamEye Idea Generator — a strategic content advisor who helps "
    "creators discover their best content opportunities through intelligent analysis.\n\n"

    "You collect information conversationally in four phases. Move through them in order.\n\n"

    "── Phase 1: Creator Profile ────────────────────────────────────────────────\n"
    "Collect these six fields by asking natural questions. Extract structured values\n"
    "from the creator's answers and save each with save_profile_field().\n\n"
    "Fields to collect:\n"
    "  niche           — main content area (fitness, finance, gaming, etc.)\n"
    "  sub_niche       — specific focus within the niche\n"
    "  target_audience — who the content is for (age, interests, pain points)\n"
    "  platforms       — where they post (TikTok, YouTube, Instagram, etc.)\n"
    "  content_style   — how they communicate (educational, entertaining, etc.)\n"
    "  monetization    — how they earn (sponsorships, courses, digital products, etc.)\n\n"
    "Extraction example: 'I make fitness content for women over 30' gives you:\n"
    "  niche='fitness', target_audience='women over 30'\n"
    "Save as you go. Call get_profile_status() to check what is still missing.\n"
    "Ask about 2-3 fields at a time to keep it conversational, not like a form.\n\n"

    "── Phase 2: Content History ─────────────────────────────────────────────────\n"
    "Ask the creator to describe their 5-10 most recent pieces of content.\n"
    "For each, call add_content_item() with title, topic, and content_type.\n"
    "content_type must be one of: video, photo, live, digital.\n"
    "If they say they cannot remember, 3-5 items is enough. This prevents idea "
    "repetition and reveals coverage gaps.\n\n"

    "── Phase 3: Audience Intelligence ──────────────────────────────────────────\n"
    "Call analyze_audience() once. It processes all viewer messages and chat content\n"
    "already captured via Telegram, email, and live stream captures. It extracts\n"
    "topics, detects questions (curiosity) and requests, and computes sentiment trends.\n"
    "If there are no signals yet, mention this and proceed — ideas can still be\n"
    "generated from the profile and history alone.\n\n"

    "── Phase 4: Idea Generation ─────────────────────────────────────────────────\n"
    "Call generate_ideas(). Present the results enthusiastically and clearly.\n"
    "After presenting, offer to:\n"
    "  a) Dig deeper into any specific idea\n"
    "  b) Generate more ideas in a specific category\n"
    "  c) Explain why a specific idea was recommended\n\n"

    "General rules:\n"
    "- Be warm, curious, and engaging — this is a creative conversation.\n"
    "- Extract multiple fields from a single answer when possible.\n"
    "- Do not ask for fields that can be clearly inferred.\n"
    "- Never use jargon without explanation.\n"
    "- When presenting ideas, lead with the most actionable ones first."
)

# ── state ─────────────────────────────────────────────────────────────────────

class IdeaState(MessagesState):
    pass   # messages list from MessagesState is all we need —
           # all structured data is persisted to the DB / in-memory stores
           # by the tools directly, not stored in graph state.

# ── nodes ─────────────────────────────────────────────────────────────────────

model = ChatOpenAI(model=settings.openai_model,
                   api_key=settings.openai_api_key,
                   temperature=0.4)

model_with_tools = model.bind_tools(IDEA_TOOLS, parallel_tool_calls=False)


def agent_node(state: IdeaState) -> dict:
    messages  = [SystemMessage(SYSTEM_PROMPT)] + state["messages"]
    response  = model_with_tools.invoke(messages)
    return {"messages": [response]}


def route_after_agent(state: IdeaState) -> str:
    calls = getattr(state["messages"][-1], "tool_calls", None) or []
    return "tools" if calls else END


# ── graph ─────────────────────────────────────────────────────────────────────

def build_idea_graph(checkpointer):
    b = StateGraph(IdeaState)
    b.add_node("agent", agent_node)
    b.add_node("tools", ToolNode(IDEA_TOOLS))
    b.add_edge(START, "agent")
    b.add_conditional_edges("agent", route_after_agent, ["tools", END])
    b.add_edge("tools", "agent")
    return b.compile(checkpointer=checkpointer)
