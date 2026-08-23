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
from .session import SessionManager, credits_earned, total_merits
from .update import CONFIG_AUTO_UPDATE, RELEASES_PAGE_URL

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

CONFIG_RATIO_PREFIX = "edppmt_ratio_"
CONFIG_COLLAPSED = "edppmt_main_collapsed"

# Colors for the version/update HyperlinkLabel, keyed by _version_state's kind.
_VERSION_COLORS = {
    "normal": "#1e88c7",
    "downloading": "#c07000",
    "downloaded": "#d9534f",
    "updated": "#2e7d32",
}

# How long "Updated to vX" stays up on the main panel before reverting to a
# plain version number on its own — long enough to notice, short enough that
# you don't need to restart EDMC a second time just to clear it.
_UPDATED_MESSAGE_DURATION_MS = 15_000

# Short activity labels for the session CP breakdown, where "Reinforcement"
# and "Undermining" spelled out would run the main panel too wide.
_SHORT_ACTIVITY_LABELS: Dict[str, str] = {
    ACQUISITION: "Acq",
    REINFORCEMENT: "Reinf",
    UNDERMINING: "UM",
}

# Every main-panel row whose text is built from live, unbounded data (a
# system/Power name, a merit count, ...) gets this wraplength, so a long
# value wraps onto a second line instead of stretching the whole EDMC main
# window wider than its default width. Chosen to match EDMC's own default
# main-window width, not the plugin's content.
_MAIN_PANEL_WRAP = 380

_frame: Optional[tk.Frame] = None
_status_label: Optional[tk.Label] = None
_system_label: Optional[tk.Label] = None
_merits_label: Optional[tk.Label] = None
_cp_label: Optional[tk.Label] = None
_credits_label: Optional[tk.Label] = None
_last_event_label: Optional[tk.Label] = None
_version_label: Optional[HyperlinkLabel] = None
_prefs_version_label: Optional[HyperlinkLabel] = None
_ratio_vars: Dict[str, tk.StringVar] = {}
_auto_update_var: Optional[tk.BooleanVar] = None

