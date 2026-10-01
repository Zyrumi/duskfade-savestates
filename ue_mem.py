"""
External (no-injection) Unreal reflection reader/writer for Duskfade.

Finds GWorld + the FName pool the same way the autosplitter's gworld.py
does, then walks Unreal's own reflection data (UClass -> FProperty list)
so every field is looked up by its real name ("RelativeLocation",
"Velocity", a Blueprint's "Energy" variable...) instead of by hardcoded
offsets. The few engine layout constants this needs (where SuperStruct /
ChildProperties / FField::Name / FProperty::Offset live) are detected live
on attach and sanity-checked, not assumed.
"""
from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes

import gworld  # sig-scan + FNamePool decoder, shared with the Save Editor

EXE = "Duskfade-Win64-Shipping.exe"

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400

kernel32 = gworld.kernel32
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.OpenProcess.restype = wintypes.HANDLE


class AttachError(RuntimeError):
    pass


class Layout:
    """Engine struct offsets, detected per attach."""
    uobj_class = 0x10
    uobj_name = 0x18
    uobj_outer = 0x20
    super_struct = None
    child_props = None
    props_size = None
    ffield_class = 0x08
    ffield_next = None
    ffield_name = None
    fprop_offset = None
    fprop_extra = None  # first subclass-specific field (Struct*, PropertyClass*, bool masks...)


