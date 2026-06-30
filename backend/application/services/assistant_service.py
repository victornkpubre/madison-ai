from composition import creator_service, idea_service
from domain.entities.assistant_entity import OnboardingStatus


# Values that are placeholders, not real creator knowledge. An agent that saves
# one of these (e.g. 'monetization' -> 'TBD') pollutes the knowledge base with
# entries that look real but say nothing — so we neither save nor list them.
_PLACEHOLDER_VALUES = {
    "", "tbd", "tba", "tbc", "n/a", "na", "none", "null", "nil",
    "unknown", "pending", "-", "--", "—", "?", "...", "to be decided",
    "to be determined",
}


def _is_placeholder(text: str) -> bool:
    return (text or "").strip().lower() in _PLACEHOLDER_VALUES


class AssistantService:

    def __init__(self):
        self._creator = creator_service
        self._ideas   = idea_service

    # ── onboarding ────────────────────────────────────────────────────────
    async def check_onboarding_status(self) -> OnboardingStatus:
        profile     = await self._creator.get_profile()
        kb          = self._creator.list_knowledge(limit=1000)
        latest_analysis = self._ideas.load_latest_audience_analysis()
        return OnboardingStatus(
            profile_set=profile.is_set(),
            profile_name=profile.name or "",
            knowledge_count=len(kb),
            idea_profile_missing=profile.strategy_missing(),
            has_audience_analysis=latest_analysis is not None,
        )

    async def save_creator_profile(self, name: str, bio: str, cta: str,
                                    email: str = "") -> str:
        try:
            await self._creator.save_profile(name, bio, cta, email or None)
            return (f"✓ Profile saved.\n"
                    f"  Name: {name}\n"
                    f"  Bio:  {bio}\n"
                    f"  CTA:  {cta}")
        except Exception as e:
            return f"✗ Error saving profile: {e}"

    async def reset_creator_profile(self) -> str:
        try:
            await self._creator.reset_profile()
            return ("✓ Profile cleared — name, bio, CTA, email, niche, sub-niche, "
                     "target audience, platforms, content style, and monetization "
                     "are all reset. Knowledge base entries and captured records "
                     "were NOT touched. Start onboarding over from scratch.")
        except Exception as e:
            return f"✗ Error clearing profile: {e}"

    async def clear_knowledge_base(self) -> str:
        try:
            await self._creator.clear_knowledge()
            return ("✓ Knowledge base cleared — every saved entry was removed. "
                     "Your profile and captured records were NOT touched by this.")
        except Exception as e:
            return f"✗ Error clearing knowledge base: {e}"

    # ── reading what's already stored ─────────────────────────────────────
    def list_knowledge_entries(self, limit: int = 60) -> str:
        """Return the ACTUAL knowledge-base entries (topic + saved answer), not
        just a count. Used by the marketing agent to answer 'what's in my
        knowledge base?' instead of claiming it can't see them."""
        try:
            entries = self._creator.list_knowledge(limit)
        except Exception as e:
            return f"Could not read the knowledge base ({e})."

        # Drop placeholder/empty entries (e.g. 'monetization: TBD') — they are
        # not real answers and should not be presented to the creator as such.
        entries = [e for e in entries if not _is_placeholder(e.content)]
        if not entries:
            return "The knowledge base is empty — no entries saved yet."

        lines = [f"Knowledge base has {len(entries)} "
                 f"entr{'y' if len(entries) == 1 else 'ies'}:"]
        for i, e in enumerate(entries, 1):
            answer = (e.content or "").strip()
            if len(answer) > 300:
                answer = answer[:300].rstrip() + "…"
            lines.append(f"{i}. {e.topic}: {answer}")
        return "\n".join(lines)

    def get_content_strategy_profile(self) -> str:
        """Return the SAVED content-strategy (idea) profile values — niche,
        sub_niche, target_audience, platforms, content_style, monetization —
        reading the real values, not just which fields are missing."""
        try:
            profile = self._ideas.load_profile()
        except Exception as e:
            return f"Could not read the content-strategy profile ({e})."

        filled  = profile.strategy_filled()
        missing = profile.strategy_missing()
        if not filled:
            return ("No content-strategy profile saved yet — niche, sub_niche, "
                    "target_audience, platforms, content_style and monetization "
                    "are all empty.")

        lines = ["Content-strategy profile (saved values):"]
        for k, v in filled.items():
            lines.append(f"  {k}: {v}")
        if missing:
            lines.append("Still missing: " + ", ".join(missing))
        return "\n".join(lines)

    # ── knowledge gaps ────────────────────────────────────────────────────
    def get_knowledge_gaps(self) -> str:
        """
        Find topics the audience is actively asking about that have no
        answer in the knowledge base yet, with the exact viewer questions
        pulled from the audience-signals data — nothing generated.
        """
        all_topics   = self._ideas.load_topic_analytics(40)
        has_interest = [t for t in all_topics
                        if t.get("question_count", 0) > 0
                        or t.get("request_count", 0) > 0]

        if not has_interest:
            return (
                "No audience signals have been analysed yet.\n"
                "Run analyze_audience() in the idea generator first, "
                "or send viewer messages to the Telegram bot to start building signals."
            )

        entries = self._creator.list_knowledge()
        known   = {e.topic.lower() for e in entries}

        gaps = []
        for t in has_interest:
            name = t["topic"].lower()
            covered = any(
                name in kt or kt in name or
                bool(set(name.split()) & set(kt.split()))
                for kt in known
            )
            if covered:
                continue

            viewer_msgs = self._ideas.load_signals_by_topic(name, ["question", "request"], 5)
            gaps.append({
                "topic":    t["topic"],
                "count":    t.get("question_count", 0) + t.get("request_count", 0),
                "messages": viewer_msgs,
            })

        if not gaps:
            return (
                "Your knowledge base already covers all active audience topics.\n"
                "Check back after more viewer messages have been collected."
            )

        lines = [
            f"{len(gaps)} topic(s) your audience keeps asking about "
            f"with no answer in your knowledge base:\n"
        ]
        for i, g in enumerate(gaps[:8], 1):
            lines.append(f"{i}. {g['topic'].upper()}  "
                         f"({g['count']} viewer message(s))")
            if g["messages"]:
                lines.append("   What viewers actually said:")
                for msg in g["messages"]:
                    lines.append(f'   — "{msg}"')
            else:
                lines.append("   (messages not yet loaded — run analyze_audience() first)")
            lines.append("")

        return "\n".join(lines)

    def save_to_knowledge_base(self, topic: str, answer: str) -> str:
        """
        Save the creator's own answer to the knowledge base. Must only be
        called with the creator's exact words — never LLM-drafted content.
        """
        if not (topic or "").strip():
            return "✗ Not saved: a topic label is required."
        if _is_placeholder(answer):
            return (f"✗ Not saved: '{answer.strip()}' is a placeholder, not a real "
                    f"answer. The knowledge base must hold the creator's actual words. "
                    f"Ask the creator for the real answer to '{topic}' and save that.")
        try:
            self._creator.save_knowledge(topic.lower().strip(), answer, source="gap_fill")
            return f"✓ Saved to knowledge base: '{topic}'"
        except Exception as e:
            # Return the error instead of raising: a raised tool error becomes an
            # error ToolMessage that the agent will retry indefinitely, blowing
            # the recursion limit. A plain string lets it move on.
            return f"✗ Error saving '{topic}': {e}"


# Process-wide singleton.
assistant_service = AssistantService()
