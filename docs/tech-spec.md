# EDPPMT Technical Specification

**Version:** 1.11.0
**Author:** R.W. Harper (CMDR Bocheaux)
**Last updated:** 2026-09-02

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
│   ├── autohonk.py         # AutoHonkController: binds-file lookup + Win32 key injection
│   ├── clipboard.py        # Inara URL builders + "Copy Progress" line template substitution
│   ├── formulas.py         # Activity constants + merits-per-CP ratio table
│   ├── interdiction.py     # InterdictionTracker: detection state machine + overlay rendering
│   ├── landing.py          # LandingTracker: docking state machine + pad-diagram overlay rendering
│   ├── overlay.py          # OverlayClient: EDMCOverlay TCP/JSON transport (generic, reusable)
│   ├── powerplay.py        # PowerplayTracker: pledge state, system context, classification, journal-file pledge recovery
│   ├── powerplay_lookup.py # Live Controlling-Power lookup (Spansh API) for the Rares window, threaded + cached
│   ├── rares.py             # Rare-goods dataset loader: nearest-N-by-distance
│   ├── rare_goods.json     # Bundled rare-goods dataset (141 entries, coords + Inara/Spansh ids baked in — see ATTRIBUTIONS.md)
│   ├── rares_window.py     # Rares Toplevel (nearest rare goods to the current system)
│   ├── session.py          # Session dict helpers (incl. per-system totals) + SessionManager (live + history)
│   ├── store.py            # sessions.json persistence
│   ├── update.py           # UpdateManager: background self-update from GitHub Releases
│   ├── ui.py                # Tkinter panel + settings tab (also owns ratio/clipboard-format config access)
│   └── window.py           # Sessions Toplevel (Current Session / History tabs; reset + copy-progress buttons)
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
| `plugin_prefs(parent, cmdr, is_beta) -> nb.Frame` | `load.py` | Creates the Settings tab: a static version link, then a bordered `nb.Notebook` with four sub-tabs, one per feature — **Tracking** (CP Ratios + Clipboard, grouped), **Auto-Honk**, **Interdiction Warning**, **Updates** (`ui.create_prefs`, `ui._create_grouped_tab`, `ui._create_single_tab`). |
| `prefs_changed(cmdr, is_beta) -> None` | `load.py` | Persists ratio, clipboard, Auto-Honk, Interdiction Warning/overlay, and auto-update settings; reloads the live `AutoHonkController`'s config; flushes session state. |
| `dashboard_entry(cmdr, is_beta, entry) -> None` | `load.py` | Called on every `Status.json` change (~1/sec in flight); forwards `entry["Flags"]` to `InterdictionTracker.handle_dashboard_flags` — see §13. |
| `journal_entry(...) -> Optional[str]` | `load.py` | Processes journal events (see §4). |

### 3.2 Not implemented

- `cmdr_data` / `capi_fleetcarrier` — no CAPI integration; all data comes from the journal and the `state` dict.
- `journal_entry_cqc` — CQC/Arena sessions ignored.

### 3.3 Allowed EDMC imports

```python
from config import appname          # Logger naming
from config import config           # Settings + window geometry persistence
from theme import theme             # UI theming (ui.py, window.py)
import myNotebook as nb             # Settings tab widgets (ui.py)
from monitor import monitor         # monitor.logfile — journal file identity (load.py)
import requests                     # GitHub Releases API + download (update.py); Spansh Controlling-Power lookup (powerplay_lookup.py) — bundled by EDMC itself
```

