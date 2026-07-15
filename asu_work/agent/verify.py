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


@dataclass
class Result:
    ok: bool                          # render + DRC completed
    eligible: bool
    connectivity_preserved: bool
    total: int | None
    final_violation_rate: float | None
    repair_rate: float | None
    per_rule: dict = field(default_factory=dict)
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


def measure(script_text: str, ctx: VContext, tag: str = "cand") -> Result:
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
                      metrics.get("repair_rate"), counts,
                      error=f"connectivity: {str(e)[:160]}")

    total = sum(counts.values())
    eligible = conn_ok           # render+DRC already succeeded to get here
    return Result(True, eligible, conn_ok, total,
                  metrics.get("final_violation_rate"),
                  metrics.get("repair_rate"), counts)
