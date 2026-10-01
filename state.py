"""
Capture / restore a live player state: position, facing, camera, momentum
and the character's stats (energy etc.), all via ue_mem's reflection
lookups. Restores only within the same level the state was captured in.
"""
from __future__ import annotations

import math
import struct
import time

import ue_mem

# Stats restored besides the transform, as (label, path). A path is
# "<owner>.<property>" where owner is "pawn" or one of the pawn's object
# properties (e.g. "HUD"); "HUD.MaterialMagicBar:Porcentage" means a scalar
# parameter on that MaterialInstanceDynamic. Missing ones are skipped, so a
# game patch that renames one only stops restoring that one stat.
STATS: list[tuple[str, str]] = [
    ("Health", "pawn.Heath"),
    # The HUD's Tick eases its bar toward these and pushes the result into
    # the bar material itself, which is what makes the graphic redraw. So
    # write these, never the bar material directly (UE skips the redraw when
    # the game "sets" a material value that already matches).
    ("Health bar", "HUD.Salud"),
    ("Health bar", "HUD.PercentSalud"),
    ("Health bar", "HUD.PercentSaludBackground"),
    # Mana has no variable at all: the gauge material's parameter IS the
    # value (the HUD's GetMana reads it back). The graphic redraws the next
    # time the game sets it, e.g. on a gadget switch.
    ("Mana", "HUD.MaterialMagicBar:Porcentage"),
    ("Potions", "pawn.PocionesActuales"),
    ("Flight time", "pawn.TiempoVuelo"),
]

# A MaterialInstanceDynamic only stores a parameter once the game first
# sets it; until then it reads the parent material's value. For the mana
# gauge that's a full bar (zone loads reset mana to full).
PARAM_DEFAULTS = {"HUD.MaterialMagicBar:Porcentage": 1.0}

RESTORE_BURST_S = 0.12  # keep re-writing for a few frames so a mid-tick write can't be lost


def rotator_to_quat(pitch: float, yaw: float, roll: float) -> tuple[float, float, float, float]:
    """UE's FRotator::Quaternion()."""
    d = math.pi / 360.0
    sp, cp = math.sin(pitch * d), math.cos(pitch * d)
    sy, cy = math.sin(yaw * d), math.cos(yaw * d)
    sr, cr = math.sin(roll * d), math.cos(roll * d)
    return (cr * sp * sy - sr * cp * cy,
            -cr * sp * cy - sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
            cr * cp * cy + sr * sp * sy)


