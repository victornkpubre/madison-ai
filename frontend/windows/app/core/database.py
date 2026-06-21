"""
application/core/database.py
─────────────────────
SQLite capture store.  Populated automatically by the Marketing Agent;
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
        # check_same_thread=False so the Marketing Agent thread can write
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

    # ── Generic table introspection (Database page) ─────────────────────────────

    def list_tables(self) -> list[str]:
        """Return every user table name in this database."""
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]

    def table_columns(self, table: str) -> list[str]:
        """Return column names for a table. `table` must come from list_tables()."""
        if table not in self.list_tables():
            return []
        return [r[1] for r in self._conn.execute(f'PRAGMA table_info("{table}")').fetchall()]

    def table_rows(self, table: str) -> list[tuple]:
        """Return every row (as tuples, in column order) for a table.
        `table` must come from list_tables()."""
        if table not in self.list_tables():
            return []
        return self._conn.execute(f'SELECT * FROM "{table}" ORDER BY 1 DESC').fetchall()

    # ── Export ─────────────────────────────────────────────────────────────────

    def export_excel(self, table: str = "captures", path: Optional[str] = None) -> str:
        """
        Write all rows of `table` to an Excel file.
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

        if path is None:
            path = f"exports/{table}.xlsx"
        os.makedirs(os.path.dirname(path), exist_ok=True)

        if table == "captures":
            df = pd.DataFrame(self.all_rows())
            # Friendlier column names for the spreadsheet
            df = df.rename(columns={
                "id":          "ID",
                "captured_at": "Captured at",
                "tiktok_name": "TikTok name",
                "telegram":    "Telegram",
                "context":     "Context",
            })
        else:
            df = pd.DataFrame(self.table_rows(table), columns=self.table_columns(table))

        df.to_excel(path, index=False)
        return path

    # ── Housekeeping ───────────────────────────────────────────────────────────

    def clear(self, table: str = "captures"):
        if table not in self.list_tables():
            return
        self._conn.execute(f'DELETE FROM "{table}"')
        self._conn.commit()

    def close(self):
        self._conn.close()
