"""
EDPPMT entry point for Elite Dangerous Market Connector.

Tracks PowerPlay merits earned per session (auto-bounded by game login),
estimates the Control Points those merits represent for Acquisition,
Reinforcement, and Undermining activity based on the system a commander is in
when they earn them, and tracks session credit income alongside it.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, Optional, Tuple

import tkinter as tk

from config import appname
from monitor import monitor

from . import __version__
from . import autohonk
from . import interdiction
from . import landing
from . import overlay
from .formulas import ACTIVITY_LABELS
from .powerplay import PLEDGE_UNKNOWN, PowerplayTracker, find_last_pledge_event
from .session import SessionManager
from .store import SessionStore
from .update import UpdateManager, check_applied_update
from . import rares_window
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
_interdiction: Optional[interdiction.InterdictionTracker] = None
_landing: Optional[landing.LandingTracker] = None
_overlay: overlay.OverlayClient = overlay.OverlayClient()

# Journal events forwarded to _interdiction.handle_event unconditionally
# (cheap to run regardless of whether the feature is enabled - only
# _on_interdiction_change's actual draw is gated on Settings). ReceiveText
# is already flowing through _dispatch for every event; Interdicted/
# EscapeInterdiction are new.
_INTERDICTION_EVENTS = ("ReceiveText", "Interdicted", "EscapeInterdiction")

# EDMC's own live-tracked current-system name, refreshed on every journal
# event regardless of whether it carries PowerPlay context - unlike
# PowerplayTracker.system_name (only updated when a PP-relevant event fires,
# so it can lag behind an actual jump). This is what the main panel and
# Sessions window use to show "what am I earning here" and to file merits
# under the right system as they're earned. See ui.refresh/window.refresh.
_current_system: Optional[str] = None

# The current system's galactic coordinates, straight off the journal's
# StarPos field (present on both FSDJump and Location, unlike PowerPlay
# context which only appears when the system is PowerPlay-relevant) - used
# purely for the Rares window's nearest-rare-goods distance calc, nothing
# PowerPlay-related reads this.
_current_system_coords: Optional[Tuple[float, float, float]] = None

# Events that carry StarPos for wherever the commander currently is - Docked
# doesn't repeat it, so it's deliberately not in this list (see the "Location"
# comment on _SYSTEM_CONTEXT_EVENTS below for why a stale value is fine to
# just leave in place rather than clear).
_STARPOS_EVENTS = ("FSDJump", "Location")

# Journal events that carry PowerplayState/Powers for the current system when
# it's powerplay-relevant. "Location" is handled separately below (it also
# doubles as the not-pledged checkpoint).
_SYSTEM_CONTEXT_EVENTS = ("FSDJump", "Docked")

# Commodity/data hand-ins at a power contact — see PowerplayTracker.apply_delivery_signal.
_DELIVERY_EVENTS = ("SearchAndRescue", "DeliverPowerMicroResources")


def plugin_start3(plugin_dir: str) -> str:
    """Load EDPPMT into EDMarketConnector."""
    global _sessions, _updater, _autohonk, _interdiction, _landing
    logger.info("EDPPMT v%s starting from %s", __version__, plugin_dir)
    _sessions = SessionManager(SessionStore(plugin_dir))
    _autohonk = autohonk.AutoHonkController()
    _interdiction = interdiction.InterdictionTracker(on_change=_on_interdiction_change)
    _landing = landing.LandingTracker(on_change=_on_landing_change)

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
    rares_window.close()
    _overlay.close()
    logger.info("EDPPMT shutting down")


def plugin_app(parent: tk.Frame) -> tk.Frame:
    """Create EDPPMT widgets on the EDMC main window."""
    global _ui_frame
    _ui_frame = ui.create_plugin_app(
        parent, _show_sessions, _show_rares, _rescan_journal,
        _toggle_autohonk, _toggle_interdiction, _toggle_landing,
    )
    if _sessions is not None:
        # Show whatever session state was persisted from last run right
        # away, rather than leaving the panel on its placeholder text until
        # the next journal event happens to arrive.
        ui.refresh(_sessions, _pp, _current_system)
    return _ui_frame


def _show_sessions() -> None:
    if _ui_frame is not None and _sessions is not None:
        window.show(_ui_frame, _sessions, _pp, _current_system)


def _show_rares() -> None:
    if _ui_frame is not None:
        rares_window.show(_ui_frame, _current_system, _current_system_coords)


def _toggle_autohonk() -> bool:
    """Main-panel Auto-Honk button: flips just the enabled flag, preserving
    fire-button/hold-duration/focus/skip-visited as already configured.
    Returns the new state so ui.py can recolor the button immediately."""
    cfg = autohonk.load_config()
    cfg.enabled = not cfg.enabled
    autohonk.save_config(cfg)
    if _autohonk is not None:
        _autohonk.reload_config()
    return cfg.enabled


def _toggle_interdiction() -> bool:
    """Main-panel Interdiction button. No reload_config() needed here -
    InterdictionTracker checks load_config().enabled fresh on every change
    (see _on_interdiction_change), unlike AutoHonkController which caches
    its config on the instance."""
    cfg = interdiction.load_config()
    cfg.enabled = not cfg.enabled
    interdiction.save_config(cfg)
    return cfg.enabled


def _toggle_landing() -> bool:
    """Main-panel Landing button - same reasoning as _toggle_interdiction."""
    cfg = landing.load_config()
    cfg.enabled = not cfg.enabled
    landing.save_config(cfg)
    return cfg.enabled


def _rescan_journal() -> None:
    """"Rescan" button handler: re-reads the current journal file from the
    start and replays its PowerPlay-relevant events, to recover merits
    earned in the gap between an EDMC restart (while the game keeps running)
    and the synthesized "StartUp" event that follows it. EDMC does not
    replay journal backlog to plugins on its own restart (see
    docs/tech-spec.md §5/§7) — only genuinely new events reach
    journal_entry() from then on — so anything earned while the old EDMC
    process wasn't running to see it live never arrives here any other way.

    Pledge/system-context/delivery events are replayed unconditionally
    (they just overwrite tracker state, so replaying an already-seen one is
    harmless) to keep classification accurate for whatever turns out to be
    new. PowerplayMerits events are only actually recorded if their
    "timestamp" is newer than the last one already recorded this session
    (current["last_merit_ts"]) — re-adding an already-counted gain would
    double it, since merit totals (unlike tracker state) accumulate. A
    genuinely new merit event sharing the exact same (whole-second-precision)
    timestamp as the last recorded one is the one edge case this can still
    miss — silently under-counting is the safer failure mode here than
    risking a double count.
    """
    if _sessions is None or _ui_frame is None:
        return
    journal_file = monitor.logfile
    if not journal_file or _sessions.current.get("journal_file") != journal_file:
        ui.set_last_event("Rescan: no active session for the current journal file")
        return

    baseline_ts = _sessions.current.get("last_merit_ts")
    replay_system: Optional[str] = None
    recovered_events = 0
    recovered_merits = 0

    try:
        with open(journal_file, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                event = entry.get("event", "")
                star_system = entry.get("StarSystem")
                if star_system:
                    replay_system = star_system

                applier = _PLEDGE_EVENT_APPLIERS.get(event)
                if applier is not None:
                    applier(_pp, entry)
                elif event == "PowerplayRank":
                    _pp.apply_rank(entry)
                elif event == "Location" or event in _SYSTEM_CONTEXT_EVENTS:
                    _pp.apply_system_context(replay_system, entry)
                elif event in _DELIVERY_EVENTS:
                    _pp.apply_delivery_signal(event, entry)
                elif event == "PowerplayMerits":
                    gained = _pp.apply_merits(entry)
                    activity = _pp.classify_current_activity(replay_system)
                    ts = entry.get("timestamp")
                    is_new = (
                        gained is not None
                        and isinstance(ts, str)
                        and (baseline_ts is None or ts > baseline_ts)
                    )
                    if is_new:
                        _sessions.record_merits(activity, gained, replay_system, ts)
                        baseline_ts = ts
                        recovered_events += 1
                        recovered_merits += gained
    except OSError:
        logger.warning("Could not read %s for rescan", journal_file, exc_info=True)
        ui.set_last_event("Rescan failed: could not read journal file")
        return

    _sessions.record_power(_pp.my_power)
    logger.info("Rescanned journal: recovered %d merits across %d events", recovered_merits, recovered_events)
    if recovered_events:
        ui.set_last_event(f"Rescan: recovered {recovered_merits} merits ({recovered_events} events)")
    else:
        ui.set_last_event("Rescan: no missed merits found")
    ui.refresh(_sessions, _pp, _current_system)
    window.refresh(_current_system)


def dashboard_entry(cmdr: str, is_beta: bool, entry: Dict[str, Any]) -> None:
    """EDMC calls this on every Status.json change (roughly once a second in
    flight) — entry is the parsed file directly. The only thing EDPPMT reads
    from it is the Flags bitmask, for the "Being Interdicted" bit (the
    earliest interdiction signal, before any resolving journal event — see
    interdiction.py)."""
    if _interdiction is None:
        return
    flags = entry.get("Flags")
    if isinstance(flags, int):
        _interdiction.handle_dashboard_flags(flags)


def _on_interdiction_change(snapshot: interdiction.InterdictionSnapshot) -> None:
    """Called synchronously from dashboard_entry (flag flip) or from
    _dispatch/journal_entry (resolving event) — both are EDMC's own calling
    thread, so the actual overlay send (up to 3 sequential socket connects,
    each with its own timeout if EDMCOverlay isn't reachable) is pushed onto
    a background thread rather than risking EDMC's callback stalling on it."""
    if not interdiction.load_config().enabled:
        return

    def worker() -> None:
        try:
            interdiction.render(snapshot, _overlay)
        except OSError:
            # EDMCOverlay isn't running/reachable — expected and silent on
            # the live path (unlike the Settings "Test Warning" button,
            # which wraps its own call and surfaces this instead).
            logger.debug("Could not reach EDMCOverlay for interdiction warning", exc_info=True)

    threading.Thread(target=worker, name="EDPPMT-interdiction-render", daemon=True).start()


def _on_landing_change(snapshot: landing.LandingSnapshot) -> None:
    """Called synchronously from _dispatch/journal_entry (EDMC's own calling
    thread) on every docking-state change - see _on_interdiction_change for
    why the actual overlay send is pushed onto a background thread."""
    if not landing.load_config().enabled:
        return

    if snapshot.docked and snapshot.hidden_after_landing:
        def clear_worker() -> None:
            try:
                landing.clear(_overlay)
            except OSError:
                logger.debug("Could not reach EDMCOverlay to clear landing pad overlay", exc_info=True)

        threading.Thread(target=clear_worker, name="EDPPMT-landing-clear", daemon=True).start()
        return

    info = landing.build_landing_display_info(
        snapshot.docking, snapshot.docked, snapshot.last_assigned_pad,
        snapshot.last_station_type, snapshot.last_carrier_type,
    )

    def worker() -> None:
        try:
            landing.render(info, snapshot.last_carrier_type, _overlay)
        except OSError:
            # EDMCOverlay isn't running/reachable - expected and silent on
            # the live path, same as _on_interdiction_change.
            logger.debug("Could not reach EDMCOverlay for landing pad overlay", exc_info=True)

    threading.Thread(target=worker, name="EDPPMT-landing-render", daemon=True).start()


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
    ui.sync_toggle_buttons()  # main-panel buttons reflect whatever Settings just saved
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
        rares_window.refresh(_current_system, _current_system_coords)


_PLEDGE_EVENT_APPLIERS = {
    "Powerplay": lambda pp, entry: pp.apply_login_snapshot(entry),
    "PowerplayJoin": lambda pp, entry: pp.apply_join(entry),
    "PowerplayLeave": lambda pp, entry: pp.apply_leave(entry),
    "PowerplayDefect": lambda pp, entry: pp.apply_defect(entry),
}


_LOADGAME_SCAN_LIMIT = 50  # "LoadGame" is always one of the first few lines in a journal file


def _mode_text(game_mode: Optional[str], group: Optional[str]) -> str:
    if game_mode == "Open":
        return "Mode: Open"
    if game_mode == "Solo":
        return "Mode: Solo"
    if game_mode == "Group":
        return f"Mode: Private ({group})" if group else "Mode: Private"
    return "Mode: unknown"


def _recover_game_mode() -> None:
    """Reads the current journal file directly for its "LoadGame" event's
    GameMode/Group fields — needed only for the "StartUp" handler below,
    where EDMC synthesizes the entry itself (no journal replay) rather than
    handing us the real "LoadGame" line that would otherwise carry them.
    Unlike _recover_pledge_state's backward scan (pledge events can recur
    through a file), this reads forward from the start and stops as soon as
    it finds "LoadGame", since that event is always near the top of the
    file and never repeats within it."""
    if not monitor.logfile:
        return
    try:
        with open(monitor.logfile, "r", encoding="utf-8") as fh:
            for _ in range(_LOADGAME_SCAN_LIMIT):
                line = fh.readline()
                if not line:
                    break
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("event") == "LoadGame":
                    ui.set_mode(_mode_text(entry.get("GameMode"), entry.get("Group")))
                    return
    except OSError:
        logger.warning("Could not read %s for game-mode recovery", monitor.logfile, exc_info=True)


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
    global _current_system_coords
    event = entry.get("event", "")

    if event in _STARPOS_EVENTS:
        star_pos = entry.get("StarPos")
        if isinstance(star_pos, list) and len(star_pos) == 3:
            try:
                _current_system_coords = (float(star_pos[0]), float(star_pos[1]), float(star_pos[2]))
            except (TypeError, ValueError):
                pass

    if _autohonk is not None:
        _autohonk.handle_event(entry, system)

    if _interdiction is not None and event in _INTERDICTION_EVENTS:
        _interdiction.handle_event(entry)

    if _landing is not None and event in landing.DOCKING_EVENTS:
        _landing.handle_event(entry)

    if event == "LoadGame":
        ui.set_mode(_mode_text(entry.get("GameMode"), entry.get("Group")))
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
        _recover_game_mode()
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
    ts = entry.get("timestamp")
    _sessions.record_merits(activity, gained, system, ts if isinstance(ts, str) else None)

    ratio = ui.ratio_for(activity)
    cp = 0.0 if not ratio else gained / ratio
    label = ACTIVITY_LABELS.get(activity, "Unattributed")
    message = f"+{gained} merits ({label}, ~{cp:.1f} CP)"
    logger.info(message)
    ui.set_last_event(message)
    return message
