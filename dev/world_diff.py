"""Dev: snapshot the live save object (and GameInstance scalars) or diff two.
python dev/world_diff.py snap A | python dev/world_diff.py diff A B"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import json

import ue_mem
import world_state

if sys.argv[1] == "snap":
    g = ue_mem.Game()
    p = g.player()
    snap = world_state.capture(g, p["gi"])
    snap["gi"] = {f["name"]: g.read_value(p["gi"], f) for c, f in g.all_fields(p["gi"])
                  if c.endswith("_C") and g.is_scalar(f)}
    snap["world"] = g.world_name()
    json.dump(snap, open(f"dev/world_{sys.argv[2]}.json", "w"), default=str)
    print(f"{snap['world']}: {len(snap['scalars'])} scalars, {len(snap['maps'])} maps, "
          f"{sum(len(v) for v in snap['levels'].values())} actor states, {len(snap['gi'])} GI scalars")
else:
    a = json.load(open(f"dev/world_{sys.argv[2]}.json"))
    b = json.load(open(f"dev/world_{sys.argv[3]}.json"))
    for line in world_state.diff(a, b):
        print(line)
    for k in sorted(set(a["gi"]) | set(b["gi"])):
        if a["gi"].get(k) != b["gi"].get(k):
            print(f"GI.{k}: {a['gi'].get(k)} -> {b['gi'].get(k)}")
