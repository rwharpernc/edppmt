"""Rare Goods Finder window for EDPPMT: nearest rare commodities to the
current system. Mirrors window.py's SessionWindow shape (module-level
show/refresh/close, saved geometry, theme.update)."""

from __future__ import annotations

import logging
import os
import tkinter as tk
import webbrowser
from tkinter import ttk
from typing import Any, Dict, List, Optional, Tuple

from config import appname, config
from theme import theme

from . import powerplay_lookup, rares
from .clipboard import inara_commodity_url

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

CONFIG_GEOMETRY = "edppmt_rares_window_geometry"
CONFIG_LIMIT = "edppmt_rares_limit"

MIN_WIDTH = 940
MIN_HEIGHT = 420
DEFAULT_GEOMETRY = "960x520"
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
        self._refresh_seq = 0
        self._id64_to_iids: Dict[int, List[str]] = {}

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

        # Default ttk row height is too tight for this table's font, which
        # left rows visually clipping into each other - same fix window.py
        # already applies to its own Treeviews (see EDPPMT.Treeview there).
        style = ttk.Style(table)
        style.configure("EDPPMT.Rares.Treeview", rowheight=26)

        columns = ("rare", "system", "station", "pad", "power")
        self._tree = ttk.Treeview(
            table, columns=columns, show="headings", selectmode="browse", style="EDPPMT.Rares.Treeview",
        )
        # Widths sized to the bundled dataset's longest values per column
        # (e.g. "Ultra-Compact Processor Prototypes", "Stefanyshyn-Piper
        # Station"), not just their headings, so nothing gets clipped.
        for col, text, width in (
            ("rare", "Rare Good", 290),
            ("system", "Origin System", 150),
            ("station", "Station", 220),
            ("pad", "Pad", 60),
            ("power", "Controlling Power", 160),
        ):
            self._tree.heading(col, text=text, anchor=tk.CENTER)
            self._tree.column(col, width=width, anchor=tk.CENTER, stretch=True)

        scrollbar = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.bind("<Double-1>", self._open_selected)

        ttk.Label(
            container,
            text=(
                "Double-click a row to open that rare good's page on Inara. Sorted by distance from your "
                "current system. Controlling Power is looked up live from Spansh — \"…\" while loading, "
                "\"—\" if unclaimed or unreachable."
            ),
            wraplength=920,
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
        self._refresh_seq += 1
        seq = self._refresh_seq
        self._id64_to_iids = {}

        self._tree.delete(*self._tree.get_children())

        if not current_coords:
            self._header_label["text"] = "Awaiting system data…"
            self._tree.insert(
                "", tk.END,
                values=("(waiting for a system jump or login to know where you are)", "", "", "", ""),
            )
            return

        self._header_label["text"] = f"Current system: {current_system or '(unknown)'}"

        entries = rares.nearest(current_coords, self._limit())
        for entry in entries:
            iid = str(entry["inaraId"])
            self._tree.insert("", tk.END, iid=iid, values=self._row_values(entry))
            id64 = entry.get("spanshId64")
            if id64 is not None:
                self._id64_to_iids.setdefault(id64, []).append(iid)

        powerplay_lookup.fetch_missing(self._id64_to_iids.keys(), lambda id64, power: self._toplevel.after(
            0, lambda: self._apply_power_result(seq, id64, power),
        ))

    def _apply_power_result(self, seq: int, id64: int, power: Optional[str]) -> None:
        if seq != self._refresh_seq or not self.alive:
            return
        for iid in self._id64_to_iids.get(id64, ()):
            if self._tree.exists(iid):
                self._tree.set(iid, "power", power or "—")

    @staticmethod
    def _row_values(entry: Dict[str, Any]) -> tuple:
        id64 = entry.get("spanshId64")
        found, power = powerplay_lookup.cached(id64) if id64 is not None else (True, None)
        return (
            entry["rare"],
            entry["system"],
            entry["station"],
            entry["pad"],
            (power or "—") if found else "…",
        )

    def _open_selected(self, _event: Optional[tk.Event] = None) -> None:
        selection = self._tree.selection()
        if not selection:
            return
        try:
            inara_id = int(selection[0])
        except ValueError:
            return
        webbrowser.open(inara_commodity_url(inara_id))

    def close(self) -> None:
        if self.alive:
            config.set(CONFIG_GEOMETRY, self._toplevel.winfo_geometry())
            self._toplevel.destroy()
