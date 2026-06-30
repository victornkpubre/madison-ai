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

from langchain_core.messages import HumanMessage

from application.agents.resilience import invoke_llm
from application.services.idea_schemas import (
    AudienceScore, AudienceSynthesis, IdeaScore, OtherStreamAnalysis,
    PostScreenshotExtraction, SentimentResult, TopicClusters,
)
from domain.entities.creator_entity import CreatorProfile
from domain.entities.idea_entity import ContentHistoryItem
from domain.repository.idea_repository_interface import IIdeaRepository


class IdeaService:

    def __init__(self, repo: IIdeaRepository):
        self._repo = repo

    # ── profile ────────────────────────────────────────────────────────────
    def load_profile(self) -> CreatorProfile:
        return self._repo.load_profile()

    async def save_profile_field(self, field: str, value: str) -> str:
        """Persist one creator content-strategy field (niche, sub_niche, target_audience,
        platforms, content_style, monetization)."""
        self._repo.upsert_profile_field(field, value)
        return f"Saved {field} = {value!r}."

    async def get_profile_status(self) -> str:
        """Return which content-strategy fields are filled and which are still missing."""
        profile = self._repo.load_profile()
        missing = profile.strategy_missing()
        filled  = profile.strategy_filled()
        if not missing:
            return "Profile complete: " + ", ".join(f"{k}={v}" for k, v in filled.items())
        return (f"Missing: {', '.join(missing)}. "
                f"Have: {', '.join(f'{k}={v}' for k, v in filled.items())}")

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
        response = await invoke_llm(prompt, bind=lambda m: m.bind(temperature=0),
                                    cache_tag="draft_ideas")
        return response.content

    async def score_ideas(self, ideas: str, profile: dict) -> dict:
        """Evaluator pass for idea_generation_graph. Scores draft ideas against the
        creator's stated niche/style/audience."""
        prompt = (
            f"Creator profile:\n"
            f"  niche: {profile.get('niche', '')}\n"
            f"  target_audience: {profile.get('target_audience', '')}\n"
            f"  content_style: {profile.get('content_style', '')}\n\n"
            f"Draft ideas:\n{ideas}\n\n"
            f"Score how well these ideas fit the creator's niche, style, and audience. "
            f"Call out any idea that feels generic or unrelated to the profile."
        )
        result = await invoke_llm(
            prompt, bind=lambda m: m.bind(temperature=0).with_structured_output(IdeaScore),
            cache_tag="idea_score")
        return {"score": result.score, "critique": result.critique}

    # ── audience_analysis_graph nodes ──────────────────────────────────────
    async def fetch_audience_signals(self, session_id: str | None = None) -> list[dict]:
        """Pulls captured viewer messages and chat content from storage.
        session_id: scope to one capture session (e.g. one TikTok LIVE
        stream's captured chat) instead of the general unanalysed pool."""
        if session_id:
            return self._repo.load_signals_by_session(session_id, limit=500)
        return self._repo.load_unanalysed_signals(limit=500)

    async def cluster_topics(self, signals: list[dict]) -> list[dict]:
        """Extraction step — groups raw signal text into topic clusters."""
        if not signals:
            return []
        clusterer_bind = lambda m: m.bind(temperature=0).with_structured_output(TopicClusters)
        messages_text = "\n".join(f"- {s.get('content', '')}" for s in signals[:200])
        prompt = (
            f"Viewer messages:\n{messages_text}\n\n"
            f"Group these into topic clusters. For each, give a short topic label, a "
            f"count, and 2-3 representative sample messages."
        )
        result = await invoke_llm(prompt, bind=clusterer_bind, cache_tag="cluster_topics")
        return [c.model_dump() for c in result.clusters]

    async def score_sentiment(self, signals: list[dict]) -> dict:
        """Extraction step — overall sentiment read on the audience signals."""
        if not signals:
            return {"overall": "neutral", "summary": "No signals captured yet."}
        scorer_bind = lambda m: m.bind(temperature=0).with_structured_output(SentimentResult)
        messages_text = "\n".join(f"- {s.get('content', '')}" for s in signals[:200])
        prompt = f"Viewer messages:\n{messages_text}\n\nAssess the overall sentiment toward the creator."
        result = await invoke_llm(prompt, bind=scorer_bind, cache_tag="score_sentiment")
        return result.model_dump()

    async def synthesize_audience_summary(
        self, topics: list[dict], sentiment: dict, signals: list[dict], critique: str = "",
    ) -> dict:
        """Fan-in step — combines the parallel topic/sentiment extractions into one
        narrative summary plus a list of content/knowledge gaps. Non-empty `critique`
        means this is a retry following a low grounding score."""
        synthesizer_bind = lambda m: m.bind(temperature=0).with_structured_output(AudienceSynthesis)
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
        result = await invoke_llm(prompt, bind=synthesizer_bind, cache_tag="synthesize_audience_summary")
        return {"summary": result.summary, "gaps": result.gaps}

    async def score_audience_summary(self, summary: str, gaps: list[str], signals: list[dict]) -> dict:
        """Evaluator pass for audience_analysis_graph. Checks the synthesis is genuinely
        grounded in the real signal text, not fabricated or overgeneralized."""
        scorer_bind = lambda m: m.bind(temperature=0).with_structured_output(AudienceScore)
        sample_text = "\n".join(f"- {s.get('content', '')}" for s in signals[:50])
        gaps_text = "\n".join(f"- {g}" for g in gaps)
        prompt = (
            f"Original viewer messages (sample):\n{sample_text}\n\n"
            f"Synthesized summary:\n{summary}\n\n"
            f"Identified gaps:\n{gaps_text}\n\n"
            f"Score whether the summary and gaps are genuinely grounded in the sample "
            f"messages above, with nothing fabricated or overgeneralized."
        )
        result = await invoke_llm(prompt, bind=scorer_bind, cache_tag="score_audience_summary")
        return {"score": result.score, "critique": result.critique}

    # ── other-creator stream analysis (idea generation from outside content) ──
    async def analyze_other_stream(self, stream_notes: str, platform: str = "") -> dict:
        """
        Analyse ANOTHER creator's live stream — not this creator's own — from
        whatever the creator captured or noticed: pasted chat text, or their
        own description of what's happening. Produces a topic summary, a
        relevance verdict against this creator's own niche/audience, and
        related content ideas.

        Deliberately takes free text rather than reusing the OCR capture
        loop in assistant_graph.py: that loop ingests every captured message
        into THIS creator's own audience_signals table via ingest_signal(),
        which would silently mix another stream's chat into this creator's
        own audience intelligence. Free text avoids that entirely — nothing
        here is persisted to the creator's profile, content history, or
        audience data; it's a one-off lens on someone else's content.

        Grounded in content history the same way generate_ideas() is: with
        history present, ideas are framed to build on/avoid repeating it;
        with none, ideas come from the profile alone and no content is
        invented or implied to exist.
        """
        profile = self.load_profile()
        history = self.load_content_references(limit=10)
        history_text = "\n".join(
            f"- {h.title} ({h.content_type or 'content'}): {h.topic or ''}"
            for h in history
        )
        history_block = (
            f"This creator's recent content (avoid repeating these — build on or "
            f"differentiate from them instead):\n{history_text}\n\n"
            if history_text else
            "This creator has no content history recorded yet — base ideas on "
            "their profile alone, and don't assume any past content exists.\n\n"
        )

        analyzer_bind = lambda m: m.bind(temperature=0.3).with_structured_output(OtherStreamAnalysis)
        prompt = (
            f"The creator is watching another creator's live stream"
            f"{f' on {platform}' if platform else ''} and wants your read on it.\n\n"
            f"What was captured or noticed from that other stream "
            f"(chat messages and/or the creator's own description):\n"
            f"{stream_notes}\n\n"
            f"This creator's own profile:\n"
            f"  niche: {profile.niche or 'not set'}\n"
            f"  sub_niche: {profile.sub_niche or ''}\n"
            f"  target_audience: {profile.target_audience or 'not set'}\n"
            f"  content_style: {profile.content_style or ''}\n\n"
            f"{history_block}"
            f"1. Identify what the OTHER stream is about — a short topic label.\n"
            f"2. Write a short report: what's happening, what's being discussed or shown.\n"
            f"3. Decide whether it's relevant to THIS creator's own niche and audience, "
            f"and say why in one sentence — relevance means real overlap, not just "
            f"'it's also a livestream'.\n"
            f"4. Give 2-4 related content ideas for THIS creator — inspired by the other "
            f"stream but clearly distinct from it, grounded in this creator's own "
            f"content history above if any exists."
        )
        result = await invoke_llm(prompt, bind=analyzer_bind, use_cache=False)
        return result.model_dump()

    # ── other-creator POST screenshot (vision counterpart to the above) ───────
    async def analyze_other_post_screenshot(self, image_b64: str, platform: str = "") -> dict:
        """
        Vision counterpart to analyze_other_stream(): the creator points
        their screen at another creator's post/video page (caption,
        hashtags, engagement counts, comments) instead of typing it out.

        This only adds ONE new step — extracting that screenshot into text
        via a vision LLM call. Once extracted, it's handed to
        analyze_other_stream() completely unchanged, so the relevance/idea
        reasoning, the content-history grounding, and the no-history
        fallback are all fully reused rather than duplicated.

        image_b64 is a base64-encoded PNG/JPEG screenshot — no API key
        needed from the creator's machine; the vision call runs here, on
        the backend, through the same resilient fallback chain (gpt-4o-mini
        → gpt-4o → claude-sonnet) every other LLM call in this app uses.
        """
        extractor_bind = lambda m: m.bind(temperature=0).with_structured_output(PostScreenshotExtraction)
        platform_label = platform or "TikTok"
        vision_prompt = (
            f"This is a screenshot of a {platform_label} post or video page, including "
            "its engagement panel and comments (if visible). Extract:\n"
            "- caption: the post's caption/description text\n"
            "- hashtags: any hashtags visible in the caption, without the # symbol\n"
            "- like_count, comment_count, save_count: the number shown next to each "
            "icon (read it as best you can, e.g. '3551' or '2.5K' as a number) — null "
            "for any not visible\n"
            "- comments: each visible comment with its author, text, and like count "
            "if shown\n"
            "Never invent anything not actually visible in the image — use null/empty "
            "for whatever you can't read."
        )
        messages = [HumanMessage(content=[
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            {"type": "text", "text": vision_prompt},
        ])]
        extraction = await invoke_llm(messages, bind=extractor_bind, use_cache=False)

        lines = [f"Caption: {extraction.caption or '(none visible)'}"]
        if extraction.hashtags:
            lines.append("Hashtags: " + " ".join(f"#{h.lstrip('#')}" for h in extraction.hashtags))
        counts = []
        if extraction.like_count is not None:
            counts.append(f"{extraction.like_count} likes")
        if extraction.comment_count is not None:
            counts.append(f"{extraction.comment_count} comments")
        if extraction.save_count is not None:
            counts.append(f"{extraction.save_count} saves")
        if counts:
            lines.append("Engagement: " + ", ".join(counts))
        if extraction.comments:
            lines.append("Top comments:")
            for c in extraction.comments[:10]:
                who = c.author or "someone"
                like_note = f" ({c.likes} likes)" if c.likes is not None else ""
                lines.append(f"  - {who}: {c.text}{like_note}")
        stream_notes = "\n".join(lines)

        analysis = await self.analyze_other_stream(stream_notes, platform)
        return {"extraction": extraction.model_dump(), "read_from_screenshot": stream_notes, **analysis}

    # ── keyword-guided inspiration hunt: step 1 (suggest search terms) ────────
    async def suggest_search_keywords(self, platform: str = "") -> str:
        """
        Suggest search terms for the keyword-guided "find inspiration from
        other creators" flow (see assistant_graph.py's start_inspiration_hunt).
        Pure text generation — grounded in profile and
        content history, doesn't read or write audience/lead data.
        """
        profile = self.load_profile()
        history = self.load_content_references(limit=10)
        history_text = "\n".join(f"- {h.title}: {h.topic or ''}" for h in history)
        history_block = (
            "Topics already covered — don't suggest terms that would mostly "
            f"surface more of the same:\n{history_text}\n\n" if history_text else
            "No content history recorded yet — keywords can be broader since "
            "nothing's been covered.\n\n"
        )
        platform_label = platform or "TikTok"
        prompt = (
            f"Suggest 5-8 short search terms (a few words each) this creator "
            f"could type into {platform_label}'s own search bar to find OTHER "
            f"creators' content relevant to their own niche — for inspiration, "
            f"not terms for their own captions or hashtags.\n\n"
            f"Creator's niche: {profile.niche or 'not set'}"
            f"{f' ({profile.sub_niche})' if profile.sub_niche else ''}\n"
            f"Target audience: {profile.target_audience or 'not set'}\n"
            f"Content style: {profile.content_style or ''}\n\n"
            f"{history_block}"
            f"Return ONLY the search terms, one per line, no numbering, no "
            f"explanation."
        )
        result = await invoke_llm(prompt, use_cache=False)
        keywords = [k.strip("-•* ").strip() for k in result.content.strip().split("\n") if k.strip()]
        lines = [f"Search terms for {platform_label}:"]
        lines += [f"  • {k}" for k in keywords[:8]]
        return "\n".join(lines)
