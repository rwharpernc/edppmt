# Changelog

All notable changes to EDPPMT are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.7.3] - 2026-08-23

### Fixed

- **Main panel sat blank until the first journal event.** The system,
  merits, CP, and last-event rows started out as empty strings and only
  picked up real text once a journal event triggered a refresh — right
  after an EDMC restart, that could leave the panel looking broken for a
  while. It now shows placeholder text ("Awaiting system data…", "Merits:
  0", "CP: —", "No merit events yet this session.") until real data
  arrives, and is refreshed with whatever session was persisted from last
  run immediately on startup instead of waiting for the next event.

## [1.7.2] - 2026-08-23

### Added

- **Main panel is now collapsible.** Click the "▾ EDPPMT:" title to collapse
  everything below the status/version row — system, merits, CP, credits, and
  last-event lines — down to a single line, for when you don't need it
  taking up space in EDMC's main window. Click again ("▸ EDPPMT:") to
  expand. The collapsed/expanded state is remembered across restarts. The
  version/update label always stays visible either way, so a pending update
  is never hidden by collapsing the section.

### Changed

- **Clearer update messaging on the main panel.** The version label now
  reads "Restart to Update (vX)" once an update has finished downloading,
  instead of the longer "vX downloaded — restart to apply". After the
  restart that applies it, "Updated to vX" now clears itself back to a
  plain version number after 15 seconds — previously it stuck around for
  the rest of that EDMC session and only cleared after a second, unrelated
  restart.

## [1.7.1] - 2026-08-23

### Fixed

- **Switching commanders mid-client kept the previous commander's merit
  totals.** Elite Dangerous keeps writing to the same journal file across a
  logout-to-menu-and-back even when you pick a *different* commander at the
  login screen. EDPPMT decided whether a `LoadGame` continued the current
  session by journal file alone, so a commander switch (without fully
  restarting the game client) was treated as a continuation and quietly
  relabeled the still-tallying session with the new commander's name. A
  `LoadGame` now only continues the session if both the journal file *and*
  the commander match; a different commander always starts a fresh,
  zeroed-out session.

## [1.7.0] - 2026-08-23

### Added

- **Auto-Honk.** Automatically fires your ship's Discovery Scanner — the
  basic system-wide "honk" that reveals bodies, not the Detailed Surface
  Scanner — every time you jump into a new system. EDPPMT reads your
  active Elite Dangerous keybindings file to find which keyboard key
  your Primary or Secondary fire button is bound to (your choice, in
  Settings), then simulates that key being held down for a configurable
  duration on `FSDJump`/`CarrierJump`. Off by default; turn it on, pick
  your fire button and hold duration, and use "Rescan" / "Test Honk Now"
  in the Settings tab to confirm it resolves your keybind and can reach
  the game window before relying on it. Windows only. If another
  companion app is also running with its own auto-honk feature enabled,
  the Settings tab flags the overlap so you can turn one off and avoid
  double-honking.

### Fixed

- **Main panel could grow wider than EDMC's default window width.** The
  system-context and session-summary lines had no `wraplength`, so a long
  system or Power name could stretch the whole EDMC main window rather
  than wrapping. Both now wrap like the existing last-event line already
  did, and the system line drops the full rival/contested-Powers list
  (the actual unbounded part) since that detail is already shown in full
  in the Sessions window's Current Session tab.

### Changed

- **Auto-Honk Settings block tightened.** Fire button and hold duration
  now share one row, as do the two behavior checkboxes, and the Rescan/
  Test Honk Now buttons sit alongside their result text instead of each
  getting a separate row — same settings, fewer rows to scan.

## [1.6.0] - 2026-08-21

### Fixed

- **Stronghold/Fortified/Exploited systems showing more than one Power, and
  merits misclassified there.** The journal's `Powers` field lists *every*
  Power active in a system — the controlling Power plus any rival actively
  undermining it — not just the controller. EDPPMT was inferring the
  controller by assuming `Powers` had exactly one entry, so a settled
  Stronghold under active undermining showed both names and had its merits
  misclassified as Acquisition instead of Reinforcement. It now reads the
  journal's `ControllingPower` field directly, and the panel shows it as
  e.g. `Stronghold (A. Lavigny-Duval, undermined by Aisling Duval)` instead
  of a flat power list.

### Changed

- **Main panel simplified to current-session data.** The session line now
  shows a per-activity CP breakdown (Acq/Reinf/UM) instead of a single Est.
  CP figure, and the merits/hr and credits/hr rates (already available in
  the Sessions window) were dropped to make room. The "Total CP" figure
  added in 1.5.0 — cumulative CP across the current session plus all saved
  history — is no longer shown on the main panel.
- **Cumulative totals moved to the Sessions window.** The History tab now
  shows an "All sessions" summary (cumulative merits, CP by activity, and
  credits earned) below the session table, replacing the main-panel "Total
  CP" figure with a fuller breakdown in the window that already holds
  session history.

## [1.5.0] - 2026-08-20

### Added

- **Cumulative CP on the main panel.** The main EDMC panel showed estimated
  CP for the current session only. It now also shows a "Total CP" figure —
  the current session's estimate plus every saved history session's —
  so you can see your running total without opening the Sessions window.

## [1.4.0] - 2026-08-20

### Added

- **Visible update status.** The version number shown in the main panel and
  the Settings tab is now a link to the latest GitHub release, and doubles
  as the update-status indicator: it reads "Downloading vX.Y.Z…" while a
  newer build is being fetched, "vX.Y.Z downloaded — restart to apply" once
  it's staged (replacing the old, easy-to-miss one-off notice), and
  "Updated to vX.Y.Z" for one restart after a staged update takes effect —
  something EDPPMT previously gave no confirmation of at all.

## [1.3.1] - 2026-08-20

### Changed

- **Clearer activity-inference note.** The Sessions window's Current Session
  tab explained activity classification as "guessed from the PowerPlay
  state," which didn't actually say how the guess is made. It now spells
  out the rule: uncontrolled system = Acquisition, your Power's system =
  Reinforcement, a rival Power's system = Undermining.

## [1.3.0] - 2026-08-20

### Added

- **Auto-update.** EDPPMT now checks GitHub for a newer release once per
  EDMC launch and, if there is one, downloads and stages it automatically
  — applied on the next EDMC restart, with a main-panel notice once it's
  ready. A backup of the current install (3 most recent kept) is made
  before every update, and `sessions.json` is never touched, since it
  isn't part of the distributed release. Toggle it from the Settings tab,
  or drop a `disable-auto-update.txt` file in the plugin folder to disable
  it outright regardless of that setting (for a folder being actively
  hand-edited).

### Fixed

- **Pledge status stuck on "not pledged" after a menu relog.** Frontier
  only sends the `Powerplay` event on the *first* login of a game client
  launch, not on a logout-to-menu-and-back-in — but EDPPMT was resetting
  its pledge tracking on every `LoadGame`, including relogs, with nothing
  left to reconfirm it. It now only resets on a genuinely new session, not
  a same-journal continuation, so a relog keeps the pledge state it
  already had.
- **Settings tab crash.** Opening Settings threw `AttributeError: module
  'myNotebook' has no attribute 'Entry'` on current EDMC versions, which
  only expose `EntryMenu`. Switched to that.

## [1.2.0] - 2026-08-20

### Added

- **Session continuity across relogs and EDMC restarts.** A session now
  spans one continuous game client launch instead of splitting on every
  `LoadGame` — logging out to the main menu and back in, or closing and
  reopening EDMC while the game keeps running, both continue the same
  session instead of starting a new one. `sessions.json` now persists the
  live session separately from history, so it actually survives an EDMC
  restart instead of being indistinguishable from a completed one.
- **Current system shown in the main panel and Sessions window.** The main
  panel now shows the current system and its PowerPlay state (e.g. `System:
  Nervi — Exploited (Zachary Hudson)`); the Sessions window's raw-state line
  includes the system name too. Activity classification also cross-checks
  the stored PowerplayState/Powers context against EDMC's live-tracked
  system name, so a stale context (moved on since the last qualifying
  event) falls back to Unattributed instead of misattributing to the wrong
  system.
- **Delivery/Donation activity tracking.** PowerPlay commodity hand-ins
  (`SearchAndRescue`, for `Power*`-named commodities) and on-foot data
  hand-ins (`DeliverPowerMicroResources`) at a power contact are now
  recognized and classified as Delivery/Donation instead of being guessed
  from system state or lumped into Unattributed. Tracked by merit count
  only, not converted to CP — the journal doesn't report which of
  Acquisition/Reinforcement/Undermining a given hand-in was aimed at.

### Fixed

- **Crowded Sessions window.** Default/minimum window size increased
  (980×620, up from 760×520), with more padding and wider columns
  throughout both the Current Session and History tabs.

## [1.1.1] - 2026-08-20

### Fixed

- **Crowded Sessions activity table.** The Current Session tab's per-activity
  breakdown now has a bordered frame with proper margin/padding around it
  and taller rows, instead of butting up against the tab edges.

## [1.1.0] - 2026-08-20

### Added

- **Byline.** README and LICENSE now credit R.W. Harper (CMDR Bocheaux) as
  author.
- **Settings tab clarification.** The ratio-editing Settings tab now notes
  that system penalties, ethos bonuses, and Squadron PP bonuses are already
  factored into the merit amount the journal reports, so the merits-per-CP
  ratios shouldn't double-count them.
- **Power rank in the panel and Sessions window.** The main panel status line
  and the Sessions window's Current Session tab now show the commander's
  PowerPlay rank alongside their pledged Power (e.g. `Pledged to Yuri Grom
  (Rank 3)`), sourced from the `Powerplay`/`PowerplayJoin`/`PowerplayDefect`/
  `PowerplayRank` journal events.

## [1.0.0] - 2026-08-20

Initial release.

### Added

- **Live PowerPlay merit tracking.** Reads the journal's `PowerplayMerits`
  event (the commander's actual merit take, already including every bonus
  the game applies — system penalties, ethos buffs, Squadron PP bonus, etc.)
  and tallies it per session, with a `TotalMerits`-diff fallback if
  `MeritsGained` is ever absent from an event.
- **Control Point (CP) estimation per activity.** Classifies each batch of
  merits as Acquisition, Reinforcement, or Undermining by comparing the
  current system's `PowerplayState`/`Powers` (from `FSDJump`/`Location`/
  `Docked`) against the commander's pledged Power, then converts using an
  editable merits-per-CP ratio table (defaults: Acquisition 4.0,
  Reinforcement 2.5, Undermining 4.2 — see Settings to correct these). CP is
  never baked into stored data; it's recalculated from the current ratios
  whenever a session is viewed, so a later ratio correction retroactively
  fixes history too.
- **Pledge detection.** Resolves whether the commander is pledged (and to
  which Power) from the `Powerplay` login event, with the always-fires
  `Location` event as a checkpoint to confirm "not pledged" when no
  `Powerplay` event showed up — surfaced directly in the panel as
  `CMDR <name>: not a PP Pledge`. Falls back to inferring pledge status (and
  Power) from the first `PowerplayMerits` event seen if EDMC attached to the
  game mid-session and missed the startup handshake.
- **Session-scoped money tracking.** Tracks total credit balance change for
  the session (all income and expenses, not just PowerPlay-specific),
  sourced from EDMC's own running `Credits` balance.
- **Session history.** A new session starts on every `LoadGame`; past
  sessions are kept (bounded to the most recent 200) in `sessions.json`
  alongside the installed plugin, so history survives EDMC and game
  restarts.
- **Main EDMC panel**: pledged Power, live merits, estimated CP, and
  merits/hr and credits/hr rates.
- **Sessions window**: a "Current Session" tab with a per-activity
  breakdown (merits, ratio used, estimated CP, CP/hr) plus credits earned
  and rate, and a "History" tab listing every past session.
- **Settings tab**: editable merits-per-CP ratio for each activity.
