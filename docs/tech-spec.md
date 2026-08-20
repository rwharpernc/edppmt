# EDPPMT Technical Specification

**Version:** 1.0.0
**Author:** R.W. Harper (CMDR Bocheaux)
**Last updated:** 2026-08-20

## 1. Overview

EDPPMT is a **package plugin** for Elite Dangerous Market Connector. It implements the EDMC Python 3 plugin API (`plugin_start3`) and processes journal events delivered through `journal_entry()`.

| Property | Value |
|----------|-------|
| Plugin folder name | `EDPPMT` (must match for EDMC logging) |
| Internal display name | `EDPPMT` (returned from `plugin_start3`) |
| Language | Python 3.9+ (bundled with EDMC) |
| UI framework | Tkinter (via EDMC main window) |
| Build output | `dist/EDPPMT/` |

## 2. Repository Layout

```
edppmt/
├── plugin/                 # Source — deployed to dist/EDPPMT/
│   ├── __init__.py         # __version__
│   ├── load.py             # EDMC callbacks (entry point); journal event dispatch
│   ├── formulas.py         # Activity constants + merits-per-CP ratio table
│   ├── powerplay.py        # PowerplayTracker: pledge state, system context, classification
│   ├── session.py          # Session dict helpers + SessionManager (live + history)
│   ├── store.py            # sessions.json persistence
│   ├── ui.py                # Tkinter panel + settings tab (also owns ratio config access)
│   └── window.py           # Sessions Toplevel (Current Session / History tabs)
├── scripts/build.mjs       # Copies plugin/ → dist/EDPPMT/
├── docs/                   # Specifications and attributions
├── dist/EDPPMT/            # Build artefact (gitignored)
├── LICENSE                 # MIT
├── CHANGELOG.md
└── README.md
```

## 3. EDMC Plugin API Surface

### 3.1 Implemented callbacks

| Function | Module | Description |
|----------|--------|--------------|
| `plugin_start3(plugin_dir: str) -> str` | `load.py` | Initialisation; creates the `SessionManager`, returns `"EDPPMT"`. |
| `plugin_stop() -> None` | `load.py` | Shutdown hook; flushes session state to disk, closes the Sessions window. |
| `plugin_app(parent: tk.Frame) -> tk.Frame` | `load.py` | Creates the main-window summary strip. |
| `plugin_prefs(parent, cmdr, is_beta) -> nb.Frame` | `load.py` | Creates the Settings tab (ratio table). |
| `prefs_changed(cmdr, is_beta) -> None` | `load.py` | Persists ratio settings; flushes session state. |
| `journal_entry(...) -> Optional[str]` | `load.py` | Processes journal events (see §4). |

### 3.2 Not implemented

- `cmdr_data` / `capi_fleetcarrier` — no CAPI integration; all data comes from the journal and the `state` dict.
- `dashboard_entry` — `Status.json` is not read.
- `journal_entry_cqc` — CQC/Arena sessions ignored.

### 3.3 Allowed EDMC imports

```python
from config import appname          # Logger naming
from config import config           # Settings + window geometry persistence
from theme import theme             # UI theming (ui.py, window.py)
import myNotebook as nb             # Settings tab widgets (ui.py)
```

