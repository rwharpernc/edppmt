# Attributions & Credits

## Author

**R.W. Harper (CMDR Bocheaux)** — creator and maintainer of EDPPMT.

Roughly half of this project's implementation and documentation was produced in collaboration with [Claude](https://www.anthropic.com/claude) (Anthropic), used as an AI coding assistant throughout development.

## Software & Libraries

| Project | Role | License / Terms |
|---------|------|-----------------|
| [Elite Dangerous Market Connector (EDMC)](https://github.com/EDCD/EDMarketConnector) | Host application and plugin API, including the `myNotebook`, `theme`, and `config` modules imported at runtime (see `docs/tech-spec.md` §3.3) | [GPL-2.0](https://github.com/EDCD/EDMarketConnector/blob/main/COPYING) |
| Python Standard Library | Plugin runtime (provided by EDMC) | PSF License |
| Node.js | Build tooling only (`scripts/build.mjs`) | [MIT](https://github.com/nodejs/node/blob/main/LICENSE) |
| Windows PowerShell `Compress-Archive` | Packaging tooling only (`scripts/package.mjs`, zips the build output) | Proprietary (Microsoft, bundled with Windows) |
| [EDMCOverlay](https://github.com/inorton/EDMCOverlay) | **Not bundled or installed by EDPPMT.** `plugin/overlay.py` is EDPPMT's own client, written against EDMCOverlay's published local-TCP JSON protocol (confirmed against its own `edmcoverlay.py`) — it's an optional, separately-installed tool the Interdiction Warning feature draws through if the user has it running. | No license declared in the upstream repo at time of writing — EDPPMT's own client code (`overlay.py`) is original, written to the protocol, not copied from it |

EDPPMT is an independent third-party plugin. It is not affiliated with, endorsed by, or maintained by the EDMC development team.

## Game & Data References

| Source | Use in EDPPMT |
|--------|---------------|
| [Frontier Developments](https://www.frontier.co.uk/) — *Elite Dangerous* | Player Journal events (`PowerplayMerits`, `Powerplay`, `PowerplayJoin`, `PowerplayLeave`, `PowerplayDefect`, `PowerplayRank`, `FSDJump`, `Location`, `Docked`, `LoadGame`, `ReceiveText`, `Interdicted`, `EscapeInterdiction`), plus `Status.json`'s `Flags` field (bit 23, "Being Interdicted") |
| [EDCD/EDMarketConnector `monitor.py`](https://github.com/EDCD/EDMarketConnector/blob/main/monitor.py) | Verified directly against this file (not just the journal manual, which predates Powerplay 2.0): confirms `state['Credits']` update behavior across event types, `state['Powerplay']` field names (`Power`, `Rank`, `Merits`, `Votes`, `TimePledged`), and that `PowerplayMerits.TotalMerits` is a running total — the basis for EDPPMT's `MeritsGained`-missing fallback (diffing `TotalMerits`) |
| [EDCD/EDMarketConnector `PLUGINS.md`](https://github.com/EDCD/EDMarketConnector/blob/main/PLUGINS.md) and [`edmc_data.py`](https://github.com/EDCD/EDMarketConnector/blob/main/edmc_data.py) | Confirms the `dashboard_entry(cmdr, is_beta, entry)` plugin callback signature (`plugin/load.py`) and `FlagsBeingInterdicted = 1 << 23`, the basis for Interdiction Warning's earliest detection signal (`plugin/interdiction.py`) |
| [Elite Dangerous Player Journal Manual v23](http://hosting.zaonce.net/community/journal/v23/Journal_Manual_v23.pdf) (Frontier, official but outdated) | `Powerplay`, `PowerplayCollect`, `PowerplayDefect`, `PowerplayDeliver`, `PowerplayFastTrack`, `PowerplayJoin`, `PowerplayLeave`, `PowerplaySalary`, `PowerplayVote`, `PowerplayVoucher` event field documentation, and the `PowerplayState`/`Powers` fields on `FSDJump`/`Location`. Predates Powerplay 2.0 — does **not** document `PowerplayMerits`, `PowerplayRank`, or the current `PowerplayState` value set. A community request to Frontier to update this manual for Powerplay 2.0 was open and unresolved as of this plugin's writing. |
| Community-shared journal excerpts (Frontier forums, various) | Confirms the undocumented `PowerplayMerits` fields `MeritsGained` and `TotalMerits` |
| Community sources (various Powerplay 2.0 guides and reference pages) | The merits-per-Control-Point ratios in `formulas.DEFAULT_RATIOS` (Acquisition 4.0, Reinforcement 2.5 per the plugin author's own figures; Undermining 4.2 as the best available community estimate at time of writing). **Not official Frontier data** — Frontier has never published these ratios, and Powerplay balance is known to change between updates. All three are exposed as editable Settings for this reason. |
| [EDSM](https://www.edsm.net/) | One-time lookup (done at authoring time, not a runtime dependency) of galactic coordinates for the 137 rare-good origin systems in `plugin/rare_goods.json`, via EDSM's public system API. Baked into the bundled file since rare-good locations are static — the Rares window never calls EDSM itself. |
| [Inara](https://inara.cz/) | One-time lookup (done at authoring time, not a runtime dependency) of each rare good's numeric Inara commodity id, from Inara's public rare-goods listing page. Baked into `plugin/rare_goods.json` as `inaraId` so the Rares window's double-click can link straight to `inara.cz/elite/commodity/<id>/` — Inara's own name-search endpoint for commodities doesn't resolve to a specific item the way its system search does. |
| [Spansh](https://www.spansh.co.uk/) | Two uses: (1) one-time lookup (authoring time) of each origin system's numeric `id64`, baked into `plugin/rare_goods.json` as `spanshId64`; (2) a genuine runtime dependency — `plugin/powerplay_lookup.py` queries Spansh's public `system/<id64>` endpoint live each time the Rares window refreshes, to show each origin system's current PowerPlay Controlling Power. This is the one part of the Rares Finder that isn't offline, because control (unlike rare-good locations) changes week to week; EDSM's own system API does not expose it. |

*Elite Dangerous* and all related marks are trademarks of Frontier Developments plc. This plugin is a fan-made tool and is not official Frontier Developments software.

## Inspiration

Other Elite Dangerous plugins and companion apps whose existing features shaped EDPPMT's own design:

| Project | Inspired |
|---------|----------|
| [Fumlop/EliteMeritTracker](https://github.com/Fumlop/EliteMeritTracker) and [alby666/EDMC-PowerPlayProgress](https://github.com/alby666/EDMC-PowerPlayProgress) (EDMC plugins; reviewed for approach, not code) | Merit/CP activity classification. Confirmed that no EDMC plugin — nor the journal itself — has a direct field mapping merits to a specific PP activity; both approach it as inference from surrounding context, same as EDPPMT's system-state-based classification. alby666/EDMC-PowerPlayProgress specifically also inspired three later additions: manual Reset/Reset Session counters, a configurable clipboard-copy format for session progress, and the Rare Goods Finder (its own "nearest rare commodities" feature). |
| EDCoPilot (third-party ED companion app) | Auto-Honk (`plugin/autohonk.py`) is modeled on EDCoPilot's own AutoHonk feature — automatically firing the Discovery Scanner on system entry, including a "HonkFiregroup"-style choice of fire button. EDPPMT's Settings tab also detects when EDCoPilot is running with its own AutoHonk enabled, to warn against double-honking. |
| EDDDT (a sibling project, an Electron/TypeScript app — `src/main/auto-honk/`, `src/main/input/`, `src/main/journal/binds.ts`, `src/main/interdiction/tracker.ts`, `src/shared/interdiction.ts`) | Auto-Honk's implementation is a straight port from EDDDT: the binds-file lookup, the ED key-token-to-Windows-virtual-key `KEY_MAP` (built from a real `Custom.binds` file), and the Win32 key-injection approach (including the "fake Alt tap" foreground-lock workaround), re-implemented in Python via `ctypes` in place of EDDDT's Node/PowerShell approach. **Interdiction Warning** (`plugin/interdiction.py`) is likewise a direct port of EDDDT's detection state machine and chat-taunt phrase list (`CHAT_THREAT_PATTERNS`, itself originally from the author's ED-obs-app) — re-implemented without Tk/EventEmitter, drawn via EDMCOverlay instead of EDDDT's own Electron overlay window since EDPPMT has no equivalent renderer of its own. |
| [ED-Rare-Router](https://github.com/rwharpernc/ED-Rare-Router) (a sibling project, same author, GPL-3.0 — an Astro/TypeScript web app for rare-goods route planning) | `plugin/rare_goods.json`'s 141-entry rare-goods dataset (origin system, station, pad size, cost, legality restrictions, PowerPlay eligibility) is ported from ED-Rare-Router's `src/data/rares.ts`, with galactic coordinates added (see the EDSM row above) for EDPPMT's simpler nearest-rares-to-current-system use case. Both projects share an author, so relicensing this data under EDPPMT's MIT license is the author's own call. |

## Community Resources

- [EDMC Plugin Documentation (PLUGINS.md)](https://github.com/EDCD/EDMarketConnector/blob/main/PLUGINS.md)
- [EDMC Plugin Registry](https://github.com/EDCD/EDMC-Plugin-Registry)

## License

EDPPMT source code is released under the [MIT License](../LICENSE).
