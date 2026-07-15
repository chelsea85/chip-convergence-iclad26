"""Repair-loop verification — render + DRC + connectivity, measured with the
OFFICIAL evaluator's own functions so our inner-loop numbers are identical to
the scoring machine's. Runs KLayout 0.30.1 (on PATH inside the Docker image).

measure(script_text, ctx) -> Result with:
  eligible               (renders + DRC ran) AND (connectivity preserved)
  connectivity_preserved
  total                  final DRC violation count (our env)
  final_violation_rate   final / original(reference JSON)   [lower is better]
  repair_rate            fixed / original                   [higher is better]
  per_rule               {rule: count}
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _load_evaluator(eval_dir: Path):
    """Import the contest evaluator module by path (guarantees identical
    counting/metric logic to official scoring)."""
    if str(eval_dir) not in sys.path:
        sys.path.insert(0, str(eval_dir))
    spec = importlib.util.spec_from_file_location(
        "asu_evaluate_repair", eval_dir / "evaluate_repair.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@dataclass
class VContext:
    eval_dir: Path            # .../evaluator
    rule_path: Path           # asap7.lydrc
    drc_report_json: Path     # reference BlockN.drc.json (original counts)
    conn_path: Path           # connectivity/BlockN.json
    workdir: Path             # scratch for renders/reports
    case: str = "block"
    _ev: object = None

    def ev(self):
        if self._ev is None:
            self._ev = _load_evaluator(self.eval_dir)
        return self._ev


# Rendered-geometry connectivity signature (credibility check, Option A per the
# 2026-07-15 review). The official connectivity gate parses the SOURCE text and
# cannot see appended geometry mutations — so a degenerate candidate could
# delete rendered geometry, cut DRC, and still "pass". This signature is
# computed from the RENDERED GDS: number of connected conducting components
# (nets, via-linked across layers) + total conducting area + per-layer shape
# counts. A credible repair must not change the component count, must not drop
# conducting area, and must not lose immutable pin/via shapes.
_CONN_SIG_KLS = '''
import pya, json, sys
gds = sys.argv[1] if len(sys.argv)>1 else "IN_GDS"
ly = pya.Layout(); ly.read(gds)
top = ly.top_cell()
COND = [(19,0),(20,0),(30,0),(40,0),(50,0),(60,0),   # M1..M6
        (18,0),(21,0),(25,0),(35,0),(45,0),(55,0)]   # V0..V5
per_layer = {}; allr = pya.Region()
for ln,dt in COND:
    li = ly.layer(pya.LayerInfo(ln,dt))
    reg = pya.Region(top.begin_shapes_rec(li))
    per_layer[f"{ln}/{dt}"] = reg.count()
    allr += reg
allr.merge()                       # touching/overlapping conductors merge = nets
comps = allr.count()               # connected-component (polygon) count
area = allr.area()
print(json.dumps({"components": comps, "conducting_area": area,
                  "per_layer": per_layer}))
'''


def _conn_signature(ev, gds_path: Path, wd: Path) -> dict | None:
    kls = wd / "conn_sig.py"
    kls.write_text(_CONN_SIG_KLS.replace("IN_GDS", str(gds_path)))
    try:
        import subprocess
        r = subprocess.run(["klayout", "-b", "-r", str(kls), str(gds_path)],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, timeout=300)
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("{") and "components" in line:
                import json as _j
                return _j.loads(line)
    except Exception:
        return None
    return None


def connectivity_credible(baseline_sig: dict, cand_sig: dict,
                          area_tol: float = 0.02) -> tuple[bool, str]:
    """Compare a candidate's rendered-connectivity signature to the baseline's.
    Credible iff net/component count unchanged and conducting area not dropped
    beyond tolerance (a big drop = degenerate geometry removal)."""
    if not baseline_sig or not cand_sig:
        return False, "signature unavailable"
    if cand_sig["components"] != baseline_sig["components"]:
        return False, (f"net count changed {baseline_sig['components']}→"
                       f"{cand_sig['components']} (short/open)")
    b_area, c_area = baseline_sig["conducting_area"], cand_sig["conducting_area"]
    if b_area and (b_area - c_area) / b_area > area_tol:
        return False, (f"conducting area dropped {b_area}→{c_area} "
                       f"({100*(b_area-c_area)/b_area:.1f}%) — geometry removal")
    return True, "rendered connectivity credible"


@dataclass
class Result:
    ok: bool                          # render + DRC completed
    eligible: bool
    connectivity_preserved: bool
    total: int | None
    final_violation_rate: float | None
    repair_rate: float | None
    per_rule: dict = field(default_factory=dict)
    conn_sig: dict = None             # rendered-connectivity signature (opt-in)
    error: str = ""

    def better_than(self, other: "Result | None") -> bool:
        """Gated-lexicographic, matching the contest: eligible first, then
        minimize final_violation_rate, then maximize repair_rate."""
        if not self.eligible:
            return False
        if other is None or not other.eligible:
            return True
        if self.final_violation_rate != other.final_violation_rate:
            return self.final_violation_rate < other.final_violation_rate
        return (self.repair_rate or 0) > (other.repair_rate or 0)


def measure(script_text: str, ctx: VContext, tag: str = "cand",
            want_conn_sig: bool = False) -> Result:
    ev = ctx.ev()
    wd = ctx.workdir / tag
    wd.mkdir(parents=True, exist_ok=True)
    cand = wd / "cand.py"
    cand.write_text(script_text, encoding="utf-8")

    render = wd / "render.py"
    gds = wd / "out.gds"
    lyrpt = wd / "out.lyrpt"
    try:
        ev.prepare_render_script(cand, render, gds)
        ev.run_command(["klayout", "-b", "-r", str(render)],
                       "render", wd / "render.log", 900)
        ev.run_klayout_drc(gds, ctx.rule_path, lyrpt, wd / "drc.log")
    except Exception as e:                       # render/DRC failure = ineligible
        return Result(False, False, False, None, None, None, error=str(e)[:200])

    sig = _conn_signature(ev, gds, wd) if want_conn_sig else None

    counts = ev.read_lyrpt_counts(lyrpt)
    original = ev.read_original_counts(ctx.drc_report_json)
    metrics = ev.calculate_drc_metrics(original, counts)

    # connectivity gate (the evaluator's own checker, on our candidate script)
    try:
        conn = ev.evaluate_connectivity(ctx.conn_path, cand)
        conn_ok = bool(conn.get("connectivity_preserved"))
    except Exception as e:
        return Result(True, False, False, sum(counts.values()),
                      metrics.get("final_violation_rate"),
                      metrics.get("repair_rate"), counts, conn_sig=sig,
                      error=f"connectivity: {str(e)[:160]}")

    total = sum(counts.values())
    eligible = conn_ok           # render+DRC already succeeded to get here
    return Result(True, eligible, conn_ok, total,
                  metrics.get("final_violation_rate"),
                  metrics.get("repair_rate"), counts, conn_sig=sig)