`state['Credits']` (EDMC's own running balance, built from dozens of journal event types — see `monitor.py` in EDMC core) is read from the `state` dict passed into `journal_entry()`; PowerPlay pledge/merit/system state is tracked independently by `powerplay.py` directly from journal entries, not from `state['Powerplay']`, so that mid-session defection (`PowerplayDefect`) is handled correctly even though EDMC's own `state['Powerplay']` doesn't track that event. `monitor.logfile` (the path of the journal file EDMC is currently tailing) is read directly to detect whether a login is a continuation of the same journal file — see §4 and §7.

`autohonk.py` deliberately does **not** add to this list. EDMC bundles `pywin32`/`psutil` for its own Windows build, but EDMC itself is not Windows-only, and this module needs to stay importable (and gracefully inert) on every platform EDMC runs on. Its Win32 key-injection and window-lookup calls (`FindWindowW`, `keybd_event`, `SetForegroundWindow`, the `AttachThreadInput` foreground-lock workaround) go through the standard-library `ctypes` module directly against `user32.dll`/`kernel32.dll`, guarded behind `sys.platform == "win32"` checks rather than an import-time dependency — see §12.

## 4. Journal Event Handling

Dispatched in `load._dispatch`, delegating to `PowerplayTracker` (`powerplay.py`) and `SessionManager` (`session.py`):

| Event | Handling |
|---|---|
| `LoadGame` | Reconciles the session against the journal EDMC is now tailing (`SessionManager.sync_session`, keyed on `monitor.logfile` — see §7). Resets pledge tracking (`PowerplayTracker.apply_login_reset`) *only* if `sync_session` reports a new session, not a same-journal continuation — see §5. Also reads `GameMode`/`Group` off this same live entry to set the main panel's Mode line (`load._mode_text`) — Open / Solo / Private (group name). |
| `StartUp` | Synthesized by EDMC when it (re)starts with the game already running (no journal replay in this case — see §5). Reconciles the session the same way `LoadGame` does. Since the synthesized entry carries no `GameMode`/`Group` (no real `LoadGame` line was delivered), `load._recover_game_mode()` reads the journal file directly for its `LoadGame` line — a short forward scan (`GameMode` is always near the top of the file, unlike pledge events which can recur, so this doesn't need `_iter_lines_reverse`'s backward-chunk approach). |
| `Powerplay` | Written at startup only if pledged. Sets pledged Power/Rank/merit baseline; resolves pledge status to `pledged`. |
| `PowerplayJoin` / `PowerplayDefect` / `PowerplayLeave` | Keep pledged Power current mid-session (EDMC's own `state['Powerplay']` does not track these). |
| `PowerplayRank` | Updates tracked rank. |
| `Location` | Always fires once at startup. Used as the checkpoint to resolve pledge status to `not_pledged` if no `Powerplay` event arrived first (see §5). Also a system-context event (see below). |
| `FSDJump`, `Docked` | Refresh the current system's name/`PowerplayState`/`Powers`/`ControllingPower` fields, when present (`PowerplayTracker.apply_system_context`). |
| `FSDJump`, `CarrierJump` | Also forwarded to `AutoHonkController.handle_event` — see §12. |
| `SearchAndRescue`, `DeliverPowerMicroResources` | PowerPlay commodity/data hand-ins (`PowerplayTracker.apply_delivery_signal`) — see §6. |
| `PowerplayMerits` | The core event. See §6. |
| `ReceiveText`, `Interdicted`, `EscapeInterdiction` | Forwarded to `InterdictionTracker.handle_event` — see §13. |
| `DockingRequested`, `DockingGranted`, `DockingDenied`, `DockingTimeout`, `DockingCancelled`, `Docked`, `Undocked`, `FSDJump`, `CarrierJump`, `SupercruiseEntry` | Forwarded to `LandingTracker.handle_event` — see §14. |

`_dispatch` forwards *every* event (not just the ones in the table above) to `AutoHonkController.handle_event` first, unconditionally — the controller itself is what filters for `FSDJump`/`CarrierJump` and whether Auto-Honk is enabled, the same way `PowerplayTracker`'s methods are only ever called for the specific events they handle. See §12. `InterdictionTracker.handle_event` and `LandingTracker.handle_event` are similarly cheap to call regardless of whether their feature is enabled — only the actual overlay draw (`_on_interdiction_change`/`_on_landing_change`) is gated on Settings. See §13/§14.

Every dispatch also forwards the `system` argument `journal_entry` receives — EDMC's own live-tracked current system name, not parsed from the entry — so `PowerplayTracker` always knows both which system its stored context describes and which system the commander is actually in right now (see §6).

Every call to `journal_entry` also updates `SessionManager`'s live credit tracking from `state['Credits']`, regardless of event type, so the credits/hr rate stays current between merit-earning events.

## 5. Pledge Detection

There is no journal event for "you are NOT pledged" — only `Powerplay`, which fires at startup *if* pledged. EDPPMT resolves the negative case by using `Location` (always written at startup) as a checkpoint: if pledge status is still unresolved when `Location` arrives, it's set to `not_pledged`. In practice `Location` and `Powerplay` can arrive in either order — both have been observed with the same timestamp, `Location` first — so this is a same-batch race, not a strict ordering guarantee: if `Location` is processed first, pledge status is transiently (and incorrectly) resolved to `not_pledged`, then immediately corrected once `Powerplay`'s own handler runs, since `apply_login_snapshot` unconditionally overwrites it.

That correction depends on `Powerplay` actually arriving, though — and it only arrives on the *first* login of a client launch. A logout to the main menu and back in sends a fresh `LoadGame`, but Frontier does **not** re-send `Powerplay` on it, since the pledge itself hasn't changed. Resetting pledge tracking on every `LoadGame` (as EDPPMT originally did) therefore threw the correct pledge away on every relog, with nothing left to reconfirm it — permanently showing "not pledged" for the rest of the session once the relog's own `Location` event resolved it. Fixed by only calling `apply_login_reset` when `SessionManager.sync_session` reports a new session (§7) rather than a same-journal continuation — a relog keeps whatever pledge state is already tracked *in memory*.

"In memory" is the operative phrase: if EDMC (or this plugin) restarts between the relog and the next event, `PowerplayTracker` is a fresh instance that never saw the original `Powerplay` event, and — since Frontier won't resend it — there's no live event left to recover it from either. `load._recover_pledge_state()` closes this gap by falling back to the journal file itself, whenever `PowerplayTracker.pledge_status` is still `unknown` going into the same-journal `LoadGame` branch or the `StartUp` handler (see §4): `powerplay.find_last_pledge_event(monitor.logfile)` reads the file backward in chunks (`powerplay._iter_lines_reverse`, no full-file load) for the most recent pledge-lifecycle event — `Powerplay`, `PowerplayJoin`, `PowerplayLeave`, or `PowerplayDefect`, whichever happened *last* (not just `Powerplay` alone, since a commander who pledged and then left or defected mid-launch would otherwise be recovered as still holding the original pledge) — stopping at `Fileheader`, the first line of every journal file. `load._PLEDGE_EVENT_APPLIERS` maps the found event's `"event"` field to the matching `PowerplayTracker.apply_*` method. If nothing is found, `pledge_status` is deliberately left `unknown` rather than set to `not_pledged` directly here — the `Location` handler's `confirm_not_pledged_if_unresolved()` (above) remains the single place that conclusion gets drawn, so there's one path to it, not two that could disagree.

If EDMC attaches to an already-running game, this startup sequence may already be behind the "replay window" EDMC exposes to plugins: EDMC does not replay backlog journal events to plugins on its own startup — only genuinely new events are passed to `journal_entry`, plus one synthesized `StartUp` event (with `cmdr`/`state` already reconstructed from the full file) if the game is running, or nothing at all if it isn't. `StartUp` calls `_recover_pledge_state()` too, since no journal replay means no fresh `Powerplay` event is coming either way. If that still finds nothing (e.g. the journal file predates this plugin version, or genuinely has no pledge event because the commander was never pledged), `PowerplayTracker.apply_merits` opportunistically resolves pledge status (and Power) from the first `PowerplayMerits` event seen, since earning PowerPlay merits is only possible while pledged.

## 6. Merit → Activity → CP Pipeline

1. **`PowerplayTracker.apply_merits(entry)`** — reads `MeritsGained` if present; otherwise diffs the event's `TotalMerits` against the last known total (matching how EDMC's own `monitor.py` maintains `state['Powerplay']['Merits']`). Also updates the running `total_merits` baseline.
2. **`PowerplayTracker.apply_delivery_signal(event, entry)`** — called on `SearchAndRescue` (filtered to `Power*`-named commodities only, since the event is shared with Thargoid War/mission salvage hand-ins) and `DeliverPowerMicroResources` (on-foot PowerPlay data, unambiguous by event name alone). Sets a one-shot `_delivery_pending` flag: the journal doesn't link a hand-in to the `PowerplayMerits` event it triggers, so this is a same-tick correlation, not a field on the merits event itself.
3. **`PowerplayTracker.classify_current_activity(current_system)`** — if `_delivery_pending` is set, consumes it and returns `delivery` immediately, bypassing every check below (a hand-in can be turned in at a different system than where the goods were collected, and doesn't require a resolved pledge to have been the source). Otherwise, compares the last-seen system `PowerplayState`/`ControllingPower` against the pledged Power (see README's "How activity is classified" for the exact rule) and returns one of `acquisition` / `reinforcement` / `undermining` / `unknown`. `current_system` is EDMC's own live-tracked system name (the `system` argument `journal_entry` receives — see §3.3), captured at the moment the merits landed; if it doesn't match `system_name` (the system the stored `PowerplayState`/`ControllingPower` context was captured in), that context is stale and classification falls through to `unknown` rather than misattributing to the wrong system. Note: the journal's `Powers` field lists *every* Power active in the system (controller plus any rival actively undermining it), not just the controller — `ControllingPower` is the field that actually says who holds it, and is what this rule is based on rather than assuming `Powers` has exactly one entry.
4. **`SessionManager.record_merits(activity, merits)`** — adds the raw merit count to the current session's per-activity totals. **Raw merits only — no CP is stored.**
5. **Display time** — `formulas.merits_to_cp(merits, ratio)` converts merits to an estimated CP figure using the *current* ratio from Settings (`ui.ratio_for(activity)`), for both the live panel and the Sessions window, including history entries. Changing a ratio in Settings therefore retroactively changes CP estimates for every stored session, not just new merit gains. `delivery` and `unknown` (`formulas.NO_CP_ACTIVITIES`) are excluded from this — see §6.1.

### 6.1 Why `delivery` has no CP ratio

A hand-in's target effect (Acquisition/Reinforcement/Undermining) is chosen in-game and isn't reported in the journal, so there's no correct single ratio to convert it with — same reasoning as `unknown`. `delivery` is tracked by raw merit count for visibility (so it isn't silently folded into `unknown`), not converted to CP.

### 6.2 Per-system tracking

`SessionManager.record_merits(activity, merits, system)` (the `system` argument is the same EDMC-live-tracked current-system name described in §4, threaded through from `journal_entry`) adds to the session's per-activity totals as before (§6 step 4), *and* to a per-system bucket — `session.add_merits` calls `session._system_bucket(session, system)` to get-or-create `session["by_system"][system]`, then increments that bucket's own `totals`/`events` the same way, plus stamps `last_seen_at`. Revisiting a system later in the session keeps adding to the same bucket rather than starting over, since it's looked up by system name each time rather than created fresh per visit — buckets are per-session, same as the top-level totals, so a new session (§7) starts every system back at zero.

