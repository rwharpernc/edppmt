# EDPPMT Technical Specification

**Version:** 1.7.0
**Author:** R.W. Harper (CMDR Bocheaux)
**Last updated:** 2026-08-23

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
| `plugin_prefs(parent, cmdr, is_beta) -> nb.Frame` | `load.py` | Creates the Settings tab (Auto-Honk block + ratio table + auto-update checkbox). |
| `prefs_changed(cmdr, is_beta) -> None` | `load.py` | Persists ratio, Auto-Honk, and auto-update settings; reloads the live `AutoHonkController`'s config; flushes session state. |
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

`autohonk.py` deliberately does **not** add to this list. EDMC bundles `pywin32`/`psutil` for its own Windows build, but EDMC itself is not Windows-only, and this module needs to stay importable (and gracefully inert) on every platform EDMC runs on. Its Win32 key-injection and window-lookup calls (`FindWindowW`, `keybd_event`, `SetForegroundWindow`, the `AttachThreadInput` foreground-lock workaround) go through the standard-library `ctypes` module directly against `user32.dll`/`kernel32.dll`, guarded behind `sys.platform == "win32"` checks rather than an import-time dependency — see §12.

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
| `FSDJump`, `Docked` | Refresh the current system's name/`PowerplayState`/`Powers`/`ControllingPower` fields, when present (`PowerplayTracker.apply_system_context`). |
| `FSDJump`, `CarrierJump` | Also forwarded to `AutoHonkController.handle_event` — see §12. |
| `SearchAndRescue`, `DeliverPowerMicroResources` | PowerPlay commodity/data hand-ins (`PowerplayTracker.apply_delivery_signal`) — see §6. |
| `PowerplayMerits` | The core event. See §6. |

`_dispatch` forwards *every* event (not just the ones in the table above) to `AutoHonkController.handle_event` first, unconditionally — the controller itself is what filters for `FSDJump`/`CarrierJump` and whether Auto-Honk is enabled, the same way `PowerplayTracker`'s methods are only ever called for the specific events they handle. See §12.

Every dispatch also forwards the `system` argument `journal_entry` receives — EDMC's own live-tracked current system name, not parsed from the entry — so `PowerplayTracker` always knows both which system its stored context describes and which system the commander is actually in right now (see §6).

Every call to `journal_entry` also updates `SessionManager`'s live credit tracking from `state['Credits']`, regardless of event type, so the credits/hr rate stays current between merit-earning events.

## 5. Pledge Detection

There is no journal event for "you are NOT pledged" — only `Powerplay`, which fires at startup *if* pledged. EDPPMT resolves the negative case by using `Location` (always written at startup) as a checkpoint: if pledge status is still unresolved when `Location` arrives, it's set to `not_pledged`. In practice `Location` and `Powerplay` can arrive in either order — both have been observed with the same timestamp, `Location` first — so this is a same-batch race, not a strict ordering guarantee: if `Location` is processed first, pledge status is transiently (and incorrectly) resolved to `not_pledged`, then immediately corrected once `Powerplay`'s own handler runs, since `apply_login_snapshot` unconditionally overwrites it.

That correction depends on `Powerplay` actually arriving, though — and it only arrives on the *first* login of a client launch. A logout to the main menu and back in sends a fresh `LoadGame`, but Frontier does **not** re-send `Powerplay` on it, since the pledge itself hasn't changed. Resetting pledge tracking on every `LoadGame` (as EDPPMT originally did) therefore threw the correct pledge away on every relog, with nothing left to reconfirm it — permanently showing "not pledged" for the rest of the session once the relog's own `Location` event resolved it. Fixed by only calling `apply_login_reset` when `SessionManager.sync_session` reports a new session (§7) rather than a same-journal continuation — a relog keeps whatever pledge state is already tracked.

If EDMC attaches to an already-running game, this startup sequence may already be behind the "replay window" EDMC exposes to plugins: EDMC does not replay backlog journal events to plugins on its own startup — only genuinely new events are passed to `journal_entry`, plus one synthesized `StartUp` event (with `cmdr`/`state` already reconstructed from the full file) if the game is running, or nothing at all if it isn't. To cover this, `PowerplayTracker.apply_merits` also opportunistically resolves pledge status (and Power) from the first `PowerplayMerits` event seen, since earning PowerPlay merits is only possible while pledged.

