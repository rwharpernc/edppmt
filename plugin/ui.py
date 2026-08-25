"""Tkinter UI for EDPPMT: main-window summary strip and the Settings tab."""

from __future__ import annotations

import logging
import os
import threading
from typing import Callable, Dict, List, Optional, Tuple

import tkinter as tk

import myNotebook as nb
from config import appname, config
from theme import theme
from ttkHyperlinkLabel import HyperlinkLabel

from . import __version__
from . import autohonk
from .formulas import (
    ACQUISITION,
    ACTIVITIES,
    ACTIVITY_LABELS,
    DEFAULT_RATIOS,
    NO_CP_ACTIVITIES,
    REINFORCEMENT,
    UNDERMINING,
    merits_to_cp,
)
from .powerplay import PowerplayTracker
from .session import SessionManager, credits_earned, system_merit_total, system_totals, total_merits
from .update import CONFIG_AUTO_UPDATE, RELEASES_PAGE_URL

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

CONFIG_RATIO_PREFIX = "edppmt_ratio_"
CONFIG_COLLAPSED = "edppmt_main_collapsed"

# Color for the main-panel "Updated to vX" HyperlinkLabel - the only state
# that widget ever shows text for (see _apply_version_state).
_UPDATED_COLOR = "#2e7d32"

# Shared with the ratio/Auto-Honk caution notes ("#c07000") for warnings;
# this one marks "how to" guidance instead (the Auto-Honk quick-setup text).
_INFO_COLOR = "#1565c0"

# How long "Updated to vX" stays up on the main panel before hiding again -
# long enough to notice, short enough that you don't need to restart EDMC a
# second time just to clear it.
_UPDATED_MESSAGE_DURATION_MS = 15_000

# Short activity labels for the session CP breakdown, where "Reinforcement"
# and "Undermining" spelled out would run the main panel too wide.
_SHORT_ACTIVITY_LABELS: Dict[str, str] = {
    ACQUISITION: "Acq",
    REINFORCEMENT: "Reinf",
    UNDERMINING: "UM",
}

# Every main-panel row whose text is built from live, unbounded data (a
# system/Power name, a merit count, a Power's name in the pledge status,
# ...) gets this wraplength - a safety net for a pathologically long value,
# not a target to design around. EDMC's window already grows to fit
# whatever's widest among every plugin it's running (this one included), so
# there generally isn't a fixed "default width" narrower than that to hold
# this plugin's own rows to - a previous, much tighter value (380px, chosen
# to approximate EDMC's own width with no other plugins at all) wrapped
# ordinary content under real-world conditions (a longer Power name in the
# pledge line, for instance) well before anything resembling "full width".
# Any single line here is still short and bounded by construction (see
# _here_merits_label/_here_cp_label below for the one row that used to
# combine two things onto one line instead), so this is generous headroom
# rather than an expectation that lines will actually get this long.
_MAIN_PANEL_WRAP = 640

_frame: Optional[tk.Frame] = None
_status_label: Optional[tk.Label] = None
_system_label: Optional[tk.Label] = None
_here_merits_label: Optional[tk.Label] = None
_here_cp_label: Optional[tk.Label] = None
_merits_label: Optional[tk.Label] = None
_cp_label: Optional[tk.Label] = None
_credits_label: Optional[tk.Label] = None
_last_event_label: Optional[tk.Label] = None
_version_label: Optional[HyperlinkLabel] = None
_ratio_vars: Dict[str, tk.StringVar] = {}
_auto_update_var: Optional[tk.BooleanVar] = None

# Main-panel collapse: title label doubles as the toggle, everything below
# the title/status/version rows hides when collapsed (those stay visible so
# pledge status is still visible at a glance, and a just-applied "Updated to
# vX" confirmation is never hidden by collapsing the section).
_title_label: Optional[tk.Label] = None
_collapsed: bool = False
_collapsible_widgets: List[tk.Widget] = []
_last_credits_earned: Optional[int] = None

