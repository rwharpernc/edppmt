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

from .formulas import ACQUISITION, DELIVERY, REINFORCEMENT, UNDERMINING, UNKNOWN

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

# "SearchAndRescue" is shared by several mechanics (Thargoid War salvage,
# regular mission hand-ins, PowerPlay commodity delivery) — Frontier's
# PowerPlay commodity item names ("PowerAgriculture", "PowerComputer", etc.)
# all share this prefix, which is how a PowerPlay hand-in is told apart from
# the others.
_POWER_COMMODITY_PREFIX = "power"

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
        self.system_name: Optional[str] = None
        self.system_state: Optional[str] = None
        self.system_powers: List[str] = []
        self.system_controller: Optional[str] = None
        self.pledge_status: str = PLEDGE_UNKNOWN
        self._delivery_pending: bool = False

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
        self._delivery_pending = False

    def apply_delivery_signal(self, event: str, entry: Mapping[str, Any]) -> None:
        """
        "SearchAndRescue" (PowerPlay commodities only) or
        "DeliverPowerMicroResources" (on-foot PowerPlay data): a hand-in at a
        power contact. Frontier's journal doesn't link this to the
        "PowerplayMerits" event it triggers, so mark the *next* merit gain as
        a delivery rather than guessing an activity from system state — a
        hand-in's target (Acquisition/Reinforcement/Undermining) is chosen
        in-game and isn't reported either, so DELIVERY is tracked by merit
        count only, same as UNKNOWN (see formulas.NO_CP_ACTIVITIES).
        """
        if event == "DeliverPowerMicroResources":
            self._delivery_pending = True
            return
        if event == "SearchAndRescue":
            name = str(entry.get("Name", "")).lower()
            if name.startswith(_POWER_COMMODITY_PREFIX):
                self._delivery_pending = True

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
        # A fresh pledge starts at Rank 0; only trust an explicit field though.
        rank = entry.get("Rank")
        self.rank = rank if isinstance(rank, int) else 0

    def apply_leave(self, entry: Mapping[str, Any]) -> None:
        self.my_power = None
        self.rank = None
        self.total_merits = None
        self.pledge_status = NOT_PLEDGED

    def apply_defect(self, entry: Mapping[str, Any]) -> None:
        to_power = entry.get("ToPower")
        self.my_power = str(to_power) if to_power else None
        self.pledge_status = PLEDGED if self.my_power else self.pledge_status
        # Merits and rank don't carry over to the new power; start fresh so
        # the next PowerplayMerits event's TotalMerits diff isn't a huge,
        # wrong number, and so the old power's rank isn't shown against the
        # new one until "PowerplayRank" corrects it.
        self.total_merits = None
        rank = entry.get("Rank")
        self.rank = rank if isinstance(rank, int) else 0

    def apply_rank(self, entry: Mapping[str, Any]) -> None:
        rank = entry.get("Rank")
        if isinstance(rank, int):
            self.rank = rank

    def pledge_summary(self) -> Optional[str]:
        """Human-readable "Power (Rank N)" string, or None if not pledged."""
        if not self.my_power:
            return None
        if self.rank is not None:
            return f"{self.my_power} (Rank {self.rank})"
        return self.my_power

    def apply_system_context(self, system: Optional[str], entry: Mapping[str, Any]) -> None:
        """FSDJump / Location / Docked: refresh PowerplayState/Powers/ControllingPower for 'here'.

        `system` is EDMC's own live-tracked current system name (the `system`
        argument `journal_entry` receives, sourced from monitor.state), not
        parsed from the entry itself — it's the authoritative answer to
        "where are we right now" regardless of which fields this particular
        event happens to carry, and lets classify_current_activity() notice
        when the commander has moved on from the system this context
        describes (see there).
        """
        if "PowerplayState" not in entry and "Powers" not in entry and "ControllingPower" not in entry:
            # Not a powerplay-relevant system right now. Deliberately don't
            # clear the previous context here — a Docked event, for instance,
            # doesn't repeat the fields of the FSDJump that got us here, and
            # that shouldn't erase a still-valid system context.
            return
        self.system_name = system
        self.system_state = entry.get("PowerplayState")
        powers = entry.get("Powers")
        self.system_powers = [str(p) for p in powers] if isinstance(powers, list) else []
        # "Powers" lists *every* Power active in the system — the controller
        # plus any rival actively undermining it — so it can have more than
        # one entry even in a settled Stronghold/Fortified/Exploited system.
        # "ControllingPower" is the one field that actually names who holds
        # it; classify_current_activity() relies on this, not on Powers'
        # length, to tell Reinforcement/Undermining apart in that case.
        controller = entry.get("ControllingPower")
        self.system_controller = str(controller) if controller else None

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

    def classify_current_activity(self, current_system: Optional[str] = None) -> str:
        """Best-guess activity classification for merits earned right now.

        `current_system` is EDMC's live-tracked system name as of the merit
        gain (see apply_system_context). If it doesn't match the system our
        stored PowerplayState/Powers context was captured in, that context is
        stale — the commander has moved on since the last powerplay-relevant
        event — so it's better to admit we don't know than to misattribute
        using a different system's data. Omit it (or pass None) to skip this
        check and classify from the stored context regardless, as before.

        A pending delivery signal (see apply_delivery_signal) takes priority
        over all of that — a commodity/data hand-in's merits aren't a guess
        from system state at all, they're a direct signal of their own, and
        can be turned in at a different system than where the goods were
        collected. This also consumes the pending flag, so it only ever
        applies to the merit gain it actually triggered.
        """
        if self._delivery_pending:
            self._delivery_pending = False
            return DELIVERY

        if not self.my_power:
            return UNKNOWN

        if current_system and self.system_name and current_system != self.system_name:
            return UNKNOWN

        state = (self.system_state or "").lower()
        controller = self.system_controller

        if state in _CONTROLLED_STATES:
            if controller == self.my_power:
                return REINFORCEMENT
            if controller:
                return UNDERMINING
            # A controlled-type state but no ControllingPower reported
            # (shouldn't normally happen): fall back to Acquisition if we're
            # among the Powers listed as active there.
            return ACQUISITION if self.my_power in self.system_powers else UNKNOWN

        if self.system_state:
            # Unoccupied / Contested / Turmoil / etc: nobody holds it yet.
            return ACQUISITION

        return UNKNOWN
