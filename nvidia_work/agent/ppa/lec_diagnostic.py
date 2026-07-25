"""LEC key-point diagnostic (HOST/Docker only) — why is a candidate INCONCLUSIVE?

When the assurance-aware selector refuses a PPA-better candidate because its
LEC verdict is INCONCLUSIVE (e.g. sha512's 0.7216 arith transform), this tool
classifies WHY, WITHOUT changing the canonical shipping recipe. It answers the
question that decides the candidate's fate:

  COMBINATIONALLY_PROVABLE   equiv_simple proves every cell with NO induction
                             -> a register-preserving rewrite; genuinely
                             equivalent. If the canonical recipe missed it,
                             that's a recipe gap worth a Codex review (NOT an
                             auto-ship).
  SEQUENTIALLY_PROVABLE@seqN  equiv_simple leaves cells but equiv_induct -seq N
                             converges. DIAGNOSTIC ONLY: deeper -seq needs
                             reset/synchronization evidence before it can
                             confer canonical eligibility (Codex A.2) — report
                             the depth, never auto-upgrade the recipe.
  INEQUIVALENT               equiv found a real difference (unproven remain and
                             a counterexample is recorded) -> the candidate is
                             WRONG; drop it. This is the important safety
                             outcome: an INCONCLUSIVE candidate that is really
                             inequivalent (the ascon _rejected lesson).
  TRULY_NONCONVERGENT        cells remain unproven at every tried depth with no
                             counterexample -> unprovable with these tools;
                             stays non-shippable (correct conservative default).

Output is EVIDENCE for a human/Codex decision. It never emits, banks, or
changes the submission or the shipping LEC recipe.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from . import verify as V
from .config import IPS
from .discover import get_spec, register
from .workspace import Workspace, candidate_from_dir, pristine_source

EVIDENCE = Path("/private/tmp/nvdla_lec_diag_evidence")
_RE_SIMPLE_LEFT = re.compile(r"Found (\d+) unproven \$equiv cells in module")
_RE_CEX = re.compile(r"Found a counterexample|Trying to prove.*failed|"
                     r"proof failed|inequivalent", re.I)


def _golden_gate_script(spec, gold_files, gate_files, extra_passes: str) -> str:
    """Two-sided equiv script reusing verify._read_stanza (the tested read
    recipe), with a swappable equivalence tail."""
    return (V._read_stanza(gold_files, spec.top, for_sat=True)
            + "design -stash gold\n"
            + V._read_stanza(gate_files, spec.top, for_sat=True)
            + "design -stash gate\n"
            + f"design -copy-from gold -as gold {spec.top}\n"
            + f"design -copy-from gate -as gate {spec.top}\n"
            + "equiv_make gold gate equiv\nhierarchy -top equiv\n"
            + extra_passes)


def _run(ws, script: str, name: str, timeout: int) -> tuple[int, str]:
    ws.write(f".lecdiag/{name}.ys", script)
    try:
        r = V.run_lec_command(
            ws.run, f"yosys .lecdiag/{name}.ys 2>&1", timeout)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return None, f"TIMEOUT after {timeout}s"


def diagnose(ip: str, variant_dir: Path, timeout: int = 1800) -> dict:
    if ip not in IPS:
        register(get_spec(ip))
    spec = IPS[ip]
    cand = candidate_from_dir(ip, variant_dir)
    ws = Workspace.create(ip, cand, tag=f"lecdiag_{int(time.time())}")
    result = {"ip": ip, "variant_dir": str(variant_dir),
              "top": spec.top, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "ladder": [], "classification": "?"}
    try:
        gold_dir = ws.root / ".lecdiag_gold"
        gold_dir.mkdir(exist_ok=True)
        gold_files = []
        for rel in spec.sources:
            (gold_dir / Path(rel).name).write_text(pristine_source(ip, rel))
            gold_files.append(f".lecdiag_gold/{Path(rel).name}")
        gate_files = list(spec.sources)

        # L1: combinational SAT only (equiv_simple, NO induction)
        rc, out = _run(ws, _golden_gate_script(
            spec, gold_files, gate_files,
            "equiv_simple -short\nequiv_status\n"), "L1_simple", timeout)
        pr = V.lec_verdict(rc, out)
        left = _RE_SIMPLE_LEFT.search(out)
        left_n = int(left.group(1)) if left else (
            0 if pr.verdict == "PROVEN" else None)
        cex = bool(_RE_CEX.search(out))
        result["ladder"].append({"level": "L1_equiv_simple",
                                  "verdict": pr.verdict, "unproven_after": left_n,
                                  "counterexample": cex})
        if pr.verdict == "PROVEN" or left_n == 0:
            result["classification"] = "COMBINATIONALLY_PROVABLE"
            return _finish(ws, result, out)

        # L2: sequential induction ladder (DIAGNOSTIC depths)
        for seq in (4, 8, 16):
            rc, out = _run(ws, _golden_gate_script(
                spec, gold_files, gate_files,
                f"equiv_simple -short\nequiv_induct -seq {seq}\n"
                "equiv_status -assert\n"), f"L2_seq{seq}", timeout)
            pr = V.lec_verdict(rc, out)
            cex = bool(_RE_CEX.search(out))
            result["ladder"].append({"level": f"L2_induct_seq{seq}",
                                     "verdict": pr.verdict,
                                     "proven": pr.proven, "unproven": pr.unproven,
                                     "counterexample": cex})
            if pr.verdict == "PROVEN":
                result["classification"] = f"SEQUENTIALLY_PROVABLE@seq{seq}"
                result["note"] = ("DIAGNOSTIC ONLY: deeper -seq needs reset/sync "
                                  "evidence before canonical eligibility (Codex "
                                  "A.2); do not auto-upgrade the shipping recipe")
                return _finish(ws, result, out)
            if cex or pr.verdict == "INEQUIVALENT":
                result["classification"] = "INEQUIVALENT"
                result["note"] = "real counterexample -> candidate is WRONG, drop it"
                return _finish(ws, result, out)

        result["classification"] = "TRULY_NONCONVERGENT"
        result["note"] = ("unprovable at seq<=16 with no counterexample; stays "
                          "non-shippable (correct conservative default)")
        return _finish(ws, result, out)
    finally:
        ws.destroy()


def _finish(ws, result: dict, last_out: str) -> dict:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"lecdiag_{result['ip']}_{time.strftime('%m%d_%H%M%S')}.log"
     ).write_text(last_out[-20000:])
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="classify WHY a candidate is LEC-INCONCLUSIVE (host only)")
    ap.add_argument("--ip", required=True)
    ap.add_argument("--variant-dir", required=True,
                    help="dir of the candidate .v files to diagnose (e.g. the "
                         "emitted experimental_best)")
    a = ap.parse_args(argv)
    res = diagnose(a.ip, Path(a.variant_dir))
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / f"lecdiag_{a.ip}_{time.strftime('%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(res, indent=2))
    print(f"\n=== LEC diagnostic: {a.ip} ===")
    for step in res["ladder"]:
        print(f"  {step['level']:20} verdict={step['verdict']} "
              f"{ {k: v for k, v in step.items() if k not in ('level','verdict')} }")
    print(f"  CLASSIFICATION: {res['classification']}")
    if res.get("note"):
        print(f"  note: {res['note']}")
    print(f"  -> {out}")
    # exit codes: 0 provable (comb or seq), 1 inequivalent, 2 nonconvergent
    if res["classification"].startswith(("COMBINATIONALLY", "SEQUENTIALLY")):
        return 0
    return 1 if res["classification"] == "INEQUIVALENT" else 2


if __name__ == "__main__":
    sys.exit(main())