No other core EDMC modules are imported. `state['Credits']` (EDMC's own running balance, built from dozens of journal event types — see `monitor.py` in EDMC core) is read from the `state` dict passed into `journal_entry()`; PowerPlay pledge/merit/system state is tracked independently by `powerplay.py` directly from journal entries, not from `state['Powerplay']`, so that mid-session defection (`PowerplayDefect`) is handled correctly even though EDMC's own `state['Powerplay']` doesn't track that event.

## 4. Journal Event Handling

Dispatched in `load._dispatch`, delegating to `PowerplayTracker` (`powerplay.py`) and `SessionManager` (`session.py`):

| Event | Handling |
|---|---|
| `LoadGame` | Starts a new session (`SessionManager.start_session`); resets pledge tracking (`PowerplayTracker.apply_login_reset`). |
| `Powerplay` | Written at startup only if pledged. Sets pledged Power/Rank/merit baseline; resolves pledge status to `pledged`. |
| `PowerplayJoin` / `PowerplayDefect` / `PowerplayLeave` | Keep pledged Power current mid-session (EDMC's own `state['Powerplay']` does not track these). |
| `PowerplayRank` | Updates tracked rank. |
| `Location` | Always fires once at startup. Used as the checkpoint to resolve pledge status to `not_pledged` if no `Powerplay` event arrived first (see §5). Also a system-context event (see below). |
| `FSDJump`, `Docked` | Refresh the current system's `PowerplayState` / `Powers` fields, when present. |
| `PowerplayMerits` | The core event. See §6. |

Every call to `journal_entry` also updates `SessionManager`'s live credit tracking from `state['Credits']`, regardless of event type, so the credits/hr rate stays current between merit-earning events.

## 5. Pledge Detection

There is no journal event for "you are NOT pledged" — only `Powerplay`, which fires at startup *if* pledged. EDPPMT resolves the negative case by using `Location` (documented as always written at startup, after `Powerplay` would have been) as a checkpoint: if pledge status is still unresolved when `Location` arrives, it's set to `not_pledged`.

If EDMC attaches to an already-running game, this startup sequence may already be behind the "replay window" EDMC exposes to plugins (EDMC does not replay backlog journal events to plugins on its own startup — only genuinely new events are passed to `journal_entry`). To cover this, `PowerplayTracker.apply_merits` also opportunistically resolves pledge status (and Power) from the first `PowerplayMerits` event seen, since earning PowerPlay merits is only possible while pledged.

## 6. Merit → Activity → CP Pipeline

1. **`PowerplayTracker.apply_merits(entry)`** — reads `MeritsGained` if present; otherwise diffs the event's `TotalMerits` against the last known total (matching how EDMC's own `monitor.py` maintains `state['Powerplay']['Merits']`). Also updates the running `total_merits` baseline.
2. **`PowerplayTracker.classify_current_activity()`** — compares the last-seen system `PowerplayState`/`Powers` against the pledged Power (see README's "How activity is classified" for the exact rule) and returns one of `acquisition` / `reinforcement` / `undermining` / `unknown`.
3. **`SessionManager.record_merits(activity, merits)`** — adds the raw merit count to the current session's per-activity totals. **Raw merits only — no CP is stored.**
4. **Display time** — `formulas.merits_to_cp(merits, ratio)` converts merits to an estimated CP figure using the *current* ratio from Settings (`ui.ratio_for(activity)`), for both the live panel and the Sessions window, including history entries. Changing a ratio in Settings therefore retroactively changes CP estimates for every stored session, not just new merit gains.

## 7. Session Data Format (`sessions.json`)

A JSON array of session objects (most recent last), persisted next to the installed plugin by `store.SessionStore`, capped at the 200 most recent (`store.MAX_HISTORY`):

```json
{
  "id": "32-char hex uuid",
  "cmdr": "CommanderName",
  "power": "Zachary Hudson",
  "started_at": "2026-08-20T18:44:33Z",
  "updated_at": "2026-08-20T19:12:01Z",
  "credits_start": 1000000,
  "credits_now": 1010000,
  "totals": { "acquisition": 80, "reinforcement": 40, "undermining": 80, "unknown": 0 },
  "events": { "acquisition": 1, "reinforcement": 1, "undermining": 2, "unknown": 0 }
}
```

`SessionManager` keeps the in-progress session as `current` and appends it to `history` only when a new `LoadGame` starts a fresh one (or on the very first `LoadGame` seen after a prior session had data). `SessionStore.save()` always writes `history + [current]` as a single array, so the file on disk always reflects the live session too — a plugin/EDMC crash loses at most whatever wasn't yet flushed (see §8).

## 8. Persistence Timing

`SessionManager._persist()` (a full JSON rewrite) is called on: `start_session`, `record_merits`, and `flush()` (called from `plugin_stop` and `prefs_changed`). It is deliberately **not** called from `record_credits`, since that runs on every single journal event — persisting there would mean a disk write per event during normal play. This means a mid-session credit change can be lost if EDMC/the game crashes before the next merit gain or a clean shutdown; merit totals are never at risk this way, since `record_merits` always persists immediately.

## 9. Ratio Settings Storage

Stored as EDMC config string values, one per activity: `edppmt_ratio_acquisition`, `edppmt_ratio_reinforcement`, `edppmt_ratio_undermining` (see `ui.CONFIG_RATIO_PREFIX`). Missing or invalid values fall back to `formulas.DEFAULT_RATIOS`.

## 10. Known Limitations

- Activity classification is a heuristic (§4/§6), not a value the game reports directly — see `docs/ATTRIBUTIONS.md` for the sourcing and its confidence level, and the README for the classification rule.
- The full set of `PowerplayState` values Frontier currently uses isn't documented (the last official journal manual predates Powerplay 2.0); `powerplay._CONTROLLED_STATES` is a conservative, extensible set rather than an exhaustive one.
- No CAPI integration — data reflects the local journal stream only.
