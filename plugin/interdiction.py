"""Interdiction Warning: detects an interdiction starting/resolving and
draws it via overlay.py. Ported from the author's sibling project EDDDT
(`src/main/interdiction/tracker.ts` + `src/shared/interdiction.ts`) — same
detection state machine, re-implemented in Python with no Tk import (pure
detection/rendering logic, like formulas.py/session.py).

Detection combines three signals, earliest-available first:
1. Status.json's "Being Interdicted" flag (Flags bit 23) - flips true the
   instant the interdiction minigame starts, well before it resolves.
   Delivered via EDMC's dashboard_entry callback - see load.py.
2. "ReceiveText" NPC chat taunts during the encounter - the only
   pre-resolution identity source (Status.json's flag carries no identity).
3. The authoritative "Interdicted"/"EscapeInterdiction" journal events once
   it resolves - these also carry a "Power" field when the interdictor is
   affiliated with one, which EDDDT's UI doesn't surface but is natural,
   already-parsed context for a PowerPlay-focused plugin.

Ephemeral by design - no persistence, mirrors EDDDT's "cheap to rebuild"
philosophy for this kind of live-only state.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

from config import appname, config

from .overlay import OverlayClient

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

_CFG_ENABLED = "edppmt_interdiction_enabled"
DEFAULT_ENABLED = False

# How long the overlay keeps showing a resolved outcome (escaped/pulled-out/
# submitted) before auto-clearing.
RESOLVED_CLEAR_S = 8.0
# Safety-net clear if Status.json's flag drops without a resolving journal
# event ever arriving (e.g. the encounter fizzles out with nothing logged).
GRACE_CLEAR_S = 3.0

# Status.json Flags bit 23 - set the moment an interdiction attempt starts
# (before it resolves). Confirmed against EDCD/EDMarketConnector's
# edmc_data.py: FlagsBeingInterdicted = 1 << 23.
_BEING_INTERDICTED_BIT = 1 << 23

# Ported verbatim from EDDDT's shared/interdiction.ts
# CHAT_THREAT_PATTERNS/isInterdictionMessage - itself ported from
# ED-obs-app's lib/cache.js. There it styles NPC chat lines that look like
# an interdiction taunt; here it's the earliest way to guess who's
# interdicting before the resolving journal event arrives.
CHAT_THREAT_PATTERNS = (
    "interdict", "interdiction", "drop cargo", "drop your cargo", "yield", "hand over", "open fire",
    "pirate", "bounty hunter", "$pirate", "$bounty", "you're mine", "no escape", "prepare for death",
    "give me", "dump that cargo", "start dumping", "seconds before", "get 'em", "end you",
    # Pirates (cargo-based)
    "tasty cargo", "big haul", "huge haul", "cargo hold", "what you're carrying", "what do you carry",
    "prepare yourself",
    # Assassins / mission NPCs
    "rumors were true", "hard person to find", "glad I found you", "your mine now", "boil you up",
    # System authority (police)
    "security forces scanning", "routine scan", "throttle down", "submit for a",
    # Hostile faction
    "messed with the wrong person", "eagle is in the nest",
)


def is_interdiction_message(text: Optional[str]) -> bool:
    if not text:
        return False
    lower = text.lower()
    return any(pattern in lower for pattern in CHAT_THREAT_PATTERNS)


@dataclass
class InterdictionConfig:
    enabled: bool = DEFAULT_ENABLED


def load_config() -> InterdictionConfig:
    return InterdictionConfig(enabled=config.get_bool(_CFG_ENABLED, default=DEFAULT_ENABLED))


def save_config(cfg: InterdictionConfig) -> None:
    config.set(_CFG_ENABLED, cfg.enabled)


@dataclass
class InterdictionSnapshot:
    active: bool = False
    interdictor_name: Optional[str] = None
    is_player: Optional[bool] = None
    is_thargoid: Optional[bool] = None
    power: Optional[str] = None
    resolution: Optional[str] = None  # "escaped" | "pulled-out" | "submitted" | None


class InterdictionTracker:
    """Combines Status.json's live flag (see handle_dashboard_flags) with
    journal events (see handle_event) for identity. `on_change` is called
    with a fresh InterdictionSnapshot every time something changes -
    load.py's listener decides whether to actually draw it (gated on
    load_config().enabled)."""

    def __init__(self, on_change: Callable[[InterdictionSnapshot], None]) -> None:
        self._on_change = on_change
        self._active = False
        self._interdictor_name: Optional[str] = None
        self._is_player: Optional[bool] = None
        self._is_thargoid: Optional[bool] = None
        self._power: Optional[str] = None
        self._resolution: Optional[str] = None
        self._was_being_interdicted = False
        self._clear_timer: Optional[threading.Timer] = None
        self._test_timer: Optional[threading.Timer] = None

    def get_snapshot(self) -> InterdictionSnapshot:
        return InterdictionSnapshot(
            active=self._active,
            interdictor_name=self._interdictor_name,
            is_player=self._is_player,
            is_thargoid=self._is_thargoid,
            power=self._power,
            resolution=self._resolution,
        )

    def trigger_test(self) -> None:
        """Settings tab's "Test Warning" button — simulates a full,
        real interdiction lifecycle (active -> resolved -> auto-clear)
        through the same snapshot the live path renders, so the whole
        pipeline (tracker -> overlay client -> EDMCOverlay) can be checked
        without waiting for a real interdiction."""
        self._clear_test_timer()
        self._clear_scheduled_clear()
        self._active = True
        self._interdictor_name = "CMDR Test Hostile"
        self._is_player = True
        self._is_thargoid = False
        self._power = None
        self._resolution = None
        self._emit_changed()

        def _resolve() -> None:
            self._test_timer = None
            self._resolution = "escaped"
            self._schedule_clear(RESOLVED_CLEAR_S)
            self._emit_changed()

        self._test_timer = threading.Timer(4.0, _resolve)
        self._test_timer.daemon = True
        self._test_timer.start()

    def handle_dashboard_flags(self, flags: int) -> None:
        being_interdicted = bool(flags & _BEING_INTERDICTED_BIT)
        was_being_interdicted = self._was_being_interdicted
        self._was_being_interdicted = being_interdicted

        if not was_being_interdicted and being_interdicted:
            self._clear_test_timer()
            self._clear_scheduled_clear()
            self._active = True
            self._interdictor_name = None
            self._is_player = None
            self._is_thargoid = None
            self._power = None
            self._resolution = None
            self._emit_changed()
            return

        if was_being_interdicted and not being_interdicted and self._active and not self._resolution:
            self._schedule_clear(GRACE_CLEAR_S)

    def handle_event(self, entry: Mapping[str, Any]) -> None:
        event = entry.get("event")

        if event == "ReceiveText":
            if self._active and not self._interdictor_name:
                message = entry.get("Message_Localised") or entry.get("Message")
                if is_interdiction_message(message):
                    sender = entry.get("From_Localised") or entry.get("From")
                    if sender:
                        self._interdictor_name = str(sender)
                        self._emit_changed()
            return

        if event == "Interdicted":
            self._clear_test_timer()
            self._active = True
            self._resolution = "submitted" if entry.get("Submitted") is True else "pulled-out"
            self._apply_interdictor_fields(entry)
            self._schedule_clear(RESOLVED_CLEAR_S)
            self._emit_changed()
            return

        if event == "EscapeInterdiction":
            self._clear_test_timer()
            self._active = True
            self._resolution = "escaped"
            self._apply_interdictor_fields(entry)
            self._schedule_clear(RESOLVED_CLEAR_S)
            self._emit_changed()

    def _apply_interdictor_fields(self, raw: Mapping[str, Any]) -> None:
        name = raw.get("Interdictor")
        if name:
            self._interdictor_name = str(name)
        if isinstance(raw.get("IsPlayer"), bool):
            self._is_player = raw["IsPlayer"]
        if isinstance(raw.get("IsThargoid"), bool):
            self._is_thargoid = raw["IsThargoid"]
        power = raw.get("Power")
        if power:
            self._power = str(power)

    def _schedule_clear(self, seconds: float) -> None:
        self._clear_scheduled_clear()

        def _clear() -> None:
            self._active = False
            self._interdictor_name = None
            self._is_player = None
            self._is_thargoid = None
            self._power = None
            self._resolution = None
            self._clear_timer = None
            self._emit_changed()

        self._clear_timer = threading.Timer(seconds, _clear)
        self._clear_timer.daemon = True
        self._clear_timer.start()

    def _clear_scheduled_clear(self) -> None:
        if self._clear_timer is not None:
            self._clear_timer.cancel()
            self._clear_timer = None

    def _clear_test_timer(self) -> None:
        if self._test_timer is not None:
            self._test_timer.cancel()
            self._test_timer = None

    def _emit_changed(self) -> None:
        self._on_change(self.get_snapshot())


# --- Rendering (overlay.py's OverlayClient is generic; this is the one
# place that knows what an interdiction warning should look like) ---------

_TITLE_ID = "edppmt_interdiction_title"
_WHO_ID = "edppmt_interdiction_who"
_RESOLUTION_ID = "edppmt_interdiction_resolution"

# Fixed placement (not user-configurable - EDMCOverlay has no "centered"
# primitive, and this keeps the Settings tab simple). Chosen to sit in the
# upper-center of a 1920x1080-ish HUD without covering the ship's own
# instruments.
_X = 650
_Y_TITLE = 100
_Y_WHO = 130
_Y_RESOLUTION = 160

_RESOLUTION_TEXT = {
    "escaped": ("Escaped!", "green"),
    "pulled-out": ("Pulled from supercruise", "red"),
    "submitted": ("Submitted to interdiction", "yellow"),
}


def render(snapshot: InterdictionSnapshot, client: OverlayClient) -> None:
    """Draws (or clears) the interdiction warning. Raises on an
    OverlayClient failure (e.g. EDMCOverlay isn't running) rather than
    swallowing it here - load.py's live listener wraps this call and
    decides that's an expected, silent-fail state; the Settings "Test
    Warning" button wraps its own call and surfaces it instead."""
    if not snapshot.active:
        _clear(client)
        return

    origin_tag = "Thargoid" if snapshot.is_thargoid else "Commander" if snapshot.is_player else None
    who = f"Interdictor: {snapshot.interdictor_name or 'Unknown'}"
    if origin_tag:
        who += f" ({origin_tag})"
    if snapshot.power:
        who += f" — Power: {snapshot.power}"

    client.send_message(_TITLE_ID, "⚠ INTERDICTION WARNING ⚠", "red", _X, _Y_TITLE, ttl=30, size="large")
    client.send_message(_WHO_ID, who, "red", _X, _Y_WHO, ttl=30)

    if snapshot.resolution:
        text, color = _RESOLUTION_TEXT.get(snapshot.resolution, (snapshot.resolution, "white"))
        client.send_message(_RESOLUTION_ID, text, color, _X, _Y_RESOLUTION, ttl=int(RESOLVED_CLEAR_S) + 1)
    else:
        client.send_message(_RESOLUTION_ID, "", "white", _X, _Y_RESOLUTION, ttl=1)


def _clear(client: OverlayClient) -> None:
    for msg_id, y in ((_TITLE_ID, _Y_TITLE), (_WHO_ID, _Y_WHO), (_RESOLUTION_ID, _Y_RESOLUTION)):
        client.send_message(msg_id, "", "white", _X, y, ttl=1)
