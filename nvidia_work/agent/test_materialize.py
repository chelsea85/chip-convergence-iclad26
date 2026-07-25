#!/usr/bin/env python3
"""SS11 migration slice 2 tests: the H1-H5 materialization path
(ppa/materialize.py) on the fake-tmake tree - frozen order, mutation-class
guards, post-gate H5 stability, and H5-as-sole-effective-input enforcement.
No Docker; regeneration runs the local fake tmake via the injected runner.
Reuses the checkpoint fixture from test_contract.
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ppa import contract as C                                    # noqa: E402
from ppa import materialize as M                                 # noqa: E402
from ppa.evaluate import _clamped_workers                        # noqa: E402
from test_contract import (TARGET, GEN_TARGET, make_tree, runner_for,
                           spec_for)                             # noqa: E402

PASS = FAIL = 0


def check(name, ok):
    global PASS, FAIL
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    PASS, FAIL = PASS + int(bool(ok)), FAIL + int(not ok)


class FakeWs:
    """Minimal workspace: root + contract/scope-validated overlay (mirrors
    Workspace.overlay semantics without repo cloning)."""
    def __init__(self, spec, root, scope):
        self.spec, self.root, self.scope = spec, root, scope

    def overlay(self, cand_files):
        ctr = C.get_contract(self.spec)
        C.validate_candidate(ctr, self.root, cand_files, self.scope)
        for rel, text in cand_files.items():
            (self.root / rel).write_text(
                text if text.endswith("\n") else text + "\n")


PROF = C.ValidationProfile(
    contract_schema="contract-v1", contest_commit="7623b53",
    container_digest="sha256:e258fff66f93", generator_digest="g1",
    reproduction_digest="r1", host_arch="arm64",
    evidence_root="nvdla_p04_evidence/")


def fresh(base_prefix="p04m_"):
    base = Path(tempfile.mkdtemp(prefix=base_prefix))
    make_tree(base)
    spec = spec_for(base)
    scope = C.CampaignScope(ip="fakenv", editable_targets=(TARGET,),
                            verification_policy="gate+lec")
    return base, spec, scope, FakeWs(spec, base, scope), runner_for(base)


def main():
    C._reset_tmake_registry()
    base, spec, scope, ws, run = fresh()
    C.register_tmake("fakenv", C.TmakeRegistration(
        layout=C.default_tmake_layout(spec),
        bound_validation_digest=PROF.digest()))
    ctr = C.get_contract(spec)
    pristine = (base / TARGET).read_text()
    EDIT = pristine.replace("assign y = a;", "assign y = a & 1'b1;")

    try:
        # ── happy path: steps 3-7 ────────────────────────────────────────────
        mrun = M.materialize_candidate(ws, ctr, scope, {TARGET: EDIT},
                                       runner=run, profile=PROF)
        m = mrun.mat
        check("steps 3-7: proceed with exact mapped closure",
              mrun.ok and m.classification == "proceed"
              and m.changed == (GEN_TARGET,))
        check("H1 != H2 (edit recorded from pristine workspace state)",
              m.h1[TARGET] != m.h2[TARGET])
        check("H3/H4 complete generated manifests present",
              len(m.h3) == 5 and len(m.h4) == 5)
        check("golden manifest retained for post-gate re-verification",
              len(mrun.golden) > len(m.h3))

        # H5 not yet established -> sole-input enforcement refuses
        try:
            M.effective_inputs(ws, ctr, mrun)
            check("effective inputs refused before the gate/H5", False)
        except C.ContractError as e:
            check("effective inputs refused before the gate/H5",
                  "H5" in str(e))

        # ── steps 9-11: gate rebuild (simulated) -> H5 == H4 ─────────────────
        ok, _ = ctr.regenerate(base, run)      # the gate's internal tmake
        check("gate-sim regeneration ok", ok)
        check("post_gate: H5 == H4 and golden intact", M.post_gate(ws, ctr, mrun))
        di = M.effective_inputs(ws, ctr, mrun)
        check("11: effective inputs are the CANDIDATE side, never .golden",
              di.side == "candidate"
              and not any(s.startswith(".golden/") for s in di.ordered_sources))
        gi = M.golden_inputs(ws, ctr, mrun)
        check("golden inputs re-verified and fully under .golden/",
              all(p.startswith(".golden/") for p in gi.ordered_sources))

        # ADV-9: a GENERATED source changed after H5 -> consumer refusal
        gen_f = base / "FAKE/outdir/nv_small/vmod/nvdla/pdp/unit.v"
        saved_gen = gen_f.read_text()
        gen_f.write_text("// post-H5 tamper\n")
        try:
            M.effective_inputs(ws, ctr, mrun)
            check("ADV-9: generated source mutated after H5 -> effective "
                  "inputs REFUSED (live revalidation)", False)
        except C.ContractError as e:
            check("ADV-9: generated source mutated after H5 -> effective "
                  "inputs REFUSED (live revalidation)",
                  "changed after H5" in str(e))
        gen_f.write_text(saved_gen)
        M.effective_inputs(ws, ctr, mrun)   # restored -> allowed again
        # ADV-10: a NON-outdir tool source changed after H5 -> refusal
        from test_contract import NONOUT_VLIB
        nv = base / NONOUT_VLIB
        saved_nv = nv.read_text()
        nv.write_text("module NV_DW_lsd_tampered(); endmodule\n")
        try:
            M.effective_inputs(ws, ctr, mrun)
            check("ADV-10: non-outdir source mutated after H5 -> effective "
                  "inputs REFUSED (inputs-digest binding)", False)
        except C.ContractError as e:
            check("ADV-10: non-outdir source mutated after H5 -> effective "
                  "inputs REFUSED (inputs-digest binding)",
                  "digest mismatch" in str(e))
        nv.write_text(saved_nv)

        # tamper after H4/H5: a second post_gate must fail
        (base / TARGET).write_text(pristine)
        ctr.regenerate(base, run)
        check("post-gate tamper -> H5 != H4 flow error",
              not M.post_gate(ws, ctr, mrun)
              and mrun.mat.classification == "flow-error")
        try:
            M.effective_inputs(ws, ctr, mrun)
            check("effective inputs refused after instability", False)
        except C.ContractError:
            check("effective inputs refused after instability", True)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # ── no-effective-change candidate refused downstream ─────────────────────
    base, spec2, scope, ws, run = fresh()
    C._reset_tmake_registry()
    C.register_tmake("fakenv", C.TmakeRegistration(
        layout=C.default_tmake_layout(spec2),
        bound_validation_digest=PROF.digest()))
    ctr = C.get_contract(spec2)
    pristine = (base / TARGET).read_text()
    try:
        mrun = M.materialize_candidate(
            ws, ctr, scope, {TARGET: pristine + "//STRIP note\n"},
            runner=run, profile=PROF)
        check("no-effective-change classified, not flow error",
              mrun.mat.classification == "no-effective-change")
        try:
            M.effective_inputs(ws, ctr, mrun)
            check("no-effective-change refused as effective input", False)
        except C.ContractError:
            check("no-effective-change refused as effective input", True)

        # scopeless refusal: normalized into a classified flow-error RECORD
        # (exception boundary, migration review SS5.2)
        m_ns = M.materialize_candidate(ws, ctr, None, {TARGET: pristine},
                                       runner=run)
        check("scopeless materialization -> flow-error record (normalized, "
              "auditable)", m_ns.mat.classification == "flow-error"
              and "contract violation" in m_ns.mat.detail)

        # pristine regeneration failure is a classified flow error
        tm = base / "FAKE/tools/bin/tmake"
        tm.write_text("#!/bin/bash\nexit 3\n")
        mfail = M.materialize_candidate(ws, ctr, scope, {TARGET: pristine},
                                        runner=run, profile=PROF)
        check("pristine regeneration failure -> flow-error record",
              mfail.mat.classification == "flow-error"
              and "pristine regeneration" in mfail.mat.detail)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # ── mutation-class guards: three evil generators ─────────────────────────
    # NOTE: the fake tmake cd's to the FAKE root, so evil paths are relative
    # to FAKE/ (tree.make, vmod/...) or its parent (../.golden).
    # first_invocation=True fires the evil during the PRISTINE run (reg 5);
    # exit_rc simulates a mutation + nonzero generator exit (reg 7).
    for label, evil, expect, first_inv, exit_rc in (
        ("immutable dependency (candidate)", "echo tampered >> tree.make",
         "immutable dependency", False, 0),
        ("ADV-5: immutable file on the PRISTINE invocation",
         "echo tampered >> tree.make", "pristine invocation", True, 0),
        ("ADV-6: leaf under an immutable DIRECTORY (spec/)",
         "echo tampered >> spec/defs/project.h", "immutable dependency",
         False, 0),
        ("ADV-6b: leaf under tools/", "echo x > tools/secret.cfg",
         "immutable dependency", False, 0),
        ("ADV-7: mutation + NONZERO generator exit still audited",
         "echo tampered >> tree.make", "immutable dependency", False, 5),
        ("ADV-8: immutable-membership change (new file under rams/)",
         "echo x > vmod/rams/new_member.v", "immutable dependency", False, 0),
        ("editable source", "echo '// gen touch' >> vmod/nvdla/pdp/core.v",
         "editable sources", False, 0),
        ("golden snapshot", "mkdir -p ../.golden/FAKE && "
         "echo x > ../.golden/FAKE/planted",
         "golden", False, 0),
    ):
        base, spec3, scope, ws, run = fresh()
        C._reset_tmake_registry()
        C.register_tmake("fakenv", C.TmakeRegistration(
            layout=C.default_tmake_layout(spec3),
            bound_validation_digest=PROF.digest()))
        ctr = C.get_contract(spec3)
        pristine = (base / TARGET).read_text()
        try:
            tm = base / "FAKE/tools/bin/tmake"
            script = tm.read_text()
            marker = base / "ranonce"
            neg = "! " if first_inv else ""
            tail = (f'if [ "$HAD" = 1 ]; then exit {exit_rc}; fi'
                    if exit_rc else ':')
            tm.write_text(script.replace(
                'echo "tmake: build vmod done"',
                f'HAD=0; [ -f "{marker}" ] && HAD=1\n'
                f'if [ {neg}"$HAD" = 1 ]; then {evil}; fi\n'
                f'touch "{marker}"\n'
                'echo "tmake: build vmod done"\n'
                f'{tail}'))
            mrun = M.materialize_candidate(
                ws, ctr, scope,
                {TARGET: pristine.replace("assign y = a;",
                                          "assign y = a & 1'b1;")},
                runner=run, profile=PROF)
            check(f"guard: generator mutating {label} -> flow-error",
                  mrun.mat.classification == "flow-error"
                  and expect in mrun.mat.detail)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    # ── SS8.7: symlinks under immutable roots cannot hide target mutation ────
    base, spec4, scope, ws, run = fresh()
    C._reset_tmake_registry()
    C.register_tmake("fakenv", C.TmakeRegistration(
        layout=C.default_tmake_layout(spec4),
        bound_validation_digest=PROF.digest()))
    ctr = C.get_contract(spec4)
    pristine = (base / TARGET).read_text()
    try:
        target_file = base / "external_header.h"
        target_file.write_text("`define X 1\n")
        hdr = base / "FAKE/spec/defs/project.h"
        hdr.unlink()
        hdr.symlink_to(target_file)
        m_sym = M.materialize_candidate(ws, ctr, scope, {TARGET: pristine},
                                        runner=run, profile=PROF)
        check("SS8.7: leaf symlink under an immutable root -> flow-error "
              "(aliases forbidden, target mutation cannot hide)",
              m_sym.mat.classification == "flow-error"
              and "symlink" in m_sym.mat.detail)
        hdr.unlink(); hdr.write_text("// fake spec\n")
        dlink = base / "FAKE/spec/linked"
        (base / "spec_ext").mkdir(exist_ok=True)
        dlink.symlink_to(base / "spec_ext")
        m_sym2 = M.materialize_candidate(ws, ctr, scope, {TARGET: pristine},
                                         runner=run, profile=PROF)
        check("SS8.7b: DIRECTORY symlink under an immutable root -> "
              "flow-error", m_sym2.mat.classification == "flow-error"
              and "symlink" in m_sym2.mat.detail)
        dlink.unlink()
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # ── worker cap consumed at the evaluator ─────────────────────────────────
    from ppa import registry
    registry.ensure_registered()
    check("evaluator clamps nvdla workers to the contract cap (4 -> 1)",
          _clamped_workers("nvdla", 4) == 1)
    check("evaluator leaves direct IPs at requested workers",
          _clamped_workers("async_fifo", 4) == 4)

    print(f"\ntest_materialize: {PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
