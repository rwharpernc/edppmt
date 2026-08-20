"""Merit -> Control Point (CP) conversion formulas for PowerPlay activities.

The journal's "PowerplayMerits" event reports the commander's actual merit
take, after every multiplier the game applies (system strength/frontline
penalties, ethos buffs, Squadron PP bonus, etc.). It does *not* say how many
Control Points that represents for the target system — that depends on which
activity (Acquisition / Reinforcement / Undermining) earned it, and Frontier
has never documented the conversion in the journal.

The ratios below are the best community-sourced figures available for
Powerplay 2.0. They are deliberately kept as plain, user-editable settings
(see ui.py) rather than baked into the code, since they are estimates and
Frontier is known to tune Powerplay balance between updates.
"""

from __future__ import annotations

from typing import Dict, Optional

ACQUISITION = "acquisition"
REINFORCEMENT = "reinforcement"
UNDERMINING = "undermining"
DELIVERY = "delivery"
UNKNOWN = "unknown"

# Order matters for UI display.
ACTIVITIES = (ACQUISITION, REINFORCEMENT, UNDERMINING, DELIVERY, UNKNOWN)

ACTIVITY_LABELS: Dict[str, str] = {
    ACQUISITION: "Acquisition",
    REINFORCEMENT: "Reinforcement",
    UNDERMINING: "Undermining",
    DELIVERY: "Delivery/Donation",
    UNKNOWN: "Unattributed",
}

# Merits required for 1 Control Point, by activity. Undermining is the least
# certain of the three community-sourced figures — correct it in Settings if
# you find your in-game CP totals don't line up.
#
# DELIVERY (commodity/data hand-ins at a power contact — see
# powerplay.apply_delivery_signal) deliberately has no ratio here: a hand-in's
# merits can count toward Acquisition, Reinforcement, *or* Undermining
# depending on what the commander chose in-game, and the journal doesn't say
# which — so, like UNKNOWN, it's tracked (merits, not CP) rather than guessed.
DEFAULT_RATIOS: Dict[str, float] = {
    ACQUISITION: 4.0,
    REINFORCEMENT: 2.5,
    UNDERMINING: 4.2,
}

# Activities with no merits-per-CP ratio — tracked by raw merit count only,
# since converting to CP would mean guessing at a conversion (or a target
# effect) the journal doesn't report.
NO_CP_ACTIVITIES = frozenset({DELIVERY, UNKNOWN})


def merits_to_cp(merits: float, ratio: Optional[float]) -> float:
    """Estimated Control Points for a batch of merits, given a merits-per-CP ratio."""
    if not ratio or ratio <= 0:
        return 0.0
    return merits / ratio
