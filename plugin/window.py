"""Session details window for EDPPMT: live breakdown + history."""

from __future__ import annotations

import logging
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Any, Dict, List, Optional, Tuple

from config import appname, config
from theme import theme

from .formulas import ACTIVITIES, ACTIVITY_LABELS, NO_CP_ACTIVITIES, merits_to_cp
from .powerplay import PowerplayTracker
from .session import (
    SessionManager,
    credits_earned,
    duration_hours,
    per_hour,
    system_merit_total,
    system_totals,
    total_merits,
    visited_systems,
)
from .ui import ratio_for

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

CONFIG_GEOMETRY = "edppmt_window_geometry"

MIN_WIDTH = 820
MIN_HEIGHT = 560
DEFAULT_GEOMETRY = "1040x720"

# Marks the row for whatever system the commander is in right now in the "By
# System" table, so it doesn't get lost among other rows once a session has
# touched several systems.
_CURRENT_SYSTEM_MARK = "▶ "

_window: Optional["SessionWindow"] = None
_styles_ready = False


def _configure_styles() -> None:
    """Bold variants of the default ttk label font, used for section titles
    and the field names in the heading/context grids — needs a Tk root to
    exist first, so this runs lazily from SessionWindow.__init__ rather than
    at import time."""
    global _styles_ready
    if _styles_ready:
        return

    base = tkfont.nametofont("TkDefaultFont")
    field_font = tkfont.Font(family=base.cget("family"), size=base.cget("size"), weight="bold")
    section_font = tkfont.Font(family=base.cget("family"), size=base.cget("size") + 1, weight="bold")

    style = ttk.Style()
    style.configure("EDPPMT.FieldName.TLabel", font=field_font)
    style.configure("EDPPMT.Section.TLabel", font=section_font)
    _styles_ready = True


def show(parent: tk.Misc, sessions: SessionManager, pp: PowerplayTracker, current_system: Optional[str]) -> None:
    """Open the sessions window, or raise it if already open."""
    global _window

    if _window is not None and _window.alive:
        _window.refresh(current_system)
        _window.lift()
        return

    _window = SessionWindow(parent, sessions, pp, current_system)


def refresh(current_system: Optional[str]) -> None:
    if _window is not None and _window.alive:
        _window.refresh(current_system)


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


def _field_row(parent: ttk.Frame, row: int, pairs: Tuple[Tuple[str, str], ...]) -> None:
    """One row of label:value pairs (bold label, plain value) in a grid —
    used for the heading and PowerPlay-context blocks so values line up
    cleanly instead of being separated by hand-typed runs of spaces."""
    col = 0
    for label, value in pairs:
        ttk.Label(parent, text=label, style="EDPPMT.FieldName.TLabel").grid(
            row=row, column=col, sticky=tk.W, padx=(0 if col == 0 else 24, 6), pady=2,
        )
        ttk.Label(parent, text=value).grid(row=row, column=col + 1, sticky=tk.W, pady=2)
        col += 2


class SessionWindow:
    def __init__(
        self, parent: tk.Misc, sessions: SessionManager, pp: PowerplayTracker, current_system: Optional[str],
    ) -> None:
        self._sessions = sessions
        self._pp = pp
        self._current_system = current_system

        self._toplevel = tk.Toplevel(parent)
        self._toplevel.title("EDPPMT — Sessions")
        self._toplevel.protocol("WM_DELETE_WINDOW", self.close)
        self._toplevel.minsize(MIN_WIDTH, MIN_HEIGHT)
        self._toplevel.geometry(_restore_geometry())

        _configure_styles()

        container = ttk.Frame(self._toplevel)
        container.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(container)
        notebook.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)

        self._current_tab = _CurrentTab(notebook)
        notebook.add(self._current_tab.frame, text="  CURRENT SESSION  ")

        self._history_tab = _HistoryTab(notebook)
        notebook.add(self._history_tab.frame, text="  HISTORY  ")

        buttons = ttk.Frame(container)
        buttons.pack(fill=tk.X, padx=14, pady=(0, 14))
        ttk.Button(buttons, text="Refresh", command=lambda: self.refresh(self._current_system)).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Close", command=self.close).pack(side=tk.RIGHT)

        try:
            theme.update(self._toplevel)
        except Exception:
            logger.debug("Theme could not be applied to the sessions window", exc_info=True)

        self.refresh(current_system)

    @property
    def alive(self) -> bool:
        try:
            return bool(self._toplevel.winfo_exists())
        except tk.TclError:
            return False

    def lift(self) -> None:
        self._toplevel.deiconify()
        self._toplevel.lift()

    def refresh(self, current_system: Optional[str]) -> None:
        if not self.alive:
            return
        self._current_system = current_system
        self._current_tab.update(self._sessions.current, self._pp, current_system)
        self._history_tab.update(self._sessions.history, self._sessions.current)

    def close(self) -> None:
        if self.alive:
            config.set(CONFIG_GEOMETRY, self._toplevel.winfo_geometry())
            self._toplevel.destroy()


