# Changelog

All notable changes to EDPPMT are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