_autohonk_frame: Optional[nb.Frame] = None
_autohonk_enabled_var: Optional[tk.BooleanVar] = None
_autohonk_firebutton_var: Optional[tk.StringVar] = None
_autohonk_hold_var: Optional[tk.StringVar] = None
_autohonk_focus_var: Optional[tk.BooleanVar] = None
_autohonk_skipvisited_var: Optional[tk.BooleanVar] = None
_autohonk_status_label: Optional[tk.Label] = None
_autohonk_result_label: Optional[tk.Label] = None

# Fire button / hold / focus / skip-visited widgets - only meaningful once
# Auto-Honk is enabled, so they grey out together with it (see
# _update_autohonk_dependent_state). Rescan/Test Honk Now are deliberately
# NOT in this list - they're a standalone sanity check that works whether
# or not Auto-Honk itself is enabled.
_autohonk_dependent_widgets: List[tk.Widget] = []

# (kind, version) — kind is one of "normal", "downloading", "downloaded", "updated".
_version_state: tuple = ("normal", None)
_updated_clear_scheduled: bool = False


def ratio_for(activity: str) -> float:
    """Current merits-per-CP ratio for an activity, from Settings or the default."""
    default = DEFAULT_RATIOS.get(activity)
    if default is None:
        return 0.0
    raw = config.get_str(f"{CONFIG_RATIO_PREFIX}{activity}")
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _separator(parent: tk.Frame) -> tk.Label:
    """A themed dash-rule label used to break the main panel into groups
    (header / system / session stats / last event) — plain tk.Label rather
    than ttk.Separator so theme.update() colors it the same as the rest of
    the panel without a second theming path to get wrong."""
    return tk.Label(parent, text="─" * 46, anchor=tk.W)


def create_plugin_app(parent: tk.Frame, on_show_details: Callable[[], None]) -> tk.Frame:
    """Create the main-window frame for EDMC."""
    global _frame, _status_label, _system_label, _here_merits_label, _here_cp_label
    global _merits_label, _cp_label, _credits_label
    global _last_event_label, _version_label, _title_label, _collapsed, _collapsible_widgets

    _frame = tk.Frame(parent)
    _frame.columnconfigure(1, weight=1)

    _collapsed = config.get_bool(CONFIG_COLLAPSED, default=False)

    _title_label = tk.Label(_frame, text=_title_text(), cursor="hand2")
    _title_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
    _title_label.bind("<Button-1>", _toggle_collapsed)

    # The plugin version itself lives only in the Settings tab now (see
    # create_prefs) - this slot is reserved purely for the one-time
    # "Updated to vX" confirmation right after a staged update takes
    # effect (see _apply_version_state), so it starts hidden.
    _version_label = HyperlinkLabel(
        _frame, text="", background=nb.Label().cget("background"), url=RELEASES_PAGE_URL, underline=True,
    )
    _version_label.grid(row=0, column=2, sticky=tk.E, padx=(4, 0))
    _version_label.grid_remove()

    # Its own full-width row rather than squeezed into column 1 next to the
    # title - "Pledged to <a long Power name> (Rank N)" competing for space
    # with the title and (briefly) the version label was wrapping well
    # short of the panel's actual available width.
    _status_label = tk.Label(
        _frame, text="Awaiting PowerPlay activity…", wraplength=_MAIN_PANEL_WRAP, justify=tk.LEFT,
    )
    _status_label.grid(row=1, column=0, columnspan=3, sticky=tk.W)

    separator1 = _separator(_frame)
    separator1.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))

    _system_label = tk.Label(_frame, text="Awaiting system data…", wraplength=_MAIN_PANEL_WRAP, justify=tk.LEFT)
    _system_label.grid(row=3, column=0, columnspan=3, sticky=tk.W)

    # What you're earning in *this* system specifically - the main reason
    # this panel exists. Directly under the system row since the two are
    # read together; switches automatically as PowerplayMerits/system-jump
    # events update the current system (see load._current_system), and
    # re-accumulates onto the same per-system total if you jump back to
    # somewhere you've already worked this session (see
    # session.system_totals). Split across two lines by design (merit count,
    # then the full three-activity CP breakdown) rather than one long line
    # left to wrap on its own - it always has two distinct things to say,
    # so it says them on two dedicated lines instead of gambling on width.
    _here_merits_label = tk.Label(_frame, text="Here: awaiting system data…", wraplength=_MAIN_PANEL_WRAP, justify=tk.LEFT)
    _here_merits_label.grid(row=4, column=0, columnspan=3, sticky=tk.W)

    _here_cp_label = tk.Label(_frame, text="", wraplength=_MAIN_PANEL_WRAP, justify=tk.LEFT)
    _here_cp_label.grid(row=5, column=0, columnspan=3, sticky=tk.W)

    separator2 = _separator(_frame)
    separator2.grid(row=6, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))

    _merits_label = tk.Label(_frame, text="Session merits: 0", wraplength=_MAIN_PANEL_WRAP, justify=tk.LEFT)
    _merits_label.grid(row=7, column=0, columnspan=3, sticky=tk.W)

    _cp_label = tk.Label(_frame, text="Session CP: —", wraplength=_MAIN_PANEL_WRAP, justify=tk.LEFT)
    _cp_label.grid(row=8, column=0, columnspan=3, sticky=tk.W)

    _credits_label = tk.Label(_frame, text="", wraplength=_MAIN_PANEL_WRAP, justify=tk.LEFT)
    _credits_label.grid(row=9, column=0, columnspan=3, sticky=tk.W)

    separator3 = _separator(_frame)
    separator3.grid(row=10, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))

    _last_event_label = tk.Label(
        _frame, text="No merit events yet this session.", wraplength=_MAIN_PANEL_WRAP, justify=tk.LEFT,
    )
    _last_event_label.grid(row=11, column=0, columnspan=3, sticky=tk.W)

    details_button = tk.Button(_frame, text="Sessions", command=on_show_details)
    details_button.grid(row=12, column=0, columnspan=3, sticky=tk.E, pady=(6, 0))

    # Everything but the title/status/version rows — those stay visible
    # while collapsed (status answers "am I pledged" at a glance, and the
    # version slot's "Updated to vX" confirmation should never be hidden by
    # collapsing the section), even though status now has its own row
    # rather than sharing the title's.
    _collapsible_widgets = [
        separator1, _system_label, _here_merits_label, _here_cp_label, separator2,
        _merits_label, _cp_label, _credits_label, separator3, _last_event_label, details_button,
    ]
    _apply_collapsed_state()

    _apply_version_state()
    theme.update(_frame)
    return _frame


