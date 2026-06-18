"""
application/core/database.py
─────────────────────
SQLite capture store.  Populated automatically by the OCR Agent;
read by the Telegram Bot to get numbers; exportable to Excel.

Schema
──────
captures(id, captured_at, tiktok_name, telegram, raw_context)
"""
import sqlite3
import os
from typing import Optional

_DB_PATH = "config/captures.db"


class CaptureDatabase:

    def __init__(self, path: str = _DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # check_same_thread=False so the OCR agent thread can write
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._init_schema()

    # ── Schema ─────────────────────────────────────────────────────────────────

    def _init_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS captures (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT    DEFAULT (datetime('now')),
                tiktok_name TEXT,
                telegram    TEXT,
                raw_context TEXT
            )
        """)
        self._conn.commit()

    # ── Write ──────────────────────────────────────────────────────────────────

    def save(self,
             tiktok_name: str,
             telegram: str,
             context: str = "") -> int:
        """Insert one capture row.  Returns the new row id."""
        cur = self._conn.execute(
            "INSERT INTO captures (tiktok_name, telegram, raw_context) VALUES (?,?,?)",
            (tiktok_name, telegram, context),
        )
        self._conn.commit()
        return cur.lastrowid

    def save_batch(self, rows: list[dict]) -> int:
        """
        Insert multiple rows at once.
        Each dict must have 'tiktok_name' and 'telegram' keys.
        Returns the number of rows inserted.
        """
        data = [(r["tiktok_name"], r.get("telegram", ""), r.get("context", ""))
                for r in rows]
        self._conn.executemany(
            "INSERT INTO captures (tiktok_name, telegram, raw_context) VALUES (?,?,?)",
            data,
        )
        self._conn.commit()
        return len(data)

    # ── Read ───────────────────────────────────────────────────────────────────

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]

    def all_rows(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, captured_at, tiktok_name, telegram, raw_context "
            "FROM captures ORDER BY id DESC"
        ).fetchall()
        return [
            {
                "id":          r[0],
                "captured_at": r[1],
                "tiktok_name": r[2],
                "telegram":    r[3],
                "context":     r[4],
            }
            for r in rows
        ]

    def telegram_contacts(self) -> list[str]:
        """Return all non-empty telegram values — used by the Telegram Bot."""
        rows = self._conn.execute(
            "SELECT telegram FROM captures "
            "WHERE telegram IS NOT NULL AND telegram != '' "
            "ORDER BY id DESC"
        ).fetchall()
        return [r[0] for r in rows]

    # ── Export ─────────────────────────────────────────────────────────────────

    def export_excel(self, path: str = "exports/captures.xlsx") -> str:
        """
        Write all rows to an Excel file.
        Requires:  pip install pandas openpyxl
        Returns the output path.
        """
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError(
                "Excel export requires pandas and openpyxl.\n"
                "Install with:  pip install pandas openpyxl"
            ) from exc

        os.makedirs(os.path.dirname(path), exist_ok=True)
        df = pd.DataFrame(self.all_rows())
        # Friendlier column names for the spreadsheet
        df = df.rename(columns={
            "id":          "ID",
            "captured_at": "Captured at",
            "tiktok_name": "TikTok name",
            "telegram":    "Telegram",
            "context":     "Context",
        })
        df.to_excel(path, index=False)
        return path

    # ── Housekeeping ───────────────────────────────────────────────────────────

    def clear(self):
        self._conn.execute("DELETE FROM captures")
        self._conn.commit()

    def close(self):
        self._conn.close()
