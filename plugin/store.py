"""JSON persistence for session history, stored alongside the plugin itself."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from config import appname

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

FILENAME = "sessions.json"
# Keep history bounded so the file can't grow forever across years of play.
MAX_HISTORY = 200


class SessionStore:
    def __init__(self, plugin_dir: str) -> None:
        self._path = os.path.join(plugin_dir, FILENAME)

    def load(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self._path):
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            logger.warning("Could not read %s; starting with empty history", self._path, exc_info=True)
            return []
        return data if isinstance(data, list) else []

    def save(self, history: List[Dict[str, Any]], current: Dict[str, Any]) -> None:
        trimmed = history[-MAX_HISTORY:]
        payload = trimmed + [current]
        try:
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
        except OSError:
            logger.warning("Could not write %s", self._path, exc_info=True)
