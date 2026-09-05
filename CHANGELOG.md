# Changelog

All notable changes to EDPPMT are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.13.3] - 2026-09-05

### Changed
- Main panel now starts collapsed by default (`edppmt_main_collapsed` now defaults to `true`) — every
  plugin from this developer now starts minimized on first launch until a commander opts into the
  expanded view; an existing install's already-saved preference is unaffected either way.
- Main-panel title changed from "EDPPMT:" to "PowerPlay Merit Tracker (EDPPMT)" for clarity in a
  multi-plugin EDMC install.

### Fixed
- The collapsible header title rendered in the regular font weight instead of bold, inconsistent with
  every other plugin's own header (ED-PLG/EDMRT/EDMMM/EDSSC/Boxelator all use a bold title). Added the
  same `_bold_font` helper and applied it to `_title_label`.
- Expanding the collapsed section could grow the whole EDMC main window: the single row holding all six
  buttons (quick toggles, divider, Rares/Sessions/Rescan) was wider than every other row on the panel,
  so the first time it became visible it — not any wrapping text row — pushed the window wider to fit
  it. Split into two half-width rows (toggles, then window-openers) so neither can exceed the panel's
  already-established width.
- A separator's fixed 46-dash guess could, for the same reason, become the panel's widest row the
  moment its section first became visible. Separators now start at a short, safely-narrow dash count
  and are widened to match the frame's already-established width, the same rule already applied to
  wrapping text labels.

## [1.13.2] - 2026-09-05

### Fixed

- **Interdiction Warning false-triggering on ordinary chat.** Its NPC chat-taunt
  detection (`CHAT_THREAT_PATTERNS`) matched `ReceiveText` messages on *any*
  channel, so other commanders casually typing words like "pirate" or
  "interdict" in system-wide chat or squadron chat — not an actual
  interdiction — could flip the warning active. Root cause confirmed against
  ~125k logged `ReceiveText` events: every false match came from the
  `starsystem`/`squadron` channels (human chat), while every match on the
  `npc` channel was a genuine taunt. Detection now only considers
  `Channel == "npc"`.

### Documentation

- **README's "Using EDPPMT" section reorganized** into per-feature
  subsections with buttons/controls pulled into scannable lists instead of
  one dense paragraph per feature — no content removed, just restructured
  for easier lookup.

## [1.13.1] - 2026-09-03

### Added

- **Landing's in-app display (Settings → Landing → "Show in EDMC app")
  now includes the pad-layout diagram**, not just the status/pad/
  denied-reason text line added in 1.13.0 — the same dodecagon (starport)
  or Large/Medium/Small grid (fleet carrier/squadron carrier/colonisation
  ship) diagram the overlay draws, at a small fixed size that fits the
  main panel. Both diagrams are now built from the same shared geometry
  code, so the overlay and in-app pictures always match. Settings →
  Landing's "Test Overlay" button now previews the in-app line and diagram
  too, alongside its existing overlay send.

### Fixed

- **In-app Landing diagram not blending into the panel** — it showed as a
  visibly mismatched box instead of matching your EDMC theme. Root cause:
  the canvas was given an explicit `background=` at creation, which made
  EDMC's theme engine treat it as user-overridden and permanently skip
  re-theming it, leaving it stuck on Tk's plain default background instead
  of the live Dark/Light/Transparent theme color every other widget on the
  panel tracks. The explicit background is gone; the canvas now themes
  itself the same way the rest of the panel does.
- **In-app Landing diagram too small to read at a glance** — bumped from a
  120px to a 200px fixed square (still a hard-coded cap on both axes, per
  the EDMC-plugin rule that a main-panel widget can never let its size
  float with content), with bolder lines and a larger pad marker.

## [1.13.0] - 2026-09-03

### Added

