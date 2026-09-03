"""Landing: docking status + pad-layout diagram, drawn via overlay.py.

Written by this plugin's own author, not ported from the third-party EDMC
LandingPad plugin (bgol/LandingPad, GPL-2.0). The one piece that does trace
back to bgol/LandingPad is the pad-index numbering itself (the 15-entry
shell/sector table, mirrored unchanged in this module's
`_PAD_LIST`/`_PAD_SECTORS`/`_DODECAGON` constants) - not because it was
copied from that plugin's source, but because that table is dictated by the
real game's actual station layout, not an author's creative choice: any
correct implementation reproduces the same numbers regardless of lineage.
Everything else here - the docking state machine, the status text
(title/station/pad number/denied reason, always shown even when no diagram
renders - see `render()`), the auto-hide timer, and the overlay rendering
itself (EDMCOverlay `"vect"`/`"rect"` messages, via `overlay.py` - written
independently against that protocol, not ported from bgol/LandingPad's own
EDMCOverlay client) - is this plugin's own original code, not
bgol/LandingPad's.

Purely journal-driven (DockingRequested/Granted/Denied/Timeout/Cancelled,
Docked/Undocked, plus FSDJump/CarrierJump/SupercruiseEntry to reset a
stale in-flight request) - no Status.json signal needed, unlike
interdiction.py. Ephemeral by design, same as interdiction.py - the pad
diagram is only ever meaningful for the commander's current approach/dock.
"""

from __future__ import annotations

import logging
import math
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, List, Mapping, Optional, Tuple

from config import appname, config

from .overlay import OverlayClient

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

_CFG_ENABLED = "edppmt_landing_enabled"
DEFAULT_ENABLED = False

# How long the overlay keeps showing "Docking Approved" info after touchdown
# before auto-hiding. An earlier reference implementation of the author's
# own used 15s here - shortened to 10s per the plugin author's own
# preference for this port.
HIDE_AFTER_LANDING_S = 10.0

# Rendering is event-driven (see render() in landing.py), and each graphic
# is sent with a ttl - EDMCOverlay/EDMCModernOverlay expire and remove it
# client-side once that ttl elapses with no resend. A docking approach from
# DockingGranted to actually touching down can easily take longer than that
# ttl (a large or busy station, or just a slow approach) with no further
# DOCKING_EVENTS firing in between to trigger a fresh render - the overlay
# would then blink out mid-approach, well before landing. This interval
# (kept comfortably under landing.py's _TTL=20s, with margin for render
# latency) re-emits the current snapshot on a repeating timer for as long
# as a docking request is outstanding, so the widget keeps refreshing
# itself even when nothing journal-driven happens in between.
_HEARTBEAT_INTERVAL_S = 12.0


@dataclass
class LandingConfig:
    enabled: bool = DEFAULT_ENABLED


def load_config() -> LandingConfig:
    return LandingConfig(enabled=config.get_bool(_CFG_ENABLED, default=DEFAULT_ENABLED))


def save_config(cfg: LandingConfig) -> None:
    config.set(_CFG_ENABLED, cfg.enabled)


# --- Docking/landing helpers -----------------------------------------

CarrierType = Optional[str]  # "FleetCarrier" | "SquadronCarrier" | "ColonisationShip" | None
PadDiagramType = Optional[str]  # "starport" | "fleetcarrier" | None

_COLONISATION_DEPOT_MARKET_IDS = {
    129032183, 129032439, 129032695, 129032951, 129033207, 129033463,
}
_COLONISATION_SHIP_STATION_KEY = re.compile(r"^\$EXT_PANEL_(?:Colonisation|Colonization)Ship", re.IGNORECASE)


def _raw_station_name(raw: Mapping[str, Any]) -> str:
    value = raw.get("StationName")
    return value.strip() if isinstance(value, str) else ""


def extract_landing_pad_from_event(raw: Mapping[str, Any]) -> Any:
    """Assigned pad from journal (DockingGranted/Docked). Field name has
    varied by game build."""
    for key in ("LandingPad", "landingpad", "LandingPadNumber", "PadNumber", "Pad", "AssignedLandingPad", "DockedPad"):
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return None


