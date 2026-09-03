"""Tkinter UI for EDPPMT: main-window summary strip and the Settings tab."""

from __future__ import annotations

import logging
import os
import threading
from typing import Callable, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk

import myNotebook as nb
from config import appname, config
from theme import theme
from ttkHyperlinkLabel import HyperlinkLabel

from . import __version__
from . import autohonk
from . import interdiction
from . import landing
from . import overlay
from .clipboard import DEFAULT_TEMPLATE as DEFAULT_CLIPBOARD_TEMPLATE
from .clipboard import PLACEHOLDERS as CLIPBOARD_PLACEHOLDERS
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
CONFIG_CLIPBOARD_FORMAT = "edppmt_clipboard_format"

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
# ...) gets its wraplength kept in sync with the frame's own current width
# (see _on_frame_configure) rather than a single fixed guess. A fixed guess
# can only ever be wrong in one of two directions - too tight (380px, tried
# first) wrapped ordinary content, like a longer Power name in the pledge
# line, well before the panel's real available width; too loose (640px,
# tried next) let those same long lines render unwrapped and stretch the
# whole EDMC main window wider than it needs to be, since EDMC sizes its
# window to whatever's widest among every plugin it's running, this one
# included. Neither number can be "right" across installs anyway - font
# size/DPI scaling and how many other plugins are stacked above/below this
# one both change what width is actually available. Starting tight and
# growing to match the frame's real, already-established width means this
# plugin's own long lines are never themselves the reason the window grows.
_MAIN_PANEL_MIN_WRAP = 300

# Every label whose wraplength should track the frame's width - populated
# as each is created below, consumed by _on_frame_configure.
_wrap_labels: List[tk.Label] = []


def _wrap_label(parent: tk.Frame, **kwargs) -> tk.Label:
    """A tk.Label that starts at the tight end of _MAIN_PANEL_MIN_WRAP and
    registers itself to be widened by _on_frame_configure once the frame's
    real width is known."""
    label = tk.Label(parent, wraplength=_MAIN_PANEL_MIN_WRAP, justify=tk.LEFT, **kwargs)
    _wrap_labels.append(label)
    return label


def _on_frame_configure(event: tk.Event) -> None:
    """Widen every main-panel label's wraplength to match the frame's own
    current width - never wider, so this plugin can't feed its own growth
    back into the next layout pass (see _MAIN_PANEL_MIN_WRAP)."""
    wrap = max(_MAIN_PANEL_MIN_WRAP, event.width)
    for label in _wrap_labels:
        label.configure(wraplength=wrap)

_frame: Optional[tk.Frame] = None
_status_label: Optional[tk.Label] = None
_mode_label: Optional[tk.Label] = None
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
_clipboard_format_var: Optional[tk.StringVar] = None

# Main-panel collapse: title label doubles as the toggle, everything below
# the title/status/version rows hides when collapsed (those stay visible so
# pledge status is still visible at a glance, and a just-applied "Updated to
# vX" confirmation is never hidden by collapsing the section).
_title_label: Optional[tk.Label] = None
_collapsed: bool = False
_collapsible_widgets: List[tk.Widget] = []
_last_credits_earned: Optional[int] = None

# Main-panel quick-toggle buttons - flip Auto-Honk/Interdiction Warning/
# Landing Pad on or off without opening Settings, colored green when on. The
# click handlers below call straight into load.py (via the on_toggle_*
# callables passed to create_plugin_app) rather than touching config here
# directly, since load.py owns the live tracker instances that need a
# reload_config() nudge (Auto-Honk) or just a fresh load_config() read on
# their next event (Interdiction/Landing Pad).
_autohonk_toggle_btn: Optional[tk.Button] = None
_interdiction_toggle_btn: Optional[tk.Button] = None
_landing_toggle_btn: Optional[tk.Button] = None
_on_toggle_autohonk: Optional[Callable[[], bool]] = None
_on_toggle_interdiction: Optional[Callable[[], bool]] = None
_on_toggle_landing: Optional[Callable[[], bool]] = None

# Captured from the first toggle button's own defaults right after creation
# (before any color override) rather than hardcoded, so "off" always matches
# whatever EDMC's current theme actually renders a plain button as.
_toggle_off_colors: Tuple[str, str] = ("", "")
_TOGGLE_ON_BG = "#2e7d32"
_TOGGLE_ON_FG = "#ffffff"

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

