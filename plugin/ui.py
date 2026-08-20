"""Tkinter UI for EDPPMT: main-window summary strip and the Settings tab."""

from __future__ import annotations

import logging
import os
from typing import Callable, Dict, Optional

import tkinter as tk

import myNotebook as nb
from config import appname, config
from theme import theme

from .formulas import ACTIVITIES, ACTIVITY_LABELS, DEFAULT_RATIOS, UNKNOWN, merits_to_cp
from .session import SessionManager, credits_earned, duration_hours, per_hour, total_merits

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

CONFIG_RATIO_PREFIX = "edppmt_ratio_"

_frame: Optional[tk.Frame] = None
_status_label: Optional[tk.Label] = None
_summary_label: Optional[tk.Label] = None
_last_event_label: Optional[tk.Label] = None
_ratio_vars: Dict[str, tk.StringVar] = {}


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
    global _frame, _status_label, _summary_label, _last_event_label

    _frame = tk.Frame(parent)
    _frame.columnconfigure(1, weight=1)

    title = tk.Label(_frame, text="EDPPMT:")
    title.grid(row=0, column=0, sticky=tk.W, padx=(0, 4))

    _status_label = tk.Label(_frame, text="Awaiting PowerPlay activity…")
    _status_label.grid(row=0, column=1, sticky=tk.W)

    details_button = tk.Button(_frame, text="Sessions", command=on_show_details)
    details_button.grid(row=0, column=2, sticky=tk.E, padx=(4, 0))

    _summary_label = tk.Label(_frame, text="", justify=tk.LEFT)
    _summary_label.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(2, 0))

    _last_event_label = tk.Label(_frame, text="", wraplength=420, justify=tk.LEFT)
    _last_event_label.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(2, 0))

    theme.update(_frame)
    return _frame


def refresh(sessions: SessionManager) -> None:
    """Update the main-window summary strip from the live session."""
    if _summary_label is None:
        return

    session = sessions.current
    merits = total_merits(session)
    hours = duration_hours(session)
    cp_total = sum(
        merits_to_cp(session["totals"].get(activity, 0), ratio_for(activity))
        for activity in ACTIVITIES
        if activity != UNKNOWN
    )
    earned = credits_earned(session)
    money_rate = per_hour(earned, hours) if earned is not None else None

    parts = [f"Merits: {merits}", f"Est. CP: {cp_total:.0f}"]
    if hours > 0:
        parts.append(f"{per_hour(merits, hours):.0f}/hr")
    if earned is not None:
        parts.append(f"Cr: {earned:+,}")
        if money_rate is not None and hours > 0:
            parts.append(f"{money_rate:+,.0f} cr/hr")

    _summary_label["text"] = "   ".join(parts)


def create_prefs(parent: nb.Notebook) -> nb.Frame:
    """Create the EDPPMT tab in EDMC's settings window."""
    global _ratio_vars

    frame = nb.Frame(parent)
    frame.columnconfigure(0, weight=1)

    nb.Label(
        frame,
        text="Merit-to-Control-Point ratios",
    ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 2))

    nb.Label(
        frame,
        text=(
            "Frontier doesn't publish these in the journal — the defaults are "
            "community-sourced best estimates. If your in-game CP totals don't "
            "line up, correct the ratio here (merits required for 1 CP)."
        ),
        wraplength=440,
        justify=tk.LEFT,
    ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 8))

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
    ).grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 10))

    _ratio_vars = {}
    row = 3
    for activity in ACTIVITIES:
        default = DEFAULT_RATIOS.get(activity)
        if default is None:
            continue

        nb.Label(frame, text=f"{ACTIVITY_LABELS[activity]}:").grid(
            row=row, column=0, sticky=tk.W, padx=10, pady=2,
        )
        var = tk.StringVar(value=_format_ratio(ratio_for(activity)))
        _ratio_vars[activity] = var
        nb.Entry(frame, textvariable=var, width=8).grid(
            row=row, column=1, sticky=tk.W, padx=(0, 10), pady=2,
        )
        row += 1

    return frame


def save_prefs() -> None:
    """Persist ratio settings from the prefs tab."""
    for activity, var in _ratio_vars.items():
        text = var.get().strip()
        try:
            value = float(text)
        except ValueError:
            continue
        if value <= 0:
            continue
        config.set(f"{CONFIG_RATIO_PREFIX}{activity}", str(value))


def _format_ratio(value: float) -> str:
    return f"{value:g}"


def set_status(message: str) -> None:
    if _status_label is not None:
        _status_label["text"] = message


def set_last_event(message: str) -> None:
    if _last_event_label is not None:
        _last_event_label["text"] = message
        _last_event_label["foreground"] = "green"