`session.system_totals(session, system)` / `system_merit_total(session, system)` read a bucket back (empty dict / zero if the system hasn't been visited); `session.visited_systems(session)` returns every system with a bucket, sorted by `last_seen_at` descending (most-recently-active first). CP for a bucket is computed the same way as the session-wide figure (§6 step 5) — derived at display time from the current ratio settings, never persisted — by both consumers:

- **Main panel's "Here" rows** (`ui._here_lines`, driven by `load._current_system` — see §4) — two dedicated labels (`ui._here_merits_label`, `ui._here_cp_label`), not one line left to wrap on its own: a merit count, then the full three-activity CP breakdown for the current system, zeros included (`ui._full_cp_bits`), unlike the session-wide CP line (`ui._cp_bits`, which omits zero activities to stay short). `load._current_system` is set at the top of every `journal_entry` call from the `system` parameter (not gated on PowerPlay-relevance the way `PowerplayTracker.system_name` is — see §4), so the "Here" rows switch immediately on jumping into a system that's never been PowerPlay-relevant at all, showing zero merits there rather than lagging on the previous system.
- **Sessions window's By System table** (`window._CurrentTab._update_system_tree`) — one row per `visited_systems(session)` entry (merits, summed Est. CP across activities, and a per-activity merit breakdown string), with the current system pinned to the front of the list (even if it has no bucket yet — i.e. zero merits so far) and marked with a `▶` prefix and "(current)" suffix.

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
    "journal_file": "C:\\...\\Journal.2026-08-20T184433.01.log",
    "last_merit_ts": "2026-08-20T19:12:01Z"
  }
}
```

`last_merit_ts` is the journal `"timestamp"` of the last `PowerplayMerits` event actually recorded into `totals` — see "Recovering a missed gap" below.

`SessionStore.load()` accepts the legacy pre-1.2.0 flat-array format too (the whole array is treated as `history`, with no `current` to resume — there's no way to tell in hindsight which entry was still live at last save).

### Session continuity (`SessionManager.sync_session`)

A session is tied to the journal file it started on (`journal_file`, from `monitor.logfile`) *and* the commander it started for (`cmdr`). `sync_session` (called on `LoadGame` and the synthesized `StartUp` — see §4) compares both against `current`:

- **Same file, same (or unset/blank) commander** → the same continuous session: a commander logout to the main menu and back in *as that same commander*, or an EDMC restart while the game keeps running, both reuse the same journal file with no commander change. `current` is kept as-is (no data lost, no history entry created), and `current["cmdr"]` is (re)confirmed.
- **Different file, or same file but a different commander** → the previous session has ended: `current` (if it had any data) is appended to `history`, and a fresh session starts. Elite keeps writing to one journal file across a logout-to-menu-and-back even when a *different* commander is picked at the login screen, so the journal file alone isn't sufficient to detect that case — matching on file only (as EDPPMT originally did) silently carried the previous commander's merit totals over onto the new one. "The game isn't running" is treated as "no active journal file" — `load.py` passes `monitor.logfile` (not `None`) only when `monitor.game_running()` is also true.

Because EDMC does not replay old journal lines to plugins (§5), resuming an existing `current` across an EDMC restart is possible precisely *because* `SessionStore` now persists `current` and `history` as separate fields — the totals already on disk are the totals, not something to be rebuilt from a replay.

`SessionStore.save()` always writes `history` and `current` together, so the file on disk reflects the live session too — a plugin/EDMC crash loses at most whatever wasn't yet flushed (see §8).

### Recovering a missed gap (`load._rescan_journal`, the main panel's "Rescan" button)

Resuming `current` across an EDMC restart (above) only carries forward the totals already recorded — it does nothing for merits earned *during* the restart itself. EDMC does not replay journal backlog to plugins when it (re)attaches to an already-running game (§5): only genuinely new events reach `journal_entry` from the `StartUp` event onward. Anything the old EDMC process didn't get to see live before it died — a PowerPlay merit gain in particular — never arrives any other way and is lost from the session total unless recovered directly from the journal file.

The "Rescan" button (next to "Sessions" on the main panel) does that: `load._rescan_journal()` re-reads `monitor.logfile` from the start (only if it matches `current["journal_file"]` — otherwise there's no session to recover into) and replays every line through the same tracker methods `_dispatch` uses live — `_PLEDGE_EVENT_APPLIERS`, `PowerplayTracker.apply_rank`/`apply_system_context`/`apply_delivery_signal` — to keep pledge/system-context/delivery state accurate for whatever turns out to be new. These are all safe to replay unconditionally: they just overwrite tracker state rather than accumulating, so re-applying an already-seen one changes nothing.

`PowerplayMerits` events are different — `SessionManager.record_merits` accumulates, so replaying an already-counted gain would double it. Each one is only actually recorded if its `"timestamp"` is newer than `current["last_merit_ts"]`, the timestamp of the last merit gain already recorded this session (updated by both the live path, `load._handle_merits`, and the rescan itself) — the same high-water-mark approach used elsewhere in this codebase in preference to more fragile bookkeeping (deliberately *not* `TotalMerits`-based dedup, since `apply_merits` prefers the event's own `MeritsGained` field, which carries no positional information to tell an already-applied event apart from a new one). A genuinely new merit event sharing the exact same whole-second-precision timestamp as the last recorded one is the one edge case this can still miss — under-counting is the safer failure mode to risk here than a double count.

`SessionManager.__init__` seeds `last_merit_ts` to the current wall-clock time if it's missing on load *and* the session already has recorded totals — a session upgraded from a version that predates this field has no reliable way to know how much of the journal file its existing totals already reflect, so Rescan treats "now" as the earliest safe recovery point rather than risk re-importing the whole file's merit history on the first click after an upgrade.

## 8. Persistence Timing

`SessionManager._persist()` (a full JSON rewrite) is called on: `sync_session`/`start_session`, `record_merits`, and `flush()` (called from `plugin_stop` and `prefs_changed`). It is deliberately **not** called from `record_credits`, since that runs on every single journal event — persisting there would mean a disk write per event during normal play. This means a mid-session credit change can be lost if EDMC/the game crashes before the next merit gain or a clean shutdown; merit totals are never at risk this way, since `record_merits` always persists immediately.

## 9. Ratio Settings Storage

Stored as EDMC config string values, one per activity: `edppmt_ratio_acquisition`, `edppmt_ratio_reinforcement`, `edppmt_ratio_undermining` (see `ui.CONFIG_RATIO_PREFIX`). Missing or invalid values fall back to `formulas.DEFAULT_RATIOS`.

## 10. Self-Update (`update.py`)

`UpdateManager.check_async()` is called once, from `plugin_start3`. It's a no-op if either the `edppmt_auto_update` config setting (**opt-in, default off** since v1.8.0 - previously default on since v1.2.0, toggled from the Settings tab) is off, or a `disable-auto-update.txt` file exists directly in `plugin_dir` — a hardcoded escape hatch for a folder being actively hand-edited (e.g. local development), independent of and not visible in Settings.

Otherwise it spawns a daemon thread that:

1. **GETs** `https://api.github.com/repos/rwharpernc/edppmt/releases/latest` (skips draft/prerelease responses) and compares its `tag_name` against `plugin.__version__`, both parsed as plain `(major, minor, patch)` integer tuples — no `semantic_version` dependency, since project versions never carry prerelease/build suffixes. A newer *or equal* remote version is a no-op.
2. If newer, calls `on_downloading(version)` (see below), then **downloads** the first `.zip` release asset to `plugin_dir/updates/`.
3. **Backs up** the current plugin folder to a timestamped zip in `plugin_dir/backups/` (walking `plugin_dir`, excluding `updates/`, `backups/`, `__pycache__/`, and `sessions.json`), then trims backups down to the 3 most recent.
4. **Extracts** the downloaded zip over `plugin_dir`, stripping the top-level `EDPPMT/` folder the release zip is packaged with (see `scripts/package.mjs`) — so files land directly in `plugin_dir`, and `sessions.json` is skipped by name even though it never appears in the zip anyway (it isn't part of the distributed source, same as the repo's own `.gitignore`).
5. Calls `on_ready(version)` (the callback passed to `UpdateManager.__init__`).