## 6. Merit → Activity → CP Pipeline

1. **`PowerplayTracker.apply_merits(entry)`** — reads `MeritsGained` if present; otherwise diffs the event's `TotalMerits` against the last known total (matching how EDMC's own `monitor.py` maintains `state['Powerplay']['Merits']`). Also updates the running `total_merits` baseline.
2. **`PowerplayTracker.apply_delivery_signal(event, entry)`** — called on `SearchAndRescue` (filtered to `Power*`-named commodities only, since the event is shared with Thargoid War/mission salvage hand-ins) and `DeliverPowerMicroResources` (on-foot PowerPlay data, unambiguous by event name alone). Sets a one-shot `_delivery_pending` flag: the journal doesn't link a hand-in to the `PowerplayMerits` event it triggers, so this is a same-tick correlation, not a field on the merits event itself.
3. **`PowerplayTracker.classify_current_activity(current_system)`** — if `_delivery_pending` is set, consumes it and returns `delivery` immediately, bypassing every check below (a hand-in can be turned in at a different system than where the goods were collected, and doesn't require a resolved pledge to have been the source). Otherwise, compares the last-seen system `PowerplayState`/`ControllingPower` against the pledged Power (see README's "How activity is classified" for the exact rule) and returns one of `acquisition` / `reinforcement` / `undermining` / `unknown`. `current_system` is EDMC's own live-tracked system name (the `system` argument `journal_entry` receives — see §3.3), captured at the moment the merits landed; if it doesn't match `system_name` (the system the stored `PowerplayState`/`ControllingPower` context was captured in), that context is stale and classification falls through to `unknown` rather than misattributing to the wrong system. Note: the journal's `Powers` field lists *every* Power active in the system (controller plus any rival actively undermining it), not just the controller — `ControllingPower` is the field that actually says who holds it, and is what this rule is based on rather than assuming `Powers` has exactly one entry.
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

A session is tied to the journal file it started on (`journal_file`, from `monitor.logfile`) *and* the commander it started for (`cmdr`). `sync_session` (called on `LoadGame` and the synthesized `StartUp` — see §4) compares both against `current`:

- **Same file, same (or unset/blank) commander** → the same continuous session: a commander logout to the main menu and back in *as that same commander*, or an EDMC restart while the game keeps running, both reuse the same journal file with no commander change. `current` is kept as-is (no data lost, no history entry created), and `current["cmdr"]` is (re)confirmed.
- **Different file, or same file but a different commander** → the previous session has ended: `current` (if it had any data) is appended to `history`, and a fresh session starts. Elite keeps writing to one journal file across a logout-to-menu-and-back even when a *different* commander is picked at the login screen, so the journal file alone isn't sufficient to detect that case — matching on file only (as EDPPMT originally did) silently carried the previous commander's merit totals over onto the new one. "The game isn't running" is treated as "no active journal file" — `load.py` passes `monitor.logfile` (not `None`) only when `monitor.game_running()` is also true.

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
2. If newer, calls `on_downloading(version)` (see below), then **downloads** the first `.zip` release asset to `plugin_dir/updates/`.
3. **Backs up** the current plugin folder to a timestamped zip in `plugin_dir/backups/` (walking `plugin_dir`, excluding `updates/`, `backups/`, `__pycache__/`, and `sessions.json`), then trims backups down to the 3 most recent.
4. **Extracts** the downloaded zip over `plugin_dir`, stripping the top-level `EDPPMT/` folder the release zip is packaged with (see `scripts/package.mjs`) — so files land directly in `plugin_dir`, and `sessions.json` is skipped by name even though it never appears in the zip anyway (it isn't part of the distributed source, same as the repo's own `.gitignore`).
5. Calls `on_ready(version)` (the callback passed to `UpdateManager.__init__`).

Both `on_downloading` and `on_ready` are plain callbacks handed to `UpdateManager.__init__`; `load.py` marshals each onto the Tk main thread via `frame.after(0, ...)` before touching any widget, since `update.py` itself has no Tkinter dependency and runs entirely off the main thread up to this point.

Nothing here reloads running code — Python already has the old modules loaded in memory for this process. The staged files only take effect the *next* time EDMC starts.

### 10.1 Update status UI

