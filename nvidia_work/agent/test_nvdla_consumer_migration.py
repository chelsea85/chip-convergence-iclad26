#!/usr/bin/env python3
"""Offline regressions for the NVDLA consumer migration (2026-07-25).

No Docker/model calls.  Exercises the trace-shaped gate, its negative and
survival controls, nested response mapping, measurement evidence binding and
the rich-evidence -> EvalResult fail-closed status algebra.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ppa import contract as C                                    # noqa: E402
from ppa import evaluate as E                                    # noqa: E402
from ppa import gate as G                                        # noqa: E402
from ppa import measure_tmake as MT                              # noqa: E402
from ppa import proposer as PR                                   # noqa: E402
from ppa import registry as R                                    # noqa: E402
from ppa.config import IPS                                       # noqa: E402
from test_contract import TARGET                                 # noqa: E402
from test_migration3 import fixture                              # noqa: E402

PASS = FAIL = 0


def check(name, ok):
    global PASS, FAIL
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    PASS, FAIL = PASS + int(bool(ok)), FAIL + int(not ok)


def raises(name, fn):
    try:
        fn()
        check(name, False)
    except C.ContractError:
        check(name, True)


def trace_plan(*, fail=False, editable_roots=("FAKE/vmod/nvdla/pdp",),
               env=None):
    if fail:
        result = (
            "echo '[FAIL] pdp_bad'; echo 'Done: 0 passed, 1 failed'; exit 1")
    else:
        result = "echo '[PASS] pdp_good'; echo 'Done: 1 passed, 0 failed'"
    build = (
        "mkdir -p FAKE/outdir/build FAKE/verif/trace && "
        f"printf '#!/bin/bash\\n{result}\\n' > "
        "FAKE/outdir/build/testrunner && "
        "chmod +x FAKE/outdir/build/testrunner && "
        "printf '#!/bin/bash\\nexec ../../outdir/build/testrunner\\n' > "
        "FAKE/verif/trace/run_trace.sh && "
        "chmod +x FAKE/verif/trace/run_trace.sh")
    return G.TraceGatePlan(
        clean_dirs=("FAKE/outdir/build",),
        regen_cmd="cd FAKE && ./tools/bin/tmake -clean -build vmod",
        build_cmd=build,
        exe_path="FAKE/outdir/build/testrunner",
        test_cwd="FAKE/verif/trace",
        test_env=env or (
            ("TEST_PREFIXES", "pdp_good"),
            ("TEST_TIMEOUT_SEC", "30"),
        ),
        test_driver="run_trace.sh",
        editable_roots=editable_roots)


def main():
    # ── plan shape and registered production defaults ──────────────────────
    R.ensure_registered()
    prod = G.get_gate_plan("nvdla")
    check("D1: production NVDLA registration is a trace-shaped plan",
          isinstance(prod, G.TraceGatePlan)
          and prod.schema == "tmake-trace-gate-v1")
    check("D1: non-degenerate pristine-passing PDP trace is the default",
          dict(prod.test_env)["TEST_PREFIXES"]
          == "pdp_1x3x8_8x8_ave_int8_0")
    check("D1: plan binds the PDP editable partition to the PDP trace",
          prod.editable_roots == ("NVDLA/vmod/nvdla/pdp",))
    injected = trace_plan(env=(
        ("TEST_PREFIXES", "pdp; touch /tmp/p04_injected"),
        ("TEST_TIMEOUT_SEC", "30"),
    )).test_cmd()
    check("D1: trace environment values are shell-quoted data",
          "TEST_PREFIXES='pdp; touch /tmp/p04_injected'" in injected
          and "TEST_PREFIXES=pdp;" not in injected)
    raises(
        "D1: duplicate trace environment names fail at construction",
        lambda: trace_plan(env=(("TEST_PREFIXES", "a"),
                                ("TEST_PREFIXES", "b"))))

    # ── positive trace gate ────────────────────────────────────────────────
    base, spec, scope, ctr, ws, run, mrun = fixture()
    try:
        rec = G.run_tmake_gate(
            ws, ctr, mrun, trace_plan(), runner=run, scope=scope)
        check("D1 positive: CLEAN/REGENERATE/BUILD/TRACE/PARSE is complete",
              rec.passed and rec.candidate_aware
              and [p.name for p in rec.phases]
              == ["CLEAN", "REGENERATE", "BUILD", "EXECUTE_TESTS",
                  "PARSE_RESULTS"])
        check("D1 positive: artifact + driver + H5 are hash-bound",
              len(rec.exe_sha) == len(rec.driver_sha) == 64
              and rec.h4_root == rec.h5_root
              and len(rec.ref()) == 64)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # ── counted functional negative ────────────────────────────────────────
    base, spec, scope, ctr, ws, run, mrun = fixture()
    try:
        rec = G.run_tmake_gate(
            ws, ctr, mrun, trace_plan(fail=True), runner=run, scope=scope)
        check("D1 negative: counted trace failure is never candidate-aware",
              not rec.passed and not rec.candidate_aware
              and rec.tests_failed == 1
              and "trace tests failed" in rec.detail)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # ── regeneration survival tripwire ─────────────────────────────────────
    base, spec, scope, ctr, ws, run, mrun = fixture()
    try:
        # Simulate an edit that existed only in generated output: the editable
        # source no longer matches the H4 candidate before the gate regenerates.
        (base / TARGET).write_text(
            "module core(input a, output y);\n"
            "assign y = a;\nendmodule\n")
        rec = G.run_tmake_gate(
            ws, ctr, mrun, trace_plan(), runner=run, scope=scope)
        check("D1 survival: regenerated root must reproduce candidate H4",
              not rec.passed and not rec.candidate_aware
              and "did not reproduce" in rec.detail)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    base, spec, scope, ctr, ws, run, mrun = fixture()
    try:
        rec = G.run_tmake_gate(
            ws, ctr, mrun,
            trace_plan(editable_roots=("FAKE/vmod/nvdla/top",)),
            runner=run, scope=scope)
        check("D1 scope: a trace for another partition refuses the PDP edit",
              not rec.passed and "does not cover" in rec.detail)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # ── exact nested-path response mapping ─────────────────────────────────
    IPS["fakenv"] = spec
    mapped = PR.parse_response(
        "fakenv",
        "// FILE: core.v\nmodule core(input a, output y);\n"
        "assign y = a;\nendmodule\n",
        allowed_paths=[TARGET])
    check("D3: model basename maps to the exact scoped nested tmake path",
          tuple(mapped) == (TARGET,))

    # ── measurement evidence binding ───────────────────────────────────────
    old_measure = E.measure
    try:
        E.measure = lambda ws, label="m": {
            "area": 9.0, "cells": 90.0, "ff": 8.0,
            "setup": 2.0, "hold": 0.1, "timing_met": True,
            "power": 0.01}

        class Inputs:
            def __init__(self, digest):
                self._digest = digest

            def digest(self):
                return self._digest

        fn = MT.make_measure_fn(
            {"area": 10.0, "cells": 100.0, "ff": 9.0,
             "setup": 0.0, "hold": 0.1, "timing_met": True,
             "power": 0.02},
            30.0, label="fakenv-deadbeef")
        m1 = fn(None, Inputs("a" * 64))
        m2 = fn(None, Inputs("b" * 64))
        check("D2: full DesignInputs digest binds measurement evidence",
              m1.ok and m2.ok and m1.ref != m2.ref
              and fn.last_ppa["area"] == 9.0)
        bad = fn(None, Inputs("not-a-digest"))
        check("D2: malformed input identity fails measurement closed",
              not bad.ok and bad.adp is None and bad.base_adp is None)
    finally:
        E.measure = old_measure

    # ── adapter status algebra ─────────────────────────────────────────────
    candidate = E.Candidate("fakenv", {TARGET: "module x; endmodule\n"},
                            cid="c" * 64)
    base_record = {
        "cid": "c" * 64, "classification": "proceed", "detail": "",
        "gate": {"passed": True, "tests": [1, 0]},
        "proof": {"verdict": "PROVEN"},
        "measurement": {"ok": True},
        "ppa": {"area": 9.0, "cells": 90.0, "ff": 8.0,
                "setup": 2.0, "hold": 0.1, "timing_met": True,
                "power": 0.01},
        "verify": {"gate": {"status": "PASS"},
                   "lec": {"status": "PROVEN"}},
        "eligible": True, "refusal_reason": None,
    }
    ok = E._tmake_adapter_result(candidate, base_record, 1.0)
    pending = E._tmake_adapter_result(
        candidate,
        {**base_record, "eligible": False,
         "refusal_reason": "CONTRACT_VALIDATION_PENDING"}, 1.0)
    gate_fail = E._tmake_adapter_result(
        candidate,
        {**base_record, "eligible": False,
         "gate": {"passed": False, "tests": [0, 1]}}, 1.0)
    lec_fail = E._tmake_adapter_result(
        candidate,
        {**base_record, "eligible": False,
         "proof": {"verdict": "INCONCLUSIVE"}}, 1.0)
    check("D3: only an eligible complete row maps to measured",
          ok.status == "measured")
    check("D3: PENDING retains diagnostic PPA but cannot be accepted",
          pending.status == "contract-pending" and pending.ppa is not None)
    check("D3: gate and LEC failures retain distinct statuses",
          gate_fail.status == "gate-fail"
          and lec_fail.status == "lec-inconclusive")

    # Partial wiring must retain the legacy refusal, not fall into sources=().
    G._reset_gate_plans()
    MT._reset_measure_providers()
    raises(
        "D3: partial tmake wiring keeps evaluate_many fail-closed",
        lambda: E.evaluate_many(
            [candidate], scope=scope,
            container_digest="sha256:" + "e" * 64,
            tool_versions={"yosys": "0.63"}))

    # Restore canonical process-local production bindings for later suites.
    C._reset_tmake_registry()
    R.ensure_registered()
    IPS.pop("fakenv", None)

    print(f"\ntest_nvdla_consumer_migration: {PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
