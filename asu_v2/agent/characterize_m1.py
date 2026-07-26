# KLayout batch: joint forensics of the M1-stack residual classes on the
# post-v2 layout — V0.M1.AUX.3 (V0 must match M1 perp width), V1.M1.EN.1
# (M1 encloses V1 by 5 & 2 nm), M1.S.* (spacing). One M1 pad can carry all
# three; dump the full stack per flagged pad to infer the seeding mechanism
# (hypothesis: the seeder reshaped/widened M1 pads).
#   CHAR_GDS=<gds> CHAR_LYRPT=<lyrpt> CHAR_OUT=<out.json> klayout -b -r characterize_m1.py
import pya, json, os, re

gds, lyrpt, out = os.environ["CHAR_GDS"], os.environ["CHAR_LYRPT"], os.environ["CHAR_OUT"]
ly = pya.Layout(); ly.read(gds)
top = ly.top_cell()
NM = 1.0 / (ly.dbu * 1000.0)

def region(l):
    return pya.Region(top.begin_shapes_rec(ly.layer(pya.LayerInfo(l, 0))))

M1 = region(19); M1.merge()
V0 = region(18)
V1 = region(21)
LISD = region(17); LISD.merge()
LIG = region(16); LIG.merge()

# markers by category
txt = open(lyrpt, encoding="utf-8", errors="replace").read()
marks = {}
for item in re.findall(r"<item>(.*?)</item>", txt, re.S):
    m = re.search(r"<category>'?([^'<]+)'?</category>", item)
    if not m: continue
    cat = m.group(1)
    if not (cat.startswith("M1.S") or cat in ("V0.M1.AUX.3", "V1.M1.EN.1")):
        continue
    for val in re.findall(r"<value>(.*?)</value>", item, re.S):
        pts = re.findall(r"(-?[\d.]+),(-?[\d.]+)", val)
        if not pts: continue
        xs = [float(x) for x, _ in pts]; ys = [float(y) for _, y in pts]
        marks.setdefault(cat, []).append(
            pya.Box(pya.Point(int(min(xs) / ly.dbu), int(min(ys) / ly.dbu)),
                    pya.Point(int(max(xs) / ly.dbu), int(max(ys) / ly.dbu))))

def boxes(reg):
    return [p.bbox() for p in reg.each()]

v0b, v1b = boxes(V0), boxes(V1)

def pad_of(b):
    for p in M1.interacting(pya.Region(b)).each():
        return p
    return None

# collect flagged pads keyed by pad bbox
pads = {}
for cat, mbs in marks.items():
    for mb in mbs:
        p = pad_of(mb)
        key = str(p.bbox()) if p is not None else "none:" + str(mb)
        e = pads.setdefault(key, {"cats": {}, "pad": p})
        e["cats"][cat] = e["cats"].get(cat, 0) + 1

def encl(inner, outer):
    return [inner.left - outer.left, inner.bottom - outer.bottom,
            outer.right - inner.right, outer.top - inner.top]

sites = []
for key, e in pads.items():
    p = e["pad"]
    if p is None:
        sites.append({"pad": key, "cats": e["cats"]}); continue
    pb = p.bbox()
    pr = pya.Region(pya.Box(pb))
    v0s = [b for b in v0b if not (pya.Region(b) & pr).is_empty()]
    v1s = [b for b in v1b if not (pya.Region(b) & pr).is_empty()]
    lisd_ext = None
    for lp in LISD.interacting(pya.Region(pb)).each():
        lb = lp.bbox()
        lisd_ext = [lb.left, lb.bottom, lb.right, lb.top]; break
    sites.append({
        "pad_bbox": [pb.left, pb.bottom, pb.right, pb.top],
        "pad_wh": [pb.width(), pb.height()],
        "pad_rect": p.is_box(),
        "cats": e["cats"],
        "v0": [{"wh": [b.width(), b.height()],
                "encl_in_pad": encl(b, pb)} for b in v0s],
        "v1": [{"wh": [b.width(), b.height()],
                "encl_in_pad": encl(b, pb)} for b in v1s],
        "lisd": lisd_ext,
    })

# aggregates
agg = {"pads_flagged": len(sites), "by_cat_combo": {}, "pad_wh_hist": {},
       "v1_wh_hist": {}, "v1_encl_min_hist": {}}
for s in sites:
    combo = "+".join(sorted(s.get("cats", {})))
    agg["by_cat_combo"][combo] = agg["by_cat_combo"].get(combo, 0) + 1
    if "pad_wh" in s:
        k = "%dx%d" % tuple(s["pad_wh"])
        agg["pad_wh_hist"][k] = agg["pad_wh_hist"].get(k, 0) + 1
    for v in s.get("v1", []):
        k = "%dx%d" % tuple(v["wh"])
        agg["v1_wh_hist"][k] = agg["v1_wh_hist"].get(k, 0) + 1
        k2 = str(min(v["encl_in_pad"]))
        agg["v1_encl_min_hist"][k2] = agg["v1_encl_min_hist"].get(k2, 0) + 1
agg["pad_wh_hist"] = dict(sorted(agg["pad_wh_hist"].items(), key=lambda kv: -kv[1])[:10])
agg["v1_wh_hist"] = dict(sorted(agg["v1_wh_hist"].items(), key=lambda kv: -kv[1])[:10])

res = {"gds": gds, "dbu_um": ly.dbu,
       "marker_counts": {k: len(v) for k, v in marks.items()},
       "agg": agg, "sites": sites}
open(out, "w", encoding="utf-8").write(json.dumps(res, indent=1))
print("[char-m1] pads=%d combos=%s" % (len(sites), agg["by_cat_combo"]))
