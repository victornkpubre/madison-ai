"""
application/ui/floating_btn.py  (v3 — multi-page)
──────────────────────────────────────────
The floating launcher button.  Expands into a multi-page panel:

  Home      →  quick-launch menu    (228 × 360)
  Chat      →  Marketing Agent chat (320 × 460)
  Dashboard →  database tables      (440 × 480)

Collapsed: 56×56 draggable circle. Draggable in either state — drag from
any non-interactive area (e.g. the panel header) while expanded.
"""
from PyQt5.QtWidgets import QWidget, QApplication, QStackedWidget, QVBoxLayout
from PyQt5.QtCore import Qt, QRect, QPropertyAnimation, QEasingCurve, QSize
from PyQt5.QtGui import QPainter, QBrush, QColor

from app.core.settings import load_settings, save_settings
from app.core.database import CaptureDatabase

# ── Dimensions per page ────────────────────────────────────────────────────────

_BTN = 56

_SIZES = {
    "home":           QSize(228, 358),
    "home_tools":     QSize(228, 460),   # home with Tools section expanded
    "chat":           QSize(320, 460),
    "dashboard":      QSize(440, 480),
}

_RAD = 12

# ── Colours ────────────────────────────────────────────────────────────────────

_C_BTN    = QColor("#5C6BC0")
_C_HOVER  = QColor("#7986CB")
_C_ACTIVE = QColor("#3949AB")
_C_PANEL  = QColor("#1E1E2E")
_C_DOT    = QColor(255, 255, 255, 210)
_C_SHADOW = QColor(0, 0, 0, 40)