def infer_carrier_type_from_dock_event(raw: Mapping[str, Any]) -> CarrierType:
    """Fleet-style pad layout (16 pads): personal FC, squadron carrier, or
    system colonisation megaship. Colonisation ships are often journal-
    reported as SurfaceStation/Unknown and need the MarketID/symbolic-name
    backstop to be recognized at all."""
    station_type = raw.get("StationType")
    station_type = station_type.lower() if isinstance(station_type, str) else ""
    name = _raw_station_name(raw)
    market_id = raw.get("MarketID")
    market_id = market_id if isinstance(market_id, int) else None

    is_colonisation_depot = (
        (market_id is not None and market_id in _COLONISATION_DEPOT_MARKET_IDS)
        or bool(_COLONISATION_SHIP_STATION_KEY.match(name))
    )

    if station_type in ("surfacestation", "unknown"):
        return "ColonisationShip" if is_colonisation_depot else None

    dockable_carrier_like = any(
        token in station_type
        for token in ("fleetcarrier", "fleet carrier", "colonisationship", "colonizationship", "dockablemegaship")
    )
    if not dockable_carrier_like:
        return None

    if "colonisationship" in station_type or "colonizationship" in station_type or is_colonisation_depot:
        return "ColonisationShip"
    if len(name) == 4:
        return "SquadronCarrier"
    return "FleetCarrier"


_DOCKING_DENIED_REASONS = {
    "NoSpace": "All pads occupied",
    "TooLarge": "Ship too large",
    "Hostile": "Hostile to station",
    "Offences": "Criminal offences",
    "Distance": "Must be within 7.5km",
    "ActiveFighter": "Active SLF deployed",
    "RestrictedAccess": "Carrier access restricted",
    "JumpImminent": "Carrier jump imminent",
}


def docking_denied_reason_to_text(reason_id: Any) -> str:
    if not isinstance(reason_id, str) or not reason_id:
        return "Unknown"
    return _DOCKING_DENIED_REASONS.get(reason_id, reason_id)


_PANEL_MATCH = re.compile(r"^\$EXT_PANEL_(?:Colonisation|Colonization)Ship_(.+)$", re.IGNORECASE)
_PANEL_MATCH_GENERIC = re.compile(r"^\$EXT_PANEL_(.+)$", re.IGNORECASE)


def format_station_display_name(raw: Mapping[str, Any]) -> str:
    """Strips `$EXT_PANEL_...` symbolic station-name tokens down to a
    readable suffix."""
    localised = raw.get("StationName_Localised")
    if isinstance(localised, str) and localised.strip():
        return localised.strip()

    name = _raw_station_name(raw)
    if not name:
        return ""
    if not name.startswith("$"):
        return name

    match = _PANEL_MATCH.match(name) or _PANEL_MATCH_GENERIC.match(name)
    if match:
        suffix = match.group(1)
        suffix = re.sub(r";+$", "", suffix).replace("_", " ")
        return re.sub(r"\s+", " ", suffix).strip()
    return name


_STARPORT_TYPES = (
    "bernal", "coriolis", "orbis", "asteroidbase", "ocellus", "dodec",
    "starport", "planetary port", "asteroid base",
)
_FLEETCARRIER_TYPES = (
    "fleetcarrier", "fleet carrier", "colonisationship", "colonizationship",
    "colonisation ship", "colonization ship", "colonisation", "colonization",
    "dockablemegaship", "dockable megaship", "squadroncarrier", "squadron carrier",
)


def _diagram_type_from_string(value: str) -> PadDiagramType:
    lower = value.lower()
    if any(t in lower for t in _FLEETCARRIER_TYPES):
        return "fleetcarrier"
    if any(t in lower for t in _STARPORT_TYPES):
        return "starport"
    return None


def _diagram_type_from_carrier(carrier: CarrierType) -> PadDiagramType:
    if carrier in ("FleetCarrier", "SquadronCarrier", "ColonisationShip"):
        return "fleetcarrier"
    return None


@dataclass
class DockingRequest:
    status: str = ""  # "" | "pending" | "granted" | "denied"
    station: str = ""
    pad: Any = None
    denied_reason: str = ""
    station_type: str = ""
    carrier_type: CarrierType = None


