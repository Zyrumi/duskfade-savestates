"""
Cross-level travel without the menu: repoint one of the current level's own
exits (an E_CambioNIvel_C "change level" event, fired by a
BP_TriggerEvento_C volume) at the target level and step the player into its
trigger. The game then does its own normal level load.

Level names are FStrings, so the new name is written into the existing
buffer (never reallocated from outside); an exit only qualifies when its
buffer already has room. If nothing fits, callers fall back to the
main-menu save swap.
"""
from __future__ import annotations

import struct

import ue_mem

ULEVEL_ACTORS = 0xA0  # ULevel::Actors (not reflected); verified by finding the pawn in it
C2W_TRANSLATION = 0x200  # USceneComponent::ComponentToWorld (0x1E0) + FQuat


def level_actors(g: ue_mem.Game, world: int) -> list[int]:
    lvl = g.get_obj(world, "PersistentLevel")
    data, num = g.tarray(lvl + ULEVEL_ACTORS)
    if not data or not 0 < num < 500000:
        return []
    raw = g.read(data, num * 8) or b""
    return [a for a in struct.unpack(f"<{len(raw) // 8}Q", raw) if a]


def read_fstring(g: ue_mem.Game, addr: int) -> tuple[str, int, int, int]:
    data, num, cap = struct.unpack("<Qii", g.read(addr, 16))
    text = g.read(data, num * 2).decode("utf-16-le", "replace").rstrip("\0") if data and 0 < num <= cap else ""
    return text, data, num, cap


def write_fstring_in_place(g: ue_mem.Game, addr: int, text: str) -> bool:
    _old, data, _num, cap = read_fstring(g, addr)
    if not data or len(text) + 1 > cap:
        return False
    g.write(data, (text + "\0").encode("utf-16-le"))
    g.write(addr + 8, struct.pack("<i", len(text) + 1))
    return True


class Exit:
    def __init__(self, g, event, trigger):
        self.g, self.event, self.trigger = g, event, trigger
        self.f_level = g.find_field(event, "NombreNivel")
        self.f_door = g.find_field(event, "NombreSalida")
        self.saved: dict[str, str] = {}
        self.saved_flags: dict[str, object] = {}

    def capacity(self) -> int:
        return read_fstring(self.g, self.event + self.f_level["offset"])[3]

    def aim(self, level: str, door: str | None) -> bool:
        g = self.g
        self.saved = {"level": read_fstring(g, self.event + self.f_level["offset"])[0],
                      "door": read_fstring(g, self.event + self.f_door["offset"])[0]}
        if not write_fstring_in_place(g, self.event + self.f_level["offset"], level):
            return False
        if door:
            write_fstring_in_place(g, self.event + self.f_door["offset"], door)
        # Re-arm one-shot triggers that already fired.
        for name, value in (("Activo", True), ("Ejecutado", False)):
            fld = g.find_field(self.trigger, name)
            if fld:
                self.saved_flags[name] = g.read_value(self.trigger, fld)
                g.write_value(self.trigger, fld, value)
        return True

    def undo(self) -> None:
        g = self.g
        if self.saved:
            write_fstring_in_place(g, self.event + self.f_level["offset"], self.saved["level"])
            write_fstring_in_place(g, self.event + self.f_door["offset"], self.saved["door"])
        for name, value in self.saved_flags.items():
            g.write_value(self.trigger, g.find_field(self.trigger, name), value)

    def location(self) -> list[float]:
        g = self.g
        box = g.get_obj(self.trigger, "Box") if g.find_field(self.trigger, "Box") else 0
        comp = box or g.get_obj(self.trigger, "RootComponent")
        return list(struct.unpack("<3d", g.read(comp + C2W_TRANSLATION, 24)))


def find_exits(g: ue_mem.Game, world: int, level: str) -> list[Exit]:
    """Exits in the loaded level whose name buffer can hold `level`."""
    actors = level_actors(g, world)
    events = {a for a in actors if g.class_name(a) == "E_CambioNIvel_C"}
    out = []
    for a in actors:
        if g.class_name(a) != "BP_TriggerEvento_C":
            continue
        fld = g.find_field(a, "EventosTrigger")
        data, num = g.tarray(a + fld["offset"]) if fld else (0, 0)
        if not data or not 0 < num < 64:
            continue
        for ev in struct.unpack(f"<{num}Q", g.read(data, num * 8)):
            if ev not in events:
                continue
            wipe = g.find_field(ev, "BorrarPartida")
            if wipe and g.read_value(ev, wipe):
                continue  # this exit also deletes the save; never touch it
            ex = Exit(g, ev, a)
            if ex.f_level and ex.f_door and ex.capacity() >= len(level) + 1:
                out.append(ex)
    return out
