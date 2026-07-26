"""The production tmake evaluation path (corrective slice 2; review SS4.9).

ONE orchestration owning RunContext -> pristine workspace -> materialize ->
structural gate (canonical registered plan) -> H5 receipt -> FROZEN
MaterializationReceipt -> receipt-revalidated proof/measurement -> frozen
EvaluationEvidence -> evaluate_policy -> evaluation_identity -> validated
ledger record.

Dispatch is EXPLICIT and fail-closed: the legacy evaluator refuses tmake
contracts (`evaluate._refuse_tmake`), and this orchestrator refuses non-tmake
families. The source CID is RECOMPUTED here from the candidate content -
caller labels are never trusted. Internally created workspaces are always
destroyed in a finally block; the ledger row retains the policy record, all
evidence refs, and the raw proof script/log hashes for later revalidation.
"""
from __future__ import annotations

import hashlib
import json

from . import contract as C
from . import gate as G
from . import materialize as M
from . import policy as P
from . import verify as V
from .config import IPS
from .evaluate import ledger_append, ledger_read


def source_cid(cand_files: dict) -> str:
    h = hashlib.sha256()
    for rel in sorted(cand_files):
        h.update(rel.encode())
        h.update(cand_files[rel].encode())
    return h.hexdigest()


def evaluate_tmake_candidate(ip: str, cand_files: dict, scope,
                             plan: "G.GatePlan | G.TraceGatePlan | None" = None,
                             *, ws=None, runner=None, profile=None,
                             measure_fn=None,
                             checks=None, proxy=None, budget=None,
                             container_digest: str, tool_versions: dict
                             ) -> dict:
    spec = IPS[ip]
    ctr = C.get_contract(spec)
    if ctr.name != "tmake":
        raise C.ContractError(
            f"orchestrator evaluates tmake contracts only; {ip!r} is "
            f"'{ctr.name}' (use the legacy evaluator)")
    refusal = C.campaign_refusal(ctr, profile)
    run_ctx = C.build_run_context(ctr, scope, profile)
    cid = source_cid(cand_files)          # RECOMPUTED, never caller-supplied

    own_ws = ws is None
    if own_ws:
        from .workspace import Workspace
        ws = Workspace.create(ip, tag=f"orc_{cid[:8]}", scope=scope)
    try:
        runner_ = runner or ws.run
        mrun = M.materialize_candidate(ws, ctr, scope, cand_files,
                                       runner=runner_, profile=profile)
        gate_ev = proof_ev = meas_ev = receipt = None
        if mrun.ok:
            gate_ev = G.run_tmake_gate(ws, ctr, mrun, plan, runner=runner_,
                                       scope=scope)
            if gate_ev.passed:
                receipt = M.freeze_receipt(mrun)   # TRANSITIVELY frozen
                proof_ev = V.lec_tmake(ws, ctr, mrun, runner=runner_,
                                       timeout=V._lec_timeout(spec))
                if measure_fn is not None:
                    di = M.effective_inputs(ws, ctr, mrun)
                    meas_ev = measure_fn(ws, di)
                    if meas_ev is not None and not isinstance(
                            meas_ev, P.MeasurementEvidence):
                        raise C.ContractError(
                            "measure_fn must return MeasurementEvidence")

        if not mrun.ok:
            failure = f"{mrun.mat.classification}: {mrun.mat.detail}"
        elif gate_ev is None:
            failure = "gate evidence missing"
        elif not gate_ev.passed:
            failure = f"gate refused: {gate_ev.detail}"
        elif receipt is None:
            failure = "gate passed without a frozen receipt"
        else:
            failure = None

        ev = P.EvaluationEvidence(
            run_context=run_ctx,
            refusal_reason=refusal["reason"] if refusal else None,
            expected_top=spec.top,
            receipt=receipt,
            failure=failure,
            gate=gate_ev, proof=proof_ev, measurement=meas_ev,
            checks=checks, proxy=proxy, budget=budget)
        result = P.evaluate_policy(ev)
        eval_id = P.evaluation_identity(
            ev, source_cid=cid,
            registration_digest=C.registration_digest(ctr),
            container_digest=container_digest, tool_versions=tool_versions
        ) if receipt is not None else None

        gate_status = None
        if gate_ev is not None:
            gate_status = ("PASS" if gate_ev.passed else
                           "FAIL" if gate_ev.tests_failed > 0
                           else "FLOW_ERROR")
        proof_status = (proof_ev.result.verdict
                        if proof_ev is not None else None)
        raw_ppa = getattr(measure_fn, "last_ppa", None)
        verify = {}
        if gate_status is not None:
            verify["gate"] = {
                "status": gate_status, "detail": gate_ev.detail}
        if proof_status is not None:
            verify["lec"] = {
                "status": proof_status,
                "detail": (f"recipe={proof_ev.result.recipe_id} "
                           f"rc={proof_ev.result.rc} "
                           f"total={proof_ev.result.total} "
                           f"proven={proof_ev.result.proven} "
                           f"unproven={proof_ev.result.unproven} "
                           f"reason={proof_ev.result.reason}")}
            verify["dualsim"] = {
                "status": "SKIP(size)",
                "detail": "whole-design NVDLA dualsim is diagnostic-only"}

        record = {
            "cid": cid, "ip": ip,
            "evaluation_id": eval_id,
            "classification": mrun.mat.classification,
            "detail": failure or mrun.mat.detail,
            "h4_root": mrun.mat.h4_root if mrun.mat.h4 else "",
            "h5_root": mrun.mat.h5_root if mrun.mat.h5 else "",
            "eligible": result.eligible,
            "assurance": result.assurance_label,
            "policy": result.record(),
            "refusal_reason": refusal["reason"] if refusal else None,
            "verify": verify,
            "receipt_ref": receipt.ref() if receipt else None,
            "gate": {"passed": gate_ev.passed,
                     "candidate_aware": gate_ev.candidate_aware,
                     "tests": [gate_ev.tests_passed, gate_ev.tests_failed],
                     "plan_digest": gate_ev.plan_digest,
                     "phases": [[p.name, p.rc, p.log_sha]
                                for p in gate_ev.phases],
                     "exe_sha": gate_ev.exe_sha,
                     "ref": gate_ev.ref()} if gate_ev else None,
            "proof": {"verdict": proof_ev.result.verdict,
                      "reason": proof_ev.result.reason,
                      "counts": [proof_ev.result.total,
                                 proof_ev.result.proven,
                                 proof_ev.result.unproven],
                      "script_sha": proof_ev.script_sha,
                      "log_sha": proof_ev.log_sha,
                      "ref": proof_ev.ref()} if proof_ev else None,
            "measurement": {
                "ok": meas_ev.ok,
                "adp": meas_ev.adp,
                "base_adp": meas_ev.base_adp,
                "ref": meas_ev.ref,
                "ppa": raw_ppa,
            } if meas_ev else None,
            # The ordinary controller consumes this exact dict.  It remains
            # subordinate to the policy result: an ineligible row can carry a
            # diagnostic measurement but can never be mapped to "measured".
            "ppa": raw_ppa,
        }
        ledger_append(ip, record)
        return record
    finally:
        if own_ws:
            ws.destroy()


def cached_evaluation(ip: str, evaluation_id: str) -> dict | None:
    """Exact validated identity or MISS (tampered rows refused)."""
    return P.cache_lookup(ledger_read(ip), evaluation_id)
