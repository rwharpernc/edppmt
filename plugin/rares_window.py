"""Rare Goods Finder window for EDPPMT: nearest rare commodities to the
current system. Mirrors window.py's SessionWindow shape (module-level
show/refresh/close, saved geometry, theme.update)."""

from __future__ import annotations

import logging
import os
import tkinter as tk
import webbrowser
from tkinter import ttk
from typing import Any, Dict, Optional, Tuple

from config import appname, config
from theme import theme

from . import rares
from .clipboard import inara_system_url

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

CONFIG_GEOMETRY = "edppmt_rares_window_geometry"
CONFIG_LIMIT = "edppmt_rares_limit"

MIN_WIDTH = 760
MIN_HEIGHT = 420
DEFAULT_GEOMETRY = "900x520"
DEFAULT_LIMIT = 10
MAX_LIMIT = 141  # size of the bundled dataset

_window: Optional["RaresWindow"] = None

Coords = Tuple[float, float, float]


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


def _saved_limit() -> int:
    raw = config.get_str(CONFIG_LIMIT)
    try:
        value = int(raw) if raw else DEFAULT_LIMIT
    except ValueError:
        value = DEFAULT_LIMIT
    return max(1, min(value, MAX_LIMIT))


def show(parent: tk.Misc, current_system: Optional[str], current_coords: Optional[Coords]) -> None:
    """Open the Rares window, or raise it if already open."""
    global _window

    if _window is not None and _window.alive:
        _window.refresh(current_system, current_coords)
        _window.lift()
        return

    _window = RaresWindow(parent, current_system, current_coords)


def refresh(current_system: Optional[str], current_coords: Optional[Coords]) -> None:
    if _window is not None and _window.alive:
        _window.refresh(current_system, current_coords)


def close() -> None:
    if _window is not None and _window.alive:
        _window.close()


class RaresWindow:
    def __init__(
        self, parent: tk.Misc, current_system: Optional[str], current_coords: Optional[Coords],
    ) -> None:
        self._current_system = current_system
        self._current_coords = current_coords

        self._toplevel = tk.Toplevel(parent)
        self._toplevel.title("EDPPMT — Rare Goods Finder")
        self._toplevel.protocol("WM_DELETE_WINDOW", self.close)
        self._toplevel.minsize(MIN_WIDTH, MIN_HEIGHT)
        self._toplevel.geometry(_restore_geometry())

        container = ttk.Frame(self._toplevel)
        container.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)

        header = ttk.Frame(container)
        header.pack(fill=tk.X, pady=(0, 8))
        self._header_label = ttk.Label(header, text="", justify=tk.LEFT)
        self._header_label.pack(side=tk.LEFT)

        controls = ttk.Frame(header)
        controls.pack(side=tk.RIGHT)
        ttk.Label(controls, text="Show nearest:").pack(side=tk.LEFT)
        self._limit_var = tk.StringVar(value=str(_saved_limit()))
        limit_entry = ttk.Entry(controls, textvariable=self._limit_var, width=4)
        limit_entry.pack(side=tk.LEFT, padx=(4, 0))
        limit_entry.bind("<Return>", lambda _e: self._apply_limit())
        ttk.Button(controls, text="Apply", command=self._apply_limit).pack(side=tk.LEFT, padx=(4, 0))

        table = ttk.Frame(container)
        table.pack(fill=tk.BOTH, expand=True)

        columns = ("rare", "system", "distance", "station", "pad", "cost", "pp", "legality")
        self._tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        for col, text, width, anchor in (
            ("rare", "Rare Good", 170, tk.W),
            ("system", "Origin System", 150, tk.W),
            ("distance", "Distance (ly)", 95, tk.E),
            ("station", "Station", 160, tk.W),
            ("pad", "Pad", 40, tk.CENTER),
            ("cost", "Cost", 80, tk.E),
            ("pp", "PP Eligible", 110, tk.W),
            ("legality", "Legality", 220, tk.W),
        ):
            self._tree.heading(col, text=text)
            self._tree.column(col, width=width, anchor=anchor, stretch=(col == "legality"))

        scrollbar = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.bind("<Double-1>", self._open_selected)

        ttk.Label(
            container,
            text=(
                "Double-click a row to open that system on Inara. Legality is general reference "
                "(not evaluated against a specific destination) — always verify in-game before trading."
            ),
            wraplength=820,
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(8, 8))

        buttons = ttk.Frame(container)
        buttons.pack(fill=tk.X)
        ttk.Button(
            buttons, text="Refresh", command=lambda: self.refresh(self._current_system, self._current_coords),
        ).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Close", command=self.close).pack(side=tk.RIGHT)

        try:
            theme.update(self._toplevel)
        except Exception:
            logger.debug("Theme could not be applied to the rares window", exc_info=True)

        self.refresh(current_system, current_coords)

    @property
    def alive(self) -> bool:
        try:
            return bool(self._toplevel.winfo_exists())
        except tk.TclError:
            return False

    def lift(self) -> None:
        self._toplevel.deiconify()
        self._toplevel.lift()

    def _limit(self) -> int:
        try:
            value = int(self._limit_var.get())
        except (ValueError, AttributeError):
            return DEFAULT_LIMIT
        return max(1, min(value, MAX_LIMIT))

    def _apply_limit(self) -> None:
        limit = self._limit()
        self._limit_var.set(str(limit))
        config.set(CONFIG_LIMIT, str(limit))
        self.refresh(self._current_system, self._current_coords)

    def refresh(self, current_system: Optional[str], current_coords: Optional[Coords]) -> None:
        if not self.alive:
            return
        self._current_system = current_system
        self._current_coords = current_coords

        self._tree.delete(*self._tree.get_children())

        if not current_coords:
            self._header_label["text"] = "Awaiting system data…"
            self._tree.insert(
                "", tk.END,
                values=("(waiting for a system jump or login to know where you are)", "", "", "", "", "", "", ""),
            )
            return

        self._header_label["text"] = f"Current system: {current_system or '(unknown)'}"

        for entry in rares.nearest(current_coords, self._limit()):
            self._tree.insert("", tk.END, values=self._row_values(entry))

    @staticmethod
    def _row_values(entry: Dict[str, Any]) -> tuple:
        cost = entry.get("cost")
        return (
            entry["rare"],
            entry["system"],
            f"{entry['distance_ly']:,.1f}",
            entry["station"],
            entry["pad"],
            f"{cost:,}" if cost is not None else "—",
            "/".join(entry.get("pp", {}).get("eligibleSystemTypes", [])) or "—",
            rares.legality_summary(entry),
        )

    def _open_selected(self, _event: Optional[tk.Event] = None) -> None:
        selection = self._tree.selection()
        if not selection:
            return
        values = self._tree.item(selection[0], "values")
        if not values or not values[1]:
            return
        webbrowser.open(inara_system_url(values[1]))

    def close(self) -> None:
        if self.alive:
            config.set(CONFIG_GEOMETRY, self._toplevel.winfo_geometry())
            self._toplevel.destroy()
