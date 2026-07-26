# KLayout batch: characterize the M4/M5/M6.AUX.1 off-grid class on a rendered
# GDS. Tests the TRACK-SHIFT hypothesis: if the seeder translated whole tracks
# off-grid, then for each off-grid polygon BOTH constrained edges are off by the
# SAME delta (translate restores the original position); if edges are off by
# different deltas it was a resize and translate won't work.
# Also records, per off-grid polygon: size, which vias interact (V3/V4/V5 and
# their slack inside the adjacent metals) so the fix can co-translate them.
#   CHAR_GDS=<gds> CHAR_OUT=<out.json> klayout -b -r characterize_grid.py
import pya, json, os

gds, out = os.environ["CHAR_GDS"], os.environ["CHAR_OUT"]
ly = pya.Layout(); ly.read(gds)
top = ly.top_cell()
NM = 1.0 / (ly.dbu * 1000.0)                     # dbu per nm

# (metal, gds layer, axis of constrained coordinate, grid nm, via layers below/above)
SPECS = [("M4", 40, "y", 24, [("V3", 35, "M3", 30), ("V4", 45, "M5", 50)]),
         ("M5", 50, "x", 24, [("V4", 45, "M4", 40), ("V5", 55, "M6", 60)]),
         ("M6", 60, "y", 32, [("V5", 55, "M5", 50)])]

def region(l):
    return pya.Region(top.begin_shapes_rec(ly.layer(pya.LayerInfo(l, 0))))

res = {"gds": gds, "layers": {}}
for mname, ml, axis, gnm, vias in SPECS:
    M = region(ml); M.merge()
    G = int(gnm * NM)
    offgrid = []
    for p in M.each():
        b = p.bbox()
        lo, hi = (b.bottom, b.top) if axis == "y" else (b.left, b.right)
        dlo, dhi = lo % G, hi % G
        if dlo == 0 and dhi == 0:
            continue
        # delta to NEAREST grid for each constrained side
        ndlo = dlo if dlo <= G // 2 else dlo - G
        ndhi = dhi if dhi <= G // 2 else dhi - G
        rect = p.is_box()
        touching = []
        for vname, vl, oml, omll in vias:
            V = region(vl)
            for v in V.interacting(pya.Region(b)).each():
                vb = v.bbox()
                om = region(omll); om.merge()
                # slack of this via inside the OTHER metal along the shift axis
                slack = None
                for op in om.interacting(pya.Region(vb)).each():
                    ob = op.bbox()
                    slack = (min(vb.bottom - ob.bottom, ob.top - vb.top)
                             if axis == "y" else
                             min(vb.left - ob.left, ob.right - vb.right))
                    break
                touching.append({"via": vname,
                                 "wh": [vb.width(), vb.height()],
                                 "other_metal_slack_dbu": slack})
        offgrid.append({
            "bbox": [b.left, b.bottom, b.right, b.top],
            "wh": [b.width(), b.height()], "rect": rect,
            "delta_lo_dbu": ndlo, "delta_hi_dbu": ndhi,
            "same_delta": ndlo == ndhi,
            "vias": touching})
    same = sum(1 for o in offgrid if o["same_delta"])
    res["layers"][mname] = {
        "grid_dbu": G, "offgrid_polys": len(offgrid),
        "same_delta": same,
        "delta_hist": {},
        "polys": offgrid}
    dh = res["layers"][mname]["delta_hist"]
    for o in offgrid:
        k = str(o["delta_lo_dbu"]) if o["same_delta"] else \
            "%d/%d" % (o["delta_lo_dbu"], o["delta_hi_dbu"])
        dh[k] = dh.get(k, 0) + 1
    print("[char-grid] %s: offgrid=%d same_delta=%d hist=%s"
          % (mname, len(offgrid), same, dh))

open(out, "w", encoding="utf-8").write(json.dumps(res, indent=1))
print("[char-grid] wrote %s" % out)