# Main-panel collapse: title label doubles as the toggle, everything below
# the title/status/version row hides when collapsed (version stays visible
# so an update-pending message is never hidden by collapsing the section).
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
    global _frame, _status_label, _system_label, _merits_label, _cp_label, _credits_label
    global _last_event_label, _version_label, _title_label, _collapsed, _collapsible_widgets

    _frame = tk.Frame(parent)
    _frame.columnconfigure(1, weight=1)

    _collapsed = config.get_bool(CONFIG_COLLAPSED, default=False)

    _title_label = tk.Label(_frame, text=_title_text(), cursor="hand2")
    _title_label.grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
    _title_label.bind("<Button-1>", _toggle_collapsed)

    _status_label = tk.Label(_frame, text="Awaiting PowerPlay activity…", wraplength=_MAIN_PANEL_WRAP)
    _status_label.grid(row=0, column=1, sticky=tk.W)

    _version_label = HyperlinkLabel(
        _frame, text=f"v{__version__}", background=nb.Label().cget("background"), url=RELEASES_PAGE_URL, underline=True,
    )
    _version_label.grid(row=0, column=2, sticky=tk.E, padx=(4, 0))

    separator1 = _separator(_frame)
    separator1.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))

    _system_label = tk.Label(_frame, text="Awaiting system data…", wraplength=_MAIN_PANEL_WRAP, justify=tk.LEFT)
    _system_label.grid(row=2, column=0, columnspan=3, sticky=tk.W)

    separator2 = _separator(_frame)
    separator2.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))

    _merits_label = tk.Label(_frame, text="Merits: 0", wraplength=_MAIN_PANEL_WRAP, justify=tk.LEFT)
    _merits_label.grid(row=4, column=0, columnspan=3, sticky=tk.W)

    _cp_label = tk.Label(_frame, text="CP: —", wraplength=_MAIN_PANEL_WRAP, justify=tk.LEFT)
    _cp_label.grid(row=5, column=0, columnspan=3, sticky=tk.W)

    _credits_label = tk.Label(_frame, text="", wraplength=_MAIN_PANEL_WRAP, justify=tk.LEFT)
    _credits_label.grid(row=6, column=0, columnspan=3, sticky=tk.W)

    separator3 = _separator(_frame)
    separator3.grid(row=7, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))

    _last_event_label = tk.Label(
        _frame, text="No merit events yet this session.", wraplength=_MAIN_PANEL_WRAP, justify=tk.LEFT,
    )
    _last_event_label.grid(row=8, column=0, columnspan=3, sticky=tk.W)

    details_button = tk.Button(_frame, text="Sessions", command=on_show_details)
    details_button.grid(row=9, column=0, columnspan=3, sticky=tk.E, pady=(6, 0))

    # Everything but the title/status/version row — that row stays visible
    # while collapsed so an update-pending message is never hidden by it.
    _collapsible_widgets = [
        separator1, _system_label, separator2, _merits_label, _cp_label,
        _credits_label, separator3, _last_event_label, details_button,
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


def _session_cp_by_activity(session: dict) -> Dict[str, float]:
    """Est. CP per CP-earning activity for a single session, from its raw merit totals."""
    totals = session.get("totals", {})
    return {
        activity: merits_to_cp(totals.get(activity, 0), ratio_for(activity))
        for activity in ACTIVITIES
        if activity not in NO_CP_ACTIVITIES
    }


def refresh(sessions: SessionManager, pp: PowerplayTracker) -> None:
    """Update the main-window summary strip from the live session."""
    global _last_credits_earned
    if _merits_label is None or _cp_label is None or _credits_label is None:
        return

    if _system_label is not None:
        _system_label["text"] = _system_summary(pp)

    session = sessions.current
    merits = total_merits(session)
    cp_by_activity = _session_cp_by_activity(session)
    earned = credits_earned(session)

    _merits_label["text"] = f"Merits: {merits:,}"

    cp_bits = " · ".join(
        f"{_SHORT_ACTIVITY_LABELS[activity]} {cp_by_activity[activity]:.0f}" for activity in ACTIVITIES if activity in cp_by_activity
    )
    _cp_label["text"] = f"CP: {cp_bits}"

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
    """Create the EDPPMT tab in EDMC's settings window."""
    global _ratio_vars, _auto_update_var, _prefs_version_label, _autohonk_frame

    frame = nb.Frame(parent)
    frame.columnconfigure(0, weight=1)
    _autohonk_frame = frame

    _prefs_version_label = HyperlinkLabel(
        frame, text=f"EDPPMT v{__version__}", background=nb.Label().cget("background"), url=RELEASES_PAGE_URL, underline=True,
    )
    _prefs_version_label.grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 2))
    row = 1

    row = _create_autohonk_section(frame, row)

    nb.Label(
        frame,
        text="Merit-to-Control-Point ratios",
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 2))
    row += 1

    nb.Label(
        frame,
        text=(
            "Frontier doesn't publish these in the journal — the defaults are "
            "community-sourced best estimates. If your in-game CP totals don't "
            "line up, correct the ratio here (merits required for 1 CP)."
        ),
        wraplength=440,
        justify=tk.LEFT,
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 8))
    row += 1

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
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 10))
    row += 1

    _ratio_vars = {}
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

    nb.Label(
        frame,
        text="Updates",
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(16, 2))
    row += 1

    _auto_update_var = tk.BooleanVar(value=config.get_bool(CONFIG_AUTO_UPDATE, default=True))
    nb.Checkbutton(
        frame,
        text="Automatically download updates (applied on EDMC's next restart)",
        variable=_auto_update_var,
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=2)
    row += 1

    _apply_version_state()
    return frame


