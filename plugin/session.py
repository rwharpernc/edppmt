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


def new_session(
    cmdr: str,
    power: Optional[str],
    credits_start: Optional[int],
    journal_file: Optional[str] = None,
) -> Dict[str, Any]:
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
        # Same totals/events, broken out per system name — lets the UI show
        # "what am I earning here" as well as the session-wide sum, and keeps
        # an accurate running count per system across however many times the
        # commander jumps back and forth to it within the session. Keyed by
        # system name rather than SystemAddress: it's what every call site
        # already has on hand (EDMC's live-tracked current-system name), and
        # two systems sharing a name isn't a real-world case worth the extra
        # lookup complexity. See system_totals/visited_systems below.
        "by_system": {},
        # The journal file this session is tied to — lets us recognise a
        # logout to the main menu and back (same file, new "LoadGame") or an
        # EDMC restart mid-game (same file, no replay) as a continuation of
        # this session rather than a new one. See SessionManager.sync_session.
        "journal_file": journal_file,
    }


def _system_bucket(session: Dict[str, Any], system: str) -> Dict[str, Any]:
    """Gets (creating if needed) the per-system totals bucket for `system`,
    so revisiting a system later in the session keeps adding to the same
    running count instead of starting over."""
    by_system = session.setdefault("by_system", {})
    bucket = by_system.get(system)
    if bucket is None:
        bucket = {
            "totals": {activity: 0 for activity in ACTIVITIES},
            "events": {activity: 0 for activity in ACTIVITIES},
            "last_seen_at": _now_iso(),
        }
        by_system[system] = bucket
    return bucket


def add_merits(session: Dict[str, Any], activity: str, merits: int, system: Optional[str] = None) -> None:
    session["totals"][activity] = session["totals"].get(activity, 0) + merits
    session["events"][activity] = session["events"].get(activity, 0) + 1
    session["updated_at"] = _now_iso()

    if system:
        bucket = _system_bucket(session, system)
        bucket["totals"][activity] = bucket["totals"].get(activity, 0) + merits
        bucket["events"][activity] = bucket["events"].get(activity, 0) + 1
        bucket["last_seen_at"] = session["updated_at"]


def system_totals(session: Dict[str, Any], system: str) -> Dict[str, int]:
    """Per-activity merit totals earned in `system` this session (empty if
    none earned there yet)."""
    return session.get("by_system", {}).get(system, {}).get("totals", {})


def system_merit_total(session: Dict[str, Any], system: str) -> int:
    return sum(system_totals(session, system).values())


def visited_systems(session: Dict[str, Any]) -> List[str]:
    """Systems with recorded merit activity this session, most-recently-active first."""
    by_system = session.get("by_system", {})
    return sorted(by_system, key=lambda name: by_system[name].get("last_seen_at", ""), reverse=True)


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
        history, current = store.load()
        self._history = history
        self.current: Dict[str, Any] = (
            current if current is not None else new_session(cmdr="", power=None, credits_start=None)
        )

    @property
    def history(self) -> List[Dict[str, Any]]:
        return self._history

    def start_session(
        self,
        cmdr: str,
        power: Optional[str],
        credits_start: Optional[int],
        journal_file: Optional[str] = None,
    ) -> None:
        if self.current.get("cmdr") or total_merits(self.current) > 0:
            self._history.append(self.current)
        self.current = new_session(cmdr, power, credits_start, journal_file)
        self._persist()

    def sync_session(
        self,
        cmdr: str,
        power: Optional[str],
        credits_start: Optional[int],
        journal_file: Optional[str],
    ) -> bool:
        """Reconcile the live session against the journal file EDMC is
        currently tracking (or None if the game isn't running).

        Called from both "LoadGame" (a genuinely new login — a fresh game
        launch, or a logout to the main menu and back within the same
        client) and the synthesized "StartUp" EDMC sends when it (re)starts
        with the game already running (no journal replay happens in that
        case, so the persisted session just needs to be picked back up).
        Either way, a journal file matching the one already being tracked
        means it's the same continuous session — keep it instead of
        starting a new one. A different (or missing) journal file means the
        previous session is over.

        Returns True if the existing session was continued, False if a new
        one was started — callers use this to decide whether pledge state
        needs re-resolving (see load._dispatch's "LoadGame" handler): a menu
        relog is a "LoadGame" too, but Frontier only re-sends "Powerplay" on
        the *first* login of a client launch, not on every relog, so
        resetting pledge tracking on a same-journal LoadGame would throw
        away a still-correct pledge with nothing left to reconfirm it.

        A same-journal login is only a continuation if it's the *same*
        commander, too: Frontier keeps writing to one journal file across a
        logout-to-menu-and-back even when a different commander is picked at
        the login screen, so matching on journal file alone would carry the
        previous commander's merit totals over onto the new one.
        """
        same_journal = bool(journal_file) and self.current.get("journal_file") == journal_file
        current_cmdr = self.current.get("cmdr")
        same_cmdr = not current_cmdr or not cmdr or current_cmdr == cmdr
        if same_journal and same_cmdr:
            if cmdr:
                self.current["cmdr"] = cmdr
            self.current["updated_at"] = _now_iso()
            self._persist()
            return True
        self.start_session(cmdr, power, credits_start, journal_file)
        return False

    def record_merits(self, activity: str, merits: int, system: Optional[str] = None) -> None:
        add_merits(self.current, activity, merits, system)
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
