# EDPPMT

**Elite Dangerous PowerPlay Merit Tracker**

A lightweight [Elite Dangerous Market Connector](https://github.com/EDCD/EDMarketConnector) (EDMC) plugin that tracks the PowerPlay merits you earn as you play, estimates the Control Points (CP) and credits they represent, and keeps a history of every session — live, automatically, with no setup beyond installing it. EDPPMT never touches the game itself; it only reads *Elite Dangerous*'s own journal files via EDMC, the same way EDMC does.

**Author:** R.W. Harper (CMDR Bocheaux)
**Version:** 1.10.1
**License:** [MIT](LICENSE)

---

## Features

- **Live merit & CP tracking** — merits and estimated Control Points for your current system, and for the session as a whole, updating in real time as you play.
- **Session history** — every session's totals are saved automatically, so you can compare past sessions later, not just watch the live one.
- **Rare Goods Finder** — the nearest rare commodities to wherever you are, each with its origin system's *current* PowerPlay controller looked up live.
- **Auto-Honk** — fires your ship's Discovery Scanner automatically on every system jump.
- **Interdiction Warning** — an on-screen heads-up, drawn the instant an interdiction starts, before it even resolves.
- **Self-update** — optional one-click updates from Settings; off by default.

## Table of Contents

- [Install](#install)
- [Updates](#updates)
- [Using EDPPMT](#using-edppmt)
- [How activity is classified](#how-activity-is-classified)
- [CP ratios](#cp-ratios)
- [Sessions](#sessions)
- [Money](#money)
- [For Developers](#for-developers)
- [Learn More](#learn-more)

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

## Using EDPPMT

- **Main EDMC panel** — pledged Power and rank on its own line (e.g. `Pledged to Yuri Grom (Rank 3)`), then which game mode you're playing in right now (`Mode: Open`, `Mode: Solo`, or `Mode: Private (<group name>)`), the current system and its PowerPlay state (e.g. `System: Nervi — Exploited (Zachary Hudson)`), two **"Here"** lines — a merit count, then the full CP breakdown (Acquisition/Reinforcement/Undermining, all three shown even at zero) — for *just the system you're in right now* — it switches the instant you jump, and keeps an accurate running total per system if you backtrack to somewhere you've already worked this session — and, below that, the session-wide merits/CP totals and credits earned, updated as journal events arrive. If your commander isn't pledged, it says so directly: `CMDR <name>: not a PP Pledge`. Click the "▾ EDPPMT:" title to collapse everything below the mode row down to one line — handy when you don't need it taking up space — and click again ("▸ EDPPMT:") to expand; the collapsed/expanded state is remembered across restarts. The title/pledge-status/mode rows stay visible either way. Rows that don't have real data yet show placeholder text ("Awaiting system data…", "Here: awaiting system data…", "Session merits: 0", etc.) rather than sitting blank, and the panel is refreshed with whatever session was already saved from your last run immediately on EDMC startup. Three buttons sit at the bottom: **Sessions** (below), **Rares** (see Rare Goods Finder below), and **Rescan** — EDMC doesn't replay journal history to plugins when it (re)starts with the game already running, so merits earned in the gap between an EDMC restart and it catching back up would otherwise be lost from the session total; Rescan re-reads the current journal file directly to recover them, and is safe to click any time (it won't double-count merits already tallied).
- **Sessions window** (click "Sessions" in the panel):
  - **Current Session** tab — a **By System** table (every system visited this session: merits, estimated CP, and a per-activity breakdown, current system pinned to the top and marked); a **By Activity** table with the session-wide breakdown (Acquisition / Reinforcement / Undermining / Delivery-Donation / Unattributed): merits, the ratio used, estimated CP, and CP/hr; the current PowerPlay context (system, state, controller, rival Powers — for sanity-checking a row that looks wrong); and credits earned this session plus the rate.
  - **History** tab — every past session (bounded to the most recent 200), so you can compare sessions later, not just watch the live one; plus an "All sessions" summary (cumulative merits, CP by activity, and credits earned across the current session and all saved history).
  - Buttons along the bottom: **Refresh** and **Close**, plus **Reset Session** (zeroes this session's merit totals — by system and by activity — without ending the session or touching credit tracking; mainly useful for correcting a bad count, such as the well-known donation-mission duplicate-merit journal bug), **Reset Current System** (zeroes just the current system's contribution, subtracted back out of the session totals too), and **Copy Progress** (copies one formatted line per row in the By System table to the clipboard — format is configurable in Settings, see below). Both resets ask for confirmation first and can't be undone.
- **Rare Goods Finder** (click "Rares" in the panel) — the nearest rare commodities to your current system, sorted by distance (nearest first, though distance itself isn't shown): rare good, origin system, station, pad size, and the origin system's current PowerPlay Controlling Power. "Show nearest" controls how many to list — type up to 141 to see the entire bundled dataset. Double-click a row to open that rare good's page on Inara. Shows "Awaiting system data…" until EDPPMT has seen a `FSDJump`/`Location` event this run. The rare-good data itself (origin, station, pad, legality, PowerPlay eligibility, galactic coordinates — 141 entries) is bundled with the plugin and never makes a network call, since none of it changes; Controlling Power is the one column looked up live (from [Spansh](https://www.spansh.co.uk/)) since PowerPlay control shifts week to week — it shows "…" while loading and "—" if the system is unclaimed or the lookup fails (e.g. no internet).
- **Interdiction Warning** (Settings → Interdiction Warning, off by default) — draws a warning on your in-game overlay the instant an interdiction starts (before it resolves), then updates it with who's interdicting (including their affiliated Power, when there is one) and the outcome (escaped / pulled from supercruise / submitted), auto-clearing a few seconds later. This draws through [EDMCOverlay](https://github.com/inorton/EDMCOverlay), a separate, optional community tool EDPPMT does not install, bundle, or launch itself — it just sends to whatever's listening on the host/port configured in Settings (default `127.0.0.1:5010`) if the feature is enabled, and silently does nothing if that's not reachable. A "Test Warning" button simulates a full interdiction lifecycle and reports whether the send actually succeeded, so you can check your EDMCOverlay setup without waiting for a real one.
- **Auto-Honk** (Settings → Auto-Honk, off by default, Windows only) — fires your ship's Discovery Scanner (the system-wide "honk," not the Detailed Surface Scanner) every time you jump into a new system. Choose which fire button (Primary/Secondary) the Discovery Scanner is bound to and a hold duration long enough to cover your ship's actual charge time; EDPPMT reads your active keybindings file to find the physical key that fire button maps to, and says so plainly in Settings if it can't (e.g. it's only bound to a joystick/HOTAS button). Use "Rescan keybind & running apps" after rebinding in-game, and "Test Honk Now" to fire immediately and confirm it reaches the game window. If EDCoPilot is also running with its own AutoHonk setting on, Settings flags it so you can turn one off and avoid double-honking. "Skip systems already visited this session" (on by default) avoids re-honking familiar space.
- **Settings tab** — the installed version (a static link to the Releases page) at the top, then four sub-tabs, one per feature:
  - **Tracking** — **CP Ratios** (the merits-per-CP ratio for each activity, editable in case Frontier tunes Powerplay balance or a default turns out to be off) and **Clipboard** (the line format "Copy Progress" in the Sessions window uses, with placeholders for the system name/Inara URL/merits/CP/PowerPlay state, and a "Reset to default" button).
  - **Auto-Honk** and **Interdiction Warning** — described above.
  - **Updates** — the auto-update checkbox (off by default).

## How activity is classified

EDPPMT infers whether a batch of merits counts as Acquisition, Reinforcement, or Undermining from the PowerPlay state of the system you're in when they land, relative to your pledged Power:

- Nobody holds the system yet → **Acquisition**
- You hold it → **Reinforcement**
- A rival holds it → **Undermining**
- Can't tell (not currently pledged, or no system context seen yet this session) → **Unattributed**

**Delivery/Donation** is the one exception: handing in PowerPlay commodities or data at a power contact is tagged directly, without guessing at a system state.

This is a best-effort heuristic, not something the game states directly — Frontier has never documented a merits→activity mapping in the journal. If a row in the Sessions window looks wrong, that's useful signal: the system name and raw PowerPlay state your commander last saw are shown right there so you can compare them against what you'd expect. See [`docs/tech-spec.md`](docs/tech-spec.md#6-merit--activity--cp-pipeline) for the full mechanics, including how pledge detection recovers itself if EDMC starts after the game is already running.

## CP ratios

| Activity | Default (merits per 1 CP) |
|---|---|
| Acquisition | 4.0 |
| Reinforcement | 2.5 |
| Undermining | 4.2 |
| Delivery/Donation | *(none — merits only, see above)* |

These are community-sourced for Powerplay 2.0 (Undermining is the least certain of the three) and editable from Settings → Tracking → CP Ratios if Frontier tunes the balance or a default turns out to be off. CP is never baked into stored session data — it's recalculated from the current ratio settings whenever you view a session, so correcting a ratio retroactively fixes CP estimates for history too. See [`docs/ATTRIBUTIONS.md`](docs/ATTRIBUTIONS.md) for where these numbers come from.

## Sessions

A session spans one continuous game client launch **for one commander**, saved to `plugin/sessions.json` (next to the installed plugin, not part of the distributed release — see Updates above). Logging out to the main menu and back in as the *same* commander, or closing and reopening EDMC while the game keeps running, both continue the same session instead of starting a new one. Switching to a *different* commander at the login screen always starts a fresh, zeroed-out session, even without restarting the game client. A new session also starts whenever the game itself is (re)launched. Sessions are per commander login, not per PowerPlay activity — defecting or leaving PowerPlay mid-session doesn't start a new one.

Deleting the plugin folder and dropping in a fresh copy removes `sessions.json` along with it, since it lives inside that same folder — copy a new version's files *into* the existing folder instead (which is what both the manual install steps above and auto-update do) to keep your history.

## Money

"Credits earned" is a simple diff of your credit balance from session start to now — it covers all income and expenses (trading, bounties, PP salary, ship costs, etc.), not just PowerPlay-specific income.

## For Developers

Building from source instead of using a release zip:

1. `npm run build` (or `node scripts/build.mjs`) — produces `dist/EDPPMT/`.
2. Copy `dist/EDPPMT` into your EDMC plugins folder the same way as the player steps above.
3. Restart EDMC.

`npm run package` does both of those *and* zips the result to `dist/EDPPMT-v<version>.zip` — the same artifact published on the Releases page.

There's no EDMC install available in this repo, so `plugin/`'s modules can't be imported standalone — `config`, `theme`, `myNotebook`, and `companion` are all provided by EDMC at runtime, not installable packages. See [`docs/tech-spec.md`](docs/tech-spec.md) for the module layout, data formats, and the full EDMC plugin API surface this plugin uses — that's the place to look for *how* any of this works internally, rather than here.

**Auto-update is off by default, but can still overwrite a local test install if you've turned it on for that copy.** A plugin folder dropped into your EDMC plugins directory for testing looks, to `update.py`, exactly like a real install - if "Automatically download updates" is enabled there and the local build is older than the latest GitHub Release, EDMC will download and stage that release over your hand-edited files on its next restart. Drop an empty `disable-auto-update.txt` file in the plugin folder to override the checkbox unconditionally if you want it on elsewhere while still hand-editing this copy.

## Learn More

- [`docs/tech-spec.md`](docs/tech-spec.md) — architecture, module layout, data formats, the full journal-event handling and activity-classification pipeline, and the EDMC plugin API surface used.
- [`docs/ATTRIBUTIONS.md`](docs/ATTRIBUTIONS.md) — sources for the journal event fields, merit/CP ratios, and third-party data this plugin relies on.
- [`CHANGELOG.md`](CHANGELOG.md) — release history.