class FloatingBtn(QWidget):
    """
    Floating launcher.  Circle when closed; multi-page panel when open.
    """

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint  |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)

        self._open        = False
        self._hovered     = False
        self._drag_start  = None
        self._drag_origin = None
        self._cur_page    = "home"

        # ── Database ──────────────────────────────────────────────────────────
        self.db = CaptureDatabase()

        # ── Pages ─────────────────────────────────────────────────────────────
        self._stack = QStackedWidget(self)
        self._stack.hide()

        from app.ui.pages.home_page      import HomePage
        from app.ui.pages.chat_page      import ChatPage
        from app.ui.pages.dashboard_page import DashboardPage

        self._home = HomePage()
        self._chat = ChatPage(self.db)
        self._dash = DashboardPage()

        self._stack.addWidget(self._home)
        self._stack.addWidget(self._chat)
        self._stack.addWidget(self._dash)

        # ── Wire navigation signals ───────────────────────────────────────────
        self._home.navigate.connect(self._navigate)
        self._home.request_close.connect(self.collapse)
        self._home.tools_toggled.connect(self._on_tools_toggled)

        self._chat.go_back.connect(lambda: self._navigate("home"))
        self._chat.request_close.connect(self.collapse)
        self._chat.data_saved.connect(
            lambda n: self._home.update_db_count(self.db.count())
        )

        self._dash.go_back.connect(lambda: self._navigate("home"))
        self._dash.request_close.connect(self.collapse)

        # ── Animation ─────────────────────────────────────────────────────────
        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._on_anim_done)

        # ── Position ──────────────────────────────────────────────────────────
        pos = load_settings().get("pos")
        self.resize(_BTN, _BTN)
        if pos:
            self.move(*pos)
        else:
            self._move_default()
        self.show()

    # ── Navigation ─────────────────────────────────────────────────────────────

    def _navigate(self, page: str):
        self._cur_page = page
        pages = {
            "home":      self._home,
            "chat":      self._chat,
            "dashboard": self._dash,
        }
        if page not in pages:
            return
        self._stack.setCurrentWidget(pages[page])
        sz = _SIZES.get(page, _SIZES["home"])
        self._resize_panel(sz.width(), sz.height())
        if page == "dashboard":
            self._dash.refresh()
        self.update()

    def _on_tools_toggled(self, expanded: bool):
        sz = _SIZES["home_tools"] if expanded else _SIZES["home"]
        self._resize_panel(sz.width(), sz.height())

    def _resize_panel(self, w: int, h: int):
        """Instantly resize the open panel (no animation — keeps it snappy)."""
        self.resize(w, h)
        self._stack.setGeometry(0, 0, w, h)

    # ── Expand / collapse ──────────────────────────────────────────────────────

    def expand(self):
        if self._open:
            return
        self._open = True
        self._stack.show()
        sz = _SIZES.get(self._cur_page, _SIZES["home"])
        tgt = self._target_rect(sz.width(), sz.height())
        self._anim.setStartValue(QRect(self.x(), self.y(), _BTN, _BTN))
        self._anim.setEndValue(tgt)
        self._anim.start()

    def collapse(self):
        if not self._open:
            return
        self._open = False
        self._stack.hide()
        self._navigate("home")
        self._anim.setStartValue(QRect(self.x(), self.y(), self.width(), self.height()))
        self._anim.setEndValue(QRect(self.x(), self.y(), _BTN, _BTN))
        self._anim.start()
        self.update()

    def toggle_panel(self):
        self.collapse() if self._open else self.expand()

    def cleanup(self):
        """Stop child worker threads and release resources before the app quits.
        Wire this to QApplication.aboutToQuit — closing the window isn't enough
        because the app uses setQuitOnLastWindowClosed(False) and quits via the
        tray/menu, which never fires a window closeEvent."""
        try:
            self._chat.cleanup()
        except Exception:
            pass
        try:
            self._dash.cleanup()
        except Exception:
            pass
        try:
            self.db.close()
        except Exception:
            pass

    def toggle_visibility(self):
        if self.isVisible():
            self.collapse()
            self.hide()
        else:
            self.show()

    def _target_rect(self, w: int, h: int) -> QRect:
        screen = QApplication.primaryScreen().availableGeometry()
        x = min(self.x(), screen.right()  - w - 4)
        y = min(self.y(), screen.bottom() - h - 4)
        return QRect(x, y, w, h)

    def _on_anim_done(self):
        if not self._open:
            self.resize(_BTN, _BTN)
        else:
            sz = _SIZES.get(self._cur_page, _SIZES["home"])
            self._stack.setGeometry(0, 0, sz.width(), sz.height())
        self.update()

    # ── Painting ───────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self._open and self.width() <= _BTN:
            self._paint_circle(p)
        else:
            self._paint_panel(p)

    def _paint_circle(self, p):
        d, m = _BTN - 10, 5
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(_C_SHADOW))
        p.drawEllipse(m + 1, m + 2, d, d)
        p.setBrush(QBrush(_C_HOVER if self._hovered else _C_BTN))
        p.drawEllipse(m, m, d, d)
        p.setBrush(QBrush(_C_DOT))
        cx, cy, dot = _BTN / 2, _BTN / 2, 4
        for r in range(3):
            for c in range(3):
                p.drawEllipse(
                    int(cx - 8 + c * 8 - dot / 2),
                    int(cy - 8 + r * 8 - dot / 2), dot, dot)

    def _paint_panel(self, p):
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(_C_SHADOW))
        p.drawRoundedRect(3, 4, w - 4, h - 4, _RAD, _RAD)
        p.setBrush(QBrush(_C_PANEL))
        p.drawRoundedRect(0, 0, w, h, _RAD, _RAD)

    # ── Mouse events ───────────────────────────────────────────────────────────

    def enterEvent(self, _):
        if not self._open:
            self._hovered = True
            self.update()

    def leaveEvent(self, _):
        self._hovered = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_start  = e.pos()
            self._drag_origin = e.globalPos()

    def mouseMoveEvent(self, e):
        if self._drag_start and e.buttons() == Qt.LeftButton:
            self.move(self.pos() + e.pos() - self._drag_start)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._drag_origin is None:
            return
        moved = (e.globalPos() - self._drag_origin).manhattanLength()
        if moved < 5 and not self._open:
            self.expand()
        elif moved >= 5:
            s = load_settings()
            s["pos"] = [self.x(), self.y()]
            save_settings(s)
        self._drag_start = self._drag_origin = None

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _move_default(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - _BTN - 20, screen.bottom() - _BTN - 20)