_interdiction_enabled_var: Optional[tk.BooleanVar] = None
_overlay_host_var: Optional[tk.StringVar] = None
_overlay_port_var: Optional[tk.StringVar] = None
_interdiction_result_label: Optional[tk.Label] = None

# Host/port fields - only meaningful once Interdiction Warning is enabled,
# so they grey out together with it (see _update_interdiction_dependent_state).
# Test Warning is deliberately NOT in this list - same reasoning as
# Auto-Honk's Rescan/Test Honk Now (a standalone sanity check either way).
_interdiction_dependent_widgets: List[tk.Widget] = []

_landing_enabled_var: Optional[tk.BooleanVar] = None
_landing_result_label: Optional[tk.Label] = None

# Host/port fields here are the SAME _overlay_host_var/_overlay_port_var
# used by the Interdiction Warning tab (one shared EDMCOverlay connection,
# edited from either tab - see _create_landing_section). Test Overlay is
# deliberately NOT in this list, same reasoning as Interdiction's Test
# Warning.
_landing_dependent_widgets: List[tk.Widget] = []

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


def clipboard_template() -> str:
    """Current "Copy Progress" line format, from Settings or the default."""
    return config.get_str(CONFIG_CLIPBOARD_FORMAT) or DEFAULT_CLIPBOARD_TEMPLATE


def _separator(parent: tk.Frame) -> tk.Label:
    """A themed dash-rule label used to break the main panel into groups
    (header / system / session stats / last event) — plain tk.Label rather
    than ttk.Separator so theme.update() colors it the same as the rest of
    the panel without a second theming path to get wrong."""
    return tk.Label(parent, text="─" * 46, anchor=tk.W)


