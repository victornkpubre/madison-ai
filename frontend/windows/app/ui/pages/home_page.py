"""
application/ui/pages/home_page.py
──────────────────────────
The default launcher menu — matches the screenshot exactly.

Navigation signals
  navigate(str)  → 'chat' | 'dashboard'
  request_close  → collapse the launcher

Tools section
  Collapsible row at the bottom of the menu showing the
  three StreamEye service statuses.  Call update_db_count(n)
  from outside to refresh the row count badge.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QApplication,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QBrush, QColor, QPen, QFont

# ── Nav items  (icon, label, target_page | None) ──────────────────────────────
_NAV = [
    ("🔍", "OCR Agent",  "chat"),
    ("📊", "Dashboard",  "dashboard"),
    ("📈", "Analytics",  None),
    ("🔔", "Alerts",     None),
    ("🎬", "Clips",      None),
]

# ── Tool / service rows ────────────────────────────────────────────────────────
_TOOLS = [
    ("👁", "OCR Extractor", "dot"),
    ("🗄", "Database",      "badge"),
    ("📤", "Telegram Bot",  "dot"),
]


class _CircleIcon(QWidget):
    """Painted circle with a 3×3 dot grid — used in the panel header."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor("#3949AB")))
        p.setPen(Qt.NoPen)
        p.drawEllipse(0, 0, 36, 36)
        p.setBrush(QBrush(QColor(255, 255, 255, 210)))
        dot = 3
        for r in range(3):
            for c in range(3):
                p.drawEllipse(
                    int(18 - 5 + c * 5 - dot / 2),
                    int(18 - 5 + r * 5 - dot / 2),
                    dot, dot,
                )


class HomePage(QWidget):
    navigate      = pyqtSignal(str)   # 'chat' | 'dashboard'
    request_close = pyqtSignal()
    tools_toggled = pyqtSignal(bool)  # True = expanded

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")
        self._tools_open = False
        self._dot_widgets: dict[str, QWidget] = {}
        self._db_badge: QLabel | None = None
        self._build()

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_header())
        root.addWidget(self._make_divider())
        root.addSpacing(4)

        for icon, label, target in _NAV:
            root.addWidget(self._make_nav_btn(icon, label, target))

        root.addSpacing(4)
        root.addWidget(self._make_divider())
        root.addSpacing(2)
        root.addWidget(self._make_tools_toggle())

        self._tools_content = self._make_tools_content()
        self._tools_content.hide()
        root.addWidget(self._tools_content)

        root.addStretch()
        root.addWidget(self._make_divider())
        root.addWidget(self._make_footer())

    def _make_header(self) -> QWidget:
        w = QWidget()
        w.setObjectName("PanelHeader")
        w.setFixedHeight(52)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)

        lay.addWidget(_CircleIcon())

        title = QLabel("Quick Launch")
        title.setObjectName("PanelTitle")
        lay.addWidget(title, stretch=1)

        close = QPushButton("✕")
        close.setObjectName("CloseBtn")
        close.setFixedSize(22, 22)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.request_close)
        lay.addWidget(close)
        return w

    def _make_divider(self) -> QFrame:
        d = QFrame()
        d.setFrameShape(QFrame.HLine)
        d.setObjectName("Divider")
        return d

    def _make_nav_btn(self, icon: str, label: str, target) -> QPushButton:
        btn = QPushButton(f"  {icon}   {label}")
        btn.setObjectName("NavBtn")
        btn.setFixedHeight(38)
        btn.setCursor(Qt.PointingHandCursor)
        if target:
            btn.clicked.connect(lambda _, t=target: self.navigate.emit(t))
        return btn

    def _make_tools_toggle(self) -> QPushButton:
        self._tools_toggle = QPushButton("  ▶   Tools")
        self._tools_toggle.setObjectName("ToolsToggle")
        self._tools_toggle.setFixedHeight(32)
        self._tools_toggle.setCursor(Qt.PointingHandCursor)
        self._tools_toggle.clicked.connect(self._toggle_tools)
        return self._tools_toggle

    def _make_tools_content(self) -> QWidget:
        w = QWidget()
        w.setObjectName("ToolsContent")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 2, 10, 4)
        lay.setSpacing(3)

        for icon, label, indicator in _TOOLS:
            row = QHBoxLayout()
            lbl = QPushButton(f"  {icon}   {label}")
            lbl.setObjectName("ToolRow")
            lbl.setFixedHeight(32)
            lbl.setCursor(Qt.PointingHandCursor)
            row.addWidget(lbl, stretch=1)

            if indicator == "dot":
                dot = QLabel("●")
                dot.setObjectName("DotOff")
                dot.setFixedWidth(18)
                dot.setAlignment(Qt.AlignCenter)
                self._dot_widgets[label] = dot
                row.addWidget(dot)
            elif indicator == "badge":
                badge = QLabel("0 rows")
                badge.setObjectName("DbBadge")
                badge.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._db_badge = badge
                row.addWidget(badge)

            lay.addLayout(row)
        return w

    def _make_footer(self) -> QWidget:
        w = QWidget()
        w.setObjectName("FooterRow")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(10, 6, 10, 8)
        lay.setSpacing(6)

        s = QPushButton("⚙   Settings")
        s.setObjectName("SecondaryBtn")
        s.setFixedHeight(32)
        s.setCursor(Qt.PointingHandCursor)

        q = QPushButton("Quit")
        q.setObjectName("DangerBtn")
        q.setFixedHeight(32)
        q.setCursor(Qt.PointingHandCursor)
        q.clicked.connect(QApplication.quit)

        lay.addWidget(s, stretch=2)
        lay.addWidget(q, stretch=1)
        return w

    # ── Tools section toggle ───────────────────────────────────────────────────

    def _toggle_tools(self):
        self._tools_open = not self._tools_open
        self._tools_content.setVisible(self._tools_open)
        arrow = "▼" if self._tools_open else "▶"
        self._tools_toggle.setText(f"  {arrow}   Tools")
        self.tools_toggled.emit(self._tools_open)

    # ── Public API ─────────────────────────────────────────────────────────────

    def update_db_count(self, n: int):
        if self._db_badge:
            self._db_badge.setText(f"{n} rows")

    def set_service_running(self, name: str, running: bool):
        dot = self._dot_widgets.get(name)
        if dot:
            dot.setObjectName("DotOn" if running else "DotOff")
            dot.style().unpolish(dot)
            dot.style().polish(dot)
