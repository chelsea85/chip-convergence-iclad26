"""ASU block-repair agent — reduce DRC violations while preserving connectivity.

Design (mirrors our NVIDIA/NXP agents):
  1. DIAGNOSE (0 tokens): DRC report -> structured per-rule findings.
  2. REPAIR: try candidate fixes — deterministic geometric passes AND model-
     proposed pya fix-passes appended to the ORIGINAL script.
  3. VERIFY every candidate with the OFFICIAL evaluator's own render+DRC+
     connectivity, and KEEP-BEST by the contest's gated-lexicographic metric.
  4. ALWAYS SHIP the best ELIGIBLE script — the untouched original is eligible,
     so the agent can never score worse than baseline, and never break
     connectivity (a candidate that does is discarded).

Runner contract (AGENT_GUIDE): python3 asu_agent.py <info_json> [--model ...]
Reads paths from info.json, sends model calls to model_endpoint, writes the
repaired script to output_path, records usage.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drc_digest
import verify
import repairs

_WRITE_RE = re.compile(r"layout\.write\(\s*(['\"]).*?\1\s*\)")


def _strip_write(script: str) -> str:
    return _WRITE_RE.sub("", script)


@dataclass
class Paths:
    case: str
    layout_script: Path
    drc_report: Path
    rule_deck: Path
    connectivity: Path
    screenshot: Path
    output: Path
    temp: Path
    usage: Path
    eval_dir: Path

    @classmethod
    def from_info(cls, info_path: Path) -> "Paths":
        d = json.loads(Path(info_path).read_text())
        script = Path(d["path_to_layout_script"])
        # evaluator dir: sibling of the testcase tree
        eval_dir = _find_eval_dir(script)
        return cls(
            case=d.get("case_name", script.stem),
            layout_script=script,
            drc_report=Path(d["path_to_drc_report"]),
            rule_deck=Path(d["path_to_design_rule"]),
            connectivity=Path(d["path_to_connectivity_file"]),
            screenshot=Path(d.get("path_to_layout_screenshot", "")),
            output=Path(d["output_path"]),
            temp=Path(d["temp_dir"]),
            usage=Path(d.get("usage_path", "")),
            eval_dir=eval_dir)


def _find_eval_dir(script: Path) -> Path:
    for p in script.parents:
        cand = p / "evaluator"
        if (cand / "evaluate_repair.py").is_file():
            return cand
    raise SystemExit("could not locate evaluator/ relative to layout script")


def _vctx(P: Paths) -> verify.VContext:
    return verify.VContext(
        eval_dir=P.eval_dir, rule_path=P.rule_deck,
        drc_report_json=P.drc_report, conn_path=P.connectivity,
        workdir=P.temp / "asu_repair", case=P.case)


def _log(msg: str):
    print(f"[asu] {msg}", flush=True)


def run(P: Paths, model=None, max_calls: int = 6) -> dict:
    ctx = _vctx(P)
    original = P.layout_script.read_text(encoding="utf-8")
    orig_nw = _strip_write(original)
    digest = drc_digest.load(P.drc_report, P.case)
    _log(f"{P.case}: {digest.total_violations} ref violations, "
         f"{len(digest.findings)} rules")

    # baseline (untouched original) — the guaranteed-eligible floor
    best_script = original
    best = verify.measure(original, ctx, tag="baseline")
    _log(f"baseline: total={best.total} fvr={best.final_violation_rate} "
         f"eligible={best.eligible} conn={best.connectivity_preserved}")

    def consider(script: str, tag: str, note: str):
        nonlocal best, best_script
        r = verify.measure(script, ctx, tag=tag)
        status = (f"total={r.total} fvr={r.final_violation_rate} "
                  f"eligible={r.eligible} conn={r.connectivity_preserved}")
        if r.better_than(best):
            best, best_script = r, script
            _log(f"KEEP {tag} ({note}): {status}  <-- new best")
        else:
            _log(f"drop {tag} ({note}): {status}")
        return r

    # ── deterministic passes (0 tokens) ──────────────────────────────────────
    grid_layers = sorted({f.layer_hint for f in digest.by_kind("grid")
                          if f.layer_hint in ("M4", "M5", "M6")})
    if grid_layers:
        consider(orig_nw + "\n" + repairs.grid_snap_pass(grid_layers),
                 "grid-snap", f"layers={grid_layers}")

    # ── model-proposed fix passes: best-of-N with render-error repair ─────────
    if model is not None:
        from model_repair import (propose_fix_pass, build_prompt,
                                   REPAIR_SUFFIX, _extract_code, _compiles)
        calls = 0
        while calls < max_calls:
            calls += 1
            prompt = build_prompt(digest, orig_nw, best, P)
            snippet = propose_fix_pass(model, prompt)
            if not snippet:
                _log(f"model call {calls}: no usable/compiling fix pass")
                continue
            r = verify.measure(orig_nw + "\n" + snippet, ctx, tag=f"model-{calls}")
            # if it broke rendering, feed the error back once (off the main count)
            if not r.ok and r.error and calls < max_calls:
                calls += 1
                fixed = _extract_code(model.generate(
                    prompt + REPAIR_SUFFIX.format(err=r.error[:800],
                                                  code=snippet[:2500])))
                if fixed and _compiles(fixed):
                    snippet = fixed
                    r = verify.measure(orig_nw + "\n" + snippet, ctx,
                                       tag=f"model-{calls}r")
            note = f"model fix pass (call {calls})"
            status = (f"total={r.total} fvr={r.final_violation_rate} "
                      f"eligible={r.eligible}")
            if r.better_than(best):
                best, best_script = r, orig_nw + "\n" + snippet
                _log(f"KEEP model-{calls} ({note}): {status}  <-- new best")
            else:
                _log(f"drop model-{calls} ({note}): {status} err={r.error[:60]}")
            if best.eligible and best.final_violation_rate is not None \
                    and best.final_violation_rate <= 1.0:
                break     # beat the reference denominator — stop spending

    # ── emit best eligible ───────────────────────────────────────────────────
    P.output.parent.mkdir(parents=True, exist_ok=True)
    P.output.write_text(best_script, encoding="utf-8")
    _log(f"emitted {P.output.name}: fvr={best.final_violation_rate} "
         f"repair_rate={best.repair_rate} eligible={best.eligible}")

    if model is not None and P.usage:
        P.usage.parent.mkdir(parents=True, exist_ok=True)
        P.usage.write_text(json.dumps(getattr(model, "usage", {}), indent=1))
    return {"case": P.case, "final_violation_rate": best.final_violation_rate,
            "repair_rate": best.repair_rate, "eligible": best.eligible,
            "total": best.total}


def main(argv=None):
    ap = argparse.ArgumentParser(description="ASU block-repair agent")
    ap.add_argument("info_json", help="runner-provided info.json")
    ap.add_argument("--model", default="none",
                    help="none | stub | vertex | endpoint")
    ap.add_argument("--max-calls", type=int, default=6)
    a = ap.parse_args(argv)
    P = Paths.from_info(Path(a.info_json))
    model = None
    if a.model not in ("none", ""):
        from model_repair import make_model
        model = make_model(a.model, P)
    summary = run(P, model=model, max_calls=a.max_calls)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
