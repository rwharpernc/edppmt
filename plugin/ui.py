"""Tkinter UI for EDPPMT: main-window summary strip and the Settings tab."""

from __future__ import annotations

import logging
import os
from typing import Callable, Dict, Optional

import tkinter as tk

import myNotebook as nb
from config import appname, config
from theme import theme
from ttkHyperlinkLabel import HyperlinkLabel

from . import __version__
from .formulas import ACTIVITIES, ACTIVITY_LABELS, DEFAULT_RATIOS, NO_CP_ACTIVITIES, merits_to_cp
from .powerplay import PowerplayTracker
from .session import SessionManager, credits_earned, duration_hours, per_hour, total_merits
from .update import CONFIG_AUTO_UPDATE, RELEASES_PAGE_URL

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

CONFIG_RATIO_PREFIX = "edppmt_ratio_"

# Colors for the version/update HyperlinkLabel, keyed by _version_state's kind.
_VERSION_COLORS = {
    "normal": "#1e88c7",
    "downloading": "#c07000",
    "downloaded": "#d9534f",
    "updated": "#2e7d32",
}

_frame: Optional[tk.Frame] = None
_status_label: Optional[tk.Label] = None
_system_label: Optional[tk.Label] = None
_summary_label: Optional[tk.Label] = None
_last_event_label: Optional[tk.Label] = None
_version_label: Optional[HyperlinkLabel] = None
_prefs_version_label: Optional[HyperlinkLabel] = None
_ratio_vars: Dict[str, tk.StringVar] = {}
_auto_update_var: Optional[tk.BooleanVar] = None

# (kind, version) — kind is one of "normal", "downloading", "downloaded", "updated".
_version_state: tuple = ("normal", None)


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


def create_plugin_app(parent: tk.Frame, on_show_details: Callable[[], None]) -> tk.Frame:
    """Create the main-window frame for EDMC."""
    global _frame, _status_label, _system_label, _summary_label, _last_event_label, _version_label

    _frame = tk.Frame(parent)
    _frame.columnconfigure(1, weight=1)

    title = tk.Label(_frame, text="EDPPMT:")
    title.grid(row=0, column=0, sticky=tk.W, padx=(0, 4))

    _status_label = tk.Label(_frame, text="Awaiting PowerPlay activity…")
    _status_label.grid(row=0, column=1, sticky=tk.W)

    _version_label = HyperlinkLabel(
        _frame, text=f"v{__version__}", background=nb.Label().cget("background"), url=RELEASES_PAGE_URL, underline=True,
    )
    _version_label.grid(row=0, column=2, sticky=tk.E, padx=(4, 0))

    _system_label = tk.Label(_frame, text="", justify=tk.LEFT)
    _system_label.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(2, 0))

    _summary_label = tk.Label(_frame, text="", justify=tk.LEFT)
    _summary_label.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(2, 0))

    _last_event_label = tk.Label(_frame, text="", wraplength=420, justify=tk.LEFT)
    _last_event_label.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(2, 0))

    details_button = tk.Button(_frame, text="Sessions", command=on_show_details)
    details_button.grid(row=4, column=0, columnspan=3, sticky=tk.E, pady=(6, 0))

    _apply_version_state()
    theme.update(_frame)
    return _frame


def _session_cp(session: dict) -> float:
    """Est. CP for a single session, from its raw merit totals."""
    return sum(
        merits_to_cp(session.get("totals", {}).get(activity, 0), ratio_for(activity))
        for activity in ACTIVITIES
        if activity not in NO_CP_ACTIVITIES
    )


def refresh(sessions: SessionManager, pp: PowerplayTracker) -> None:
    """Update the main-window summary strip from the live session."""
    if _summary_label is None:
        return

    if _system_label is not None:
        _system_label["text"] = _system_summary(pp)

    session = sessions.current
    merits = total_merits(session)
    hours = duration_hours(session)
    cp_total = _session_cp(session)
    cumulative_cp = cp_total + sum(_session_cp(s) for s in sessions.history)
    earned = credits_earned(session)
    money_rate = per_hour(earned, hours) if earned is not None else None

    parts = [f"Merits: {merits}", f"Est. CP: {cp_total:.0f}", f"Total CP: {cumulative_cp:.0f}"]
    if hours > 0:
        parts.append(f"{per_hour(merits, hours):.0f}/hr")
    if earned is not None:
        parts.append(f"Cr: {earned:+,}")
        if money_rate is not None and hours > 0:
            parts.append(f"{money_rate:+,.0f} cr/hr")

    _summary_label["text"] = "   ".join(parts)


def _system_summary(pp: PowerplayTracker) -> str:
    """'System: Nervi — Exploited (Zachary Hudson)', for the main panel."""
    if not pp.system_name:
        return ""
    state = pp.system_state or "no PP data"
    powers = ", ".join(pp.system_powers) if pp.system_powers else "uncontested"
    return f"System: {pp.system_name} — {state} ({powers})"


def create_prefs(parent: nb.Notebook) -> nb.Frame:
    """Create the EDPPMT tab in EDMC's settings window."""
    global _ratio_vars, _auto_update_var, _prefs_version_label

    frame = nb.Frame(parent)
    frame.columnconfigure(0, weight=1)

    _prefs_version_label = HyperlinkLabel(
        frame, text=f"EDPPMT v{__version__}", background=nb.Label().cget("background"), url=RELEASES_PAGE_URL, underline=True,
    )
    _prefs_version_label.grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 2))

    nb.Label(
        frame,
        text="Merit-to-Control-Point ratios",
    ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 2))

    nb.Label(
        frame,
        text=(
            "Frontier doesn't publish these in the journal — the defaults are "
            "community-sourced best estimates. If your in-game CP totals don't "
            "line up, correct the ratio here (merits required for 1 CP)."
        ),
        wraplength=440,
        justify=tk.LEFT,
    ).grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 8))

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
    ).grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 10))

    _ratio_vars = {}
    row = 4
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
        return f"{plugin}v{version} downloaded — restart to apply"
    if kind == "updated":
        return f"{plugin}Updated to v{version}"
    return f"{plugin}v{__version__}"


def _apply_version_state() -> None:
    kind, version = _version_state
    color = _VERSION_COLORS.get(kind, _VERSION_COLORS["normal"])
    if _version_label is not None:
        _version_label.configure(text=_version_text(kind, version, prefixed=False), url=RELEASES_PAGE_URL, foreground=color)
    if _prefs_version_label is not None:
        _prefs_version_label.configure(text=_version_text(kind, version, prefixed=True), url=RELEASES_PAGE_URL, foreground=color)
