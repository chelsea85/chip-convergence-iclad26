# KLayout batch script; paths via env vars (KLayout does not forward argv):
#   CHAR_GDS=<gds> CHAR_LYRPT=<lyrpt> CHAR_OUT=<out.json> klayout -b -r characterize_v0.py
# Phase 0/1 forensics: characterize every V0.M1.AUX.3-flagged site on the
# rendered BASELINE layout — the same flagged-vs-correct diff that cracked the
# upper-layer via-width class, now with the device-layer couplings that make V0
# different (V0.S.1 spacing, V0.LISD.EN.2 containment, V0.LIG.* interaction).
#
# For each flagged V0 site, emit:
#   v0 box, local M1 rail geometry, the PROPOSED widened V0 (flush to M1's
#   perpendicular extent at the via position, per V0.M1.AUX.3), and geometric
#   prechecks: neighbor-V0 spacing after widening, LISD containment (3 nm
#   enclosure), LIG overlap change, M1 containment. Plus array multiplicity
#   (flagged cuts per rail landing) and flagged-vs-correct size histograms.
import pya, json, os, re

gds, lyrpt, out = os.environ["CHAR_GDS"], os.environ["CHAR_LYRPT"], os.environ["CHAR_OUT"]

ly = pya.Layout(); ly.read(gds)
top = ly.top_cell()
NM = 1.0 / (ly.dbu * 1000.0)          # dbu per nm
def nm(v): return int(round(v * NM))

L = {n: ly.layer(pya.LayerInfo(l, 0)) for n, l in
     [("LIG", 16), ("LISD", 17), ("V0", 18), ("M1", 19)]}
R = {n: pya.Region(top.begin_shapes_rec(li)) for n, li in L.items()}
M1 = R["M1"].dup(); M1.merge()
LISD = R["LISD"].dup(); LISD.merge()
LIG = R["LIG"].dup(); LIG.merge()
V0 = R["V0"]                           # raw cuts (unmerged)

# ── flagged V0s from the DRC marker database (authoritative, not re-derived) ──
txt = open(lyrpt, encoding="utf-8", errors="replace").read()
flag_boxes = []
for item in re.findall(r"<item>(.*?)</item>", txt, re.S):
    if "V0.M1.AUX.3" not in item:
        continue
    for val in re.findall(r"<value>(.*?)</value>", item, re.S):
        pts = re.findall(r"(-?[\d.]+),(-?[\d.]+)", val)
        if not pts:
            continue
        xs = [float(x) for x, _ in pts]; ys = [float(y) for _, y in pts]
        flag_boxes.append(pya.Box(pya.Point(int(min(xs) / ly.dbu), int(min(ys) / ly.dbu)),
                                  pya.Point(int(max(xs) / ly.dbu), int(max(ys) / ly.dbu))))

v0_boxes = [p.bbox() for p in V0.each()]
def v0_at(mb):
    hits = [b for b in v0_boxes
            if b.left <= mb.right and b.right >= mb.left
            and b.bottom <= mb.top and b.top >= mb.bottom]
    return hits

flagged, seen = [], set()
for mb in flag_boxes:
    for b in v0_at(mb):
        key = (b.left, b.bottom, b.right, b.top)
        if key not in seen:
            seen.add(key); flagged.append(b)

flagged_keys = set((b.left, b.bottom, b.right, b.top) for b in flagged)
correct = [b for b in v0_boxes
           if (b.left, b.bottom, b.right, b.top) not in flagged_keys]

def hist(boxes):
    h = {}
    for b in boxes:
        k = "%dx%d" % (b.width(), b.height())
        h[k] = h.get(k, 0) + 1
    return dict(sorted(h.items(), key=lambda kv: -kv[1])[:8])

