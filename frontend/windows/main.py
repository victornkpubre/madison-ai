"""
floating_launcher — entry point
Run:  python main.py
"""
import sys
import os

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("FloatingLauncher")
    app.setQuitOnLastWindowClosed(False)

    # ── Load theme ────────────────────────────────────────────────────────────
    from app.core.settings import load_settings
    settings = load_settings()

    theme_file = f"assets/themes/{settings.get('theme', 'dark')}.qss"
    if os.path.exists(theme_file):
        with open(theme_file, encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    # ── Boot UI ───────────────────────────────────────────────────────────────
    from app.ui.floating_btn import FloatingBtn
    from app.ui.tray_icon import AppTray

    btn  = FloatingBtn()
    tray = AppTray(btn)
    tray.show()

    # ── Optional: global hotkey ───────────────────────────────────────────────
    try:
        from app.utils.hotkeys import HotkeyManager
        hk = HotkeyManager()
        hk.triggered.connect(lambda _: btn.toggle_panel())
        hk.register(settings.get("hotkey", "ctrl+shift+space"))
        print(f"[hotkey] {settings.get('hotkey', 'ctrl+shift+space')} registered")
    except Exception as exc:
        print(f"[hotkey] not available — {exc}")

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