def _title_text() -> str:
    return f"{'▸' if _collapsed else '▾'} EDPPMT:"


def _toggle_collapsed(_event: Optional[tk.Event] = None) -> None:
    global _collapsed
    _collapsed = not _collapsed
    config.set(CONFIG_COLLAPSED, _collapsed)
    _apply_collapsed_state()


def _apply_collapsed_state() -> None:
    if _title_label is not None:
        _title_label["text"] = _title_text()
    for widget in _collapsible_widgets:
        if _collapsed:
            widget.grid_remove()
        else:
            widget.grid()
    # credits_label's own visibility also depends on whether there's balance
    # data yet (see refresh()) — re-apply that on top of the blanket show
    # above rather than always forcing it visible on expand.
    if not _collapsed and _credits_label is not None and _last_credits_earned is None:
        _credits_label.grid_remove()


def _cp_by_activity(totals: Dict[str, int]) -> Dict[str, float]:
    """Est. CP per CP-earning activity that's actually earned something, from
    a raw {activity: merits} totals dict. Zero-merit activities are omitted
    rather than shown as "Acq 0" — keeps the whole-session summary line from
    listing every activity type regardless of whether it's contributed
    anything. (The current-system line wants the opposite — see
    _full_cp_bits — since knowing which activities are at *zero* here is
    exactly the point there.)"""
    return {
        activity: merits_to_cp(totals.get(activity, 0), ratio_for(activity))
        for activity in ACTIVITIES
        if activity not in NO_CP_ACTIVITIES and totals.get(activity, 0)
    }


def _session_cp_by_activity(session: dict) -> Dict[str, float]:
    """Est. CP per CP-earning activity for a whole session, from its raw merit totals."""
    return _cp_by_activity(session.get("totals", {}))


