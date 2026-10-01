"""Dev tool: raw-byte snapshot of every object reachable from the player
(2 hops), then diff two snapshots mapping changed bytes to property names.
python raw_diff.py snap A | python raw_diff.py diff A B"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pickle
import sys

import ue_mem
SKIP_CLASS_WORDS = ("AnimMontage", "Texture", "Font", "NiagaraSystem")


def walk(g):
    p = g.player()
    queue = [(r, p[r], 0) for r in ("pawn", "pc", "ps", "gi", "move") if p.get(r)]
    seen = {}
    while queue:
        path, obj, d = queue.pop(0)
        if obj in seen:
            continue
        seen[obj] = path
        if d >= 2:
            continue
        for _c, f in g.all_fields(obj):
            if f["kind"] == "ObjectProperty" and not any(w in (f.get("class") or "") for w in SKIP_CLASS_WORDS):
                ref = g.ptr(obj + f["offset"])
                if ref and ref not in seen and g.is_uobject(ref):
                    queue.append((f"{path}>{f['name']}", ref, d + 1))
    return seen


if sys.argv[1] == "snap":
    g = ue_mem.Game()
    objs = walk(g)
    data = {}
    for obj, path in objs.items():
        size = g.i32(g.obj_class(obj) + g.L.props_size) or 0
        if 0 < size < 0x20000:
            fields = sorted(((f["offset"], f["name"], f["kind"], f.get("struct")) for _c, f in g.all_fields(obj)))
            data[path] = (obj, g.read(obj, size), fields)
            for off, name, kind, _st in fields:
                if kind == "ArrayProperty":
                    ptr, num = g.tarray(obj + off)
                    if ptr and 0 < num <= 64:
                        blob = g.read(ptr, num * 48)
                        if blob:
                            data[f"{path}[{name}]"] = (ptr, blob, [(0, name + "[]", "raw", None)])
    pickle.dump(data, open(f"raw_{sys.argv[2]}.pkl", "wb"))
    print(f"raw snap {sys.argv[2]}: {len(data)} objects")
else:
    import struct
    A = pickle.load(open(f"raw_{sys.argv[2]}.pkl", "rb"))
    B = pickle.load(open(f"raw_{sys.argv[3]}.pkl", "rb"))
    for path, (obj, a, fields) in A.items():
        if path not in B or B[path][0] != obj or not a or not B[path][1]:
            continue
        b = B[path][1]
        hits = {}
        for i in range(0, min(len(a), len(b)) - 7, 8):
            if a[i:i+8] != b[i:i+8]:
                owner = None
                for off, name, kind, st in fields:
                    if off <= i:
                        owner = (off, name, kind, st)
                hits.setdefault(owner, []).append(i)
        for owner, offs in hits.items():
            if owner is None:
                continue
            off, name, kind, st = owner
            if any(w in name for w in ("Timeline", "TL_", "Tick", "Time", "Frame")):
                continue
            span = [o - off for o in offs]
            dv = ""
            if kind == "DoubleProperty":
                dv = f"{struct.unpack_from('<d', a, off)[0]} -> {struct.unpack_from('<d', b, off)[0]}"
            print(f"{path}.{name} [{kind} {st or ''}] +{off:#x} bytes@{[hex(s) for s in span[:6]]} {dv}")