class Session:
    """One attach to the running game. Re-create after a game restart."""

    def __init__(self):
        self.g = ue_mem.Game()
        self._c2w_off: dict[int, int] = {}
        self._world = 0

    def _fresh(self):
        """Classes can be unloaded and their memory reused across level
        loads, so drop every cached offset whenever the world changes."""
        w = self.g.uworld()
        if w != self._world:
            self._world = w
            self._c2w_off.clear()
            self.g._fields_cache.clear()

    def _component_to_world_offset(self, comp: int) -> int | None:
        """ComponentToWorld isn't a reflected property, so find it by value:
        for a root component its translation equals RelativeLocation. It's an
        FTransform (quat, translation, scale; 16-aligned), so the match sits
        at +0x20 of a 16-aligned block right after the reflected fields."""
        g = self.g
        cls = g.obj_class(comp)
        if cls in self._c2w_off:
            return self._c2w_off[cls]
        rel_fld = g.find_field(comp, "RelativeLocation")
        rel = g.read(comp + rel_fld["offset"], 24)
        size = g.i32(cls + g.L.props_size) or 0x300
        blob = g.read(comp, max(size, 0x300) + 0x100)
        hits = []
        i = blob.find(rel)
        while i != -1:
            if i != rel_fld["offset"] and i % 16 == 0 and i >= 0x20:
                q = struct.unpack_from("<4d", blob, i - 0x20)
                scale = struct.unpack_from("<3d", blob, i + 0x20)
                if abs(sum(c * c for c in q) - 1.0) < 1e-3 and all(0.01 < s < 100 for s in scale):
                    hits.append(i - 0x20)
            i = blob.find(rel, i + 1)
        off = hits[0] if len(hits) == 1 else None
        if off is not None:
            self._c2w_off[cls] = off
        return off

    def _stat_targets(self, p: dict) -> list[tuple[str, str, object]]:
        """(path, kind, target) where kind is "field" (target=(obj, fld)) or
        "param" (target=[float addresses])."""
        g = self.g
        out = []
        for _label, path in STATS:
            owner, rest = path.split(".", 1)
            obj = p["pawn"] if owner == "pawn" else (g.get_obj(p["pawn"], owner) if g.find_field(p["pawn"], owner) else 0)
            if not obj:
                continue
            if ":" in rest:
                mid_name, param = rest.split(":", 1)
                if not g.find_field(obj, mid_name):
                    continue
                mid = g.get_obj(obj, mid_name)
                addrs = g.mid_param_addrs(mid, param) if mid else []
                if addrs:
                    out.append((path, "param", addrs))
                elif path in PARAM_DEFAULTS:
                    out.append((path, "param-default", None))
            else:
                fld = g.find_field(obj, rest)
                if fld and g.is_scalar(fld):
                    out.append((path, "field", (obj, fld)))
        return out

    def _read_stat(self, kind, target):
        if kind == "field":
            return self.g.read_value(*target)
        if kind == "param-default":
            return None
        b = self.g.read(target[0], 4)
        return struct.unpack("<f", b)[0] if b else None

    def _write_stat(self, kind, target, value):
        if kind == "field":
            self.g.write_value(target[0], target[1], value)
        elif kind == "param":
            data = struct.pack("<f", value)
            for a in target:
                self.g.write(a, data)

    def capture(self) -> dict:
        self._fresh()
        g = self.g
        p = g.player()
        root, move, pc = p["root"], p["move"], p["pc"]
        st = {
            "world": g.world_name(),
            "time": time.time(),
            "location": g.read_value(root, g.find_field(root, "RelativeLocation")),
            "rotation": g.read_value(root, g.find_field(root, "RelativeRotation")),
            "control_rotation": g.read_value(pc, g.find_field(pc, "ControlRotation")),
            "stats": {},
        }
        if move:
            st["velocity"] = g.read_value(move, g.find_field(move, "Velocity"))
            st["movement_mode"] = g.read_value(move, g.find_field(move, "MovementMode"))
        for path, kind, target in self._stat_targets(p):
            val = self._read_stat(kind, target)
            if val is None:
                val = PARAM_DEFAULTS.get(path)
            if val is not None:
                st["stats"][path] = val
        return st

    def restore(self, st: dict) -> list[str]:
        """Warps the player back and restores stats. Returns warnings about
        anything that couldn't be restored exactly."""
        self._fresh()
        g = self.g
        here = g.world_name()
        if here != st["world"]:
            raise ue_mem.AttachError(f"That state is from {st['world']}, you're in {here}.")
        p = g.player()
        root, move, pc = p["root"], p["move"], p["pc"]
        loc = st["location"]
        rot = st["rotation"]
        c2w = self._component_to_world_offset(root)
        rel_loc = g.find_field(root, "RelativeLocation")
        rel_rot = g.find_field(root, "RelativeRotation")
        ctl_rot = g.find_field(pc, "ControlRotation")
        vel = g.find_field(move, "Velocity") if move else None
        mode = g.find_field(move, "MovementMode") if move else None
        stats = [(kind, target, st["stats"][path]) for path, kind, target in self._stat_targets(p)
                 if path in st["stats"]]
        warnings = []
        for path, kind, _t in self._stat_targets(p):
            if kind == "param-default" and st["stats"].get(path, PARAM_DEFAULTS[path]) != PARAM_DEFAULTS[path]:
                label = next(lbl for lbl, pth in STATS if pth == path)
                warnings.append(f"{label} is still untouched this zone, so it stays full. Use it once, then load again.")
        if c2w is None:
            warnings.append("Couldn't find the capsule's world transform; the warp may only apply once you move.")
        # Moving the capsule by hand doesn't refresh the mesh/camera attached
        # to it; only a real movement step does. PendingLaunchVelocity is what
        # LaunchCharacter uses: on its next tick the movement component
        # switches to falling properly and moves, so everything catches up.
        # Standing states get a 2-unit lift and a tiny downward launch, which
        # just settles back onto the floor.
        v = st.get("velocity") or [0.0, 0.0, 0.0]
        grounded_or_air = st.get("movement_mode") in (1, 2, 3)
        launch_fld = g.find_field(move, "PendingLaunchVelocity") if move else None
        use_launch = grounded_or_air and launch_fld is not None
        still = sum(c * c for c in v) < 1.0
        if use_launch and still:
            loc = [loc[0], loc[1], loc[2] + 2.0]
            launch_v = [0.0, 0.0, -1.0]
        else:
            launch_v = v
        loc_bytes = struct.pack("<3d", *loc)
        quat_bytes = struct.pack("<4d", *rotator_to_quat(*rot))

        end = time.perf_counter() + RESTORE_BURST_S
        while True:
            g.write_value(root, rel_loc, loc)
            g.write_value(root, rel_rot, rot)
            if c2w is not None:
                g.write(root + c2w, quat_bytes)
                g.write(root + c2w + 0x20, loc_bytes)
            g.write_value(pc, ctl_rot, st["control_rotation"])
            if vel is not None:
                g.write_value(move, vel, v)
            if not use_launch and mode is not None and "movement_mode" in st:
                g.write_value(move, mode, st["movement_mode"])
            for kind, target, val in stats:
                self._write_stat(kind, target, val)
            if use_launch:
                g.write_value(move, launch_fld, launch_v)
            if time.perf_counter() >= end:
                break
            time.sleep(0.002)
        return warnings
