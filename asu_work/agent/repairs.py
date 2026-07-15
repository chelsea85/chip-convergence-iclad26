"""Deterministic geometric repair passes, emitted as pya code appended to the
ORIGINAL layout script (the source declarations are not edited; the pass mutates
the built shapes just before write). Zero model tokens.

NOTE on connectivity: the pass DOES change rendered geometry (e.g. `s.polygon =
...`), so connectivity is NOT preserved "by construction". It is preserved
because (a) the agent re-runs the official connectivity checker on every
candidate and (b) keep-best retains the eligible baseline if a candidate
regresses or breaks connectivity. Verification — not the append mechanism — is
the guarantee.

Currently implemented: `grid_snap_pass` (+ modes). The coordinated wide-metal-via
fixer was evaluated as an experiment (see ASU_DAILY_RUN_LOG) but is NOT retained
here; it regressed (neighbour spacing) and is not part of the shipped agent.
"""
from __future__ import annotations

# metal layer (layer,datatype) for ASAP7 drawing, from asap7.lyp
_METAL_LD = {"M1": (19, 0), "M2": (20, 0), "M3": (30, 0),
             "M4": (40, 0), "M5": (50, 0), "M6": (60, 0)}
# which edges each grid rule constrains: horizontal edges => snap Y, vertical => X
_GRID_AXIS = {"M4": "y", "M5": "x", "M6": "y"}   # from the rule descriptions


_SNAP_HELPER = '''
# ===== ASU deterministic repair pass (grid snap) =====
import math as _math
def _asu_snap_coord(v, grid, mode, center):
    if mode == "outward":                    # grow away from centroid -> keeps enclosure
        return (int(_math.ceil(v / grid)) * grid if v >= center
                else int(_math.floor(v / grid)) * grid)
    return int(round(v / grid)) * grid       # nearest

def _asu_snap_layer(layout, ln, dt, grid_dbu, axis, mode):
    li = layout.layer(pya.LayerInfo(ln, dt))
    n = 0
    for ci in range(layout.cells()):
        cell = layout.cell(ci)
        shapes = cell.shapes(li)
        edits = []
        for s in shapes.each():
            poly = None
            if s.is_polygon():
                poly = s.polygon
            elif s.is_box():
                poly = pya.Polygon(s.box)
            elif s.is_path():
                poly = s.path.polygon()
            if poly is None:
                continue
            bb = poly.bbox()
            cx, cy = (bb.left + bb.right) / 2.0, (bb.bottom + bb.top) / 2.0
            pts = list(poly.each_point_hull())
            changed = False
            newpts = []
            for p in pts:
                x, y = p.x, p.y
                if axis == "y":
                    ny = _asu_snap_coord(y, grid_dbu, mode, cy)
                    if ny != y:
                        y = ny; changed = True
                else:
                    nx = _asu_snap_coord(x, grid_dbu, mode, cx)
                    if nx != x:
                        x = nx; changed = True
                newpts.append(pya.Point(x, y))
            if changed:
                edits.append((s, pya.Polygon(newpts)))
        for s, np_ in edits:
            s.polygon = np_          # KLayout: assign to convert/replace in place
            n += 1
    return n

_asu_total = 0
'''


_VIA_BAR_HELPER = '''
# ===== ASU via-bar repair pass (2026-07-15) =====
# The seeded errors split each via-in-wide-metal landing into a multi-cut array;
# every min-via then fails the via-width-match rule (V.M.AUX.2/.3). Replace each
# flagged array with ONE continuous via BAR spanning the metal's length (keeping
# the min via thickness → NO lower-metal widening → no enclosure/spacing cascade).
# Upper routing layers only (V2/M3, V4/M5, V5/M6); V0/M1 is the device layer and
# must NOT be barred (it explodes enclosure/spacing + breaks connectivity).
def _asu_bar_pair(layout, via_ln, m_ln):
    top = layout.top_cell()
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
    todel = []
    for s in vsh.each():
        b = s.polygon.bbox() if s.is_polygon() else (s.box if s.is_box() else None)
        if b is None: continue
        for (ml, mbo, mr, mt, h) in landings:
            if b.left >= ml and b.right <= mr and b.bottom >= mbo and b.top <= mt:
                todel.append(s); break
    for s in todel: s.delete()
    n = 0
    for (ml, mbo, mr, mt, h), cuts in landings.items():
        if h:                                        # M horizontal: bar spans x
            th = cuts[0].height(); cy = (mbo + mt) // 2
            vsh.insert(pya.Box(ml, cy - th // 2, mr, cy - th // 2 + th))
        else:                                        # M vertical: bar spans y
            tw = cuts[0].width(); cx = (ml + mr) // 2
            vsh.insert(pya.Box(cx - tw // 2, mbo, cx - tw // 2 + tw, mt))
        n += 1
    return n
'''

# (via_layer, metal_layer) pairs safe to bar — upper routing only, NOT V0/M1
_BAR_PAIRS = [(25, 30), (45, 50), (55, 60)]   # V2/M3, V4/M5, V5/M6


def via_bar_pass(pairs=None) -> str:
    """Replace flagged multi-cut via arrays with continuous via bars. This is
    the ASU agent's primary repair (FVR 0.68-0.76 on all 5 public blocks)."""
    pairs = pairs or _BAR_PAIRS
    lines = [_VIA_BAR_HELPER, "_asu_bars = 0"]
    for vln, mln in pairs:
        lines.append(f"_asu_bars += _asu_bar_pair(layout, {vln}, {mln})")
    lines.append("print('[asu-repair] via-bars placed:', _asu_bars)")
    return "\n".join(lines) + "\n"


def grid_snap_pass(layers: list[str], mode: str = "nearest") -> str:
    """Snap off-grid edges on the given metal layers to their required grid.
    mode='outward' grows shapes to grid (preserves via enclosure); 'nearest'
    minimizes movement. `layers` e.g. ['M4','M5','M6']."""
    lines = [_SNAP_HELPER,
             "_asu_grid_nm = {'M4': 24, 'M5': 24, 'M6': 32}",
             "_asu_dbu_per_nm = 1.0 / (layout.dbu * 1000.0)"]
    for m in layers:
        if m not in _METAL_LD:
            continue
        ln, dt = _METAL_LD[m]
        axis = _GRID_AXIS.get(m, "y")
        lines.append(
            f"_asu_total += _asu_snap_layer(layout, {ln}, {dt}, "
            f"int(round(_asu_grid_nm['{m}'] * _asu_dbu_per_nm)), '{axis}', "
            f"'{mode}')")
    lines.append("print('[asu-repair] grid-snap edits:', _asu_total)")
    return "\n".join(lines) + "\n"
