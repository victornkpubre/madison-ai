"""
application/utils/hotkeys.py
─────────────────────
Thread-safe global hotkey manager.

The `keyboard` library fires callbacks on a background OS thread.
This class uses a Qt signal to marshal those callbacks back onto the
main Qt thread safely — no QThread or mutex required.

Install:
    pip install keyboard

Usage in main.py:
    hk = HotkeyManager()
    hk.triggered.connect(lambda _: btn.toggle_panel())
    hk.register("ctrl+shift+space")
"""
from PyQt5.QtCore import QObject, pyqtSignal


class HotkeyManager(QObject):
    """Emits `triggered(shortcut_str)` on the Qt main thread."""

    triggered = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            import keyboard
            self._kb = keyboard
        except ImportError as exc:
            raise ImportError(
                "Global hotkeys require the 'keyboard' package.\n"
                "Install it with:  pip install keyboard"
            ) from exc
        self._registered: list[str] = []

    def register(self, shortcut: str) -> None:
        """
        Register a global hotkey.
        The shortcut string uses keyboard's syntax, e.g.
        "ctrl+shift+space", "alt+f1", "windows+r".
        """
        self._kb.add_hotkey(
            shortcut,
            lambda s=shortcut: self.triggered.emit(s)
        )
        self._registered.append(shortcut)
        print(f"[hotkeys] registered: {shortcut}")

    def unregister(self, shortcut: str) -> None:
        self._kb.remove_hotkey(shortcut)
        self._registered = [s for s in self._registered if s != shortcut]

    def unregister_all(self) -> None:
        self._kb.unhook_all_hotkeys()
        self._registered.clear()