The main panel and Settings tab each show a `ttkHyperlinkLabel.HyperlinkLabel` (`ui._version_label` / `ui._prefs_version_label`) linking to `update.RELEASES_PAGE_URL` (`https://github.com/rwharpernc/edppmt/releases/latest`). Both labels are driven from one module-level `ui._version_state` tuple (`kind`, `version`), applied by `ui._apply_version_state()`, so the two stay in sync:

| Kind | Text (main panel) | Color | Set by |
|------|--------------------|-------|--------|
| `normal` | `vX.Y.Z` | blue `#1e88c7` | default at widget creation |
| `downloading` | `Downloading vX.Y.Z…` | orange `#c07000` | `ui.set_update_downloading`, from `UpdateManager`'s `on_downloading` |
| `downloaded` | `Restart to Update (vX.Y.Z)` | red `#d9534f` | `ui.set_update_downloaded`, from `on_ready` |
| `updated` | `Updated to vX.Y.Z` | green `#2e7d32` | `ui.set_update_applied`, from `plugin_start3` (see below) |

The Settings-tab label prefixes its text with `EDPPMT ` since it has no adjacent title to give that context; the main-panel label doesn't.

`update.check_applied_update()` detects the `updated` case: it reads the `edppmt_last_version` config value written on the *previous* run, compares it to `plugin.__version__`, and rewrites it to the current version every run. A mismatch (and a non-empty previous value, so this doesn't fire on a first-ever install) means a staged update just took effect on this restart, and `plugin_start3` calls `ui.set_update_applied(version)` immediately — before `plugin_app` has created any widget, since `_apply_version_state()` is a no-op until the label exists, and `create_plugin_app`/`create_prefs` each call it again at the end of widget construction to pick up whatever state is already current.

The `updated` state doesn't stay up indefinitely: `_apply_version_state()` schedules `_clear_updated_state()` via `_version_label.after(_UPDATED_MESSAGE_DURATION_MS, ...)` (15s) the first time it applies an `updated` kind, guarded by `_updated_clear_scheduled` so a second call (e.g. from `create_prefs` re-applying the same already-current state) doesn't schedule a duplicate timer. When it fires, it reverts `_version_state` to `("normal", None)` and re-applies — so a restart that applies an update only needs *that* restart, not a second one, to see the label settle back to a plain version number.

### 10.2 Main panel collapse

`ui._collapsed` (persisted as the `edppmt_main_collapsed` config bool) gates visibility of every main-panel row below the title/status/version row — the separators, system/merits/CP/credits/last-event labels, and the "Sessions" button — via `grid()`/`grid_remove()` in `ui._apply_collapsed_state()`. The title label itself (`▾ EDPPMT:` / `▸ EDPPMT:`) doubles as the toggle, bound via `<Button-1>` to `ui._toggle_collapsed`. The version/update label is deliberately *not* in the collapsible set, so an update-pending message stays visible regardless of collapse state. `_credits_label`'s own data-dependent visibility (hidden until there's a balance to show — see `refresh()`) is layered on top: `refresh()` won't `grid()` it back in while collapsed, and expanding re-applies the cached `_last_credits_earned is None` check rather than unconditionally showing it.

## 11. Known Limitations

- Activity classification is a heuristic (§4/§6), not a value the game reports directly — see `docs/ATTRIBUTIONS.md` for the sourcing and its confidence level, and the README for the classification rule.
- The full set of `PowerplayState` values Frontier currently uses isn't documented (the last official journal manual predates Powerplay 2.0); `powerplay._CONTROLLED_STATES` is a conservative, extensible set rather than an exhaustive one.
- No CAPI integration for PowerPlay data — the merit/pledge/session data reflects the local journal stream only. (`update.py` does make outbound HTTPS requests to GitHub — the one exception to an otherwise fully local plugin — see §10.)

## 12. Auto-Honk (`autohonk.py`)

Ported from a sibling project (EDDDT, an Electron/TypeScript app — `src/main/auto-honk/`, `src/main/input/`, `src/main/journal/binds.ts`) and modeled on EDCoPilot's own AutoHonk feature: fires the ship's Discovery Scanner automatically on system entry by simulating the keyboard key bound to a configurable fire button. Windows only — inert everywhere else (see §3.3).

### 12.1 Keybind resolution

`resolve_key_binding(fire_button)` (`fire_button` is `"Primary"` or `"Secondary"`, chosen in Settings — this is *which fire group's button* the Discovery Scanner is mapped to, mirroring EDCoPilot's own "HonkFiregroup" setting, not the DSS, which only does anything while already in FSS mode):

