"""Source/generated/regeneration contracts (P0-4 checkpoint-1e).

Design: NVIDIA_NVDLA_P04_DESIGN_REV2_FOR_REVIEW.md + REV21_ADDENDUM (frozen SSH).
Checkpoint-1b corrections per NVIDIA_P04_SLICE_CODE_REVIEW.md SS3/SS4:
explicit Tmake layout + strict filelist parsing (3.1), symmetric side-bound
DesignInputs (3.2), required/canonical/IP-bound scope (3.3), hardened PROVEN
construction (3.4), bound validation profiles (3.5), fail-closed manifests and
symlink rejection (3.6), H1/H2-aware classification (3.7), real Sv2v mappings
(3.8), four path classes (4.3), full-length digests (4.6).

Dependency direction: contract.py imports config; config never imports
contract. Regeneration takes an injected `runner` (production: Workspace.run
-> docker; tests: local subprocess) - no docker assumption here. Contracts are
stateless across candidates; per-candidate state lives in Materialization
records returned to the caller.
"""
from __future__ import annotations

import sys

if sys.version_info < (3, 10):                     # review SS4.1: explicit floor
    raise RuntimeError(
        f"ppa.contract requires Python >= 3.10 (kw_only dataclasses); "
        f"this interpreter is {sys.version.split()[0]}. On the macOS host use "
        f"python3.12.")

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import IPSpec, REPO


