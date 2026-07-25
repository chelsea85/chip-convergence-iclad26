"""The single eligibility authority (corrective slice 2; review SS4.4-4.8).

Policy input is the TRANSITIVELY FROZEN evidence set: the self-validating
`MaterializationReceipt` (copied out of the mutable builder), exact-typed
`GateEvidence`/`ProofEvidence`, and adapter-validated measurement/check
records (finite values, 64-hex refs). `EligibilityResult` construction is
FACTORY-GUARDED: only `evaluate_policy()` (and `validate_cached_policy()`,
which re-derives the root) can construct one - computing the public root
algorithm is no longer sufficient (review SS4.5). Identity includes the gate
PLAN digest via GateEvidence, so any plan command change changes the
evaluation ID (review SS4.7); `validate_cached_row()` revalidates a ledger
row's schema + policy root + eligibility before a cache hit is returned
(tampered rows are refused).
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from . import contract as C
from . import gate as GT
from . import materialize as MZ

POLICY_SCHEMA = "nvdla-eligibility-v3"

CONDITIONS = (
    "contract_recognized_and_validated", "paths_in_universe_and_scope",
    "source_delta_only", "regeneration_complete", "effective_source_change",
    "collateral_drift_clear", "template_and_effective_checks",
    "gate_candidate_aware_pass", "h5_stable", "proxy_policy_satisfied",
    "measurement_valid", "objective_improves", "lec_proven_v2",
    "evidence_complete", "campaign_constraints",
)


@dataclass(frozen=True)
class CheckEvidence:
    """ok + a 64-hex content digest reference into the retained evidence
    store (free strings are refused - review SS4.5)."""
    ok: bool
    ref: str

    def __post_init__(self):
        if not C._is_sha256(self.ref):
            raise C.ContractError(
                "CheckEvidence.ref must be a 64-hex content digest")


@dataclass(frozen=True)
class MeasurementEvidence:
    ok: bool
    adp: float | None
    base_adp: float | None
    ref: str

    def __post_init__(self):
        if not C._is_sha256(self.ref):
            raise C.ContractError(
                "MeasurementEvidence.ref must be a 64-hex content digest")
        if self.ok:
            for name, v in (("adp", self.adp), ("base_adp", self.base_adp)):
                if (not isinstance(v, (int, float)) or isinstance(v, bool)
                        or not math.isfinite(v) or v <= 0):
                    raise C.ContractError(
                        f"MeasurementEvidence.{name} must be a finite "
                        f"positive number when ok=True (got {v!r})")


@dataclass(frozen=True)
class EvaluationEvidence:
    """The one aggregate the policy derives from - EXACT frozen types only
    (review SS4.4): the transitively frozen MaterializationReceipt (or None
    for failed materializations, carried as `failure`), self-validating
    GateEvidence/ProofEvidence, validated measurement/check records."""
    run_context: "C.RunContext"
    refusal_reason: str | None
    expected_top: str
    receipt: "MZ.MaterializationReceipt | None"
    failure: str | None                       # classification detail if no receipt
    gate: "GT.GateEvidence | None"
    proof: object | None                      # verify.ProofEvidence
    measurement: MeasurementEvidence | None
    checks: CheckEvidence | None = None
    proxy: CheckEvidence | None = None
    budget: CheckEvidence | None = None

    def __post_init__(self):
        from . import verify as V
        if not isinstance(self.run_context, C.RunContext):
            raise C.ContractError("run_context must be a RunContext")
        if self.receipt is not None and not isinstance(
                self.receipt, MZ.MaterializationReceipt):
            raise C.ContractError(
                "receipt must be a frozen MaterializationReceipt")
        if self.receipt is None and self.failure is None:
            raise C.ContractError(
                "either a receipt or an explicit failure reason is required")
        if self.gate is not None and not isinstance(self.gate,
                                                    GT.GateEvidence):
            raise C.ContractError("gate must be a GateEvidence")
        if self.proof is not None and not isinstance(self.proof,
                                                     V.ProofEvidence):
            raise C.ContractError("proof must be a ProofEvidence")
        if self.measurement is not None and not isinstance(
                self.measurement, MeasurementEvidence):
            raise C.ContractError("measurement must be MeasurementEvidence")
        if not self.expected_top:
            raise C.ContractError("expected_top is required")


def _conditions_root(schema: str, conditions: tuple) -> str:
    blob = json.dumps([schema] + [[c.name, c.status, c.reason, c.evidence]
                                  for c in conditions])
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class ConditionResult:
    name: str
    status: str
    reason: str = ""
    evidence: str = ""

    def __post_init__(self):
        if self.name not in CONDITIONS:
            raise C.ContractError(f"unknown eligibility condition {self.name}")
        if self.status not in ("PASS", "FAIL", "PENDING"):
            raise C.ContractError(f"bad condition status {self.status}")
        if self.status == "PASS" and not C._is_sha256(self.evidence):
            raise C.ContractError(
                f"condition {self.name}: PASS requires a 64-hex "
                f"content-digest evidence reference")


# factory guard (review SS4.5): computing the public root algorithm is not
# enough - construction outside the two factories raises. (object.__setattr__
# level attacks remain out of the agreed threat model.)
_CONSTRUCTING = False


@dataclass(frozen=True)
class EligibilityResult:
    schema: str
    conditions: tuple
    evidence_root: str

    def __post_init__(self):
        if not _CONSTRUCTING:
            raise C.ContractError(
                "EligibilityResult may only be produced by evaluate_policy()/"
                "validate_cached_policy() - manual construction is refused")
        names = [c.name for c in self.conditions]
        if sorted(names) != sorted(CONDITIONS):
            raise C.ContractError("eligibility requires every condition "
                                  "exactly once")
        if self.schema != POLICY_SCHEMA:
            raise C.ContractError(f"unknown policy schema {self.schema}")
        if self.evidence_root != _conditions_root(self.schema,
                                                  self.conditions):
            raise C.ContractError("evidence_root mismatch")

    @property
    def eligible(self) -> bool:
        return all(c.status == "PASS" for c in self.conditions)

    @property
    def assurance_label(self) -> str:
        if not self.eligible:
            fails = [c.name for c in self.conditions if c.status != "PASS"]
            return f"ineligible({','.join(fails[:3])})"
        return ("yosys_whole_design_equiv_proven_under_pinned_recipe"
                "+organizer_gate_candidate_aware_pass"
                "+generic_dualsim_not_required_diagnostic_only")

    def record(self) -> dict:
        return {"schema": self.schema, "eligible": self.eligible,
                "assurance": self.assurance_label,
                "evidence_root": self.evidence_root,
                "conditions": [{"name": c.name, "status": c.status,
                                "reason": c.reason, "evidence": c.evidence}
                               for c in self.conditions]}


def _build_result(conditions: tuple) -> EligibilityResult:
    global _CONSTRUCTING
    _CONSTRUCTING = True
    try:
        return EligibilityResult(
            schema=POLICY_SCHEMA, conditions=conditions,
            evidence_root=_conditions_root(POLICY_SCHEMA, conditions))
    finally:
        _CONSTRUCTING = False


def evaluate_policy(ev: EvaluationEvidence) -> EligibilityResult:
    """Derive all 15 conditions from the frozen aggregate."""
    rc = ev.run_context
    rcpt = ev.receipt
    scope = rc.scope
    scope_ref = hashlib.sha256(scope.scope_id().encode()).hexdigest()
    mat_ref = rcpt.ref() if rcpt else ""
    proceed = rcpt is not None            # receipts exist ONLY for proceed

    def cond(name, ok, reason="", evidence="", pending=False):
        if pending:
            return ConditionResult(name=name, status="PENDING", reason=reason)
        if ok and evidence:
            return ConditionResult(name=name, status="PASS", reason=reason,
                                   evidence=evidence)
        return ConditionResult(name=name, status="FAIL",
                               reason=reason or "no bound evidence")

    # proof bindings (review SS4.6): top + BOTH side digests + H5 + script
    proof_ok = False
    proof_reason = "no proof evidence"
    if ev.proof is not None and rcpt is not None:
        pres = ev.proof.result
        bindings = (ev.proof.cand_inputs_digest
                    == rcpt.effective.inputs_digest
                    and ev.proof.gold_inputs_digest
                    == rcpt.effective.golden_inputs_digest
                    and ev.proof.h5_root == rcpt.h5_root
                    and ev.proof.top == ev.expected_top
                    and C._is_sha256(ev.proof.script_sha)
                    and C._is_sha256(ev.proof.log_sha))
        proof_ok = (pres.verdict == "PROVEN"
                    and pres.recipe_id == C.LEC_RECIPE_CONTRACT_V2
                    and bool(bindings))
        proof_reason = (f"{pres.verdict}/{pres.reason}"
                        + ("" if bindings else
                           " (bindings do not match the receipt/top)"))

    gate_ok = bool(ev.gate is not None and rcpt is not None
                   and ev.gate.passed and ev.gate.candidate_aware
                   and ev.gate.h5_root == rcpt.h5_root
                   and ev.gate.h4_root == rcpt.h4_root)

    meas = ev.measurement
    improves = bool(meas and meas.ok and meas.adp is not None
                    and meas.base_adp is not None
                    and meas.adp < meas.base_adp)

    h1 = dict(rcpt.h1) if rcpt else {}
    h2 = dict(rcpt.h2) if rcpt else {}

    conditions = (
        cond("contract_recognized_and_validated",
             ev.refusal_reason is None
             and rc.validation_state == "VALIDATED",
             reason=ev.refusal_reason or rc.validation_state,
             evidence=scope_ref if (ev.refusal_reason is None
                                    and rc.validation_state == "VALIDATED")
             else ""),
        cond("paths_in_universe_and_scope",
             proceed and set(h1) == set(scope.editable_targets),
             reason=ev.failure or "", evidence=mat_ref),
        cond("source_delta_only", proceed and set(h1) == set(h2),
             reason=ev.failure or "", evidence=mat_ref),
        cond("regeneration_complete", proceed, reason=ev.failure or "",
             evidence=mat_ref),
        cond("effective_source_change", proceed, reason=ev.failure or "",
             evidence=mat_ref),
        cond("collateral_drift_clear", proceed, reason=ev.failure or "",
             evidence=mat_ref),
        cond("template_and_effective_checks",
             bool(ev.checks and ev.checks.ok),
             evidence=ev.checks.ref if ev.checks else "",
             pending=ev.checks is None),
        cond("gate_candidate_aware_pass", gate_ok,
             reason=getattr(ev.gate, "detail", "no gate evidence"),
             evidence=ev.gate.ref() if ev.gate is not None else ""),
        cond("h5_stable",
             proceed and rcpt.h5_root == rcpt.h4_root,
             evidence=hashlib.sha256(
                 rcpt.h5_root.encode()).hexdigest() if rcpt else ""),
        cond("proxy_policy_satisfied", bool(ev.proxy and ev.proxy.ok),
             evidence=ev.proxy.ref if ev.proxy else "",
             pending=ev.proxy is None),
        cond("measurement_valid", bool(meas and meas.ok),
             evidence=meas.ref if meas else ""),
        cond("objective_improves", improves,
             reason="" if improves else "no improvement or no measurement",
             evidence=meas.ref if (meas and improves) else ""),
        cond("lec_proven_v2", proof_ok, reason=proof_reason,
             evidence=ev.proof.ref() if ev.proof is not None else ""),
        cond("evidence_complete",
             all(x is not None for x in (rcpt, ev.gate, ev.proof, meas)),
             evidence=(hashlib.sha256(
                 rcpt.effective.inputs_digest.encode()).hexdigest()
                 if rcpt else "")),
        cond("campaign_constraints", bool(ev.budget and ev.budget.ok),
             evidence=ev.budget.ref if ev.budget else "",
             pending=ev.budget is None),
    )
    return _build_result(conditions)


# ── evaluation identity + validated cache (review SS4.7) ─────────────────────
def evaluation_identity(ev: EvaluationEvidence, *, source_cid: str,
                        registration_digest: str, container_digest: str,
                        tool_versions: dict,
                        measurement_recipe: str = "top-area-v2") -> str:
    rcpt = ev.receipt
    if rcpt is None:
        raise C.ContractError("evaluation identity requires the frozen "
                              "materialization receipt")
    if not C._is_sha256(source_cid):
        raise C.ContractError(
            "source_cid must be the recomputed 64-hex candidate-content "
            "digest (caller labels are refused)")
    if not C._is_sha256(registration_digest):
        raise C.ContractError("registration_digest must be 64-hex sha256")
    if not (container_digest.startswith("sha256:")
            and C._is_sha256(container_digest[7:])):
        raise C.ContractError("container_digest must be sha256:<64-hex>")
    if not isinstance(tool_versions, dict) or not tool_versions:
        raise C.ContractError("tool_versions must be a nonempty dict")
    if any(str(v).startswith("/") for v in tool_versions.values()):
        raise C.ContractError("tool_versions must not contain absolute paths")
    blob = json.dumps({
        "source_cid": source_cid,
        "registration_digest": registration_digest,
        "scope_id": ev.run_context.scope.scope_id(),
        "materialization_receipt": rcpt.ref(),
        "design_inputs_digest": rcpt.effective.inputs_digest,
        "golden_inputs_digest": rcpt.effective.golden_inputs_digest,
        "policy_schema": POLICY_SCHEMA,
        "verification_policy": ev.run_context.scope.verification_policy,
        # the gate PLAN digest itself: any command/path change -> new identity
        "gate_plan_digest": ev.gate.plan_digest if ev.gate else "none",
        "gate_ref": ev.gate.ref() if ev.gate else "none",
        "proof_script_digest": (ev.proof.script_sha if ev.proof else "none"),
        "measurement_recipe_digest": hashlib.sha256(
            measurement_recipe.encode()).hexdigest(),
        "container_digest": container_digest,
        "tool_versions": dict(sorted(tool_versions.items()))},
        sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def validate_cached_row(rec: dict) -> bool:
    """A cache hit must be a VALIDATED record (review SS4.7): typed policy
    payload with the expected schema, recomputed evidence root, and internal
    eligible-consistency. Tampered rows are refused."""
    pol = rec.get("policy")
    if not isinstance(pol, dict) or pol.get("schema") != POLICY_SCHEMA:
        return False
    conds = pol.get("conditions")
    if not isinstance(conds, list) or len(conds) != len(CONDITIONS):
        return False
    try:
        tup = tuple(ConditionResult(name=c["name"], status=c["status"],
                                    reason=c.get("reason", ""),
                                    evidence=c.get("evidence", ""))
                    for c in conds)
    except (C.ContractError, KeyError, TypeError):
        return False
    # every condition exactly once (corrective2 review SS4.5: 15 copies of
    # one PASS condition must not validate)
    if sorted(c.name for c in tup) != sorted(CONDITIONS):
        return False
    if _conditions_root(POLICY_SCHEMA, tup) != pol.get("evidence_root"):
        return False
    if pol.get("eligible") != all(c.status == "PASS" for c in tup):
        return False
    if rec.get("eligible") != pol.get("eligible"):
        return False
    return True


def cache_lookup(records: list[dict], evaluation_id: str) -> dict | None:
    """Exact evaluation-identity match AND full row validation - a matching
    ID on a tampered/malformed row is a MISS, never a hit."""
    for rec in reversed(records):
        if rec.get("evaluation_id") == evaluation_id:
            return rec if validate_cached_row(rec) else None
    return None