def get_pad_diagram_type(docking: DockingRequest, last_station_type: str, last_carrier_type: CarrierType) -> PadDiagramType:
    """Which pad-diagram family applies. `last_station_type` is only
    consulted when the in-flight request has no station type of its own yet
    - once it does (e.g. an outpost, which has no diagram family), that's
    authoritative and must not fall through to a stale value left over from
    a previous, unrelated station."""
    if docking.station_type:
        return _diagram_type_from_string(docking.station_type) or _diagram_type_from_carrier(docking.carrier_type)
    if last_station_type:
        kind = _diagram_type_from_string(last_station_type)
        if kind:
            return kind
    return _diagram_type_from_carrier(docking.carrier_type or last_carrier_type)


def parse_numeric_pad(pad: Any) -> Optional[int]:
    """Journal may send pad as a number or a string ("12", "Pad 12")."""
    if pad is None or pad == "":
        return None
    if isinstance(pad, bool):
        return None
    if isinstance(pad, (int, float)):
        n = int(pad)
        return n if n > 0 else None
    match = re.search(r"(\d+)", str(pad).strip())
    if not match:
        return None
    n = int(match.group(1))
    return n if n > 0 else None


@dataclass
class LandingDisplayInfo:
    status_label: Optional[str] = None  # "Docking Requested" | "Docking Approved" | "Docking Denied" | None
    station: str = ""
    denied_reason: str = ""
    pad: Optional[int] = None
    diagram_type: PadDiagramType = None
    show_diagram: bool = False


def build_landing_display_info(
    docking: DockingRequest,
    docked: bool,
    last_assigned_pad: Any,
    last_station_type: str,
    last_carrier_type: CarrierType,
) -> LandingDisplayInfo:
    """One shared derivation: while docking.status is
    'granted'/'denied'/'pending' that drives the text;
    once it's cleared (post-touchdown), fall back to the persisted
    docked+last_assigned_pad."""
    diagram_type = get_pad_diagram_type(docking, last_station_type, last_carrier_type)

    status_label: Optional[str] = None
    if docking.status == "granted":
        status_label = "Docking Approved"
    elif docking.status == "denied":
        status_label = "Docking Denied"
    elif docking.status == "pending":
        status_label = "Docking Requested"
    elif docked and last_assigned_pad is not None:
        status_label = "Docking Approved"

    if docking.status == "granted":
        pad = parse_numeric_pad(docking.pad)
    elif status_label == "Docking Approved" and docked:
        pad = parse_numeric_pad(last_assigned_pad)
    else:
        pad = None

    show_diagram = diagram_type is not None and (docking.status in ("granted", "denied") or docked)

    return LandingDisplayInfo(
        status_label=status_label,
        station=docking.station,
        denied_reason=docking.denied_reason,
        pad=pad,
        diagram_type=diagram_type,
        show_diagram=show_diagram,
    )


# --- State machine ------------------------------------------------------

_RESET_DOCKING_EVENTS = ("FSDJump", "CarrierJump", "SupercruiseEntry")

DOCKING_EVENTS = (
    "DockingRequested", "DockingGranted", "DockingDenied", "DockingTimeout", "DockingCancelled",
    "Docked", "Undocked",
) + _RESET_DOCKING_EVENTS


@dataclass
class LandingSnapshot:
    docking: DockingRequest = field(default_factory=DockingRequest)
    docked: bool = False
    last_assigned_pad: Any = None
    last_station_type: str = ""
    last_carrier_type: CarrierType = None
    hidden_after_landing: bool = False


