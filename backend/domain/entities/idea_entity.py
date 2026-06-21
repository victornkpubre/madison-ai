from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Fields collected conversationally during Phase 1 of the idea-generator
# flow, with a human-readable description of each — shared between the
# application-layer service and the LangGraph tool docstrings.
PROFILE_FIELDS: dict[str, str] = {
    "niche":            "Main content area (fitness, finance, cooking, etc.)",
    "sub_niche":        "Specific focus within the niche",
    "target_audience":  "Who the content is for (demographics, interests, pain points)",
    "platforms":        "Where the creator posts (list of platforms)",
    "content_style":    "Communication style (educational, entertaining, motivational...)",
    "monetization":     "Revenue streams (sponsorships, courses, memberships, tips...)",
}


@dataclass
class CreatorIdeaProfile:
    """Content-strategy profile used exclusively by the idea generator."""
    niche: Optional[str] = None
    sub_niche: Optional[str] = None
    target_audience: Optional[str] = None
    platforms: Optional[str] = None
    content_style: Optional[str] = None
    monetization: Optional[str] = None
    updated_at: Optional[datetime] = None

    def filled_fields(self) -> dict[str, str]:
        return {k: v for k, v in self.as_dict().items() if v}

    def missing_fields(self) -> list[str]:
        filled = self.filled_fields()
        return [k for k in PROFILE_FIELDS if k not in filled]

    def as_dict(self) -> dict:
        return {"niche": self.niche, "sub_niche": self.sub_niche,
                "target_audience": self.target_audience,
                "platforms": self.platforms,
                "content_style": self.content_style,
                "monetization": self.monetization}


@dataclass
class ContentHistoryItem:
    """A past video, post, or live session — used to avoid idea repetition
    and reveal coverage gaps."""
    title: str
    topic: Optional[str] = None
    content_type: Optional[str] = None   # video | photo | live | digital
    platform: Optional[str] = None
    id: Optional[str] = None
    posted_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


@dataclass
class AudienceSignal:
    """A raw viewer message collected for audience-intelligence analysis."""
    content: str
    source: str = "telegram"
    session_id: str = ""
    id: Optional[str] = None
    signal_type: Optional[str] = None   # question | request | positive | negative | neutral
    topic: Optional[str] = None
    timestamp: Optional[datetime] = None


@dataclass
class TopicAnalytic:
    """Per-topic metrics derived from audience signal analysis."""
    topic: str
    frequency: int = 1
    velocity: float = 0.0
    curiosity_score: float = 0.0
    question_count: int = 0
    request_count: int = 0
    sentiment: float = 0.0
    last_seen: Optional[datetime] = None
