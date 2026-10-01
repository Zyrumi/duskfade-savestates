"""Dev tool: snapshot every scalar reachable (2 hops) from the player, or
diff two snapshots.  python wide_snap.py snap A | python wide_snap.py diff A B"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import json
import sys

import ue_mem

SKIP_CLASS_WORDS = ("Material", "NiagaraSystem", "AnimMontage", "Timeline", "Sound", "Texture",
                    "Mesh", "Niagara", "FMOD", "PostProcess", "Decal", "Cable", "Font")


def snap(tag):
    g = ue_mem.Game()
    p = g.player()
    seen = {}
    queue = [(role, p[role]) for role in ("pawn", "pc", "ps", "gi", "move", "root") if p.get(role)]
    depth = {path: 0 for path, _ in queue}
    out = {}
    while queue:
        path, obj = queue.pop(0)
        if obj in seen:
            continue
        seen[obj] = path
        for cname, f in g.all_fields(obj):
            if g.is_scalar(f):
                out[f"{path}.{f['name']}"] = g.read_value(obj, f)
            elif f["kind"] == "ObjectProperty" and depth[path] < 2:
                cls = f.get("class") or ""
                if any(w in cls for w in SKIP_CLASS_WORDS):
                    continue
                ref = g.ptr(obj + f["offset"])
                if ref and ref not in seen and g.is_uobject(ref):
                    np = f"{path}>{f['name']}"
                    depth[np] = depth[path] + 1
                    queue.append((np, ref))
    json.dump(out, open(f"snap_{tag}.json", "w"), default=str)
    print(f"snap {tag}: {len(out)} values from {len(seen)} objects")


def diff(a, b):
    A = json.load(open(f"snap_{a}.json"))
    B = json.load(open(f"snap_{b}.json"))
    for k in A:
        if k in B and A[k] != B[k] and "Timeline" not in k and "TL_" not in k:
            print(f"{k}: {A[k]} -> {B[k]}")


if sys.argv[1] == "snap":
    snap(sys.argv[2])
else:
    diff(sys.argv[2], sys.argv[3])
