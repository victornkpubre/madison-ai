"""
application/ui/pages/dashboard_page.py
───────────────────────────────
Database viewer — accessible from the home menu's "Dashboard" item.

Shows the captures table with columns:
  ID | TikTok Name | Telegram | Captured At

Buttons: Refresh · Export to Excel · Clear database
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor

from app.core.database import CaptureDatabase


class DashboardPage(QWidget):
    go_back       = pyqtSignal()
    request_close = pyqtSignal()

    def __init__(self, db: CaptureDatabase, parent=None):
        super().__init__(parent)
        self.setObjectName("DashboardPage")
        self.db = db
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

        self._count_lbl = QLabel("0 captures")
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
        cols = ["ID", "TikTok Name", "Telegram", "Captured At"]
        self._table = QTableWidget(0, len(cols))
        self._table.setObjectName("CaptureTable")
        self._table.setHorizontalHeaderLabels(cols)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)   # ID
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)            # TikTok
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)            # Telegram
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)   # Time

        return self._table

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        w.setObjectName("Toolbar")
        w.setFixedHeight(44)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(10, 6, 10, 8)
        lay.setSpacing(8)

        clear = QPushButton("🗑  Clear table")
        clear.setObjectName("DangerBtn")
        clear.setFixedHeight(30)
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(self._confirm_clear)

        export = QPushButton("Export to Excel")
        export.setObjectName("ActionBtn")
        export.setFixedHeight(30)
        export.setCursor(Qt.PointingHandCursor)
        export.clicked.connect(self._export)

        lay.addWidget(clear)
        lay.addStretch()
        lay.addWidget(export)
        return w

    # ── Data ───────────────────────────────────────────────────────────────────

    def refresh(self):
        """Reload data from the database."""
        rows = self.db.all_rows()
        self._table.setRowCount(0)

        for row in rows:
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setRowHeight(r, 28)

            for c, val in enumerate([
                str(row["id"]),
                row["tiktok_name"] or "",
                row["telegram"]    or "",
                row["captured_at"] or "",
            ]):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self._table.setItem(r, c, item)

        count = len(rows)
        self._count_lbl.setText(
            f"{count} capture{'s' if count != 1 else ''}"
        )

    def _export(self):
        try:
            path = self.db.export_excel()
            # Show brief confirmation in the stats bar
            self._count_lbl.setText(f"✓ Exported → {path}")
        except Exception as exc:
            self._count_lbl.setText(f"Export failed: {exc}")

    def _confirm_clear(self):
        mb = QMessageBox(self)
        mb.setWindowTitle("Clear database")
        mb.setText("Delete all captured rows?  This cannot be undone.")
        mb.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        mb.setDefaultButton(QMessageBox.Cancel)
        if mb.exec_() == QMessageBox.Yes:
            self.db.clear()
            self.refresh()