- **Landing now shows in the EDMC app itself**, not just the overlay — a
  new line below the main-panel buttons mirrors the same docking status,
  assigned pad, and approval/denial reason. Settings → Landing has two new
  independent checkboxes, "Show on Overlay" and "Show in EDMC app" (both on
  by default), so either display can be turned off without disabling the
  other; the main panel's existing "Landing" button (and Settings' "Enable
  Landing" checkbox) still turns both off at once.

### Changed

- **The pad number is no longer drawn on the Landing diagram graphic
  itself** — the assigned pad/rect is still highlighted, but the number is
  only ever shown once, in the "Pad N" status line above the diagram (and
  now in the EDMC app line too).

## [1.12.2] - 2026-09-03

### Fixed

- **Landing's overlay visibly drifting/jumping around the screen on
  EDMCModernOverlay**, with its pad number sometimes landing off from the
  pad it labels. Root cause: this widget's card, text, and diagram are all
  one registered EDMCModernOverlay Plugin Group, and hidden/inactive pieces
  were being "cleared" by sending them to literal screen coordinate
  `(0, 0)` at zero size. EDMCModernOverlay's Fill-mode grouping includes
  every live payload's raw position in its bounding-box calculation
  regardless of size, so those parked-at-origin payloads were dragging the
  whole widget's computed anchor toward the top-left corner for as long as
  they stayed live, then releasing once they expired — a constant,
  out-of-phase pull as different payloads' ttls ran down on their own
  schedules. Cleared/inactive payloads are now parked within the widget's
  own real footprint instead, which keeps the group's bounding box (and
  therefore its position) stable. Interdiction Warning's card had the same
  bug and got the same fix.
- **Fleet-carrier diagram's active-pad number visibly off-center**,
  worse for single-digit pad numbers than double-digit ones. Its manual
  centering offset was a single fixed value; it now scales with the pad
  number's digit count.

## [1.12.1] - 2026-09-03

### Added

- **`scripts/test_overlay.py`** (`npm run test:overlay`), a standalone
  developer CLI that exercises every Interdiction Warning/Landing overlay
  scenario against a real EDMCOverlay/EDMCModernOverlay instance without
  EDMC running (Elite Dangerous itself still needs to be, for the overlay
  app to have a window to draw itself onto) — see README's "For
  Developers" section.

### Fixed

- **Landing's overlay disappearing before you actually landed**, then
  popping back up once you did. Every graphic sent to EDMCOverlay carries a
  ttl, and Landing only refreshed on docking-related journal events — if
  the approach from Docking Approved to touchdown took longer than that
  ttl (easy at a large or busy station), the overlay expired and vanished
  mid-approach with nothing to refresh it, then reappeared once the
  `Docked` event finally fired. It now refreshes itself on a repeating
  timer for as long as a docking request is outstanding, so it stays up
  continuously from approval through touchdown, then auto-hides as before.
- **Landing's card leaving a large empty gap on its right side**, with the
  pad diagram crammed off to the left instead of centered. The card is now
  sized to hug its actual content, and the diagram is centered on its
  midline.
