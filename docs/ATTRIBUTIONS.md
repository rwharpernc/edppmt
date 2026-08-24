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

EDPPMT is an independent third-party plugin. It is not affiliated with, endorsed by, or maintained by the EDMC development team.

## Game & Data References

| Source | Use in EDPPMT |
|--------|---------------|
| [Frontier Developments](https://www.frontier.co.uk/) — *Elite Dangerous* | Player Journal events (`PowerplayMerits`, `Powerplay`, `PowerplayJoin`, `PowerplayLeave`, `PowerplayDefect`, `PowerplayRank`, `FSDJump`, `Location`, `Docked`, `LoadGame`) |
| [EDCD/EDMarketConnector `monitor.py`](https://github.com/EDCD/EDMarketConnector/blob/main/monitor.py) | Verified directly against this file (not just the journal manual, which predates Powerplay 2.0): confirms `state['Credits']` update behavior across event types, `state['Powerplay']` field names (`Power`, `Rank`, `Merits`, `Votes`, `TimePledged`), and that `PowerplayMerits.TotalMerits` is a running total — the basis for EDPPMT's `MeritsGained`-missing fallback (diffing `TotalMerits`) |
| [Elite Dangerous Player Journal Manual v23](http://hosting.zaonce.net/community/journal/v23/Journal_Manual_v23.pdf) (Frontier, official but outdated) | `Powerplay`, `PowerplayCollect`, `PowerplayDefect`, `PowerplayDeliver`, `PowerplayFastTrack`, `PowerplayJoin`, `PowerplayLeave`, `PowerplaySalary`, `PowerplayVote`, `PowerplayVoucher` event field documentation, and the `PowerplayState`/`Powers` fields on `FSDJump`/`Location`. Predates Powerplay 2.0 — does **not** document `PowerplayMerits`, `PowerplayRank`, or the current `PowerplayState` value set. A community request to Frontier to update this manual for Powerplay 2.0 was open and unresolved as of this plugin's writing. |
| Community-shared journal excerpts (Frontier forums, various) | Confirms the undocumented `PowerplayMerits` fields `MeritsGained` and `TotalMerits` |
| Community sources (various Powerplay 2.0 guides and reference pages) | The merits-per-Control-Point ratios in `formulas.DEFAULT_RATIOS` (Acquisition 4.0, Reinforcement 2.5 per the plugin author's own figures; Undermining 4.2 as the best available community estimate at time of writing). **Not official Frontier data** — Frontier has never published these ratios, and Powerplay balance is known to change between updates. All three are exposed as editable Settings for this reason. |

*Elite Dangerous* and all related marks are trademarks of Frontier Developments plc. This plugin is a fan-made tool and is not official Frontier Developments software.

## Inspiration

Other Elite Dangerous plugins and companion apps whose existing features shaped EDPPMT's own design:

| Project | Inspired |
|---------|----------|
| [Fumlop/EliteMeritTracker](https://github.com/Fumlop/EliteMeritTracker) and [alby666/EDMC-PowerPlayProgress](https://github.com/alby666/EDMC-PowerPlayProgress) (EDMC plugins; reviewed for approach, not code) | Merit/CP activity classification. Confirmed that no EDMC plugin — nor the journal itself — has a direct field mapping merits to a specific PP activity; both approach it as inference from surrounding context, same as EDPPMT's system-state-based classification. |
| EDCoPilot (third-party ED companion app) | Auto-Honk (`plugin/autohonk.py`) is modeled on EDCoPilot's own AutoHonk feature — automatically firing the Discovery Scanner on system entry, including a "HonkFiregroup"-style choice of fire button. EDPPMT's Settings tab also detects when EDCoPilot is running with its own AutoHonk enabled, to warn against double-honking. |
| EDDDT (a sibling project, an Electron/TypeScript app — `src/main/auto-honk/`, `src/main/input/`, `src/main/journal/binds.ts`) | Auto-Honk's implementation is a straight port from EDDDT: the binds-file lookup, the ED key-token-to-Windows-virtual-key `KEY_MAP` (built from a real `Custom.binds` file), and the Win32 key-injection approach (including the "fake Alt tap" foreground-lock workaround), re-implemented in Python via `ctypes` in place of EDDDT's Node/PowerShell approach. |

## Community Resources

- [EDMC Plugin Documentation (PLUGINS.md)](https://github.com/EDCD/EDMarketConnector/blob/main/PLUGINS.md)
- [EDMC Plugin Registry](https://github.com/EDCD/EDMC-Plugin-Registry)

## License

EDPPMT source code is released under the [MIT License](../LICENSE).