Both `on_downloading` and `on_ready` are plain callbacks handed to `UpdateManager.__init__`; `load.py` marshals each onto the Tk main thread via `frame.after(0, ...)` before touching any widget, since `update.py` itself has no Tkinter dependency and runs entirely off the main thread up to this point.

Nothing here reloads running code — Python already has the old modules loaded in memory for this process. The staged files only take effect the *next* time EDMC starts.

### 10.1 Update status UI

**Since v1.8.0, the plugin version lives only in the Settings tab.** `create_prefs` builds a static `ttkHyperlinkLabel.HyperlinkLabel` (`EDPPMT v{__version__}`, linking to `update.RELEASES_PAGE_URL`) once, at creation, and nothing ever touches it again - no color, no text changes, regardless of update state. Previously this label was reactive (see the v1.7.x history in CHANGELOG.md for what that looked like); it's plain now.

The main panel keeps one `ui._version_label` (`ttkHyperlinkLabel.HyperlinkLabel`, created empty and `grid_remove()`d immediately) purely for a one-time "Updated to vX.Y.Z" confirmation. It's driven by the same module-level `ui._version_state` tuple (`kind`, `version`) as before, applied by `ui._apply_version_state()`, but that function now does far less:

| Kind | Main-panel label | Set by |
|------|-------------------|--------|
| `normal` | hidden (`grid_remove()`) | default / after the "updated" message clears |
| `downloading` | hidden - tracked, not shown | `ui.set_update_downloading`, from `UpdateManager`'s `on_downloading` |
| `downloaded` | hidden - tracked, not shown | `ui.set_update_downloaded`, from `on_ready` |
| `updated` | `Updated to vX.Y.Z`, green `#2e7d32`, `grid()`ed back in | `ui.set_update_applied`, from `plugin_start3` (see below) |

