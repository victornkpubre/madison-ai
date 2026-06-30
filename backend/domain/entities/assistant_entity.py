from dataclasses import dataclass, field


@dataclass
class OnboardingStatus:
    """Snapshot of available creator information, used to drive both the
    growth-focused welcome message and the mechanical onboarding Q&A."""
    profile_set: bool
    profile_name: str
    knowledge_count: int
    idea_profile_missing: list[str] = field(default_factory=list)
    has_audience_analysis: bool = False

    @property
    def is_complete(self) -> bool:
        """Base onboarding gate: creator identity + at least one knowledge
        entry. Required before handling any other request."""
        return self.profile_set and self.knowledge_count > 0

    @property
    def growth_ready(self) -> bool:
        """True once there's enough creator + audience data to build a real,
        data-grounded content plan instead of asking for more setup."""
        return not self.idea_profile_missing and self.has_audience_analysis

    def describe(self) -> str:
        lines = ["Onboarding status:"]
        if self.profile_set:
            lines.append(f"  \u2713  Creator profile set — name: {self.profile_name}")
        else:
            lines.append("  \u25cb  Creator profile not set (name, bio, call to action)")

        if self.knowledge_count > 0:
            lines.append(f"  \u2713  Knowledge base has {self.knowledge_count} entries")
        else:
            lines.append("  \u25cb  Knowledge base is empty")

        if self.idea_profile_missing:
            lines.append("  \u25cb  Content-strategy profile incomplete — missing: "
                         + ", ".join(self.idea_profile_missing))
        else:
            lines.append("  \u2713  Content-strategy profile complete (niche, audience, style, etc.)")

        if self.has_audience_analysis:
            lines.append("  \u2713  Audience analysis has been run at least once")
        else:
            lines.append("  \u25cb  No audience analysis yet")

        if not self.is_complete:
            lines.append("\nOnboarding is incomplete. Collect missing information "
                         "conversationally before handling the creator's request.")
        elif self.growth_ready:
            lines.append("\nSetup complete and growth-ready: recommend a data-grounded "
                         "content plan or audience-driven next step, not more setup.")
        else:
            lines.append("\nBase setup complete. Proceed with the creator's request, but "
                         "mention that the content-strategy profile and/or audience "
                         "analysis are still missing — collecting them unlocks a real "
                         "content plan.")
        return "\n".join(lines)
