"""Clipboard copy formatting for the Sessions window's "Copy Progress" button.

Kept as pure functions (no Tk imports) so they're trivially testable and
reusable from the Rares window too (both need an Inara system-search URL).
"""

from __future__ import annotations

from urllib.parse import quote

DEFAULT_TEMPLATE = "[{system}]({system_url}) - {merits} merits (~{cp} CP) - {state}"

# Documented for the Settings tab's placeholder legend.
PLACEHOLDERS = ("{system}", "{system_url}", "{merits}", "{cp}", "{state}")


def inara_system_url(system: str) -> str:
    """Inara.cz system-search URL for `system` — clicking it lands on that
    system's page (Inara resolves the search itself; there's no public API
    for the numeric system ID Inara's own URLs otherwise use)."""
    return f"https://inara.cz/elite/starsystem/?search={quote(system)}"


def format_system_line(
    template: str, *, system: str, merits: str, cp: str, state: str,
) -> str:
    """Substitutes the placeholders in `template` for one system's row.
    Falls back to the raw template on a malformed/unknown placeholder rather
    than raising into a Tk button callback."""
    try:
        return template.format(
            system=system, system_url=inara_system_url(system), merits=merits, cp=cp, state=state,
        )
    except (KeyError, IndexError, ValueError):
        return template
