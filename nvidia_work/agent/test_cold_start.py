#!/usr/bin/env python3
"""Cold-start hidden-testcase drill (repeatable).

Simulates what happens at DAC: an IP the agent has never seen appears in the
contest repo. Copies async_fifo under a throwaway name, then runs the FULL
path — discover -> fresh baseline (Docker synth+STA) -> propose (stub replay)
-> verify -> measure -> objective decision — and asserts:

  1. the registry/ledger key is the LOCATION name, not env.sh DESIGN_NAME
     (a DESIGN_NAME collision with a known IP must not alias onto its
     cached baseline — bug found+fixed 2026-07-11)
  2. a fresh baseline is measured and cached under that key
  3. the variant round completes with an explicit accept/reject decision

Run: python3 test_cold_start.py        (~15s; needs Docker)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NV = HERE.parent
REPO = (HERE.parents[1] / "ICLAD-Hackathon-2026" /
        "problem-categories" / "ICLAD26-NVIDIA-Problems")
DRILL = "drill_hidden_ip"
LEDGER = HERE / "ledger"


def cleanup():
    shutil.rmtree(REPO / DRILL, ignore_errors=True)
    shutil.rmtree(HERE / "work" / DRILL, ignore_errors=True)
    shutil.rmtree(LEDGER / "reports" / DRILL, ignore_errors=True)
    (LEDGER / f"{DRILL}_baseline.json").unlink(missing_ok=True)
    (LEDGER / f"{DRILL}.jsonl").unlink(missing_ok=True)
    (LEDGER / f"{DRILL}_rounds.jsonl").unlink(missing_ok=True)


def main() -> int:
    cleanup()
    src = REPO / "async_fifo"
    dst = REPO / DRILL
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
        "build", "obj_dir*", "syn_results", "reports"))
    failures = 0
    try:
        r = subprocess.run(
            [sys.executable, "-m", "ppa.controller", "--ip", DRILL,
             "--rounds", "1", "--k", "1", "--model", "stub",
             "--stub-replay", str(NV / "exp1_graycomb")],
            cwd=HERE, capture_output=True, text=True, timeout=1800)
        out = r.stdout + r.stderr

        base_file = LEDGER / f"{DRILL}_baseline.json"
        checks = [
            ("controller exit 0", r.returncode == 0),
            (f"registry key is location name [{DRILL}]",
             f"[{DRILL}]" in out),
            ("DESIGN_NAME did NOT alias onto async_fifo ledger",
             "[async_fifo]" not in out),
            ("fresh baseline cached under drill key", base_file.is_file()),
            ("round reached an explicit decision",
             ("accept" in out or "reject" in out)),
        ]
        if base_file.is_file():
            ppa = json.loads(base_file.read_text())["ppa"]
            checks.append(("baseline PPA sane (cells>0, area>0)",
                           ppa["cells"] > 0 and ppa["area"] > 0))
        for name, ok in checks:
            print(f"[{'PASS' if ok else 'FAIL'}] {name}")
            failures += 0 if ok else 1
        if failures:
            print("--- controller output tail ---")
            print(out[-1500:])
        print(f"cold-start drill: {len(checks)-failures}/{len(checks)} PASS")
    finally:
        cleanup()
    return failures


if __name__ == "__main__":
    sys.exit(main())