class ContractError(RuntimeError):
    """A candidate/flow violated the source contract (fail closed)."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(p: Path) -> str:
    return _sha256(p.read_bytes())


_HEX64 = __import__("re").compile(r"[0-9a-f]{64}")


def _is_sha256(v) -> bool:
    """Exact 64-hex sha256 check (re-review4 SS5.1): fullmatch (a trailing
    newline can slip past `$`+match) and explicit type check (a non-string is
    False, never a raw TypeError). Shared by every evidence validator."""
    return isinstance(v, str) and _HEX64.fullmatch(v) is not None


def _assert_unaliased(root: Path, rel: str, what: str = "path"):
    """Reject a symlink at the leaf OR in any component below root (review
    SS4.1/SS4.5: lexical approval must not be redirectable through internal
    links - containment alone does not enforce the candidate-state
    invariant). With no symlinked components, resolved == lexical."""
    p = root
    for part in Path(rel).parts:
        p = p / part
        if p.is_symlink():
            raise ContractError(
                f"{what} {rel} has symlinked component "
                f"{p.relative_to(root)} - aliases are rejected")


def _canon(rel: str) -> str:
    """Canonical relative path: normalized first (filelists legitimately use
    `../../` entries that resolve inside the tree - review SS4.5 requires
    resolving, not storing, traversal syntax), then rejected if the NORMALIZED
    form still escapes or is absolute."""
    if Path(rel).is_absolute():
        raise ContractError(f"absolute path {rel!r}")
    norm = os.path.normpath(rel)
    if norm.startswith(".."):
        raise ContractError(f"path escapes tree after normalization: {rel!r}")
    return norm


# ── proof result algebra (Rev2.1a SSH.2; hardened per review SS3.4) ──────────
PROOF_VERDICTS = ("PROVEN", "INEQUIVALENT", "INCONCLUSIVE", "FLOW_ERROR")
PROOF_REASONS = {
    "PROVEN": ("fully_proven",),
    "INEQUIVALENT": ("reset_reachable_counterexample",),
    "INCONCLUSIVE": ("induction_counterexample_unconfirmed", "nonconvergent",
                     "timeout", "resource_limit"),
    "FLOW_ERROR": ("zero_compared_points", "malformed_status", "wrong_top",
                   "interface_mismatch", "frontend_abort",
                   "input_binding_mismatch"),
}

# Versioned recipes (Rev2.1a SSH.1). v1 = retained diagnostic evidence (bare
# equiv_induct/equiv_status; historical, never relabeled). v2 = canonical
# contract recipe (+explicit `-seq 4`, +`equiv_status -assert`); only v2 can
# confer eligibility.
LEC_RECIPE_DIAG_V1 = "nvdla-lec-diag-v1"
LEC_RECIPE_CONTRACT_V2 = "nvdla-lec-contract-v2"


@dataclass(frozen=True)
class ProofResult:
    """verdict+reason algebra. A PROVEN record cannot be constructed without
    the locally enforceable A.1 requirements (rc 0, nonzero total, proven ==
    total, zero unproven, canonical v2 recipe) - a bare hand-built string
    verdict can never read as assurance (review SS3.4). Top/interface/input
    bindings live in the verify-layer evidence object (migration phase); the
    eligibility policy checks both."""
    verdict: str
    reason: str
    rc: int | None = None
    total: int | None = None
    proven: int | None = None
    unproven: int | None = None
    recipe_id: str = ""

    def __post_init__(self):
        if self.verdict not in PROOF_VERDICTS:
            raise ContractError(f"unknown proof verdict {self.verdict}")
        if self.reason not in PROOF_REASONS[self.verdict]:
            raise ContractError(
                f"reason '{self.reason}' invalid for verdict {self.verdict}")
        if self.verdict == "PROVEN":
            ok = (self.rc == 0 and isinstance(self.total, int)
                  and self.total > 0 and self.proven == self.total
                  and self.unproven == 0
                  and self.recipe_id == LEC_RECIPE_CONTRACT_V2)
            if not ok:
                raise ContractError(
                    "PROVEN requires rc==0, total>0, proven==total, "
                    "unproven==0 and the canonical recipe "
                    f"{LEC_RECIPE_CONTRACT_V2}; got rc={self.rc} "
                    f"total={self.total} proven={self.proven} "
                    f"unproven={self.unproven} recipe={self.recipe_id!r}")

    # NOTE (checkpoint-1c, review SS4.3): this is a normalized DIAGNOSTIC
    # record only. It deliberately exposes NO eligibility property - the
    # frozen A.1/H.1 PROVEN rule additionally requires status/top/interface/
    # input bindings and the v2 recipe DIGEST, which live in the verify-layer
    # evidence object; the single versioned policy result (consumer-migration
    # phase) is the only object that may expose LEC eligibility.


# ── host-validation profile (Rev2.1a SSH.4b; hardened per review SS3.5) ──────
@dataclass(frozen=True)
class ValidationProfile:
    """Identity of a completed host determinism validation (H-1). Every
    component is required and nonempty; VALIDATED additionally requires this
    profile's digest to equal the explicitly configured bound digest - an
    arbitrary caller-created profile is never sufficient."""
    contract_schema: str
    contest_commit: str
    container_digest: str
    generator_digest: str
    reproduction_digest: str
    host_arch: str
    evidence_root: str                 # required (frozen SSH.4b; review SS4.2)
    manifest_algo: str = "sha256/canonical-json-v1"

    _REQUIRED = ("contract_schema", "contest_commit", "container_digest",
                 "generator_digest", "reproduction_digest", "host_arch",
                 "evidence_root", "manifest_algo")

    def __post_init__(self):
        for f in self._REQUIRED:
            if not getattr(self, f):
                raise ContractError(f"ValidationProfile.{f} must be nonempty")

    def digest(self) -> str:
        return _sha256(json.dumps(asdict(self), sort_keys=True).encode())


# ── campaign scope (Rev2.1a SSE.2; hardened per review SS3.3) ────────────────
KNOWN_SCOPE_SCHEMAS = ("contract-v1",)


@dataclass(frozen=True, kw_only=True)
class CampaignScope:
    """Immutable run-level narrowing of a contract's editable universe.

    Targets are canonicalized AND STORED canonicalized at construction, so an
    aliased scope cannot behave differently from its scope_id. requested_
    workers is PROVENANCE-ONLY and excluded from scope_id (explicit Rev2.1a
    amendment, review SS3.3 option 2): it changes parallelism, never results,
    and including it would fragment evidence lookup. The effective count comes
    from effective_workers().
    """
    ip: str
    editable_targets: tuple[str, ...]
    verification_policy: str
    requested_workers: int = 1
    max_changed_files: int = 1
    schema: str = "contract-v1"

    def __post_init__(self):
        if not self.ip or not self.verification_policy:
            raise ContractError("CampaignScope: ip and verification_policy "
                                "are required")
        if self.schema not in KNOWN_SCOPE_SCHEMAS:
            raise ContractError(f"CampaignScope: unknown schema {self.schema}")
        if not self.editable_targets:
            raise ContractError("CampaignScope: empty editable_targets")
        for t in self.editable_targets:
            # scope targets are hand-declared: raw traversal syntax is a
            # config error even when it would normalize inside the tree
            if ".." in Path(t).parts:
                raise ContractError(f"CampaignScope: '..' in target {t!r}")
        norm = tuple(_canon(t) for t in self.editable_targets)
        if len(set(norm)) != len(norm):
            raise ContractError(f"CampaignScope: duplicate targets after "
                                f"canonicalization: {norm}")
        object.__setattr__(self, "editable_targets", norm)   # store canonical
        if self.max_changed_files < 1 or self.requested_workers < 1:
            raise ContractError("CampaignScope: limits must be >= 1")

    def scope_id(self) -> str:
        blob = json.dumps({
            "ip": self.ip,
            "targets": sorted(self.editable_targets),
            "policy": self.verification_policy,
            "max_changed_files": self.max_changed_files,
            "schema": self.schema}, sort_keys=True)
        return _sha256(blob.encode())        # full sha256 (review SS4.6)


def effective_workers(scope: CampaignScope, contract: "SourceContract",
                      global_cap: int = 8) -> int:
    """min(requested, contract hard cap, global cap) - resolved once,
    persisted in provenance (requested + both caps + effective), consumed by
    every executor path. Invalid caps are structured errors, never silently
    rewritten to 1 (review SS5.3)."""
    if global_cap < 1 or contract.worker_cap() < 1:
        raise ContractError(
            f"invalid worker caps: global={global_cap}, "
            f"contract={contract.worker_cap()} (must be >= 1)")
    return min(scope.requested_workers, contract.worker_cap(), global_cap)


# ── manifests (hardened per review SS3.6) ────────────────────────────────────
@dataclass(frozen=True)
class ManifestEntry:
    rel: str
    size: int
    sha256: str


def validate_manifest(entries: tuple[ManifestEntry, ...],
                      what: str = "manifest") -> tuple[ManifestEntry, ...]:
    """Structural validation for manifests, INCLUDING deserialized evidence
    tuples that never went through tree_manifest (review SS4.5): nonempty,
    canonical unique rels, size >= 0, 64-hex sha256."""
    if not entries:
        raise ContractError(f"{what}: empty manifest is invalid")
    rels = [e.rel for e in entries]
    if len(set(rels)) != len(rels):
        raise ContractError(f"{what}: duplicate rels")
    for e in entries:
        if not e.rel or e.rel == "." or _canon(e.rel) != e.rel:
            raise ContractError(f"{what}: invalid/non-canonical rel {e.rel!r}")
        if not isinstance(e.size, int) or e.size < 0:
            raise ContractError(f"{what}: invalid size for {e.rel}")
        if not _is_sha256(e.sha256):
            raise ContractError(f"{what}: invalid sha256 for {e.rel}")
    return entries


def tree_manifest(root: Path, rels: list[str]) -> tuple[ManifestEntry, ...]:
    """Hash `rels` (relative to root). Fail closed on: empty set, duplicate or
    non-canonical paths, missing/non-regular files, symlinks at the leaf OR IN
    ANY PARENT COMPONENT (review SS4.5), or resolved escape from root."""
    if not rels:
        raise ContractError("tree_manifest: empty file set (missing "
                            "generated output is a flow error, not an empty "
                            "manifest)")
    canon = [_canon(r) for r in rels]
    if len(set(canon)) != len(canon):
        dupes = sorted({c for c in canon if canon.count(c) > 1})
        raise ContractError(f"tree_manifest: duplicate paths {dupes[:5]}")
    rroot = root.resolve()
    out = []
    for rel in sorted(canon):
        p = root / rel
        _assert_unaliased(root, rel, "tree_manifest entry")
        if not p.is_file():
            raise ContractError(f"tree_manifest: {rel} missing or non-regular")
        if not str(p.resolve()).startswith(str(rroot) + os.sep):
            raise ContractError(f"tree_manifest: {rel} escapes {root}")
        out.append(ManifestEntry(rel, p.stat().st_size, _hash_file(p)))
    return tuple(out)


def manifest_root(entries: tuple[ManifestEntry, ...]) -> str:
    """Combined digest over canonical JSON of (rel, size, hash) - fully
    validates and sorts itself (empty/malformed/duplicate rejected)."""
    validate_manifest(entries, "manifest_root")
    blob = json.dumps([[e.rel, e.size, e.sha256]
                       for e in sorted(entries, key=lambda e: e.rel)])
    return _sha256(blob.encode())


# ── design inputs (Rev2.1a SSB.2; symmetric sides per review SS3.2) ──────────
SIDES = ("golden", "candidate")


@dataclass(frozen=True)
class DesignInputs:
    """Exact tool inputs for one side of one design, built by the contract
    from ONE parsed logical filelist model with side-specific physical roots.
    `per_file_defer` is a Yosys concept honored only by yosys_read(). Paths
    are logical/workspace-relative and canonical; digests cover every ordered
    source and include file actually supplied to the tool."""
    side: str
    top: str
    ordered_sources: tuple[str, ...]
    include_roots: tuple[str, ...] = ()
    include_files: tuple[str, ...] = ()
    defines: tuple[str, ...] = ()
    per_file_defer: bool = False
    filelist_digest: str = ""
    manifest_digest: str = ""

    def __post_init__(self):
        if self.side not in SIDES:
            raise ContractError(f"DesignInputs.side must be one of {SIDES}")
        if not self.top:
            raise ContractError("DesignInputs: empty top")
        if not self.ordered_sources:
            raise ContractError("DesignInputs: empty ordered_sources")
        for group in (self.ordered_sources, self.include_roots,
                      self.include_files):
            for p in group:
                if _canon(p) != p:
                    raise ContractError(f"DesignInputs: non-canonical path "
                                        f"{p!r}")
        for name, group in (("ordered_sources", self.ordered_sources),
                            ("include_roots", self.include_roots),
                            ("include_files", self.include_files),
                            ("defines", self.defines)):
            if len(set(group)) != len(group):
                raise ContractError(f"DesignInputs: duplicates in {name}")

    def digest(self) -> str:
        blob = json.dumps([self.side, self.top, list(self.ordered_sources),
                           list(self.include_roots), list(self.include_files),
                           list(self.defines), self.per_file_defer,
                           self.filelist_digest, self.manifest_digest])
        return _sha256(blob.encode())

    def yosys_read(self) -> str:
        opts = "".join(f" -D{d}" for d in self.defines) + \
               "".join(f" -I{i}" for i in self.include_roots)
        if self.per_file_defer:
            return "".join(f"read_verilog -sv -defer{opts} {s}\n"
                           for s in self.ordered_sources)
        return f"read_verilog -sv{opts} {' '.join(self.ordered_sources)}\n"


# ── materialization record + classification (H1/H2-aware, review SS3.7) ──────
@dataclass
class Materialization:
    """H1-H5 hash ledger + classification for one candidate.

    classification: proceed | no-effective-change | collateral-drift |
                    flow-error | "" (pending)
    """
    h1: dict = None                             # pristine source hashes
    h2: dict = None                             # candidate source hashes
    h3: tuple = ()                              # pristine generated manifest
    h4: tuple = ()                              # candidate generated, pre-gate
    h5: tuple = ()                              # candidate generated, post-gate
    changed: tuple = ()
    classification: str = ""
    detail: str = ""

    def __post_init__(self):
        self.h1 = self.h1 or {}
        self.h2 = self.h2 or {}

    @property
    def h3_root(self): return manifest_root(self.h3) if self.h3 else ""
    @property
    def h4_root(self): return manifest_root(self.h4) if self.h4 else ""
    @property
    def h5_root(self): return manifest_root(self.h5) if self.h5 else ""


def check_scope_compat(contract: "SourceContract",
                       scope: CampaignScope | None):
    """ONE contract/scope compatibility validator used everywhere a scope is
    consumed (review SS4.4): overlay, seeding, classification."""
    if contract.requires_scope() and scope is None:
        raise ContractError(
            f"{contract.name} contract ({contract.spec.name}) requires an "
            f"explicit CampaignScope")
    if scope is not None and scope.ip != contract.spec.name:
        raise ContractError(f"scope.ip {scope.ip!r} != contract IP "
                            f"{contract.spec.name!r}")


def classify_materialization(contract: "SourceContract", mat: Materialization,
                             scope: CampaignScope | None = None,
                             profile: "ValidationProfile | None" = None
                             ) -> Materialization:
    """SS6.3 classification, H1/H2-aware and SCOPE-AUTHORITATIVE (review
    SS4.4): scope compatibility is enforced here too (a consumer omission or
    evidence-deserialization bug cannot bypass overlay's authority); H1/H2
    membership must equal the complete scoped target set; derived edit count
    obeys max_changed_files; manifests are validated even when deserialized.
    The determinism state is DERIVED via contract.validation_state(profile) -
    callers cannot supply "VALIDATED" as text (re-review2 SS4.2). While
    PENDING, unexpected generated changes are flow errors (the campaign must
    be refused anyway) - never a host-proven-drift claim."""
    check_scope_compat(contract, scope)      # raises: config error, not record
    validation_state = contract.validation_state(profile)

    def fail(d):
        mat.classification, mat.detail = "flow-error", d
        return mat
    if not mat.h3 or not mat.h4:
        return fail("missing H3/H4 generated manifest")
    try:
        validate_manifest(mat.h3, "H3")
        validate_manifest(mat.h4, "H4")
    except ContractError as e:
        return fail(str(e))
    if not mat.h1 or not mat.h2:
        return fail("missing H1/H2 source evidence")
    if set(mat.h1) != set(mat.h2):
        return fail("H1/H2 cover different source paths")
    if scope is not None and set(mat.h1) != set(scope.editable_targets):
        return fail(f"H1/H2 membership {sorted(mat.h1)} != complete scoped "
                    f"target set {sorted(scope.editable_targets)}")
    for rel in mat.h1:
        if _canon(rel) != rel:
            return fail(f"non-canonical H1/H2 path: {rel!r}")
        if not (_is_sha256(mat.h1[rel]) and _is_sha256(mat.h2[rel])):
            return fail(f"invalid H1/H2 hash for {rel}")
        if not contract.is_editable(rel):
            return fail(f"H1/H2 path outside editable universe: {rel}")
    edited = sorted(k for k in mat.h1 if mat.h1[k] != mat.h2[k])
    if scope is not None and len(edited) > scope.max_changed_files:
        return fail(f"{len(edited)} edited files > scope max "
                    f"{scope.max_changed_files}")
    h3 = {e.rel: e.sha256 for e in mat.h3}
    h4 = {e.rel: e.sha256 for e in mat.h4}
    if set(h3) != set(h4):
        return fail("generated file set changed (membership)")
    changed = sorted(r for r in h3 if h3[r] != h4[r])
    mat.changed = tuple(changed)
    expected = sorted({g for rel in edited
                       for g in contract.source_to_generated(rel)})
    extra = [r for r in changed if r not in expected]
    if extra:
        # covers generator/environment drift when H1 == H2 too: with no edits
        # the expected closure is empty, so ANY generated change is unmapped.
        # The drift LABEL requires a host-validated determinism profile
        # (review SS4.4): while PENDING this is a flow error, not a
        # host-proven contract-violation claim.
        if validation_state == "VALIDATED":
            mat.classification = "collateral-drift"
            mat.detail = f"unmapped generated files changed: {extra[:5]}"
        else:
            mat.classification = "flow-error"
            mat.detail = (f"unmapped generated changes {extra[:5]} under "
                          f"UNVALIDATED determinism profile "
                          f"({validation_state}) - campaign must be refused")
    elif not edited:
        mat.classification, mat.detail = "no-effective-change", \
            "H1 == H2: no declared source changed"
    elif not changed:
        mat.classification, mat.detail = "no-effective-change", \
            "H4 == H3: edit did not reach the generated representation"
    elif set(changed) != set(expected):
        mat.classification, mat.detail = "flow-error", \
            f"partial mapped closure: changed {changed} != expected {expected}"
    else:
        mat.classification = "proceed"
    return mat


def check_gate_stability(mat: Materialization) -> bool:
    """H5 == H4 (design SS5 step 10). False -> flow-error; H5 is the canonical
    effective input everywhere downstream. Manifests are validated (via
    manifest_root) even when deserialized; malformed evidence raises."""
    ok = bool(mat.h4) and bool(mat.h5) and mat.h4_root == mat.h5_root
    if not ok:
        mat.classification, mat.detail = "flow-error", \
            f"post-gate manifest H5 {mat.h5_root[:12]} != pre-gate H4 " \
            f"{mat.h4_root[:12]}"
    return ok


# ── the contracts ────────────────────────────────────────────────────────────
class SourceContract:
    """Static source/generated relationship for one IP; stateless across
    candidates."""
    name = "base"
    requires_host_validation = False

    def __init__(self, spec: IPSpec):
        self.spec = spec

    # editability -------------------------------------------------------------
    def is_editable(self, rel: str) -> bool:
        raise NotImplementedError

    def editable_roots(self) -> tuple[str, ...]:
        raise NotImplementedError

    def requires_scope(self) -> bool:
        return False

    def path_classes(self) -> dict[str, tuple[str, ...]]:
        """Frozen classes (Rev2.1a SSH.4/D.2) + an explicit `golden` class
        (review SS5.6): `.golden` is a live READ-ONLY design-input snapshot
        with its own lifecycle - it is neither append-only evidence nor
        tool-writable output, so it gets its own mutation class."""
        return {"editable": self.editable_roots(), "tool_writable": (),
                "immutable_deps": (), "golden": (),
                "evidence": (".evidence",)}

    # resources ---------------------------------------------------------------
    def worker_cap(self) -> int:
        return 8

    # host validation ---------------------------------------------------------
    # Trusted expected H-1 profile digest: read-only property backed by a
    # private attribute set ONCE at construction from the frozen
    # TmakeRegistration (re-review2 SS4.2). Public assignment raises
    # AttributeError, so runtime code cannot recreate trusted state
    # (`ctr.bound_validation_digest = x` fails); there is no caller digest
    # argument anywhere. None until host H-1 completes -> PENDING.
    _bound_validation_digest: str | None = None

    @property
    def bound_validation_digest(self) -> str | None:
        return self._bound_validation_digest

    def validation_state(self, profile: ValidationProfile | None = None) -> str:
        """VALIDATED for families host-proven by the banked campaigns.
        Contracts requiring host validation are PENDING until the supplied
        current profile matches the CONTRACT-OWNED bound digest AND carries a
        recognized schema - arbitrary caller-created profiles are
        insufficient. Wrong-typed profiles are structured errors, not opaque
        crashes (re-review3 SS10.1)."""
        if profile is not None and not isinstance(profile, ValidationProfile):
            raise ContractError(
                f"validation_state expects ValidationProfile | None, got "
                f"{type(profile).__name__} (legacy string states were "
                f"removed at checkpoint-1d)")
        if not self.requires_host_validation:
            return "VALIDATED"
        if (profile is not None
                and self.bound_validation_digest
                and profile.contract_schema in KNOWN_SCOPE_SCHEMAS
                and profile.digest() == self.bound_validation_digest):
            return "VALIDATED"
        return "PENDING"

    # representations ---------------------------------------------------------
    def effective_sources(self) -> tuple[str, ...]:
        return tuple(self.spec.sources)

    def source_to_generated(self, rel: str) -> tuple[str, ...]:
        return (rel,)

    def generated_to_source(self, rel: str) -> str | None:
        return rel

    def pristine_editable_state(self, scope: CampaignScope | None = None,
                                repo: Path = None) -> dict[str, str]:
        """Editable-source seed for pools/parents. Every target is validated
        through the same contract/scope path validator (review SS3.3); no
        assert-based enforcement."""
        repo = repo or REPO
        check_scope_compat(self, scope)
        rels = (scope.editable_targets if scope is not None
                else self.effective_sources())
        out = {}
        for rel in rels:
            validate_candidate_path(self, repo, rel, scope)
            out[rel] = (repo / rel).read_text()
        return out

    # regeneration ------------------------------------------------------------
    def regenerate(self, root: Path, runner, touched: list[str] = ()):
        return True, ""

    # fingerprints ------------------------------------------------------------
    def fingerprint_rels(self, root: Path) -> list[str]:
        return list(self.effective_sources())

    def fingerprint(self, root: Path) -> tuple[ManifestEntry, ...]:
        return tree_manifest(root, self.fingerprint_rels(root))

    # inputs ------------------------------------------------------------------
    def design_inputs(self, root: Path, side: str) -> DesignInputs:
        return DesignInputs(side=side, top=self.spec.top,
                            ordered_sources=self.effective_sources(),
                            manifest_digest=manifest_root(
                                self.fingerprint(root)))


class DirectContract(SourceContract):
    """Editable == effective (async_fifo, sha512, flat discovered IPs).
    Byte-identical acceptance to the pre-contract overlay rule."""
    name = "direct"

    def editable_roots(self):
        return (self.spec.rtl_dir,)

    def is_editable(self, rel: str) -> bool:
        return str(Path(rel).parent) == self.spec.rtl_dir


class Sv2vContract(SourceContract):
    """OpenTitan dual representation (AES, Ascon, KMAC, prim + discovered
    generated/*.v + sv_sources arrangements). Two preserved edit modes
    (SS10.2), now with REAL mappings (review SS3.8):
      mode (a) source-edit: an sv_sources `.sv` maps to its authoritative
               generated `{rtl_dir}/<stem>.v` (host-sv2v regenerated);
      mode (b) authoritative-generated: a `.v` provided directly in rtl_dir
               maps to itself (regen skipped; gate-awareness labeled from
               runtime evidence, not here)."""
    name = "sv2v"

    def editable_roots(self):
        return (self.spec.rtl_dir,) + tuple(self.spec.sv_sources)

    def is_editable(self, rel: str) -> bool:
        return (str(Path(rel).parent) == self.spec.rtl_dir
                or rel in self.spec.sv_sources)

    def source_to_generated(self, rel: str) -> tuple[str, ...]:
        if rel in self.spec.sv_sources:
            return (f"{self.spec.rtl_dir}/{Path(rel).stem}.v",)
        if str(Path(rel).parent) == self.spec.rtl_dir:
            return (rel,)                      # mode (b): authoritative .v
        return ()

    def generated_to_source(self, rel: str) -> str | None:
        if rel in self.spec.sv_sources:
            return rel
        if str(Path(rel).parent) == self.spec.rtl_dir:
            stem = Path(rel).stem
            for s in self.spec.sv_sources:
                if Path(s).stem == stem:
                    return s                   # mode (a): diagnose to the .sv
            return rel                         # mode (b): the .v IS the source
        return None


# ── tmake layout + contract ──────────────────────────────────────────────────
@dataclass(frozen=True)
class TmakeLayout:
    """Explicit NVDLA-style layout (review SS3.1/SS7.2: no convention-derived
    single root). The COMPLETE generated root (tripwire/determinism universe)
    is distinct from the editable<->generated mapping root."""
    root: str                       # e.g. "NVDLA"
    config: str                     # e.g. "nv_small"
    editable_root: str              # NVDLA/vmod/nvdla (templates)
    generated_root: str             # NVDLA/outdir/nv_small/vmod  (COMPLETE)
    mapping_root: str               # NVDLA/outdir/nv_small/vmod/nvdla
    filelist: str                   # NVDLA/syn/yosys_syn/nvdla_yosys.f
    filelist_base: str              # dir filelist entries resolve from
    generator_cwd: str              # NVDLA
    generator_cmd: str              # ./tools/bin/tmake -clean -build vmod
    schema: str = "tmake-layout-v1"

    def __post_init__(self):
        for f in ("root", "config", "editable_root", "generated_root",
                  "mapping_root", "filelist", "filelist_base",
                  "generator_cwd", "generator_cmd", "schema"):
            v = getattr(self, f)
            if not v:
                raise ContractError(f"TmakeLayout.{f} must be nonempty")
        for f in ("root", "editable_root", "generated_root", "mapping_root",
                  "filelist", "filelist_base", "generator_cwd"):
            v = getattr(self, f)
            if _canon(v) != v:
                raise ContractError(f"TmakeLayout.{f} non-canonical: {v!r}")
        for f in ("editable_root", "generated_root", "mapping_root",
                  "filelist", "filelist_base"):
            if not getattr(self, f).startswith(self.root + "/"):
                raise ContractError(
                    f"TmakeLayout.{f} not under root {self.root!r}")
        # generator_cwd may BE the root (NVDLA runs tmake from its root)
        if not (self.generator_cwd == self.root
                or self.generator_cwd.startswith(self.root + "/")):
            raise ContractError(
                f"TmakeLayout.generator_cwd not under root {self.root!r}")
        if not self.filelist.startswith(self.filelist_base + "/"):
            raise ContractError(
                "TmakeLayout.filelist must be under filelist_base")
        if not self.mapping_root.startswith(self.generated_root + "/"):
            raise ContractError("TmakeLayout.mapping_root must be under "
                                "generated_root")


@dataclass(frozen=True)
class TmakeRegistration:
    """Immutable trusted registration (re-review2 SS4.2): the layout AND the
    trusted H-1 validation binding travel together as one frozen value loaded
    by the explicit factory. `bound_validation_digest` stays None until host
    H-1 completes - an unbound registration can never yield VALIDATED."""
    layout: TmakeLayout
    bound_validation_digest: str | None = None

    def __post_init__(self):
        # fail-fast configuration quality (re-review3 SS10.2): the binding is
        # either absent or a full sha256 - a typo can never half-match
        if (self.bound_validation_digest is not None
                and not _is_sha256(self.bound_validation_digest)):
            raise ContractError(
                "TmakeRegistration.bound_validation_digest must be None or "
                "64-hex sha256")


# Sealed explicit registry (re-review3 SS4): tmake contracts resolve a
# DECLARED registration - never subtrees[0] conventions. The mutable dict is
# module-PRIVATE; the exported TMAKE_REGISTRY is a read-only MappingProxyType
# view, so `TMAKE_REGISTRY[k] = v` raises - duplicate/late replacement fails
# through the container itself, not just the helper. Contracts additionally
# retain their FROZEN registration at construction, so even a mutated private
# dict cannot affect an already-resolved contract. The layout (incl. schema)
# is hashed into the contract/evaluation identity during consumer migration.
from types import MappingProxyType as _MappingProxy

_TMAKE_REGISTRY: dict[str, TmakeRegistration] = {}
TMAKE_REGISTRY = _MappingProxy(_TMAKE_REGISTRY)   # read-only public view


def register_tmake(ip_name: str, reg: TmakeRegistration) -> TmakeRegistration:
    if not isinstance(reg, TmakeRegistration):
        raise ContractError("register_tmake requires a TmakeRegistration")
    if ip_name in _TMAKE_REGISTRY:
        raise ContractError(
            f"tmake registration for {ip_name!r} already exists - duplicate "
            f"registration is rejected (test-only: _reset_tmake_registry)")
    _TMAKE_REGISTRY[ip_name] = reg
    return reg


def _reset_tmake_registry():
    """TEST-ONLY: clear the registry (never called by production code)."""
    _TMAKE_REGISTRY.clear()


def default_tmake_layout(spec: IPSpec, config: str = "nv_small") -> TmakeLayout:
    """Helper for CONSTRUCTING the standard-shape layout to register
    explicitly. Never auto-invoked by the contract factory."""
    if not spec.subtrees or not spec.filelist:
        raise ContractError(
            f"tmake contract for {spec.name!r} needs spec.subtrees[0] and an "
            f"explicit spec.filelist")
    root = spec.subtrees[0]
    return TmakeLayout(
        root=root, config=config,
        editable_root=f"{root}/vmod/nvdla",
        generated_root=f"{root}/outdir/{config}/vmod",
        mapping_root=f"{root}/outdir/{config}/vmod/nvdla",
        filelist=_canon(spec.filelist),
        filelist_base=str(Path(spec.filelist).parent),
        generator_cwd=root,
        generator_cmd="./tools/bin/tmake -clean -build vmod")


@dataclass(frozen=True)
class FilelistModel:
    """Strictly parsed tool-input structure: exact order preserved; every
    entry resolved to canonical workspace-relative paths; missing/duplicate/
    escaping entries are structured errors (review SS3.1). Construction is
    self-validating (re-review2 SS5.4) - a cached/deserialized model cannot
    bypass the parser's uniqueness/canonicality guarantees."""
    defines: tuple[str, ...]
    include_roots: tuple[str, ...]
    sources: tuple[str, ...]
    digest: str

    def __post_init__(self):
        if not self.sources:
            raise ContractError("FilelistModel: empty sources")
        if not _is_sha256(self.digest):
            raise ContractError("FilelistModel: digest must be 64-hex sha256")
        for name, group in (("defines", self.defines),
                            ("include_roots", self.include_roots),
                            ("sources", self.sources)):
            if len(set(group)) != len(group):
                raise ContractError(f"FilelistModel: duplicates in {name}")
            if any(not g for g in group):
                raise ContractError(f"FilelistModel: empty entry in {name}")
        for p in (*self.include_roots, *self.sources):
            if _canon(p) != p:
                raise ContractError(f"FilelistModel: non-canonical path {p!r}")


class TmakeContract(SourceContract):
    """NVDLA-style: editable templates under <root>/vmod/nvdla, consumed
    representation regenerated into the COMPLETE <root>/outdir/<cfg>/vmod tree
    by tmake. Explicit registry entries only - never auto-discovered."""
    name = "tmake"
    requires_host_validation = True

    def __init__(self, spec: IPSpec):
        """PRODUCTION path only: the registration comes exclusively from the
        sealed registry (re-review3 SS4.5) - there is no constructor bypass.
        Tests inject state by registering (and test-only resetting) through
        register_tmake, the same authority production uses."""
        super().__init__(spec)
        reg = _TMAKE_REGISTRY.get(spec.name)
        if reg is None:
            raise ContractError(
                f"tmake IP {spec.name!r} has no declared TmakeRegistration - "
                f"register one explicitly (register_tmake); layouts are "
                f"never derived by convention")
        # retain ONLY the frozen registration; layout and the trusted binding
        # are derived properties of that immutable value - there is no
        # writable scalar copy to assign (re-review3 SS4.3)
        self._registration = reg
        self._sealed = True

    # sealed against ordinary attribute mutation after construction
    # (re-review3 SS4.4): normal API-level assignment - including to the
    # private backing state - raises. DELETION is sealed too (re-review4 SS4):
    # without __delattr__, `del contract._sealed` would remove the sentinel
    # and re-enable assignment. Hostile introspection (object.__setattr__ /
    # object.__delattr__) is explicitly out of scope per the review.
    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise AttributeError(
                f"TmakeContract is sealed; cannot set {name!r}")
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if getattr(self, "_sealed", False):
            raise AttributeError(
                f"TmakeContract is sealed; cannot delete {name!r}")
        super().__delattr__(name)

    @property
    def layout(self) -> TmakeLayout:
        return self._registration.layout

    @property
    def bound_validation_digest(self) -> str | None:
        return self._registration.bound_validation_digest

    def requires_scope(self) -> bool:
        return True                    # NVDLA v1: one exact target, always

    def worker_cap(self) -> int:
        return 1

    # editability -------------------------------------------------------------
    def editable_roots(self):
        return (self.layout.editable_root,)

    def is_editable(self, rel: str) -> bool:
        return (rel.startswith(self.layout.editable_root + "/")
                and rel.endswith(".v"))

    def path_classes(self) -> dict[str, tuple[str, ...]]:
        r = self.layout.root
        return {
            "editable": (self.layout.editable_root,),
            # candidate-forbidden but legitimately deleted/rewritten by tools
            "tool_writable": (f"{r}/outdir", f"{r}/verif"),
            "immutable_deps": (f"{r}/tools", f"{r}/spec", f"{r}/vmod/vlibs",
                               f"{r}/vmod/rams", self.layout.filelist,
                               f"{r}/tree.make", f"{r}/Makefile"),
            "golden": (".golden",),        # read-only design-input snapshot
            "evidence": (".evidence",),    # append-only evaluation artifacts
        }

    # representations ---------------------------------------------------------
    def source_to_generated(self, rel: str) -> tuple[str, ...]:
        er = self.layout.editable_root
        if not rel.startswith(er + "/"):
            return ()
        return (self.layout.mapping_root + rel[len(er):],)

    def generated_to_source(self, rel: str) -> str | None:
        mr = self.layout.mapping_root
        if not rel.startswith(mr + "/"):
            return None
        return self.layout.editable_root + rel[len(mr):]

    # filelist / tool inputs --------------------------------------------------
    def filelist_model(self, root: Path) -> FilelistModel:
        # the filelist ITSELF is validated unaliased BEFORE any is_file()/
        # read - an external symlink with identical bytes is rejected at the
        # read/check boundary, not laundered by the content digest
        # (re-review2 SS4.4)
        _assert_unaliased(root, self.layout.filelist, "filelist")
        fl = root / self.layout.filelist
        if not fl.is_file():
            raise ContractError(f"filelist missing: {self.layout.filelist}")
        raw = fl.read_bytes()
        base = self.layout.filelist_base
        defines, incs, srcs = [], [], []
        for line in raw.decode().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-D"):
                tok = line[2:].strip()
                if not tok:
                    raise ContractError("filelist: empty -D token")
                defines.append(tok)
            elif line.startswith("-I"):
                tok = line[2:].strip()
                if not tok:
                    raise ContractError("filelist: empty -I token")
                incs.append(_canon(os.path.join(base, tok)))
            else:
                srcs.append(_canon(os.path.join(base, line)))
        for label, group in (("source", srcs), ("include-root", incs),
                             ("define", defines)):
            if len(set(group)) != len(group):
                raise ContractError(f"filelist: duplicate {label} entries")
        # When an IP pins an explicit LEC frontend recipe, it must describe
        # exactly the same environment as the authoritative filelist. This
        # prevents a later filelist change from silently making synthesis and
        # equivalence elaborate different designs. Legacy/default specs leave
        # every field empty/False and preserve the pre-buildout behavior.
        if (self.spec.lec_defines or self.spec.lec_includes
                or self.spec.lec_defer):
            if not self.spec.lec_defer:
                raise ContractError(
                    "tmake LEC frontend override requires lec_defer=True")
            if (len(defines) != len(self.spec.lec_defines)
                    or set(defines) != set(self.spec.lec_defines)):
                raise ContractError(
                    "filelist defines differ from pinned IPSpec.lec_defines")
            if tuple(incs) != self.spec.lec_includes:
                raise ContractError(
                    "filelist include roots differ from pinned "
                    "IPSpec.lec_includes")
        for rel in srcs:
            _assert_unaliased(root, rel, "filelist source")
            if not (root / rel).is_file():
                raise ContractError(f"filelist source missing/non-regular: "
                                    f"{rel}")
        for rel in incs:
            _assert_unaliased(root, rel, "filelist include root")
            if not (root / rel).is_dir():
                raise ContractError(f"filelist include root missing: {rel}")
        return FilelistModel(tuple(defines), tuple(incs), tuple(srcs),
                             _sha256(raw))

    def include_universe(self, root: Path, model: FilelistModel,
                         prefix: str = "") -> tuple[str, ...]:
        """Mechanical (Rev2.1a SSH.4a): every regular *.vh recursively under
        the declared include roots, with an include-token resolution table -
        one logical token (basename, the `include` search key) resolving to
        more than one distinct physical file is an ERROR (review SS4.6).
        Logical (unprefixed) rels returned."""
        by_token: dict[str, str] = {}
        for inc in model.include_roots:
            d = root / (prefix + inc) if prefix else root / inc
            for p in sorted(d.rglob("*.vh")):
                rel_phys = str(p.relative_to(root))
                rel = rel_phys[len(prefix):] if prefix else rel_phys
                _assert_unaliased(root, rel_phys, "include file")
                if not p.is_file():
                    raise ContractError(f"include universe: non-regular {rel}")
                tok = p.name
                if tok in by_token and by_token[tok] != rel:
                    raise ContractError(
                        f"ambiguous include token {tok!r}: resolves to both "
                        f"{by_token[tok]} and {rel}")
                by_token[tok] = rel
        return tuple(sorted(by_token.values()))

    # regeneration ------------------------------------------------------------
    def regenerate(self, root: Path, runner, touched: list[str] = ()):
        r = runner(f"cd {self.layout.generator_cwd} && "
                   f"{self.layout.generator_cmd}", 600)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")

    # fingerprints (complete generated universe ONLY - review SS3.1) ----------
    def fingerprint_rels(self, root: Path) -> list[str]:
        gen = root / self.layout.generated_root
        if not gen.is_dir():
            raise ContractError(
                f"generated root missing: {self.layout.generated_root}")
        rels = [str(p.relative_to(root)) for pat in ("*.v", "*.vh")
                for p in gen.rglob(pat)]
        if not rels:
            raise ContractError(
                f"generated root empty: {self.layout.generated_root}")
        return rels

    # golden snapshot ---------------------------------------------------------
    def golden_dir(self) -> str:
        return f".golden/{self.layout.root}"

    def golden_universe(self, root: Path) -> list[str]:
        """Everything the golden side needs: the complete generated universe,
        every filelist source (incl. the non-outdir inputs), and the include
        universe."""
        model = self.filelist_model(root)
        rels = set(self.fingerprint_rels(root))
        rels.update(model.sources)
        rels.update(self.include_universe(root, model))
        rels.add(self.layout.filelist)
        return sorted(rels)

    def snapshot_golden(self, root: Path) -> tuple[ManifestEntry, ...]:
        """Copy the golden universe to .golden/ (pre-overlay) and return its
        FULL manifest (not only the generated subset). The golden-root PATH is
        validated unaliased before any write (re-review2 SS4.3)."""
        _assert_unaliased(root, self.golden_dir(), "golden root")
        rels = self.golden_universe(root)
        man = tree_manifest(root, rels)
        for e in man:
            dst = root / self.golden_dir() / e.rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / e.rel, dst)
        return man

    def verify_golden(self, root: Path,
                      manifest: tuple[ManifestEntry, ...]) -> bool:
        """Exact membership + size + content, reconstructed WITHOUT following
        links (review SS4.5): any symlink IN THE GOLDEN-ROOT PATH ITSELF
        (`.golden` or its layout component - re-review2 SS4.3) or under the
        golden root - leaf, dir, or a link aliasing back to the candidate
        tree - fails verification, as do extra or missing members."""
        validate_manifest(manifest, "golden manifest")
        try:
            _assert_unaliased(root, self.golden_dir(), "golden root")
        except ContractError:
            return False
        g = root / self.golden_dir()
        if not g.is_dir() or g.is_symlink():
            return False
        actual = {}
        for dirpath, dirnames, filenames in os.walk(g, followlinks=False):
            dp = Path(dirpath)
            for d in dirnames:
                if (dp / d).is_symlink():
                    return False               # symlinked dir inside golden
            for f in filenames:
                p = dp / f
                if p.is_symlink():
                    return False               # symlinked leaf inside golden
                actual[str(p.relative_to(g))] = p
        if set(actual) != {e.rel for e in manifest}:
            return False
        return all(actual[e.rel].stat().st_size == e.size
                   and _hash_file(actual[e.rel]) == e.sha256
                   for e in manifest)

    # inputs (ONE parsed model, side-specific physical roots - review SS3.2) --
    def design_inputs(self, root: Path, side: str) -> DesignInputs:
        if side not in SIDES:
            raise ContractError(f"side must be one of {SIDES}")
        model = self.filelist_model(root)
        prefix = self.golden_dir() + "/" if side == "golden" else ""
        configured = bool(self.spec.lec_defines or self.spec.lec_includes
                          or self.spec.lec_defer)
        logical_includes = (self.spec.lec_includes
                            if configured else model.include_roots)
        logical_defines = (self.spec.lec_defines
                           if configured else model.defines)
        inc_files = self.include_universe(root, model,
                                          prefix=prefix if prefix else "")
        # hash every ordered source + include file at the SIDE-SPECIFIC path,
        # recorded under its physical (side) rel so the digest binds the side
        side_rels = [prefix + r for r in (*model.sources, *inc_files)]
        for rel in side_rels:
            p = root / rel
            if p.is_symlink() or not p.is_file():
                raise ContractError(f"{side} input missing/non-regular: {rel}")
        man = tree_manifest(root, side_rels)
        return DesignInputs(
            side=side, top=self.spec.top,
            ordered_sources=tuple(prefix + s for s in model.sources),
            include_roots=tuple(prefix + i for i in logical_includes),
            include_files=tuple(prefix + f for f in inc_files),
            defines=logical_defines,
            per_file_defer=(self.spec.lec_defer if configured else True),
            filelist_digest=model.digest,
            manifest_digest=manifest_root(man))


# ── path validation (two layers + scope authority - review SS3.3) ────────────
def validate_candidate_path(contract: SourceContract, root: Path, rel: str,
                            scope: CampaignScope | None = None):
    """The one shared candidate-target validator (review SS4.1): canonical
    lexical path, NO symlink at the leaf or any component (so resolved ==
    lexical and a scoped path cannot redirect into immutable/out-of-scope
    files inside the workspace), existing regular file, editable-universe and
    scope membership."""
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts:
        raise ContractError(f"bad candidate path {rel}")
    if _canon(rel) != rel:
        raise ContractError(f"non-canonical candidate path {rel!r}")
    resolved = (root / p).resolve()
    if not str(resolved).startswith(str(root.resolve()) + os.sep):
        raise ContractError(f"candidate path escapes workspace: {rel}")
    _assert_unaliased(root, rel, "candidate path")
    if not (root / p).is_file():
        raise ContractError(f"candidate path {rel} is not an existing "
                            f"regular file")
    if not contract.is_editable(rel):
        raise ContractError(
            f"{rel} outside editable universe {contract.editable_roots()}")
    if scope is not None and rel not in scope.editable_targets:
        raise ContractError(
            f"{rel} not in campaign scope targets {scope.editable_targets}")


def validate_candidate(contract: SourceContract, root: Path,
                       cand_files: dict, scope: CampaignScope | None = None):
    check_scope_compat(contract, scope)
    for rel in cand_files:
        validate_candidate_path(contract, root, rel, scope)
    if scope is not None and len(cand_files) > scope.max_changed_files:
        raise ContractError(
            f"{len(cand_files)} changed files > scope max "
            f"{scope.max_changed_files}")


# ── immutable run context (SS11 migration step 1; re-review5 SS7.1) ──────────
@dataclass(frozen=True, kw_only=True)
class RunContext:
    """ONE immutable per-campaign context: the accepted scope plus the
    effective-worker resolution with full provenance (SSH.5: requested, both
    caps, and the resolved value are all persisted; resolved ONCE here and
    consumed by every executor path). Built only via build_run_context()."""
    scope: CampaignScope
    contract_family: str
    validation_state: str              # derived at build - never caller text
    requested_workers: int
    contract_cap: int
    global_cap: int
    effective_workers: int

    def provenance(self) -> dict:
        return {"scope_id": self.scope.scope_id(),
                "ip": self.scope.ip,
                "contract_family": self.contract_family,
                "validation_state": self.validation_state,
                "requested_workers": self.requested_workers,
                "contract_cap": self.contract_cap,
                "global_cap": self.global_cap,
                "effective_workers": self.effective_workers}


def build_run_context(contract: SourceContract, scope: CampaignScope,
                      profile: ValidationProfile | None = None,
                      global_cap: int = 8) -> RunContext:
    check_scope_compat(contract, scope)
    return RunContext(
        scope=scope,
        contract_family=contract.name,
        validation_state=contract.validation_state(profile),
        requested_workers=scope.requested_workers,
        contract_cap=contract.worker_cap(),
        global_cap=global_cap,
        effective_workers=effective_workers(scope, contract, global_cap))


def campaign_refusal(contract: SourceContract,
                     profile: ValidationProfile | None = None) -> dict | None:
    """Capability gate decision (SS11 step 2; design E.4): returns a
    structured refusal record when a host-validation-requiring contract is not
    VALIDATED - the caller persists it and refuses ALL model calls/evaluation.
    Returns None when the campaign may proceed. Pure: no filesystem access."""
    if not contract.requires_host_validation:
        return None
    state = contract.validation_state(profile)
    if state == "VALIDATED":
        return None
    return {
        "reason": "CONTRACT_VALIDATION_PENDING",
        "ip": contract.spec.name,
        "contract_family": contract.name,
        "expected_profile_digest": contract.bound_validation_digest,
        "current_profile_digest": profile.digest() if profile else None,
        "detail": "host H-1 determinism evidence is not configured/matched; "
                  "optimization and model campaigns are refused (keyless "
                  "pristine validation and sandbox construction remain "
                  "allowed - design rev2.1 SSE.4)",
    }


def registration_digest(contract: SourceContract) -> str:
    """Exact contract-registration identity for evaluation IDs: for tmake,
    the full layout + schema + validation binding; for legacy families, the
    family name + spec editable fields."""
    spec_facts = {"top": contract.spec.top,
                  "clocks": [[c.name, c.period_ns]
                             for c in contract.spec.clocks],
                  "resets": [list(r) for r in contract.spec.resets],
                  "gate_dir": contract.spec.gate_dir,
                  "gate_cmd": contract.spec.gate_cmd,
                  "filelist": contract.spec.filelist,
                  "lec_defines": list(contract.spec.lec_defines),
                  "lec_includes": list(contract.spec.lec_includes),
                  "lec_defer": contract.spec.lec_defer,
                  "lec_pristine_seconds":
                      contract.spec.lec_pristine_seconds}
    if isinstance(contract, TmakeContract):
        blob = json.dumps({"layout": asdict(contract.layout),
                           "bound": contract.bound_validation_digest,
                           "spec": spec_facts},
                          sort_keys=True)
    else:
        blob = json.dumps({"family": contract.name,
                           "rtl_dir": contract.spec.rtl_dir,
                           "sv_sources": list(contract.spec.sv_sources),
                           "spec": spec_facts},
                          sort_keys=True)
    return _sha256(blob.encode())


# ── resolution ───────────────────────────────────────────────────────────────
_FAMILIES = {"direct": DirectContract, "sv2v": Sv2vContract,
             "tmake": TmakeContract}


def get_contract(spec: IPSpec) -> SourceContract:
    """Empty key -> documented legacy classifier (sv_sources nonempty -> sv2v,
    else direct). tmake is never inferred. Unknown nonempty keys are
    structured configuration errors, never silent fallbacks."""
    key = spec.contract or ("sv2v" if spec.sv_sources else "direct")
    try:
        cls = _FAMILIES[key]
    except KeyError:
        raise ContractError(
            f"unknown contract family '{key}' for IP '{spec.name}' "
            f"(known: {sorted(_FAMILIES)})") from None
    return cls(spec)
