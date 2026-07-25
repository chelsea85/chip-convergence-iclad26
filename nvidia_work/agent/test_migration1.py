#!/usr/bin/env python3
"""SS11 consumer-migration slice 1 tests (re-review5 SS7.1-2, no Docker):
literal production NVDLA registration, immutable RunContext with worker
provenance, and the capability gate with mandatory PENDING refusal - proving
NO model call can occur while the production NVDLA contract is unvalidated.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ppa import contract as C                                    # noqa: E402
from ppa import controller, registry                             # noqa: E402
from ppa.config import IPS, REPO                                 # noqa: E402

PASS = FAIL = 0


def check(name, ok):
    global PASS, FAIL
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    PASS, FAIL = PASS + int(bool(ok)), FAIL + int(not ok)


def main():
    if not (REPO / "NVDLA").is_dir():
        print("PREREQ-MISSING: contest NVDLA tree not present at", REPO)
        return 3

    # ── step 1: literal production registration ──────────────────────────────
    registry.ensure_registered()
    registry.ensure_registered()          # idempotent
    check("nvdla registered in IPS (never reaches discovery)",
          "nvdla" in IPS and IPS["nvdla"].contract == "tmake")
    check("nvdla TmakeRegistration present and H-1 UNBOUND",
          "nvdla" in C.TMAKE_REGISTRY
          and C.TMAKE_REGISTRY["nvdla"].bound_validation_digest is None)
    ctr = C.get_contract(IPS["nvdla"])
    check("production contract resolves via sealed registry; PENDING",
          isinstance(ctr, C.TmakeContract)
          and ctr.validation_state() == "PENDING"
          and ctr.layout is registry.NVDLA_LAYOUT)
    model = ctr.filelist_model(REPO)
    check("literal layout characterizes the real tree (323/22/4)",
          len(model.sources) == 323 and len(model.include_roots) == 22
          and len(model.defines) == 4)
    check("spec facts: top/clocks/resets literal",
          IPS["nvdla"].top == "NV_nvdla"
          and IPS["nvdla"].clocks[0].period_ns == 30.0
          and ("dla_reset_rstn", 0) in IPS["nvdla"].resets)

    # ── step 1: immutable run context with worker provenance ─────────────────
    TARGET = "NVDLA/vmod/nvdla/pdp/NV_NVDLA_PDP_core.v"
    scope = C.CampaignScope(ip="nvdla", editable_targets=(TARGET,),
                            verification_policy="gate+lec",
                            requested_workers=4)
    rc = C.build_run_context(ctr, scope)
    check("RunContext: effective=1 (tmake cap) with FULL provenance",
          rc.effective_workers == 1 and rc.requested_workers == 4
          and rc.contract_cap == 1 and rc.global_cap == 8
          and rc.validation_state == "PENDING"
          and rc.provenance()["scope_id"] == scope.scope_id())
    try:
        rc.effective_workers = 8
        check("RunContext immutable", False)
    except Exception:
        check("RunContext immutable", True)
    try:
        C.build_run_context(ctr, C.CampaignScope(
            ip="othernv", editable_targets=(TARGET,),
            verification_policy="gate+lec"))
        check("RunContext refuses wrong-IP scope", False)
    except C.ContractError:
        check("RunContext refuses wrong-IP scope", True)

    # ── step 2: capability gate / PENDING refusal ────────────────────────────
    refusal = C.campaign_refusal(ctr)
    check("refusal record: reason + expected(None)/current identities",
          refusal is not None
          and refusal["reason"] == "CONTRACT_VALIDATION_PENDING"
          and refusal["expected_profile_digest"] is None
          and refusal["current_profile_digest"] is None
          and refusal["ip"] == "nvdla")
    prof = C.ValidationProfile(
        contract_schema="contract-v1", contest_commit="7623b53",
        container_digest="sha256:e258fff66f93", generator_digest="g1",
        reproduction_digest="r1", host_arch="arm64",
        evidence_root="nvdla_p04_evidence/")
    r2 = C.campaign_refusal(ctr, prof)
    check("self-created profile still refused; current identity recorded",
          r2 is not None and r2["current_profile_digest"] == prof.digest())
    check("direct/sv2v contracts are never refused",
          C.campaign_refusal(C.get_contract(IPS["async_fifo"])) is None
          and C.campaign_refusal(C.get_contract(IPS["ascon"])) is None)

    # controller gate: a NON-stub model on pending nvdla must raise BEFORE any
    # model call, and persist the structured refusal (to a TEMP ledger -
    # migration review SS4.2: the test must not pollute the real ledger)
    import tempfile as _tf
    _ltmp = Path(_tf.mkdtemp(prefix="mig1led_"))
    _old_ledger = controller.LEDGER_DIR
    controller.LEDGER_DIR = _ltmp

    class _FakeRealModel:                 # not StubModel -> a "real" campaign
        calls = 0
        def generate(self, *a, **k):
            _FakeRealModel.calls += 1
            return ""
    try:
        refusals = controller.LEDGER_DIR / "refusals.jsonl"
        try:
            controller._campaign_gate(IPS["nvdla"], _FakeRealModel())
            check("gate: real model on PENDING nvdla refused", False)
        except C.ContractError as e:
            check("gate: real model on PENDING nvdla refused",
                  "CONTRACT_VALIDATION_PENDING" in str(e))
        after = refusals.read_text().splitlines()
        rec = json.loads(after[-1])
        check("gate: structured refusal persisted (reason + identities + ts)",
              len(after) == 1
              and rec["reason"] == "CONTRACT_VALIDATION_PENDING"
              and rec["ip"] == "nvdla" and "ts" in rec
              and rec["expected_profile_digest"] is None)
        check("gate: zero model calls occurred while pending",
              _FakeRealModel.calls == 0)

        # ADV-1 (migration review SS4.2): a class merely NAMED StubModel is a
        # REAL model - identity is isinstance, never a name string
        class _StubLike:
            pass
        _StubLike.__name__ = "StubModel"
        try:
            controller._campaign_gate(IPS["nvdla"], _StubLike())
            check("ADV-1: class NAMED 'StubModel' is REFUSED while PENDING "
                  "(no name spoof)", False)
        except C.ContractError:
            check("ADV-1: class NAMED 'StubModel' is REFUSED while PENDING "
                  "(no name spoof)", True)

        # ADV-2: the GENUINE production StubModel is the explicit keyless mode
        from ppa.proposer import make_model
        real_stub = make_model("stub", replay_dirs=[])
        controller._campaign_gate(IPS["nvdla"], real_stub)
        check("ADV-2: genuine StubModel (isinstance) allowed while PENDING "
              "(keyless validation mode)", True)
        controller._campaign_gate(IPS["async_fifo"], _FakeRealModel())
        check("gate: validated families pass with a real model", True)

        # ADV-3: a matching BOUND profile reaches VALIDATED through the
        # production path (registered bound contract + RunContext)
        import dataclasses as _dc
        spec_b = _dc.replace(IPS["nvdla"], name="nvdlabound")
        C.register_tmake("nvdlabound", C.TmakeRegistration(
            layout=registry.NVDLA_LAYOUT,
            bound_validation_digest=prof.digest()))
        IPS["nvdlabound"] = spec_b
        try:
            ctr_b = C.get_contract(spec_b)
            rcx = C.build_run_context(
                ctr_b, C.CampaignScope(ip="nvdlabound",
                                       editable_targets=(TARGET,),
                                       verification_policy="gate+lec"),
                prof)
            check("ADV-3: bound profile -> VALIDATED via RunContext; "
                  "real model passes the gate",
                  rcx.validation_state == "VALIDATED"
                  and C.campaign_refusal(ctr_b, prof) is None)
            controller._campaign_gate(spec_b, _FakeRealModel(), prof)
            check("ADV-3b: gate passes for the bound contract + profile", True)
        finally:
            IPS.pop("nvdlabound", None)
    finally:
        controller.LEDGER_DIR = _old_ledger
        import shutil as _sh
        _sh.rmtree(_ltmp, ignore_errors=True)

    print(f"\ntest_migration1: {PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
