"""Session state: PowerPlay merit tallies and credit income, per game login.

Raw merits are stored per activity; CP is *not* persisted — it's derived at
display time from the current ratio settings (see formulas.py), so correcting
a ratio in Settings retroactively re-estimates CP for past sessions too.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from .formulas import ACTIVITIES
from .store import SessionStore


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_iso(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return time.mktime(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return None


def new_session(cmdr: str, power: Optional[str], credits_start: Optional[int]) -> Dict[str, Any]:
    now = _now_iso()
    return {
        "id": uuid.uuid4().hex,
        "cmdr": cmdr,
        "power": power,
        "started_at": now,
        "updated_at": now,
        "credits_start": credits_start,
        "credits_now": credits_start,
        "totals": {activity: 0 for activity in ACTIVITIES},
        "events": {activity: 0 for activity in ACTIVITIES},
    }


def add_merits(session: Dict[str, Any], activity: str, merits: int) -> None:
    session["totals"][activity] = session["totals"].get(activity, 0) + merits
    session["events"][activity] = session["events"].get(activity, 0) + 1
    session["updated_at"] = _now_iso()


def update_credits(session: Dict[str, Any], credits_now: Optional[int]) -> None:
    if credits_now is None:
        return
    if session.get("credits_start") is None:
        session["credits_start"] = credits_now
    session["credits_now"] = credits_now
    session["updated_at"] = _now_iso()


def update_power(session: Dict[str, Any], power: Optional[str]) -> None:
    if power and session.get("power") != power:
        session["power"] = power


def total_merits(session: Dict[str, Any]) -> int:
    return sum(session.get("totals", {}).values())


def credits_earned(session: Dict[str, Any]) -> Optional[int]:
    start = session.get("credits_start")
    now = session.get("credits_now")
    if start is None or now is None:
        return None
    return now - start


def duration_hours(session: Dict[str, Any]) -> float:
    started = _parse_iso(session.get("started_at"))
    updated = _parse_iso(session.get("updated_at"))
    if started is None or updated is None:
        return 0.0
    return max(0.0, updated - started) / 3600.0


def per_hour(amount: float, hours: float) -> float:
    if hours <= 0:
        return 0.0
    return amount / hours


class SessionManager:
    """Owns the live session plus loaded history, and persists on change."""

    def __init__(self, store: SessionStore) -> None:
        self._store = store
        self._history: List[Dict[str, Any]] = store.load()
        self.current: Dict[str, Any] = new_session(cmdr="", power=None, credits_start=None)

    @property
    def history(self) -> List[Dict[str, Any]]:
        return self._history

    def start_session(self, cmdr: str, power: Optional[str], credits_start: Optional[int]) -> None:
        if self.current.get("cmdr") or total_merits(self.current) > 0:
            self._history.append(self.current)
        self.current = new_session(cmdr, power, credits_start)
        self._persist()

    def record_merits(self, activity: str, merits: int) -> None:
        add_merits(self.current, activity, merits)
        self._persist()

    def record_credits(self, credits_now: Optional[int]) -> None:
        # Called on every journal event to keep the live rate accurate;
        # deliberately not persisted here to avoid a disk write per event.
        # flush() (on merit gains, prefs changes, and plugin_stop) covers it.
        update_credits(self.current, credits_now)

    def record_power(self, power: Optional[str]) -> None:
        update_power(self.current, power)

    def flush(self) -> None:
        self._persist()

    def _persist(self) -> None:
        self._store.save(self._history, self.current)
