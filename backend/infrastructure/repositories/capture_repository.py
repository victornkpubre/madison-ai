"""
capture_repository.py
═════════════════════════
Persists completed capture sessions (see domain/captures/capture_entity.py
and CaptureSessionModel). Additive to the original codebase — the capture
loop itself is unchanged; this just gives finished sessions a durable
home so the creator can review what's been captured via GET /captures.

Falls back to an in-memory list when DATABASE_URL is not set, matching
every other repository in this codebase.
"""
from __future__ import annotations

import json

from sqlalchemy import select

from backend.config import settings
from backend.domain.entities.capture_entity import CaptureSession
from backend.infrastructure.database.capture_model import CaptureSessionModel
from backend.infrastructure.database.db import get_sync_session


class CaptureRepository:

    def __init__(self):
        self._sessions_mem: list[dict] = []

    def save_session(self, session: CaptureSession) -> None:
        record = {
            "fields": session.fields,
            "target": session.target,
            "collected": session.collected,
            "records": session.records,
            "stopped_reason": session.stopped_reason,
        }
        if settings.database_url:
            with get_sync_session() as s:
                s.add(CaptureSessionModel(
                    fields=",".join(session.fields),
                    target=session.target,
                    collected=session.collected,
                    records_json=json.dumps(session.records)[:8000],
                    stopped_reason=session.stopped_reason,
                ))
                s.commit()
        else:
            self._sessions_mem.append(record)

    def list_recent(self, limit: int = 20) -> list[dict]:
        if settings.database_url:
            with get_sync_session() as s:
                rows = s.execute(
                    select(CaptureSessionModel)
                    .order_by(CaptureSessionModel.created_at.desc())
                    .limit(limit)
                ).scalars().all()
            out = []
            for r in rows:
                try:
                    records = json.loads(r.records_json)
                except Exception:
                    records = []
                out.append({
                    "id": r.id, "fields": r.fields.split(","),
                    "target": r.target, "collected": r.collected,
                    "records": records, "stopped_reason": r.stopped_reason,
                    "created_at": str(r.created_at),
                })
            return out
        return list(reversed(self._sessions_mem))[:limit]


# Process-wide singleton — see application/assistant/assistant_graph.py
capture_repository = CaptureRepository()