# ── per-site analysis ────────────────────────────────────────────────────────
S18, S27, EN3 = int(18 * NM), int(27 * NM), int(3 * NM)
sites = []
for b in flagged:
    m1p = None
    for p in M1.interacting(pya.Region(b)).each():
        m1p = p; break
    if m1p is None:
        sites.append({"v0": [b.left, b.bottom, b.right, b.top],
                      "fail": "no-M1"}); continue
    mb = m1p.bbox(); horiz = mb.width() >= mb.height()
    # M1's perpendicular extent at the via's along-rail span
    band = pya.Box(b.left, mb.bottom, b.right, mb.top) if horiz \
        else pya.Box(mb.left, b.bottom, mb.right, b.top)
    local = pya.Region(band) & M1
    prop = local.bbox()                # proposed widened V0 (flush to M1 perp)

    checks, why = True, []
    if not (pya.Region(prop) - M1).is_empty():
        checks = False; why.append("m1-nonrect")
    # neighbor-V0 spacing after widening (worst-case V0.S.1 = 27 nm)
    pr = pya.Region(prop)
    gap18 = gap27 = True
    for ob in v0_boxes:
        if (ob.left, ob.bottom, ob.right, ob.top) == (b.left, b.bottom, b.right, b.top):
            continue
        dx = max(ob.left - prop.right, prop.left - ob.right, 0)
        dy = max(ob.bottom - prop.top, prop.bottom - ob.top, 0)
        if dx == 0 and dy == 0:
            gap18 = gap27 = False; break
        d = (dx * dx + dy * dy) ** 0.5
        if d < S18: gap18 = False
        if d < S27: gap27 = False
    if not gap18: checks = False; why.append("spacing<18nm")
    elif not gap27: why.append("spacing<27nm(warn)")
    # device-layer relationship must not change class
    in_lisd = pya.Region(b).inside(LISD).count() > 0
    if in_lisd:
        shrunk = LISD.sized(-EN3)
        if pya.Region(prop).inside(shrunk).count() == 0:
            checks = False; why.append("lisd-en3")
    ilig = not (pya.Region(b) & LIG).is_empty()
    if ilig:
        d_ov = (pr & LIG).area() - (pya.Region(b) & LIG).area()
        why.append("lig-overlap%+d" % d_ov)
    sites.append({
        "v0": [b.left, b.bottom, b.right, b.top],
        "v0_wh_dbu": [b.width(), b.height()],
        "m1_wh_dbu": [mb.width(), mb.height()],
        "m1_horiz": horiz,
        "proposed": [prop.left, prop.bottom, prop.right, prop.top],
        "grow_perp_dbu": (prop.height() - b.height()) if horiz
                         else (prop.width() - b.width()),
        "in_lisd": in_lisd, "interacts_lig": ilig,
        "precheck_pass": checks, "notes": why})

# array multiplicity: flagged cuts sharing one M1 rail polygon
rails = {}
for b in flagged:
    for p in M1.interacting(pya.Region(b)).each():
        k = str(p.bbox()); rails[k] = rails.get(k, 0) + 1
        break
mult = {}
for v in rails.values():
    mult[v] = mult.get(v, 0) + 1

res = {
    "gds": gds, "dbu_um": ly.dbu,
    "marker_items": len(flag_boxes),
    "flagged_v0": len(flagged), "correct_v0": len(correct),
    "flagged_size_hist_dbu": hist(flagged),
    "correct_size_hist_dbu": hist(correct),
    "cuts_per_rail_hist": mult,
    "precheck_pass": sum(1 for s in sites if s.get("precheck_pass")),
    "fail_reasons": {},
    "sites": sites,
}
for s in sites:
    if not s.get("precheck_pass"):
        for w in s.get("notes", ["?"]) or ["?"]:
            if "(warn)" in w or w.startswith("lig-overlap"): continue
            res["fail_reasons"][w] = res["fail_reasons"].get(w, 0) + 1

open(out, "w", encoding="utf-8").write(json.dumps(res, indent=1))
print("[char-v0] flagged=%d correct=%d precheck_pass=%d -> %s"
      % (len(flagged), len(correct), res["precheck_pass"], out))