def create_plugin_app(
    parent: tk.Frame,
    on_show_details: Callable[[], None],
    on_show_rares: Callable[[], None],
    on_rescan: Callable[[], None],
    on_toggle_autohonk: Callable[[], bool],
    on_toggle_interdiction: Callable[[], bool],
    on_toggle_landing: Callable[[], bool],
) -> tk.Frame:
    """Create the main-window frame for EDMC."""
    global _frame, _status_label, _mode_label, _system_label, _here_merits_label, _here_cp_label
    global _merits_label, _cp_label, _credits_label
    global _last_event_label, _version_label, _title_label, _collapsed, _collapsible_widgets
    global _autohonk_toggle_btn, _interdiction_toggle_btn, _landing_toggle_btn
    global _on_toggle_autohonk, _on_toggle_interdiction, _on_toggle_landing, _toggle_off_colors

    _on_toggle_autohonk = on_toggle_autohonk
    _on_toggle_interdiction = on_toggle_interdiction
    _on_toggle_landing = on_toggle_landing

    _frame = tk.Frame(parent)
    _frame.columnconfigure(1, weight=1)
    _frame.bind("<Configure>", _on_frame_configure)

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
    _status_label = _wrap_label(_frame, text="Awaiting PowerPlay activity…")
    _status_label.grid(row=1, column=0, columnspan=3, sticky=tk.W)

    # Same visibility exemption as _status_label - which mode you're in is
    # identity info worth seeing at a glance even collapsed, same reasoning
    # as pledge status.
    _mode_label = _wrap_label(_frame, text="Mode: awaiting login…")
    _mode_label.grid(row=2, column=0, columnspan=3, sticky=tk.W)

    separator1 = _separator(_frame)
    separator1.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))

    _system_label = _wrap_label(_frame, text="Awaiting system data…")
    _system_label.grid(row=4, column=0, columnspan=3, sticky=tk.W)

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
    _here_merits_label = _wrap_label(_frame, text="Here: awaiting system data…")
    _here_merits_label.grid(row=5, column=0, columnspan=3, sticky=tk.W)

    _here_cp_label = _wrap_label(_frame, text="")
    _here_cp_label.grid(row=6, column=0, columnspan=3, sticky=tk.W)

    separator2 = _separator(_frame)
    separator2.grid(row=7, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))

    _merits_label = _wrap_label(_frame, text="Session merits: 0")
    _merits_label.grid(row=8, column=0, columnspan=3, sticky=tk.W)

    _cp_label = _wrap_label(_frame, text="Session CP: —")
    _cp_label.grid(row=9, column=0, columnspan=3, sticky=tk.W)

    _credits_label = _wrap_label(_frame, text="")
    _credits_label.grid(row=10, column=0, columnspan=3, sticky=tk.W)

    separator3 = _separator(_frame)
    separator3.grid(row=11, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))

    _last_event_label = _wrap_label(_frame, text="No merit events yet this session.")
    _last_event_label.grid(row=12, column=0, columnspan=3, sticky=tk.W)

    buttons_row = tk.Frame(_frame)
    buttons_row.grid(row=13, column=0, columnspan=3, sticky=tk.E, pady=(6, 0))
    rares_button = tk.Button(buttons_row, text="Rares", command=on_show_rares)
    rares_button.pack(side=tk.LEFT, padx=(0, 6))
    details_button = tk.Button(buttons_row, text="Sessions", command=on_show_details)
    details_button.pack(side=tk.LEFT, padx=(0, 6))
    rescan_button = tk.Button(buttons_row, text="Rescan", command=on_rescan)
    rescan_button.pack(side=tk.LEFT)

    # Quick on/off toggles for the three overlay/automation features, so
    # they can be flipped without opening Settings. Colored below, AFTER
    # theme.update() runs (see the sync_toggle_buttons() call at the bottom
    # of this function) - EDMC's theme engine repaints plain tk widgets'
    # colors when it walks the frame, which would otherwise stomp an
    # explicit color set here before that walk happens.
    toggle_row = tk.Frame(_frame)
    toggle_row.grid(row=14, column=0, columnspan=3, sticky=tk.W, pady=(4, 0))
    _autohonk_toggle_btn = tk.Button(toggle_row, text="Auto-Honk", command=_on_autohonk_toggle_click)
    _autohonk_toggle_btn.pack(side=tk.LEFT, padx=(0, 6))
    _interdiction_toggle_btn = tk.Button(toggle_row, text="Interdiction", command=_on_interdiction_toggle_click)
    _interdiction_toggle_btn.pack(side=tk.LEFT, padx=(0, 6))
    _landing_toggle_btn = tk.Button(toggle_row, text="Landing Pad", command=_on_landing_toggle_click)
    _landing_toggle_btn.pack(side=tk.LEFT)

    # Everything but the title/status/mode/version rows — those stay visible
    # while collapsed (status and mode answer "am I pledged" and "which
    # mode" at a glance, and the version slot's "Updated to vX" confirmation
    # should never be hidden by collapsing the section), even though they
    # now have their own rows rather than sharing the title's.
    _collapsible_widgets = [
        separator1, _system_label, _here_merits_label, _here_cp_label, separator2,
        _merits_label, _cp_label, _credits_label, separator3, _last_event_label, buttons_row, toggle_row,
    ]
    _apply_collapsed_state()

    _apply_version_state()
    theme.update(_frame)

    # Captured only now (plain tk.Button defaults are the same across all
    # three) rather than hardcoded, so the "off" color always matches
    # whatever EDMC's theme.update() above actually rendered a plain button
    # as - and applied after theme.update() for the same reason.
    _toggle_off_colors = (_autohonk_toggle_btn.cget("background"), _autohonk_toggle_btn.cget("foreground"))
    sync_toggle_buttons()

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


def _apply_toggle_button_state(button: tk.Button, enabled: bool) -> None:
    if enabled:
        bg, fg = _TOGGLE_ON_BG, _TOGGLE_ON_FG
    else:
        bg, fg = _toggle_off_colors
    try:
        button.configure(background=bg, foreground=fg, activebackground=bg, activeforeground=fg)
    except tk.TclError:
        pass  # Main window was closed mid-update.


def sync_toggle_buttons() -> None:
    """Re-colors the three main-panel toggle buttons from current config.
    Called right after Settings saves (load.prefs_changed) so a checkbox
    change there is reflected on the panel immediately, and once at panel
    creation for the initial state."""
    if _autohonk_toggle_btn is not None:
        _apply_toggle_button_state(_autohonk_toggle_btn, autohonk.load_config().enabled)
    if _interdiction_toggle_btn is not None:
        _apply_toggle_button_state(_interdiction_toggle_btn, interdiction.load_config().enabled)
    if _landing_toggle_btn is not None:
        _apply_toggle_button_state(_landing_toggle_btn, landing.load_config().enabled)


