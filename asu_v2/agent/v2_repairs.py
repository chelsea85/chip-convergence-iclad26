"""ASU v2 repair passes (rev3, 2026-07-26) — build on top of asu_work without
modifying it. Emitted as self-contained pya code appended to the original
layout script, so they run identically under the official runner (inside the
organizer's KLayout render; no external inputs).

Release stack: via-bar-safe + track-shift + v1-patch.

Safety model (post Codex Rev2 review — layer-aware, no flat-projection
acceptance anywhere):
  * via-bar-safe: a bar is placed only if the electrical roots it touches on
    BOTH adjacent metal layers equal the original cuts' (full-stack union-find,
    positive-area via linking). Rejected landings keep their original cuts.
  * track-shift: per-move layer-aware acceptance — same-layer touch set,
    stationary adjacent-via positive-area contact sets, and each riding cut's
    opposite-side host set must all be unchanged; M3 patches may touch only
    their host rail and no foreign via; M6 tracks interacting V6 never move.
  * v1-patch: a patch must extend only its host pad and may not create a new
    positive-area via contact absent from the host.
NOTE: verify.py's 2D credibility gate (v1, unchanged) is an anti-deletion
proxy, NOT an electrical check; the electrical gate is the layer-aware
partition comparison in v2_run.py / characterize_laconn.py.
"""
from __future__ import annotations

