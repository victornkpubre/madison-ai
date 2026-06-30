from typing import TypedDict

from langgraph.constants import START, END
from langgraph.graph import StateGraph

from composition import idea_service

# ── subgraph 1: self-correcting idea generation ─────────────────────────
IDEA_SCORE_THRESHOLD = 0.7

class IdeaGenState(TypedDict):
    profile: dict
    content_history: list[dict]
    audience_summary: str
    draft_ideas: str
    critique: str
    score: float
    retry_count: int
    max_retries: int
    final_ideas: str


async def generate_node(state: IdeaGenState) -> dict:
    draft = await idea_service.draft_ideas(
        profile=state["profile"],
        content_history=state["content_history"],
        audience_summary=state["audience_summary"],
        critique=state.get("critique", ""),
    )
    return {"draft_ideas": draft}


async def evaluate_node(state: IdeaGenState) -> dict:
    result = await idea_service.score_ideas(
        ideas=state["draft_ideas"],
        profile=state["profile"],
    )
    return {
        "score": result["score"],
        "critique": result["critique"],
        "retry_count": state["retry_count"] + 1,
    }


def route_after_evaluate(state: IdeaGenState) -> str:
    if state["score"] >= IDEA_SCORE_THRESHOLD:
        return "accept"
    if state["retry_count"] >= state["max_retries"]:
        return "accept"  # cap hit — return best effort rather than loop forever
    return "retry"


async def finalize_node(state: IdeaGenState) -> dict:
    return {"final_ideas": state["draft_ideas"]}


def build_idea_generation_graph():
    builder = StateGraph(IdeaGenState)
    builder.add_node("generate", generate_node)
    builder.add_node("evaluate", evaluate_node)
    builder.add_node("finalize", finalize_node)

    builder.add_edge(START, "generate")
    builder.add_edge("generate", "evaluate")
    builder.add_conditional_edges(
        "evaluate", route_after_evaluate, {"retry": "generate", "accept": "finalize"}
    )
    builder.add_edge("finalize", END)

    return builder.compile()  # no checkpointer — runs fully inside one tool call


idea_generation_graph = build_idea_generation_graph()


async def generate_ideas(max_retries: int = 2) -> str:
    """Entry point called by idea_tools.py. Builds the subgraph's initial state
    from the stored profile, content history, and the most recent audience
    analysis, then runs idea_generation_graph to completion. `max_retries` caps
    how many generate/evaluate cycles run before returning the best effort."""
    profile = idea_service.load_profile().strategy_dict()
    content_history = [
        {"title": item.title, "content_type": item.content_type, "topic": item.topic}
        for item in idea_service.load_content_references(limit=30)
    ]
    latest_analysis = idea_service.load_latest_audience_analysis()
    audience_summary = latest_analysis["summary"] if latest_analysis else ""

    initial_state = {
        "profile": profile,
        "content_history": content_history,
        "audience_summary": audience_summary,
        "draft_ideas": "",
        "critique": "",
        "score": 0.0,
        "retry_count": 0,
        "max_retries": max_retries,
        "final_ideas": "",
    }
    result = await idea_generation_graph.ainvoke(initial_state)
    return result["final_ideas"]

