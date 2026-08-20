# Changelog

All notable changes to EDPPMT are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