def _on_autohonk_toggle_click() -> None:
    if _on_toggle_autohonk is None or _autohonk_toggle_btn is None:
        return
    enabled = _on_toggle_autohonk()
    _apply_toggle_button_state(_autohonk_toggle_btn, enabled)
    if _autohonk_enabled_var is not None:
        _autohonk_enabled_var.set(enabled)
        _update_autohonk_dependent_state()


def _on_interdiction_toggle_click() -> None:
    if _on_toggle_interdiction is None or _interdiction_toggle_btn is None:
        return
    enabled = _on_toggle_interdiction()
    _apply_toggle_button_state(_interdiction_toggle_btn, enabled)
    if _interdiction_enabled_var is not None:
        _interdiction_enabled_var.set(enabled)
        _update_interdiction_dependent_state()


def _on_landing_toggle_click() -> None:
    if _on_toggle_landing is None or _landing_toggle_btn is None:
        return
    enabled = _on_toggle_landing()
    _apply_toggle_button_state(_landing_toggle_btn, enabled)
    if _landing_enabled_var is not None:
        _landing_enabled_var.set(enabled)
        _update_landing_dependent_state()


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


def _create_grouped_tab(
    notebook: nb.Notebook, tab_text: str, sections: List[Tuple[str, Callable[[nb.Frame], None]]],
) -> None:
    """One Settings sub-tab holding several stacked, titled sections (e.g.
    Tracking = CP Ratios + Clipboard) rather than a second level of nested
    tabs — cheaper to scan, and each section-builder is unchanged/reused
    as-is (it just gets its own child frame to grid into from row 0)."""
    tab = nb.Frame(notebook)
    tab.columnconfigure(0, weight=1)
    notebook.add(tab, text=tab_text)

    row = 0
    for index, (title, build_section) in enumerate(sections):
        if index > 0:
            ttk.Separator(tab, orient=tk.HORIZONTAL).grid(
                row=row, column=0, sticky=tk.EW, padx=10, pady=(8, 0),
            )
            row += 1
        nb.Label(tab, text=title, font=("TkDefaultFont", 9, "bold")).grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=(10, 2),
        )
        row += 1
        section = nb.Frame(tab)
        section.columnconfigure(0, weight=1)
        section.grid(row=row, column=0, sticky=tk.NSEW)
        row += 1
        build_section(section)


_SETTINGS_NOTEBOOK_STYLE = "EDPPMT.TNotebook"


def _style_settings_notebook() -> None:
    """The active ttk theme's default Notebook styling renders tabs with
    little to no visible border against the page background, so the tab
    strip doesn't read as a set of clickable tabs. Scoped to our own style
    name (rather than the bare "TNotebook"/"TNotebook.Tab" ttk uses
    everywhere else) so this doesn't bleed into EDMC's own outer
    plugin-tabs notebook or any other plugin's notebook."""
    style = ttk.Style()
    style.configure(f"{_SETTINGS_NOTEBOOK_STYLE}.Tab", padding=(10, 4), borderwidth=1, relief=tk.RAISED)
    style.map(f"{_SETTINGS_NOTEBOOK_STYLE}.Tab", relief=[("selected", tk.SUNKEN)])


def _create_single_tab(notebook: nb.Notebook, tab_text: str, build_section: Callable[[nb.Frame], None]) -> None:
    """One Settings sub-tab holding exactly one section — no group title
    needed above it since the tab's own label already says what it is."""
    tab = nb.Frame(notebook)
    tab.columnconfigure(0, weight=1)
    notebook.add(tab, text=tab_text)
    build_section(tab)