class _CurrentTab:
    """Live breakdown of the in-progress session: who/how long, what's been
    earned in each system visited, and the same broken out by activity."""

    def __init__(self, parent: ttk.Notebook) -> None:
        self.frame = ttk.Frame(parent)

        style = ttk.Style(self.frame)
        style.configure("EDPPMT.Treeview", rowheight=28)
        style.configure("EDPPMT.System.Treeview", rowheight=26)

        # --- Session heading: commander/power/started/duration -----------
        heading = ttk.Frame(self.frame)
        heading.pack(fill=tk.X, padx=16, pady=(16, 12))
        self._heading = heading

        # --- By system -----------------------------------------------------
        ttk.Label(self.frame, text="By System", style="EDPPMT.Section.TLabel").pack(
            fill=tk.X, padx=16, pady=(0, 4),
        )
        ttk.Label(
            self.frame,
            text="What you've earned in each system this session — the current one is marked and stays first.",
            wraplength=900,
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=16, pady=(0, 6))

        system_table = ttk.Frame(self.frame)
        system_table.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 14))

        self._system_tree = ttk.Treeview(
            system_table,
            columns=("system", "merits", "cp", "breakdown"),
            show="headings",
            selectmode="none",
            height=6,
            style="EDPPMT.System.Treeview",
        )
        for col, text, width, anchor in (
            ("system", "System", 200, tk.W),
            ("merits", "Merits", 90, tk.E),
            ("cp", "Est. CP", 90, tk.E),
            ("breakdown", "Activity breakdown", 320, tk.W),
        ):
            self._system_tree.heading(col, text=text)
            self._system_tree.column(col, width=width, anchor=anchor, stretch=(col == "breakdown"))

        system_scrollbar = ttk.Scrollbar(system_table, orient=tk.VERTICAL, command=self._system_tree.yview)
        self._system_tree.configure(yscrollcommand=system_scrollbar.set)
        self._system_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        system_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # --- By activity (session-wide) ------------------------------------
        ttk.Label(self.frame, text="By Activity (session total)", style="EDPPMT.Section.TLabel").pack(
            fill=tk.X, padx=16, pady=(0, 4),
        )

        activity_table = ttk.Frame(self.frame, padding=12, relief=tk.GROOVE, borderwidth=1)
        activity_table.pack(fill=tk.X, padx=16, pady=(0, 14))

        self._tree = ttk.Treeview(
            activity_table,
            columns=("activity", "merits", "ratio", "cp", "cp_hr"),
            show="headings",
            selectmode="none",
            height=len(ACTIVITIES) + 1,
            style="EDPPMT.Treeview",
        )
        for col, text, width, anchor in (
            ("activity", "Activity", 180, tk.W),
            ("merits", "Merits", 110, tk.E),
            ("ratio", "Merits/CP", 110, tk.E),
            ("cp", "Est. CP", 110, tk.E),
            ("cp_hr", "CP/hr", 110, tk.E),
        ):
            self._tree.heading(col, text=text)
            self._tree.column(col, width=width, anchor=anchor, stretch=(col == "activity"))
        self._tree.pack(fill=tk.X, padx=6, pady=6)

        # --- Money + live PowerPlay context ---------------------------------
        money = ttk.Frame(self.frame)
        money.pack(fill=tk.X, padx=16, pady=(0, 10))
        self._money_label = ttk.Label(money, text="", justify=tk.LEFT)
        self._money_label.pack(anchor=tk.W)

        ttk.Label(self.frame, text="Current PowerPlay Context", style="EDPPMT.Section.TLabel").pack(
            fill=tk.X, padx=16, pady=(0, 4),
        )
        context = ttk.Frame(self.frame)
        context.pack(fill=tk.X, padx=16, pady=(0, 8))
        self._context = context

        note = ttk.Label(
            self.frame,
            text=(
                "The journal doesn't say which activity your merits were for, so EDPPMT infers it from "
                "who controlled the system when they landed: uncontrolled = Acquisition, your Power = "
                "Reinforcement, a rival Power = Undermining. If a system's breakdown above looks wrong, "
                "compare it against the context shown here."
            ),
            wraplength=900,
            justify=tk.LEFT,
            foreground="#c07000",
        )
        note.pack(fill=tk.X, padx=16, pady=(0, 12))

    def update(self, session: Dict[str, Any], pp: PowerplayTracker, current_system: Optional[str]) -> None:
        cmdr = session.get("cmdr") or "(unknown)"
        power = pp.pledge_summary() or session.get("power") or "(not pledged)"
        started = session.get("started_at") or "?"
        hours = duration_hours(session)

        for child in self._heading.winfo_children():
            child.destroy()
        _field_row(self._heading, 0, (("Commander:", cmdr), ("Power:", power)))
        _field_row(self._heading, 1, (("Started:", started), ("Duration:", f"{hours:.2f}h")))

        for child in self._context.winfo_children():
            child.destroy()
        name = current_system or pp.system_name or "(none seen yet)"
        state = pp.system_state or "(none seen yet)"
        controller = pp.system_controller or "(none)"
        powers = ", ".join(pp.system_powers) if pp.system_powers else "(none)"
        _field_row(self._context, 0, (("System:", name), ("State:", state)))
        _field_row(self._context, 1, (("Controller:", controller), ("Rival Powers:", powers)))

        self._update_system_tree(session, current_system)
        self._update_activity_tree(session, hours)

        earned = credits_earned(session)
        if earned is None:
            self._money_label["text"] = "Credits earned this session: (no balance data yet)"
        else:
            rate = f"{per_hour(earned, hours):+,.0f} cr/hr" if hours > 0 else "—"
            self._money_label["text"] = f"Credits earned this session: {earned:+,}      Rate: {rate}"

    def _update_system_tree(self, session: Dict[str, Any], current_system: Optional[str]) -> None:
        self._system_tree.delete(*self._system_tree.get_children())

        systems = visited_systems(session)
        # The current system leads the list even if it hasn't earned any
        # merits yet this visit, so it's never missing from its own table.
        if current_system and current_system not in systems:
            systems = [current_system] + systems
        elif current_system in systems:
            systems = [current_system] + [s for s in systems if s != current_system]

        if not systems:
            self._system_tree.insert("", tk.END, values=("(no systems visited yet)", "", "", ""))
            return

        for name in systems:
            totals = system_totals(session, name)
            merits = system_merit_total(session, name)
            cp = sum(
                merits_to_cp(totals.get(activity, 0), ratio_for(activity))
                for activity in ACTIVITIES
                if activity not in NO_CP_ACTIVITIES
            )
            breakdown = " · ".join(
                f"{ACTIVITY_LABELS[activity]} {totals[activity]:,}"
                for activity in ACTIVITIES
                if totals.get(activity)
            ) or "—"

            label = f"{_CURRENT_SYSTEM_MARK}{name} (current)" if name == current_system else name
            self._system_tree.insert(
                "", tk.END, values=(label, f"{merits:,}", f"{cp:,.1f}" if merits else "—", breakdown),
            )

    def _update_activity_tree(self, session: Dict[str, Any], hours: float) -> None:
        self._tree.delete(*self._tree.get_children())
        totals = session.get("totals", {})

        merits_sum = 0
        cp_sum = 0.0
        for activity in ACTIVITIES:
            merits = totals.get(activity, 0)
            merits_sum += merits
            has_cp = activity not in NO_CP_ACTIVITIES
            ratio = ratio_for(activity) if has_cp else 0.0
            cp = merits_to_cp(merits, ratio) if has_cp else 0.0
            cp_sum += cp
            cp_hr = per_hour(cp, hours)
            self._tree.insert(
                "",
                tk.END,
                values=(
                    ACTIVITY_LABELS[activity],
                    f"{merits:,}",
                    f"{ratio:g}" if ratio else "—",
                    f"{cp:,.1f}" if has_cp else "—",
                    f"{cp_hr:,.1f}" if has_cp and hours > 0 else "—",
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


def _cumulative_summary(sessions: List[Dict[str, Any]]) -> str:
    """'All sessions — Merits: 12,345   CP: Acquisition 120 / Reinforcement 80 / Undermining 40   Cr: +200,000'."""
    merit_totals: Dict[str, int] = {activity: 0 for activity in ACTIVITIES}
    for s in sessions:
        totals = s.get("totals", {})
        for activity in ACTIVITIES:
            merit_totals[activity] += totals.get(activity, 0)

    cumulative_merits = sum(merit_totals.values())
    cp_bits = " / ".join(
        f"{ACTIVITY_LABELS[activity]} {merits_to_cp(merit_totals[activity], ratio_for(activity)):,.1f}"
        for activity in ACTIVITIES
        if activity not in NO_CP_ACTIVITIES
    )

    cumulative_earned = 0
    have_credits = False
    for s in sessions:
        earned = credits_earned(s)
        if earned is not None:
            cumulative_earned += earned
            have_credits = True

    parts = [f"All sessions — Merits: {cumulative_merits:,}", f"CP: {cp_bits}"]
    if have_credits:
        parts.append(f"Cr: {cumulative_earned:+,}")
    return "   ".join(parts)


class _HistoryTab:
    """Past sessions, most recent first."""

    def __init__(self, parent: ttk.Notebook) -> None:
        self.frame = ttk.Frame(parent, padding=(16, 16, 6, 16))

        ttk.Label(self.frame, text="All Sessions", style="EDPPMT.Section.TLabel").pack(
            fill=tk.X, pady=(0, 8),
        )

        style = ttk.Style(self.frame)
        style.configure("EDPPMT.History.Treeview", rowheight=26)

        table = ttk.Frame(self.frame)
        table.pack(fill=tk.BOTH, expand=True)

        self._tree = ttk.Treeview(
            table,
            columns=("started", "cmdr", "power", "duration", "merits", "cp", "credits"),
            show="headings",
            selectmode="none",
            style="EDPPMT.History.Treeview",
        )
        for col, text, width, anchor in (
            ("started", "Started", 190, tk.W),
            ("cmdr", "Commander", 130, tk.W),
            ("power", "Power", 170, tk.W),
            ("duration", "Duration", 90, tk.E),
            ("merits", "Merits", 100, tk.E),
            ("cp", "Est. CP", 100, tk.E),
            ("credits", "Credits", 130, tk.E),
        ):
            self._tree.heading(col, text=text)
            self._tree.column(col, width=width, anchor=anchor, stretch=(col == "power"))

        self._summary_label = ttk.Label(self.frame, text="", anchor=tk.W, justify=tk.LEFT)
        self._summary_label.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

        scrollbar = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def update(self, history: List[Dict[str, Any]], current: Dict[str, Any]) -> None:
        self._tree.delete(*self._tree.get_children())

        sessions = list(history) + [current]
        self._summary_label["text"] = _cumulative_summary(sessions)
        for session in reversed(sessions):
            hours = duration_hours(session)
            cp_sum = sum(
                merits_to_cp(session.get("totals", {}).get(activity, 0), ratio_for(activity))
                for activity in ACTIVITIES
                if activity not in NO_CP_ACTIVITIES
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