`downloading`/`downloaded` still update `_version_state` (so `update.py`'s own `logger.info` calls remain the only record of them) but `_apply_version_state()` deliberately renders nothing for either - this was a design choice to keep the main panel visually quiet, not an oversight.

`update.check_applied_update()` detects the `updated` case: it reads the `edppmt_last_version` config value written on the *previous* run, compares it to `plugin.__version__`, and rewrites it to the current version every run. A mismatch (and a non-empty previous value, so this doesn't fire on a first-ever install) means a staged update just took effect on this restart, and `plugin_start3` calls `ui.set_update_applied(version)` immediately — before `plugin_app` has created any widget, since `_apply_version_state()` is a no-op until `_version_label` exists, and `create_plugin_app` calls it again at the end of widget construction to pick up whatever state is already current.

The `updated` state doesn't stay up indefinitely: `_apply_version_state()` schedules `_clear_updated_state()` via `_version_label.after(_UPDATED_MESSAGE_DURATION_MS, ...)` (15s) the first time it applies an `updated` kind, guarded by `_updated_clear_scheduled` so a second call doesn't schedule a duplicate timer. When it fires, it reverts `_version_state` to `("normal", None)` and re-applies, which `grid_remove()`s the label - so a restart that applies an update only needs *that* restart, not a second one, to see the label disappear again.

### 10.2 Main panel collapse

`ui._collapsed` (persisted as the `edppmt_main_collapsed` config bool) gates visibility of every main-panel row below the title/version/status/mode rows — the separators, system/here-merits/here-CP/session-merits/session-CP/credits/last-event labels, and the "Sessions" button — via `grid()`/`grid_remove()` in `ui._apply_collapsed_state()`. The title label itself (`▾ EDPPMT:` / `▸ EDPPMT:`) doubles as the toggle, bound via `<Button-1>` to `ui._toggle_collapsed`. The version label, the status label (`ui._status_label`, on its own row since v1.9.0 — see §3.1/main-panel layout), and the mode label (`ui._mode_label`, added in v1.10.0) are deliberately *not* in the collapsible set: pledge status and game mode both stay visible at a glance, and a just-applied "Updated to vX" confirmation stays visible regardless of collapse state (even though that label is itself hidden the rest of the time - see 10.1). `_credits_label`'s own data-dependent visibility (hidden until there's a balance to show — see `refresh()`) is layered on top: `refresh()` won't `grid()` it back in while collapsed, and expanding re-applies the cached `_last_credits_earned is None` check rather than unconditionally showing it.

## 11. Known Limitations

- Activity classification is a heuristic (§4/§6), not a value the game reports directly — see `docs/ATTRIBUTIONS.md` for the sourcing and its confidence level, and the README for the classification rule.
- The full set of `PowerplayState` values Frontier currently uses isn't documented (the last official journal manual predates Powerplay 2.0); `powerplay._CONTROLLED_STATES` is a conservative, extensible set rather than an exhaustive one.
- No CAPI integration for PowerPlay data — the merit/pledge/session data reflects the local journal stream only. (`update.py` does make outbound HTTPS requests to GitHub — the one exception to an otherwise fully local plugin — see §10.)

## 12. Auto-Honk (`autohonk.py`)

Fires the ship's Discovery Scanner automatically on system entry by simulating the keyboard key bound to a configurable fire button. Windows only — inert everywhere else (see §3.3). See `docs/ATTRIBUTIONS.md` for prior art this feature draws on.

### 12.1 Keybind resolution

`resolve_key_binding(fire_button)` (`fire_button` is `"Primary"` or `"Secondary"`, chosen in Settings — this is *which fire group's button* the Discovery Scanner is mapped to, not the DSS, which only does anything while already in FSS mode):

1. Finds the active `Custom.<major>.<minor>.binds` file under `%LOCALAPPDATA%\Frontier Developments\Elite Dangerous\Options\Bindings` (`StartPreset.start` names the active preset by base name — near-universally `Custom`; ED bumps the version suffix on schema changes, so the most recently *modified* matching file is used rather than parsing version numbers).
2. Extracts that action's `<Primary>`/`<Secondary>` input slots via a targeted regex (the binds XML is flat and regular enough that a full parser isn't needed).
3. Picks the `Device="Keyboard"` slot, if any, and maps its `Key="..."` token (e.g. `Key_Numpad_Divide`) to a Windows virtual-key code via `KEY_MAP` — deliberately not exhaustive.

Re-resolved fresh on every honk attempt (not cached) — binds can change any time the user edits their control scheme in-game, and this only runs once per jump, so the extra file read is cheap. Possible outcomes: `resolved`, `no-keyboard-binding` (bound to a joystick/HOTAS only), `not-bound`, `unsupported-key` (bound to a keyboard key `KEY_MAP` doesn't cover), `binds-not-found`.

### 12.2 Key injection

`send_key_press(vk, focus_window, hold_ms)` finds the `Elite - Dangerous (CLIENT)` window (`FindWindowW`, matched by both title and class — `FrontierDevelopmentsAppWinClass` — since EDMC's Python is bundled 64-bit and a `None`/empty class argument can misbehave), optionally brings it to the foreground (the `AttachThreadInput` + simulated Alt-tap dance that works around Windows' foreground-lock heuristic silently ignoring `SetForegroundWindow` from a background process), then holds the resolved key down for `hold_ms` via `keybd_event` before releasing it — a tap alone never honks, since the Discovery Scanner charges while the button stays physically depressed. All Win32 calls go through `ctypes` directly (see §3.3's note on why not `pywin32`), with explicit `ctypes.wintypes` `argtypes`/`restype` throughout to avoid HWND truncation on 64-bit Windows. Blocking for the full hold duration, so it must only ever run on a background thread — never the Tk main thread `journal_entry` itself runs on.

### 12.3 Controller (`AutoHonkController`)

One instance, created in `plugin_start3`, held in `load._autohonk`. `handle_event(entry, system)` is called from `_dispatch` for every journal event (see §4) and is itself the filter: no-ops unless `enabled` and the event is `FSDJump`/`CarrierJump`. When it fires, it spawns a daemon thread that re-resolves the keybind and calls `send_key_press` — `journal_entry` itself never blocks. `skip_if_visited_this_session` (default on) tracks jumped-into `SystemAddress` values in a per-controller-instance set so backtracking through familiar space doesn't re-honk; `reset_session()` clears it, called from `load._dispatch`'s `LoadGame` handler exactly when `SessionManager.sync_session` reports a genuinely new session (not a same-journal relog — see §5/§7), since a fresh flight is the natural boundary for "already visited," not an EDMC restart.

### 12.4 Settings & persistence

Stored as individual EDMC config values (`ui._save_autohonk_prefs`/`autohonk.load_config`/`autohonk.save_config`): `edppmt_autohonk_enabled`, `edppmt_autohonk_firebutton`, `edppmt_autohonk_holdms` (milliseconds, stored as a string, entered in the UI as seconds), `edppmt_autohonk_focus`, `edppmt_autohonk_skipvisited`. `load._prefs_changed` calls `AutoHonkController.reload_config()` right after `ui.save_prefs()`, so a toggle takes effect immediately rather than only on EDMC's next restart (unlike the ratio/auto-update settings, which only affect display-time calculations and the next update check respectively, and so don't need a live-reload path).

The Settings tab's "Rescan keybind & running apps" and "Test Honk Now" buttons operate on whatever is currently selected in the dialog — including unsaved changes — independently of the live `AutoHonkController` and its saved config, so a user can verify a keybind or fire a manual test honk before committing to Save. "Rescan" also flags `COMPANION_APPS` (currently just `EDCoPilot.exe`) if running, via `tasklist` (chosen over `psutil` for the same reason as §3.3's ctypes note — no new EDMC-bundled dependency), since EDCoPilot has its own AutoHonk setting that would double-honk if both are enabled.

## 13. Interdiction Warning (`interdiction.py`, `overlay.py`)

Draws a warning on the in-game overlay when an interdiction starts, via a separate, optional community tool — either the original [EDMCOverlay](https://github.com/inorton/EDMCOverlay) or its newer, backwards-compatible replacement [EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay) (same wire protocol; ModernOverlay layers a few opt-in extensions on top — see 13.2) — that EDPPMT does not install, bundle, or launch — see `docs/ATTRIBUTIONS.md`. Off by default. Adapted from an earlier reference implementation of the plugin author's own (an Electron-based interdiction tracker/overlay); the detection state machine is a straight port, the rendering target isn't (EDPPMT has no equivalent transparent overlay window of its own, so it draws through EDMCOverlay's TCP protocol instead).

### 13.1 Detection (`InterdictionTracker`)

Three signals - whichever actually arrives first wins, since `dashboard_entry` (Status.json) and `journal_entry` (`ReceiveText`) are independent EDMC callbacks with no ordering guarantee for the same real-world instant:

1. **`Status.json`'s `Flags` bit 23** (`FlagsBeingInterdicted = 1 << 23`, confirmed against `EDCD/EDMarketConnector`'s `edmc_data.py`) — flips true the instant the interdiction minigame starts, before any resolving journal event, but only reaches this plugin on EDMC's next `dashboard_entry` call (Status.json is written roughly once a second, so up to ~1s of lag from the instant itself). Delivered via `dashboard_entry` (`load.py`) → `InterdictionTracker.handle_dashboard_flags(flags)`.
2. **`ReceiveText`** — NPC chat lines matched against `CHAT_THREAT_PATTERNS` (~35 threat/taunt phrases, ported verbatim from an earlier reference implementation of the author's own, itself originally from another prior project of theirs) are an **independent trigger**, not just identity enrichment for signal 1 — a taunt line can and does arrive before the Flags bit does. `handle_event`'s `ReceiveText` branch sets `active = True` itself (previously it required `self._active` already being `True`, meaning a taunt that beat the flag was silently dropped and the warning didn't appear until the flag caught up, or worst case not until the resolving event — this was the actual cause of a "warning appears very late" report). Symmetrically, `handle_dashboard_flags`'s rising-edge branch now only resets identity fields (`interdictor_name`/`is_player`/etc.) when `not self._active` yet, so a flag arriving *after* a chat-trigger can't wipe the identity the chat line already supplied. Either way, `ReceiveText` remains the only pre-resolution identity source (Status.json's flag carries none).
3. **`Interdicted`** (fields: `Submitted`, `Interdictor`, `IsPlayer`, `IsThargoid`, and `Power` when the interdictor is affiliated with one) / **`EscapeInterdiction`** — the authoritative resolution. `Power` isn't surfaced by the reference implementation's own UI but is directly on the event EDPPMT is already parsing, so it's shown when present — a PowerPlay-specific addition over the ported base.

`InterdictionSnapshot` (`active`, `interdictor_name`, `is_player`, `is_thargoid`, `power`, `resolution`) is emitted via an `on_change` callback (constructor-injected, same style as `UpdateManager`'s `on_ready`/`on_downloading` in `update.py`) rather than a ported EventEmitter. Two `threading.Timer`s stand in for the reference implementation's `setTimeout`s: `RESOLVED_CLEAR_S = 8.0` (how long a resolved outcome stays up before auto-clearing) and `GRACE_CLEAR_S = 3.0` (safety-net clear if Status.json's flag drops with no resolving event ever arriving). Ephemeral by design — no persistence, favoring a "cheap to rebuild" approach for this kind of live-only state.

### 13.2 Rendering (`interdiction.render`, `overlay.OverlayClient`)

`overlay.py` is a generic EDMCOverlay transport (own module, reusable by a future overlay feature): `OverlayClient` holds **one persistent TCP connection** open for its whole lifetime, reconnecting lazily on the next send if it drops. This isn't just an optimization — confirmed against EDMCOverlay's own server source (`OverlayJsonServer.ServerThread`'s `finally` block), a connection's graphics are *deleted* the instant that connection disconnects, independent of their `ttl`. An earlier connect-send-close-per-message design (each `send_*` call opening and immediately closing its own socket) therefore had every graphic removed moments after it arrived regardless of the ttl passed — Landing's multi-shape diagram made this obvious (pieces disappearing before the next piece even sent), but it silently undermined Interdiction Warning's persistence too. Sends are serialized with a lock (`_send`) since `load.py` shares one `OverlayClient` across both features' independent render threads. Raises `OSError` on failure (unreachable, or a reconnect attempt also failed); callers decide whether to swallow it. `load.plugin_stop()` calls `_overlay.close()` on EDMC shutdown.

`overlay.register_modern_overlay_group()` (called once from `load.plugin_start3`) registers this plugin's ids with EDMCModernOverlay's Plugin Group system, via its `overlay_plugin.overlay_api.define_plugin_group()` — a plain `ImportError` (classic EDMCOverlay, or no overlay plugin installed at all) makes this a silent no-op. Per EDMCModernOverlay's own wiki (`Concepts.md`): "Plugin Groups exist to handle everything from automatic scaling of Payloads (**especially vector images**)..." — without this registration, each of Landing's ~17 separate `"vect"` shape ids (shells/spokes/pad marker) was apparently being treated as its own independent unit for Fill-mode scaling, each anchored from its own tiny individual bounding box instead of the diagram's shared one, which is what an "exploded", pieces-flying-apart diagram looks like (reported against EDMCModernOverlay specifically; classic EDMCOverlay has no per-payload grouping/anchor system, so this failure mode doesn't apply there). Two groups are registered - `"Interdiction"` (its card + 3 text ids) and `"Landing"` (its card + text + all diagram shape ids) - so each feature's whole widget scales/anchors as one unit rather than per-payload.

`scripts/test_overlay.py` (`npm run test:overlay`) is a standalone CLI that exercises every Interdiction/Landing `render()` scenario against a real EDMCOverlay/EDMCModernOverlay instance without EDMC running (Elite Dangerous itself still needs to be — both overlay apps track the live game window and draw nothing without one, even though they'll still receive and store whatever's sent either way) — it imports `overlay.py`/`interdiction.py`/`landing.py` directly (stubbing only `config`, the one EDMC-provided module those three touch) rather than reimplementing anything, so it's testing the exact code that ships. The persistent-connection fix above was itself verified this way, plus against a small mock server (not checked in) that replicates `OverlayJsonServer`'s per-connection graphics-ownership and disconnect-cleanup behavior closely enough to confirm a multi-message diagram render actually lands as one atomic-looking update rather than flickering pieces in.

`interdiction.render(snapshot, client)` is the one place that knows what a warning should look like — colors ported precisely from an earlier reference implementation of the author's own, whose own design is explicit that this widget deliberately does *not* follow a switchable overlay-chrome palette ("its red-alert styling is a safety signal, not chrome, and stays fixed regardless of theme"): a `send_shape("rect", ...)` card with a **constant** red-500 border (`#ef4444`) and red-950-at-95%-alpha fill (`#f2450a0a`) — this never changes with resolution state, unlike an earlier version of this module that (incorrectly, compared to that reference) tracked the border color to the resolution — behind three stacked `send_message` calls: the plain-text title "INTERDICTION WARNING" in red-400 (`#f87171`, no `⚠` glyph — EDMCOverlay's bundled EUROCAPS font likely can't render it, which was very possibly why the warning "looked terrible"), "Interdictor: `<name>` (`<origin tag>`)[ — Power: `<power>`]" in a neutral `"white"` (matching the reference's non-alarm near-white for this line — only the title and resolution carry the alert color), and the resolution line in its own semantic color (escaped `#34d399` emerald-400, pulled-out `#fca5a5` red-300, submitted `#fcd34d` amber-300). `_clear()` sends the card and all three text ids back with `ttl=1` when the snapshot goes inactive. The card passes `thickness=2` to `send_shape` — an EDMCModernOverlay-only extension (crisper explicit border width) that's a harmless unknown JSON field on classic EDMCOverlay, confirmed against its C# `Graphic`/`OverlayJsonServer` sources (Newtonsoft.Json ignores unrecognized fields by default).

`load._on_interdiction_change` (the `on_change` callback) is invoked synchronously from whichever EDMC callback triggered the transition (`dashboard_entry` for the flag flip, `journal_entry`/`_dispatch` for a resolving event) — since a `render()` call can involve up to three sequential socket connects, each with its own timeout if EDMCOverlay isn't reachable, the actual render is pushed onto a short-lived daemon thread rather than risking that EDMC callback stalling on it. Gated on `interdiction.load_config().enabled`; failures are logged at debug and otherwise swallowed — an unreachable EDMCOverlay must never break journal/dashboard processing. The Settings "Test Warning" button (`ui._test_interdiction`) calls `render` directly against whatever host/port is currently in the dialog (even unsaved) on its own background thread, and — unlike the live path — surfaces the real success/failure back to the dialog, so the integration can be checked without waiting for a real interdiction.

### 13.3 Settings & persistence

`edppmt_interdiction_enabled` (`interdiction.load_config`/`save_config`) and `edppmt_overlay_host`/`edppmt_overlay_port` (`overlay.load_config`/`save_config`, defaults `127.0.0.1`/`5010`) — same per-module dataclass + `load_config`/`save_config` pattern as `autohonk.py`. `OverlayClient` re-reads config fresh on every send rather than caching it at construction, so a host/port change in Settings takes effect immediately without a `reload_config()` call.

## 14. Landing (`landing.py`, `overlay.py`)

Draws docking status and a pad-layout diagram on the in-game overlay, via the same EDMCOverlay connection as §13 — see `docs/ATTRIBUTIONS.md`. Off by default. Written by this plugin's own author, not the third-party EDMC LandingPad plugin (bgol/LandingPad, GPL-2.0). This module's diagram geometry cites bgol/LandingPad as the original reference for the pad-index numbering table specifically (`_PAD_LIST`/`_PAD_SECTORS`/`_DODECAGON` in `landing.py`) — that table is dictated by the real game's actual station layout (any correct implementation reproduces the same 15 entries; it isn't an author's creative expression), which both bgol/LandingPad's Python and EDPPMT's independent re-implementation necessarily agree on. Everything else — the docking state machine, the status text, the auto-hide timer, and the EDMCOverlay rendering itself — is this project's own original code, written independently of bgol/LandingPad's own source (which `landing.py`'s author had not read until auditing this attribution, at which point the two implementations' overlay wire-level approach for the starport diagram — closed-loop `vect` shells plus 12 separate 2-point spoke lines — turned out to converge, most likely because EDMCOverlay's `vect` primitive only really supports one practical way to draw a disconnected polygon-plus-spokes shape, not because of copying). Don't "clean up" `landing.py`'s geometry constants without re-checking against a known-good reference (bgol/LandingPad, or the real game's own station layout) first.

### 14.1 State (`LandingTracker`)

Purely journal-driven — no Status.json signal needed, unlike Interdiction Warning. `handle_event` is a straight port of an earlier reference implementation's docking reducer cases:

- `DockingRequested` → `docking.status = "pending"`.
- `DockingGranted` → `docking.status = "granted"`, captures the assigned pad (`extract_landing_pad_from_event` — the journal has used several field names for this across game builds: `LandingPad`, `LandingPadNumber`, `PadNumber`, `Pad`, `AssignedLandingPad`, `DockedPad`) and the station/carrier type for diagram classification (`infer_carrier_type_from_dock_event`, `get_pad_diagram_type`).
- `DockingDenied`/`DockingTimeout` → `docking.status = "denied"` with a human-readable reason (`docking_denied_reason_to_text`); the pad is deliberately cleared so a denied attempt never shows a stale "Pad N" from an earlier request.
- `DockingCancelled`, and `FSDJump`/`CarrierJump`/`SupercruiseEntry` (leaving the approach before a request resolves) → resets `docking` to idle and `docked` to `False`.
- `Docked` → clears `docking` back to idle and sets `docked = True`, persisting `last_assigned_pad`/`last_station_type`/`last_carrier_type` (these three deliberately outlive `docking` resetting, so the widget can keep showing the pad after touchdown) and starts the auto-hide timer (below).
- `Undocked` → `docked = False`.

`LandingSnapshot` is emitted via an `on_change` callback (same constructor-injected style as `InterdictionTracker`). A `threading.Timer` (`HIDE_AFTER_LANDING_S = 10.0`) sets `hidden_after_landing` after touchdown — an earlier reference implementation's dashboard "Landing" page keeps showing post-touchdown state indefinitely and its own *overlay widget* auto-hides after 15s; EDPPMT has no equivalent dashboard page (so that auto-hide timer lives directly in `LandingTracker` rather than being split across two consumers) and uses 10s here per the plugin author's own preference for this port.

A second `threading.Timer` (`_HEARTBEAT_INTERVAL_S = 12.0`) re-emits the current snapshot on a repeating basis for as long as a docking request is outstanding (`docking.status` is `"pending"`/`"granted"`/`"denied"`), rescheduling itself after every beat and stopping the moment that status clears (`Docked`, `DockingCancelled`, `Undocked`, or one of the `FSDJump`/`CarrierJump`/`SupercruiseEntry` resets). This exists because `render()` (§14.2) is otherwise purely event-driven — every graphic it sends carries a `ttl`, and with no `DOCKING_EVENTS` firing in between, a docking approach that takes longer than that ttl (easily possible at a large or busy station) would let the overlay expire and vanish mid-approach, well before actually landing, only to reappear once `Docked` finally fired a fresh render. The heartbeat's interval is kept comfortably under `render()`'s `_TTL = 20` (§14.2) so the refresh always lands before expiry, with margin for render latency. Once `Docked` fires, the heartbeat stops and `_schedule_hide` (above) takes over instead — no heartbeat is needed there since `HIDE_AFTER_LANDING_S` (10s) is already well under the ttl.

`build_landing_display_info(docking, docked, last_assigned_pad, last_station_type, last_carrier_type)` is the single derivation ported from an earlier reference implementation's own `buildLandingDisplayInfo` — the same function that reference shares between its dashboard page and overlay widget so their status text and diagram-gating logic can't drift apart. `get_pad_diagram_type` only falls back to `last_station_type` when the *current* docking request has no station type of its own yet, so e.g. landing at an outpost right after a starport dock can't leak that starport's diagram onto the outpost.

### 14.2 Rendering (`landing.render`, `overlay.OverlayClient.send_vector`)

One `send_shape("rect", ...)` card (`_CARD_ID`, plus `thickness=2`) is sized to enclose the whole widget: the status text block above and the pad diagram below it, trimmed to hug that content (`_CARD_W = 320`) rather than the wider box an earlier version used, which left a large empty gap on the card's right side since nothing else in the widget ever reached that far right. The pad diagram is centered exactly on the card's horizontal midline (`_DIAGRAM_CX = _CARD_X + _CARD_W // 2`) since its geometry is fully computed here and can be positioned precisely; the status text itself stays left-aligned at `_TEXT_X` rather than attempting to center it too — EDMCOverlay gives no text-measurement API, so an estimated-character-width guess could put a line visibly off-center instead of just left-aligned (same caveat as `interdiction.render`'s fixed-placement text, §13.2/13.3's `_X`). The one line this doesn't fit cleanly is the no-diagram-for-this-station-type fallback sentence (`_Y_FALLBACK`), which is long enough to run past the card's right edge at any reasonable width — unavoidable without wrapping, and not new to this change. Unlike `interdiction.render`'s card, this one's chrome — border `#80f97316` (orange-500 at 50% alpha) and fill `#d9000000` (black at 85% alpha) — is **constant**, never tracking docking status; only the status/denied-reason text itself is semantically colored (`#f87171` red-400 for "Docking Denied", `#34d399` emerald-400 otherwise). Both the palette and this chrome-vs-semantic split are ported precisely from an earlier reference implementation's own "elite-orange" theme — the title uses that theme's primary text tone (`#fdba74` orange-300), while station/pad/the no-diagram fallback line use its muted tone (`#c2410c` orange-700, the dimmest tier — deliberately not the brighter secondary tone). The pad-diagram's own stroke/active-fill colors (`_STROKE`/`_ACTIVE`, orange-400/amber-400) are unaffected either way — that reference hardcodes those regardless of theme, same as this module always did. Status text (title/status/station/pad/denied-reason) is five `send_message` calls, same pattern as `interdiction.render` — the "Pad N" line specifically is sent unconditionally whenever a pad is known, independent of whether a diagram renders at all (see the next paragraph's outpost/settlement fallback), so the pad number is never *only* conveyed graphically. The pad diagram needed a new `OverlayClient.send_vector` — EDMCOverlay's `"vect"` shape (confirmed against `EDMCOverlay/EDMCOverlay/{Graphic,GraphicType,VectorPoint,OverlayRenderer}.cs`: a `Vector` array of `{x,y,color,marker,text}` points; consecutive points are connected by a line in the graphic's own `color`, and any point with its own `color` set additionally gets a marker (`"cross"`/`"circle"`) and a text label — a single-point array draws just that point's marker/text with no line, which is how the diagram's active-pad indicator is sent standalone). `send_shape`'s existing `"rect"` covers the fleet-carrier grid.

- **Starport** (`_render_starport_diagram`) — 4 nested dodecagon shells (`_DODECAGON`, `_SHELL_SCALE`) as closed-loop `vect` polygons, 12 radial spoke lines (outer shell to inner shell, one `vect` each since a single multi-point `vect` would wrongly chain unrelated spokes together), and one single-point `vect` marking the assigned pad (`_starport_pad_pos` — pads 1-45 wrap mod 15 across 3 shell-offset repeats, ported verbatim from an earlier reference implementation's own pad-position math).
- **Fleet carrier** (`_render_fleetcarrier_diagram`) — 8 Large + 4 Medium + 4 Small pad rects (`_fleetcarrier_pad_rects`, ported verbatim from that same reference), doubled left/right for `SquadronCarrier`. Always sends all `_MAX_FLEETCARRIER_PADS` (32) shape ids every render (filling unused ones with a zero-size cleared rect, parked at the diagram's own center rather than the screen origin — see the note in `_clear_fleetcarrier_diagram` for why) rather than tracking how many were drawn last time, so switching from a 32-pad squadron carrier diagram down to a 16-pad personal carrier can't leave stale rects on screen. Neither diagram family draws the pad number on the graphic itself — the active pad/rect is just highlighted (`_ACTIVE` fill/marker), and `_FLEETCARRIER_LABEL_ID` is always sent blank/cleared — since the "Pad N" status line (below) already says the number once, unconditionally; drawing it a second time on the diagram was redundant and, for the fleet-carrier grid specifically, needed its own digit-count-dependent centering estimate that this removal also eliminates.
- `pad: None` (a denied request whose station type is still known) renders a blank diagram — station-layout context without a false pad claim — by skipping the marker/active-rect send.
- No third diagram family for outposts/planetary ports/settlements — `show_diagram` is `False` there and a fallback text line explains which pad number to look for instead.

**Clearing payloads without moving the widget.** `clear()`, `_clear_fleetcarrier_diagram()`, and the per-render fleet-carrier loop all "hide" a shape/message it no longer wants shown by sending it with zero size (or blank text) and `ttl=1`, rather than by omitting the send — but critically, at a coordinate *inside* the widget's own real footprint (`_DIAGRAM_CX`/`_DIAGRAM_CY` for diagram pieces, `_CARD_X`/`_CARD_Y` for the card), never at literal `(0, 0)`. This was a real bug, confirmed by reading EDMCModernOverlay's own grouping source directly (`overlay_client/payload_transform.py`'s `accumulate_group_bounds`): a registered Plugin Group's Fill-mode bounding box (§13.2's `register_modern_overlay_group`) includes every currently-live payload's raw `x`/`y` unconditionally, even a zero-size rect or blank message — size and content don't exempt a payload from contributing to the group's bounds. Since this widget's card, text, and diagram are all one registered Plugin Group, a "cleared" payload parked at `(0, 0)` was a phantom point at the screen's top-left corner that dragged the group's computed anchor/scale toward it for as long as that payload stayed live (its own `ttl`), then released once it expired and got resent on the next render or heartbeat (§14.1) cycle. With each payload's `ttl` running down on its own schedule, that pull-and-release was constant and out of phase across payloads — which is what made the whole widget visibly drift and jump on EDMCModernOverlay (reported as "the overlay is moving around on screen"). `interdiction.py`'s `_clear()` had the identical bug (its card cleared to `(0, 0)`) and got the identical fix, parked at `_CARD_X`/`_CARD_Y`.

`load._on_landing_change` mirrors `_on_interdiction_change`: invoked synchronously from `_dispatch` on every docking-relevant event, gated on `landing.load_config().enabled`, actual overlay render pushed onto a short-lived daemon thread (a full starport diagram is ~17 separate JSON messages, all sent over the one persistent connection described in §13.2), failures logged at debug and swallowed. The overlay send and the in-app label update (below) are each independently gated on `cfg.overlay_enabled`/`cfg.in_app_enabled` — either medium can be off while the other stays on. When `hidden_after_landing` flips true post-touchdown, the overlay path calls `landing.clear()` instead of `render()`, and the in-app path clears its text to `""` instead of formatting one. The Settings "Test Overlay" button (`ui._test_landing`) calls `render` directly with a synthetic "Docking Approved, Pad 24, starport" `LandingDisplayInfo` against whatever host/port is currently in the dialog, and surfaces success/failure — same pattern as `_test_interdiction`; it only exercises the overlay path, not the in-app label.

**In-app display (`ui.set_landing_info`, `landing.format_in_app_text`).** The same `LandingDisplayInfo` that drives the overlay also drives a one-line label on the main panel, below the quick-toggle buttons row (`ui.py`'s `_landing_info_label`, grid row 14) — `landing.format_in_app_text` condenses status/station/pad/denied-reason onto one line (e.g. `Docking Approved — Jameson Memorial — Pad 24`, or `Docking Denied — Jameson Memorial (All pads occupied)`), and `ui.py` prefixes it with `"Landing: "` and shows it via the same wraplength-tracking `_wrap_label` mechanism every other unbounded-text row on the panel already uses (§ "Using EDPPMT" in the README; a long station name wraps rather than widening the panel — see the EDMC-plugin main-window-sizing rule this whole class of widget has to obey). Since `journal_entry`'s calling thread isn't guaranteed to be Tk's, the in-app update is marshalled onto the main thread via `_ui_frame.after(0, ...)`, same as `_on_update_downloading`/`_on_update_ready` — unlike the overlay send, which is pure socket I/O and doesn't need the Tk thread at all. The label is hidden (`grid_remove`) whenever there's nothing to show — feature disabled, `in_app_enabled` off, or no active docking state — same show/hide pattern as `_credits_label`.

Turning Landing off — the main-panel button (`load._toggle_landing`) or the Settings checkbox (`load.prefs_changed`) — clears both widgets immediately via `load._clear_landing_display()`, rather than leaving the last-rendered state up until the next docking event happens to refresh it. This matters more for the in-app label than the overlay: the overlay's own `ttl` (`_TTL = 20`, §14.2) means a stale overlay graphic expires on its own within seconds either way, but a Tk label has no such self-expiry — without this explicit clear, disabling Landing mid-approach would leave `Landing: Docking Requested — ...` sitting on the main panel indefinitely. `_clear_landing_display` re-reads `landing.load_config()` and independently clears whichever of overlay/in-app is currently *not* both feature-enabled and medium-enabled, so it's also what makes an individual "Show on Overlay"/"Show in EDMC app" checkbox change in Settings take effect right away.

### 14.3 Settings & persistence

`edppmt_landing_enabled` (`landing.load_config`/`save_config`) is the master toggle — the same one the main-panel Landing button flips (§15) — and gates both display mediums at once. `edppmt_landing_overlay_enabled`/`edppmt_landing_in_app_enabled` (both default `True`) let either medium be turned off independently while `edppmt_landing_enabled` stays on; they only take effect while the master toggle is on. Reuses Interdiction Warning's `edppmt_overlay_host`/`edppmt_overlay_port` (`overlay.py`) rather than a second host/port pair — `ui.py` binds the same `_overlay_host_var`/`_overlay_port_var` `tk.StringVar`s into both tabs' entry widgets (created once, whichever tab is built first), so there's exactly one in-memory value regardless of which tab the user edits, and both tabs' save paths write it to the same config keys.

## 15. Main-panel quick toggles (`ui.py`, `load.py`)

Three buttons on the main panel — Auto-Honk, Interdiction, Landing — flip each feature's `enabled` flag without opening Settings. `ui.create_plugin_app` takes three additional `on_toggle_*` callables (`load._toggle_autohonk`/`_toggle_interdiction`/`_toggle_landing`); each reads that module's full config, flips just `.enabled`, writes it back (preserving every other field, e.g. Auto-Honk's fire button/hold duration), and returns the new state so the button can recolor immediately. `_toggle_autohonk` additionally calls `AutoHonkController.reload_config()` — the only one of the three whose live tracker caches its config on the instance rather than reading `load_config()` fresh on every event.

Button coloring (`ui._apply_toggle_button_state`) is explicit background/foreground: green (`#2e7d32`/white) when on, or the plain `tk.Button` default otherwise. That default is captured once from the button's own rendered colors (`_toggle_off_colors`) — deliberately *after* `theme.update(_frame)` runs at the end of `create_plugin_app`, since EDMC's theme engine repaints plain tk widget colors when it walks the frame, which would otherwise immediately overwrite an explicit color set beforehand. A click also pushes the new state into the Settings dialog's own `BooleanVar` if it's currently open (`_interdiction_enabled_var`/etc.), and `load.prefs_changed` calls `ui.sync_toggle_buttons()` right after `ui.save_prefs()` so the reverse direction (Settings checkbox → panel button color) stays in sync too, all within the same running EDMC session.

The three toggle buttons share `buttons_row` with the pre-existing Rares/Sessions/Rescan buttons (one row, not two) — toggles first, then a `"│"` `tk.Label` divider, then the window-opening buttons — rather than a second row below. The divider is a plain `tk.Label`, not `ttk.Separator`, for the same reason `_separator()` (the horizontal dash-rule between panel sections) already avoids `ttk.Separator`: it carries its own ttk styling path that EDMC's `theme.update()` doesn't reconcile with plain-tk widget colors/margins the same way, which in practice rendered the gap on one side of a padx'd `ttk.Separator` visibly smaller than the other — a plain Label's `padx=8` isn't subject to that, and comes out equal both sides (confirmed by measuring `winfo_x()`/`winfo_width()` on both neighbors post-layout). `buttons_row.grid(...)` also carries no `sticky` (previously `sticky=tk.E`), so the whole row centers under the panel instead of hugging the right edge.
