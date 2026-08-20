# EDPPMT Technical Specification

**Version:** 1.3.0
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
│   ├── update.py           # UpdateManager: background self-update from GitHub Releases
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
| `plugin_start3(plugin_dir: str) -> str` | `load.py` | Initialisation; creates the `SessionManager`, starts the background update check (`UpdateManager.check_async`, see §11), returns `"EDPPMT"`. |
| `plugin_stop() -> None` | `load.py` | Shutdown hook; flushes session state to disk, closes the Sessions window. |
| `plugin_app(parent: tk.Frame) -> tk.Frame` | `load.py` | Creates the main-window summary strip. |
| `plugin_prefs(parent, cmdr, is_beta) -> nb.Frame` | `load.py` | Creates the Settings tab (ratio table + auto-update checkbox). |
| `prefs_changed(cmdr, is_beta) -> None` | `load.py` | Persists ratio and auto-update settings; flushes session state. |
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
from monitor import monitor         # monitor.logfile — journal file identity (load.py)
import requests                     # GitHub Releases API + download (update.py) — bundled by EDMC itself
```

`state['Credits']` (EDMC's own running balance, built from dozens of journal event types — see `monitor.py` in EDMC core) is read from the `state` dict passed into `journal_entry()`; PowerPlay pledge/merit/system state is tracked independently by `powerplay.py` directly from journal entries, not from `state['Powerplay']`, so that mid-session defection (`PowerplayDefect`) is handled correctly even though EDMC's own `state['Powerplay']` doesn't track that event. `monitor.logfile` (the path of the journal file EDMC is currently tailing) is read directly to detect whether a login is a continuation of the same journal file — see §4 and §7.

## 4. Journal Event Handling

Dispatched in `load._dispatch`, delegating to `PowerplayTracker` (`powerplay.py`) and `SessionManager` (`session.py`):

| Event | Handling |
|---|---|
| `LoadGame` | Reconciles the session against the journal EDMC is now tailing (`SessionManager.sync_session`, keyed on `monitor.logfile` — see §7). Resets pledge tracking (`PowerplayTracker.apply_login_reset`) *only* if `sync_session` reports a new session, not a same-journal continuation — see §5. |
| `StartUp` | Synthesized by EDMC when it (re)starts with the game already running (no journal replay in this case — see §5). Reconciles the session the same way `LoadGame` does. |
| `Powerplay` | Written at startup only if pledged. Sets pledged Power/Rank/merit baseline; resolves pledge status to `pledged`. |
| `PowerplayJoin` / `PowerplayDefect` / `PowerplayLeave` | Keep pledged Power current mid-session (EDMC's own `state['Powerplay']` does not track these). |
| `PowerplayRank` | Updates tracked rank. |
| `Location` | Always fires once at startup. Used as the checkpoint to resolve pledge status to `not_pledged` if no `Powerplay` event arrived first (see §5). Also a system-context event (see below). |
| `FSDJump`, `Docked` | Refresh the current system's name/`PowerplayState`/`Powers` fields, when present (`PowerplayTracker.apply_system_context`). |
| `SearchAndRescue`, `DeliverPowerMicroResources` | PowerPlay commodity/data hand-ins (`PowerplayTracker.apply_delivery_signal`) — see §6. |
| `PowerplayMerits` | The core event. See §6. |

Every dispatch also forwards the `system` argument `journal_entry` receives — EDMC's own live-tracked current system name, not parsed from the entry — so `PowerplayTracker` always knows both which system its stored context describes and which system the commander is actually in right now (see §6).

Every call to `journal_entry` also updates `SessionManager`'s live credit tracking from `state['Credits']`, regardless of event type, so the credits/hr rate stays current between merit-earning events.

## 5. Pledge Detection

There is no journal event for "you are NOT pledged" — only `Powerplay`, which fires at startup *if* pledged. EDPPMT resolves the negative case by using `Location` (always written at startup) as a checkpoint: if pledge status is still unresolved when `Location` arrives, it's set to `not_pledged`. In practice `Location` and `Powerplay` can arrive in either order — both have been observed with the same timestamp, `Location` first — so this is a same-batch race, not a strict ordering guarantee: if `Location` is processed first, pledge status is transiently (and incorrectly) resolved to `not_pledged`, then immediately corrected once `Powerplay`'s own handler runs, since `apply_login_snapshot` unconditionally overwrites it.

That correction depends on `Powerplay` actually arriving, though — and it only arrives on the *first* login of a client launch. A logout to the main menu and back in sends a fresh `LoadGame`, but Frontier does **not** re-send `Powerplay` on it, since the pledge itself hasn't changed. Resetting pledge tracking on every `LoadGame` (as EDPPMT originally did) therefore threw the correct pledge away on every relog, with nothing left to reconfirm it — permanently showing "not pledged" for the rest of the session once the relog's own `Location` event resolved it. Fixed by only calling `apply_login_reset` when `SessionManager.sync_session` reports a new session (§7) rather than a same-journal continuation — a relog keeps whatever pledge state is already tracked.

If EDMC attaches to an already-running game, this startup sequence may already be behind the "replay window" EDMC exposes to plugins: EDMC does not replay backlog journal events to plugins on its own startup — only genuinely new events are passed to `journal_entry`, plus one synthesized `StartUp` event (with `cmdr`/`state` already reconstructed from the full file) if the game is running, or nothing at all if it isn't. To cover this, `PowerplayTracker.apply_merits` also opportunistically resolves pledge status (and Power) from the first `PowerplayMerits` event seen, since earning PowerPlay merits is only possible while pledged.

## 6. Merit → Activity → CP Pipeline

1. **`PowerplayTracker.apply_merits(entry)`** — reads `MeritsGained` if present; otherwise diffs the event's `TotalMerits` against the last known total (matching how EDMC's own `monitor.py` maintains `state['Powerplay']['Merits']`). Also updates the running `total_merits` baseline.
2. **`PowerplayTracker.apply_delivery_signal(event, entry)`** — called on `SearchAndRescue` (filtered to `Power*`-named commodities only, since the event is shared with Thargoid War/mission salvage hand-ins) and `DeliverPowerMicroResources` (on-foot PowerPlay data, unambiguous by event name alone). Sets a one-shot `_delivery_pending` flag: the journal doesn't link a hand-in to the `PowerplayMerits` event it triggers, so this is a same-tick correlation, not a field on the merits event itself.
3. **`PowerplayTracker.classify_current_activity(current_system)`** — if `_delivery_pending` is set, consumes it and returns `delivery` immediately, bypassing every check below (a hand-in can be turned in at a different system than where the goods were collected, and doesn't require a resolved pledge to have been the source). Otherwise, compares the last-seen system `PowerplayState`/`Powers` against the pledged Power (see README's "How activity is classified" for the exact rule) and returns one of `acquisition` / `reinforcement` / `undermining` / `unknown`. `current_system` is EDMC's own live-tracked system name (the `system` argument `journal_entry` receives — see §3.3), captured at the moment the merits landed; if it doesn't match `system_name` (the system the stored `PowerplayState`/`Powers` context was captured in), that context is stale and classification falls through to `unknown` rather than misattributing to the wrong system.
4. **`SessionManager.record_merits(activity, merits)`** — adds the raw merit count to the current session's per-activity totals. **Raw merits only — no CP is stored.**
5. **Display time** — `formulas.merits_to_cp(merits, ratio)` converts merits to an estimated CP figure using the *current* ratio from Settings (`ui.ratio_for(activity)`), for both the live panel and the Sessions window, including history entries. Changing a ratio in Settings therefore retroactively changes CP estimates for every stored session, not just new merit gains. `delivery` and `unknown` (`formulas.NO_CP_ACTIVITIES`) are excluded from this — see §6.1.

### 6.1 Why `delivery` has no CP ratio

A hand-in's target effect (Acquisition/Reinforcement/Undermining) is chosen in-game and isn't reported in the journal, so there's no correct single ratio to convert it with — same reasoning as `unknown`. `delivery` is tracked by raw merit count for visibility (so it isn't silently folded into `unknown`), not converted to CP.

## 7. Session Data Format (`sessions.json`)

Persisted next to the installed plugin by `store.SessionStore`, capped at the 200 most recent history entries (`store.MAX_HISTORY`):

```json
{
  "history": [ /* past session objects, oldest first */ ],
  "current": {
    "id": "32-char hex uuid",
    "cmdr": "CommanderName",
    "power": "Zachary Hudson",
    "started_at": "2026-08-20T18:44:33Z",
    "updated_at": "2026-08-20T19:12:01Z",
    "credits_start": 1000000,
    "credits_now": 1010000,
    "totals": { "acquisition": 80, "reinforcement": 40, "undermining": 80, "unknown": 0 },
    "events": { "acquisition": 1, "reinforcement": 1, "undermining": 2, "unknown": 0 },
    "journal_file": "C:\\...\\Journal.2026-08-20T184433.01.log"
  }
}
```

`SessionStore.load()` accepts the legacy pre-1.2.0 flat-array format too (the whole array is treated as `history`, with no `current` to resume — there's no way to tell in hindsight which entry was still live at last save).

### Session continuity (`SessionManager.sync_session`)

A session is tied to the journal file it started on (`journal_file`, from `monitor.logfile`). `sync_session` (called on `LoadGame` and the synthesized `StartUp` — see §4) compares the journal file EDMC is now tailing against `current["journal_file"]`:

- **Same file** → the same continuous session: a commander logout to the main menu and back in, or an EDMC restart while the game keeps running, both reuse the same journal file. `current` is kept as-is (no data lost, no history entry created).
- **Different (or no) file** → the previous session has ended: `current` (if it had any data) is appended to `history`, and a fresh session starts for the new journal file. "The game isn't running" is treated as "no active journal file" — `load.py` passes `monitor.logfile` (not `None`) only when `monitor.game_running()` is also true.

Because EDMC does not replay old journal lines to plugins (§5), resuming an existing `current` across an EDMC restart is possible precisely *because* `SessionStore` now persists `current` and `history` as separate fields — the totals already on disk are the totals, not something to be rebuilt from a replay.

`SessionStore.save()` always writes `history` and `current` together, so the file on disk reflects the live session too — a plugin/EDMC crash loses at most whatever wasn't yet flushed (see §8).

## 8. Persistence Timing

`SessionManager._persist()` (a full JSON rewrite) is called on: `sync_session`/`start_session`, `record_merits`, and `flush()` (called from `plugin_stop` and `prefs_changed`). It is deliberately **not** called from `record_credits`, since that runs on every single journal event — persisting there would mean a disk write per event during normal play. This means a mid-session credit change can be lost if EDMC/the game crashes before the next merit gain or a clean shutdown; merit totals are never at risk this way, since `record_merits` always persists immediately.

## 9. Ratio Settings Storage

Stored as EDMC config string values, one per activity: `edppmt_ratio_acquisition`, `edppmt_ratio_reinforcement`, `edppmt_ratio_undermining` (see `ui.CONFIG_RATIO_PREFIX`). Missing or invalid values fall back to `formulas.DEFAULT_RATIOS`.

## 10. Self-Update (`update.py`)

`UpdateManager.check_async()` is called once, from `plugin_start3`. It's a no-op if either the `edppmt_auto_update` config setting (default on, toggled from the Settings tab) is off, or a `disable-auto-update.txt` file exists directly in `plugin_dir` — a hardcoded escape hatch for a folder being actively hand-edited (e.g. local development), independent of and not visible in Settings.

Otherwise it spawns a daemon thread that:

1. **GETs** `https://api.github.com/repos/rwharpernc/edppmt/releases/latest` (skips draft/prerelease responses) and compares its `tag_name` against `plugin.__version__`, both parsed as plain `(major, minor, patch)` integer tuples — no `semantic_version` dependency, since project versions never carry prerelease/build suffixes. A newer *or equal* remote version is a no-op.
2. If newer, **downloads** the first `.zip` release asset to `plugin_dir/updates/`.
3. **Backs up** the current plugin folder to a timestamped zip in `plugin_dir/backups/` (walking `plugin_dir`, excluding `updates/`, `backups/`, `__pycache__/`, and `sessions.json`), then trims backups down to the 3 most recent.
4. **Extracts** the downloaded zip over `plugin_dir`, stripping the top-level `EDPPMT/` folder the release zip is packaged with (see `scripts/package.mjs`) — so files land directly in `plugin_dir`, and `sessions.json` is skipped by name even though it never appears in the zip anyway (it isn't part of the distributed source, same as the repo's own `.gitignore`).
5. Calls `on_ready(version)` (the callback passed to `UpdateManager.__init__`) — `load.py` marshals this onto the Tk main thread via `frame.after(0, ...)` before touching any widget, since `update.py` itself has no Tkinter dependency and runs entirely off the main thread up to this point.

Nothing here reloads running code — Python already has the old modules loaded in memory for this process. The staged files only take effect the *next* time EDMC starts, which is why step 5 surfaces a "restart to apply" notice (`ui.set_update_status`) in the main panel rather than claiming the update is live.

## 11. Known Limitations

- Activity classification is a heuristic (§4/§6), not a value the game reports directly — see `docs/ATTRIBUTIONS.md` for the sourcing and its confidence level, and the README for the classification rule.
- The full set of `PowerplayState` values Frontier currently uses isn't documented (the last official journal manual predates Powerplay 2.0); `powerplay._CONTROLLED_STATES` is a conservative, extensible set rather than an exhaustive one.
- No CAPI integration for PowerPlay data — the merit/pledge/session data reflects the local journal stream only. (`update.py` does make outbound HTTPS requests to GitHub — the one exception to an otherwise fully local plugin — see §10.)