- **Landing's starport pad diagram still rendering as an "exploded"
  scattered mess on EDMCModernOverlay**, even after the connection fix
  below. EDMCModernOverlay has its own "Plugin Group" system specifically
  for scaling multi-piece vector payloads together as one unit — without
  registering one, each of the diagram's ~17 separate shape pieces was
  apparently being scaled/anchored independently around its own tiny
  bounding box. EDPPMT now registers its payload ids with EDMCModernOverlay
  on startup (a silent no-op on classic EDMCOverlay, which has no such
  system and isn't affected by this).
- **Overlay graphics (Interdiction Warning, Landing) not reliably staying
  on screen, and Landing's pad diagram rendering as broken/incomplete
  pieces.** `overlay.py` was opening a new TCP connection per message and
  closing it immediately after sending. EDMCOverlay deletes a connection's
  graphics the instant that connection disconnects, independent of `ttl` —
  so every graphic was being removed moments after it arrived, before the
  next one (for a multi-piece diagram) even sent, and well before its
  intended lifetime. `OverlayClient` now holds one persistent connection
  open instead, reconnecting only if it actually drops.
- **Interdiction Warning appearing very late, or not until it was already
  resolving.** NPC chat taunts (`ReceiveText`) could only *enrich* an
  already-active warning, never trigger one on their own — so if
  Status.json's flag (the primary signal) was ever slow to reach the
  plugin, or momentarily missed, the warning waited for the interdiction
  to actually resolve before showing anything at all. A matching taunt is
  now an independent trigger in its own right, and whichever of the two
  signals arrives first no longer gets its identity data overwritten by
  the other arriving second.
- **Fleet carrier pad-diagram's active-pad number being unreadable** — its
  label was drawn in the same amber color as the fill it sits on top of.
  Now dark text, matching the reference diagram it's ported from.

### Changed

- **"Landing Pad" renamed to "Landing"** throughout the Settings tab, main
  panel button, and overlay — same feature, shorter name.
- **Landing's post-touchdown auto-hide shortened from 15 to 10 seconds.**
- **Interdiction Warning and Landing overlay colors now match the author's
  original design precisely**, rather than approximating it: Interdiction
  Warning's card and title stay a constant red regardless of state (a
  fixed safety-signal color, not themed) with only the resolution line
  itself color-coded (green/red/amber); Landing's card and title now use
  an "Elite Orange" chrome palette (dark, orange-bordered card;
  orange-toned text hierarchy), with only the status/denied-reason text
  staying semantically red/green. Interdiction Warning's title also lost
  its ⚠ emoji, which the overlay's bundled font likely couldn't render.

## [1.12.0] - 2026-09-03

### Added

- **Landing Pad.** Draws docking status on your in-game overlay from the
  moment you request docking (Docking Requested → Approved/Denied), plus a
  pad-layout diagram highlighting the specific pad you're assigned — a
  dodecagon layout for starports/outposts/planetary ports, or a
  Large/Medium/Small grid for fleet carriers, squadron carriers, and
  colonisation ships. Stays up for ~15 seconds after touchdown, then
  auto-hides. Off by default; draws through
  [EDMCOverlay](https://github.com/inorton/EDMCOverlay) (same connection as
  Interdiction Warning). New Settings → Landing Pad section with a "Test
  Overlay" button. Written by the plugin author; its pad-diagram geometry
  cites the EDMC LandingPad plugin (bgol/LandingPad) as its original
  source for the pad-numbering table.
- **Main-panel quick toggles.** Three new buttons — **Auto-Honk**,
  **Interdiction**, **Landing Pad** — flip each feature on or off without
  opening Settings, turning green while enabled. They share the main
  panel's existing bottom button row with **Rares**/**Sessions**/**Rescan**,
  split from them by a vertical divider, and the whole row is now centered
  under the panel. Any change here shows up in the Settings tab's own
  checkbox immediately if it's open, and vice versa.

### Changed

