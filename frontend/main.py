
import sys
import os

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from frontend.settings import load_settings


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("FloatingLauncher")
    app.setQuitOnLastWindowClosed(False)

    # ── Load theme ────────────────────────────────────────────────────────────
    settings = load_settings()

    theme_file = f"assets/themes/{settings.get('theme', 'dark')}.qss"
    if os.path.exists(theme_file):
        with open(theme_file, encoding="utf-8") as f:
            app.setStyleSheet(f.read())


if __name__ == "__main__":
    main()