class LandingTracker:
    """Tracks docking state (`docking`, `docked`, `last_assigned_pad`,
    `last_station_type`, `last_carrier_type`), plus the overlay widget's
    own post-touchdown auto-hide timer."""

    def __init__(self, on_change: Callable[[LandingSnapshot], None]) -> None:
        self._on_change = on_change
        self._docking = DockingRequest()
        self._docked = False
        self._last_assigned_pad: Any = None
        self._last_station_type = ""
        self._last_carrier_type: CarrierType = None
        self._hide_timer: Optional[threading.Timer] = None
        self._hidden_after_landing = False
        self._heartbeat_timer: Optional[threading.Timer] = None

    def get_snapshot(self) -> LandingSnapshot:
        return LandingSnapshot(
            docking=self._docking,
            docked=self._docked,
            last_assigned_pad=self._last_assigned_pad,
            last_station_type=self._last_station_type,
            last_carrier_type=self._last_carrier_type,
            hidden_after_landing=self._hidden_after_landing,
        )

    def handle_event(self, entry: Mapping[str, Any]) -> None:
        event = entry.get("event")

        if event == "DockingRequested":
            self._docking = DockingRequest(
                status="pending", station=format_station_display_name(entry), pad=None, denied_reason="",
                station_type=self._docking.station_type, carrier_type=self._docking.carrier_type,
            )
        elif event == "DockingGranted":
            station_type = entry.get("StationType")
            station_type = station_type.lower() if isinstance(station_type, str) else ""
            self._docking = DockingRequest(
                status="granted", station=format_station_display_name(entry),
                pad=extract_landing_pad_from_event(entry), denied_reason="",
                station_type=station_type, carrier_type=infer_carrier_type_from_dock_event(entry),
            )
        elif event == "DockingDenied":
            self._docking.status = "denied"
            self._docking.station = format_station_display_name(entry)
            self._docking.pad = None
            self._docking.denied_reason = docking_denied_reason_to_text(entry.get("Reason"))
        elif event == "DockingTimeout":
            self._docking.status = "denied"
            self._docking.station = format_station_display_name(entry) or self._docking.station
            self._docking.denied_reason = "Timed out"
        elif event == "DockingCancelled":
            self._docking = DockingRequest()
        elif event == "Docked":
            self._clear_hide_timer()
            pad = extract_landing_pad_from_event(entry)
            if pad is None:
                pad = self._docking.pad
            event_station_type = entry.get("StationType")
            station_type = (
                event_station_type if isinstance(event_station_type, str)
                else (self._docking.station_type or self._last_station_type or "")
            ).lower()
            carrier_type = self._docking.carrier_type or infer_carrier_type_from_dock_event(entry)

            self._docking = DockingRequest()
            self._docked = True
            if pad is not None:
                self._last_assigned_pad = pad
            self._last_station_type = station_type
            self._last_carrier_type = carrier_type
            self._hidden_after_landing = False
            self._schedule_hide()
        elif event == "Undocked":
            self._docked = False
            self._clear_hide_timer()
            self._hidden_after_landing = False
        elif event in _RESET_DOCKING_EVENTS:
            self._docking = DockingRequest()
            self._docked = False
            self._clear_hide_timer()
            self._hidden_after_landing = False
        else:
            return

        # Keep the overlay refreshing itself (see _HEARTBEAT_INTERVAL_S)
        # for as long as a docking request is outstanding (pending/granted/
        # denied); once it's cleared - Docked (the hide timer takes over
        # instead), Cancelled, Undocked, or an approach-abandoning reset -
        # stop, so this timer never outlives the request it's refreshing.
        if self._docking.status:
            self._schedule_heartbeat()
        else:
            self._clear_heartbeat()

        self._emit_changed()

    def _schedule_heartbeat(self) -> None:
        self._clear_heartbeat()

        def _beat() -> None:
            self._heartbeat_timer = None
            if self._docking.status:
                self._emit_changed()
                self._schedule_heartbeat()

        self._heartbeat_timer = threading.Timer(_HEARTBEAT_INTERVAL_S, _beat)
        self._heartbeat_timer.daemon = True
        self._heartbeat_timer.start()

    def _clear_heartbeat(self) -> None:
        if self._heartbeat_timer is not None:
            self._heartbeat_timer.cancel()
            self._heartbeat_timer = None

    def _schedule_hide(self) -> None:
        self._clear_hide_timer()

        def _hide() -> None:
            self._hide_timer = None
            self._hidden_after_landing = True
            self._emit_changed()

        self._hide_timer = threading.Timer(HIDE_AFTER_LANDING_S, _hide)
        self._hide_timer.daemon = True
        self._hide_timer.start()

    def _clear_hide_timer(self) -> None:
        if self._hide_timer is not None:
            self._hide_timer.cancel()
            self._hide_timer = None

    def _emit_changed(self) -> None:
        self._on_change(self.get_snapshot())


# --- Pad diagram geometry (this table's ultimate source is the EDMC
# LandingPad plugin's pad-index math - don't "clean up" without
# re-checking against it, or against the real game's own station layout) -

_SHELL_SCALE = (1.0, 0.625, 0.455, 0.25)
_SIN15 = math.sin(math.pi / 12)
_COS15 = math.cos(math.pi / 12)
_SIN45 = math.sqrt(2) / 2
_SIN60 = math.sqrt(3) / 2

