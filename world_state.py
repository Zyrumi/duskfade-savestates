"""
Snapshot of the game's live save object (GameInstance.SaveGame): story
progress, unlocks, and LevelsState, the per-level table of every
interactive actor's state (cutscene/dialogue triggers, chests, coins,
enemies...). Levels read this table when they load, so writing a snapshot
back and reloading the level puts the world back the way it was.
"""
from __future__ import annotations

import ue_mem

SCALAR_MAP_KINDS = {"StrProperty", "ByteProperty", "IntProperty", "NameProperty"}
# GameInstance fields that mirror story progress (the rest are settings).
GI_FIELDS = ("MomentoHistoria", "TrozosColocados", "SistemaDiaNoche")
ARRAY_INNER = 0x78
ARRAY_ELEM = {"BoolProperty": 1, "ByteProperty": 1, "EnumProperty": 1, "IntProperty": 4}
ORPHAN_CHAR = "~"


def _key(g: ue_mem.Game, kind: str, addr: int):
    if kind == "StrProperty":
        return g.fstring(addr)
    if kind == "NameProperty":
        return g.fname(addr)
    if kind == "IntProperty":
        return g.i32(addr)
    b = g.read(addr, 1)
    return b[0] if b else None


def save_object(g: ue_mem.Game, gi: int) -> int:
    return g.get_obj(gi, "SaveGame")


def capture(g: ue_mem.Game, gi: int) -> dict:
    sg = save_object(g, gi)
    out = {"scalars": {}, "maps": {}, "levels": {}, "arrays": {}, "gi": {}}
    for name in GI_FIELDS:
        f = g.find_field(gi, name)
        if f and g.is_scalar(f):
            out["gi"][name] = g.read_value(gi, f)
    for _c, f in g.all_fields(sg):
        if not _c.endswith("_C"):
            continue
        if g.is_scalar(f):
            out["scalars"][f["name"]] = g.read_value(sg, f)
        elif f["kind"] == "ArrayProperty":
            inner = g._field_class_name(g.ptr(f["addr"] + ARRAY_INNER))
            data, num = g.tarray(sg + f["offset"])
            if inner in ARRAY_ELEM and data and 0 < num < 4096:
                out["arrays"][f["name"]] = g.read(data, num * ARRAY_ELEM[inner]).hex()
        elif f["kind"] == "MapProperty":
            kp, vp = g.map_props(f)
            entries = g.map_entries(sg + f["offset"], f)
            if f["name"] == "LevelsState":
                inner = g.own_fields(vp["struct_ptr"])[0]
                for k, v in entries:
                    level = g.fstring(k)
                    out["levels"][level] = {g.fstring(ik): g.i32(iv)
                                            for ik, iv in g.map_entries(v + inner["offset"], inner)}
            elif kp["kind"] in SCALAR_MAP_KINDS and vp["kind"] in ("ByteProperty", "IntProperty"):
                read_v = g.i32 if vp["kind"] == "IntProperty" else (lambda a: (g.read(a, 1) or b"\0")[0])
                out["maps"][f["name"]] = {str(_key(g, kp["kind"], k)): read_v(v) for k, v in entries}
    return out


def diff(a: dict, b: dict) -> list[str]:
    lines = []
    for k in sorted(set(a["scalars"]) | set(b["scalars"])):
        if a["scalars"].get(k) != b["scalars"].get(k):
            lines.append(f"{k}: {a['scalars'].get(k)} -> {b['scalars'].get(k)}")
    for m in sorted(set(a["maps"]) | set(b["maps"])):
        x, y = a["maps"].get(m, {}), b["maps"].get(m, {})
        for k in sorted(set(x) | set(y)):
            if x.get(k) != y.get(k):
                lines.append(f"{m}[{k}]: {x.get(k)} -> {y.get(k)}")
    for lvl in sorted(set(a["levels"]) | set(b["levels"])):
        x, y = a["levels"].get(lvl, {}), b["levels"].get(lvl, {})
        for k in sorted(set(x) | set(y)):
            if x.get(k) != y.get(k):
                lines.append(f"LevelsState[{lvl}][{k}]: {x.get(k)} -> {y.get(k)}")
    return lines


def _orphan(g: ue_mem.Game, key_addr: int) -> None:
    """Makes a map entry unfindable without unlinking it: change the first
    character of its FString key in place. Lookups by the real name then
    miss (reads as "never happened"); the dead entry is harmless."""
    b = g.read(key_addr, 8)
    data = int.from_bytes(b, "little") if b else 0
    if data:
        g.write(data, ORPHAN_CHAR.encode("utf-16-le"))


def _restore_scalar_map(g: ue_mem.Game, obj: int, f: dict, want: dict) -> int:
    """Writes values for keys that exist on both sides; returns how many changed."""
    kp, vp = g.map_props(f)
    size = 4 if vp["kind"] == "IntProperty" else 1
    changed = 0
    for k, v in g.map_entries(obj + f["offset"], f):
        key = str(_key(g, kp["kind"], k))
        if key in want:
            cur = g.i32(v) if size == 4 else (g.read(v, 1) or bytes(1))[0]
            if cur != want[key]:
                g.write(v, int(want[key]).to_bytes(size, "little", signed=size == 4))
                changed += 1
    return changed


