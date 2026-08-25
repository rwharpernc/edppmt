"""
EDPPMT entry point for Elite Dangerous Market Connector.

Tracks PowerPlay merits earned per session (auto-bounded by game login),
estimates the Control Points those merits represent for Acquisition,
Reinforcement, and Undermining activity based on the system a commander is in
when they earn them, and tracks session credit income alongside it.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import tkinter as tk

from config import appname
from monitor import monitor

from . import __version__
from . import autohonk
from .formulas import ACTIVITY_LABELS
from .powerplay import PLEDGE_UNKNOWN, PowerplayTracker, find_last_pledge_event
from .session import SessionManager
from .store import SessionStore
from .update import UpdateManager, check_applied_update
from . import ui
from . import window

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

if not logger.hasHandlers():
    level = logging.INFO
    logger.setLevel(level)
    logger_channel = logging.StreamHandler()
    logger_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - "
        "%(module)s:%(lineno)d:%(funcName)s: %(message)s",
    )
    logger_formatter.default_time_format = "%Y-%m-%d %H:%M:%S"
    logger_formatter.default_msec_format = "%s.%03d"
    logger_channel.setFormatter(logger_formatter)
    logger.addHandler(logger_channel)

_pp = PowerplayTracker()
_sessions: Optional[SessionManager] = None
_ui_frame: Optional[tk.Frame] = None
_updater: Optional[UpdateManager] = None
_autohonk: Optional[autohonk.AutoHonkController] = None

# EDMC's own live-tracked current-system name, refreshed on every journal
# event regardless of whether it carries PowerPlay context - unlike
# PowerplayTracker.system_name (only updated when a PP-relevant event fires,
# so it can lag behind an actual jump). This is what the main panel and
# Sessions window use to show "what am I earning here" and to file merits
# under the right system as they're earned. See ui.refresh/window.refresh.
_current_system: Optional[str] = None

# Journal events that carry PowerplayState/Powers for the current system when
# it's powerplay-relevant. "Location" is handled separately below (it also
# doubles as the not-pledged checkpoint).
_SYSTEM_CONTEXT_EVENTS = ("FSDJump", "Docked")

# Commodity/data hand-ins at a power contact — see PowerplayTracker.apply_delivery_signal.
_DELIVERY_EVENTS = ("SearchAndRescue", "DeliverPowerMicroResources")


def plugin_start3(plugin_dir: str) -> str:
    """Load EDPPMT into EDMarketConnector."""
    global _sessions, _updater, _autohonk
    logger.info("EDPPMT v%s starting from %s", __version__, plugin_dir)
    _sessions = SessionManager(SessionStore(plugin_dir))
    _autohonk = autohonk.AutoHonkController()

    applied_version = check_applied_update()
    if applied_version is not None:
        logger.info("EDPPMT updated to v%s", applied_version)
        ui.set_update_applied(applied_version)

    _updater = UpdateManager(plugin_dir, on_ready=_on_update_ready, on_downloading=_on_update_downloading)
    _updater.check_async()
    return "EDPPMT"


def _on_update_downloading(version: str) -> None:
    # Called from the update-check background thread — marshal onto the Tk
    # main thread before touching any widgets.
    if _ui_frame is not None:
        _ui_frame.after(0, lambda: ui.set_update_downloading(version))


def _on_update_ready(version: str) -> None:
    # Called from the update-check background thread — marshal onto the Tk
    # main thread before touching any widgets.
    if _ui_frame is not None:
        _ui_frame.after(0, lambda: ui.set_update_downloaded(version))


def plugin_stop() -> None:
    """EDMarketConnector is closing."""
    if _sessions is not None:
        _sessions.flush()
    window.close()
    logger.info("EDPPMT shutting down")


def plugin_app(parent: tk.Frame) -> tk.Frame:
    """Create EDPPMT widgets on the EDMC main window."""
    global _ui_frame
    _ui_frame = ui.create_plugin_app(parent, _show_sessions)
    if _sessions is not None:
        # Show whatever session state was persisted from last run right
        # away, rather than leaving the panel on its placeholder text until
        # the next journal event happens to arrive.
        ui.refresh(_sessions, _pp, _current_system)
    return _ui_frame


def _show_sessions() -> None:
    if _ui_frame is not None and _sessions is not None:
        window.show(_ui_frame, _sessions, _pp, _current_system)


def plugin_prefs(parent, cmdr: str, is_beta: bool):
    """Create the EDPPMT settings tab."""
    return ui.create_prefs(parent)


def prefs_changed(cmdr: str, is_beta: bool) -> None:
    """Settings were saved."""
    ui.save_prefs()
    if _autohonk is not None:
        # Picks up enabled/fire-button/hold-duration changes immediately,
        # rather than only on EDMC's next restart.
        _autohonk.reload_config()
    if _sessions is not None:
        _sessions.flush()


def journal_entry(
    cmdr: str,
    is_beta: bool,
    system: str,
    station: str,
    entry: Dict[str, Any],
    state: Dict[str, Any],
) -> Optional[str]:
    """Handle journal events for PowerPlay merit/CP tracking."""
    global _current_system
    if _sessions is None:
        return None

    if system:
        _current_system = system

    try:
        credits_now = state.get("Credits") if isinstance(state, dict) else None
        if isinstance(credits_now, (int, float)):
            _sessions.record_credits(int(credits_now))

        return _dispatch(cmdr, system, entry)
    finally:
        ui.refresh(_sessions, _pp, _current_system)
        window.refresh(_current_system)


_PLEDGE_EVENT_APPLIERS = {
    "Powerplay": lambda pp, entry: pp.apply_login_snapshot(entry),
    "PowerplayJoin": lambda pp, entry: pp.apply_join(entry),
    "PowerplayLeave": lambda pp, entry: pp.apply_leave(entry),
    "PowerplayDefect": lambda pp, entry: pp.apply_defect(entry),
}


def _recover_pledge_state() -> None:
    """Falls back to reading the current journal file directly for the last
    pledge-lifecycle event when _pp doesn't already know pledge status in
    memory — see the "LoadGame" (continued) and "StartUp" handlers below for
    the two situations that need it. A no-op if _pp already has an answer
    (the common case), so it's safe to call unconditionally from both.
    """
    if _pp.pledge_status != PLEDGE_UNKNOWN:
        return
    entry = find_last_pledge_event(monitor.logfile)
    if entry is not None:
        _PLEDGE_EVENT_APPLIERS[entry["event"]](_pp, entry)
        logger.info("Recovered pledge state from journal file: %s", _pp.pledge_summary() or "not pledged")
    # If nothing was found, leave pledge_status as PLEDGE_UNKNOWN — the
    # "Location" handler's confirm_not_pledged_if_unresolved() is still the
    # one place that settles it to NOT_PLEDGED, so there's exactly one path
    # to that conclusion rather than two that could disagree.


def _dispatch(cmdr: str, system: str, entry: Dict[str, Any]) -> Optional[str]:
    assert _sessions is not None
    event = entry.get("event", "")

    if _autohonk is not None:
        _autohonk.handle_event(entry, system)

    if event == "LoadGame":
        credits_start = entry.get("Credits")
        continued = _sessions.sync_session(
            cmdr,
            None,
            credits_start if isinstance(credits_start, int) else None,
            monitor.logfile,
        )
        logger.info("LoadGame for %s (%s)", cmdr, "continuing session" if continued else "new session")
        if continued:
            # Same journal file as before — a logout to the main menu and
            # back in, not a fresh game launch. Frontier only re-sends
            # "Powerplay" on the *first* login of a client launch, not on
            # every relog, so there's no new live event to (re)confirm
            # pledge status with here. Usually that's fine because _pp
            # already has the right answer in memory from before the relog
            # — but if EDMC (or this plugin) restarted between the relog and
            # now, _pp is a fresh tracker that never saw it. Recover it from
            # the journal file itself in that case rather than showing "not
            # pledged" until a full game restart (see _recover_pledge_state).
            _recover_pledge_state()
            ui.set_status(
                f"Pledged to {_pp.pledge_summary()}" if _pp.my_power else f"CMDR {cmdr}: not a PP Pledge"
            )
        else:
            _pp.apply_login_reset()
            if _autohonk is not None:
                _autohonk.reset_session()
            ui.set_status(f"{cmdr}: checking PowerPlay pledge…")
        return None

    if event == "StartUp":
        # EDMC (re)started with the game already running. EDMC doesn't
        # replay the journal to plugins in this case (see docs/tech-spec.md
        # §4) — it synthesizes this single event with cmdr/state already
        # reconstructed. Pick the session back up if it's the same journal
        # file we were already tracking.
        _sessions.sync_session(cmdr, None, None, monitor.logfile)
        logger.info("StartUp (EDMC attached to a running game) for %s", cmdr)
        # No journal replay means no "Powerplay" event is coming either, so
        # _pp (freshly created this run) has no way to learn pledge status
        # on its own — recover it from the journal file directly.
        _recover_pledge_state()
        ui.set_status(f"Pledged to {_pp.pledge_summary()}" if _pp.my_power else f"CMDR {cmdr}: not a PP Pledge")
        return None

    if event == "Powerplay":
        _pp.apply_login_snapshot(entry)
        _sessions.record_power(_pp.my_power)
        ui.set_status(f"Pledged to {_pp.pledge_summary()}" if _pp.my_power else f"CMDR {cmdr}: not a PP Pledge")
        return None

    if event == "PowerplayJoin":
        _pp.apply_join(entry)
        _sessions.record_power(_pp.my_power)
        ui.set_status(f"Pledged to {_pp.pledge_summary()}")
        return None

    if event == "PowerplayLeave":
        _pp.apply_leave(entry)
        ui.set_status("Left PowerPlay")
        return None

    if event == "PowerplayDefect":
        _pp.apply_defect(entry)
        _sessions.record_power(_pp.my_power)
        ui.set_status(f"Defected to {_pp.pledge_summary()}")
        return None

    if event == "PowerplayRank":
        _pp.apply_rank(entry)
        if _pp.my_power:
            ui.set_status(f"Pledged to {_pp.pledge_summary()}")
        return None

    if event == "Location":
        # "Location" always fires once at startup, after "Powerplay" would
        # have if the commander is pledged — so if pledge status is still
        # unresolved by now, there was no "Powerplay" event, meaning not
        # pledged. See PowerplayTracker.apply_login_reset for why there's no
        # more direct signal for this.
        if _pp.confirm_not_pledged_if_unresolved():
            logger.info("CMDR %s is not pledged to a Power", cmdr)
            ui.set_status(f"CMDR {cmdr}: not a PP Pledge")
        _pp.apply_system_context(system, entry)
        return None

    if event in _SYSTEM_CONTEXT_EVENTS:
        _pp.apply_system_context(system, entry)
        return None

    if event in _DELIVERY_EVENTS:
        _pp.apply_delivery_signal(event, entry)
        return None

    if event == "PowerplayMerits":
        return _handle_merits(system, entry)

    return None


def _handle_merits(system: str, entry: Dict[str, Any]) -> Optional[str]:
    assert _sessions is not None

    gained = _pp.apply_merits(entry)
    _sessions.record_power(_pp.my_power)
    if gained is None:
        return None

    activity = _pp.classify_current_activity(system)
    _sessions.record_merits(activity, gained, system)

    ratio = ui.ratio_for(activity)
    cp = 0.0 if not ratio else gained / ratio
    label = ACTIVITY_LABELS.get(activity, "Unattributed")
    message = f"+{gained} merits ({label}, ~{cp:.1f} CP)"
    logger.info(message)
    ui.set_last_event(message)
    return message
