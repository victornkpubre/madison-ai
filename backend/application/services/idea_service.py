"""
idea_service.py
═════════════════════
Application service for the idea-generator domain: the content-strategy
profile, content history, audience signals, topic analytics, and the
LLM-driven idea generation / audience analysis logic consumed by the
idea_generation_graph and audience_analysis_graph LangGraph nodes.

Depends on IIdeaRepository, not the concrete IdeaRepository, and never
imports from infrastructure/ — the singleton is wired in composition.py.
Same pattern as CreatorService(repo: ICreatorRepository).

Method names (load_profile, ingest_signal, load_topic_analytics,
load_content_references) match the established call sites in
reply_graph.py and interface/api/ideas.py rather than introducing a
parallel naming convention.
"""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from backend.application.agents.resilience import invoke_llm
from backend.application.services.idea_schemas import (
    AudienceScore, AudienceSynthesis, IdeaScore, SentimentResult, TopicClusters,
)
from backend.config import settings
from backend.domain.entities.idea_entity import ContentHistoryItem, CreatorIdeaProfile
from backend.domain.repository.idea_repository_interface import IIdeaRepository


class IdeaService:

    def __init__(self, repo: IIdeaRepository, llm: ChatOpenAI | None = None):
        self._repo = repo
        self._llm = llm or ChatOpenAI(model=settings.openai_model, temperature=0,
                                      api_key=settings.openai_api_key)

    # ── profile ────────────────────────────────────────────────────────────
    def load_profile(self) -> CreatorIdeaProfile:
        return self._repo.load_profile()

    async def save_profile_field(self, field: str, value: str) -> str:
        """Persist one creator content-strategy field (niche, sub_niche, target_audience,
        platforms, content_style, monetization)."""
        self._repo.upsert_profile_field(field, value)
        return f"Saved {field} = {value!r}."

    async def get_profile_status(self) -> str:
        """Return which content-strategy fields are filled and which are still missing."""
        profile = self._repo.load_profile()
        missing = profile.missing_fields()
        if not missing:
            return "Profile complete: " + ", ".join(f"{k}={v}" for k, v in profile.filled_fields().items())
        return (f"Missing: {', '.join(missing)}. "
                f"Have: {', '.join(f'{k}={v}' for k, v in profile.filled_fields().items())}")

    # ── content history ────────────────────────────────────────────────────
    async def add_content_item(self, title: str, topic: str, content_type: str) -> str:
        """Record one piece of the creator's recent content history."""
        self._repo.insert_content_item(title=title, topic=topic, content_type=content_type)
        return f"Added '{title}' ({content_type}) to content history."

    async def get_content_history_summary(self) -> str:
        """Return a short summary of recorded content history."""
        history = self._repo.load_content_references()
        if not history:
            return "No content history recorded yet."
        return f"{len(history)} items recorded: " + ", ".join(item.title for item in history)

    def load_content_references(self, limit: int = 30) -> list[ContentHistoryItem]:
        """Pass-through used directly by reply_graph.py's retrieve_knowledge tool
        to surface past content alongside knowledge-base entries."""
        return self._repo.load_content_references(limit)

    def load_content_topics(self, limit: int = 50) -> list[str]:
        return self._repo.load_content_topics(limit)

    # ── audience signals ───────────────────────────────────────────────────
    def ingest_signal(self, content: str, source: str = "telegram", session_id: str = "") -> None:
        self._repo.insert_signal(content, source, session_id)

    def mark_signal_analysed(self, signal: dict, signal_type: str, topic: str) -> None:
        self._repo.update_signal_topic(signal, signal_type, topic)

    def load_signals_by_topic(self, topic: str, signal_types: list[str] | None = None, limit: int = 5) -> list[str]:
        return self._repo.load_signals_by_topic(topic, signal_types, limit)

    # ── topic analytics ────────────────────────────────────────────────────
    def record_topic_analytics(self, topic: str, frequency: int, velocity: float,
                               curiosity_score: float, question_count: int,
                               request_count: int, sentiment: float) -> None:
        self._repo.upsert_topic_analytics(
            topic, frequency, velocity, curiosity_score, question_count, request_count, sentiment,
        )

    def load_topic_analytics(self, limit: int = 20) -> list[dict]:
        return self._repo.load_topic_analytics(limit)

    # ── audience analysis (synthesized summary, distinct from raw signals) ──
    def save_audience_analysis(self, summary: str, gaps: list[str]) -> None:
        """Persist the synthesized audience summary so a later
        generate_ideas() run can read it back without redoing the analysis."""
        self._repo.save_audience_analysis(summary, gaps)

    def load_latest_audience_analysis(self) -> dict | None:
        return self._repo.load_latest_audience_analysis()

    # ── idea_generation_graph nodes ────────────────────────────────────────
    async def draft_ideas(self, profile: dict, content_history: list[dict],
                          audience_summary: str, critique: str = "") -> str:
        """One generation pass. Non-empty `critique` means this is a retry following a
        low evaluator score on the previous draft."""
        history_text = "\n".join(
            f"- {item.get('title', '')} ({item.get('content_type', '')}): {item.get('topic', '')}"
            for item in content_history
        ) or "No content history recorded."

        retry_block = (
            f"\nYour previous draft scored too low. Evaluator feedback:\n{critique}\n"
            f"Address this directly in your revised ideas.\n"
            if critique else ""
        )

        prompt = (
            f"Creator profile:\n"
            f"  niche: {profile.get('niche', '')}\n"
            f"  sub_niche: {profile.get('sub_niche', '')}\n"
            f"  target_audience: {profile.get('target_audience', '')}\n"
            f"  platforms: {profile.get('platforms', '')}\n"
            f"  content_style: {profile.get('content_style', '')}\n"
            f"  monetization: {profile.get('monetization', '')}\n\n"
            f"Recent content history:\n{history_text}\n\n"
            f"Audience intelligence summary:\n{audience_summary or 'Not yet analysed.'}\n"
            f"{retry_block}\n"
            f"Generate 5-8 specific content ideas spanning videos, pictures, live stream "
            f"activities, and digital services. Every idea must tie directly to something "
            f"in the profile, content history, or audience summary above — no generic "
            f"suggestions. Format as a numbered list with a one-line rationale per idea."
        )
        response = await invoke_llm(self._llm, prompt)
        return response.content

    async def score_ideas(self, ideas: str, profile: dict) -> dict:
        """Evaluator pass for idea_generation_graph. Scores draft ideas against the
        creator's stated niche/style/audience."""
        scorer = self._llm.with_structured_output(IdeaScore)
        prompt = (
            f"Creator profile:\n"
            f"  niche: {profile.get('niche', '')}\n"
            f"  target_audience: {profile.get('target_audience', '')}\n"
            f"  content_style: {profile.get('content_style', '')}\n\n"
            f"Draft ideas:\n{ideas}\n\n"
            f"Score how well these ideas fit the creator's niche, style, and audience. "
            f"Call out any idea that feels generic or unrelated to the profile."
        )
        result = await invoke_llm(scorer, prompt)
        return {"score": result.score, "critique": result.critique}

    # ── audience_analysis_graph nodes ──────────────────────────────────────
    async def fetch_audience_signals(self) -> list[dict]:
        """Pulls captured viewer messages and chat content from storage."""
        return self._repo.load_unanalysed_signals(limit=500)

    async def cluster_topics(self, signals: list[dict]) -> list[dict]:
        """Extraction step — groups raw signal text into topic clusters."""
        if not signals:
            return []
        clusterer = self._llm.with_structured_output(TopicClusters)
        messages_text = "\n".join(f"- {s.get('content', '')}" for s in signals[:200])
        prompt = (
            f"Viewer messages:\n{messages_text}\n\n"
            f"Group these into topic clusters. For each, give a short topic label, a "
            f"count, and 2-3 representative sample messages."
        )
        result = await invoke_llm(clusterer, prompt)
        return [c.model_dump() for c in result.clusters]

    async def score_sentiment(self, signals: list[dict]) -> dict:
        """Extraction step — overall sentiment read on the audience signals."""
        if not signals:
            return {"overall": "neutral", "summary": "No signals captured yet."}
        scorer = self._llm.with_structured_output(SentimentResult)
        messages_text = "\n".join(f"- {s.get('content', '')}" for s in signals[:200])
        prompt = f"Viewer messages:\n{messages_text}\n\nAssess the overall sentiment toward the creator."
        result = await invoke_llm(scorer, prompt)
        return result.model_dump()

    async def synthesize_audience_summary(
        self, topics: list[dict], sentiment: dict, signals: list[dict], critique: str = "",
    ) -> dict:
        """Fan-in step — combines the parallel topic/sentiment extractions into one
        narrative summary plus a list of content/knowledge gaps. Non-empty `critique`
        means this is a retry following a low grounding score."""
        synthesizer = self._llm.with_structured_output(AudienceSynthesis)
        topics_text = "\n".join(f"- {t['topic']} ({t['count']} mentions)" for t in topics) or "No clear topics."
        retry_block = (
            f"\nYour previous synthesis was flagged for not staying grounded in the "
            f"actual signals. Evaluator feedback:\n{critique}\n" if critique else ""
        )
        prompt = (
            f"Topic clusters:\n{topics_text}\n\n"
            f"Overall sentiment: {sentiment.get('overall', 'unknown')} — {sentiment.get('summary', '')}\n"
            f"{retry_block}\n"
            f"Write a short narrative of what this audience cares about and how they "
            f"feel, then list specific content/knowledge gaps — topics raised repeatedly "
            f"with no clear answer in the creator's existing content. Every gap must "
            f"trace back to an actual topic cluster above, not be invented."
        )
        result = await invoke_llm(synthesizer, prompt)
        return {"summary": result.summary, "gaps": result.gaps}

    async def score_audience_summary(self, summary: str, gaps: list[str], signals: list[dict]) -> dict:
        """Evaluator pass for audience_analysis_graph. Checks the synthesis is genuinely
        grounded in the real signal text, not fabricated or overgeneralized."""
        scorer = self._llm.with_structured_output(AudienceScore)
        sample_text = "\n".join(f"- {s.get('content', '')}" for s in signals[:50])
        gaps_text = "\n".join(f"- {g}" for g in gaps)
        prompt = (
            f"Original viewer messages (sample):\n{sample_text}\n\n"
            f"Synthesized summary:\n{summary}\n\n"
            f"Identified gaps:\n{gaps_text}\n\n"
            f"Score whether the summary and gaps are genuinely grounded in the sample "
            f"messages above, with nothing fabricated or overgeneralized."
        )
        result = await invoke_llm(scorer, prompt)
        return {"score": result.score, "critique": result.critique}