1. Finds the active `Custom.<major>.<minor>.binds` file under `%LOCALAPPDATA%\Frontier Developments\Elite Dangerous\Options\Bindings` (`StartPreset.start` names the active preset by base name — near-universally `Custom`; ED bumps the version suffix on schema changes, so the most recently *modified* matching file is used rather than parsing version numbers).
2. Extracts that action's `<Primary>`/`<Secondary>` input slots via a targeted regex (the binds XML is flat and regular enough that a full parser isn't needed).
3. Picks the `Device="Keyboard"` slot, if any, and maps its `Key="..."` token (e.g. `Key_Numpad_Divide`) to a Windows virtual-key code via `KEY_MAP` — ported 1:1 from EDDDT's `keymap.ts`, deliberately not exhaustive.

Re-resolved fresh on every honk attempt (not cached) — binds can change any time the user edits their control scheme in-game, and this only runs once per jump, so the extra file read is cheap. Possible outcomes: `resolved`, `no-keyboard-binding` (bound to a joystick/HOTAS only), `not-bound`, `unsupported-key` (bound to a keyboard key `KEY_MAP` doesn't cover), `binds-not-found`.

### 12.2 Key injection

`send_key_press(vk, focus_window, hold_ms)` finds the `Elite - Dangerous (CLIENT)` window (`FindWindowW`, matched by both title and class — `FrontierDevelopmentsAppWinClass` — since EDMC's Python is bundled 64-bit and a `None`/empty class argument can misbehave), optionally brings it to the foreground (the `AttachThreadInput` + simulated Alt-tap dance that works around Windows' foreground-lock heuristic silently ignoring `SetForegroundWindow` from a background process), then holds the resolved key down for `hold_ms` via `keybd_event` before releasing it — a tap alone never honks, since the Discovery Scanner charges while the button stays physically depressed. All Win32 calls go through `ctypes` directly (see §3.3's note on why not `pywin32`), with explicit `ctypes.wintypes` `argtypes`/`restype` throughout to avoid HWND truncation on 64-bit Windows. Blocking for the full hold duration, so it must only ever run on a background thread — never the Tk main thread `journal_entry` itself runs on.

### 12.3 Controller (`AutoHonkController`)

One instance, created in `plugin_start3`, held in `load._autohonk`. `handle_event(entry, system)` is called from `_dispatch` for every journal event (see §4) and is itself the filter: no-ops unless `enabled` and the event is `FSDJump`/`CarrierJump`. When it fires, it spawns a daemon thread that re-resolves the keybind and calls `send_key_press` — `journal_entry` itself never blocks. `skip_if_visited_this_session` (default on) tracks jumped-into `SystemAddress` values in a per-controller-instance set so backtracking through familiar space doesn't re-honk; `reset_session()` clears it, called from `load._dispatch`'s `LoadGame` handler exactly when `SessionManager.sync_session` reports a genuinely new session (not a same-journal relog — see §5/§7), since a fresh flight is the natural boundary for "already visited," not an EDMC restart.

### 12.4 Settings & persistence

Stored as individual EDMC config values (`ui._save_autohonk_prefs`/`autohonk.load_config`/`autohonk.save_config`): `edppmt_autohonk_enabled`, `edppmt_autohonk_firebutton`, `edppmt_autohonk_holdms` (milliseconds, stored as a string, entered in the UI as seconds), `edppmt_autohonk_focus`, `edppmt_autohonk_skipvisited`. `load._prefs_changed` calls `AutoHonkController.reload_config()` right after `ui.save_prefs()`, so a toggle takes effect immediately rather than only on EDMC's next restart (unlike the ratio/auto-update settings, which only affect display-time calculations and the next update check respectively, and so don't need a live-reload path).

The Settings tab's "Rescan keybind & running apps" and "Test Honk Now" buttons operate on whatever is currently selected in the dialog — including unsaved changes — independently of the live `AutoHonkController` and its saved config, so a user can verify a keybind or fire a manual test honk before committing to Save. "Rescan" also flags `COMPANION_APPS` (currently just `EDCoPilot.exe`) if running, via `tasklist` (chosen over `psutil` for the same reason as §3.3's ctypes note — no new EDMC-bundled dependency), since EDCoPilot has its own AutoHonk setting that would double-honk if both are enabled.
