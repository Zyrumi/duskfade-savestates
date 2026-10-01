# Duskfade Save States (beta)

A **practice tool** for Duskfade runners: save your exact spot and warp back
to it with a hotkey, or rewind the whole world to that moment.

> **Practice only.** This tool reads and writes the running game's memory.
> Close it before doing real runs. It never touches the game's files except
> when you use the main-menu fallback described below, which backs your save
> up first.

This is a beta. It has been tested in a handful of levels on one save; the
point of putting it out is to find where it breaks. See
[Reporting problems](#reporting-problems).

## What it does

| Key | Action |
| --- | --- |
| **F5** | Save a state into the active slot |
| **F8** | Load: put Zirian back (spot, facing, camera, momentum, health, mana, potions, flight time) |
| **F9** | Full reset load: also rewind the world to the moment you pressed F5 |
| **F6 / F7** | Switch to the previous / next slot |

A soft chime confirms each action, since the game covers the tool's window.
Keys and the chime can be changed under **Settings**. The keys are grabbed
system-wide while the tool runs, so the game won't see them.

### F8 vs F9

- **F8** only restores Zirian. The world stays as it is now: cutscenes you
  have seen, enemies you killed and chests you opened stay that way. Within
  the same level it is instant.
- **F9** also rewinds the world: story progress, unlocks and upgrades, and
  every level's record of which cutscenes, dialogues, chests, shards,
  enemies and doors are done. It reloads the level (a couple of seconds) so
  everything re-reads that record, then warps you. Use it for tricks that
  only work before something has been triggered.

### Loading a state from another level

The game has to load that level first, so this takes a few seconds. The tool
points one of the current level's own exits at the target level and steps
you into it, so the game does its normal level load, then warps you.

If no exit in the current level can be used, F8 falls back to the main menu:
exit to the main menu, the tool swaps in the save file it kept with the state
(your current save is backed up to `Backups\` first), then pick **Continue**.
That route also rewinds progress to the game's last save before the state was
made. **Retry does not work for this**, it only respawns you in the current
level. Pressing the load key again cancels a pending load.

## Install

**Exe:** download the zip from the
[Releases](https://github.com/Zyrumi/duskfade-savestates/releases) page,
extract it anywhere, run `Duskfade Save States.exe` while the game is
running. Windows SmartScreen may warn about an unknown publisher; choose
"More info" then "Run anyway".

**From source:** Python 3.10+ on Windows, no extra packages. Run
`python savestate_app.py` (or `run_savestates.bat`).

Everything the tool creates (slots, settings, kept saves, backups, log) is
stored next to it.

## Known limits

- A few levels may have no usable exit (for example arenas). There F9 stops
  with a message and F8 uses the main-menu route.
- `AncientTemple1_GB` has a name too long for any exit's text space seen so
  far, so it always uses the main-menu route.
- Mana: the value is restored right away, but the gauge graphic only redraws
  the next time the game updates it (switching gadgets does it).
- F9 hides entries the game added after your F5 by renaming them (first
  letter becomes `~`) instead of deleting them, which would be unsafe from
  outside the game. These dead entries are harmless but end up in your save
  file and accumulate slowly with heavy F9 use.
- F9 is exact when the game is on the same playthrough as the state (or
  later). After loading an unrelated or earlier save, things the state had
  done that the loaded save never recorded show up as not done.
- Built and tested against the current Steam build. A game update may break
  it until it's re-checked.

## Reporting problems

Open an [issue](https://github.com/Zyrumi/duskfade-savestates/issues) with:

1. Which level you were in, and the level of the state you loaded.
2. Which key you pressed and what happened (the tool's status line text helps).
3. The `savestates.log` file from the tool's folder.

## How it works

No mods, no DLL injection. The tool reads Unreal Engine's own reflection data
from outside the game process (signature scan for `GWorld` and the name
table, then walking class/property metadata), so every value is found by its
real in-game name: the player's capsule and movement component, the HUD's
mana material parameter, the game's live save object (`LevelsState`, the
per-level actor table), and the level exits (`E_CambioNIvel_C`). Restoring
writes those values back, using the engine's own `PendingLaunchVelocity` to
make the movement system take a real step so the character and camera catch
up.

`dev/` holds the research scripts used to find all this (field dumps,
before/after memory diffs).

## License

GPL-3.0, same as [duskfade-save-tools](https://github.com/Zyrumi/duskfade-save-tools),
which `gworld.py`, `gvas_lite.py` and `angled_button.py` come from.