# Four nested dodecagon shells, 12 radial spokes; pads 1-45 wrap mod 15
# across 3 shell-offset repeats.
_DODECAGON: Tuple[Tuple[float, float], ...] = (
    (_COS15, -_SIN15), (_SIN45, -_SIN45), (_SIN15, -_COS15), (-_SIN15, -_COS15),
    (-_SIN45, -_SIN45), (-_COS15, -_SIN15), (-_COS15, _SIN15), (-_SIN45, _SIN45),
    (-_SIN15, _COS15), (_SIN15, _COS15), (_SIN45, _SIN45), (_COS15, _SIN15),
)
_PAD_LIST: Tuple[Tuple[int, int], ...] = (
    (0, 0), (0, 0), (0, 2), (0, 2), (1, 0), (1, 0), (1, 1), (1, 2),
    (2, 0), (2, 2), (3, 0), (3, 0), (3, 1), (3, 2), (3, 2),
)
_PAD_SECTORS: Tuple[Tuple[float, float], ...] = (
    (0, 1), (-0.5, _SIN60), (-_SIN60, 0.5), (-1, 0), (-_SIN60, -0.5), (-0.5, -_SIN60),
    (0, -1), (0.5, -_SIN60), (_SIN60, -0.5), (1, 0), (_SIN60, 0.5), (0.5, _SIN60),
)


def _starport_shell_points(cx: float, cy: float, r: float, scale: float) -> List[Tuple[float, float]]:
    return [(cx + dx * r * scale, cy + dy * r * scale) for dx, dy in _DODECAGON]


