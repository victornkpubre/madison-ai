"""
application/ui/pages/dashboard_page.py
───────────────────────────────
Database viewer — accessible from the home menu's "Database" item.

Read-only browser over the backend's data. Pick a view from the selector
to see its columns and rows: creator profile, idea profile, captures,
captured contacts, Telegram users, email accounts, and message templates.

The data is fetched live from the backend (GET /database/views and
/database/views/{key}); the base URL is derived from `agent_url` in
config/settings.json. Backend data is read-only here, so there is no
"clear" action — only Refresh and Export to Excel.
"""
from urllib.parse import urlsplit

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox,
)
from PyQt5.QtCore import Qt, pyqtSignal

from app.core.settings import load_settings
from app.utils.db_api_worker import DbApiWorker


class DashboardPage(QWidget):
    go_back       = pyqtSignal()
    request_close = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DashboardPage")
        self._views: list[dict] = []           # [{key, label}, ...]
        self._columns: list[str] = []
        self._rows: list[list] = []
        self._threads: set = set()             # strong refs to live workers
        self._build()

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header())
        root.addWidget(self._make_divider())
        root.addWidget(self._make_stats_bar())
        root.addWidget(self._make_table(), stretch=1)
        root.addWidget(self._make_divider())
        root.addWidget(self._make_toolbar())

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setObjectName("PanelHeader")
        w.setFixedHeight(46)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(8, 0, 10, 0)
        lay.setSpacing(6)

        back = QPushButton("←")
        back.setObjectName("BackBtn")
        back.setFixedSize(28, 28)
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.go_back)
        back.setToolTip("Back to menu")

        title = QLabel("Database")
        title.setObjectName("PanelTitle")

        export = QPushButton("Export ↓")
        export.setObjectName("ExportBtn")
        export.setFixedHeight(24)
        export.setCursor(Qt.PointingHandCursor)
        export.clicked.connect(self._export)

        close = QPushButton("✕")
        close.setObjectName("CloseBtn")
        close.setFixedSize(22, 22)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.request_close)

        lay.addWidget(back)
        lay.addWidget(title, stretch=1)
        lay.addWidget(export)
        lay.addSpacing(4)
        lay.addWidget(close)
        return w

    def _make_divider(self) -> QFrame:
        d = QFrame()
        d.setFrameShape(QFrame.HLine)
        d.setObjectName("Divider")
        return d

    def _make_stats_bar(self) -> QWidget:
        w = QWidget()
        w.setObjectName("StatsBar")
        w.setFixedHeight(32)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        self._table_selector = QComboBox()
        self._table_selector.setObjectName("TableSelector")
        self._table_selector.setCursor(Qt.PointingHandCursor)
        self._table_selector.currentIndexChanged.connect(self._on_view_changed)
        lay.addWidget(self._table_selector)

        self._count_lbl = QLabel("0 rows")
        self._count_lbl.setObjectName("StatsLabel")
        lay.addWidget(self._count_lbl)
        lay.addStretch()

        refresh = QPushButton("↻ Refresh")
        refresh.setObjectName("SecondaryBtn")
        refresh.setFixedHeight(22)
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self.refresh)
        lay.addWidget(refresh)
        return w

    def _make_table(self) -> QTableWidget:
        self._table = QTableWidget(0, 0)
        self._table.setObjectName("CaptureTable")
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        return self._table

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        w.setObjectName("Toolbar")
        w.setFixedHeight(44)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(10, 6, 10, 8)
        lay.setSpacing(8)

        export = QPushButton("Export to Excel")
        export.setObjectName("ActionBtn")
        export.setFixedHeight(30)
        export.setCursor(Qt.PointingHandCursor)
        export.clicked.connect(self._export)

        lay.addStretch()
        lay.addWidget(export)
        return w

    # ── Backend access ───────────────────────────────────────────────────────────

    def _base_url(self) -> str:
        """Derive the backend root (scheme://host:port) from agent_url."""
        agent_url = load_settings().get("agent_url", "")
        parts = urlsplit(agent_url)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
        return ""

    def _fetch(self, path: str, on_loaded):
        """Spawn a worker to GET {base}{path} and call on_loaded(json)."""
        base = self._base_url()
        if not base:
            self._count_lbl.setText("No agent_url in config/settings.json")
            return
        worker = DbApiWorker(f"{base}{path}")
        worker.loaded.connect(on_loaded)
        worker.failed.connect(lambda msg: self._count_lbl.setText(msg))
        self._track(worker)
        worker.start()

    def _track(self, worker):
        """Keep a strong ref until Qt's finished signal, then drop and delete."""
        self._threads.add(worker)
        worker.finished.connect(lambda w=worker: self._threads.discard(w))
        worker.finished.connect(worker.deleteLater)

    # ── Data ───────────────────────────────────────────────────────────────────

    def refresh(self):
        """Reload the list of views, then the currently selected view's data."""
        self._count_lbl.setText("Loading…")
        self._fetch("/database/views", self._on_views_loaded)

    def _on_views_loaded(self, payload):
        views = (payload or {}).get("views", [])
        self._views = views
        current = self._table_selector.currentData()

        self._table_selector.blockSignals(True)
        self._table_selector.clear()
        for v in views:
            self._table_selector.addItem(v.get("label", v.get("key", "")), v.get("key"))
        # Restore the previous selection if it still exists.
        if current is not None:
            idx = self._table_selector.findData(current)
            if idx >= 0:
                self._table_selector.setCurrentIndex(idx)
        self._table_selector.blockSignals(False)

        if not views:
            self._count_lbl.setText("No data")
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            return
        self._load_view_data()

    def _on_view_changed(self, _index: int):
        self._load_view_data()

    def _current_key(self) -> str:
        return self._table_selector.currentData() or ""

    def _load_view_data(self):
        key = self._current_key()
        if not key:
            return
        self._count_lbl.setText("Loading…")
        self._fetch(f"/database/views/{key}", self._on_view_data_loaded)

    def _on_view_data_loaded(self, payload):
        payload = payload or {}
        self._columns = payload.get("columns", [])
        self._rows = payload.get("rows", [])

        self._table.setRowCount(0)
        self._table.setColumnCount(len(self._columns))
        self._table.setHorizontalHeaderLabels(self._columns)

        hdr = self._table.horizontalHeader()
        for c in range(len(self._columns)):
            hdr.setSectionResizeMode(
                c, QHeaderView.ResizeToContents if c == 0 else QHeaderView.Stretch)

        for row in self._rows:
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setRowHeight(r, 28)
            for c, val in enumerate(row):
                item = QTableWidgetItem("" if val is None else str(val))
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self._table.setItem(r, c, item)

        count = len(self._rows)
        self._count_lbl.setText(f"{count} row{'s' if count != 1 else ''}")

    # ── Export ───────────────────────────────────────────────────────────────────

    def _export(self):
        if not self._columns:
            self._count_lbl.setText("Nothing to export")
            return
        try:
            import os
            import pandas as pd
        except ImportError:
            self._count_lbl.setText("Export needs pandas + openpyxl")
            return
        try:
            os.makedirs("exports", exist_ok=True)
            path = f"exports/{self._current_key() or 'view'}.xlsx"
            pd.DataFrame(self._rows, columns=self._columns).to_excel(path, index=False)
            self._count_lbl.setText(f"✓ Exported → {path}")
        except Exception as exc:
            self._count_lbl.setText(f"Export failed: {exc}")

    # ── Lifecycle ─────────────────────────────────────────────────────────────────

    def cleanup(self):
        """Stop every running worker so Qt never destroys a live QThread on exit."""
        for worker in list(self._threads):
            try:
                worker.stop()
            except Exception:
                pass
        self._threads.clear()