_TRACK_SHIFT_HELPER = '''
# ===== ASU v2 track-shift repair pass (rev3, 2026-07-26) =====
# Translate off-grid M4/M5/M6 tracks back to the routing grid (min-width tracks
# to the 2G pitch per M*.AUX.2, wider rails to the G edge grid), co-translating
# riding V3/V4 cuts and patching M3 end-caps.
#
# Acceptance is LAYER-AWARE PER MOVE (Rev3 / Codex P0-B) — no flat projected
# fallback. A move is accepted only if ALL of:
#   * same-layer touching contacts of the track are unchanged;
#   * the set of STATIONARY adjacent-layer via shapes with positive-area
#     overlap on the track is unchanged (riding cuts excluded — they co-move);
#   * every riding cut keeps positive-area overlap with exactly the same
#     opposite-side metal polygons (V3 vs M3 hosts, V4 vs M5 hosts);
#   * every inserted M3 patch touches ONLY its host rail (no other M3) and has
#     no positive-area overlap with any stationary V2/V3 shape;
#   * tracks interacting an un-co-translated upper via layer never move (M6/V6).
# Otherwise the opposite grid position is tried, else the track is left as-is.
def _asu_ts_layer(layout, m_ln, axis, grid_nm, ride_ln, below_ln, badj_lns,
                  ride2_ln, above2_ln, adj_lns, forbid_ln, stats):
    top = layout.top_cell()
    dbu_nm = 1.0 / (layout.dbu * 1000.0)
    G = int(round(grid_nm * dbu_nm))
    ENC = int(round(5 * dbu_nm))          # V.M.EN end-cap
    TIP = int(round(31 * dbu_nm))         # worst tip-to-tip spacing
    def region(l):
        return pya.Region(top.begin_shapes_rec(layout.layer(pya.LayerInfo(l, 0))))
    mli = layout.layer(pya.LayerInfo(m_ln, 0))
    M = region(m_ln); M.merge()
    msh = top.shapes(mli)
    B = region(below_ln) if below_ln else pya.Region()
    B.merge()
    Bpolys = [pp for pp in B.each()]
    A2polys = []
    if above2_ln:
        A2 = region(above2_ln); A2.merge()
        A2polys = [pp for pp in A2.each()]
    BADJ = [[pp for pp in region(l).each()] for l in (badj_lns or ())]
    ADJ = [[pp for pp in region(l).each()] for l in (adj_lns or ())]
    vsh = top.shapes(layout.layer(pya.LayerInfo(ride_ln, 0))) if ride_ln else None
    vsh2 = top.shapes(layout.layer(pya.LayerInfo(ride2_ln, 0))) if ride2_ln else None
    FORB = region(forbid_ln) if forbid_ln else pya.Region()

    moves = []
    for p in M.each():
        if not p.is_box():
            continue
        b = p.bbox()
        lo, hi = (b.bottom, b.top) if axis == "y" else (b.left, b.right)
        size = hi - lo
        if size % G != 0:                # pure translation cannot fix this one
            if lo % G or hi % G:
                stats["skip_resize"] += 1
            continue
        P = 2 * G if size == G else G    # min-width tracks sit on the 2G pitch
        r = lo % P
        if r == 0:
            continue
        d = -r if r <= P // 2 else P - r
        moves.append((b, [d, d - P if d > 0 else d + P]))

    WM = 512
    def near(polylist, bb, excl):
        out = []
        for i, pp in enumerate(polylist):
            pb = pp.bbox()
            if pb.left > bb.right + WM or pb.right < bb.left - WM or \\
               pb.bottom > bb.top + WM or pb.top < bb.bottom - WM:
                continue
            if (pb.left, pb.bottom, pb.right, pb.top) in excl:
                continue
            out.append(i)
        return out
    def pos_ids(polylist, ids, reg):
        return set(i for i in ids if (pya.Region(polylist[i]) & reg).area() > 0)

    for b, dcands in moves:
        if forbid_ln and not FORB.interacting(pya.Region(b)).is_empty():
            stats["skip_upper"] += 1; continue     # fail closed (M6/V6 etc.)
        # riding cuts (fully inside the track bbox) on both adjacent via layers
        cuts, cuts2 = [], []
        for sh, lst in ((vsh, cuts), (vsh2, cuts2)):
            if sh is None: continue
            for s in sh.each():
                vb = s.box if s.is_box() else (s.polygon.bbox() if s.is_polygon() else None)
                if vb is None: continue
                if vb.left >= b.left and vb.right <= b.right and \\
                   vb.bottom >= b.bottom and vb.top <= b.top:
                    lst.append((s, vb))
        excl = set((vb.left, vb.bottom, vb.right, vb.top) for _, vb in cuts)
        excl |= set((vb.left, vb.bottom, vb.right, vb.top) for _, vb in cuts2)
        trk = pya.Region(b)
        MO = M.dup(); MO -= trk
        same_before = MO.interacting(trk)
        adj_near = [near(lst, b, excl) for lst in ADJ]
        adj_before = [pos_ids(ADJ[k], adj_near[k], trk) for k in range(len(ADJ))]
        bnear = near(Bpolys, b, set()) if below_ln else []
        anear = near(A2polys, b, set()) if above2_ln else []
        hosts_before = [pos_ids(Bpolys, bnear, pya.Region(vb)) for _, vb in cuts]
        hosts2_before = [pos_ids(A2polys, anear, pya.Region(vb)) for _, vb in cuts2]

        applied = False
        for d in dcands:
            disp = pya.Vector(0, d) if axis == "y" else pya.Vector(d, 0)
            tr = pya.Trans(disp)
            # end-cap enclosure below each shifted V3 cut; collect patches
            ok, patches = True, []
            for _, vb in cuts:
                nb = pya.Box(vb.left + disp.x, vb.bottom + disp.y,
                             vb.right + disp.x, vb.top + disp.y)
                hostp = None
                for op in B.interacting(pya.Region(vb)).each():
                    hostp = op; break
                if hostp is None:
                    ok = False; break
                host = hostp.bbox()
                if axis == "y":
                    lo_sl, hi_sl = nb.bottom - host.bottom, host.top - nb.top
                else:
                    lo_sl, hi_sl = nb.left - host.left, host.right - nb.right
                for side, sl in (("lo", lo_sl), ("hi", hi_sl)):
                    if sl >= ENC: continue
                    need = ENC - sl
                    if axis == "y":
                        patch = pya.Box(host.left, host.bottom - need, host.right,
                                        host.bottom) if side == "lo" else \\
                                pya.Box(host.left, host.top, host.right, host.top + need)
                        probe = pya.Box(host.left, patch.bottom - TIP, host.right,
                                        patch.bottom) if side == "lo" else \\
                                pya.Box(host.left, patch.top, host.right, patch.top + TIP)
                    else:
                        patch = pya.Box(host.left - need, host.bottom, host.left,
                                        host.top) if side == "lo" else \\
                                pya.Box(host.right, host.bottom, host.right + need, host.top)
                        probe = pya.Box(patch.left - TIP, host.bottom, patch.left,
                                        host.top) if side == "lo" else \\
                                pya.Box(patch.right, host.bottom, patch.right + TIP, host.top)
                    if not (pya.Region(probe) & B).is_empty():
                        ok = False; break
                    pr = pya.Region(patch)
                    Bmin = B.dup(); Bmin -= pya.Region(hostp)
                    if not Bmin.interacting(pr).is_empty():
                        ok = False; break   # patch would touch a foreign rail
                    hit_via = False
                    for lst in BADJ:
                        for i in near(lst, patch, excl):
                            if (pya.Region(lst[i]) & pr).area() > 0:
                                hit_via = True; break
                        if hit_via: break
                    if hit_via:
                        ok = False; break   # patch would contact a foreign via
                    patches.append(patch)
                if not ok: break
            if not ok:
                continue
            trk2 = trk.transformed(tr)
            # layer-aware acceptance
            if not (same_before ^ MO.interacting(trk2)).is_empty():
                continue                    # same-layer touch set changed
            good = True
            for k in range(len(ADJ)):
                if pos_ids(ADJ[k], adj_near[k], trk2) != adj_before[k]:
                    good = False; break     # stationary via contact changed
            if good:
                for ci, (_, vb) in enumerate(cuts):
                    nb = pya.Region(pya.Box(vb.left + disp.x, vb.bottom + disp.y,
                                            vb.right + disp.x, vb.top + disp.y))
                    if pos_ids(Bpolys, bnear, nb) != hosts_before[ci]:
                        good = False; break # V3 cut changed its M3 host set
            if good:
                for ci, (_, vb) in enumerate(cuts2):
                    nb = pya.Region(pya.Box(vb.left + disp.x, vb.bottom + disp.y,
                                            vb.right + disp.x, vb.top + disp.y))
                    if pos_ids(A2polys, anear, nb) != hosts2_before[ci]:
                        good = False; break # V4 cut changed its M5 host set
            if not good:
                continue
            # apply
            med = []
            for s in msh.each():
                sb = s.box if s.is_box() else (s.polygon.bbox() if s.is_polygon() else None)
                if sb is None: continue
                if sb.left >= b.left and sb.right <= b.right and \\
                   sb.bottom >= b.bottom and sb.top <= b.top:
                    med.append(s)
            for s in med:
                s.transform(tr)
            for s, _ in cuts:
                s.transform(tr)
            for s, _ in cuts2:
                s.transform(tr)
            if below_ln and patches:
                bsh = top.shapes(layout.layer(pya.LayerInfo(below_ln, 0)))
                for patch in patches:
                    bsh.insert(patch)
            stats["moved"] += 1
            applied = True
            break
        if not applied:
            stats["skipped"] += 1
'''


