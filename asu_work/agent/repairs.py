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
