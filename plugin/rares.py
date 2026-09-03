"""Rare-goods locator: nearest rare commodities to the current system.

Rare-good origins never move, so the dataset (`rare_goods.json`, compiled by
this plugin's own author, coordinates baked in via a one-time EDSM lookup —
see docs/ATTRIBUTIONS.md) is bundled as a static file rather than queried
live, consistent with EDPPMT's passive/offline-first design (see README
"How it works").
"""

from __future__ import annotations

import json
import logging
import math
import os
from typing import Any, Dict, List, Optional, Tuple

from config import appname

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

_DATA_PATH = os.path.join(os.path.dirname(__file__), "rare_goods.json")

_cache: Optional[List[Dict[str, Any]]] = None


def _load() -> List[Dict[str, Any]]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(_DATA_PATH, "r", encoding="utf-8") as fh:
            _cache = json.load(fh)
    except (OSError, ValueError):
        logger.warning("Could not read %s", _DATA_PATH, exc_info=True)
        _cache = []
    return _cache


def _distance_ly(a: Tuple[float, float, float], b: Dict[str, float]) -> float:
    return math.sqrt((a[0] - b["x"]) ** 2 + (a[1] - b["y"]) ** 2 + (a[2] - b["z"]) ** 2)


def nearest(current_coords: Tuple[float, float, float], limit: int = 10) -> List[Dict[str, Any]]:
    """The `limit` nearest rare goods to `current_coords` (a StarPos-shaped
    (x, y, z) tuple), each entry annotated with `distance_ly`, nearest first."""
    entries = _load()
    annotated = [
        {**entry, "distance_ly": _distance_ly(current_coords, entry["coords"])} for entry in entries
    ]
    annotated.sort(key=lambda e: e["distance_ly"])
    return annotated[:limit]