# Save-object fields the character keeps its own copy of under another name.
PAWN_ALIASES = {"PocionesMaximas": "PocionesMax"}


def restore_pawn(g: ue_mem.Game, pawn: int, snap: dict) -> int:
    """The character keeps its own copies of unlocks/upgrades/collectibles
    and copies them INTO the save object whenever the game saves (level
    exits do), so they have to be rewound too or the old values come back.
    Returns how many values changed."""
    fields = {f["name"].lower(): f for c, f in g.all_fields(pawn) if c.endswith("_C")}
    changed = 0
    for name, val in snap["scalars"].items():
        f = fields.get(PAWN_ALIASES.get(name, name).lower())
        if f and g.is_scalar(f) and g.read_value(pawn, f) != val:
            g.write_value(pawn, f, val)
            changed += 1
    for name, hexval in snap.get("arrays", {}).items():
        f = fields.get(name.lower())
        if not f or f["kind"] != "ArrayProperty":
            continue
        want = bytes.fromhex(hexval)
        inner = g.ptr(f["addr"] + ARRAY_INNER)
        kind = g._field_class_name(inner)
        data, num = g.tarray(pawn + f["offset"])
        if not data or num != len(want):
            continue
        if kind == "BoolProperty":
            if g.read(data, num) != want:
                g.write(data, want)
                changed += 1
        elif kind == "StructProperty":
            # e.g. Struct_Habilidades {Gadget, Desbloqueada?}: the save keeps
            # only the unlocked flag per slot.
            st = g.ptr(inner + g.L.fprop_extra)
            esize = g.struct_stride(st)
            flag = next((x for x in g.own_fields(st) if x["kind"] == "BoolProperty"
                         and x["name"].startswith("Desbloqueada")), None)
            if not flag or not esize:
                continue
            for i, b in enumerate(want):
                e = data + i * esize
                if g.read_value(e, flag) != bool(b):
                    g.write_value(e, flag, bool(b))
                    changed += 1
    for name, want in snap["maps"].items():
        f = fields.get(name.lower())
        if f and f["kind"] == "MapProperty":
            changed += _restore_scalar_map(g, pawn, f, want)
    return changed


def restore(g: ue_mem.Game, gi: int, snap: dict, orphan: bool = True) -> dict:
    """Writes a capture() snapshot back into the live save object, in place.
    With orphan=False only values are written (no entries are hidden).
    Returns counts of what changed."""
    sg = save_object(g, gi)
    stats = {"values": 0, "orphaned": 0, "missing": 0}
    for name, val in snap.get("gi", {}).items():
        f = g.find_field(gi, name)
        if f and g.read_value(gi, f) != val:
            g.write_value(gi, f, val)
            stats["values"] += 1
    for _c, f in g.all_fields(sg):
        if not _c.endswith("_C"):
            continue
        name = f["name"]
        if g.is_scalar(f) and name in snap["scalars"]:
            if g.read_value(sg, f) != snap["scalars"][name]:
                g.write_value(sg, f, snap["scalars"][name])
                stats["values"] += 1
        elif f["kind"] == "ArrayProperty" and name in snap.get("arrays", {}):
            want = bytes.fromhex(snap["arrays"][name])
            data, num = g.tarray(sg + f["offset"])
            inner = g._field_class_name(g.ptr(f["addr"] + ARRAY_INNER))
            if data and num * ARRAY_ELEM.get(inner, 0) == len(want) and g.read(data, len(want)) != want:
                g.write(data, want)
                stats["values"] += 1
        elif f["kind"] == "MapProperty" and name == "LevelsState":
            _kp, vp = g.map_props(f)
            inner = g.own_fields(vp["struct_ptr"])[0]
            for k, v in g.map_entries(sg + f["offset"], f):
                level = g.fstring(k)
                if not level or level.startswith(ORPHAN_CHAR):
                    continue
                want = snap["levels"].get(level)
                if want is None:
                    if orphan:
                        _orphan(g, k)  # whole level first visited after the snapshot
                        stats["orphaned"] += 1
                    continue
                seen = set()
                for ik, iv in g.map_entries(v + inner["offset"], inner):
                    actor = g.fstring(ik)
                    if not actor or actor.startswith(ORPHAN_CHAR):
                        continue
                    seen.add(actor)
                    if actor not in want:
                        if orphan:
                            _orphan(g, ik)
                            stats["orphaned"] += 1
                    elif g.i32(iv) != want[actor]:
                        g.write(iv, int(want[actor]).to_bytes(4, "little", signed=True))
                        stats["values"] += 1
                stats["missing"] += len(set(want) - seen)
        elif f["kind"] == "MapProperty" and name in snap["maps"]:
            stats["values"] += _restore_scalar_map(g, sg, f, snap["maps"][name])
    return stats