def _create_autohonk_section(frame: nb.Frame, row: int) -> int:
    """Auto-Honk (Discovery Scanner on jump) settings block. Returns the
    next free grid row."""
    global _autohonk_enabled_var, _autohonk_firebutton_var, _autohonk_hold_var
    global _autohonk_focus_var, _autohonk_skipvisited_var
    global _autohonk_status_label, _autohonk_result_label

    cfg = autohonk.load_config()

    nb.Label(
        frame, text="Auto-Honk (Discovery Scanner on jump)",
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(14, 2))
    row += 1

    nb.Label(
        frame,
        text=(
            "Automatically fires your ship's Discovery Scanner — the basic system-wide "
            "\"honk\" that reveals bodies, not the Detailed Surface Scanner (that one only "
            "does anything while already in FSS mode) — every time you jump into a new "
            "system. Modeled on EDCoPilot's own AutoHonk feature; if EDCoPilot is also "
            "running with its AutoHonk on, turn one off below to avoid double-honking."
        ),
        wraplength=440,
        justify=tk.LEFT,
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 8))
    row += 1

    _autohonk_enabled_var = tk.BooleanVar(value=cfg.enabled)
    nb.Checkbutton(
        frame, text="Enable Auto-Honk", variable=_autohonk_enabled_var,
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=2)
    row += 1

    # Fire button + hold duration on one row — both answer "how do we honk",
    # so they read as one setting rather than two.
    nb.Label(frame, text="Fire button:").grid(row=row, column=0, sticky=tk.W, padx=10, pady=2)
    fire_row = tk.Frame(frame)
    fire_row.grid(row=row, column=1, sticky=tk.W, padx=(0, 10), pady=2)
    _autohonk_firebutton_var = tk.StringVar(value=cfg.fire_button)
    tk.OptionMenu(fire_row, _autohonk_firebutton_var, *autohonk.FIRE_BUTTONS).pack(side=tk.LEFT)
    nb.Label(fire_row, text="   Hold (sec):").pack(side=tk.LEFT)
    _autohonk_hold_var = tk.StringVar(value=_format_ratio(cfg.hold_ms / 1000))
    nb.EntryMenu(fire_row, textvariable=_autohonk_hold_var, width=5).pack(side=tk.LEFT, padx=(4, 0))
    row += 1

    # Both behavior toggles on one row for the same reason.
    behavior_row = tk.Frame(frame)
    behavior_row.grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=2)
    _autohonk_focus_var = tk.BooleanVar(value=cfg.focus_game_window)
    nb.Checkbutton(
        behavior_row, text="Focus game window first", variable=_autohonk_focus_var,
    ).pack(side=tk.LEFT)
    _autohonk_skipvisited_var = tk.BooleanVar(value=cfg.skip_if_visited_this_session)
    nb.Checkbutton(
        behavior_row, text="Skip systems already visited", variable=_autohonk_skipvisited_var,
    ).pack(side=tk.LEFT, padx=(16, 0))
    row += 1

    _autohonk_status_label = nb.Label(frame, text="", wraplength=440, justify=tk.LEFT)
    _autohonk_status_label.grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(4, 2))
    row += 1

    # Buttons and their one result label share a row so "do a thing" and
    # "here's what happened" stay visually paired.
    action_row = tk.Frame(frame)
    action_row.grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 6))
    tk.Button(action_row, text="Rescan", command=_rescan_autohonk).pack(side=tk.LEFT)
    tk.Button(action_row, text="Test Honk Now", command=_test_autohonk).pack(side=tk.LEFT, padx=(6, 0))
    _autohonk_result_label = nb.Label(action_row, text="", wraplength=280, justify=tk.LEFT)
    _autohonk_result_label.pack(side=tk.LEFT, padx=(10, 0))
    row += 1

    _rescan_autohonk()
    return row


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
    """An update is being downloaded in the background."""
    global _version_state
    _version_state = ("downloading", version)
    _apply_version_state()


def set_update_downloaded(version: str) -> None:
    """An update has been staged and will apply on EDMC's next restart."""
    global _version_state
    _version_state = ("downloaded", version)
    _apply_version_state()


def set_update_applied(version: str) -> None:
    """A staged update just took effect on this restart."""
    global _version_state
    _version_state = ("updated", version)
    _apply_version_state()


def _version_text(kind: str, version: Optional[str], *, prefixed: bool) -> str:
    # The main-window label sits next to an "EDPPMT:" title, so it stays
    # short; the prefs-tab label has no such title, so it names the plugin.
    plugin = "EDPPMT " if prefixed else ""
    if kind == "downloading":
        return f"{plugin}Downloading v{version}…"
    if kind == "downloaded":
        return f"{plugin}Restart to Update (v{version})"
    if kind == "updated":
        return f"{plugin}Updated to v{version}"
    return f"{plugin}v{__version__}"


def _apply_version_state() -> None:
    global _updated_clear_scheduled
    kind, version = _version_state
    color = _VERSION_COLORS.get(kind, _VERSION_COLORS["normal"])
    if _version_label is not None:
        _version_label.configure(text=_version_text(kind, version, prefixed=False), url=RELEASES_PAGE_URL, foreground=color)
    if _prefs_version_label is not None:
        _prefs_version_label.configure(text=_version_text(kind, version, prefixed=True), url=RELEASES_PAGE_URL, foreground=color)

    # "Updated to vX" is only interesting right after the restart that
    # applied it — clear it back to a plain version number on its own after
    # a while instead of leaving it stuck until yet another restart.
    if kind == "updated" and not _updated_clear_scheduled and _version_label is not None:
        _updated_clear_scheduled = True
        _version_label.after(_UPDATED_MESSAGE_DURATION_MS, _clear_updated_state)


def _clear_updated_state() -> None:
    global _version_state, _updated_clear_scheduled
    _updated_clear_scheduled = False
    if _version_state[0] == "updated":
        _version_state = ("normal", None)
        try:
            _apply_version_state()
        except tk.TclError:
            pass  # Main window was closed before the timer fired.
