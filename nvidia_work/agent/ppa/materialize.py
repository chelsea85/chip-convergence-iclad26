"""H1-H5 materialization path (corrective slice; migration review SS4.3/4.4).

Frozen candidate order (design rev2 SS5) with PER-INVOCATION mutation-class
enforcement (normative D.2): a complete, symlink-safe recursive manifest of
EVERY immutable dependency root (files AND directories - tools/spec/vlibs/
rams/filelist) is captured BEFORE the pristine generator runs, re-checked
after the pristine invocation, and re-checked after the candidate invocation
- INCLUDING when the generator exits nonzero. Membership changes count.

H5 time-of-use (review SS4.4): post_gate() emits a FROZEN `EffectiveDesign`
receipt binding the complete candidate DesignInputs digest + H4/H5 roots +
scope/contract identity. `effective_inputs()` REVALIDATES the live workspace
against the receipt (fingerprint recomputed == H5 root; DesignInputs digest
recomputed == receipt digest) immediately before every use - a generated OR
non-outdir source changed after H5 fails closed.

Exception boundary (review SS5.2): expected contract/tool errors are
normalized into classified flow-error records with the reason retained.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from . import contract as C


@dataclass(frozen=True)
class EffectiveDesign:
    """The H5-bound receipt: the ONLY key to candidate tool inputs. Frozen at
    post_gate; consumers revalidate live state against it at time of use."""
    ip: str
    scope_id: str
    contract_family: str
    h4_root: str
    h5_root: str
    inputs_digest: str          # complete candidate DesignInputs.digest()
    golden_inputs_digest: str   # complete golden DesignInputs.digest()
    golden_root: str            # golden manifest root


@dataclass
class MaterializationRun:
    mat: C.Materialization
    golden: tuple = ()
    regen_log: str = ""
    receipt: EffectiveDesign | None = None   # set ONLY by post_gate()

    @property
    def ok(self) -> bool:
        return self.mat.classification == "proceed"


def _walk_class_manifest(root, rels) -> dict:
    """Recursive manifest over declared roots (files or dirs):
    {rel: (size, sha256)}. Membership is part of the manifest. ANY symlink at
    or below a declared root - leaf OR directory - is REJECTED outright
    (corrective review SS4.3): a link whose external target mutates would be
    invisible to content hashing, so aliases are structurally forbidden under
    immutable dependency roots."""
    out = {}
    for rel in rels:
        p = root / rel
        if p.is_symlink():
            raise C.ContractError(
                f"symlink at immutable dependency root {rel} - aliases are "
                f"forbidden under immutable roots")
        if p.is_file():
            out[rel] = (p.stat().st_size, C._hash_file(p))
        elif p.is_dir():
            for dirpath, dirnames, filenames in os.walk(p, followlinks=False):
                for d in dirnames:
                    if os.path.islink(os.path.join(dirpath, d)):
                        raise C.ContractError(
                            f"symlinked directory under immutable root "
                            f"{rel}: {os.path.relpath(os.path.join(dirpath, d), root)}")
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    frel = os.path.relpath(fp, root)
                    if os.path.islink(fp):
                        raise C.ContractError(
                            f"symlink under immutable root {rel}: {frel}")
                    st = os.stat(fp)
                    out[frel] = (st.st_size, C._hash_file(root / frel))
    return out


def immutable_manifest(root, ctr) -> dict:
    return _walk_class_manifest(root, ctr.path_classes()["immutable_deps"])


@dataclass(frozen=True)
class MaterializationReceipt:
    """TRANSITIVELY frozen, self-validating materialization evidence
    (corrective review SS4.4): H1/H2 as immutable tuples, manifest roots, and
    the classification are COPIED out of the mutable builder at freeze time -
    later mutation of the builder cannot change this record or any policy
    verdict derived from it."""
    h1: tuple                     # ((rel, sha256), ...)
    h2: tuple
    h3_root: str
    h4_root: str
    h5_root: str
    classification: str
    detail: str
    effective: "EffectiveDesign"

    def __post_init__(self):
        for name, pairs in (("h1", self.h1), ("h2", self.h2)):
            for rel, sha in pairs:
                if not rel or not C._is_sha256(sha):
                    raise C.ContractError(
                        f"MaterializationReceipt.{name} invalid entry {rel}")
        for f in ("h3_root", "h4_root", "h5_root"):
            if not C._is_sha256(getattr(self, f)):
                raise C.ContractError(
                    f"MaterializationReceipt.{f} must be 64-hex")
        if self.classification != "proceed":
            raise C.ContractError(
                "a MaterializationReceipt exists only for proceed-classified "
                f"runs (got {self.classification!r})")
        if not isinstance(self.effective, EffectiveDesign):
            raise C.ContractError("effective must be an EffectiveDesign")
        if (self.effective.h4_root != self.h4_root
                or self.effective.h5_root != self.h5_root):
            raise C.ContractError(
                "receipt/effective-design H-root mismatch")

    def ref(self) -> str:
        import hashlib as _h
        import json as _j
        return _h.sha256(_j.dumps(
            {"h1": list(self.h1), "h2": list(self.h2),
             "h3": self.h3_root, "h4": self.h4_root, "h5": self.h5_root,
             "inputs": self.effective.inputs_digest},
            sort_keys=True).encode()).hexdigest()


def freeze_receipt(run: "MaterializationRun") -> MaterializationReceipt:
    """Emit the frozen receipt AFTER a successful post_gate. Values are
    COPIED - the mutable builder is left behind."""
    mat = run.mat
    if run.receipt is None or mat.classification != "proceed":
        raise C.ContractError(
            "freeze_receipt requires a proceed-classified, post-gate run")
    return MaterializationReceipt(
        h1=tuple(sorted((r, h) for r, h in mat.h1.items())),
        h2=tuple(sorted((r, h) for r, h in mat.h2.items())),
        h3_root=mat.h3_root, h4_root=mat.h4_root, h5_root=mat.h5_root,
        classification=mat.classification, detail=mat.detail,
        effective=run.receipt)


def materialize_candidate(ws, ctr, scope, cand_files, runner=None,
                          profile=None) -> MaterializationRun:
    """Steps 3-7 for a PRISTINE workspace. Every failure - including raised
    contract errors and generator mutations on EITHER invocation - becomes a
    classified flow-error record."""
    root = ws.root
    runner = runner or ws.run
    run = MaterializationRun(mat=C.Materialization())
    mat = run.mat

    def fail(detail):
        mat.classification, mat.detail = "flow-error", detail
        return run

    try:
        C.check_scope_compat(ctr, scope)
        C.validate_candidate(ctr, root, cand_files, scope)

        # immutable baseline BEFORE the pristine generator (review SS4.3: the
        # first invocation is guarded too - a pristine-run mutation can never
        # be absorbed into the baseline)
        imm0 = immutable_manifest(root, ctr)

        # step 3: pristine materialization
        ok, log = ctr.regenerate(root, runner)
        run.regen_log = log
        imm_after_pristine = immutable_manifest(root, ctr)
        if imm_after_pristine != imm0:
            return fail("generator mutated an immutable dependency "
                        "(pristine invocation)")
        if not ok:
            return fail("pristine regeneration failed")

        # step 4: golden snapshot + H3 (before ANY overlay)
        run.golden = ctr.snapshot_golden(root)
        mat.h3 = ctr.fingerprint(root)
        mat.h1 = {rel: C._hash_file(root / rel) for rel in cand_files}

        # step 5: overlay (workspace enforces contract + scope again)
        ws.overlay(cand_files)
        mat.h2 = {rel: C._hash_file(root / rel) for rel in cand_files}

        # step 6: candidate regeneration - the drift audit runs whether or
        # not the generator exits zero (review SS4.3)
        ok, log = ctr.regenerate(root, runner)
        run.regen_log += log
        if immutable_manifest(root, ctr) != imm0:
            return fail("generator mutated an immutable dependency "
                        "(candidate invocation)")
        if {rel: C._hash_file(root / rel) for rel in cand_files} != mat.h2:
            return fail("generator mutated editable sources")
        if not ctr.verify_golden(root, run.golden):
            return fail("generator reached the golden snapshot")
        if not ok:
            return fail("candidate regeneration failed")

        # step 7: H4 + classification
        mat.h4 = ctr.fingerprint(root)
        C.classify_materialization(ctr, mat, scope, profile=profile)
        return run
    except C.ContractError as e:
        return fail(f"contract violation: {e}")


def post_gate(ws, ctr, run: MaterializationRun,
              scope=None) -> bool:
    """Steps 9-10 + the FROZEN receipt (review SS4.4): recompute H5, require
    H5 == H4, re-verify golden, then bind the complete candidate DesignInputs
    digest into an immutable EffectiveDesign. Consumers use the receipt."""
    mat = run.mat
    try:
        mat.h5 = ctr.fingerprint(ws.root)
    except C.ContractError as e:
        mat.classification, mat.detail = "flow-error", str(e)
        return False
    if not ctr.verify_golden(ws.root, run.golden):
        mat.classification, mat.detail = "flow-error", \
            "golden snapshot changed during the gate"
        return False
    if not C.check_gate_stability(mat):
        return False
    try:
        di = ctr.design_inputs(ws.root, "candidate")
        gi = ctr.design_inputs(ws.root, "golden")
    except C.ContractError as e:
        mat.classification, mat.detail = "flow-error", \
            f"side inputs invalid at H5: {e}"
        return False
    run.receipt = EffectiveDesign(
        ip=ctr.spec.name,
        scope_id=scope.scope_id() if scope is not None else "",
        contract_family=ctr.name,
        h4_root=mat.h4_root, h5_root=mat.h5_root,
        inputs_digest=di.digest(),
        golden_inputs_digest=gi.digest(),
        golden_root=C.manifest_root(run.golden))
    return True


def effective_inputs(ws, ctr, run: MaterializationRun) -> C.DesignInputs:
    """The ONLY path to candidate tool inputs - and it REVALIDATES the live
    workspace against the frozen receipt at time of use (review SS4.4):
    the current fingerprint must still equal the H5 root, and the recomputed
    complete DesignInputs digest (which covers non-outdir sources and the
    include universe) must equal the receipt digest."""
    mat = run.mat
    if mat.classification != "proceed":
        raise C.ContractError(
            f"effective inputs refused: classification="
            f"{mat.classification or 'pending'} ({mat.detail})")
    if run.receipt is None or not mat.h5 or mat.h5_root != mat.h4_root:
        raise C.ContractError(
            "effective inputs refused: H5 receipt not established - run the "
            "gate and post_gate() first (H5 is the sole effective input)")
    live_root = C.manifest_root(ctr.fingerprint(ws.root))
    if live_root != run.receipt.h5_root:
        raise C.ContractError(
            "effective inputs refused: workspace generated tree changed "
            f"after H5 (live {live_root[:12]} != receipt "
            f"{run.receipt.h5_root[:12]})")
    di = ctr.design_inputs(ws.root, "candidate")
    if di.digest() != run.receipt.inputs_digest:
        raise C.ContractError(
            "effective inputs refused: candidate tool inputs changed after "
            "H5 (digest mismatch vs receipt - non-outdir/include drift)")
    return di


def golden_inputs(ws, ctr, run: MaterializationRun) -> C.DesignInputs:
    """Golden-side tool inputs, re-verified against the snapshot manifest
    immediately before use (design rev2 SS7 condition 6)."""
    if not ctr.verify_golden(ws.root, run.golden):
        raise C.ContractError("golden snapshot failed re-verification")
    return ctr.design_inputs(ws.root, "golden")
