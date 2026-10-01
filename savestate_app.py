"""
Duskfade Save States: save your exact spot (position, facing, camera,
momentum, health, mana, potions) and warp back to it with a hotkey.

Global hotkeys work while the game has focus. Practice tool only: it
writes to the running game's memory and never touches save files.
"""
from __future__ import annotations

import ctypes
import json
import logging
import logging.handlers
import queue
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import ttk

import chimes
import savefiles
import state
import travel
import world_state
import ue_mem
import gworld
from angled_button import AngledButton
from paths import APP_DIR

STATES_FILE = APP_DIR / "states.json"
LOG_FILE = APP_DIR / "savestates.log"
CONFIG_FILE = APP_DIR / "savestate_config.json"

DUSK = "#1b1626"
PANEL = "#251f33"
PANEL_RAISED = "#2c2438"
EDGE = "#3c3350"
AMBER = "#e8935a"
TEAL = "#5fc9c0"
TEAL_DIM = "#3d8f88"
INK = "#f0e6d8"
INK_MID = "#c7bcd4"
INK_DIM = "#9184a3"
ROSE = "#e07a8a"

VERSION = "0.1.0"
# After a level change, wait this long once the player exists before warping,
# so the level's own setup (which resets health etc.) has run. Recordings show
# nothing moves the player after spawn, so this is short; the guard below
# catches a level that teleports the player afterwards anyway.
SETTLE_S = 0.3
GUARD_S = 1.5          # watch this long after a post-load warp
GUARD_JUMP = 400.0     # units between two checks that only a teleport covers
GUARD_REWARPS = 2

ACTIONS = {
    "save": "Save state",
    "load": "Load state",
    "reset": "Full reset load",
    "prev": "Previous slot",
    "next": "Next slot",
}
DEFAULT_KEYS = {"save": "F5", "load": "F8", "reset": "F9", "prev": "F6", "next": "F7"}
KEY_CHOICES = [f"F{i}" for i in range(1, 13)]

user32 = ctypes.WinDLL("user32", use_last_error=True)
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000


log = logging.getLogger("savestates")


