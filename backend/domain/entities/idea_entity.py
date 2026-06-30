from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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