def create_prefs(parent: nb.Notebook) -> nb.Frame:
    """Create the EDPPMT tab in EDMC's settings window.

    One tab per feature rather than grouping unrelated ones under a
    generic "Alerts" tab (Auto-Honk isn't itself a warning/alert, it's an
    automation, so it gets top billing of its own):
    - **Tracking** — CP Ratios + Clipboard format: how merits are estimated
      and exported.
    - **Auto-Honk** — fires the Discovery Scanner on system entry.
    - **Interdiction Warning** — overlay warning when interdicted.
    - **Landing Pad** — overlay docking status + pad-layout diagram.
    - **Updates** — unchanged.
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

    # A visibly-bordered frame around the notebook — without it, the tab
    # strip sits flush against the page background and doesn't read as
    # tabs at all (see _style_settings_notebook for the tab-level styling,
    # which some ttk themes ignore; this border is the part every
    # platform/theme actually renders).
    notebook_border = tk.Frame(outer, relief=tk.GROOVE, borderwidth=2)
    notebook_border.grid(row=1, column=0, sticky=tk.NSEW, padx=10, pady=(0, 10))
    notebook_border.columnconfigure(0, weight=1)
    notebook_border.rowconfigure(0, weight=1)

    _style_settings_notebook()
    tabs = nb.Notebook(notebook_border, style=_SETTINGS_NOTEBOOK_STYLE)
    tabs.grid(row=0, column=0, sticky=tk.NSEW, padx=4, pady=4)

    _create_grouped_tab(
        tabs, "Tracking",
        [("CP Ratios", _create_ratios_section), ("Clipboard", _create_clipboard_section)],
    )
    _create_single_tab(tabs, "Auto-Honk", _create_autohonk_section)
    _create_single_tab(tabs, "Interdiction Warning", _create_interdiction_section)
    _create_single_tab(tabs, "Landing Pad", _create_landing_section)
    _create_single_tab(tabs, "Updates", _create_updates_section)

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


def _create_clipboard_section(frame: nb.Frame) -> None:
    """Format string for the Sessions window's "Copy Progress" button."""
    global _clipboard_format_var

    nb.Label(
        frame,
        text="Format for each system's line when \"Copy Progress\" (Sessions window) copies to the clipboard.",
        wraplength=440,
        justify=tk.LEFT,
    ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 6))

    nb.Label(
        frame,
        text="Placeholders: " + "  ".join(CLIPBOARD_PLACEHOLDERS),
        wraplength=440,
        justify=tk.LEFT,
        foreground=_INFO_COLOR,
    ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 8))

    _clipboard_format_var = tk.StringVar(value=clipboard_template())
    nb.EntryMenu(frame, textvariable=_clipboard_format_var, width=60).grid(
        row=2, column=0, sticky=tk.W, padx=10, pady=2,
    )

    def _reset_default() -> None:
        if _clipboard_format_var is not None:
            _clipboard_format_var.set(DEFAULT_CLIPBOARD_TEMPLATE)

    tk.Button(frame, text="Reset to default", command=_reset_default).grid(
        row=2, column=1, sticky=tk.W, padx=(6, 10), pady=2,
    )


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


def _create_interdiction_section(frame: nb.Frame) -> None:
    """Interdiction Warning: draws a warning on the in-game overlay when an
    interdiction starts, via the separate EDMCOverlay helper app."""
    global _interdiction_enabled_var, _overlay_host_var, _overlay_port_var
    global _interdiction_result_label, _interdiction_dependent_widgets

    interdiction_cfg = interdiction.load_config()
    overlay_cfg = overlay.load_config()

    nb.Label(
        frame,
        text=(
            "Shows a warning on your in-game overlay the moment an interdiction starts — before it "
            "resolves — via EDMCOverlay, a separate, optional helper app EDPPMT does not install or "
            "launch itself."
        ),
        wraplength=440,
        justify=tk.LEFT,
    ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 4))

    HyperlinkLabel(
        frame, text="Get EDMCOverlay", background=nb.Label().cget("background"),
        url="https://github.com/inorton/EDMCOverlay", underline=True,
    ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 8))

    _interdiction_enabled_var = tk.BooleanVar(value=interdiction_cfg.enabled)
    nb.Checkbutton(
        frame, text="Enable Interdiction Warning", variable=_interdiction_enabled_var,
        command=_update_interdiction_dependent_state,
    ).grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=10, pady=2)

    sub = nb.Frame(frame)
    sub.grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=(28, 10))

    host_row = tk.Frame(sub)
    host_row.grid(row=0, column=0, sticky=tk.W, pady=2)
    nb.Label(host_row, text="EDMCOverlay host:").pack(side=tk.LEFT)
    _overlay_host_var = tk.StringVar(value=overlay_cfg.host)
    host_entry = nb.EntryMenu(host_row, textvariable=_overlay_host_var, width=12)
    host_entry.pack(side=tk.LEFT, padx=(4, 0))
    nb.Label(host_row, text="   Port:").pack(side=tk.LEFT)
    _overlay_port_var = tk.StringVar(value=overlay_cfg.port)
    port_entry = nb.EntryMenu(host_row, textvariable=_overlay_port_var, width=6)
    port_entry.pack(side=tk.LEFT, padx=(4, 0))

    _interdiction_dependent_widgets = [host_entry, port_entry]

    action_row = tk.Frame(frame)
    action_row.grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(6, 2))
    tk.Button(action_row, text="Test Warning", command=_test_interdiction).pack(side=tk.LEFT)
    _interdiction_result_label = nb.Label(action_row, text="", wraplength=320, justify=tk.LEFT)
    _interdiction_result_label.pack(side=tk.LEFT, padx=(10, 0))

    nb.Label(
        frame,
        text="(Test Warning works even while disabled above, and reports whether EDMCOverlay was actually reachable.)",
        wraplength=440,
        justify=tk.LEFT,
    ).grid(row=5, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 10))

    _update_interdiction_dependent_state()


