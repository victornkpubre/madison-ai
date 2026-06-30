"""
database.py (interface/api)
══════════════════════════════
Read-only database browser for the desktop app's Database page.

Exposes the curated views defined in
infrastructure/database/browser.py so the creator can inspect their
stored data without a SQL client. Strictly read-only — there are no
write or delete endpoints here.

  GET /database/views          → [{key, label}, ...]
  GET /database/views/{key}    → {columns: [...], rows: [[...]]}
"""
from __future__ import annotations

from fastapi import APIRouter

from infrastructure.database import browser

router = APIRouter()


@router.get("/database/views")
async def list_database_views():
    """Return the available views (key + display label) in display order."""
    return {"views": browser.list_views()}


@router.get("/database/views/{key}")
async def get_database_view(key: str):
    """Return the columns and rows for one view."""
    return await browser.load_view(key)
