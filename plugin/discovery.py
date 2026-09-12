"""Discovery: alerts when the system you just jumped into, or a body you just
scanned/mapped, has never been found by anyone before — drawn via
overlay.py, same shape as interdiction.py/landing.py.

Detection relies on fields the journal already carries, no extra scanning
required on the player's part:

1. System-level: the instant you jump into a system, the game auto-scans
   the arrival star and reports it as a "Scan" event with `ScanType`:
   "AutoScan" — this fires on its own, before you do anything. That event's
   `WasDiscovered` field is `False` when nobody has ever scanned this star
   before, which is the best available proxy for "nobody's been to this
   system" (there's no direct system-level flag in the journal). Detected
   via the presence of `StarType` on the Scan entry (only stars carry it).
2. Body-level (scan): every "Scan" event (star or planet, any `ScanType`)
   carries its own `WasDiscovered` — `False` means you're the first to
   scan it.
3. Body-level (mapped): the Detailed Surface Scanner's "SAAScanComplete"
   event, unlike "Scan", carries no discovery flag of its own — it only
   fires once you've actually completed the DSS probe pattern. Whether that
   makes you first-to-map is decided by the *previous* Scan event's own
   `WasMapped` field for the same body (`False` there means nobody had
   mapped it as of that scan) — cached per body name and consulted when
   the matching SAAScanComplete arrives. Cleared on system change so a
   stale cache entry can never leak into the next system.

Deliberately silent on the (overwhelmingly common, especially anywhere
near inhabited/PowerPlay space) "already discovered" case — this is meant
to read as a celebratory alert for the genuinely new case, not a running
status readout that would clutter the overlay on every single jump/scan.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from config import appname, config

from .overlay import OverlayClient

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

_CFG_ENABLED = "edppmt_discovery_enabled"
DEFAULT_ENABLED = False

# How long each alert stays up before auto-clearing. System and body alerts
# clear independently (see DiscoveryTracker) since a body discovery can
# easily follow a system discovery within seconds while exploring.
SYSTEM_CLEAR_S = 12.0
BODY_CLEAR_S = 8.0

# Journal events this tracker needs to see — load.py forwards these
# unconditionally (cheap to run regardless of whether the feature is
# enabled), same pattern as interdiction._INTERDICTION_EVENTS.
DISCOVERY_EVENTS = ("Scan", "SAAScanComplete")


@dataclass
class DiscoveryConfig:
    enabled: bool = DEFAULT_ENABLED


def load_config() -> DiscoveryConfig:
    return DiscoveryConfig(enabled=config.get_bool(_CFG_ENABLED, default=DEFAULT_ENABLED))


def save_config(cfg: DiscoveryConfig) -> None:
    config.set(_CFG_ENABLED, cfg.enabled)


@dataclass
class DiscoverySnapshot:
    system_visible: bool = False
    system_name: Optional[str] = None
    body_visible: bool = False
    body_name: Optional[str] = None
    body_action: Optional[str] = None  # "scanned" | "mapped"


class DiscoveryTracker:
    """Combines system-entry tracking (handle_system_change, called from
    load.py's journal_entry alongside _current_system) with Scan/
    SAAScanComplete journal events (handle_event) to decide when to fire a
    "first discovery" alert. `on_change` is called with a fresh
    DiscoverySnapshot every time either alert slot changes — load.py's
    listener decides whether to actually draw it (gated on
    load_config().enabled)."""

    def __init__(self, on_change) -> None:
        self._on_change = on_change
        self._system_name: Optional[str] = None
        self._star_evaluated = False
        self._mapped_cache: Dict[str, bool] = {}

        self._system_visible = False
        self._system_display_name: Optional[str] = None
        self._body_visible = False
        self._body_name: Optional[str] = None
        self._body_action: Optional[str] = None

        self._system_timer: Optional[threading.Timer] = None
        self._body_timer: Optional[threading.Timer] = None
        self._test_timer: Optional[threading.Timer] = None

    def get_snapshot(self) -> DiscoverySnapshot:
        return DiscoverySnapshot(
            system_visible=self._system_visible,
            system_name=self._system_display_name,
            body_visible=self._body_visible,
            body_name=self._body_name,
            body_action=self._body_action,
        )

    def trigger_test(self) -> None:
        """Settings tab's "Test Discovery" button — fires both alert slots
        at once through the same snapshot the live path renders, so the
        whole pipeline (tracker -> overlay client -> EDMCOverlay) can be
        checked without waiting for a real, genuinely-undiscovered system."""
        self._clear_test_timer()
        self._show_system("Test System")
        self._show_body("Test Body 1 c", "scanned")

        def _map() -> None:
            self._test_timer = None
            self._show_body("Test Body 1 c", "mapped")

        self._test_timer = threading.Timer(2.0, _map)
        self._test_timer.daemon = True
        self._test_timer.start()

    def handle_system_change(self, system: Optional[str]) -> None:
        """Called from load.py's journal_entry whenever the current system
        name is (re)established (FSDJump/Location/StartUp-recovered) —
        resets per-system discovery state so a body cached from the
        previous system can never be mistaken for one in this system, and
        so the arrival star's AutoScan gets evaluated fresh here."""
        if system and system != self._system_name:
            self._system_name = system
            self._star_evaluated = False
            self._mapped_cache = {}

    def handle_event(self, entry: Mapping[str, Any]) -> None:
        event = entry.get("event")

        if event == "Scan":
            body_name = entry.get("BodyName")
            if not body_name:
                return
            was_discovered = entry.get("WasDiscovered")
            was_mapped = entry.get("WasMapped")
            if isinstance(was_mapped, bool):
                self._mapped_cache[body_name] = was_mapped

            # Only stars carry "StarType" — this is the arrival star's
            # automatic post-jump scan, the earliest signal for "has
            # anyone ever been to this system before".
            if "StarType" in entry and not self._star_evaluated:
                self._star_evaluated = True
                if was_discovered is False:
                    self._show_system(self._system_name or body_name)

            if was_discovered is False:
                self._show_body(body_name, "scanned")
            return

        if event == "SAAScanComplete":
            body_name = entry.get("BodyName")
            if not body_name:
                return
            # Consult (not overwrite with anything else) the flag the
            # body's own Scan event carried — SAAScanComplete itself has no
            # discovery info. Once evaluated, mark it mapped so replaying
            # the same completion (shouldn't normally happen) can't
            # re-announce it.
            was_mapped = self._mapped_cache.get(body_name)
            self._mapped_cache[body_name] = True
            if was_mapped is False:
                self._show_body(body_name, "mapped")
            return

    def _show_system(self, name: str) -> None:
        self._system_visible = True
        self._system_display_name = name
        self._schedule_system_clear(SYSTEM_CLEAR_S)
        self._emit_changed()

    def _show_body(self, name: str, action: str) -> None:
        self._body_visible = True
        self._body_name = name
        self._body_action = action
        self._schedule_body_clear(BODY_CLEAR_S)
        self._emit_changed()

    def _schedule_system_clear(self, seconds: float) -> None:
        if self._system_timer is not None:
            self._system_timer.cancel()

        def _clear() -> None:
            self._system_visible = False
            self._system_display_name = None
            self._system_timer = None
            self._emit_changed()

        self._system_timer = threading.Timer(seconds, _clear)
        self._system_timer.daemon = True
        self._system_timer.start()

    def _schedule_body_clear(self, seconds: float) -> None:
        if self._body_timer is not None:
            self._body_timer.cancel()

        def _clear() -> None:
            self._body_visible = False
            self._body_name = None
            self._body_action = None
            self._body_timer = None
            self._emit_changed()

        self._body_timer = threading.Timer(seconds, _clear)
        self._body_timer.daemon = True
        self._body_timer.start()

    def _clear_test_timer(self) -> None:
        if self._test_timer is not None:
            self._test_timer.cancel()
            self._test_timer = None

    def _emit_changed(self) -> None:
        self._on_change(self.get_snapshot())


# --- Rendering (overlay.py's OverlayClient is generic; this is the one
# place that knows what a discovery alert should look like) ---------------

_SYSTEM_CARD_ID = "edppmt_discovery_system_card"
_SYSTEM_TITLE_ID = "edppmt_discovery_system_title"
_SYSTEM_NAME_ID = "edppmt_discovery_system_name"
_BODY_CARD_ID = "edppmt_discovery_body_card"
_BODY_TITLE_ID = "edppmt_discovery_body_title"
_BODY_NAME_ID = "edppmt_discovery_body_name"

# Fixed placement, upper-right — clear of Interdiction Warning's upper-
# center card (X=650) and Landing's lower-left card (Y=650+), so both can
# be on at once without overlapping. Not user-configurable, same reasoning
# as interdiction.py's own fixed placement.
_X = 1320
_Y_SYSTEM_TITLE = 100
_Y_SYSTEM_NAME = 130
_Y_BODY_TITLE = 180
_Y_BODY_NAME = 210

# Gold/amber reads as an achievement/celebration color (matches the game's
# own "first discovered" Universal Cartographics bonus styling) rather than
# a warning color like interdiction's red — this is good news, not danger.
_SYSTEM_BORDER = "#f59e0b"  # amber-500
_SYSTEM_FILL = "#4a2f0a0a"  # amber-950 at ~95% alpha
_SYSTEM_TITLE_COLOR = "#fbbf24"  # amber-400
_SYSTEM_NAME_COLOR = "white"

# Body alerts use a cyan/teal accent instead — visually distinct from the
# system card's amber so the two can't be misread as duplicates of the same
# alert when both are showing at once.
_BODY_BORDER = "#22d3ee"  # cyan-400
_BODY_FILL = "#0a3a4a0a"  # cyan-950 at ~95% alpha
_BODY_TITLE_COLOR = "#67e8f9"  # cyan-300
_BODY_NAME_COLOR = "white"

_SYSTEM_CARD_X = _X - 20
_SYSTEM_CARD_Y = _Y_SYSTEM_TITLE - 26
_CARD_W = 480
_SYSTEM_CARD_H = (_Y_SYSTEM_NAME + 30) - _SYSTEM_CARD_Y

_BODY_CARD_X = _X - 20
_BODY_CARD_Y = _Y_BODY_TITLE - 26
_BODY_CARD_H = (_Y_BODY_NAME + 30) - _BODY_CARD_Y

_BODY_ACTION_TEXT = {
    "scanned": "First scan of a new discovery!",
    "mapped": "First to map this body!",
}


def render(snapshot: DiscoverySnapshot, client: OverlayClient) -> None:
    """Draws (or clears) both alert slots. Raises on an OverlayClient
    failure (e.g. EDMCOverlay isn't running) rather than swallowing it here
    — load.py's live listener wraps this call and decides that's an
    expected, silent-fail state; the Settings "Test Discovery" button wraps
    its own call and surfaces it instead."""
    if snapshot.system_visible:
        client.send_shape(
            _SYSTEM_CARD_ID, "rect", _SYSTEM_BORDER, _SYSTEM_FILL,
            _SYSTEM_CARD_X, _SYSTEM_CARD_Y, _CARD_W, _SYSTEM_CARD_H, ttl=30, thickness=2,
        )
        client.send_message(
            _SYSTEM_TITLE_ID, "NEW SYSTEM DISCOVERY", _SYSTEM_TITLE_COLOR, _X, _Y_SYSTEM_TITLE, ttl=30, size="large",
        )
        client.send_message(
            _SYSTEM_NAME_ID, snapshot.system_name or "Unknown system", _SYSTEM_NAME_COLOR, _X, _Y_SYSTEM_NAME, ttl=30,
        )
    else:
        _clear_system(client)

    if snapshot.body_visible:
        title = _BODY_ACTION_TEXT.get(snapshot.body_action or "", "New discovery!")
        client.send_shape(
            _BODY_CARD_ID, "rect", _BODY_BORDER, _BODY_FILL,
            _BODY_CARD_X, _BODY_CARD_Y, _CARD_W, _BODY_CARD_H, ttl=30, thickness=2,
        )
        client.send_message(_BODY_TITLE_ID, title, _BODY_TITLE_COLOR, _X, _Y_BODY_TITLE, ttl=30, size="large")
        client.send_message(
            _BODY_NAME_ID, snapshot.body_name or "Unknown body", _BODY_NAME_COLOR, _X, _Y_BODY_NAME, ttl=30,
        )
    else:
        _clear_body(client)


def clear(client: OverlayClient) -> None:
    """Clears both alert slots unconditionally — used when the feature is
    turned off, so a still-visible alert doesn't linger until its own ttl
    expires."""
    _clear_system(client)
    _clear_body(client)


def _clear_system(client: OverlayClient) -> None:
    # Parked at the card's own position, not (0, 0) — see interdiction.py's
    # `_clear` for the full writeup of why a zero-size rect at literal
    # screen-origin would drag EDMCModernOverlay's Plugin Group bounding
    # box toward the corner.
    client.send_shape(_SYSTEM_CARD_ID, "rect", "", "", _SYSTEM_CARD_X, _SYSTEM_CARD_Y, 0, 0, ttl=1)
    client.send_message(_SYSTEM_TITLE_ID, "", "white", _X, _Y_SYSTEM_TITLE, ttl=1)
    client.send_message(_SYSTEM_NAME_ID, "", "white", _X, _Y_SYSTEM_NAME, ttl=1)


def _clear_body(client: OverlayClient) -> None:
    client.send_shape(_BODY_CARD_ID, "rect", "", "", _BODY_CARD_X, _BODY_CARD_Y, 0, 0, ttl=1)
    client.send_message(_BODY_TITLE_ID, "", "white", _X, _Y_BODY_TITLE, ttl=1)
    client.send_message(_BODY_NAME_ID, "", "white", _X, _Y_BODY_NAME, ttl=1)
