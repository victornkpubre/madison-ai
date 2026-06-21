# Idea Generator
# A conversational onboarding + content-strategy advisor for a creator, run as a tool-calling loop (gpt-4o-mini + IDEA_TOOLS, one tool call per turn).
#
# Collect profile — save_profile_field, get_profile_status — niche, sub_niche, target_audience, platforms, content_style, monetization, gathered conversationally over multiple turns.
# Collect content history — add_content_item, get_content_history_summary — 5-10 recent pieces of content (title, topic, type).
# Analyze the audience — analyze_audience — runs once, processes captured viewer messages into a summary + content gaps.
# Generate ideas — generate_ideas — produces the final content suggestions, grounded in the profile, history, and audience analysis from the steps above.
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from backend.application.agents.graphs.prompts.idea_prompt import SYSTEM_PROMPT
from backend.application.agents.graphs.tools.idea_tools import IDEA_TOOLS
from backend.application.agents.resilience import invoke_llm
from backend.config import settings

# ── top-level conversational graph ───────────────────────────────────────
_model = ChatOpenAI(model=settings.openai_model, temperature=0, api_key=settings.openai_api_key)
model_with_tools = _model.bind_tools(IDEA_TOOLS, parallel_tool_calls=False)


async def agent_node(state: MessagesState) -> dict:
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = await invoke_llm(model_with_tools, messages)
    return {"messages": [response]}


def route_after_agent(state: MessagesState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END


def build_idea_graph(checkpointer=None):
    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(IDEA_TOOLS))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")

    return builder.compile(checkpointer=checkpointer)
