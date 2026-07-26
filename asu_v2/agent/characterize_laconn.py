# Layer-aware electrical connectivity characterization (response to Codex
# P0-1, 2026-07-26). Metal polygons merge only within their own layer; layers
# connect ONLY through the via layer between them (official BLOCK_STACK,
# check_connectivity.py: M1..M10/pad through V1..V9 — layers 19..96).
# Reports the electrical component count via a union-find over per-layer
# merged polygons joined by positive-area via overlap (matches the review's
# characterization), plus an M2-anchored partition hash.
#   CHAR_GDS=<gds> CHAR_OUT=<out.json> klayout -b -r characterize_laconn.py
import pya, json, os, hashlib

gds, out = os.environ["CHAR_GDS"], os.environ["CHAR_OUT"]
ly = pya.Layout(); ly.read(gds)
top = ly.top_cell()

STACK = [(19, 21, 20), (20, 25, 30), (30, 35, 40), (40, 45, 50), (50, 55, 60),
         (60, 65, 70), (70, 75, 80), (80, 85, 90), (90, 95, 96)]
METALS = sorted({b for b, v, a in STACK} | {a for b, v, a in STACK})

def region(l):
    return pya.Region(top.begin_shapes_rec(ly.layer(pya.LayerInfo(l, 0))))

# per-layer merged polygons, with bucket index for fast bbox lookup
BUCK = 5000
polys, buckets = {}, {}
for m in METALS:
    R = region(m); R.merge()
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

def hits(m, via_poly):
    vb = via_poly.bbox()
    cand = set()
    for bx in range(vb.left // BUCK, vb.right // BUCK + 1):
        for by in range(vb.bottom // BUCK, vb.top // BUCK + 1):
            cand.update(buckets[m].get((bx, by), []))
    vr = pya.Region(via_poly)
    out = []
    for i in cand:
        if (vr & pya.Region(polys[m][i])).area() > 0:   # positive-area overlap
            out.append((m, i))
    return out

floating = 0
for below, vl, above in STACK:
    V = region(vl)
    for vp in V.each():
        h = hits(below, vp) + hits(above, vp)
        if not h:
            floating += 1
            continue
        first = h[0]
        for other in h[1:]:
            union(first, other)

# component count over ALL metal polygons
roots = set()
for m in METALS:
    for i in range(len(polys[m])):
        roots.add(find((m, i)))
components = len(roots)

# M2-anchored partition: group M2 polygon indices (sorted centroids) by root
m2 = 20
keyed = {}
for i, p in enumerate(polys[m2]):
    b = p.bbox()
    keyed.setdefault(find((m2, i)), []).append((b.left, b.bottom, b.right, b.top))
part = sorted(tuple(sorted(v)) for v in keyed.values())
part_hash = hashlib.sha256(json.dumps(part).encode()).hexdigest()[:16]

res = {"gds": gds, "components": components, "floating_vias": floating,
       "metal_polys": {str(m): len(polys[m]) for m in METALS},
       "m2_partition_sha16": part_hash}
open(out, "w", encoding="utf-8").write(json.dumps(res, indent=1))
print("[laconn] %s: components=%d floating=%d m2_part=%s"
      % (os.path.basename(os.path.dirname(gds)), components, floating, part_hash))
