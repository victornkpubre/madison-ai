"""
application/ui/tray_icon.py
───────────────────
System-tray icon (notification area, bottom-right of taskbar).

  Left-click  → show / hide the floating button
  Right-click → context menu (theme switch, quit)

The tray icon is drawn programmatically — no .ico file required.
If you want a custom icon, replace _make_icon() with:
    return QIcon("assets/icons/application.ico")
"""
from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush
from PyQt5.QtCore import Qt
import os


def _make_icon(color: str = "#5C6BC0", size: int = 32) -> QIcon:
    """Render a solid circle as the tray icon."""
    px = QPixmap(size, size)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.NoPen)
    margin = 2
    p.drawEllipse(margin, margin, size - margin * 2, size - margin * 2)
    p.end()
    return QIcon(px)


class AppTray(QSystemTrayIcon):
    """System-tray companion for the floating launcher."""

    def __init__(self, launcher, parent=None):
        super().__init__(_make_icon(), parent)
        self.launcher = launcher
        self.setToolTip("Floating Launcher")
        self._build_menu()
        self.activated.connect(self._on_activate)

    # ── Menu ───────────────────────────────────────────────────────────────────

    def _build_menu(self):
        menu = QMenu()

        toggle = menu.addAction("Show / Hide launcher")
        toggle.triggered.connect(self.launcher.toggle_visibility)

        menu.addSeparator()

        theme_menu = menu.addMenu("Theme")
        theme_menu.addAction("Dark").triggered.connect(
            lambda: self._set_theme("dark"))
        theme_menu.addAction("Light").triggered.connect(
            lambda: self._set_theme("light"))

        menu.addSeparator()

        menu.addAction("Quit").triggered.connect(QApplication.quit)

        self.setContextMenu(menu)

    # ── Callbacks ──────────────────────────────────────────────────────────────

    def _on_activate(self, reason):
        if reason == QSystemTrayIcon.Trigger:   # left-click
            self.launcher.toggle_visibility()

    def _set_theme(self, name: str):
        from app.core.settings import load_settings, save_settings
        path = f"assets/themes/{name}.qss"
        if not os.path.exists(path):
            self.showMessage(
                "Theme not found",
                f"Could not find {path}",
                QSystemTrayIcon.Warning,
                2000,
            )
            return
        with open(path) as f:
            QApplication.instance().setStyleSheet(f.read())
        s = load_settings()
        s["theme"] = name
        save_settings(s)
        self.showMessage(
            "Theme changed",
            f"Switched to {name} theme",
            QSystemTrayIcon.Information,
            1500,
        )
