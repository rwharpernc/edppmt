# EDPPMT

**Elite Dangerous PowerPlay Merit Tracker**

A lightweight [Elite Dangerous Market Connector](https://github.com/EDCD/EDMarketConnector) (EDMC) plugin for *Elite Dangerous*. EDPPMT tracks how many PowerPlay merits you earn as you play, estimates how many Control Points (CP) that represents for Acquisition, Reinforcement, and Undermining activity, and tracks credit income alongside it — live, per session, with session history kept across game and EDMC restarts.

**Author:** R.W. Harper (CMDR Bocheaux)
**Version:** 1.9.0
**License:** [MIT](LICENSE)

---

## Table of Contents

- [Install](#install)
- [Updates](#updates)
- [What it shows](#what-it-shows)
- [Why](#why)
- [How it works](#how-it-works)
- [Auto-Honk](#auto-honk)
- [How activity is classified](#how-activity-is-classified)
- [Ratios](#ratios)
- [Pledge detection](#pledge-detection)
- [Sessions](#sessions)
- [Money](#money)
- [For Developers](#for-developers)
- [Documentation](#documentation)

## Install

You don't need Node.js, Python, or any of this repo's source tree — just a release zip.

1. Download the latest `EDPPMT-vX.Y.Z.zip` from the [Releases page](https://github.com/rwharpernc/edppmt/releases/latest).
2. Extract it, then copy the `EDPPMT` folder it contains into your EDMC plugins folder: `%LOCALAPPDATA%\EDMarketConnector\plugins\EDPPMT`.
3. Restart EDMC.

After that first install, you can turn on auto-update from the Settings tab if you'd rather not track new releases yourself — see Updates below.

## Updates

**Off by default — this is opt-in, not opt-out.** Turn on "Automatically download updates" in the Settings tab if you want it: EDPPMT then checks GitHub for a newer release once per EDMC launch and, if there is one, downloads and stages it automatically — it takes effect the next time you restart EDMC. Nothing is sent in that check beyond the request itself (no telemetry, no session data). Your session history is never touched by any of this either way: it lives in `sessions.json` inside the plugin folder, which isn't part of the distributed release, so an update can't overwrite it (see Sessions below for what *does* remove it — deleting the whole plugin folder rather than updating it in place).

The plugin version lives only in the Settings tab (a static link to the [latest release on GitHub](https://github.com/rwharpernc/edppmt/releases/latest)) — the main panel stays silent about it except for one thing: right after a staged update takes effect, it briefly shows "Updated to vX.Y.Z" in the corner for about 15 seconds, then goes back to showing nothing there.

A backup of your current install is kept (the 3 most recent, in `backups/` inside the plugin folder) before each update is applied, in case anything goes wrong.

If you turn it on for a copy you're actively hand-editing (developing, not just running it), drop an empty `disable-auto-update.txt` file directly in the plugin folder — that disables auto-update for that install regardless of the Settings checkbox, so a background check can't clobber in-progress work.

## What it shows

- **Main EDMC panel** — pledged Power and rank on its own line (e.g. `Pledged to Yuri Grom (Rank 3)`), the current system and its PowerPlay state (e.g. `System: Nervi — Exploited (Zachary Hudson)`), two **"Here"** lines — a merit count, then the full CP breakdown (Acquisition/Reinforcement/Undermining, all three shown even at zero) — for *just the system you're in right now* — it switches the instant you jump, and keeps an accurate running total per system if you backtrack to somewhere you've already worked this session — and, below that, the session-wide merits/CP totals and credits earned, updated as journal events arrive. If your commander isn't pledged, it says so directly: `CMDR <name>: not a PP Pledge`. Click the "▾ EDPPMT:" title to collapse everything below the pledge-status row down to one line — handy when you don't need it taking up space — and click again ("▸ EDPPMT:") to expand; the collapsed/expanded state is remembered across restarts. The title/pledge-status rows stay visible either way, and are otherwise silent about the plugin version (see Updates above for where that lives) except right after an auto-update takes effect, when it briefly shows "Updated to vX.Y.Z" next to the title. Rows that don't have real data yet show placeholder text ("Awaiting system data…", "Here: awaiting system data…", "Session merits: 0", etc.) rather than sitting blank, and the panel is refreshed with whatever session was already saved from your last run immediately on EDMC startup. Two buttons sit at the bottom: **Sessions** (below) and **Rares** (see Rare Goods Finder below).
- **Sessions window** (click "Sessions" in the panel):
  - **Current Session** tab — a **By System** table (every system visited this session: merits, estimated CP, and a per-activity breakdown, current system pinned to the top and marked); a **By Activity** table with the session-wide breakdown (Acquisition / Reinforcement / Undermining / Delivery-Donation / Unattributed): merits, the ratio used, estimated CP, and CP/hr; the current PowerPlay context (system, state, controller, rival Powers — for sanity-checking a row that looks wrong); and credits earned this session plus the rate.
  - **History** tab — every past session (bounded to the most recent 200), so you can compare sessions later, not just watch the live one; plus an "All sessions" summary (cumulative merits, CP by activity, and credits earned across the current session and all saved history).
  - Buttons along the bottom: **Refresh** and **Close**, plus **Reset Session** (zeroes this session's merit totals — by system and by activity — without ending the session or touching credit tracking; mainly useful for correcting a bad count, such as the well-known donation-mission duplicate-merit journal bug), **Reset Current System** (zeroes just the current system's contribution, subtracted back out of the session totals too), and **Copy Progress** (copies one formatted line per row in the By System table to the clipboard — format is configurable in Settings, see below). Both resets ask for confirmation first and can't be undone.
- **Rare Goods Finder** (click "Rares" in the panel) — the nearest rare commodities to your current system, sorted by distance (nearest first, though distance itself isn't shown): rare good, origin system, station, pad size, and the origin system's current PowerPlay Controlling Power. "Show nearest" controls how many to list. Double-click a row to open that rare good's page on Inara. Shows "Awaiting system data…" until EDPPMT has seen a `FSDJump`/`Location` event this run. The rare-good data itself (origin, station, pad, legality, PowerPlay eligibility, galactic coordinates — 141 entries) is bundled with the plugin and never makes a network call, since none of it changes; Controlling Power is the one column looked up live (from [Spansh](https://www.spansh.co.uk/)) since PowerPlay control shifts week to week — it shows "…" while loading and "—" if the system is unclaimed or the lookup fails (e.g. no internet). See [`docs/ATTRIBUTIONS.md`](docs/ATTRIBUTIONS.md) for where the dataset and lookup come from.
- **Interdiction Warning** (Settings → Alerts, off by default) — draws a warning on your in-game overlay the instant an interdiction starts (`Status.json`'s "Being Interdicted" flag, before it resolves), then updates it with who's interdicting (from NPC chat taunts, or the resolving journal event — including their affiliated Power, when there is one) and the outcome (escaped / pulled from supercruise / submitted), auto-clearing a few seconds later. This draws through [EDMCOverlay](https://github.com/inorton/EDMCOverlay), a separate, optional community tool EDPPMT does not install, bundle, or launch itself — it just sends to whatever's listening on the host/port configured in Settings (default `127.0.0.1:5010`) if the feature is enabled, and silently does nothing if that's not reachable. A "Test Warning" button simulates a full interdiction lifecycle and reports whether the send actually succeeded, so you can check your EDMCOverlay setup without waiting for a real one.
- **Settings tab** — the installed version (a static link to the Releases page) at the top, then three sub-tabs, grouped by purpose:
  - **Tracking** — **CP Ratios** (the merits-per-CP ratio for each activity, editable in case Frontier tunes Powerplay balance or a default turns out to be off) and **Clipboard** (the line format "Copy Progress" in the Sessions window uses, with placeholders for the system name/Inara URL/merits/CP/PowerPlay state, and a "Reset to default" button).
  - **Alerts** — **Auto-Honk** (a quick-setup note plus the configuration below) and **Interdiction Warning** (the EDMCOverlay connection settings and "Test Warning" button described above).
  - **Updates** — the auto-update checkbox (off by default).

## Why

The journal's `PowerplayMerits` event reports your actual merit take, already including every bonus the game applies — system strength/frontline penalties, ethos buffs, your Squadron's PP bonus, all of it. What it does *not* say is how many Control Points that's worth for the system, because that depends on which activity earned it, and Frontier has never documented the conversion in the journal (the last official journal manual predates Powerplay 2.0 entirely).

EDPPMT infers the activity from the PowerPlay state of the system you're in when the merits land, and converts to an estimated CP figure using an editable ratio table — so you can watch your CP contribution and credit income build in real time instead of doing the math yourself after the fact.

## How it works

EDPPMT never touches the game. It's a passive listener sitting behind EDMC:

```
Elite Dangerous  →  writes journal files  →  EDMC tails them  →  EDPPMT reacts
```

It reads `PowerplayMerits` for the merit amount, `Powerplay`/`PowerplayJoin`/`PowerplayDefect`/`PowerplayLeave` for which Power you're pledged to, and `FSDJump`/`Location`/`Docked` for the PowerPlay state of the system you're currently in — combining the last two to decide whether a batch of merits was Acquisition, Reinforcement, or Undermining. EDMC's own running credit balance (built from dozens of journal event types) is diffed against the session start to report money earned.

## Auto-Honk

Automatically fires your ship's Discovery Scanner — the basic system-wide "honk" that reveals bodies, not the Detailed Surface Scanner (that one only does anything while already in FSS mode) — every time you jump into a new system. Off by default, Windows only.

Turn it on from the Settings tab, choose which fire button (Primary/Secondary) the Discovery Scanner is bound to in your firegroup, and set a hold duration — the scanner charges up while the button stays held down and only fires once fully charged, so this needs to be long enough to cover your ship's actual charge time. EDPPMT reads your active Elite Dangerous keybindings file to find which physical keyboard key that fire button maps to; if it's only bound to a joystick/HOTAS button, or isn't bound at all, the Settings tab says so rather than guessing. Use "Rescan keybind & running apps" after rebinding in-game, and "Test Honk Now" to fire immediately and confirm it can reach the game window — both work independently of whether Auto-Honk itself is enabled or already saved.

If EDCoPilot is also running with its own AutoHonk setting on, the Settings tab flags it — turn one off to avoid double-honking, since both fire the same physical key for the same purpose. "Skip systems already visited this session" (on by default) avoids re-honking a system you've already jumped into since your last login, so backtracking through familiar space doesn't repeatedly fire it.

## How activity is classified

There's no journal field that says "these merits were Acquisition." EDPPMT infers it from the current system's `PowerplayState` and `ControllingPower` fields (reported on `FSDJump` / `Location` / `Docked` whenever the system is PowerPlay-relevant) relative to your pledged Power:

- Nobody holds the system yet → **Acquisition**
- You hold it → **Reinforcement**
- A rival holds it → **Undermining**
- Can't tell (not currently pledged, or no system context seen yet this session) → **Unattributed**

Note: the journal's `Powers` field lists *every* Power active in the system — the controller plus any rival actively undermining it — so a settled Stronghold/Fortified/Exploited system can still show more than one name there. `ControllingPower` is the field that actually says who holds it, and is what the above rule is based on.

EDPPMT also cross-checks this against EDMC's own live-tracked system name at the moment merits actually land. If you've moved on to a different system since the last `PowerplayState`/`Powers` context was captured — say, a `Docked` event that doesn't repeat those fields — that context is stale, and the merits are marked **Unattributed** instead of being misattributed to the wrong system.

**Delivery/Donation** is the one exception to all of the above: handing in PowerPlay commodities (`SearchAndRescue`, for the `Power*`-named commodities — agricultural samples, computer parts, and the rest) or PowerPlay data on foot (`DeliverPowerMicroResources`) at a power contact earns merits too, and EDPPMT catches the `PowerplayMerits` event that immediately follows one of those and tags it **Delivery/Donation** directly, skipping the system-state guess entirely. Since the journal doesn't say which of Acquisition/Reinforcement/Undermining a given hand-in was aimed at (that's chosen in-game), Delivery/Donation is tracked by merit count only, the same as Unattributed — see Ratios below.

This is a best-effort heuristic, not something the game states directly. If a row in the Current Session tab looks wrong, that's useful signal — the system name and raw `PowerplayState` your commander last saw are shown right there so you can compare them against what you'd expect.

## Ratios

| Activity | Default (merits per 1 CP) |
|---|---|
| Acquisition | 4.0 |
| Reinforcement | 2.5 |
| Undermining | 4.2 |
| Delivery/Donation | *(none — merits only, see above)* |

These are community-sourced for Powerplay 2.0 (Undermining is the least certain of the three). Per-Power ethos bonuses are **not** a separate factor here — they affect merit *generation*, which is already reflected in `MeritsGained` by the time the journal reports it, the same as the Squadron PP bonus. CP is never baked into stored session data; it's recalculated from the current ratio settings whenever you view a session, so correcting a ratio in Settings retroactively fixes CP estimates for history too.

## Pledge detection

Pledge status is normally resolved right at login: the `Powerplay` event only fires if pledged, and its absence by the time the always-present `Location` event fires means not pledged. Frontier only writes that `Powerplay` event once per client launch, though — not on a logout-to-menu-and-back — so if EDMC (or EDPPMT itself) had restarted in between, there's no fresh live event to tell it the pledge status again. EDPPMT falls back to reading the current journal file directly in that case, scanning backward for the most recent pledge-lifecycle event (`Powerplay`/`PowerplayJoin`/`PowerplayLeave`/`PowerplayDefect` — whichever happened last, so a commander who pledged and later left isn't recovered as still pledged) — the same way Auto-Honk reads the keybindings file directly rather than waiting on the game. If you start EDMC *after* the game is already running and there's nothing recoverable that way either, EDPPMT falls back further to resolving pledge status (and which Power) from the first `PowerplayMerits` event it sees, so it still catches up, just not instantly.

## Sessions

A session spans one continuous game client launch **for one commander**, saved to `plugin/sessions.json` (next to the installed plugin, not part of the distributed release — see Updates above). Logging out to the main menu and back in as the *same* commander, or closing and reopening EDMC while the game keeps running, both continue the same session instead of starting a new one — EDPPMT recognizes them by the journal file they share. Switching to a *different* commander at the login screen always starts a fresh, zeroed-out session, even without restarting the game client — Elite keeps writing to that same journal file across the switch, but EDPPMT checks the commander name too, not just the journal file. A new session also starts whenever the game itself is (re)launched, producing a new journal file; if the game isn't running, there's no active journal to continue, and your last session just sits there as-is until you launch it again. Sessions are per commander login, not per PowerPlay activity — defecting or leaving PowerPlay mid-session doesn't start a new one.

Deleting the plugin folder and dropping in a fresh copy removes `sessions.json` along with it, since it lives inside that same folder — copy a new version's files *into* the existing folder instead (which is what both the manual install steps above and auto-update do) to keep your history.

## Money

"Credits earned" is a simple diff of your credit balance from session start to now — it covers all income and expenses (trading, bounties, PP salary, ship costs, etc.), not just PowerPlay-specific income.

## For Developers

Building from source instead of using a release zip:

1. `npm run build` (or `node scripts/build.mjs`) — produces `dist/EDPPMT/`.
2. Copy `dist/EDPPMT` into your EDMC plugins folder the same way as the player steps above.
3. Restart EDMC.

`npm run package` does both of those *and* zips the result to `dist/EDPPMT-v<version>.zip` — the same artifact published on the Releases page.

There's no EDMC install available in this repo, so `plugin/`'s modules can't be imported standalone — `config`, `theme`, `myNotebook`, and `companion` are all provided by EDMC at runtime, not installable packages. See [`docs/tech-spec.md`](docs/tech-spec.md) for the module layout and the EDMC API surface this plugin uses.

**Auto-update is off by default, but can still overwrite a local test install if you've turned it on for that copy.** A plugin folder dropped into your EDMC plugins directory for testing looks, to `update.py`, exactly like a real install - if "Automatically download updates" is enabled there and the local build is older than the latest GitHub Release, EDMC will download and stage that release over your hand-edited files on its next restart. Drop an empty `disable-auto-update.txt` file in the plugin folder to override the checkbox unconditionally if you want it on elsewhere while still hand-editing this copy.

## Documentation

- [`docs/tech-spec.md`](docs/tech-spec.md) — architecture, module layout, data formats, and the EDMC plugin API surface used.
- [`docs/ATTRIBUTIONS.md`](docs/ATTRIBUTIONS.md) — sources for the journal event fields and merit/CP ratios this plugin relies on.
- [`CHANGELOG.md`](CHANGELOG.md) — release history.