def _cp_bits(cp_by_activity: Dict[str, float]) -> str:
    """'Acq 30 · Reinf 12' from a {activity: cp} dict, in ACTIVITIES order."""
    return " · ".join(
        f"{_SHORT_ACTIVITY_LABELS[activity]} {cp_by_activity[activity]:.0f}"
        for activity in ACTIVITIES if activity in cp_by_activity
    )


def _full_cp_bits(totals: Dict[str, int]) -> str:
    """'Acq 30 · Reinf 0 · UM 0' — every CP-earning activity, zeros
    included, straight from a raw {activity: merits} totals dict. Unlike
    _cp_bits(_cp_by_activity(...)) (which omits zero activities to keep the
    whole-session summary line short), the current-system line needs to show
    the full per-activity CP breakdown even when most of it is zero, so it's
    obvious at a glance which activities this system has (and hasn't)
    contributed to."""
    return " · ".join(
        f"{_SHORT_ACTIVITY_LABELS[activity]} {merits_to_cp(totals.get(activity, 0), ratio_for(activity)):.0f}"
        for activity in ACTIVITIES
        if activity not in NO_CP_ACTIVITIES
    )


def _here_lines(session: dict, current_system: Optional[str]) -> Tuple[str, str]:
    """('Here: 142 merits', 'CP: Acq 30 · Reinf 0 · UM 0') for whatever
    system the commander is in right now — the full per-activity CP
    breakdown for that system specifically (not the whole session — see
    session.system_totals).

    Two separate lines by design, not one line left to wrap on its own: this
    row always has two distinct things to say (a merit count, and a
    three-activity CP breakdown), so it says them on two dedicated labels
    rather than gambling on whether one long line fits."""
    if not current_system:
        return "Here: awaiting system data…", ""

    merits = system_merit_total(session, current_system)
    cp_bits = _full_cp_bits(system_totals(session, current_system))
    return f"Here: {merits:,} merits", f"CP: {cp_bits}"


def refresh(sessions: SessionManager, pp: PowerplayTracker, current_system: Optional[str] = None) -> None:
    """Update the main-window summary strip from the live session."""
    global _last_credits_earned
    if _merits_label is None or _cp_label is None or _credits_label is None:
        return

    if _system_label is not None:
        _system_label["text"] = _system_summary(pp)

    session = sessions.current

    if _here_merits_label is not None and _here_cp_label is not None:
        here_merits_text, here_cp_text = _here_lines(session, current_system)
        _here_merits_label["text"] = here_merits_text
        _here_cp_label["text"] = here_cp_text

    merits = total_merits(session)
    cp_by_activity = _session_cp_by_activity(session)
    earned = credits_earned(session)

    _merits_label["text"] = f"Session merits: {merits:,}"
    _cp_label["text"] = f"Session CP: {_cp_bits(cp_by_activity)}"

    # Hidden (not just blank) until there's balance data to show, so the
    # row doesn't sit there empty between session start and the first
    # Cargo/Wallet event.
    _last_credits_earned = earned
    if earned is None:
        _credits_label.grid_remove()
    else:
        _credits_label["text"] = f"Credits: {earned:+,}"
        if not _collapsed:
            _credits_label.grid()


def _system_summary(pp: PowerplayTracker) -> str:
    """'Nervi — Exploited (Zachary Hudson)' for the main panel.

    Deliberately just the controller, not the full rival/contested-Powers
    list — that's the one thing here whose length is genuinely unbounded
    (a contested system can list several Powers), and it's already shown
    in full in the Sessions window's Current Session tab (the raw
    Controller/Powers line), which is a better home for it anyway since
    that's where you'd go to sanity-check a merit classification. Keeping
    it off the main panel keeps this row's width predictable."""
    if not pp.system_name:
        return "Awaiting system data…"
    state = pp.system_state or "no PP data"
    if pp.system_controller:
        detail = pp.system_controller
    elif pp.system_powers:
        detail = "contested"
    else:
        detail = "uncontested"
    return f"{pp.system_name} — {state} ({detail})"


