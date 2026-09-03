#!/usr/bin/env python3
"""Standalone overlay tester for EDPPMT's Interdiction Warning and Landing
features.

Exercises every render() scenario (interdiction states, every Landing
diagram family, the no-diagram text fallback, denied/approved/requested)
against a *real* running EDMCOverlay or EDMCModernOverlay instance, using
the actual plugin/overlay.py, plugin/interdiction.py, and plugin/landing.py
code - not a reimplementation, so what you see here is exactly what ships.
Neither EDMC nor Elite Dangerous need to be running; only the overlay
helper app does.

Usage:
    python scripts/test_overlay.py [--host 127.0.0.1] [--port 5010]

Then pick a scenario number at the prompt, look at the overlay, repeat.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import types
from pathlib import Path
from typing import Callable, List, Tuple

ROOT = Path(__file__).resolve().parent.parent


def _stub_config() -> None:
    """plugin/*.py do `from config import appname, config` at import time -
    that module is provided by EDMC at runtime and doesn't exist outside
    it. A minimal in-memory stand-in is enough for overlay.py/
    interdiction.py/landing.py specifically (unlike ui.py/window.py/
    rares_window.py, none of them touch EDMC's theme/myNotebook/companion
    modules, so nothing else needs stubbing here)."""

    class _Config:
        def __init__(self) -> None:
            self._store: dict = {}

        def get_bool(self, key: str, default: bool = False) -> bool:
            return self._store.get(key, default)

        def get_str(self, key: str, default=None):
            return self._store.get(key, default)

        def set(self, key: str, value) -> None:
            self._store[key] = value

    stub = types.ModuleType("config")
    stub.appname = "EDMarketConnector"  # type: ignore[attr-defined]
    stub.config = _Config()  # type: ignore[attr-defined]
    sys.modules["config"] = stub


def _import_plugin_modules():
    """plugin/*.py use relative imports (`from .overlay import ...`), so
    they must be imported as members of a package literally named
    "plugin" - the same name EDMC loads this plugin under."""
    _stub_config()
    pkg = types.ModuleType("plugin")
    pkg.__path__ = [str(ROOT / "plugin")]  # type: ignore[attr-defined]
    sys.modules["plugin"] = pkg
    overlay = importlib.import_module("plugin.overlay")
    interdiction = importlib.import_module("plugin.interdiction")
    landing = importlib.import_module("plugin.landing")
    return overlay, interdiction, landing


Scenario = Tuple[str, Callable[[object], None]]


def _build_scenarios(interdiction, landing) -> List[Scenario]:
    def interdiction_active(power=None, is_thargoid=False, is_player=True) -> Callable[[object], None]:
        return lambda client: interdiction.render(
            interdiction.InterdictionSnapshot(
                active=True, interdictor_name="CMDR Test Hostile",
                is_player=is_player, is_thargoid=is_thargoid, power=power,
            ),
            client,
        )

    def interdiction_resolved(resolution: str) -> Callable[[object], None]:
        return lambda client: interdiction.render(
            interdiction.InterdictionSnapshot(
                active=True, interdictor_name="CMDR Test Hostile",
                is_player=True, is_thargoid=False, resolution=resolution,
            ),
            client,
        )

    def landing_scenario(carrier_type=None, **kwargs) -> Callable[[object], None]:
        info = landing.LandingDisplayInfo(**kwargs)
        return lambda client: landing.render(info, carrier_type, client)

    return [
        ("Interdiction: active, player", interdiction_active()),
        ("Interdiction: active, Thargoid", interdiction_active(is_thargoid=True, is_player=False)),
        ("Interdiction: active, affiliated with a Power", interdiction_active(power="Zachary Hudson")),
        ("Interdiction: resolved - escaped", interdiction_resolved("escaped")),
        ("Interdiction: resolved - pulled from supercruise", interdiction_resolved("pulled-out")),
        ("Interdiction: resolved - submitted", interdiction_resolved("submitted")),
        ("Interdiction: clear", lambda client: interdiction.render(interdiction.InterdictionSnapshot(active=False), client)),
        ("Landing: Docking Requested (pending, no pad yet)", landing_scenario(
            status_label="Docking Requested", station="Jameson Memorial",
            pad=None, diagram_type=None, show_diagram=False,
        )),
        ("Landing: Docking Approved, starport, pad 1", landing_scenario(
            status_label="Docking Approved", station="Jameson Memorial",
            pad=1, diagram_type="starport", show_diagram=True,
        )),
        ("Landing: Docking Approved, starport, pad 24", landing_scenario(
            status_label="Docking Approved", station="Jameson Memorial",
            pad=24, diagram_type="starport", show_diagram=True,
        )),
        ("Landing: Docking Approved, starport, pad 45", landing_scenario(
            status_label="Docking Approved", station="Jameson Memorial",
            pad=45, diagram_type="starport", show_diagram=True,
        )),
        ("Landing: Docking Denied (ship too large)", landing_scenario(
            status_label="Docking Denied", station="Jameson Memorial", denied_reason="Ship too large",
            pad=None, diagram_type="starport", show_diagram=True,
        )),
        ("Landing: Docking Approved, Fleet Carrier, pad 5", landing_scenario(
            status_label="Docking Approved", station="ABCD Voyager",
            pad=5, diagram_type="fleetcarrier", show_diagram=True, carrier_type="FleetCarrier",
        )),
        ("Landing: Docking Approved, Squadron Carrier, pad 20", landing_scenario(
            status_label="Docking Approved", station="ABCD",
            pad=20, diagram_type="fleetcarrier", show_diagram=True, carrier_type="SquadronCarrier",
        )),
        ("Landing: Docking Approved, Colonisation Ship, pad 3", landing_scenario(
            status_label="Docking Approved", station="Colonisation Ship",
            pad=3, diagram_type="fleetcarrier", show_diagram=True, carrier_type="ColonisationShip",
        )),
        ("Landing: Docking Approved, no diagram family (outpost) - text fallback", landing_scenario(
            status_label="Docking Approved", station="Some Outpost",
            pad=2, diagram_type=None, show_diagram=False,
        )),
        ("Landing: clear", lambda client: landing.clear(client)),
        ("Clear everything (interdiction + landing)", None),  # handled specially below
    ]


def _print_menu(scenarios: List[Scenario]) -> None:
    print("Scenarios:")
    for i, (name, _) in enumerate(scenarios):
        print(f"  {i:2d}) {name}")
    print("   q) quit\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1", help="EDMCOverlay/EDMCModernOverlay host (default: 127.0.0.1)")
    parser.add_argument("--port", default="5010", help="EDMCOverlay/EDMCModernOverlay port (default: 5010)")
    args = parser.parse_args()

    overlay, interdiction, landing = _import_plugin_modules()
    client = overlay.OverlayClient(overlay.OverlayConfig(host=args.host, port=args.port))
    scenarios = _build_scenarios(interdiction, landing)
    clear_all_index = len(scenarios) - 1

    print(f"EDPPMT overlay tester - target {args.host}:{args.port}")
    print("EDMCOverlay or EDMCModernOverlay must already be running there - EDMC and the game don't need to be.")
    print("Leave this running while you look at the overlay - quitting (q) disconnects, and everything this")
    print("tool sent disappears immediately when it does (same as closing EDMC would for the real plugin).\n")

    try:
        while True:
            _print_menu(scenarios)
            choice = input("> ").strip().lower()
            if choice in ("q", "quit", "exit"):
                break
            if not choice:
                continue
            try:
                index = int(choice)
                name, action = scenarios[index]
            except (ValueError, IndexError):
                print("Not a valid choice.\n")
                continue

            try:
                if index == clear_all_index:
                    interdiction.render(interdiction.InterdictionSnapshot(active=False), client)
                    landing.clear(client)
                else:
                    action(client)
                print(f"Sent: {name}\n")
            except OSError as err:
                print(f"Could not reach the overlay at {args.host}:{args.port} ({err}).\n")
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        client.close()


if __name__ == "__main__":
    main()
