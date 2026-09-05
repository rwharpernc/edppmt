"""Interdiction Warning: detects an interdiction starting/resolving and
draws it via overlay.py. Written by this plugin's own author against a
detection state machine from an earlier reference implementation of their
own, re-implemented in Python with no Tk import (pure detection/rendering
logic, like formulas.py/session.py).

Detection combines three signals - whichever actually arrives first wins,
since dashboard_entry (Status.json) and journal_entry (ReceiveText) are two
independent EDMC callbacks with no ordering guarantee between them for the
same real-world instant:
1. Status.json's "Being Interdicted" flag (Flags bit 23) - flips true the
   instant the interdiction minigame starts, well before it resolves, but
   only reaches this plugin on EDMC's next dashboard_entry call (Status.json
   is written roughly once a second, so this can lag the instant itself by
   up to ~1s). Delivered via EDMC's dashboard_entry callback - see load.py.
2. "ReceiveText" NPC chat taunts during the encounter, restricted to
   Channel == "npc" - an independent trigger in its own right (not just
   identity enrichment for signal 1), since a taunt line can arrive before
   the flag does. The channel gate matters: "starsystem" (system-wide chat)
   and "squadron" chat are other commanders casually typing words like
   "pirate" or "interdict" with no interdiction happening, and were a real
   source of false positives before this gate was added (confirmed against
   ~125k logged ReceiveText events - see handle_event). The only
   pre-resolution identity source either way (Status.json's flag carries no
   identity) - whichever of the two arrives second fills in whatever the
   first one didn't already have (see handle_dashboard_flags/handle_event's
   "don't stomp already-known identity" guards).
3. The authoritative "Interdicted"/"EscapeInterdiction" journal events once
   it resolves - these also carry a "Power" field when the interdictor is
   affiliated with one, which isn't surfaced by the reference
   implementation's own UI but is natural, already-parsed context for a
   PowerPlay-focused plugin.

Ephemeral by design - no persistence, favoring a "cheap to rebuild"
approach for this kind of live-only state.
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

# Ported verbatim from an earlier reference implementation of the author's
# own, itself originally from another prior project of theirs. There it
# styles NPC chat lines that look like an interdiction taunt; here it's
# the earliest way to guess who's interdicting before the resolving
# journal event arrives.
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
            # Don't stomp identity already learned from a ReceiveText taunt
            # that arrived first - dashboard_entry only fires on the next
            # Status.json write (up to ~1s later), so a chat-triggered
            # activation can easily beat the flag here.
            if not self._active:
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
            # Only the "npc" channel is hostile-ship dialogue - "starsystem"
            # (system-wide chat) and "squadron" chat are other commanders
            # casually typing words like "pirate" or "interdict" with no
            # interdiction happening at all (confirmed against ~125k logged
            # ReceiveText events: every CHAT_THREAT_PATTERNS match outside
            # "npc" was a false positive from human chat; every "npc" match
            # was a genuine taunt). Without this gate, that chat spuriously
            # flips the warning active.
            if entry.get("Channel") != "npc":
                return
            if not self._interdictor_name:
                message = entry.get("Message_Localised") or entry.get("Message")
                if is_interdiction_message(message):
                    sender = entry.get("From_Localised") or entry.get("From")
                    if sender:
                        # A matching taunt is itself a trigger, not just
                        # enrichment - it can arrive before Status.json's
                        # flag does (dashboard_entry only fires on the
                        # next Status.json write, up to ~1s later), so
                        # waiting for `self._active` first meant a
                        # same-tick taunt was silently dropped and the
                        # warning didn't appear until the flag caught up
                        # (or, worst case, not until the resolving event).
                        if not self._active:
                            self._clear_test_timer()
                            self._clear_scheduled_clear()
                            self._active = True
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

_CARD_ID = "edppmt_interdiction_card"
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

# This card's styling deliberately does NOT follow a switchable
# overlay-chrome palette - its red-alert styling is a safety signal, not
# chrome, and stays fixed regardless of theme. So unlike landing.py's card
# (which does follow the Elite Orange chrome palette), this card's
# border/fill never change with docking/resolution state - only the
# resolution line's own text color is semantic.
_CARD_BORDER = "#ef4444"  # red-500
_CARD_FILL = "#f2450a0a"  # red-950 at ~95% alpha
_TITLE_COLOR = "#f87171"  # red-400
_WHO_COLOR = "white"  # near-white, not red - the alert color is reserved
# for the title/resolution, so the identity line reads as plain
# information rather than more alarm text.

_CARD_X = _X - 20
_CARD_Y = _Y_TITLE - 26
_CARD_W = 600
_CARD_H = (_Y_RESOLUTION + 30) - _CARD_Y

_RESOLUTION_TEXT = {
    "escaped": ("Escaped!", "#34d399"),  # emerald-400
    "pulled-out": ("Pulled from supercruise", "#fca5a5"),  # red-300
    "submitted": ("Submitted to interdiction", "#fcd34d"),  # amber-300
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

    client.send_shape(_CARD_ID, "rect", _CARD_BORDER, _CARD_FILL, _CARD_X, _CARD_Y, _CARD_W, _CARD_H, ttl=30, thickness=2)
    client.send_message(_TITLE_ID, "INTERDICTION WARNING", _TITLE_COLOR, _X, _Y_TITLE, ttl=30, size="large")
    client.send_message(_WHO_ID, who, _WHO_COLOR, _X, _Y_WHO, ttl=30)

    if snapshot.resolution:
        text, resolution_color = _RESOLUTION_TEXT.get(snapshot.resolution, (snapshot.resolution, "white"))
        client.send_message(_RESOLUTION_ID, text, resolution_color, _X, _Y_RESOLUTION, ttl=int(RESOLVED_CLEAR_S) + 1)
    else:
        client.send_message(_RESOLUTION_ID, "", "white", _X, _Y_RESOLUTION, ttl=1)


def _clear(client: OverlayClient) -> None:
    # Parked at the card's own position, not (0, 0) - a zero-size rect at
    # literal screen-origin still pollutes this widget's registered
    # EDMCModernOverlay Plugin Group bounding box (confirmed against its
    # own `accumulate_group_bounds` source, which includes every live
    # payload's raw x/y regardless of size), dragging the group's
    # Fill-mode anchor/scale toward the corner for as long as this payload
    # stays live - see landing.py's `_clear_fleetcarrier_diagram` for the
    # full writeup of this bug, found while chasing the same symptom
    # (widget visibly drifting/jumping) there.
    client.send_shape(_CARD_ID, "rect", "", "", _CARD_X, _CARD_Y, 0, 0, ttl=1)
    for msg_id, y in ((_TITLE_ID, _Y_TITLE), (_WHO_ID, _Y_WHO), (_RESOLUTION_ID, _Y_RESOLUTION)):
        client.send_message(msg_id, "", "white", _X, y, ttl=1)