def create_prefs(parent: nb.Notebook) -> nb.Frame:
    """Create the EDPPMT tab in EDMC's settings window.

    A small tab strip (Auto-Honk / CP Ratios / Updates) rather than one long
    scroll of unrelated settings — Auto-Honk in particular has enough moving
    parts (five controls plus live status/test feedback) that it was getting
    lost among the CP ratio entries stacked below it.
    """
    global _ratio_vars, _auto_update_var

    outer = nb.Frame(parent)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(1, weight=1)

    # Static - always shows the running version, regardless of auto-update
    # state (which only ever surfaces on the main panel, and only right
    # after an update is applied - see _apply_version_state).
    HyperlinkLabel(
        outer, text=f"EDPPMT v{__version__}", background=nb.Label().cget("background"), url=RELEASES_PAGE_URL, underline=True,
    ).grid(row=0, column=0, sticky=tk.W, padx=10, pady=(10, 6))

    tabs = nb.Notebook(outer)
    tabs.grid(row=1, column=0, sticky=tk.NSEW, padx=10, pady=(0, 10))

    autohonk_tab = nb.Frame(tabs)
    autohonk_tab.columnconfigure(0, weight=1)
    tabs.add(autohonk_tab, text="Auto-Honk")
    _create_autohonk_section(autohonk_tab)

    ratios_tab = nb.Frame(tabs)
    ratios_tab.columnconfigure(0, weight=1)
    tabs.add(ratios_tab, text="CP Ratios")
    _create_ratios_section(ratios_tab)

    updates_tab = nb.Frame(tabs)
    updates_tab.columnconfigure(0, weight=1)
    tabs.add(updates_tab, text="Updates")
    _create_updates_section(updates_tab)

    _apply_version_state()
    return outer


def _create_ratios_section(frame: nb.Frame) -> None:
    """Merit-to-Control-Point ratio overrides, one per CP-earning activity."""
    global _ratio_vars

    nb.Label(
        frame,
        text=(
            "Frontier doesn't publish these in the journal — the defaults are "
            "community-sourced best estimates. If your in-game CP totals don't "
            "line up, correct the ratio here (merits required for 1 CP)."
        ),
        wraplength=440,
        justify=tk.LEFT,
    ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 8))

    nb.Label(
        frame,
        text=(
            "Note: system strength/frontline penalties, ethos bonuses, and your "
            "Squadron's PP bonus are already baked into the merit amount the "
            "journal reports — these ratios only convert that final merit total "
            "into CP, so there's no separate bonus to account for here."
        ),
        wraplength=440,
        justify=tk.LEFT,
        foreground="#c07000",
    ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 10))

    _ratio_vars = {}
    row = 2
    for activity in ACTIVITIES:
        default = DEFAULT_RATIOS.get(activity)
        if default is None:
            continue

        nb.Label(frame, text=f"{ACTIVITY_LABELS[activity]}:").grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=2,
        )
        var = tk.StringVar(value=_format_ratio(ratio_for(activity)))
        _ratio_vars[activity] = var
        nb.EntryMenu(frame, textvariable=var, width=8).grid(
            row=row, column=1, sticky=tk.W, padx=(0, 10), pady=2,
        )
        row += 1


def _create_updates_section(frame: nb.Frame) -> None:
    """Auto-update opt-in."""
    global _auto_update_var

    _auto_update_var = tk.BooleanVar(value=config.get_bool(CONFIG_AUTO_UPDATE, default=False))
    nb.Checkbutton(
        frame,
        text="Automatically download updates (applied on EDMC's next restart)",
        variable=_auto_update_var,
    ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 2))


