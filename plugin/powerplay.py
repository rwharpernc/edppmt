"""Tracks the commander's pledged Power, merit total, and the current system's
PowerPlay context, and classifies which activity a batch of merits most likely
came from.

The journal has no field that says "these merits came from Acquisition" — that
has to be inferred from where the commander is when they earn them. FSDJump /
Location / Docked report a system's "PowerplayState" and "Powers" (the
controlling power, or the powers contesting it) whenever the system is
powerplay-relevant. Comparing that to the commander's own pledged power tells
us whether being there helps acquire an unclaimed system, reinforce one's own
power's hold on it, or undermine a rival's.

Confirmed against EDMarketConnector's own monitor.py (which maintains
state['Powerplay'] the same way): the "Powerplay" event (written at login if
pledged) carries Power/Rank/Merits/Votes/TimePledged, and "PowerplayMerits"
carries a running "TotalMerits". EDMC does not track PowerplayJoin/Leave/
Defect itself, so a mid-session defection would leave EDMC's own state stale;
this tracker handles those events directly instead of relying on EDMC's state.
"""

from __future__ import annotations

import logging
import os
from typing import Any, List, Mapping, Optional

from config import appname

from .formulas import ACQUISITION, REINFORCEMENT, UNDERMINING, UNKNOWN

plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")

# PowerplayState values that mean "a single power has already secured this
# system" — under one of these, whether it's *our* power or a rival's Powers
# entry is what separates Reinforcement from Undermining. Anything else means
# nobody has it secured yet, so effort there is Acquisition. The exact set of
# state names Frontier uses isn't documented (the last official journal
# manual predates Powerplay 2.0); this list covers both the legacy and
# current names seen in the wild and is deliberately conservative — an
# unrecognised state falls through to Acquisition rather than guessing wrong.
_CONTROLLED_STATES = {"exploited", "fortified", "stronghold", "controlled", "homesystem"}

# Pledge status, resolved once per game session (see apply_login_reset /
# confirm_not_pledged_if_unresolved).
PLEDGE_UNKNOWN = "unknown"
PLEDGED = "pledged"
NOT_PLEDGED = "not_pledged"


class PowerplayTracker:
    """Commander's pledged Power/merit total, plus the PowerPlay state of 'here'."""

    def __init__(self) -> None:
        self.my_power: Optional[str] = None
        self.rank: Optional[int] = None
        self.total_merits: Optional[int] = None
        self.system_state: Optional[str] = None
        self.system_powers: List[str] = []
        self.pledge_status: str = PLEDGE_UNKNOWN

    def apply_login_reset(self) -> None:
        """
        "LoadGame": start of a fresh game session.

        The journal only ever tells us "you ARE pledged" (the "Powerplay"
        event, written alongside LoadGame at startup if pledged) — there's no
        "you are NOT pledged" event. So pledge_status goes back to unknown
        here, and confirm_not_pledged_if_unresolved() (called on the next
        always-fires "Location" event) resolves it to NOT_PLEDGED if no
        "Powerplay" event showed up in between.
        """
        self.my_power = None
        self.rank = None
        self.total_merits = None
        self.pledge_status = PLEDGE_UNKNOWN

    def apply_login_snapshot(self, entry: Mapping[str, Any]) -> None:
        """"Powerplay" event: written at startup if the commander is pledged."""
        power = entry.get("Power")
        self.my_power = str(power) if power else None
        self.pledge_status = PLEDGED if self.my_power else NOT_PLEDGED
        rank = entry.get("Rank")
        if isinstance(rank, int):
            self.rank = rank
        merits = entry.get("Merits")
        if isinstance(merits, int):
            self.total_merits = merits

    def confirm_not_pledged_if_unresolved(self) -> bool:
        """
        Call on "Location" (always fires once at startup, after "Powerplay"
        would have if pledged). Returns True if this call just resolved the
        status to NOT_PLEDGED.
        """
        if self.pledge_status == PLEDGE_UNKNOWN:
            self.pledge_status = NOT_PLEDGED
            return True
        return False

    def apply_join(self, entry: Mapping[str, Any]) -> None:
        power = entry.get("Power")
        self.my_power = str(power) if power else self.my_power
        self.pledge_status = PLEDGED if self.my_power else self.pledge_status

    def apply_leave(self, entry: Mapping[str, Any]) -> None:
        self.my_power = None
        self.rank = None
        self.total_merits = None
        self.pledge_status = NOT_PLEDGED

    def apply_defect(self, entry: Mapping[str, Any]) -> None:
        to_power = entry.get("ToPower")
        self.my_power = str(to_power) if to_power else None
        self.pledge_status = PLEDGED if self.my_power else self.pledge_status
        # Merits don't carry over to the new power; start fresh so the next
        # PowerplayMerits event's TotalMerits diff isn't a huge, wrong number.
        self.total_merits = None

    def apply_rank(self, entry: Mapping[str, Any]) -> None:
        rank = entry.get("Rank")
        if isinstance(rank, int):
            self.rank = rank

    def apply_system_context(self, entry: Mapping[str, Any]) -> None:
        """FSDJump / Location / Docked: refresh PowerplayState + Powers for 'here'."""
        if "PowerplayState" not in entry and "Powers" not in entry:
            # Not a powerplay-relevant system right now. Deliberately don't
            # clear the previous context here — a Docked event, for instance,
            # doesn't repeat the fields of the FSDJump that got us here, and
            # that shouldn't erase a still-valid system context.
            return
        self.system_state = entry.get("PowerplayState")
        powers = entry.get("Powers")
        self.system_powers = [str(p) for p in powers] if isinstance(powers, list) else []

    def apply_merits(self, entry: Mapping[str, Any]) -> Optional[int]:
        """
        "PowerplayMerits" event: returns the merits gained, or None if there's
        nothing usable to report.

        Prefers the event's own "MeritsGained" (community-confirmed field,
        though undocumented by Frontier); falls back to diffing "TotalMerits"
        against the last known total, which is what EDMC's own state tracking
        relies on, so it's a solid fallback if MeritsGained is ever absent.

        Also resolves pledge status if it wasn't already: earning PowerPlay
        merits is only possible while pledged, so this recovers correctly
        even if EDMC attached to the game mid-session and never saw this
        commander's "Powerplay"/"Location" startup events.
        """
        power = entry.get("Power")
        if power and not self.my_power:
            self.my_power = str(power)
        if self.pledge_status != PLEDGED:
            self.pledge_status = PLEDGED

        total = entry.get("TotalMerits")
        gained = entry.get("MeritsGained")

        if not isinstance(gained, int):
            if isinstance(total, int) and self.total_merits is not None:
                gained = total - self.total_merits
            else:
                gained = None

        if isinstance(total, int):
            self.total_merits = total

        return gained if isinstance(gained, int) and gained > 0 else None

    def classify_current_activity(self) -> str:
        """Best-guess activity classification for merits earned right now."""
        if not self.my_power:
            return UNKNOWN

        state = (self.system_state or "").lower()
        controller = self.system_powers[0] if len(self.system_powers) == 1 else None

        if state in _CONTROLLED_STATES:
            if controller == self.my_power:
                return REINFORCEMENT
            if controller:
                return UNDERMINING
            # A controlled-type state but more than one Power listed: still
            # being fought over rather than settled, so treat as Acquisition
            # if we're one of the contenders.
            return ACQUISITION if self.my_power in self.system_powers else UNKNOWN

        if self.system_state:
            # Unoccupied / Contested / Turmoil / etc: nobody holds it yet.
            return ACQUISITION

        return UNKNOWN
