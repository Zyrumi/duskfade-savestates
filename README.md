# Duskfade Save States (beta)

A **practice tool** for Duskfade runners: save your exact spot and warp back
to it with a hotkey, rewind the whole world to that moment, and see the
level's collision, death zones and story triggers through an overlay.

> **Practice only.** This tool reads and writes the running game's memory.
> While it is open, the game's HUD shows a **grey checkerboard behind the
> health clock dial**. That mark is forced and shows up in every recording.
> A run with the checkerboard visible anywhere is not a valid run.

This is a beta. The point of putting it out is to find where it breaks. See
[Reporting problems](#reporting-problems).

## Download

Get the zip from the [Releases](https://github.com/Zyrumi/duskfade-savestates/releases)
page, extract it anywhere, and run `Duskfade Save States.exe` while the game
is running. Windows SmartScreen may warn about an unknown publisher; choose
"More info" then "Run anyway".

Everything the tool creates (slots, settings, kept saves, backups, logs,
collision cache) is stored next to the exe.

**Updates:** from 0.2.1 on, the tool checks for a newer version when it starts
and shows an **Update to vX** button in its bottom bar. One click downloads
it, checks it against the release's published checksum, and restarts into the
new version; your slots and settings stay. (0.2.0 has no updater: download
0.2.1 by hand once.)

## The watermark

When the tool is open, every HUD the game builds shows the checkerboard dial,
starting from your next zone load. Dialogue boxes get a darkened checkerboard
background too, because the game hides the whole HUD while one is open (for
example during the time echo flight glitch). **Save (F5) and load (F8) only work while
the checkerboard is actually on screen** (HUD visible, not in a cutscene or
menu), and the overlay only draws then. F9 and loads from another level work
right away, because they reload a level, which builds a marked HUD; the warp
at the end waits until the mark shows. After you close the tool, the mark
stays until the next zone load.

## Save states

| Key | Action |
| --- | --- |
| **F5** | Save a state into the active slot |
| **F8** | Load: put Zirian back (spot, facing, camera, momentum, health, mana, potions, flight time) |
| **F9** | Full reset load: also rewind the world to the moment you pressed F5 |
| **F6 / F7** | Switch to the previous / next slot |

A soft chime confirms each action. Keys and the chime can be changed under
**Settings**. The keys only belong to the tool while the game window is in
front; in every other program they work as normal.

**F8** only restores Zirian; the world stays as it is now. **F9** also rewinds
story progress, unlocks, upgrades and every level's record of cutscenes,
dialogues, chests, shards, enemies and doors, then reloads the level (a couple
of seconds) and warps you. Use it for tricks that only work before something
has been triggered.

Loading a state from another level takes a few seconds: the tool sends you
through one of the current level's own exits to the right level, then warps
you. If no exit can be used, exit to the main menu: the tool swaps in the save
it kept with the state (your current save is backed up to `Backups\` first),
then pick **Continue**. Pressing the load key again cancels a pending load.

## Hazard overlay

Press **Overlay** in the tool's window. It draws over the game while the game
is in front:

- **Collision view**: every surface that blocks you. Green = floor you can
  stand on. **Striped sand = faces up but you slide on it** (too steep, or the
  level marks it unwalkable: no standing, no jump refresh). Blue = wall, dark =
  underside. Anything without collision isn't drawn.
- **DEATH / DAMAGE / NO RESPAWN** zones, **invisible walls**, **LOAD** zones
  (with destination and what switches them on), **CUTSCENE** and **DIALOGUE**
  triggers. Time echo dialogue zones are shown from any distance.
- **About you**: a trail of the last 10 seconds (solid = standing, dashed = in
  the air), your save-state slots in this level as ghost outlines (the active
  one bold, with a dotted line to it), and a line naming the surface under you
  and whether it holds you.

| Key | Action |
| --- | --- |
| **F10** | Show / hide the overlay |
| **Ctrl+F10** | Cycle what's shown: everything, walls, story triggers, damage and no-respawn, none |
| **Ctrl+Shift+F10** | Death planes on / off |
| **Shift+F10** | Labels: long, short, off |
| **F11** | Collision view: see-through, solid, off |
| **Ctrl+F11** | Draw range: 25k, near, everything |
| **Shift+F11** | Trail + "under you" line on / off |

The info box in the top-left corner (level name, what's under you) can be
switched off under **Settings** in the tool's window; key help and warnings
still show briefly when needed.

The first visit to a level takes a few seconds to read its collision; after
that it's cached and shows instantly.

## Known limits

- A few levels have no usable exit (for example arenas). There F9 stops with a
  message and F8 uses the main-menu route. `AncientTemple1_GB` always uses the
  main-menu route.
- Mana: the value is restored right away, but the gauge graphic only redraws
  the next time the game updates it (switching gadgets does it).
- F9 hides entries the game added after your F5 instead of deleting them; the
  dead entries are harmless but slowly accumulate in your save file.
- The overlay is a separate window on top of the game, so it trails camera
  movement by about a frame.
- Built and tested against the current Steam build. A game update may break it
  until it's re-checked.

## Reporting problems

Use [New issue](https://github.com/Zyrumi/duskfade-savestates/issues/new/choose).
The form asks which level you were in, what you pressed and what happened, and
has a box for `savestates.log` (and `overlay.log` for overlay problems) from
the tool's folder. The logs are the most useful part.

## License

The program is free to download and use for practice. It is not open source:
redistributing modified copies, or copies with the watermark removed, is not
permitted. Third-party components and their licenses are listed in
`THIRD-PARTY-NOTICES.txt` inside the zip.