def _update_interdiction_dependent_state() -> None:
    if _interdiction_enabled_var is None:
        return
    state = tk.NORMAL if _interdiction_enabled_var.get() else tk.DISABLED
    for widget in _interdiction_dependent_widgets:
        try:
            widget["state"] = state
        except tk.TclError:
            pass


def _test_interdiction() -> None:
    """Simulates a full interdiction lifecycle through the real detection
    pipeline (see interdiction.InterdictionTracker.trigger_test), rendering
    against whatever host/port is currently in the dialog (even if not yet
    saved) so the actual overlay send can be checked — unlike the live path,
    a failure here is reported, not silently swallowed."""
    if _interdiction_result_label is None:
        return

    cfg = overlay.OverlayConfig(
        host=_overlay_host_var.get() if _overlay_host_var is not None else overlay.DEFAULT_HOST,
        port=_overlay_port_var.get() if _overlay_port_var is not None else overlay.DEFAULT_PORT,
    )
    client = overlay.OverlayClient(cfg)
    frame = _interdiction_result_label

    def worker() -> None:
        try:
            interdiction.render(
                interdiction.InterdictionSnapshot(
                    active=True, interdictor_name="CMDR Test Hostile", is_player=True, is_thargoid=False,
                ),
                client,
            )
            outcome, color = "Sent — check your overlay.", "#2e7d32"
        except OSError as err:
            outcome, color = f"Could not reach EDMCOverlay at {cfg.host}:{cfg.port} ({err}).", "#c07000"

        try:
            frame.after(0, lambda: (frame.configure(text=outcome, foreground=color)))
        except tk.TclError:
            pass  # Settings dialog was closed before the test finished.

    threading.Thread(target=worker, name="EDPPMT-interdiction-test", daemon=True).start()


def _create_landing_section(frame: nb.Frame) -> None:
    """Landing Pad: draws docking status (requested/approved/denied) and a
    pad-layout diagram on the in-game overlay, via the same EDMCOverlay
    helper app as Interdiction Warning."""
    global _landing_enabled_var, _overlay_host_var, _overlay_port_var
    global _landing_result_label, _landing_dependent_widgets

    landing_cfg = landing.load_config()
    overlay_cfg = overlay.load_config()

    nb.Label(
        frame,
        text=(
            "Shows docking status and a pad-layout diagram (which pad you're assigned) on your "
            "in-game overlay while requesting/approaching a dock, via EDMCOverlay, a separate, "
            "optional helper app EDPPMT does not install or launch itself."
        ),
        wraplength=440,
        justify=tk.LEFT,
    ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 4))

    HyperlinkLabel(
        frame, text="Get EDMCOverlay", background=nb.Label().cget("background"),
        url="https://github.com/inorton/EDMCOverlay", underline=True,
    ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 8))

    _landing_enabled_var = tk.BooleanVar(value=landing_cfg.enabled)
    nb.Checkbutton(
        frame, text="Enable Landing Pad overlay", variable=_landing_enabled_var,
        command=_update_landing_dependent_state,
    ).grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=10, pady=2)

    sub = nb.Frame(frame)
    sub.grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=(28, 10))

    host_row = tk.Frame(sub)
    host_row.grid(row=0, column=0, sticky=tk.W, pady=2)
    nb.Label(host_row, text="EDMCOverlay host:").pack(side=tk.LEFT)
    # Same connection as Interdiction Warning — _overlay_host_var/_overlay_port_var
    # are reused here rather than duplicated, so there's exactly one set of
    # values in memory regardless of which tab was opened last.
    if _overlay_host_var is None:
        _overlay_host_var = tk.StringVar(value=overlay_cfg.host)
    host_entry = nb.EntryMenu(host_row, textvariable=_overlay_host_var, width=12)
    host_entry.pack(side=tk.LEFT, padx=(4, 0))
    nb.Label(host_row, text="   Port:").pack(side=tk.LEFT)
    if _overlay_port_var is None:
        _overlay_port_var = tk.StringVar(value=overlay_cfg.port)
    port_entry = nb.EntryMenu(host_row, textvariable=_overlay_port_var, width=6)
    port_entry.pack(side=tk.LEFT, padx=(4, 0))

    _landing_dependent_widgets = [host_entry, port_entry]

    action_row = tk.Frame(frame)
    action_row.grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(6, 2))
    tk.Button(action_row, text="Test Overlay", command=_test_landing).pack(side=tk.LEFT)
    _landing_result_label = nb.Label(action_row, text="", wraplength=320, justify=tk.LEFT)
    _landing_result_label.pack(side=tk.LEFT, padx=(10, 0))

    nb.Label(
        frame,
        text="(Test Overlay works even while disabled above, and reports whether EDMCOverlay was actually reachable.)",
        wraplength=440,
        justify=tk.LEFT,
    ).grid(row=5, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 10))

    _update_landing_dependent_state()


