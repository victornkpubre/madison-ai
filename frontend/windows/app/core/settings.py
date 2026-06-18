"""
application/core/settings.py
─────────────────────
Load and persist user preferences to config/settings.json.

The settings dict is intentionally plain so it's easy to extend —
just add a new key to _DEFAULTS and it will appear automatically.
"""
import json
import os
from typing import Any

_CONFIG_PATH = "config/settings.json"

_DEFAULTS: dict[str, Any] = {
    "pos":    [100, 100],       # [x, y] screen position of the floating button
    "theme":  "dark",           # "dark" | "light"
    "hotkey": "ctrl+shift+space",
    "agent_url": "",
}


def load_settings() -> dict:
    """
    Return merged settings: file values override defaults so newly added
    default keys appear even when an older config file is on disk.
    """
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return {**_DEFAULTS, **json.load(f)}
    except FileNotFoundError:
        return _DEFAULTS.copy()
    except json.JSONDecodeError as exc:
        print(f"[settings] corrupt JSON ({exc}), falling back to defaults")
        return _DEFAULTS.copy()


def save_settings(data: dict) -> None:
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
