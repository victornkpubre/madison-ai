from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CreatorProfile:
    """The creator's public-facing profile, used to personalise message
    templates and the viewer-reply agent's system prompt."""
    name: Optional[str] = None
    bio: Optional[str] = None
    cta: Optional[str] = None
    email: Optional[str] = None
    updated_at: Optional[datetime] = None

    def is_set(self) -> bool:
        return bool(self.name)

    def as_dict(self) -> dict:
        return {"name": self.name, "bio": self.bio,
                "cta": self.cta, "email": self.email}

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