def _create_autohonk_section(frame: nb.Frame) -> None:
    """Auto-Honk (Discovery Scanner on jump) settings tab."""
    global _autohonk_enabled_var, _autohonk_firebutton_var, _autohonk_hold_var
    global _autohonk_focus_var, _autohonk_skipvisited_var
    global _autohonk_status_label, _autohonk_result_label, _autohonk_frame
    global _autohonk_dependent_widgets

    cfg = autohonk.load_config()
    _autohonk_frame = frame

    nb.Label(
        frame,
        text=(
            "Automatically fires your ship's Discovery Scanner — the basic system-wide "
            "\"honk\" that reveals bodies, not the Detailed Surface Scanner (that one only "
            "does anything while already in FSS mode) — every time you jump into a new "
            "system."
        ),
        wraplength=440,
        justify=tk.LEFT,
    ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 6))

    nb.Label(
        frame,
        text=(
            "If EDCoPilot is also running with its own Auto-Honk turned on, turn "
            "one of the two off — otherwise you'll get double honks."
        ),
        wraplength=440,
        justify=tk.LEFT,
        foreground="#c07000",
    ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 8))

    nb.Label(
        frame,
        text=(
            "To set this up: turn on \"Enable Auto-Honk\" below, check that \"Fire "
            "button\" matches whichever button your Discovery Scanner is actually "
            "bound to in-game (the status line will confirm the physical key), then "
            "click \"Test Honk Now\" while sitting in your ship to make sure it fires."
        ),
        wraplength=440,
        justify=tk.LEFT,
        foreground=_INFO_COLOR,
    ).grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 12))

    _autohonk_enabled_var = tk.BooleanVar(value=cfg.enabled)
    nb.Checkbutton(
        frame, text="Enable Auto-Honk", variable=_autohonk_enabled_var,
        command=_update_autohonk_dependent_state,
    ).grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=10, pady=2)

    # Everything below only takes effect once Auto-Honk is enabled above, so
    # it's indented under the checkbox and greys out with it (see
    # _update_autohonk_dependent_state) rather than sitting there looking
    # just as "live" as the checkbox itself.
    sub = nb.Frame(frame)
    sub.grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=(28, 10))

    # Fire button + hold duration on one row — both answer "how do we honk",
    # so they read as one setting rather than two.
    fire_row = tk.Frame(sub)
    fire_row.grid(row=0, column=0, sticky=tk.W, pady=2)
    nb.Label(fire_row, text="Fire button:").pack(side=tk.LEFT)
    _autohonk_firebutton_var = tk.StringVar(value=cfg.fire_button)
    firebutton_menu = tk.OptionMenu(fire_row, _autohonk_firebutton_var, *autohonk.FIRE_BUTTONS)
    firebutton_menu.pack(side=tk.LEFT, padx=(4, 0))
    nb.Label(fire_row, text="   Hold (sec):").pack(side=tk.LEFT)
    _autohonk_hold_var = tk.StringVar(value=_format_ratio(cfg.hold_ms / 1000))
    hold_entry = nb.EntryMenu(fire_row, textvariable=_autohonk_hold_var, width=5)
    hold_entry.pack(side=tk.LEFT, padx=(4, 0))

    # Both behavior toggles on one row for the same reason.
    behavior_row = tk.Frame(sub)
    behavior_row.grid(row=1, column=0, sticky=tk.W, pady=2)
    _autohonk_focus_var = tk.BooleanVar(value=cfg.focus_game_window)
    focus_check = nb.Checkbutton(
        behavior_row, text="Focus game window first", variable=_autohonk_focus_var,
    )
    focus_check.pack(side=tk.LEFT)
    _autohonk_skipvisited_var = tk.BooleanVar(value=cfg.skip_if_visited_this_session)
    skip_check = nb.Checkbutton(
        behavior_row, text="Skip systems already visited", variable=_autohonk_skipvisited_var,
    )
    skip_check.pack(side=tk.LEFT, padx=(16, 0))

    _autohonk_dependent_widgets = [firebutton_menu, hold_entry, focus_check, skip_check]

    _autohonk_status_label = nb.Label(frame, text="", wraplength=440, justify=tk.LEFT)
    _autohonk_status_label.grid(row=5, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 2))

    # Buttons and their one result label share a row so "do a thing" and
    # "here's what happened" stay visually paired. Deliberately outside the
    # indented/greyed-out `sub` block — these work as a standalone sanity
    # check regardless of the Enable checkbox (see _test_autohonk).
    action_row = tk.Frame(frame)
    action_row.grid(row=6, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 2))
    tk.Button(action_row, text="Rescan", command=_rescan_autohonk).pack(side=tk.LEFT)
    tk.Button(action_row, text="Test Honk Now", command=_test_autohonk).pack(side=tk.LEFT, padx=(6, 0))
    _autohonk_result_label = nb.Label(action_row, text="", wraplength=280, justify=tk.LEFT)
    _autohonk_result_label.pack(side=tk.LEFT, padx=(10, 0))

    nb.Label(
        frame,
        text="(These two work even while Auto-Honk is disabled above, so you can check your setup before turning it on.)",
        wraplength=440,
        justify=tk.LEFT,
    ).grid(row=7, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 10))

    _update_autohonk_dependent_state()
    _rescan_autohonk()


