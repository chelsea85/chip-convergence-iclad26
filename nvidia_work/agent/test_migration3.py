#!/usr/bin/env python3
"""Corrective-slice tests (migration review SS8/SS9): hardened LEC parser,
full structural gate with artifact binding, evidence-derived policy,
B.2 evaluation identity + stale-cache refusal, legacy gate rc, and the
production tmake orchestration end-to-end (fake tree, no Docker).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
from ppa import contract as C                                    # noqa: E402
from ppa import evaluate as E                                    # noqa: E402
from ppa import gate as G                                        # noqa: E402
from ppa import materialize as M                                 # noqa: E402
from ppa import orchestrate as O                                 # noqa: E402
from ppa import policy as P                                      # noqa: E402
from ppa import verify as V                                      # noqa: E402
from test_contract import TARGET, make_tree, runner_for, spec_for  # noqa: E402
from test_materialize import PROF, FakeWs                        # noqa: E402

PASS = FAIL = 0


def check(name, ok):
    global PASS, FAIL
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    PASS, FAIL = PASS + int(bool(ok)), FAIL + int(not ok)


def raises(fn, name):
    try:
        fn()
        check(name, False)
    except C.ContractError:
        check(name, True)


# REALISTIC yosys 0.63 proven log: equiv_simple ENTRY line ("Found N unproven
# ... (N groups) in equiv:", the cells QUEUED for proving) is present in EVERY
# real proof. The earlier fixture omitted it, which hid a verdict bug that made
# PROVEN unreachable (caught by a host release control 2026-07-23).
OK_OUT = """equiv_simple: Found 381209 unproven $equiv cells (35523 groups) in equiv:
equiv_simple: Proved 381209 previously unproven $equiv cells.
equiv_status: Found 381209 $equiv cells in equiv:
equiv_status:   Of those cells 381209 are proven and 0 are unproven.
Equivalence successfully proven!
"""
UNPROVEN_OUT = """equiv_simple: Found 502 unproven $equiv cells (502 groups) in equiv:
equiv_simple: Proved 400 previously unproven $equiv cells.
equiv_induct: Found 102 unproven $equiv cells in module equiv:
equiv_status: Found 502 $equiv cells in equiv:
equiv_status:   Of those cells 400 are proven and 102 are unproven.
"""
ZERO_OUT = """Found 0 $equiv cells in equiv.
Of those cells 0 are proven and 0 are unproven.
"""
# ADV: earlier all-proven block, later contradictory unproven block
CONTRADICTORY = """Found 10 $equiv cells in equiv.
Of those cells 10 are proven and 0 are unproven.
Equivalence successfully proven!
Found 10 $equiv cells in equiv.
Of those cells 9 are proven and 1 are unproven.
"""
LATE_UNPROVEN = OK_OUT + "Found 3 unproven $equiv cells in module equiv!\n"


def gate_plan(**kw):
    base = dict(
        clean_dirs=("FAKE/outdir/build",),
        regen_cmd="cd FAKE && ./tools/bin/tmake -clean -build vmod",
        build_cmd="mkdir -p FAKE/outdir/build",
        link_cmd=("printf '#!/bin/bash\\necho 30 PASS, 0 FAIL\\n' "
                  "> FAKE/outdir/build/testrunner && chmod +x "
                  "FAKE/outdir/build/testrunner"),
        exe_path="FAKE/outdir/build/testrunner")
    base.update(kw)
    return G.GatePlan(**base)


REF = "e" * 64   # content-digest evidence refs (64-hex required)


def fixture():
    base = Path(tempfile.mkdtemp(prefix="p04c_"))
    make_tree(base)
    spec = spec_for(base)
    scope = C.CampaignScope(ip="fakenv", editable_targets=(TARGET,),
                            verification_policy="gate+lec")
    C._reset_tmake_registry()
    C.register_tmake("fakenv", C.TmakeRegistration(
        layout=C.default_tmake_layout(spec),
        bound_validation_digest=PROF.digest()))
    ctr = C.get_contract(spec)
    ws = FakeWs(spec, base, scope)
    run = runner_for(base)
    pristine = (base / TARGET).read_text()
    mrun = M.materialize_candidate(
        ws, ctr, scope,
        {TARGET: pristine.replace("assign y = a;", "assign y = a & 1'b1;")},
        runner=run, profile=PROF)
    assert mrun.ok, mrun.mat.detail
    return base, spec, scope, ctr, ws, run, mrun


def main():
    # ── hardened LEC parser (SS4.6; regressions 16-17) ───────────────────────
    pr = V.lec_verdict(0, OK_OUT)
    check("PROVEN: rc0 + success + consistent counts",
          pr.verdict == "PROVEN" and pr.total == 381209)
    check("REGRESSION (2026-07-23): a REAL proof log with the equiv_simple "
          "ENTRY line ('Found N unproven ... (N groups) in equiv') is PROVEN "
          "- the entry line is not a residual failure",
          V.lec_verdict(0, OK_OUT).verdict == "PROVEN"
          and "unproven $equiv cells (" in OK_OUT)
    check("ADV-16: earlier success + later contradictory block -> FLOW_ERROR, "
          "never PROVEN",
          V.lec_verdict(0, CONTRADICTORY).verdict == "FLOW_ERROR")
    check("ADV-16b: success + later unproven mention -> INCONCLUSIVE, never "
          "PROVEN", V.lec_verdict(0, LATE_UNPROVEN).verdict == "INCONCLUSIVE")
    check("unproven cells -> INCONCLUSIVE/nonconvergent",
          V.lec_verdict(1, UNPROVEN_OUT).verdict == "INCONCLUSIVE")
    check("zero compared points -> FLOW_ERROR",
          V.lec_verdict(0, ZERO_OUT).reason == "zero_compared_points")
    check("success without counts -> FLOW_ERROR",
          V.lec_verdict(0, "Equivalence successfully proven!").reason
          == "malformed_status")
    check("rc!=0 never PROVEN", V.lec_verdict(2, OK_OUT).verdict != "PROVEN")
    check("v2 recipe pinned", "equiv_induct -seq 4" in V._EQUIV_PASSES
          and "equiv_status -assert" in V._EQUIV_PASSES)

    # ── legacy gate rc fail-closed (SS4.9; regression 27) ────────────────────
    tmp = Path(tempfile.mkdtemp(prefix="p04lg_"))
    try:
        r = subprocess.run(
            ["bash", str(Path("../harness/run_gate.sh").resolve()), "fake",
             str(tmp), "echo TEST PASSED; exit 7"],
            capture_output=True, text=True)
        check("ADV-27: run_gate.sh 'TEST PASSED; exit 7' -> nonzero exit + "
              "FAIL, banner never wins",
              r.returncode == 7 and "GATE: FAIL" in r.stdout
              and "GATE-RC: 7" in r.stdout)
        r2 = subprocess.run(
            ["bash", str(Path("../harness/run_gate.sh").resolve()), "fake",
             str(tmp), "echo 3 PASS, 0 FAIL"],
            capture_output=True, text=True)
        check("legacy gate positive path intact (rc0 + summary -> PASS)",
              r2.returncode == 0 and "GATE: PASS" in r2.stdout
              and "GATE-RC: 0" in r2.stdout)
        # REGRESSION (2026-07-23 release-control catch): the OpenTitan
        # Verilator TBs report success with the banner "Simulation passed!"
        # and NO per-test count. The parser must PASS it (rc0 + banner + no
        # fail markers) - a "require positive count" rule wrongly FAILed the
        # real aes/prim/ascon pristine gate.
        r3 = subprocess.run(
            ["bash", str(Path("../harness/run_gate.sh").resolve()), "ascon",
             str(tmp), "echo 'Simulation passed!'"],
            capture_output=True, text=True)
        check("OpenTitan verilator 'Simulation passed!' (uncounted banner) "
              "-> GATE: PASS", r3.returncode == 0 and "GATE: PASS" in r3.stdout)
        r4 = subprocess.run(
            ["bash", str(Path("../harness/run_gate.sh").resolve()), "ascon",
             str(tmp), "echo 'Simulation failed!'"],
            capture_output=True, text=True)
        check("verilator 'Simulation failed!' -> GATE: FAIL",
              r4.returncode != 0 and "GATE: FAIL" in r4.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ── structural gate with artifact binding (SS4.5; reg 11-15) ─────────────
    raises(lambda: G.GatePlan(clean_dirs=(), regen_cmd="x", build_cmd="x",
                              link_cmd="x", exe_path=""),
           "unbound GatePlan (no clean dirs / exe) is not "
           "eligibility-capable")
    raises(lambda: gate_plan(clean_dirs=("FAKE/outdir/../vmod/nvdla",)),
           "SS8.5: `..` traversal in clean_dirs rejected AT CONSTRUCTION")
    raises(lambda: gate_plan(clean_dirs=("/abs/build",)),
           "absolute clean dir rejected")
    raises(lambda: gate_plan(exe_path="FAKE/verif/runner"),
           "exe outside every clean root rejected (stale-survival guard)")
    # FIX-3: alias validation is UNCONDITIONAL - a clean dir under a
    # parent-component symlink is rejected even when the leaf does not exist
    base_fx, spec_fx, scope_fx, ctr_fx, ws_fx, run_fx, mrun_fx = fixture()
    try:
        (base_fx / "FAKE/outdir/real").mkdir(parents=True, exist_ok=True)
        (base_fx / "FAKE/outdir/alias").symlink_to(base_fx / "FAKE/outdir/real")
        plan_fx = gate_plan(clean_dirs=("FAKE/outdir/alias/nonexistent",),
                            exe_path="FAKE/outdir/alias/nonexistent/r")
        rec_fx = G.run_tmake_gate(ws_fx, ctr_fx, mrun_fx, plan_fx,
                                  runner=run_fx, scope=scope_fx)
        check("FIX-3: nonexistent clean leaf under a symlinked parent still "
              "rejected (unconditional alias walk)",
              not rec_fx.passed and "symlink" in rec_fx.detail.lower())
    finally:
        shutil.rmtree(base_fx, ignore_errors=True)

    check("SS8.4: any plan command change changes the plan digest",
          gate_plan().digest() != gate_plan(test_args=("-x",)).digest()
          and gate_plan().digest()
          != gate_plan(build_cmd="mkdir -p FAKE/outdir/build && true"
                       ).digest())

    base, spec, scope, ctr, ws, run, mrun = fixture()
    try:
        rec = G.run_tmake_gate(ws, ctr, mrun, gate_plan(), runner=run,
                               scope=scope)
        check("gate: full H.4e phases (incl. separate LINK) with real rc + "
              "artifact hash",
              rec.passed and rec.candidate_aware and rec.tests_passed == 30
              and [p.name for p in rec.phases]
              == ["CLEAN", "REGENERATE", "COMPILE", "LINK", "EXECUTE_TESTS",
                  "PARSE_RESULTS"]
              and len(rec.exe_sha) == 64)
        check("SS8.4b: gate ref covers plan+phases+counts (regen-cmd change "
              "would change identity)", len(rec.ref()) == 64
              and rec.plan_digest == gate_plan().digest())
        # SS8.1: a plan whose regen is NOT the contract generator is refused
        rec_fake = G.run_tmake_gate(
            ws, ctr, mrun, gate_plan(regen_cmd="true"), runner=run,
            scope=scope)
        check("SS8.1: regen_cmd=true (not the contract recipe) refused - "
              "never candidate-aware",
              not rec_fake.passed and not rec_fake.candidate_aware
              and "not the contract generator" in rec_fake.detail)
        # FIX-1 shell-injection inert: a test_args token beginning with `;`
        # is a QUOTED argument to the artifact, never a second command
        # (corrective2 SS4.1). The artifact exits 7 -> gate FAILS.
        inj = G.run_tmake_gate(
            ws, ctr, mrun,
            gate_plan(link_cmd=("printf '#!/bin/bash\\nexit 7\\n' > "
                                "FAKE/outdir/build/testrunner && chmod +x "
                                "FAKE/outdir/build/testrunner"),
                      test_args=("; echo", "30 PASS, 0 FAIL")),
            runner=run, scope=scope)
        check("FIX-1: `; echo 30 PASS, 0 FAIL` as test_args is an INERT "
              "argument - artifact exit 7 -> gate FAILS, not candidate-aware",
              not inj.passed and not inj.candidate_aware)
        raises(lambda: G.GatePlan(
            clean_dirs=("FAKE/outdir/build",),
            regen_cmd="x", build_cmd="x", link_cmd="x",
            exe_path="FAKE/outdir/build/r", test_args="not-a-tuple"),
               "FIX-1b: free-form string test_args refused (tuple required)")
        di = M.effective_inputs(ws, ctr, mrun)
        check("gate PASS -> frozen receipt -> effective inputs",
              di.side == "candidate" and mrun.receipt is not None
              and mrun.receipt.inputs_digest == di.digest())
        frz = M.freeze_receipt(mrun)
        check("SS8.8: MaterializationReceipt transitively frozen + "
              "self-validated", frz.classification == "proceed"
              and len(frz.ref()) == 64)

        # proof adapter: canned yosys output through the PRODUCTION path
        canned = lambda cmd, timeout=1800: SimpleNamespace(  # noqa: E731
            returncode=0, stdout=OK_OUT, stderr="")
        ws.write = lambda rel, text: (base / rel).parent.mkdir(
            parents=True, exist_ok=True) or (base / rel).write_text(text)
        proof = V.lec_tmake(ws, ctr, mrun, runner=canned)
        check("ADV-20: production proof binds top/side digests/script/log to "
              "the H5 receipt",
              proof.result.verdict == "PROVEN"
              and proof.cand_inputs_digest == mrun.receipt.inputs_digest
              and proof.h5_root == mrun.receipt.h5_root
              and len(proof.script_sha) == 64 and len(proof.log_sha) == 64)

        # evidence-derived policy over the FROZEN receipt
        run_ctx = C.build_run_context(ctr, scope, PROF)
        meas = P.MeasurementEvidence(ok=True, adp=0.9, base_adp=1.0, ref=REF)
        raises(lambda: P.MeasurementEvidence(ok=True, adp=float("-inf"),
                                             base_adp=1.0, ref=REF),
               "SS8.12: adp=-inf rejected at construction")
        raises(lambda: P.MeasurementEvidence(ok=True, adp=float("nan"),
                                             base_adp=1.0, ref=REF),
               "SS8.12b: NaN adp rejected")
        raises(lambda: P.MeasurementEvidence(ok=True, adp=-0.5, base_adp=1.0,
                                             ref=REF),
               "SS8.12c: negative adp rejected")
        raises(lambda: P.CheckEvidence(True, "checks:1"),
               "SS8.11: free-string evidence ref rejected (64-hex required)")
        ok_ev = P.EvaluationEvidence(
            run_context=run_ctx, refusal_reason=None,
            expected_top=spec.top, receipt=frz, failure=None,
            gate=rec, proof=proof, measurement=meas,
            checks=P.CheckEvidence(True, REF),
            proxy=P.CheckEvidence(True, REF),
            budget=P.CheckEvidence(True, REF))
        pol = P.evaluate_policy(ok_ev)
        check("policy: eligible from BOUND evidence only; 15 conditions",
              pol.eligible and len(pol.conditions) == 15)
        check("ADV-22: every PASS condition carries a nonempty evidence ref",
              all(c.evidence for c in pol.conditions if c.status == "PASS"))
        check("assurance label composite",
              "candidate_aware" in pol.assurance_label)

        try:
            P.EvaluationEvidence(
                run_context=run_ctx, refusal_reason=None,
                expected_top=spec.top,
                receipt=SimpleNamespace(classification="proceed"),
                failure=None, gate=None, proof=None, measurement=None)
            check("ADV-21: SimpleNamespace evidence rejected", False)
        except C.ContractError:
            check("ADV-21: SimpleNamespace evidence rejected", True)

        # SS8.8b: mutating the BUILDER after freezing changes nothing
        saved_cls = mrun.mat.classification
        mrun.mat.classification = "flow-error"
        pol_again = P.evaluate_policy(ok_ev)
        check("SS8.8b: builder mutation after freeze does not change the "
              "policy verdict", pol_again.eligible)
        mrun.mat.classification = saved_cls

        # SS8.10: a CORRECTLY computed root still cannot construct a result
        conds = tuple(P.ConditionResult(name=n, status="PASS", evidence=REF)
                      for n in P.CONDITIONS)
        good_root = P._conditions_root(P.POLICY_SCHEMA, conds)
        try:
            P.EligibilityResult(schema=P.POLICY_SCHEMA, conditions=conds,
                                evidence_root=good_root)
            check("SS8.10: manual all-PASS with a CORRECT root still "
                  "refused (factory-guarded)", False)
        except C.ContractError:
            check("SS8.10: manual all-PASS with a CORRECT root still "
                  "refused (factory-guarded)", True)

        # unbound proof (wrong receipt binding) cannot satisfy lec_proven_v2
        import dataclasses as _dc
        bad_proof = _dc.replace(proof, cand_inputs_digest="0" * 64)
        pol_bad = P.evaluate_policy(_dc.replace(ok_ev, proof=bad_proof))
        check("ADV-18: valid counts under the WRONG input digest -> "
              "lec_proven_v2 FAIL",
              not pol_bad.eligible
              and any(c.name == "lec_proven_v2" and c.status == "FAIL"
                      for c in pol_bad.conditions))

        # evaluation identity + stale-cache (SS4.8; reg 25)
        kw = dict(source_cid="c" * 64,
                  registration_digest=C.registration_digest(ctr),
                  container_digest="sha256:" + "e" * 64,
                  tool_versions={"yosys": "0.63", "opensta": "2.4"})
        e0 = P.evaluation_identity(ok_ev, **kw)
        check("identity deterministic full sha256",
              e0 == P.evaluation_identity(ok_ev, **kw) and len(e0) == 64)
        raises(lambda: P.evaluation_identity(
            ok_ev, source_cid="cand01", registration_digest="short",
            container_digest="sha256:" + "e" * 64,
            tool_versions={"yosys": "0.63"}),
               "non-digest source cid + registration refused")
        raises(lambda: P.evaluation_identity(
            ok_ev, source_cid="c" * 64,
            registration_digest=C.registration_digest(ctr),
            container_digest="iclad-dev:v1",
            tool_versions={"yosys": "0.63"}),
               "tag-only container digest refused (full sha256 required)")
        # SS8.14: plan change -> new gate evidence -> new identity
        import dataclasses as _dcx
        rec2 = G.run_tmake_gate(ws, ctr, mrun,
                                gate_plan(test_args=("-verbose",)),
                                runner=run, scope=scope)
        ev_plan2 = _dcx.replace(ok_ev, gate=rec2)
        check("SS8.14: gate PLAN change changes the evaluation identity",
              rec2.plan_digest != rec.plan_digest
              and P.evaluation_identity(ev_plan2, **kw)
              != P.evaluation_identity(ok_ev, **kw))
        scope2 = C.CampaignScope(ip="fakenv", editable_targets=(TARGET,),
                                 verification_policy="gate+lec+dualsim")
        ev2 = _dc.replace(ok_ev,
                          run_context=C.build_run_context(ctr, scope2, PROF))
        check("ADV-25: changed scope/policy identity -> different id",
              P.evaluation_identity(ev2, **kw) != e0)
        good_row = {"evaluation_id": e0, "eligible": pol.eligible,
                    "policy": pol.record()}
        tampered = {"evaluation_id": e0, "eligible": True,
                    "policy": "tampered"}
        check("SS8.15: validated cache - good row hits; TAMPERED row with a "
              "matching id is a MISS; changed id MISSES",
              P.cache_lookup([good_row], e0) is not None
              and P.cache_lookup([tampered], e0) is None
              and P.cache_lookup([good_row],
                                 P.evaluation_identity(ev2, **kw)) is None)
        # FIX-4: 15 COPIES of one PASS condition with a correctly recomputed
        # root must NOT validate (condition-name uniqueness required)
        one = pol.record()["conditions"][0]
        dup_conds = [dict(one) for _ in P.CONDITIONS]
        dup_tup = tuple(P.ConditionResult(name=c["name"], status=c["status"],
                                          reason=c["reason"],
                                          evidence=c["evidence"])
                        for c in dup_conds)
        forged = {"evaluation_id": e0, "eligible": True,
                  "policy": {"schema": P.POLICY_SCHEMA,
                             "eligible": True,
                             "evidence_root": P._conditions_root(
                                 P.POLICY_SCHEMA, dup_tup),
                             "conditions": dup_conds}}
        check("FIX-4: 15 copies of one condition + correct root is a cache "
              "MISS (uniqueness enforced)",
              P.cache_lookup([forged], e0) is None)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # gate failure modes on fresh fixtures
    for label, plan_mut, script_note, expect in (
        ("SS8.2: link produces no artifact -> never candidate-aware",
         {"link_cmd": "true"}, None, "no artifact"),
        ("SS8.3: test executes the DECLARED artifact - a failing artifact "
         "cannot be masked by banners",
         {"link_cmd": ("printf '#!/bin/bash\\necho ALL TESTS PASSED\\n"
                       "exit 7\\n' > FAKE/outdir/build/testrunner && chmod "
                       "+x FAKE/outdir/build/testrunner")}, None, "rc=7"),
        ("ADV-14a: zero tests -> failure",
         {"link_cmd": ("printf '#!/bin/bash\\necho built ok\\n' > "
                       "FAKE/outdir/build/testrunner && chmod +x "
                       "FAKE/outdir/build/testrunner")}, None, "zero tests"),
        ("ADV-14b: contradictory summaries -> failure",
         {"link_cmd": ("printf '#!/bin/bash\\necho 30 PASS, 0 FAIL\\necho "
                       "29 PASS, 1 FAIL\\n' > FAKE/outdir/build/testrunner "
                       "&& chmod +x FAKE/outdir/build/testrunner")}, None,
         "contradictory"),
    ):
        base, spec, scope, ctr, ws, run, mrun = fixture()
        try:
            import dataclasses as _dc
            plan = _dc.replace(gate_plan(), **plan_mut)
            rec = G.run_tmake_gate(ws, ctr, mrun, plan, runner=run,
                                   scope=scope)
            check(label, not rec.passed and not rec.candidate_aware
                  and expect in rec.detail)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    # ADV-12: stale passing binary + no rebuild -> refused
    base, spec, scope, ctr, ws, run, mrun = fixture()
    try:
        stale = base / "FAKE/outdir/build/testrunner"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("#!/bin/bash\necho 30 PASS, 0 FAIL\n")
        stale.chmod(0o755)
        plan = gate_plan(link_cmd="true")
        rec = G.run_tmake_gate(ws, ctr, mrun, plan, runner=run, scope=scope)
        check("ADV-12: stale passing binary is CLEANed; no rebuild -> "
              "failure, never a pass from the stale artifact",
              not rec.passed and "no artifact" in rec.detail)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # ── production orchestration end-to-end (SS4.1; reg 26) ──────────────────
    # FRESH tree (no prior materialization - the orchestrator owns the whole
    # candidate lifecycle from a pristine workspace)
    base = Path(tempfile.mkdtemp(prefix="p04o_"))
    make_tree(base)
    spec = spec_for(base)
    scope = C.CampaignScope(ip="fakenv", editable_targets=(TARGET,),
                            verification_policy="gate+lec")
    C._reset_tmake_registry()
    C.register_tmake("fakenv", C.TmakeRegistration(
        layout=C.default_tmake_layout(spec),
        bound_validation_digest=PROF.digest()))
    ws = FakeWs(spec, base, scope)
    run = runner_for(base)
    ltmp = Path(tempfile.mkdtemp(prefix="p04led_"))
    old_ledger = E.LEDGER_DIR
    from ppa.config import IPS as _IPS
    try:
        E.LEDGER_DIR = ltmp
        _IPS["fakenv"] = spec
        canned = lambda_ok = None

        def orch_runner(cmd, timeout=1800):
            if cmd.startswith("yosys"):
                return SimpleNamespace(returncode=0, stdout=OK_OUT, stderr="")
            return run(cmd, timeout)

        def measure_fn(w, di):
            return P.MeasurementEvidence(ok=True, adp=0.9, base_adp=1.0,
                                         ref=di.digest())

        ws.write = lambda rel, text: (base / rel).parent.mkdir(
            parents=True, exist_ok=True) or (base / rel).write_text(text)
        pristine = (base / TARGET).read_text()
        rec = O.evaluate_tmake_candidate(
            "fakenv",
            {TARGET: pristine.replace("assign y = a;",
                                      "assign y = a & 1'b1;")},
            scope, gate_plan(), ws=ws, runner=orch_runner, profile=PROF,
            measure_fn=measure_fn,
            checks=P.CheckEvidence(True, "e" * 64),
            proxy=P.CheckEvidence(True, "e" * 64),
            budget=P.CheckEvidence(True, "e" * 64),
            container_digest="sha256:" + "e" * 64,
            tool_versions={"yosys": "0.63"})
        check("ADV-26: production orchestration -> eligible record with "
              "evaluation id + policy + evidence roots persisted",
              rec["eligible"] and rec["evaluation_id"]
              and rec["policy"]["evidence_root"]
              and rec["gate"]["candidate_aware"]
              and rec["proof"]["verdict"] == "PROVEN")
        check("cached_evaluation: exact VALIDATED identity hit; wrong id "
              "miss; recomputed cid recorded",
              O.cached_evaluation(spec.name, rec["evaluation_id"]) is not None
              and O.cached_evaluation(spec.name, "0" * 64) is None
              and len(rec["cid"]) == 64)
        # SS8.17: the legacy evaluator explicitly refuses tmake
        try:
            E.evaluate_many([E.Candidate(ip="fakenv",
                                         files={TARGET: pristine})])
            check("SS8.17: legacy evaluator refuses tmake contracts", False)
        except C.ContractError as e:
            check("SS8.17: legacy evaluator refuses tmake contracts",
                  "orchestrate" in str(e))
    finally:
        E.LEDGER_DIR = old_ledger
        _IPS.pop("fakenv", None)
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(ltmp, ignore_errors=True)

    # mixed-IP batch refused (SS5.6)
    try:
        E.evaluate_many([E.Candidate(ip="a", files={"x": "y"}),
                         E.Candidate(ip="b", files={"x": "y"})])
        check("mixed-IP evaluate_many refused", False)
    except (ValueError, AssertionError):
        check("mixed-IP evaluate_many refused", True)

    print(f"\ntest_migration3: {PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
