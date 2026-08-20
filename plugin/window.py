"""Session details window for EDPPMT: live breakdown + history."""

from __future__ import annotations

import logging
import os
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, List, Optional

from config import appname, config
from theme import theme

from .formulas import ACTIVITIES, ACTIVITY_LABELS, UNKNOWN, merits_to_cp
from .powerplay import PowerplayTracker
from .session import SessionManager, credits_earned, duration_hours, per_hour, total_merits
from .ui import ratio_for

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

CONFIG_GEOMETRY = "edppmt_window_geometry"

MIN_WIDTH = 640
MIN_HEIGHT = 420
DEFAULT_GEOMETRY = "760x520"

_window: Optional["SessionWindow"] = None


def show(parent: tk.Misc, sessions: SessionManager, pp: PowerplayTracker) -> None:
    """Open the sessions window, or raise it if already open."""
    global _window

    if _window is not None and _window.alive:
        _window.refresh()
        _window.lift()
        return

    _window = SessionWindow(parent, sessions, pp)


def refresh() -> None:
    if _window is not None and _window.alive:
        _window.refresh()


def close() -> None:
    if _window is not None and _window.alive:
        _window.close()


def _restore_geometry() -> str:
    saved = config.get_str(CONFIG_GEOMETRY)
    if not saved:
        return DEFAULT_GEOMETRY

    size, sep, position = saved.partition("+")
    width, _, height = size.partition("x")
    try:
        too_small = int(width) < MIN_WIDTH or int(height) < MIN_HEIGHT
    except ValueError:
        return DEFAULT_GEOMETRY

    if not too_small:
        return saved
    return f"{DEFAULT_GEOMETRY}+{position}" if sep else DEFAULT_GEOMETRY


class SessionWindow:
    def __init__(self, parent: tk.Misc, sessions: SessionManager, pp: PowerplayTracker) -> None:
        self._sessions = sessions
        self._pp = pp

        self._toplevel = tk.Toplevel(parent)
        self._toplevel.title("EDPPMT — Sessions")
        self._toplevel.protocol("WM_DELETE_WINDOW", self.close)
        self._toplevel.minsize(MIN_WIDTH, MIN_HEIGHT)
        self._toplevel.geometry(_restore_geometry())

        container = ttk.Frame(self._toplevel)
        container.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(container)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._current_tab = _CurrentTab(notebook)
        notebook.add(self._current_tab.frame, text="  CURRENT SESSION  ")

        self._history_tab = _HistoryTab(notebook)
        notebook.add(self._history_tab.frame, text="  HISTORY  ")

        buttons = ttk.Frame(container)
        buttons.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(buttons, text="Refresh", command=self.refresh).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Close", command=self.close).pack(side=tk.RIGHT)

        try:
            theme.update(self._toplevel)
        except Exception:
            logger.debug("Theme could not be applied to the sessions window", exc_info=True)

        self.refresh()

    @property
    def alive(self) -> bool:
        try:
            return bool(self._toplevel.winfo_exists())
        except tk.TclError:
            return False

    def lift(self) -> None:
        self._toplevel.deiconify()
        self._toplevel.lift()

    def refresh(self) -> None:
        if not self.alive:
            return
        self._current_tab.update(self._sessions.current, self._pp)
        self._history_tab.update(self._sessions.history, self._sessions.current)

    def close(self) -> None:
        if self.alive:
            config.set(CONFIG_GEOMETRY, self._toplevel.winfo_geometry())
            self._toplevel.destroy()


