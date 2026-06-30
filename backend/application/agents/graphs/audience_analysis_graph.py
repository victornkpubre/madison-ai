from typing import Optional, TypedDict

from langgraph.constants import START, END
from langgraph.graph import StateGraph

from composition import idea_service

# ── subgraph 2: parallel extraction + self-correcting synthesis ─────────
AUDIENCE_SCORE_THRESHOLD = 0.7


class AudienceState(TypedDict):
    signals: list[dict]
    topics: list[dict]
    sentiment: dict
    gaps: list[str]
    summary: str
    critique: str
    score: float
    retry_count: int
    max_retries: int
    final_summary: str
    session_id: Optional[str]


async def fetch_signals_node(state: AudienceState) -> dict:
    signals = await idea_service.fetch_audience_signals(session_id=state.get("session_id"))
    return {"signals": signals}


async def cluster_topics_node(state: AudienceState) -> dict:
    topics = await idea_service.cluster_topics(state["signals"])
    return {"topics": topics}


async def score_sentiment_node(state: AudienceState) -> dict:
    sentiment = await idea_service.score_sentiment(state["signals"])
    return {"sentiment": sentiment}


async def synthesize_node(state: AudienceState) -> dict:
    result = await idea_service.synthesize_audience_summary(
        topics=state["topics"],
        sentiment=state["sentiment"],
        signals=state["signals"],
        critique=state.get("critique", ""),
    )
    return {"gaps": result["gaps"], "summary": result["summary"]}


async def evaluate_audience_node(state: AudienceState) -> dict:
    result = await idea_service.score_audience_summary(
        summary=state["summary"],
        gaps=state["gaps"],
        signals=state["signals"],
    )
    return {
        "score": result["score"],
        "critique": result["critique"],
        "retry_count": state["retry_count"] + 1,
    }


def route_after_audience_evaluate(state: AudienceState) -> str:
    if state["score"] >= AUDIENCE_SCORE_THRESHOLD:
        return "accept"
    if state["retry_count"] >= state["max_retries"]:
        return "accept"
    return "retry"


async def finalize_audience_node(state: AudienceState) -> dict:
    return {"final_summary": state["summary"]}


def build_audience_analysis_graph():
    builder = StateGraph(AudienceState)
    builder.add_node("fetch_signals", fetch_signals_node)
    builder.add_node("cluster_topics", cluster_topics_node)
    builder.add_node("score_sentiment", score_sentiment_node)
    builder.add_node("synthesize", synthesize_node)
    builder.add_node("evaluate", evaluate_audience_node)
    builder.add_node("finalize", finalize_audience_node)

    builder.add_edge(START, "fetch_signals")

    # fan-out: both extraction steps run off the same signals, independently
    builder.add_edge("fetch_signals", "cluster_topics")
    builder.add_edge("fetch_signals", "score_sentiment")

    # fan-in: synthesize waits for both extraction branches to complete
    builder.add_edge("cluster_topics", "synthesize")
    builder.add_edge("score_sentiment", "synthesize")

    builder.add_edge("synthesize", "evaluate")
    builder.add_conditional_edges(
        "evaluate", route_after_audience_evaluate, {"retry": "synthesize", "accept": "finalize"}
    )
    builder.add_edge("finalize", END)

    return builder.compile()


audience_analysis_graph = build_audience_analysis_graph()


def _format_audience_summary(summary: str, gaps: list[str], signal_count: int = 0) -> str:
    gaps_text = "\n".join(f"  - {g}" for g in gaps) or "  (none identified)"
    count_line = f"Based on {signal_count} audience message(s).\n\n" if signal_count else ""
    return f"{count_line}{summary}\n\nContent/knowledge gaps:\n{gaps_text}"


async def analyze_audience(max_retries: int = 2, session_id: str | None = None) -> str:
    """Entry point called by idea_tools.py. Builds a fresh AudienceState, runs
    audience_analysis_graph to completion, and persists the result so a later
    generate_ideas() call can read it back. `max_retries` caps how many
    synthesize/evaluate cycles run before returning the best effort.
    session_id: scope the analysis to one capture session (e.g. one TikTok
    LIVE stream's captured chat) instead of the general signal pool."""
    initial_state = {
        "signals": [],
        "topics": [],
        "sentiment": {},
        "gaps": [],
        "summary": "",
        "critique": "",
        "score": 0.0,
        "retry_count": 0,
        "max_retries": max_retries,
        "final_summary": "",
        "session_id": session_id,
    }
    result = await audience_analysis_graph.ainvoke(initial_state)
    idea_service.save_audience_analysis(summary=result["final_summary"], gaps=result["gaps"])
    return _format_audience_summary(result["final_summary"], result["gaps"],
                                    signal_count=len(result.get("signals", [])))