def track_shift_pass() -> str:
    """Translate off-grid M4/M5/M6 tracks back to grid with layer-aware
    per-move electrical acceptance (Rev3): riding V3/V4 cuts co-translate,
    M3 end-caps are patched, and any move that would change a same-layer,
    adjacent-via, or riding-cut contact set is reverted."""
    lines = [
        _TRACK_SHIFT_HELPER,
        "_asu_ts = {'moved': 0, 'skip_resize': 0, 'skipped': 0, 'skip_upper': 0}",
        "_asu_ts_layer(layout, 40, 'y', 24, 35, 30, (25, 35), 45, 50, (35, 45), None, _asu_ts)",
        "_asu_ts_layer(layout, 50, 'x', 24, None, None, None, None, None, (45, 55), None, _asu_ts)",
        "_asu_ts_layer(layout, 60, 'y', 32, None, None, None, None, None, (55,), 65, _asu_ts)",
        "print('[asu-v2] track-shift:', _asu_ts)",
    ]
    return "\n".join(lines) + "\n"


_VIA_BAR_SAFE_HELPER = '''
# ===== ASU v2 via-bar-SAFE repair pass (rev3, 2026-07-26, Codex P0-1/P0-A) =====
# Same repair as v1 via_bar_pass — replace each flagged multi-cut via array
# with one continuous bar — but with a TWO-SIDED ELECTRICAL guard: the set of
# layer-aware electrical components (full official stack, positive-area via
# linking) that the bar touches on the BELOW *and* ABOVE metal layers must
# EQUAL the set the original cuts touch. Bars over already-connected rails are
# fine; bars that would join or drop any net on either side keep their
# original cuts (fail closed). Deletion is by exact cut box, never bbox.
_ASU_STACK = [(19,21,20),(20,25,30),(30,35,40),(40,45,50),(50,55,60),
              (60,65,70),(70,75,80),(80,85,90),(90,95,96)]

def _asu_elec(layout):
    # electrical partition of per-layer merged metal polygons via union-find
    top = layout.top_cell()
    metals = sorted(set([b for b,v,a in _ASU_STACK] + [a for b,v,a in _ASU_STACK]))
    BUCK = 5000
    polys, buckets = {}, {}
    for m in metals:
        R = pya.Region(top.begin_shapes_rec(layout.layer(pya.LayerInfo(m,0))))
        R.merge()
        lst = [pp for pp in R.each()]
        polys[m] = lst
        idx = {}
        for i, pp in enumerate(lst):
            bb = pp.bbox()
            for bx in range(bb.left//BUCK, bb.right//BUCK+1):
                for by in range(bb.bottom//BUCK, bb.top//BUCK+1):
                    idx.setdefault((bx,by), []).append(i)
        buckets[m] = idx
    parent = {}
    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    def hits(m, reg, rb):
        cand = set()
        for bx in range(rb.left//BUCK, rb.right//BUCK+1):
            for by in range(rb.bottom//BUCK, rb.top//BUCK+1):
                cand.update(buckets[m].get((bx,by), []))
        out = []
        for i in cand:
            if (reg & pya.Region(polys[m][i])).area() > 0:
                out.append((m, i))
        return out
    for below, vl, above in _ASU_STACK:
        V = pya.Region(top.begin_shapes_rec(layout.layer(pya.LayerInfo(vl,0))))
        for vp in V.each():
            vr = pya.Region(vp); vb = vp.bbox()
            h = hits(below, vr, vb) + hits(above, vr, vb)
            for other in h[1:]:
                union(h[0], other)
    return polys, buckets, find, hits

def _asu_bar_pair_safe(layout, via_ln, m_ln, below_ln, elec, stats):
    top = layout.top_cell()
    polys, buckets, find, hits = elec
    vli = layout.layer(pya.LayerInfo(via_ln, 0))
    mli = layout.layer(pya.LayerInfo(m_ln, 0))
    V = pya.Region(top.begin_shapes_rec(vli))
    M = pya.Region(top.begin_shapes_rec(mli)); M.merge()
    top.flatten(-1, True)
    vsh = top.shapes(vli)
    landings = {}
    for v in V.each():
        vb = v.bbox(); mp = None
        for p in M.interacting(pya.Region(vb)).each(): mp = p; break
        if not mp: continue
        mb = mp.bbox(); horiz = mb.width() >= mb.height()
        vperp = vb.height() if horiz else vb.width()
        mperp = mb.height() if horiz else mb.width()
        if vperp >= mperp: continue                 # already matched (not flagged)
        landings.setdefault((mb.left, mb.bottom, mb.right, mb.top, horiz), []).append(vb)
    def touch_roots(reg, rb):
        # TWO-SIDED, PER-SIDE (Rev3 / Codex P0-A + drop control): the roots the
        # bar touches on the BELOW and on the ABOVE metal must EACH equal the
        # original cuts'. The two sides are compared separately — a union
        # comparison hides a dropped below-contact when rail and landing are
        # the same net through the very cuts being replaced.
        return (frozenset(find(t) for t in hits(below_ln, reg, rb)),
                frozenset(find(t) for t in hits(m_ln, reg, rb)))
    accepted_bars, accepted_cuts = [], set()
    for key, cuts in landings.items():
        ml, mbo, mr, mt, h = key
        if h:                                        # M horizontal: bar spans x
            th = cuts[0].height(); cy = (mbo + mt) // 2
            bar = pya.Box(ml, cy - th // 2, mr, cy - th // 2 + th)
        else:                                        # M vertical: bar spans y
            tw = cuts[0].width(); cx = (ml + mr) // 2
            bar = pya.Box(cx - tw // 2, mbo, cx - tw // 2 + tw, mt)
        cutsr = pya.Region()
        for c in cuts: cutsr.insert(c)
        if touch_roots(pya.Region(bar), bar) != touch_roots(cutsr, cutsr.bbox()):
            stats["bar_skip_la"] += 1               # would short/open a net
            continue
        accepted_bars.append(bar)
        for c in cuts:
            accepted_cuts.add((c.left, c.bottom, c.right, c.top))
    todel = []
    for s in vsh.each():
        b = s.polygon.bbox() if s.is_polygon() else (s.box if s.is_box() else None)
        if b is None: continue
        if (b.left, b.bottom, b.right, b.top) in accepted_cuts:
            todel.append(s)                          # exact-box match ONLY
    for s in todel: s.delete()
    for bar in accepted_bars:
        vsh.insert(bar)
        stats["bars"] += 1
'''