def resource(name: str) -> Path:
    """Bundled read-only files: inside the exe's temp folder when packaged."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def setup_logging() -> None:
    """savestates.log next to the tool: what testers attach to bug reports."""
    handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


class HotkeyThread(threading.Thread):
    """Registers global hotkeys and forwards presses to a queue."""

    def __init__(self, keys: dict[str, str], out: queue.Queue):
        super().__init__(daemon=True)
        self.keys = keys
        self.out = out
        self.failed: list[str] = []
        self.ready = threading.Event()
        self.tid = None

    def run(self):
        self.tid = ctypes.windll.kernel32.GetCurrentThreadId()
        ids = {}
        for i, (action, key) in enumerate(self.keys.items(), start=1):
            vk = 0x70 + int(key[1:]) - 1
            if user32.RegisterHotKey(None, i, MOD_NOREPEAT, vk):
                ids[i] = action
            else:
                self.failed.append(key)
        self.ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in ids:
                self.out.put(ids[msg.wParam])
        for i in ids:
            user32.UnregisterHotKey(None, i)

    def stop(self):
        if self.tid:
            user32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)


class App(tk.Tk):
    COLUMNS = ("slot", "level", "health", "mana", "potions", "saved")

    def __init__(self):
        super().__init__()
        self.title(f"Duskfade Save States {VERSION} (beta)")
        try:
            self.iconbitmap(str(resource("savestates.ico")))
        except tk.TclError:
            pass
        self.geometry("740x440")
        self.cfg = load_json(CONFIG_FILE, {})
        self.cfg["keys"] = {**DEFAULT_KEYS, **self.cfg.get("keys", {})}
        self.slots: list[dict] = load_json(STATES_FILE, [])
        self.active = min(self.cfg.get("active", 0), max(len(self.slots) - 1, 0))
        self.session: state.Session | None = None
        self.events: queue.Queue = queue.Queue()
        self.hotkeys: HotkeyThread | None = None
        # Cross-level load in progress: {"slot": name, "state": ..., "seen": t|None, "until": t}
        self.pending: dict | None = None
        # Post-load watch: {"slot", "until", "last", "pawn", "rewarps"}
        self.guard: dict | None = None

        chimes.ensure_sounds()
        self._apply_theme()
        self._build()
        self._start_hotkeys()
        self._refresh()
        self.after(50, self._pump)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ---------- UI ----------

    def _apply_theme(self):
        self.configure(bg=DUSK)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=DUSK, foreground=INK, font=("Segoe UI", 10))
        style.configure("TFrame", background=DUSK)
        style.configure("TLabel", background=DUSK, foreground=INK)
        style.configure("Dim.TLabel", background=DUSK, foreground=INK_DIM)
        style.configure("Title.TLabel", background=DUSK, foreground=AMBER, font=("Segoe UI", 15, "bold"))
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=INK,
                        bordercolor=EDGE, borderwidth=0, rowheight=26)
        style.map("Treeview", background=[("selected", TEAL_DIM)], foreground=[("selected", DUSK)])
        style.configure("Treeview.Heading", background=PANEL_RAISED, foreground=TEAL, bordercolor=EDGE,
                        relief="flat", font=("Segoe UI", 10, "bold"))
        style.map("Treeview.Heading", background=[("active", EDGE)])
        style.configure("TCombobox", fieldbackground=PANEL_RAISED, background=PANEL_RAISED, foreground=INK,
                        arrowcolor=TEAL, bordercolor=EDGE)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL_RAISED)], foreground=[("readonly", INK)])
        self.option_add("*TCombobox*Listbox.background", PANEL_RAISED)
        self.option_add("*TCombobox*Listbox.foreground", INK)
        style.configure("TEntry", fieldbackground=PANEL_RAISED, foreground=INK, insertcolor=INK, bordercolor=EDGE)
        style.configure("Vertical.TScrollbar", background=PANEL_RAISED, troughcolor=PANEL, bordercolor=EDGE,
                        arrowcolor=TEAL, lightcolor=PANEL_RAISED, darkcolor=PANEL_RAISED)
        style.map("Vertical.TScrollbar", background=[("active", EDGE)])

    def _build(self):
        head = ttk.Frame(self, padding=(14, 12, 14, 4))
        head.pack(fill="x")
        ttk.Label(head, text="Duskfade Save States", style="Title.TLabel").pack(side="left")
        self.keys_label = ttk.Label(head, style="Dim.TLabel")
        self.keys_label.pack(side="right")

        # Pack the fixed-height parts (buttons, status) before the list, so
        # when the window shrinks it's the list that gives up space.
        bar = tk.Frame(self, bg=PANEL, padx=10, pady=8)
        bar.pack(fill="x", side="bottom")
        for text, cmd, style, w in (("Save", lambda: self._do("save"), "primary", 80),
                                    ("Load", lambda: self._do("load"), "primary", 80),
                                    ("Full reset", lambda: self._do("reset"), "primary", 100),
                                    ("New slot", self._new_slot, "secondary", 90),
                                    ("Rename", self._rename, "secondary", 80),
                                    ("Delete", self._delete, "secondary", 80)):
            AngledButton(bar, text, command=cmd, style=style, width=w, height=30, bg=PANEL).pack(side="left", padx=4)
        AngledButton(bar, "Settings", command=self._hotkey_dialog, width=90, height=30, bg=PANEL).pack(side="right", padx=4)

        # Status line: symbol + text, so state never relies on colour alone.
        self.status = tk.Label(self, anchor="w", justify="left", bg=DUSK, fg=INK_MID, font=("Segoe UI", 10),
                               padx=14, pady=4)
        self.status.pack(fill="x", side="bottom")
        self.status.bind("<Configure>", lambda e: self.status.configure(wraplength=max(200, e.width - 28)))

        body = ttk.Frame(self, padding=(14, 4))
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=self.COLUMNS, show="headings", selectmode="browse", height=3)
        heads = {"slot": "Slot", "level": "Level", "health": "Health", "mana": "Mana",
                 "potions": "Potions", "saved": "Saved"}
        widths = {"slot": 170, "level": 150, "health": 70, "mana": 60, "potions": 65, "saved": 80}
        for col in self.COLUMNS:
            self.tree.heading(col, text=heads[col])
            self.tree.column(col, width=widths[col], minwidth=50,
                             anchor="w" if col in ("slot", "level") else "center")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _e: self._rename())

        # Never narrower than the button row; tall enough for a few slots.
        self.update_idletasks()
        self.minsize(bar.winfo_reqwidth(), head.winfo_reqheight() + bar.winfo_reqheight() + 150)

    def _set_status(self, text: str, kind: str = "info"):
        log.log(logging.WARNING if kind in ("warn", "error") else logging.INFO, "status[%s] %s", kind, text)
        sym, color = {"ok": ("✔", TEAL), "error": ("✖", ROSE), "warn": ("!", AMBER), "info": ("•", INK_MID)}[kind]
        self.status.configure(text=f"{sym}  {text}", fg=color)

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        for i, slot in enumerate(self.slots):
            st = slot.get("state")
            marker = "▶ " if i == self.active else "   "
            if st:
                stats = st.get("stats", {})
                hp = stats.get("pawn.Heath")
                mana = stats.get("HUD.MaterialMagicBar:Porcentage")
                row = (marker + slot["name"], st.get("world", "?"),
                       f"{hp:.0f}" if hp is not None else "-",
                       f"{mana * 100:.0f}%" if mana is not None else "-",
                       stats.get("pawn.PocionesActuales", "-"),
                       time.strftime("%H:%M:%S", time.localtime(st.get("time", 0))))
            else:
                row = (marker + slot["name"], "(empty)", "", "", "", "")
            self.tree.insert("", "end", iid=str(i), values=row)
        if self.slots:
            self.tree.selection_set(str(self.active))
            self.tree.see(str(self.active))
        k = self.cfg["keys"]
        self.keys_label.configure(text=f"{k['save']} save   {k['load']} load   {k['reset']} full reset   "
                                       f"{k['prev']}/{k['next']} slot")

    def _on_select(self, _e):
        sel = self.tree.selection()
        if sel and int(sel[0]) != self.active:
            self.active = int(sel[0])
            self._persist()
            self._refresh()

    def _persist(self):
        self.cfg["active"] = self.active
        save_json(CONFIG_FILE, self.cfg)
        save_json(STATES_FILE, self.slots)

    # ---------- slot management ----------

    def _new_slot(self):
        n = 1
        names = {s["name"] for s in self.slots}
        while f"Slot {n}" in names:
            n += 1
        self.slots.append({"name": f"Slot {n}", "state": None})
        self.active = len(self.slots) - 1
        self._persist()
        self._refresh()

    def _rename(self):
        if not self.slots:
            return
        slot = self.slots[self.active]
        win = tk.Toplevel(self, bg=DUSK, padx=14, pady=12)
        win.title("Rename slot")
        win.transient(self)
        ttk.Label(win, text="Slot name").pack(anchor="w")
        var = tk.StringVar(value=slot["name"])
        entry = ttk.Entry(win, textvariable=var, width=32)
        entry.pack(pady=6)
        entry.select_range(0, "end")
        entry.focus_set()

        def ok(_e=None):
            name = var.get().strip()
            if name:
                slot["name"] = name
                self._persist()
                self._refresh()
            win.destroy()

        entry.bind("<Return>", ok)
        entry.bind("<Escape>", lambda _e: win.destroy())
        AngledButton(win, "Rename", command=ok, style="primary", width=100, height=30).pack(anchor="e")

    def _delete(self):
        if not self.slots:
            return
        name = self.slots[self.active]["name"]
        savefiles.delete(self.slots[self.active].get("save"))
        del self.slots[self.active]
        self.active = max(0, min(self.active, len(self.slots) - 1))
        self._persist()
        self._refresh()
        self._set_status(f"Deleted {name}.")

    def _cycle(self, step: int):
        if not self.slots:
            self._new_slot()
        self.active = (self.active + step) % len(self.slots)
        self._persist()
        self._refresh()
        self._sound("slot")
        self._set_status(f"Active slot: {self.slots[self.active]['name']}")

    # ---------- game actions ----------

    def _get_session(self) -> state.Session:
        pid = gworld.find_pid(ue_mem.EXE)
        if pid is None:
            self.session = None
            raise ue_mem.AttachError("Duskfade isn't running.")
        if self.session is None or self.session.g.pid != pid:
            self._set_status("Connecting to the game...")
            self.update_idletasks()
            self.session = state.Session()
        return self.session

    def _do(self, action: str):
        if action in ("prev", "next"):
            self._cycle(-1 if action == "prev" else 1)
            return
        log.info("action %s, slot %s", action, self.slots[self.active]["name"] if self.slots else None)
        try:
            sess = self._get_session()
            if action == "save":
                if not self.slots:
                    self.slots.append({"name": "Slot 1", "state": None})
                    self.active = 0
                slot = self.slots[self.active]
                slot["state"] = sess.capture()
                slot["world"] = world_state.capture(sess.g, sess.g.player()["gi"])
                savefiles.delete(slot.get("save"))
                slot["save"] = savefiles.snapshot(savefiles.new_tag())
                self._persist()
                self._refresh()
                self._sound("save")
                self._set_status(f"Saved {slot['name']} in {slot['state']['world']}.", "ok")
            else:
                slot = self.slots[self.active] if self.slots else None
                if not slot or not slot.get("state"):
                    raise ue_mem.AttachError("That slot is empty. Save a state first.")
                self.guard = None
                if self.pending and self.pending["slot"] == slot["name"]:
                    self.pending = None
                    self._sound("slot")
                    self._set_status("Cancelled the pending load.")
                    return
                self.pending = None
                here = sess.g.world_name()
                if action == "reset":
                    self._start_reset(slot, here)
                elif here == slot["state"]["world"]:
                    self._restore(sess, slot)
                else:
                    self._start_level_swap(slot, here)
        except (ue_mem.AttachError, KeyError) as e:
            self._sound("error")
            self._set_status(str(e).strip("'\""), "error")
        except Exception as e:  # noqa: BLE001 -- a stale session after a level load etc.
            log.exception("action %s failed", action)
            self.session = None
            self._sound("error")
            self._set_status(f"Couldn't read the game right now ({e.__class__.__name__}). Try again in a moment.",
                             "error")

    def _restore(self, sess: state.Session, slot: dict):
        log.info("warp to %s in %s", [round(c) for c in slot["state"]["location"]], slot["state"]["world"])
        warnings = sess.restore(slot["state"])
        self._sound("load")
        if warnings:
            self._set_status(" ".join(warnings), "warn")
        else:
            self._set_status(f"Loaded {slot['name']}.", "ok")

    def _start_level_swap(self, slot: dict, here: str | None):
        """The state is in another level. First choice: repoint one of this
        level's own exits at it and step into the trigger, so the game loads
        it normally (no menu, progress untouched). If no exit can be used,
        fall back to the main-menu save swap."""
        target = slot["state"]["world"]
        info = slot.get("save")
        base = {"slot": slot["name"], "state": slot["state"], "save": info, "seen": None, "t0": time.time(),
                "wrong_since": None, "until": time.time() + 900}
        sess = self._get_session()
        exits = []
        if here and here != gworld.MENU_WORLD_NAME:
            try:
                exits = travel.find_exits(sess.g, sess.g.uworld(), target)
            except Exception:  # noqa: BLE001 -- odd level layout: use the menu route
                exits = []
        if exits:
            self.pending = {**base, "mode": "door", "exits": exits, "idx": -1, "origin": sess.g.uworld(),
                            "left": False,
                            "door": savefiles.arrival_door(info, target)}
            self._next_exit()
            return
        self._start_menu_swap(base, here)

    def _start_reset(self, slot: dict, here: str | None):
        """Full reset: put the live save object (story progress, unlocks,
        every level's actor table) back to the snapshot, reload the state's
        level through an exit so its actors re-read that table, then warp."""
        snap = slot.get("world")
        target = slot["state"]["world"]
        if not snap:
            raise ue_mem.AttachError("That state was saved before full reset existed. Save it again to enable F9.")
        if not here or here == gworld.MENU_WORLD_NAME:
            raise ue_mem.AttachError("Full reset works from inside a level, not the menu.")
        sess = self._get_session()
        exits = travel.find_exits(sess.g, sess.g.uworld(), target)
        if not exits:
            raise ue_mem.AttachError(f"No exit in {here} can be pointed at {target}. Walk to another area and try again.")
        player = sess.g.player()
        changed = world_state.restore(sess.g, player["gi"], snap)
        changed["character"] = world_state.restore_pawn(sess.g, player["pawn"], snap)
        log.info("full reset %s -> %s: %s, %d usable exits", here, target, changed, len(exits))
        self.pending = {"slot": slot["name"], "state": slot["state"], "save": slot.get("save"), "seen": None,
                        "t0": time.time(),
                        "wrong_since": None, "until": time.time() + 900, "mode": "door", "exits": exits, "idx": -1,
                        "origin": sess.g.uworld(), "left": False, "world_snap": snap,
                        "gi": sess.g.player()["gi"], "door": savefiles.arrival_door(slot.get("save"), target)}
        self._next_exit()
        self._set_status(f"Rewinding and reloading {target}...")

    def _next_exit(self):
        p = self.pending
        sess = self.session
        if p["idx"] >= 0:
            p["exits"][p["idx"]].undo()
        p["idx"] += 1
        if p["idx"] >= len(p["exits"]) and p.get("world_snap"):
            self.pending = None
            raise ue_mem.AttachError("None of this level's exits would fire. The rewind is already in memory, so "
                                     "going through any door will show it; then press F8 to warp.")
        if p["idx"] >= len(p["exits"]):
            self._start_menu_swap(p, sess.g.world_name(), note="None of this level's exits would go. ")
            return
        ex = p["exits"][p["idx"]]
        log.info("trying exit %s (trigger %s), door %s", self.session.g.obj_name(ex.event),
                 self.session.g.obj_name(ex.trigger), p.get("door"))
        if not ex.aim(p["state"]["world"], p["door"]):
            self._next_exit()
            return
        here = sess.capture()
        here.update(location=ex.location(), velocity=[0.0, 0.0, 0.0], movement_mode=1, stats={})
        try:
            sess.restore(here)
        except Exception:
            ex.undo()
            self.pending = None
            raise
        p["attempt_at"] = time.time()
        self._sound("slot")
        self._set_status(f"Travelling to {p['state']['world']}...")

    def _start_menu_swap(self, base: dict, here: str | None, note: str = ""):
        info = base.get("save")
        target = base["state"]["world"]
        if not info:
            self.pending = None
            raise ue_mem.AttachError(f"{note}That state is from {target} and has no save file attached. "
                                     "Save it again in that level to enable loading it from the menu.")
        self.pending = {**base, "mode": "menu", "swapped": False}
        if here == gworld.MENU_WORLD_NAME:
            self._check_pending()
        else:
            self._set_status(f"{note}Exit to the main menu and the {target} save gets swapped in.")

    def _check_pending(self):
        p = self.pending
        if not p:
            return
        now = time.time()
        if now > p["until"]:
            self.pending = None
            self._set_status("Gave up waiting for the level to load. Press load again to retry.", "warn")
            return
        target = p["state"]["world"]
        try:
            sess = self._get_session()
            sess._fresh()
            world = sess.g.world_name()
        except Exception:  # noqa: BLE001 -- loading screens, game restarting
            p["seen"] = None
            return
        if p["mode"] == "door":
            w = sess.g.uworld()
            if w != p["origin"]:
                p["left"] = True
                self._phase(p, "old level gone")
            arrived = p["left"] and w and world == target
            if p.get("world_snap") and not arrived:
                # Until the new level exists, keep the snapshot in place so
                # nothing the old level writes while unloading survives.
                try:
                    world_state.restore(sess.g, p["gi"], p["world_snap"])
                    if not p["left"]:
                        world_state.restore_pawn(sess.g, sess.g.player()["pawn"], p["world_snap"])
                except Exception:  # noqa: BLE001 -- mid-load reads can fail
                    pass
            if not p["left"]:
                if time.time() - p["attempt_at"] > 5:
                    try:
                        self._next_exit()
                    except ue_mem.AttachError as e:
                        self._sound("error")
                        self._set_status(str(e), "error")
                return
            if not w or not world:
                return  # loading
            self._phase(p, f"new level up ({world})")
            if world != target:
                p["wrong_since"] = p["wrong_since"] or now
                if now - p["wrong_since"] < 8:
                    return  # maybe a transition map on the way
                self.pending = None
                self._sound("error")
                self._set_status(f"The exit took you to {world} instead of {target}. Press load to try again.",
                                 "error")
                return
        if world == gworld.MENU_WORLD_NAME:
            p["seen"] = p["wrong_since"] = None
            if not p["swapped"]:
                try:
                    savefiles.swap_in(p["save"])
                except Exception as e:  # noqa: BLE001
                    self.pending = None
                    self._sound("error")
                    self._set_status(f"Couldn't swap the save in ({e}).", "error")
                    return
                p["swapped"] = True
                self._sound("save")
                self._set_status(f"{target} save is in place (your old one is backed up). Pick Continue.", "ok")
            return
        if p["mode"] == "menu" and not p["swapped"]:
            return
        if world != target:
            # Continue landed somewhere else; going back to the menu re-swaps.
            p["seen"] = None
            p["wrong_since"] = p["wrong_since"] or now
            if now - p["wrong_since"] > 5:
                p["swapped"] = False
                where = p["save"].get("level") or "another level"
                self._set_status(f"The save loaded {world} instead of {target} (it points at {where}). "
                                 "Exit to the menu to try again, or press load to cancel.", "warn")
            return
        try:
            sess.g.player()
        except Exception:  # noqa: BLE001 -- player not spawned yet
            p["seen"] = None
            return
        # Let the level finish spawning the player and running its own setup
        # (which resets health etc.) before writing over it.
        if p["seen"] is None:
            p["seen"] = now
            self._phase(p, "player spawned")
        elif now - p["seen"] >= SETTLE_S:
            self.pending = None
            if p.get("world_snap"):
                # The new level may have loaded values the exit's save copied
                # in; put the snapshot's values back (no entries hidden now).
                try:
                    player = sess.g.player()
                    world_state.restore(sess.g, player["gi"], p["world_snap"], orphan=False)
                    world_state.restore_pawn(sess.g, player["pawn"], p["world_snap"])
                except Exception:  # noqa: BLE001
                    pass
            slot = next((s for s in self.slots if s["name"] == p["slot"]), {"name": p["slot"], "state": p["state"]})
            try:
                self._restore(sess, slot)
                self._phase(p, "warped")
                self._start_guard(sess, slot)
            except Exception as e:  # noqa: BLE001
                log.exception("warp after level load failed")
                self._sound("error")
                self._set_status(f"Level loaded but the warp failed ({e}). Press load again.", "error")

    def _player_spot(self, sess: state.Session) -> tuple[int, list[float]]:
        pl = sess.g.player()
        root = pl["root"]
        return pl["pawn"], sess.g.read_value(root, sess.g.find_field(root, "RelativeLocation"))

    def _start_guard(self, sess: state.Session, slot: dict):
        pawn, loc = self._player_spot(sess)
        self.guard = {"slot": slot, "until": time.time() + GUARD_S, "last": loc, "pawn": pawn, "rewarps": 0}

    def _check_guard(self):
        """Right after a post-load warp: if the level teleports the player
        (spawn logic running late), warp them back."""
        gd = self.guard
        if not gd or time.time() > gd["until"]:
            self.guard = None
            return
        try:
            sess = self._get_session()
            pawn, loc = self._player_spot(sess)
        except Exception:  # noqa: BLE001
            return
        jump = sum((a - b) ** 2 for a, b in zip(loc, gd["last"])) ** 0.5
        gd["last"] = loc
        if pawn != gd["pawn"] or jump > GUARD_JUMP:
            if gd["rewarps"] >= GUARD_REWARPS:
                self.guard = None
                return
            gd["rewarps"] += 1
            log.info("guard: player moved %.0f units (pawn changed: %s), warping again", jump, pawn != gd["pawn"])
            try:
                self._restore(sess, gd["slot"])
                gd["pawn"], gd["last"] = self._player_spot(sess)
            except Exception:  # noqa: BLE001
                log.exception("guard re-warp failed")

    @staticmethod
    def _phase(p: dict, name: str) -> None:
        """Logs each loading phase once, with time since the key press."""
        done = p.setdefault("phases", set())
        if name not in done:
            done.add(name)
            log.info("phase +%.2fs %s", time.time() - p.get("t0", time.time()), name)

    def _sound(self, name: str):
        if self.cfg.get("sound", True):
            chimes.play(name)

    def _pump(self):
        try:
            while True:
                self._do(self.events.get_nowait())
        except queue.Empty:
            pass
        now = time.monotonic()
        if self.guard and now - getattr(self, "_last_guard_check", 0) > 0.05:
            self._last_guard_check = now
            self._check_guard()
        interval = 0.02 if self.pending and self.pending.get("mode") == "door" else 0.3
        if self.pending and now - getattr(self, "_last_pending_check", 0) > interval:
            self._last_pending_check = now
            self._check_pending()
        self.after(30, self._pump)

    # ---------- hotkeys ----------

    def _start_hotkeys(self):
        if self.hotkeys:
            self.hotkeys.stop()
            self.hotkeys.join(timeout=1)
        self.hotkeys = HotkeyThread(dict(self.cfg["keys"]), self.events)
        self.hotkeys.start()
        self.hotkeys.ready.wait(2)
        if self.hotkeys.failed:
            self._set_status(f"Couldn't grab {', '.join(self.hotkeys.failed)} (another program has it). "
                             "Pick different keys under Settings.", "warn")
        else:
            self._set_status("Ready. Hotkeys work while the game has focus.")

    def _hotkey_dialog(self):
        win = tk.Toplevel(self, bg=DUSK, padx=16, pady=12)
        win.title("Settings")
        win.transient(self)
        vars_ = {}
        for r, (action, label) in enumerate(ACTIONS.items()):
            ttk.Label(win, text=label).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12))
            v = tk.StringVar(value=self.cfg["keys"][action])
            ttk.Combobox(win, textvariable=v, values=KEY_CHOICES, state="readonly", width=6).grid(row=r, column=1)
            vars_[action] = v
        sound_var = tk.BooleanVar(value=self.cfg.get("sound", True))
        tk.Checkbutton(win, text="Play a chime on save/load", variable=sound_var, bg=DUSK, fg=INK,
                       selectcolor=PANEL_RAISED, activebackground=DUSK, activeforeground=INK,
                       command=lambda: sound_var.get() and chimes.play("save")).grid(
            row=len(ACTIONS), column=0, columnspan=2, sticky="w", pady=(8, 0))
        msg = ttk.Label(win, style="Dim.TLabel")
        msg.grid(row=len(ACTIONS) + 2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        def ok():
            keys = {a: v.get() for a, v in vars_.items()}
            if len(set(keys.values())) != len(keys):
                msg.configure(text="Each action needs its own key.")
                return
            self.cfg["keys"] = keys
            self.cfg["sound"] = sound_var.get()
            self._persist()
            self._start_hotkeys()
            self._refresh()
            win.destroy()

        AngledButton(win, "Save keys", command=ok, style="primary", width=100, height=30).grid(
            row=len(ACTIONS) + 3, column=1, sticky="e", pady=(10, 0))

    def _close(self):
        if self.hotkeys:
            self.hotkeys.stop()
        self.destroy()


if __name__ == "__main__":
    setup_logging()
    log.info("started, version %s", VERSION)
    try:
        App().mainloop()
    except Exception:
        log.exception("crashed")
        raise
