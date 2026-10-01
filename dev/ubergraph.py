"""Dev tool: dump a Blueprint object's UberGraphFrame (persistent event-graph
locals) using the ExecuteUbergraph_* UFunction's own property layout."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import json
import sys

import ue_mem

UFIELD_NEXT = 0x28


def functions(g, cls):
    f = g.ptr(cls + 0x48)  # UStruct::Children
    while f:
        yield f
        f = g.ptr(f + UFIELD_NEXT)


def frame_values(g, obj):
    cls = g.obj_class(obj)
    uber = next((fn for fn in functions(g, cls) if (g.obj_name(fn) or "").startswith("ExecuteUbergraph")), None)
    fld = g.find_field(obj, "UberGraphFrame")
    if not uber or not fld:
        return {}
    frame = g.ptr(obj + fld["offset"])
    out = {}
    for f in g.own_fields(uber):
        if g.is_scalar(f):
            out[f["name"]] = g.read_value(frame, f)
    return out


if __name__ == "__main__":
    g = ue_mem.Game()
    p = g.player()
    targets = {"pawn": p["pawn"], "hud": g.get_obj(p["pawn"], "HUD"), "gi": p["gi"], "pc": p["pc"]}
    snap = {k: frame_values(g, v) for k, v in targets.items() if v}
    tag = sys.argv[1]
    json.dump(snap, open(f"uber_{tag}.json", "w"), default=str)
    for k, vals in snap.items():
        print(k, len(vals))
        for n, v in vals.items():
            if isinstance(v, float) and 0 < v <= 100 and "mana" in n.lower() or "magia" in n.lower() or "energ" in n.lower():
                print("   ", n, v)
