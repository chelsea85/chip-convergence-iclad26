# Layer-aware electrical partition COMPARISON (Rev3 — Codex Rev2 review §5,
# option 2: immutable anchors). An anchor is a metal polygon byte-identical
# (layer + vertices) in baseline and candidate; the partition of anchors into
# electrical components must match EXACTLY (full SHA-256), every component on
# both sides must contain >=1 anchor (fail closed), and component/floating-via
# counts must be preserved. Moved/patched geometry is not an anchor — it is
# refereed by the stationary anchors it connects. KNOWN LIMIT (documented): a
# swap between two single-anchor isomorphic components is invisible to any
# anchor signature; that case is rejected by the passes' per-move layer-aware
# acceptance (permanent negative control: track/projection-swap).
#   CHAR_BASE_GDS=<gds> CHAR_CAND_GDS=<gds> CHAR_OUT=<json> \
#       klayout -b -r compare_laconn.py
import pya, json, os, hashlib

base_gds, cand_gds, out = (os.environ["CHAR_BASE_GDS"],
                           os.environ["CHAR_CAND_GDS"], os.environ["CHAR_OUT"])

STACK = [(19, 21, 20), (20, 25, 30), (30, 35, 40), (40, 45, 50), (50, 55, 60),
         (60, 65, 70), (70, 75, 80), (80, 85, 90), (90, 95, 96)]
METALS = sorted({b for b, v, a in STACK} | {a for b, v, a in STACK})
BUCK = 5000


def load(gds):
    ly = pya.Layout(); ly.read(gds)
    top = ly.top_cell()
    polys, buckets = {}, {}
    for m in METALS:
        R = pya.Region(top.begin_shapes_rec(ly.layer(pya.LayerInfo(m, 0))))
        R.merge()
        lst = [p for p in R.each()]
        polys[m] = lst
        idx = {}
        for i, p in enumerate(lst):
            b = p.bbox()
            for bx in range(b.left // BUCK, b.right // BUCK + 1):
                for by in range(b.bottom // BUCK, b.top // BUCK + 1):
                    idx.setdefault((bx, by), []).append(i)
        buckets[m] = idx
    parent = {}
    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    def hits(m, reg, rb):
        cand = set()
        for bx in range(rb.left // BUCK, rb.right // BUCK + 1):
            for by in range(rb.bottom // BUCK, rb.top // BUCK + 1):
                cand.update(buckets[m].get((bx, by), []))
        return [(m, i) for i in cand
                if (reg & pya.Region(polys[m][i])).area() > 0]
    floating = 0
    for below, vl, above in STACK:
        V = pya.Region(top.begin_shapes_rec(ly.layer(pya.LayerInfo(vl, 0))))
        for vp in V.each():
            vr = pya.Region(vp); vb = vp.bbox()
            h = hits(below, vr, vb) + hits(above, vr, vb)
            if not h:
                floating += 1
                continue
            for other in h[1:]:
                union(h[0], other)
    return polys, buckets, find, hits, floating


bp, bbk, bfind, bhits, bfloat = load(base_gds)
cp, cbk, cfind, chits, cfloat = load(cand_gds)

# IMMUTABLE ANCHORS (Codex Rev2 §5, option 2): a polygon that is byte-identical
# (same layer, same vertices) in baseline and candidate is a stable anchor.
# Moved/patched/barred geometry is not an anchor; it is refereed by the
# stationary anchors it connects. Fail closed if any electrical component on
# either side contains no anchor.
cindex = {}
for m in METALS:
    for i, pl in enumerate(cp[m]):
        cindex[(m, str(pl))] = i

anchors = []          # (anchor_id, base_root, cand_root)
for m in METALS:
    for i, pl in enumerate(bp[m]):
        key = (m, str(pl))
        j = cindex.get(key)
        if j is None:
            continue                       # changed geometry — not an anchor
        b = pl.bbox()
        aid = (m, b.left, b.bottom, b.right, b.top)
        anchors.append((aid, str(bfind((m, i))), str(cfind((m, j)))))

# fail-closed coverage: every component on BOTH sides must hold >=1 anchor
b_anchored = set(br for _, br, _ in anchors)
c_anchored = set(cr for _, _, cr in anchors)
b_all = set(str(bfind((m, i))) for m in METALS for i in range(len(bp[m])))
c_all = set(str(cfind((m, i))) for m in METALS for i in range(len(cp[m])))
b_uncovered = len(b_all - b_anchored)
c_uncovered = len(c_all - c_anchored)

def partition_sha(pairs):
    part = {}
    for aid, key in pairs:
        part.setdefault(key, []).append(aid)
    canon = sorted(tuple(sorted(map(str, v))) for v in part.values())
    return hashlib.sha256(json.dumps(canon).encode()).hexdigest(), len(part)

base_sha, base_n = partition_sha([(a, br) for a, br, _ in anchors])
cand_sha, cand_n = partition_sha([(a, cr) for a, _, cr in anchors])

equal = (base_sha == cand_sha and b_uncovered == 0 and c_uncovered == 0
         and len(b_all) == len(c_all) and bfloat == cfloat)
res = {"base_gds": base_gds, "cand_gds": cand_gds,
       "anchors": len(anchors),
       "base_components": len(b_all), "cand_components": len(c_all),
       "base_uncovered_components": b_uncovered,
       "cand_uncovered_components": c_uncovered,
       "base_floating_vias": bfloat, "cand_floating_vias": cfloat,
       "base_partition_sha256": base_sha, "cand_partition_sha256": cand_sha,
       "base_anchor_groups": base_n, "cand_anchor_groups": cand_n,
       "partition_equal": equal}
open(out, "w", encoding="utf-8").write(json.dumps(res, indent=1))
print("[laconn-cmp] anchors=%d uncovered=%d/%d comps %d->%d groups %d->%d equal=%s"
      % (len(anchors), b_uncovered, c_uncovered, len(b_all), len(c_all),
         base_n, cand_n, equal))
