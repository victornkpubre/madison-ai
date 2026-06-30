from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# The content-strategy half of the unified creator profile. Kept as a named map
# (field -> human-readable description) so services and the idea-generator tool
# docstrings share one source of truth. Identity fields (name/bio/cta/email) are
# listed separately because they are collected by a different flow.
STRATEGY_FIELDS: dict[str, str] = {
    "niche":            "Main content area (fitness, finance, cooking, etc.)",
    "sub_niche":        "Specific focus within the niche",
    "target_audience":  "Who the content is for (demographics, interests, pain points)",
    "platforms":        "Where the creator posts (list of platforms)",
    "content_style":    "Communication style (educational, entertaining, motivational...)",
    "monetization":     "Revenue streams (sponsorships, courses, memberships, tips...)",
}

IDENTITY_FIELDS: tuple[str, ...] = ("name", "bio", "cta", "email")
PROFILE_FIELDS: tuple[str, ...] = IDENTITY_FIELDS + tuple(STRATEGY_FIELDS)


@dataclass
class CreatorProfile:
    """The creator's single unified profile. Holds both the public-facing
    identity used by message templates and the viewer-reply agent (name, bio,
    cta, email) AND the content-strategy fields used by the idea generator
    (niche, sub_niche, target_audience, platforms, content_style, monetization).

    Previously these were two separate profiles (CreatorProfile + the idea
    generator's CreatorIdeaProfile) backed by two tables; they are now one row,
    so both agents read and write a single source of truth."""
    # identity / outreach
    name: Optional[str] = None
    bio: Optional[str] = None
    cta: Optional[str] = None
    email: Optional[str] = None
    # content strategy
    niche: Optional[str] = None
    sub_niche: Optional[str] = None
    target_audience: Optional[str] = None
    platforms: Optional[str] = None
    content_style: Optional[str] = None
    monetization: Optional[str] = None
    updated_at: Optional[datetime] = None

    def is_set(self) -> bool:
        return bool(self.name)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in PROFILE_FIELDS}

    def identity_dict(self) -> dict:
        return {k: getattr(self, k) for k in IDENTITY_FIELDS}

    def strategy_dict(self) -> dict:
        return {k: getattr(self, k) for k in STRATEGY_FIELDS}

    # ── content-strategy completeness (used by the idea generator) ──────────
    def strategy_filled(self) -> dict[str, str]:
        return {k: v for k, v in self.strategy_dict().items() if v}

    def strategy_missing(self) -> list[str]:
        filled = self.strategy_filled()
        return [k for k in STRATEGY_FIELDS if k not in filled]


@dataclass
class CreatorKnowledgeEntry:
    """A single entry of the knowledge base of the creator used by the viewer-reply agent —
    their story, an opinion, a common answer, a resource link, etc."""
    topic: str
    content: str
    source: str = "manual"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def normalised_topic(self) -> str:
        return self.topic.lower().strip()