def via_bar_safe_pass() -> str:
    """Two-sided electrically-guarded replacement for the v1 via_bar_pass:
    bars that would join or drop nets on either adjacent layer are not
    placed (their landings keep the original cuts)."""
    lines = [
        _VIA_BAR_SAFE_HELPER,
        "_asu_vb = {'bars': 0, 'bar_skip_la': 0}",
        "_asu_vb_elec = _asu_elec(layout)   # electrical partition BEFORE any bar",
        "_asu_bar_pair_safe(layout, 25, 30, 20, _asu_vb_elec, _asu_vb)   # V2: M2 below",
        "_asu_bar_pair_safe(layout, 45, 50, 40, _asu_vb_elec, _asu_vb)   # V4: M4 below",
        "_asu_bar_pair_safe(layout, 55, 60, 50, _asu_vb_elec, _asu_vb)   # V5: M5 below",
        "print('[asu-v2] via-bar-safe:', _asu_vb)",
    ]
    return "\n".join(lines) + "\n"


_V1_PATCH_HELPER = '''
# ===== ASU v2 V1-enclosure patch pass (rev3, 2026-07-26) =====
# V1.M1.EN.1 exact predicate (from asap7.lydrc): V1 passes iff inside(M1) AND
# at least one AXIS has both slacks >= 2 nm with one >= 5 nm. Patch only real
# failures, minimally, on the cheapest passing axis (all 4 orientations
# tried). Layer-aware acceptance (no flat counting): the patch must extend
# ONLY its host pad (no touch with other M1) and must not create a new
# positive-area contact with any V0/V1 that does not already contact the host
# — then it cannot change the electrical graph.
def _asu_v1_patch(layout, stats):
    top = layout.top_cell()
    dbu_nm = 1.0 / (layout.dbu * 1000.0)
    E2 = int(round(2 * dbu_nm))
    E5 = int(round(5 * dbu_nm))
    SPROBE = int(round(25 * dbu_nm))      # tip-to-side spacing (patch edges are
    # tips, neighbor pad edges are sides; rare tip-tip neighbors -> DRC referee)
    V0GUARD = int(round(1 * dbu_nm))      # only forbid touching a V0/its edge line
    m1li = layout.layer(pya.LayerInfo(19, 0))
    M1 = pya.Region(top.begin_shapes_rec(m1li)); M1.merge()
    V1 = pya.Region(top.begin_shapes_rec(layout.layer(pya.LayerInfo(21, 0))))
    V0 = pya.Region(top.begin_shapes_rec(layout.layer(pya.LayerInfo(18, 0))))
    msh = top.shapes(m1li)
    def side_box(vb, side, e):
        if side == "l": return pya.Box(vb.left - e, vb.bottom, vb.left, vb.top)
        if side == "r": return pya.Box(vb.right, vb.bottom, vb.right + e, vb.top)
        if side == "b": return pya.Box(vb.left, vb.bottom - e, vb.right, vb.bottom)
        return pya.Box(vb.left, vb.top, vb.right, vb.top + e)
    def cov(box):
        return (pya.Region(box) - M1).is_empty()
    for v in V1.each():
        vb = v.bbox()
        if (pya.Region(vb) & M1).is_empty():
            continue                      # V1 not on M1 at all — not our case
        inside = (pya.Region(vb) - M1).is_empty()
        def axis_ok(s1, s2):
            return inside and ((cov(side_box(vb, s1, E5)) and cov(side_box(vb, s2, E2)))
                               or (cov(side_box(vb, s1, E2)) and cov(side_box(vb, s2, E5))))
        if axis_ok("l", "r") or axis_ok("b", "t"):
            continue                      # already passes the rule
        host = M1.interacting(pya.Region(vb))
        othr = M1.dup(); othr -= host
        done = False
        why = "space"
        for s1, s2 in (("l", "r"), ("r", "l"), ("b", "t"), ("t", "b")):
            want = (pya.Region(vb) + pya.Region(side_box(vb, s1, E5))
                    + pya.Region(side_box(vb, s2, E2)))
            miss = want - M1
            if miss.is_empty():
                continue
            if not V0.interacting(miss.sized(V0GUARD)).is_empty():
                why = "v0"; continue
            if not miss.sized(SPROBE).interacting(othr).is_empty():
                why = "space"; continue
            if not othr.interacting(miss).is_empty():
                why = "space"; continue   # must never touch a foreign pad
            hostr = pya.Region()
            for hp in host.each(): hostr.insert(hp)
            new_edge = False
            for via_reg in (V0, V1):
                for vp in via_reg.each():
                    vpb = vp.bbox(); mb = miss.bbox()
                    if vpb.left > mb.right or vpb.right < mb.left or \\
                       vpb.bottom > mb.top or vpb.top < mb.bottom:
                        continue
                    vr = pya.Region(vp)
                    if (vr & miss).area() > 0 and (vr & hostr).area() <= 0:
                        new_edge = True; break
                if new_edge: break
            if new_edge:
                why = "v0"; continue      # would create a new electrical edge
            for pnew in miss.each():
                msh.insert(pnew)
            stats["v1_patched"] += 1; done = True; break
        if not done:
            stats["v1_skip_" + why] += 1
'''


