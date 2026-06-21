from backend.composition import creator_service, idea_service
from backend.domain.entities.assistant_entity import OnboardingStatus


class AssistantService:

    def __init__(self):
        self._creator = creator_service
        self._ideas   = idea_service

    # ── onboarding ────────────────────────────────────────────────────────
    async def check_onboarding_status(self) -> OnboardingStatus:
        profile = await self._creator.get_profile()
        kb      = self._creator.list_knowledge(limit=1000)
        return OnboardingStatus(
            profile_set=profile.is_set(),
            profile_name=profile.name or "",
            knowledge_count=len(kb),
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
        self._creator.save_knowledge(topic.lower().strip(), answer, source="gap_fill")
        return f"✓ Saved to knowledge base: '{topic}'"


# Process-wide singleton.
assistant_service = AssistantService()
