"""Where the tool keeps its files: next to the script, or next to the exe
when packaged (a PyInstaller --onefile exe's __file__ points into a temp
folder that is wiped after every run)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent

DEFAULT_SAVE_DIR = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) \
    / "Duskfade" / "Saved" / "SaveGames"
