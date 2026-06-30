from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


KNOWN_FIELDS: list[str] = ["tiktok_username", "telegram", "email", "age", "location"]
MAX_SLICES = 40

CaptureRecord = dict[str, str]


@dataclass
class CaptureSession:
    """The accumulated state of one capture run"""
    fields: list[str]
    target: int
    records: list[CaptureRecord] = field(default_factory=list)
    slices_done: int = 0
    capture_tool_id: Optional[str] = None
    stopped_reason: Optional[str] = None
    platform: str = "tiktok"
    id: Optional[str] = None
    created_at: Optional[datetime] = None

    @property
    def collected(self) -> int:
        return len(self.records)

    def is_complete(self) -> bool:
        return self.collected >= self.target or self.slices_done >= MAX_SLICES