def _update_autohonk_dependent_state() -> None:
    """Greys out the fire-button/hold/behavior controls when Auto-Honk is
    off, so it's visually obvious they only matter once it's on. Rescan and
    Test Honk Now are deliberately left out of this — they're a standalone
    sanity check that works either way."""
    if _autohonk_enabled_var is None:
        return
    state = tk.NORMAL if _autohonk_enabled_var.get() else tk.DISABLED
    for widget in _autohonk_dependent_widgets:
        try:
            widget["state"] = state
        except tk.TclError:
            pass


def _autohonk_binding_text(fire_button: str) -> Tuple[str, str]:
    """(text, color) describing the current keybind resolution for
    fire_button — resolved fresh each call, not cached, so it always
    reflects the (possibly unsaved) fire-button choice in the dialog."""
    binding = autohonk.resolve_key_binding(fire_button)
    status = binding["status"]
    if status == "resolved":
        return f"Will press {binding['label']} when you jump into a system.", "#2e7d32"
    return autohonk.BINDING_STATUS_TEXT.get(status, status), "#c07000"


def _rescan_autohonk() -> None:
    """Re-reads the binds file and re-checks companion-app processes for
    the currently-selected (possibly unsaved) fire button."""
    if _autohonk_firebutton_var is None or _autohonk_status_label is None:
        return

    text, color = _autohonk_binding_text(_autohonk_firebutton_var.get())
    text = f"Status: {text}"
    conflicts = [name for exe, name in autohonk.COMPANION_APPS if autohonk.is_process_running(exe)]
    if conflicts:
        text += (
            "\n" + ", ".join(conflicts)
            + " is running — if its own Auto-Honk is also enabled, you'll get duplicate honks."
        )
    _autohonk_status_label["text"] = text
    _autohonk_status_label["foreground"] = color


def _set_autohonk_result(system: str, outcome: str) -> None:
    if _autohonk_result_label is None:
        return
    _autohonk_result_label["text"] = f"Last test ({system}): {autohonk.HONK_OUTCOME_TEXT.get(outcome, outcome)}"


def _test_autohonk() -> None:
    """Fires immediately using whatever is currently selected in the
    dialog (even if not yet saved) — works regardless of the Enable
    Auto-Honk checkbox, so it's a standalone sanity check of binding
    resolution + key injection without needing a real jump."""
    if _autohonk_firebutton_var is None or _autohonk_result_label is None:
        return

    fire_button = _autohonk_firebutton_var.get()
    focus_window = bool(_autohonk_focus_var.get()) if _autohonk_focus_var is not None else autohonk.DEFAULT_FOCUS
    try:
        hold_ms = max(1, round(float(_autohonk_hold_var.get()) * 1000)) if _autohonk_hold_var is not None else autohonk.DEFAULT_HOLD_MS
    except ValueError:
        hold_ms = autohonk.DEFAULT_HOLD_MS

    _autohonk_result_label["text"] = "Testing…"
    frame = _autohonk_frame

    def worker() -> None:
        binding = autohonk.resolve_key_binding(fire_button)
        if binding["status"] == "resolved":
            vk = autohonk.KEY_MAP[binding["raw_key"]][0]
            outcome = autohonk.send_key_press(vk, focus_window, hold_ms)
        else:
            outcome = "unresolved"

        if frame is not None:
            try:
                frame.after(0, lambda: _set_autohonk_result("Test", outcome))
            except tk.TclError:
                pass  # Settings dialog was closed before the test finished.

    threading.Thread(target=worker, name="EDPPMT-autohonk-test", daemon=True).start()


