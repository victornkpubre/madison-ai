"""
assistant_entity.py
═════════════════════
Domain entities for the creator-assistant feature — primarily the
onboarding status check that runs at the start of every new assistant
conversation to decide whether setup (profile + knowledge base) needs to
happen before the creator's actual request.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OnboardingStatus:
    """Snapshot of what's missing from the creator's setup."""

    profile_set: bool
    profile_name: str
    knowledge_count: int

    @property
    def is_complete(self) -> bool:
        return self.profile_set and self.knowledge_count > 0

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

        if not self.is_complete:
            lines.append("\nOnboarding is incomplete. Collect missing information "
                         "conversationally before handling the creator's request.")
        else:
            lines.append("\nSetup complete. Proceed with the creator's request.")
        return "\n".join(lines)