def _update_landing_dependent_state() -> None:
    if _landing_enabled_var is None:
        return
    state = tk.NORMAL if _landing_enabled_var.get() else tk.DISABLED
    for widget in _landing_dependent_widgets:
        try:
            widget["state"] = state
        except tk.TclError:
            pass


def _test_landing() -> None:
    """Simulates a "Docking Approved" state (a starport, Pad 24) through the
    real render() path, against whatever host/port is currently in the
    dialog (even if not yet saved) - same reasoning as _test_interdiction."""
    if _landing_result_label is None:
        return

    cfg = overlay.OverlayConfig(
        host=_overlay_host_var.get() if _overlay_host_var is not None else overlay.DEFAULT_HOST,
        port=_overlay_port_var.get() if _overlay_port_var is not None else overlay.DEFAULT_PORT,
    )
    client = overlay.OverlayClient(cfg)
    frame = _landing_result_label

    def worker() -> None:
        try:
            landing.render(
                landing.LandingDisplayInfo(
                    status_label="Docking Approved", station="Preview Station", pad=24,
                    diagram_type="starport", show_diagram=True,
                ),
                None,
                client,
            )
            outcome, color = "Sent — check your overlay.", "#2e7d32"
        except OSError as err:
            outcome, color = f"Could not reach EDMCOverlay at {cfg.host}:{cfg.port} ({err}).", "#c07000"

        try:
            frame.after(0, lambda: (frame.configure(text=outcome, foreground=color)))
        except tk.TclError:
            pass  # Settings dialog was closed before the test finished.

    threading.Thread(target=worker, name="EDPPMT-landing-test", daemon=True).start()


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

    if _clipboard_format_var is not None:
        text = _clipboard_format_var.get()
        config.set(CONFIG_CLIPBOARD_FORMAT, text if text.strip() else DEFAULT_CLIPBOARD_TEMPLATE)

    _save_autohonk_prefs()
    _save_interdiction_prefs()
    _save_landing_prefs()


def _save_interdiction_prefs() -> None:
    if _interdiction_enabled_var is None:
        return

    interdiction.save_config(interdiction.InterdictionConfig(enabled=bool(_interdiction_enabled_var.get())))
    _save_overlay_connection_prefs()


def _save_landing_prefs() -> None:
    if _landing_enabled_var is None:
        return

    landing.save_config(landing.LandingConfig(enabled=bool(_landing_enabled_var.get())))
    # Reaches the same config keys as _save_interdiction_prefs — harmless to
    # write twice from one _overlay_host_var/_overlay_port_var pair, and
    # keeps this function self-contained if the Interdiction tab is ever
    # made optional/removed.
    _save_overlay_connection_prefs()


def _save_overlay_connection_prefs() -> None:
    overlay.save_config(
        overlay.OverlayConfig(
            host=(_overlay_host_var.get().strip() if _overlay_host_var is not None else "") or overlay.DEFAULT_HOST,
            port=(_overlay_port_var.get().strip() if _overlay_port_var is not None else "") or overlay.DEFAULT_PORT,
        )
    )


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


def set_mode(message: str) -> None:
    if _mode_label is not None:
        _mode_label["text"] = message


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