- **Interdiction Warning and Landing Pad now draw a colored card behind
  their text** (and, for Landing Pad, the diagram too) instead of bare
  floating text on the overlay — a translucent dark background with a
  border colored to match the current state (red for a denial/bad outcome,
  green otherwise), closer to the boxed look the author was going for.
  Renders on both the original
  [EDMCOverlay](https://github.com/inorton/EDMCOverlay) and
  [EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay);
  the newer EDMCModernOverlay additionally gets a crisper, explicit border
  thickness where supported.

## [1.11.0] - 2026-09-02

### Added

- **"Rescan" button on the main panel**, next to "Sessions". EDMC does not
  replay journal backlog to plugins when it (re)starts with the game already
  running - only genuinely new events reach the plugin from that point on -
  so merits earned in the gap between an EDMC restart and the "StartUp"
  event it synthesizes afterward were previously lost from the session
  totals for good. Rescan re-reads the current journal file directly and
  recovers anything missed that way, without double-counting merits already
  tallied (tracked via the timestamp of the last-recorded merit gain, so
  clicking it again after it's already caught up is a safe no-op).

### Fixed

- **Main panel stretching EDMC's main window wider than it needs to be.**
  1.9.0 fixed lines wrapping too early by widening the fixed wrap guess
  from 380px to 640px, but a single guessed pixel width can't actually
  match "the panel's real available width" - that varies with font
  size/DPI scaling and how many other plugins are stacked in the same
  window, so 640px just moved the same bug (a guess that's wrong for some
  installs) in the other direction. Main-panel labels now track the
  frame's own current width instead of guessing at a fixed number, so this
  plugin's long lines can no longer be what forces the window wider in the
  first place.

## [1.10.1] - 2026-09-01

### Changed

- **Settings tab restructured.** Auto-Honk and Interdiction Warning each get
  their own top-level tab instead of being grouped under a generic "Alerts"
  tab (Auto-Honk isn't itself a warning). The Settings notebook also gets a
  visible border around the tab strip, since the default styling rendered
  it almost flush with the page background.

## [1.10.0] - 2026-08-31

### Added

- **Game mode on the main panel.** A new line right below pledge status
  shows which mode you're currently playing in — `Mode: Open`, `Mode:
  Solo`, or `Mode: Private (<group name>)` — read from the `LoadGame`
  journal event (recovered directly from the journal file if EDMC attached
  to an already-running game, same as pledge-status recovery). Stays
  visible when the main panel is collapsed, same as pledge status.
- **Manual reset controls.** The Sessions window gains **Reset Session**
  (zeroes this session's merit totals — by system and by activity — without
  ending the session or touching credit tracking) and **Reset Current
  System** (zeroes just the current system's contribution, subtracted back
  out of the session totals too) buttons, both confirmed before running.
  Mainly useful for correcting a bad count, such as the well-known
  donation-mission duplicate-merit journal bug.
- **Copy Progress to clipboard.** A new button in the Sessions window copies
  one formatted line per system in the By System table to the clipboard,
  using a user-editable template (Settings → Clipboard) with placeholders
  for the system name, an Inara link, merits, estimated CP, and PowerPlay
  state.
- **Rare Goods Finder.** A new "Rares" button on the main panel opens a
  window listing the nearest rare commodities to your current system —
  rare good, origin system, station, pad size, and the origin system's
  current PowerPlay Controlling Power, columns sized to the dataset's
  longest values and centered under their headings — sorted by distance,
  with double-click opening the rare good's page on Inara. The bundled
  141-entry dataset (compiled by the author, coordinates resolved once via
  EDSM) ships with the plugin and makes no network call; Controlling Power
  is looked up live from [Spansh](https://www.spansh.co.uk/) instead, since PowerPlay
  control isn't static like the rest of the dataset — it shows "…" while
  loading and "—" if unclaimed or unreachable.
- **Interdiction Warning.** Draws a warning on your in-game overlay the
  instant an interdiction starts (before it resolves), then updates it with
  who's interdicting — including their affiliated Power, when there is one —
  and the outcome (escaped / pulled from supercruise / submitted). Off by
  default; draws through [EDMCOverlay](https://github.com/inorton/EDMCOverlay),
  a separate, optional community tool EDPPMT does not install or launch
  itself. New Settings → Alerts → Interdiction Warning section with a "Test
  Warning" button.

### Changed

- **Settings tab reorganized.** The four flat sub-tabs (Auto-Honk / CP
  Ratios / Clipboard / Updates) are now three, grouped by purpose:
  **Tracking** (CP Ratios + Clipboard), **Alerts** (Auto-Honk + Interdiction
  Warning), and **Updates**.

Inspired by a review of [alby666/EDMC-PowerPlayProgress](https://github.com/alby666/EDMC-PowerPlayProgress) — see `docs/ATTRIBUTIONS.md`.

## [1.9.0] - 2026-08-25

### Added

- **Per-system CP tracking.** The main panel now shows two "Here" lines —
  a merit count, then the full CP breakdown (Acquisition/Reinforcement/
  Undermining, all three shown even at zero) — for *just the system you're
  currently in*. It switches the instant you jump, and keeps an accurate
  running total per system if you jump back to somewhere you've already
  worked this session, rather than folding everything into one session-wide
  number. The Sessions window's Current Session tab gains a matching **By
  System** table (merits, Est. CP, and a per-activity breakdown for every
  system visited this session, current system pinned to the top and
  marked). The existing session-wide Merits/CP lines are still there, just
  relabeled "Session merits"/"Session CP" so they're not confused with the
  per-system figures.
- **Pledge status now recovers from the journal file on a relog, without a
  full game restart.** Frontier only writes a `Powerplay` event once per
  client launch, not on every logout-to-menu-and-back, so if EDMC (or this
  plugin) had restarted in between, there was no live event left to tell
  EDPPMT the pledge status again — it showed "not pledged" until you fully
  relaunched the game. EDPPMT now falls back to reading the current journal
  file directly for the most recent pledge-lifecycle event
  (`Powerplay`/`PowerplayJoin`/`PowerplayLeave`/`PowerplayDefect`, whichever
  happened last) whenever it doesn't already know pledge status from a live
  event, the same way Auto-Honk already reads the keybindings file directly
  rather than waiting on the game.

### Changed

- **Settings tab reorganized into Auto-Honk / CP Ratios / Updates sub-tabs.**
  Previously everything sat in one long scroll, with Auto-Honk's five
  controls easy to lose among the CP ratio entries below them. Auto-Honk's
  tab now leads with a 3-step "how to set this up" note, and its fire
  button/hold-duration/behavior controls grey out together with the "Enable
  Auto-Honk" checkbox so it's visually obvious they only matter once it's
  on — Rescan and Test Honk Now stay active either way, since they're a
  standalone sanity check.
- **Sessions window readability pass.** The heading and PowerPlay-context
  blocks are now aligned label/value grids instead of hand-spaced single
  lines, and bold section headers ("By System", "By Activity (session
  total)", "Current PowerPlay Context", "All Sessions") break up what was
  one dense block per tab.

### Fixed

- **Main panel lines wrapping well short of the window's actual width.**
  The pledge status line ("Pledged to \<Power\> (Rank N)") shared a row with
  the title and version label, leaving it far less room than the panel's
  real width before wrapping — it now has its own full-width row. The
  "Here" line is now two dedicated lines (merit count, then the CP
  breakdown) instead of one line that could wrap mid-phrase. The wrap width
  shared by every other row was also a guessed, overly tight approximation
  of "EDMC's default width" that didn't hold up against real installs
  (typically running several plugins, each widening the window) — increased
  accordingly.

## [1.8.0] - 2026-08-25

### Changed

- **Auto-update is now opt-in, off by default.** Previously on by default
  (since v1.2.0) - anyone who never touched the Settings checkbox was
  getting automatic downloads without having asked for them. Existing
  installs that never explicitly set the checkbox will have auto-update
  turned off the next time they update to this version; anyone who wants
  it back on needs to check the box in Settings again.
- **The plugin version no longer shows permanently on the main panel.**
  It now lives only in the Settings tab (a static link to the Releases
  page, no longer changing color/text with update state). The main
  panel's version slot is otherwise silent and only ever shows one thing:
  a brief "Updated to vX.Y.Z" right after a staged update takes effect,
  clearing itself after about 15 seconds. The previous "Downloading
  vX…"/"Restart to Update (vX)" main-panel messages are gone - that state
  is still tracked internally, it just isn't shown anywhere anymore.

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
