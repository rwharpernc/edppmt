# EDPPMT — Elite Dangerous PowerPlay Merit Tracker

[![Release](https://img.shields.io/github/v/release/rwharpernc/edppmt?sort=semver)](https://github.com/rwharpernc/edppmt/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Author:** R.W. Harper (CMDR Bocheaux)

EDPPMT extends Elite Dangerous Market Connector (EDMC) with a PowerPlay
panel: it tracks the merits you earn live, estimates the Control Points
(CP) and credits they represent, keeps a history of every session, and
adds a handful of optional quality-of-life tools (Rare Goods Finder,
Auto-Honk, Interdiction Warning, Landing). It never touches the game
itself — it only reads *Elite Dangerous*'s own journal files via EDMC,
the same way EDMC does. See [Developer Documentation](#developer-documentation)
below for architecture and internals.

Please report issues on [GitHub](https://github.com/rwharpernc/edppmt/issues).

## Key Features

- **Live merit & CP tracking** — merits and estimated Control Points for
  your current system and for the session as a whole, updating in real
  time. CP is estimated from editable merits-per-CP ratios (Acquisition,
  Reinforcement, Undermining) since Frontier doesn't publish an exact
  conversion.
- **Session history** — every session's totals save automatically (up to
  200 past sessions), so you can compare sessions later, not just watch
  the live one.
- **Rare Goods Finder** — the nearest rare commodities to wherever you
  are, each with its origin system's *current* PowerPlay controller
  looked up live from Spansh.
- **Auto-Honk** *(Windows only, off by default)* — fires your Discovery
  Scanner automatically on every system jump.
- **Interdiction Warning** *(off by default)* — an on-screen heads-up via
  an optional overlay plugin, drawn the instant an interdiction starts.
- **Landing** *(off by default)* — docking status, assigned pad, and a
  pad-layout diagram, shown on the in-game overlay and/or right in the
  EDMC panel.
- **Alt-friendly** — every commander's merits, CP, and sessions are
  tracked separately, and switching commanders in EDMC switches the
  whole panel with them.
- **Collapsible header** and **optional self-update** (off by default) —
  see [Network access disclosure](#network-access-disclosure).

## Requirements

- [Elite Dangerous Market Connector (EDMC)](https://github.com/EDCD/EDMarketConnector),
  installed and running. EDPPMT is a plugin for EDMC, not a standalone
  application — it cannot function without it.
- **Optional:** [EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay)
  (or the older EDMCOverlay) for Interdiction Warning's and Landing's
  in-game overlay graphics. Without it, both features simply have no
  overlay to draw on — the plugin still works.

## Installation

1. Open EDMC and choose `File → Settings → Plugins`, then click *Open
   Plugins Folder* to reveal your plugins directory (usually
   `%LOCALAPPDATA%\EDMarketConnector\plugins` on Windows).
2. Download the latest `EDPPMT-vX.Y.Z.zip` from the
   [Releases page](https://github.com/rwharpernc/edppmt/releases/latest)
   and unzip it. Do **not** download individual files — keep the
   `EDPPMT` folder structure intact.
3. Move the extracted `EDPPMT` folder into the plugins directory,
   removing any older copy first if one exists.
4. Restart EDMC. The plugin's settings tab appears under
   `File → Settings → EDPPMT`, and its panel joins EDMC's main window.

_To update manually, replace the `EDPPMT` folder's contents with the new
release and restart EDMC — or turn on auto-update (see below)._

## First Run & Configuration

- The panel appears in EDMC's main window automatically once the plugin
  is installed — no setup required to start tracking merits.
- Start EDMC before (or with) the game so journal events reach it live.
- Interdiction Warning, Landing, and Auto-Honk are all **off by default**
  — turn them on from the Settings tab (`File → Settings → EDPPMT`) or
  with the quick-toggle buttons on the main panel.
- The Settings tab shows the installed version (a link to the Releases
  page) and lets you edit the CP ratios and clipboard format.
- Click the panel header to collapse it to just the title; the
  collapsed/expanded state persists across restarts.

## Using the Plugin

- **Main panel** shows your pledged Power and rank, current game mode,
  the system you're in and its PowerPlay state, merits/CP for *this
  system* (switches live as you jump), and session-wide totals —
  updated as journal events arrive.
- **Buttons**: quick on/off toggles for Auto-Honk, Interdiction, and
  Landing; **Rares** opens the Rare Goods Finder; **Sessions** opens the
  session-history window; **Rescan** re-reads the current journal file
  directly, recovering any merits missed if EDMC started after the game
  was already running.
- **Sessions window** — a By System and By Activity breakdown for the
  current session, plus a History tab of past sessions and a cumulative
  all-time summary. A session spans one continuous game-client launch
  for one commander; switching to a different commander always starts a
  fresh session.
- **How activity is classified**: EDPPMT infers Acquisition /
  Reinforcement / Undermining from the PowerPlay state of the system you
  earned merits in, relative to your pledged Power — a best-effort
  heuristic (Frontier hasn't documented a merits→activity mapping), so a
  row that looks wrong is worth double-checking against the system state
  shown alongside it.
- **"Credits earned"** is a simple diff of your credit balance from
  session start to now — it covers all income and expenses, not just
  PowerPlay-specific income.

## Support

Questions, ideas, or bugs? Open an issue on
[GitHub](https://github.com/rwharpernc/edppmt/issues).

*EDPPMT is a community project and is not affiliated with Frontier
Developments or the EDMC development team.*

## Network access disclosure

EDPPMT makes network calls only for features you can see are network-backed:

- **Spansh**, to look up a system's current PowerPlay Controlling Power
  for the Rare Goods Finder (live, since control shifts week to week).
- **GitHub**, to check whether a newer release exists (once per EDMC
  start, only if "Automatically download updates" is enabled — off by
  default) and to download the release `.zip` if one is found.
- Interdiction Warning and Landing send to a local overlay endpoint you
  configure (default `127.0.0.1:5010`) — that's your own machine, not a
  remote service.

No telemetry, and no merit/session data is ever sent anywhere. Session
history lives in `sessions.json` inside the plugin folder and is never
touched by an update — only deleting the plugin folder removes it.

## Developer Documentation

Want to modify EDPPMT, run it from source, or submit a pull request?

- [docs/tech-spec.md](docs/tech-spec.md) — architecture, module layout, data formats, the merit/activity/CP pipeline, and the EDMC plugin API surface used.
- [docs/ATTRIBUTIONS.md](docs/ATTRIBUTIONS.md) — sources for journal event fields, merit/CP ratios, and third-party data this plugin relies on.
- [CHANGELOG.md](CHANGELOG.md) — release history.