class _CurrentTab:
    """Live breakdown of the in-progress session."""

    def __init__(self, parent: ttk.Notebook) -> None:
        self.frame = ttk.Frame(parent)

        self._heading = ttk.Label(self.frame, text="", anchor=tk.W, justify=tk.LEFT)
        self._heading.pack(fill=tk.X, padx=10, pady=(10, 8))

        table = ttk.Frame(self.frame, padding=8, relief=tk.GROOVE, borderwidth=1)
        table.pack(fill=tk.X, padx=14, pady=(0, 14))

        style = ttk.Style(table)
        style.configure("EDPPMT.Treeview", rowheight=26)

        self._tree = ttk.Treeview(
            table,
            columns=("activity", "merits", "ratio", "cp", "cp_hr"),
            show="headings",
            selectmode="none",
            height=len(ACTIVITIES) + 1,
            style="EDPPMT.Treeview",
        )
        for col, text, width, anchor in (
            ("activity", "Activity", 150, tk.W),
            ("merits", "Merits", 100, tk.E),
            ("ratio", "Merits/CP", 100, tk.E),
            ("cp", "Est. CP", 100, tk.E),
            ("cp_hr", "CP/hr", 100, tk.E),
        ):
            self._tree.heading(col, text=text)
            self._tree.column(col, width=width, anchor=anchor, stretch=(col == "activity"))
        self._tree.pack(fill=tk.X, padx=4, pady=4)

        money = ttk.Frame(self.frame)
        money.pack(fill=tk.X, padx=10, pady=(14, 0))
        self._money_label = ttk.Label(money, text="", justify=tk.LEFT)
        self._money_label.pack(anchor=tk.W)

        self._raw_state_label = ttk.Label(self.frame, text="", anchor=tk.W)
        self._raw_state_label.pack(fill=tk.X, padx=10, pady=(10, 0))

        note = ttk.Label(
            self.frame,
            text=(
                "Activity is guessed from the PowerPlay state of the system you're "
                "in when merits land — check the raw state above if a row looks "
                "wrong."
            ),
            wraplength=560,
            justify=tk.LEFT,
            foreground="#c07000",
        )
        note.pack(fill=tk.X, padx=10, pady=(4, 0))

    def update(self, session: Dict[str, Any], pp: PowerplayTracker) -> None:
        cmdr = session.get("cmdr") or "(unknown)"
        power = pp.pledge_summary() or session.get("power") or "(not pledged)"
        started = session.get("started_at") or "?"
        hours = duration_hours(session)
        self._heading["text"] = (
            f"Commander: {cmdr}      Power: {power}\n"
            f"Started: {started}      Duration: {hours:.2f}h"
        )

        state = pp.system_state or "(none seen yet)"
        powers = ", ".join(pp.system_powers) if pp.system_powers else "(none)"
        self._raw_state_label["text"] = f"Last seen system PowerplayState: {state}      Powers: {powers}"

        self._tree.delete(*self._tree.get_children())
        totals = session.get("totals", {})

        merits_sum = 0
        cp_sum = 0.0
        for activity in ACTIVITIES:
            merits = totals.get(activity, 0)
            merits_sum += merits
            ratio = ratio_for(activity) if activity != UNKNOWN else 0.0
            cp = merits_to_cp(merits, ratio) if activity != UNKNOWN else 0.0
            cp_sum += cp
            cp_hr = per_hour(cp, hours)
            self._tree.insert(
                "",
                tk.END,
                values=(
                    ACTIVITY_LABELS[activity],
                    f"{merits:,}",
                    f"{ratio:g}" if ratio else "—",
                    f"{cp:,.1f}" if activity != UNKNOWN else "—",
                    f"{cp_hr:,.1f}" if activity != UNKNOWN and hours > 0 else "—",
                ),
            )

        self._tree.insert(
            "",
            tk.END,
            values=(
                "Total",
                f"{merits_sum:,}",
                "",
                f"{cp_sum:,.1f}",
                f"{per_hour(cp_sum, hours):,.1f}" if hours > 0 else "—",
            ),
        )

        earned = credits_earned(session)
        if earned is None:
            self._money_label["text"] = "Credits earned this session: (no balance data yet)"
        else:
            rate = f"{per_hour(earned, hours):+,.0f} cr/hr" if hours > 0 else "—"
            self._money_label["text"] = f"Credits earned this session: {earned:+,}      Rate: {rate}"


class _HistoryTab:
    """Past sessions, most recent first."""

    def __init__(self, parent: ttk.Notebook) -> None:
        self.frame = ttk.Frame(parent)

        self._tree = ttk.Treeview(
            self.frame,
            columns=("started", "cmdr", "power", "duration", "merits", "cp", "credits"),
            show="headings",
            selectmode="none",
        )
        for col, text, width, anchor in (
            ("started", "Started", 150, tk.W),
            ("cmdr", "Commander", 110, tk.W),
            ("power", "Power", 130, tk.W),
            ("duration", "Duration", 70, tk.E),
            ("merits", "Merits", 80, tk.E),
            ("cp", "Est. CP", 80, tk.E),
            ("credits", "Credits", 110, tk.E),
        ):
            self._tree.heading(col, text=text)
            self._tree.column(col, width=width, anchor=anchor, stretch=(col == "power"))

        scrollbar = ttk.Scrollbar(self.frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=10)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=10, padx=(0, 10))

    def update(self, history: List[Dict[str, Any]], current: Dict[str, Any]) -> None:
        self._tree.delete(*self._tree.get_children())

        sessions = list(history) + [current]
        for session in reversed(sessions):
            hours = duration_hours(session)
            cp_sum = sum(
                merits_to_cp(session.get("totals", {}).get(activity, 0), ratio_for(activity))
                for activity in ACTIVITIES
                if activity != UNKNOWN
            )
            earned = credits_earned(session)
            is_current = session is current

            self._tree.insert(
                "",
                tk.END,
                values=(
                    session.get("started_at", "?") + (" (live)" if is_current else ""),
                    session.get("cmdr") or "?",
                    session.get("power") or "—",
                    f"{hours:.2f}h",
                    f"{total_merits(session):,}",
                    f"{cp_sum:,.1f}",
                    f"{earned:+,}" if earned is not None else "—",
                ),
            )

        if not sessions:
            self._tree.insert("", tk.END, values=("(no sessions yet)", "", "", "", "", "", ""))
