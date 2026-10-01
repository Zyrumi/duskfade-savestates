"""
Save-file side of loading. Each save state keeps a copy of the game's live
save from the moment it was taken; the main-menu fallback route swaps that
copy back in (after backing up the slot), and the game loads it on Continue.
"""
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import gvas_lite
from paths import APP_DIR, DEFAULT_SAVE_DIR

SAVES_DIR = APP_DIR / "saves"
BACKUPS_DIR = APP_DIR / "Backups"
CONFIG_FILE = APP_DIR / "savestate_config.json"
SLOT_PATTERN = "DFSlot_*.sav"
BACKUPS_KEPT = 30


def save_dir() -> Path:
    """The game's save folder; can be overridden with "save_dir" in
    savestate_config.json for unusual installs."""
    try:
        custom = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("save_dir")
    except (OSError, ValueError):
        custom = None
    return Path(custom) if custom else DEFAULT_SAVE_DIR


def atomic_copy(src: Path, dest: Path) -> None:
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.copy2(src, tmp)
    tmp.replace(dest)


def active_slot() -> Path | None:
    """The slot the game is playing on: the most recently written one."""
    slots = sorted(save_dir().glob(SLOT_PATTERN), key=lambda p: p.stat().st_mtime, reverse=True)
    return slots[0] if slots else None


def backup(slot: Path) -> Path:
    """Copies the slot into Backups\\<slot>\\<timestamp>.sav, keeping the newest few."""
    folder = BACKUPS_DIR / slot.stem
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{datetime.now():%Y-%m-%d_%H-%M-%S}_before_savestate.sav"
    shutil.copy2(slot, dest)
    for old in sorted(folder.glob("*.sav"), key=lambda p: p.stat().st_mtime, reverse=True)[BACKUPS_KEPT:]:
        old.unlink(missing_ok=True)
    return dest


def snapshot(tag: str) -> dict | None:
    """Copies the live save next to the state. Returns what to store in the
    state, or None if there's no save to copy."""
    src = active_slot()
    if src is None:
        return None
    SAVES_DIR.mkdir(exist_ok=True)
    dest = SAVES_DIR / f"{tag}.sav"
    atomic_copy(src, dest)
    try:
        level = gvas_lite.read_summary(dest).last_level_player
    except Exception:  # noqa: BLE001 -- an unreadable save just means no level check
        level = None
    return {"file": dest.name, "slot": src.name, "level": level}


def swap_in(info: dict) -> Path:
    """Backs up the slot, then writes the state's save over it."""
    src = SAVES_DIR / info["file"]
    if not src.exists():
        raise FileNotFoundError(f"The stored save {src.name} is missing.")
    dest = save_dir() / info["slot"]
    if dest.exists():
        backup(dest)
    atomic_copy(src, dest)
    return dest


def new_tag() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"


def delete(info: dict | None) -> None:
    if info:
        (SAVES_DIR / info["file"]).unlink(missing_ok=True)


def arrival_door(info: dict | None, level: str) -> str | None:
    """The door the stored save says the player entered `level` through,
    used as the arrival point for a menu-less level change."""
    if not info or info.get("level") != level:
        return None
    try:
        return gvas_lite.read_summary(SAVES_DIR / info["file"]).last_door
    except Exception:  # noqa: BLE001
        return None