def _starport_pad_pos(pad: int, cx: float, cy: float, r: float) -> Tuple[float, float]:
    normalized = ((pad - 1) % 45 + 45) % 45
    s, t = _PAD_LIST[normalized % 15]
    sector = s + (normalized // 15) * 4
    dx, dy = _PAD_SECTORS[sector % 12]
    td = (_SHELL_SCALE[t] + _SHELL_SCALE[t + 1]) / 2
    rt = r * _COS15 * td
    return (cx + rt * dx, cy + rt * dy)


def _fleetcarrier_pad_rects(carrier_type: CarrierType) -> List[Tuple[float, float, float, float]]:
    """8 Large + 4 Medium + 4 Small pads; SquadronCarrier duplicates the
    cluster left/right (32 total)."""

    def add_pads(x_off: float, rects: List[Tuple[float, float, float, float]]) -> None:
        for y in (22, 2, -18, -38):
            for x in (-12, 2):
                rects.append((x + x_off, y, x + x_off + 10, y + 16))
        for x in (-22, 15):
            for y in (25, 10):
                rects.append((x + x_off, y, x + x_off + 7, y + 11))
        small_x = (-24, -18, 14, 20) if carrier_type == "ColonisationShip" else (-24, 14, 20, -18)
        for x in small_x:
            rects.append((x + x_off, 0, x + x_off + 4, 6))

    pad_list: List[Tuple[float, float, float, float]] = []
    if carrier_type == "SquadronCarrier":
        squad_offset = 48 / 2 + 2
        add_pads(squad_offset, pad_list)
        add_pads(-squad_offset, pad_list)
    else:
        add_pads(0, pad_list)
    return pad_list


_MAX_FLEETCARRIER_PADS = 32  # SquadronCarrier's doubled cluster - the widest case


# --- Rendering (overlay.py's OverlayClient is generic; this is the one
# place that knows what the Landing widget should look like) -------------

_STROKE = "#fb923c"  # orange-400, theme-independent - see below
_ACTIVE = "#fbbf24"  # amber-400
_LABEL_ON_ACTIVE = "#0f172a"  # slate-900 (dark text on the amber fill)

# "Elite Orange" chrome - unlike interdiction.py's card (which stays
# hardcoded red as a safety signal by design), this widget's chrome
# follows a switchable palette; "elite-orange" is the one in use here.
# Text hierarchy: title -> textPrimary, station/pad/fallback -> textMuted
# (the dimmest tier - deliberately not textSecondary), and
# statusLabel/deniedLabel stay semantic (red/emerald) regardless of theme,
# same principle as interdiction.py's resolution colors.
_CHROME_BORDER = "#80f97316"  # orange-500 at 50% alpha
_CHROME_FILL = "#d9000000"  # black at 85% alpha
_TEXT_PRIMARY = "#fdba74"  # orange-300
_TEXT_MUTED = "#c2410c"  # orange-700
_STATUS_OK = "#34d399"  # emerald-400
_STATUS_DENIED = "#f87171"  # red-400

# Fixed placement (not user-configurable - same reasoning as
# interdiction.py). Lower-left of the virtual 1280x1024-ish HUD, clear of
# interdiction.py's upper-center warning.
_TEXT_X = 40
_Y_TITLE = 650
_Y_STATUS = 675
_Y_STATION = 698
_Y_PAD = 721
_Y_DENIED = 744
_Y_FALLBACK = 767

# A translucent card behind the whole widget (status text + diagram),
# sized to hug its actual content rather than leaving dead space - it used
# to be 420 wide with the diagram anchored at its own fixed cx=110, which
# left a large empty gap on the card's right side (nothing else in the
# widget ever reaches that far right). _CARD_W is trimmed to a width that
# comfortably fits the status text column (title/status/station/pad/denied
# - a generous character budget, since station names vary and EDMCOverlay
# gives no text-measurement API to size this exactly) plus the diagram,
# and the diagram is centered on the card's midline (_DIAGRAM_CX). The
# status text itself stays left-aligned at _TEXT_X - true per-line
# centering isn't attempted, since without real glyph widths (see
# interdiction.py's identical caveat) an estimated-width guess could put
# text visibly off-center instead of just left-aligned. The one exception
# is the "no diagram for this station type" fallback sentence
# (_Y_FALLBACK), which is long enough that it's expected to run past the
# card's right edge regardless of width - unavoidable without wrapping.
# Chrome (_CHROME_BORDER/_CHROME_FILL above) is constant - it does not
# track docking status (only the status/denied-reason text itself is
# status-colored, not the card).
_CARD_ID = "edppmt_landing_card"
_CARD_X = 20
_CARD_Y = _Y_TITLE - 14
_CARD_W = 320
_DIAGRAM_CX = _CARD_X + _CARD_W // 2
_DIAGRAM_CY = 860
_DIAGRAM_SIZE = 160
_CARD_H = int(_DIAGRAM_CY + _DIAGRAM_SIZE / 2 + 20 - _CARD_Y)

# Render is event-driven (docking-state changes), not per-frame, so a
# generous ttl means the drawing survives comfortably between updates.
_TTL = 20

_STARPORT_SHELL_IDS = tuple(f"edppmt_landing_shell{i}" for i in range(4))
_STARPORT_SPOKE_IDS = tuple(f"edppmt_landing_spoke{i}" for i in range(12))
_STARPORT_PADMARK_ID = "edppmt_landing_padmark"
_FLEETCARRIER_PAD_IDS = tuple(f"edppmt_landing_fcpad{i}" for i in range(_MAX_FLEETCARRIER_PADS))
_FLEETCARRIER_LABEL_ID = "edppmt_landing_fclabel"

_STATUS_TEXT_IDS = (
    ("edppmt_landing_title", _Y_TITLE), ("edppmt_landing_status", _Y_STATUS),
    ("edppmt_landing_station", _Y_STATION), ("edppmt_landing_pad", _Y_PAD),
    ("edppmt_landing_denied", _Y_DENIED), ("edppmt_landing_fallback", _Y_FALLBACK),
)


def render(info: LandingDisplayInfo, carrier_type: CarrierType, client: OverlayClient) -> None:
    """Draws (or clears) the Landing widget. Raises on an OverlayClient
    failure - load.py's live listener wraps this call and decides that's an
    expected, silent-fail state; the Settings "Test Overlay" button wraps
    its own call and surfaces it instead."""
    if not info.status_label:
        clear(client)
        return

    status_color = _STATUS_DENIED if info.status_label == "Docking Denied" else _STATUS_OK
    client.send_shape(_CARD_ID, "rect", _CHROME_BORDER, _CHROME_FILL, _CARD_X, _CARD_Y, _CARD_W, _CARD_H, ttl=_TTL, thickness=2)
    client.send_message("edppmt_landing_title", "Landing", _TEXT_PRIMARY, _TEXT_X, _Y_TITLE, ttl=_TTL, size="large")
    client.send_message("edppmt_landing_status", info.status_label, status_color, _TEXT_X, _Y_STATUS, ttl=_TTL)
    _send_or_clear(client, "edppmt_landing_station", info.station, _TEXT_MUTED, _TEXT_X, _Y_STATION)
    # This "Pad N" text line is unconditional - sent whenever a pad is known,
    # regardless of whether a diagram renders below it (see the fallback_text
    # branch further down for stations with no diagram family at all, e.g.
    # outposts) - the pad number itself must never depend on the diagram.
    _send_or_clear(client, "edppmt_landing_pad", f"Pad {info.pad}" if info.pad is not None else "", _TEXT_MUTED, _TEXT_X, _Y_PAD)

    denied_label = (info.denied_reason or "Unknown") if info.status_label == "Docking Denied" else ""
    _send_or_clear(client, "edppmt_landing_denied", denied_label, _STATUS_DENIED, _TEXT_X, _Y_DENIED)

    fallback_text = ""
    if info.show_diagram and info.diagram_type == "starport":
        _render_starport_diagram(client, info.pad)
        _clear_fleetcarrier_diagram(client)
    elif info.show_diagram and info.diagram_type == "fleetcarrier":
        _render_fleetcarrier_diagram(client, info.pad, carrier_type)
        _clear_starport_diagram(client)
    else:
        _clear_starport_diagram(client)
        _clear_fleetcarrier_diagram(client)
        if info.pad is not None and info.status_label == "Docking Approved":
            fallback_text = f"No pad layout diagram for this station type. It's the one with the {info.pad} above it."

    _send_or_clear(client, "edppmt_landing_fallback", fallback_text, _TEXT_MUTED, _TEXT_X, _Y_FALLBACK)


def clear(client: OverlayClient) -> None:
    # Parked at the card's own position, not (0, 0) - see
    # _clear_fleetcarrier_diagram's comment for why.
    client.send_shape(_CARD_ID, "rect", "", "", _CARD_X, _CARD_Y, 0, 0, ttl=1)
    for msg_id, y in _STATUS_TEXT_IDS:
        client.send_message(msg_id, "", "white", _TEXT_X, y, ttl=1)
    _clear_starport_diagram(client)
    _clear_fleetcarrier_diagram(client)


def _send_or_clear(client: OverlayClient, msg_id: str, text: str, color: str, x: int, y: int) -> None:
    if text:
        client.send_message(msg_id, text, color, x, y, ttl=_TTL)
    else:
        client.send_message(msg_id, "", "white", x, y, ttl=1)


def _render_starport_diagram(client: OverlayClient, pad: Optional[int]) -> None:
    r = _DIAGRAM_SIZE / 2 - 8
    shells = [_starport_shell_points(_DIAGRAM_CX, _DIAGRAM_CY, r, scale) for scale in _SHELL_SCALE]

    for shape_id, points in zip(_STARPORT_SHELL_IDS, shells):
        closed = list(points) + [points[0]]
        client.send_vector(shape_id, [{"x": x, "y": y} for x, y in closed], _STROKE, ttl=_TTL)

    for i, shape_id in enumerate(_STARPORT_SPOKE_IDS):
        outer, inner = shells[0][i], shells[3][i]
        client.send_vector(
            shape_id, [{"x": outer[0], "y": outer[1]}, {"x": inner[0], "y": inner[1]}], _STROKE, ttl=_TTL,
        )

    if pad is not None:
        px, py = _starport_pad_pos(pad, _DIAGRAM_CX, _DIAGRAM_CY, r)
        client.send_vector(
            _STARPORT_PADMARK_ID,
            [{"x": px, "y": py, "color": _ACTIVE, "marker": "circle", "text": str(pad)}],
            _ACTIVE, ttl=_TTL,
        )
    else:
        client.send_vector(_STARPORT_PADMARK_ID, [], "", ttl=1)


def _render_fleetcarrier_diagram(client: OverlayClient, pad: Optional[int], carrier_type: CarrierType) -> None:
    box_w, box_h = 48, 76
    pad_list = _fleetcarrier_pad_rects(carrier_type)
    pad_count = len(pad_list)
    scale = min((_DIAGRAM_SIZE - 16) / box_w, (_DIAGRAM_SIZE - 16) / box_h, 4)
    active_index = ((pad - 1) % pad_count + pad_count) % pad_count if pad is not None and pad_count else -1

    active_rect: Optional[Tuple[float, float, float, float]] = None
    for i, shape_id in enumerate(_FLEETCARRIER_PAD_IDS):
        if i >= pad_count:
            # Parked at the diagram's own center, not (0, 0) - see
            # _clear_fleetcarrier_diagram's comment for why.
            client.send_shape(shape_id, "rect", "", "", _DIAGRAM_CX, _DIAGRAM_CY, 0, 0, ttl=1)
            continue
        x1, y1, x2, y2 = pad_list[i]
        sx1, sy1 = _DIAGRAM_CX + x1 * scale, _DIAGRAM_CY - y1 * scale
        sx2, sy2 = _DIAGRAM_CX + x2 * scale, _DIAGRAM_CY - y2 * scale
        rx, ry = min(sx1, sx2), min(sy1, sy2)
        w, h = max(int(round(abs(sx2 - sx1))), 1), max(int(round(abs(sy2 - sy1))), 1)
        is_active = i == active_index
        if is_active:
            active_rect = (rx, ry, rx + w, ry + h)
        client.send_shape(
            shape_id, "rect", _STROKE, _ACTIVE if is_active else "",
            int(round(rx)), int(round(ry)), w, h, ttl=_TTL,
        )

    if active_rect is not None and pad is not None:
        rx, ry, rx2, ry2 = active_rect
        # Dark text (matches the reference diagram's label fill) - it sits
        # directly on top of the rect's own amber (_ACTIVE) fill, so
        # amber-on-amber here would be illegible. The starport pad marker
        # doesn't have this problem: its "circle" vect marker is
        # stroke-only (EDMCOverlay never fills a vect marker), so its
        # amber label text sits on the game background, not a fill.
        # No text-measurement API is available (same caveat as the card
        # layout above), so centering is a per-digit-count estimate rather
        # than a single fixed offset - a flat offset tuned for "24" left
        # single-digit pads ("3") visibly off-center to one side.
        digits = len(str(pad))
        label_x = int(round((rx + rx2) / 2)) - 3 * digits
        label_y = int(round((ry + ry2) / 2)) - 6
        client.send_message(_FLEETCARRIER_LABEL_ID, str(pad), _LABEL_ON_ACTIVE, label_x, label_y, ttl=_TTL)
    else:
        # Parked at the diagram's own center, not (0, 0) - see
        # _clear_fleetcarrier_diagram's comment for why.
        client.send_message(_FLEETCARRIER_LABEL_ID, "", "white", _DIAGRAM_CX, _DIAGRAM_CY, ttl=1)


def _clear_starport_diagram(client: OverlayClient) -> None:
    for shape_id in _STARPORT_SHELL_IDS + _STARPORT_SPOKE_IDS:
        client.send_vector(shape_id, [], "", ttl=1)
    client.send_vector(_STARPORT_PADMARK_ID, [], "", ttl=1)


def _clear_fleetcarrier_diagram(client: OverlayClient) -> None:
    # Parked at the diagram's own center (_DIAGRAM_CX/_DIAGRAM_CY), not
    # literal (0, 0) - confirmed against EDMCModernOverlay's own grouping
    # source (`overlay_client/payload_transform.py`'s
    # `accumulate_group_bounds`): a Plugin Group's Fill-mode bounding box
    # includes every live payload's raw (x, y) unconditionally, even a
    # zero-size rect/blank message that renders nothing. This card's whole
    # widget (text + diagram) is one registered Plugin Group (see
    # overlay.register_modern_overlay_group), so a "cleared" payload sent
    # to (0, 0) was a phantom point at the screen's top-left corner that
    # dragged the group's computed anchor/scale toward it for as long as
    # that payload stayed live (its own ttl) - then let go once it expired
    # and got resent on the next render/heartbeat cycle. With payloads
    # expiring on their own independent schedules, that pull-and-release
    # was constant and out of phase, which is what made the whole widget
    # visibly drift/jump on EDMCModernOverlay. Parking cleared payloads
    # inside the diagram's own real footprint instead keeps the group's
    # bounding box - and therefore its anchor/scale - stable.
    for shape_id in _FLEETCARRIER_PAD_IDS:
        client.send_shape(shape_id, "rect", "", "", _DIAGRAM_CX, _DIAGRAM_CY, 0, 0, ttl=1)
    client.send_message(_FLEETCARRIER_LABEL_ID, "", "white", _DIAGRAM_CX, _DIAGRAM_CY, ttl=1)