def save_prefs() -> None:
    """Persist ratio and update-preference settings from the prefs tab."""
    for activity, var in _ratio_vars.items():
        text = var.get().strip()
        try:
            value = float(text)
        except ValueError:
            continue
        if value <= 0:
            continue
        config.set(f"{CONFIG_RATIO_PREFIX}{activity}", str(value))

    if _auto_update_var is not None:
        config.set(CONFIG_AUTO_UPDATE, _auto_update_var.get())

    _save_autohonk_prefs()


def _save_autohonk_prefs() -> None:
    if _autohonk_enabled_var is None:
        return

    fire_button = _autohonk_firebutton_var.get() if _autohonk_firebutton_var is not None else autohonk.DEFAULT_FIRE_BUTTON
    if fire_button not in autohonk.FIRE_BUTTONS:
        fire_button = autohonk.DEFAULT_FIRE_BUTTON

    try:
        hold_ms = (
            max(1000, round(float(_autohonk_hold_var.get()) * 1000))
            if _autohonk_hold_var is not None
            else autohonk.DEFAULT_HOLD_MS
        )
    except ValueError:
        hold_ms = autohonk.DEFAULT_HOLD_MS

    autohonk.save_config(
        autohonk.AutoHonkConfig(
            enabled=bool(_autohonk_enabled_var.get()),
            fire_button=fire_button,
            focus_game_window=bool(_autohonk_focus_var.get()) if _autohonk_focus_var is not None else autohonk.DEFAULT_FOCUS,
            skip_if_visited_this_session=(
                bool(_autohonk_skipvisited_var.get()) if _autohonk_skipvisited_var is not None else autohonk.DEFAULT_SKIP_VISITED
            ),
            hold_ms=hold_ms,
        )
    )


def _format_ratio(value: float) -> str:
    return f"{value:g}"


def set_status(message: str) -> None:
    if _status_label is not None:
        _status_label["text"] = message


def set_last_event(message: str) -> None:
    if _last_event_label is not None:
        _last_event_label["text"] = message
        _last_event_label["foreground"] = "green"


def set_update_downloading(version: str) -> None:
    """An update is being downloaded in the background. Tracked but not
    currently rendered anywhere - see _apply_version_state."""
    global _version_state
    _version_state = ("downloading", version)
    _apply_version_state()


def set_update_downloaded(version: str) -> None:
    """An update has been staged and will apply on EDMC's next restart.
    Tracked but not currently rendered anywhere - see _apply_version_state."""
    global _version_state
    _version_state = ("downloaded", version)
    _apply_version_state()


def set_update_applied(version: str) -> None:
    """A staged update just took effect on this restart."""
    global _version_state
    _version_state = ("updated", version)
    _apply_version_state()


def _apply_version_state() -> None:
    """The main-panel version slot only ever shows text for the "updated"
    kind - "downloading"/"downloaded" are tracked (still logged by
    update.py itself) but deliberately produce no visible change here. The
    Settings tab's version label is fully static (see create_prefs) and is
    never touched by this function at all."""
    global _updated_clear_scheduled
    kind, version = _version_state
    if _version_label is None:
        return

    if kind == "updated" and version is not None:
        _version_label.configure(text=f"Updated to v{version}", url=RELEASES_PAGE_URL, foreground=_UPDATED_COLOR)
        _version_label.grid()
        if not _updated_clear_scheduled:
            _updated_clear_scheduled = True
            _version_label.after(_UPDATED_MESSAGE_DURATION_MS, _clear_updated_state)
    else:
        _version_label.grid_remove()


def _clear_updated_state() -> None:
    global _version_state, _updated_clear_scheduled
    _updated_clear_scheduled = False
    if _version_state[0] == "updated":
        _version_state = ("normal", None)
        try:
            _apply_version_state()
        except tk.TclError:
            pass  # Main window was closed before the timer fired.
