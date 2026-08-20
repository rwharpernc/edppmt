"""JSON persistence for session history, stored alongside the plugin itself."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from config import appname

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

FILENAME = "sessions.json"
# Keep history bounded so the file can't grow forever across years of play.
MAX_HISTORY = 200


class SessionStore:
    def __init__(self, plugin_dir: str) -> None:
        self._path = os.path.join(plugin_dir, FILENAME)

    def load(self) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Returns (history, current). current is None if there's nothing to resume."""
        if not os.path.exists(self._path):
            return [], None
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            logger.warning("Could not read %s; starting with empty history", self._path, exc_info=True)
            return [], None

        if isinstance(data, dict):
            history = data.get("history")
            current = data.get("current")
            return (
                history if isinstance(history, list) else [],
                current if isinstance(current, dict) else None,
            )
        if isinstance(data, list):
            # Legacy format (pre-1.2.0): a flat list with the live session as
            # the last entry, indistinguishable from history. There's no way
            # to tell them apart in hindsight, so keep it all as history
            # rather than guessing which entry was still in progress.
            return data, None
        return [], None

    def save(self, history: List[Dict[str, Any]], current: Dict[str, Any]) -> None:
        trimmed = history[-MAX_HISTORY:]
        payload = {"history": trimmed, "current": current}
        try:
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
        except OSError:
            logger.warning("Could not write %s", self._path, exc_info=True)
