"""Dev probe: attach, print detected layout, dump the local player's
reflected fields (with live values) to probe_<tag>.txt. Run twice around
an in-game change and diff to see which fields moved."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import json
import sys

import ue_mem

tag = sys.argv[1] if len(sys.argv) > 1 else "a"
g = ue_mem.Game()
print("world:", g.world_name())
print("layout:", {k: (hex(v) if isinstance(v, int) else v) for k, v in vars(g.L).items()},
      {k: hex(getattr(ue_mem.Layout, k)) for k in ("uobj_class", "uobj_name", "ffield_class")})
p = g.player()
lines = []
values = {}
for role in ("pawn", "root", "move", "pc", "ps", "gi"):
    obj = p.get(role)
    if not obj:
        continue
    lines.append(f"===== {role}: {g.obj_name(obj)} ({g.class_name(obj)}) @ {obj:#x}")
    for cname, f in g.all_fields(obj):
        val = g.read_value(obj, f) if g.is_scalar(f) else None
        extra = f.get("struct") or f.get("class") or f.get("enum") or ""
        if f["kind"] in ("ObjectProperty",):
            ref = g.ptr(obj + f["offset"])
            val = f"-> {g.obj_name(ref)} ({g.class_name(ref)})" if ref else "null"
        lines.append(f"  [{cname}] {f['name']:40s} {f['kind']:18s} {extra:24s} +{f['offset']:#06x}  {val}")
        if g.is_scalar(f):
            values[f"{role}.{cname}.{f['name']}"] = val
# components of the pawn (energy etc. may live on an actor component)
comps = []
for cname, f in g.all_fields(p["pawn"]):
    if f["kind"] == "ObjectProperty":
        ref = g.ptr(p["pawn"] + f["offset"])
        if ref and g.is_uobject(ref) and ref not in p.values():
            comps.append((f["name"], ref))
for fname, obj in comps:
    lines.append(f"===== pawn.{fname}: {g.obj_name(obj)} ({g.class_name(obj)}) @ {obj:#x}")
    for cname, f in g.all_fields(obj):
        if g.is_scalar(f):
            val = g.read_value(obj, f)
            lines.append(f"  [{cname}] {f['name']:40s} {f['kind']:18s} +{f['offset']:#06x}  {val}")
            values[f"pawn.{fname}.{cname}.{f['name']}"] = val
open(f"probe_{tag}.txt", "w", encoding="utf-8").write("\n".join(lines))
json.dump(values, open(f"probe_{tag}.json", "w"), indent=0, default=str)
print(f"wrote probe_{tag}.txt ({len(lines)} lines)")