class Game:
    def __init__(self):
        pid = gworld.find_pid(EXE)
        if pid is None:
            raise AttachError("Duskfade isn't running.")
        self.pid = pid
        self.h = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION
                                      | PROCESS_QUERY_INFORMATION, False, pid)
        if not self.h:
            raise AttachError(f"OpenProcess failed (error {ctypes.get_last_error()}).")
        mod = gworld.get_module_range(pid, EXE)
        if mod is None:
            raise AttachError("Couldn't find the game module.")
        base, size = mod
        rva = gworld.find_gworld_rva(self.h, base, size)
        nrva = gworld.find_gnames_rva(self.h, base, size)
        if rva is None or nrva is None:
            raise AttachError("Signature scan for GWorld/GNames failed (game patched?).")
        self.gworld_addr = base + rva
        self.names = gworld.NamePool(self.h, base + nrva)
        if not self.names.initialize():
            raise AttachError("FName pool layout detection failed.")
        self._name_cache: dict[int, str] = {}
        self._fields_cache: dict[int, list] = {}
        self.L = Layout()
        self._detect_layout()

    # ---------- raw memory ----------

    def read(self, addr: int, size: int) -> bytes | None:
        if not addr:
            return None
        buf = ctypes.create_string_buffer(size)
        n = ctypes.c_size_t(0)
        if not kernel32.ReadProcessMemory(self.h, addr, buf, size, ctypes.byref(n)) or n.value != size:
            return None
        return buf.raw

    def write(self, addr: int, data: bytes) -> bool:
        n = ctypes.c_size_t(0)
        ok = kernel32.WriteProcessMemory(self.h, addr, data, len(data), ctypes.byref(n))
        return bool(ok) and n.value == len(data)

    def ptr(self, addr: int) -> int:
        b = self.read(addr, 8)
        return struct.unpack("<Q", b)[0] if b else 0

    def u32(self, addr: int) -> int | None:
        b = self.read(addr, 4)
        return struct.unpack("<I", b)[0] if b else None

    def i32(self, addr: int) -> int | None:
        b = self.read(addr, 4)
        return struct.unpack("<i", b)[0] if b else None

    def fname(self, addr: int) -> str | None:
        b = self.read(addr, 8)
        if not b:
            return None
        idx, num = struct.unpack("<ii", b)
        if idx < 0 or idx > 0x7FFFFFF:
            return None
        base = self._name_cache.get(idx)
        if base is None:
            base = self.names.decode(idx)
            if base is None or not base.isprintable() or len(base) > 256:
                return None
            self._name_cache[idx] = base
        return f"{base}_{num - 1}" if num > 0 else base

    # ---------- UObject helpers ----------

    def obj_name(self, obj: int) -> str | None:
        return self.fname(obj + self.L.uobj_name) if obj else None

    def obj_class(self, obj: int) -> int:
        return self.ptr(obj + self.L.uobj_class) if obj else 0

    def class_name(self, obj: int) -> str | None:
        return self.obj_name(self.obj_class(obj))

    def is_uobject(self, p: int) -> bool:
        if not p or p & 7:
            return False
        cls = self.obj_class(p)
        if not cls or cls & 7:
            return False
        meta = self.obj_class(cls)
        return self.obj_name(meta) in ("Class", "BlueprintGeneratedClass", "WidgetBlueprintGeneratedClass",
                                       "AnimBlueprintGeneratedClass", "DynamicClass")

    def _field_class_name(self, field: int) -> str | None:
        fc = self.ptr(field + self.L.ffield_class)
        return self.fname(fc) if fc else None

    def _is_ffield(self, p: int) -> bool:
        if not p or p & 7:
            return False
        n = self._field_class_name(p)
        return bool(n) and n.endswith("Property")

    # ---------- layout detection ----------

    def _detect_layout(self):
        L = self.L
        world = self.uworld()
        if not world:
            raise AttachError("GWorld is null (still loading?). Try again in a level.")
        world_cls = self.obj_class(world)
        if self.obj_name(world_cls) != "World":
            raise AttachError(f"GWorld class decoded as {self.obj_name(world_cls)!r}, expected 'World'.")
        blob = self.read(world_cls, 0x100)
        # SuperStruct: pointer to a class named "Object"
        for off in range(0x28, 0x80, 8):
            p = struct.unpack_from("<Q", blob, off)[0]
            if p and self.obj_name(p) == "Object" and self.class_name(p) == "Class":
                L.super_struct = off
                break
        # ChildProperties: first pointer after SuperStruct that looks like an FField
        for off in range((L.super_struct or 0x28) + 8, 0xA0, 8):
            p = struct.unpack_from("<Q", blob, off)[0]
            if self._is_ffield(p):
                L.child_props = off
                break
        if L.super_struct is None or L.child_props is None:
            raise AttachError(f"UStruct layout detection failed (super={L.super_struct}, props={L.child_props}).")
        L.props_size = L.child_props + 8  # int32 PropertiesSize follows ChildProperties

        first = struct.unpack_from("<Q", blob, L.child_props)[0]
        fblob = self.read(first, 0x40)
        for off in range(0x10, 0x40, 8):
            p = struct.unpack_from("<Q", fblob, off)[0]
            if L.ffield_next is None and (self._is_ffield(p)):
                L.ffield_next = off
        for off in range(0x10, 0x40, 8):
            n = self.fname(first + off)
            if n and n.isidentifier() and not n.endswith("Property") and off != L.ffield_next:
                L.ffield_name = off
                break
        if L.ffield_next is None or L.ffield_name is None:
            raise AttachError("FField layout detection failed.")

        # FProperty::Offset_Internal: the int32 slot where every property of
        # UWorld has a distinct offset inside [0x28, PropertiesSize).
        world_size = self.i32(world_cls + L.props_size) or 0
        fields = []
        f = first
        for _ in range(500):
            if not f:
                break
            fields.append(f)
            f = self.ptr(f + L.ffield_next)
        for off in range(L.ffield_name + 8, 0x70, 4):
            vals = [self.i32(x + off) for x in fields]
            if all(v is not None and 0x28 <= v < world_size for v in vals) and len(set(vals)) == len(vals):
                L.fprop_offset = off
                break
        if L.fprop_offset is None:
            raise AttachError("FProperty::Offset detection failed.")
        # First subclass field: find a StructProperty and look for its UScriptStruct*.
        for x in fields:
            if self._field_class_name(x) == "StructProperty":
                for off in range(0x60, 0xA0, 8):
                    p = self.ptr(x + off)
                    if p and self.class_name(p) == "ScriptStruct":
                        L.fprop_extra = off
                        break
            if L.fprop_extra:
                break
        if L.fprop_extra is None:
            raise AttachError("FProperty size detection failed.")

    # ---------- reflection ----------

    def uworld(self) -> int:
        return self.ptr(self.gworld_addr)

    def world_name(self) -> str | None:
        return self.obj_name(self.uworld())

    def class_chain(self, cls: int) -> list[int]:
        out = []
        while cls and len(out) < 64:
            out.append(cls)
            cls = self.ptr(cls + self.L.super_struct)
        return out

    def own_fields(self, struct_ptr: int) -> list[dict]:
        """Properties declared directly on this UStruct (not inherited)."""
        if struct_ptr in self._fields_cache:
            return self._fields_cache[struct_ptr]
        L = self.L
        out = []
        f = self.ptr(struct_ptr + L.child_props)
        while f and len(out) < 2000:
            kind = self._field_class_name(f) or "?"
            info = {
                "name": self.fname(f + L.ffield_name) or "?",
                "kind": kind,
                "offset": self.i32(f + L.fprop_offset),
                "addr": f,
            }
            if kind == "StructProperty":
                info["struct"] = self.obj_name(self.ptr(f + L.fprop_extra))
            elif kind == "BoolProperty":
                b = self.read(f + L.fprop_extra, 4)
                info["bool"] = tuple(b) if b else (1, 0, 1, 0xFF)  # FieldSize, ByteOffset, ByteMask, FieldMask
            elif kind in ("ObjectProperty", "WeakObjectProperty", "ClassProperty", "SoftObjectProperty"):
                info["class"] = self.obj_name(self.ptr(f + L.fprop_extra))
            elif kind == "EnumProperty":
                info["enum"] = self.obj_name(self.ptr(f + L.fprop_extra + 8))
            elif kind == "ByteProperty":
                info["enum"] = self.obj_name(self.ptr(f + L.fprop_extra))
            out.append(info)
            f = self.ptr(f + L.ffield_next)
        self._fields_cache[struct_ptr] = out
        return out

    def all_fields(self, obj: int) -> list[tuple[str, dict]]:
        """(declaring class name, field) for the object's whole class chain."""
        res = []
        for cls in self.class_chain(self.obj_class(obj)):
            cname = self.obj_name(cls)
            for fld in self.own_fields(cls):
                res.append((cname, fld))
        return res

    def find_field(self, obj_or_struct: int, name: str, is_struct: bool = False) -> dict | None:
        start = obj_or_struct if is_struct else self.obj_class(obj_or_struct)
        for cls in self.class_chain(start):
            for fld in self.own_fields(cls):
                if fld["name"] == name:
                    return fld
        return None

    def field_addr(self, obj: int, name: str) -> int:
        fld = self.find_field(obj, name)
        if fld is None:
            raise KeyError(f"{self.class_name(obj)} has no property {name!r}")
        return obj + fld["offset"]

    def get_obj(self, obj: int, name: str) -> int:
        return self.ptr(self.field_addr(obj, name))

    # ---------- value (de)serialisation for scalar fields ----------

    SCALAR_FMT = {
        "FloatProperty": "<f", "DoubleProperty": "<d", "IntProperty": "<i", "UInt32Property": "<I",
        "Int64Property": "<q", "Int16Property": "<h", "Int8Property": "<b", "ByteProperty": "<B",
        "EnumProperty": "<B",
    }
    STRUCT_FMT = {"Vector": "<3d", "Rotator": "<3d", "Vector2D": "<2d", "Quat": "<4d",
                  "LinearColor": "<4f", "IntPoint": "<2i"}

    def read_value(self, obj: int, fld: dict):
        addr = obj + fld["offset"]
        kind = fld["kind"]
        if kind == "BoolProperty":
            _fs, byte_off, byte_mask, _fm = fld["bool"]
            b = self.read(addr + byte_off, 1)
            return None if b is None else bool(b[0] & byte_mask)
        fmt = self.SCALAR_FMT.get(kind) or (self.STRUCT_FMT.get(fld.get("struct")) if kind == "StructProperty" else None)
        if not fmt:
            return None
        b = self.read(addr, struct.calcsize(fmt))
        if b is None:
            return None
        v = struct.unpack(fmt, b)
        return v[0] if len(v) == 1 else list(v)

    def write_value(self, obj: int, fld: dict, value) -> bool:
        addr = obj + fld["offset"]
        kind = fld["kind"]
        if kind == "BoolProperty":
            _fs, byte_off, byte_mask, _fm = fld["bool"]
            b = self.read(addr + byte_off, 1)
            if b is None:
                return False
            cur = b[0]
            new = (cur | byte_mask) if value else (cur & ~byte_mask & 0xFF)
            return new == cur or self.write(addr + byte_off, bytes([new]))
        fmt = self.SCALAR_FMT.get(kind) or (self.STRUCT_FMT.get(fld.get("struct")) if kind == "StructProperty" else None)
        if not fmt:
            return False
        vals = value if isinstance(value, (list, tuple)) else [value]
        return self.write(addr, struct.pack(fmt, *vals))

    def is_scalar(self, fld: dict) -> bool:
        k = fld["kind"]
        return k == "BoolProperty" or k in self.SCALAR_FMT or (k == "StructProperty" and fld.get("struct") in self.STRUCT_FMT)

    # ---------- player lookup ----------

    def tarray(self, addr: int) -> tuple[int, int]:
        b = self.read(addr, 16)
        if not b:
            return 0, 0
        data, num, _max = struct.unpack("<Qii", b)
        return data, num

    def player(self) -> dict:
        """Returns the local player's controller, pawn, root + movement component."""
        world = self.uworld()
        gi = self.get_obj(world, "OwningGameInstance")
        data, num = self.tarray(self.field_addr(gi, "LocalPlayers"))
        if not data or num < 1:
            raise AttachError("No local player yet.")
        lp = self.ptr(data)
        pc = self.get_obj(lp, "PlayerController")
        pawn = self.get_obj(pc, "AcknowledgedPawn") or self.get_obj(pc, "Pawn")
        if not pawn:
            raise AttachError("No player pawn (menu or loading?).")
        root = self.get_obj(pawn, "RootComponent")
        move = 0
        if self.find_field(pawn, "CharacterMovement"):
            move = self.get_obj(pawn, "CharacterMovement")
        ps = self.get_obj(pc, "PlayerState") if self.find_field(pc, "PlayerState") else 0
        return {"world": world, "gi": gi, "pc": pc, "pawn": pawn, "root": root, "move": move, "ps": ps}

    # ---------- material instance scalar parameters ----------

    ARRAY_INNER = 0x78  # FArrayProperty::Inner (after EArrayPropertyFlags)
    MID_RESOURCE = 0x248  # UMaterialInstance::Resource (not reflected)

    def mid_param_addrs(self, mid: int, name: str) -> list[int]:
        """Addresses of a MaterialInstanceDynamic scalar parameter's float:
        the game-thread copy (what GetScalarParameterValue reads) and, when
        found, the render-thread copy."""
        fld = self.find_field(mid, "ScalarParameterValues")
        if fld is None:
            return []
        inner = self.ptr(fld["addr"] + self.ARRAY_INNER)
        st = self.ptr(inner + self.L.fprop_extra)
        esize = self.struct_stride(st) or 36
        sf = {f["name"]: f["offset"] for f in self.own_fields(st)}
        data, num = self.tarray(mid + fld["offset"])
        out = []
        name_key = None
        for i in range(max(0, min(num, 64))):
            e = data + i * esize
            if self.fname(e + sf.get("ParameterInfo", 0)) == name:
                out.append(e + sf.get("ParameterValue", 0x10))
                name_key = self.read(e + sf.get("ParameterInfo", 0), 4)
        if not out:
            return out
        # Render copy: TArray<{hashed name info (16 bytes), float}> inside the resource.
        res = self.ptr(mid + self.MID_RESOURCE)
        blob = self.read(res, 0x400) if res else None
        if blob:
            for j in range(0, 0x400 - 16, 8):
                dp, n, mx = struct.unpack_from("<Qii", blob, j)
                if 0 < n <= 32 and n <= mx <= 64 and 0x10000 < dp < 0x7FFFFFFFFFFF and dp % 4 == 0:
                    arr = self.read(dp, n * 20)
                    if arr:
                        for k in range(n):
                            if arr[k * 20:k * 20 + 4] == name_key:
                                out.append(dp + k * 20 + 16)
                                break
                        if len(out) > 1:
                            break
        return out

    def struct_stride(self, struct_ptr: int) -> int:
        """Array stride of a UScriptStruct: PropertiesSize rounded up to
        MinAlignment (an int16 right after it), as Unreal lays arrays out."""
        size = self.i32(struct_ptr + self.L.props_size) or 0
        b = self.read(struct_ptr + self.L.props_size + 4, 2)
        align = int.from_bytes(b, "little") if b else 1
        align = align if align in (1, 2, 4, 8, 16) else 8
        return (size + align - 1) // align * align

    # ---------- TMap (FScriptMap) ----------

    MAP_KEY_PROP = 0x70
    MAP_VALUE_PROP = 0x78
    MAP_LAYOUT = 0x80  # FScriptMapLayout: ValueOffset, HashNextIdOffset, HashIndexOffset, ElementSize

    def map_entries(self, map_addr: int, map_fld: dict) -> list[tuple[int, int]]:
        """(key address, value address) for every live pair of a TMap.
        Reads the sparse array and its allocation bits; never writes."""
        value_off, _hn, _hi, elem_size = struct.unpack("<4i", self.read(map_fld["addr"] + self.MAP_LAYOUT, 16))
        raw = self.read(map_addr, 0x38)
        if not raw:
            return []
        data, num, _cap = struct.unpack_from("<Qii", raw, 0)
        num_bits = struct.unpack_from("<i", raw, 0x28)[0]
        if not data or not 0 <= num <= 1_000_000 or num_bits < num:
            return []
        secondary = struct.unpack_from("<Q", raw, 0x20)[0]
        nwords = (num_bits + 31) // 32
        bits_raw = self.read(secondary, nwords * 4) if secondary else raw[0x10:0x20]
        words = struct.unpack(f"<{len(bits_raw) // 4}I", bits_raw)
        out = []
        for i in range(num):
            if words[i // 32] >> (i % 32) & 1:
                e = data + i * elem_size
                out.append((e, e + value_off))
        return out

    def map_props(self, map_fld: dict) -> tuple[dict, dict]:
        """Key and value FProperty info for a MapProperty, shaped like own_fields() entries."""
        def info(prop):
            kind = self._field_class_name(prop)
            d = {"name": self.fname(prop + self.L.ffield_name), "kind": kind, "offset": 0, "addr": prop}
            if kind == "StructProperty":
                d["struct_ptr"] = self.ptr(prop + self.L.fprop_extra)
                d["struct"] = self.obj_name(d["struct_ptr"])
            return d
        return (info(self.ptr(map_fld["addr"] + self.MAP_KEY_PROP)),
                info(self.ptr(map_fld["addr"] + self.MAP_VALUE_PROP)))

    def fstring(self, addr: int) -> str | None:
        b = self.read(addr, 16)
        if not b:
            return None
        data, num, cap = struct.unpack("<Qii", b)
        if not data or not 0 < num <= cap or num > 4096:
            return "" if num == 0 else None
        raw = self.read(data, num * 2)
        return raw.decode("utf-16-le", "replace").rstrip("\0") if raw else None
