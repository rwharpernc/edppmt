# EDPPMT

**Elite Dangerous PowerPlay Merit Tracker**

A lightweight [Elite Dangerous Market Connector](https://github.com/EDCD/EDMarketConnector) (EDMC) plugin for *Elite Dangerous*. EDPPMT tracks how many PowerPlay merits you earn as you play, estimates how many Control Points (CP) that represents for Acquisition, Reinforcement, and Undermining activity, and tracks credit income alongside it — live, per session, with session history kept across game and EDMC restarts.

**Author:** R.W. Harper (CMDR Bocheaux)
**Version:** 1.2.0
**License:** [MIT](LICENSE)

---

## Why

The journal's `PowerplayMerits` event reports your actual merit take, already including every bonus the game applies — system strength/frontline penalties, ethos buffs, your Squadron's PP bonus, all of it. What it does *not* say is how many Control Points that's worth for the system, because that depends on which activity earned it, and Frontier has never documented the conversion in the journal (the last official journal manual predates Powerplay 2.0 entirely).

EDPPMT infers the activity from the PowerPlay state of the system you're in when the merits land, and converts to an estimated CP figure using an editable ratio table — so you can watch your CP contribution and credit income build in real time instead of doing the math yourself after the fact.

## How it works

EDPPMT never touches the game. It's a passive listener sitting behind EDMC:

```
Elite Dangerous  →  writes journal files  →  EDMC tails them  →  EDPPMT reacts
```

It reads `PowerplayMerits` for the merit amount, `Powerplay`/`PowerplayJoin`/`PowerplayDefect`/`PowerplayLeave` for which Power you're pledged to, and `FSDJump`/`Location`/`Docked` for the PowerPlay state of the system you're currently in — combining the last two to decide whether a batch of merits was Acquisition, Reinforcement, or Undermining. EDMC's own running credit balance (built from dozens of journal event types) is diffed against the session start to report money earned.

## Install

1. `npm run build` (or `node scripts/build.mjs`) — produces `dist/EDPPMT/`.
2. Copy `dist/EDPPMT` into your EDMC plugins folder: `%LOCALAPPDATA%\EDMarketConnector\plugins\EDPPMT`.
3. Restart EDMC.

Alternatively, `npm run package` builds and also zips the result to `dist/EDPPMT-v<version>.zip` — extract it and copy the `EDPPMT` folder it contains the same way. Handy for sharing a release without handing over the source tree.

## What it shows

- **Main EDMC panel** — pledged Power and rank (e.g. `Pledged to Yuri Grom (Rank 3)`), the current system and its PowerPlay state (e.g. `System: Nervi — Exploited (Zachary Hudson)`), live session merits, estimated CP, and merits/hr and credits/hr rates, updated as journal events arrive. If your commander isn't pledged, it says so directly: `CMDR <name>: not a PP Pledge`.
- **Sessions window** (click "Sessions" in the panel):
  - **Current Session** tab — a per-activity breakdown (Acquisition / Reinforcement / Undermining / Unattributed): merits, the ratio used, estimated CP, and CP/hr; the system name and raw `PowerplayState`/`Powers` last seen (for sanity-checking a row that looks wrong); and credits earned this session plus the rate.
  - **History** tab — every past session (bounded to the most recent 200), so you can compare sessions later, not just watch the live one.
- **Settings tab** — the merits-per-CP ratio for each activity, editable in case Frontier tunes Powerplay balance or a default turns out to be off.

## How activity is classified

There's no journal field that says "these merits were Acquisition." EDPPMT infers it from the current system's `PowerplayState` and `Powers` fields (reported on `FSDJump` / `Location` / `Docked` whenever the system is PowerPlay-relevant) relative to your pledged Power:

- Nobody holds the system yet → **Acquisition**
- You hold it → **Reinforcement**
- A rival holds it → **Undermining**
- Can't tell (not currently pledged, or no system context seen yet this session) → **Unattributed**

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

Pledge status is normally resolved right at login: the `Powerplay` event only fires if pledged, and its absence by the time the always-present `Location` event fires means not pledged. If you start EDMC *after* the game is already running, that startup handshake is missed — EDPPMT falls back to resolving pledge status (and which Power) from the first `PowerplayMerits` event it sees instead, so it still catches up, just not instantly.

## Sessions

A session spans one continuous game client launch, saved to `plugin/sessions.json` (next to the installed plugin). Logging out to the main menu and back in, or closing and reopening EDMC while the game keeps running, both continue the same session instead of starting a new one — EDPPMT recognizes them by the journal file they share. A new session only starts when the game itself is (re)launched, producing a new journal file; if the game isn't running, there's no active journal to continue, and your last session just sits there as-is until you launch it again. Sessions are per commander login, not per PowerPlay activity — defecting or leaving PowerPlay mid-session doesn't start a new one.

## Money

"Credits earned" is a simple diff of your credit balance from session start to now — it covers all income and expenses (trading, bounties, PP salary, ship costs, etc.), not just PowerPlay-specific income.

## Development

```
npm run build     # plugin/ -> dist/EDPPMT/
```

There's no EDMC install available in this repo, so `plugin/`'s modules can't be imported standalone — `config`, `theme`, `myNotebook`, and `companion` are all provided by EDMC at runtime, not installable packages. See `docs/tech-spec.md` for the module layout and the EDMC API surface this plugin uses.

## Documentation

- [`docs/tech-spec.md`](docs/tech-spec.md) — architecture, module layout, data formats, and the EDMC plugin API surface used.
- [`docs/ATTRIBUTIONS.md`](docs/ATTRIBUTIONS.md) — sources for the journal event fields and merit/CP ratios this plugin relies on.
- [`CHANGELOG.md`](CHANGELOG.md) — release history.
