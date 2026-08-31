"""Live lookup of a system's current PowerPlay controlling Power, via
Spansh's public system API (https://spansh.co.uk/api/system/<id64>) — the
only community data source found that tracks current PowerPlay control for
arbitrary systems (EDSM's system API does not expose it).

Unlike the rest of the Rares Finder, this makes a network call at refresh
time rather than baking data in, since control changes (weekly PowerPlay
cycles) where a rare good's origin system never moves. Results are cached
for the life of the process — id64 -> controlling Power name, or None for a
resolved-but-unclaimed system — since a redraw shouldn't refetch a system
it already has an answer for.

Runs lookups in a background thread pool and never touches Tkinter
directly; callers marshal results onto the main thread themselves, same
pattern as update.py.
"""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, Optional, Tuple

import requests
from config import appname

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

REQUEST_TIMEOUT_S = 8
MAX_WORKERS = 5
HEADERS = {"User-Agent": "EDPPMT-rares-window"}

_cache_lock = threading.Lock()
_cache: dict = {}


def cached(id64: int) -> Tuple[bool, Optional[str]]:
    """(True, power) if `id64` has already been resolved this run (`power`
    is None for a resolved-but-unclaimed system), else (False, None)."""
    with _cache_lock:
        if id64 in _cache:
            return True, _cache[id64]
    return False, None


def _fetch_one(id64: int) -> Optional[str]:
    power: Optional[str] = None
    try:
        resp = requests.get(
            f"https://spansh.co.uk/api/system/{id64}", headers=HEADERS, timeout=REQUEST_TIMEOUT_S,
        )
        resp.raise_for_status()
        power = resp.json().get("record", {}).get("controlling_power") or None
    except Exception:
        logger.debug("Spansh controlling-power lookup failed for id64=%s", id64, exc_info=True)

    with _cache_lock:
        _cache[id64] = power
    return power


def fetch_missing(id64s: Iterable[int], on_result: Callable[[int, Optional[str]], None]) -> None:
    """Looks up the controlling Power for each of `id64s` not already
    cached, calling `on_result(id64, power_or_none)` from a background
    thread as each completes — not necessarily in order. Does nothing (no
    thread spawned) if every id64 is already cached. Callers must marshal
    onto the Tk main thread themselves before touching widgets."""
    with _cache_lock:
        pending = [id64 for id64 in id64s if id64 not in _cache]
    if not pending:
        return

    def worker() -> None:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch_one, id64): id64 for id64 in pending}
            for future in as_completed(futures):
                on_result(futures[future], future.result())

    threading.Thread(target=worker, name="EDPPMT-rares-power-lookup", daemon=True).start()
