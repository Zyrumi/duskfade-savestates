"""Dev: log SaveGame.Habilidades and the pawn's Habilidades flags every 20ms."""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import time
import ue_mem

g = ue_mem.Game()
last = None
t0 = time.time()
while time.time() - t0 < float(sys.argv[1]) if len(sys.argv) > 1 else 40:
    try:
        world = g.uworld()
        name = g.world_name() if world else None
        gi_sg = sg = pawn_flags = None
        try:
            p = g.player()
            sg = g.get_obj(p["gi"], "SaveGame")
            d, n = g.tarray(g.field_addr(sg, "Habilidades"))
            gi_sg = g.read(d, n).hex() if d else None
            f = g.find_field(p["pawn"], "Habilidades")
            d2, n2 = g.tarray(p["pawn"] + f["offset"])
            pawn_flags = "".join("1" if b else "0" for b in (g.read(d2, n2 * 2) or b"")[1::2])
        except Exception as e:
            gi_sg = gi_sg or type(e).__name__
        cur = (hex(world), name, gi_sg, pawn_flags)
        if cur != last:
            print(f"+{time.time() - t0:6.2f}s world={cur[0]} {cur[1]} SaveGame.Habilidades={cur[2]} pawn={cur[3]}", flush=True)
            last = cur
    except Exception as e:
        print("err", e, flush=True)
    time.sleep(0.02)