def v1_patch_pass() -> str:
    """Minimal exact-predicate V1.M1.EN.1 patches with layer-aware acceptance."""
    lines = [
        _V1_PATCH_HELPER,
        "_asu_v1 = {'v1_patched': 0, 'v1_skip_v0': 0, 'v1_skip_space': 0}",
        "_asu_v1_patch(layout, _asu_v1)",
        "print('[asu-v2] v1-patch:', _asu_v1)",
    ]
    return "\n".join(lines) + "\n"


# ── v0-finger: EXCLUDED from the release stack ──────────────────────────────
# Falsified per-site (asu_v2/results/PHASE4_M1_STACK_FINDINGS.md): 16 stepped-
# pad slivers + 21 adjacent-V1 conflicts of 37 Block1 sites. Kept only so the
# experiment remains reproducible from the registry; NOT emitted for release.
_V0_FINGER_HELPER = '''
# ===== ASU v2 V0 finger-reconstruction pass (EXPERIMENTAL, zero yield) =====
def _asu_v0_finger(layout, stats):
    top = layout.top_cell()
    dbu_nm = 1.0 / (layout.dbu * 1000.0)
    W = int(round(20 * dbu_nm))
    EXT = int(round(24 * dbu_nm))
    MARG = int(round(18 * dbu_nm))
    GU = int(round(5 * dbu_nm))
    m1li = layout.layer(pya.LayerInfo(19, 0))
    M1 = pya.Region(top.begin_shapes_rec(m1li)); M1.merge()
    V0 = pya.Region(top.begin_shapes_rec(layout.layer(pya.LayerInfo(18, 0))))
    V1 = pya.Region(top.begin_shapes_rec(layout.layer(pya.LayerInfo(21, 0))))
    msh = top.shapes(m1li)
    def free(box):
        return (pya.Region(box) & M1).is_empty()
    for v in V0.each():
        vb = v.bbox()
        fl = {"l": free(pya.Box(vb.left - 1, vb.bottom, vb.left, vb.top)),
              "r": free(pya.Box(vb.right, vb.bottom, vb.right + 1, vb.top)),
              "b": free(pya.Box(vb.left, vb.bottom - 1, vb.right, vb.bottom)),
              "t": free(pya.Box(vb.left, vb.top, vb.right, vb.top + 1))}
        if (fl["l"] and fl["r"]) or (fl["b"] and fl["t"]):
            continue
        if (pya.Region(vb) & M1).is_empty():
            continue
        anchors = [s for s in ("t", "b", "l", "r") if fl[s]]
        if not anchors:
            stats["v0_interior"] += 1; continue
        s0 = anchors[0]
        others = V0.dup(); others -= pya.Region(vb)
        vias = others + V1
        win = pya.Region(pya.Box(vb.left - 600, vb.bottom - 600,
                                 vb.right + 600, vb.top + 600))
        local = M1 & win
        wc_pre = local.width_check(72).count()
        sc_pre = local.space_check(72).count()
        def try_slits(w, ext):
            if s0 in ("t", "b"):
                D = vb.height() + ext
                y1, y2 = (vb.top - D, vb.top) if s0 == "t" else (vb.bottom, vb.bottom + D)
                boxes = [pya.Box(vb.left - w, y1, vb.left, y2),
                         pya.Box(vb.right, y1, vb.right + w, y2)]
                finger = pya.Box(vb.left, y1, vb.right, y2)
            else:
                D = vb.width() + ext
                x1, x2 = (vb.right - D, vb.right) if s0 == "r" else (vb.left, vb.left + D)
                boxes = [pya.Box(x1, vb.bottom - w, x2, vb.bottom),
                         pya.Box(x1, vb.top, x2, vb.top + w)]
                finger = pya.Box(x1, vb.bottom, x2, vb.top)
            sr = pya.Region()
            for bx in boxes: sr.insert(bx)
            sr = sr & M1
            fill = pya.Region(finger) - M1
            if sr.is_empty() and fill.is_empty():
                return None
            after = (local - sr) + fill
            after.merge()
            if after.width_check(72).count() > wc_pre:
                return None
            if after.space_check(72).count() > sc_pre:
                return None
            if not vias.interacting(sr.sized(GU) + fill).is_empty():
                return "via"
            return (sr, fill)
        picked, saw_via = None, False
        for w, ext in ((W, EXT), (W + MARG, EXT), (W + 2 * MARG, EXT), (W, 76)):
            r = try_slits(w, ext)
            if r == "via":
                saw_via = True; continue
            if r is not None:
                picked = r; break
        if picked is None:
            stats["v0_via_near" if saw_via else "v0_sliver"] += 1; continue
        sreg, fillreg = picked
        srb = sreg.bbox()
        hit = []
        for s in msh.each():
            sb = s.box if s.is_box() else (s.polygon.bbox() if s.is_polygon() else None)
            if sb is None: continue
            if sb.left < srb.right and sb.right > srb.left and \\
               sb.bottom < srb.top and sb.top > srb.bottom:
                sp = pya.Polygon(s.box) if s.is_box() else s.polygon
                if not (pya.Region(sp) & sreg).is_empty():
                    hit.append((s, sp))
        if not hit:
            stats["v0_nohit"] += 1; continue
        for s, sp in hit:
            rem = pya.Region(sp) - sreg
            for pnew in rem.each():
                msh.insert(pnew)
        for s, _ in hit:
            s.delete()
        for pnew in fillreg.each():
            msh.insert(pnew)
        stats["v0_fixed"] += 1
'''


def v0_finger_pass() -> str:
    """EXPERIMENTAL (excluded from release): V0 finger reconstruction."""
    lines = [
        _V0_FINGER_HELPER,
        "_asu_v0 = {'v0_fixed': 0, 'v0_interior': 0, 'v0_sliver': 0,"
        " 'v0_via_near': 0, 'v0_nohit': 0}",
        "_asu_v0_finger(layout, _asu_v0)",
        "print('[asu-v2] v0-finger:', _asu_v0)",
    ]
    return "\n".join(lines) + "\n"
