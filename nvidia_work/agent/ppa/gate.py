"""Structural gate adapter (corrective slice 2; review SS4.1/4.2).

Candidate-to-artifact CAUSALITY, not correlation:
  - the GatePlan is CANONICAL per contract: paths are canonicalized and
    containment-validated at construction (no `..`/absolute/symlink-aliased
    spellings - review SS4.2), the plan carries a full content digest, and
    `run_tmake_gate` REQUIRES the regeneration phase to be the contract's
    registered generator recipe and the test phase to structurally execute
    the declared artifact;
  - CLEAN uses validated filesystem deletion of resolved-contained roots
    (never a constructed `rm -rf` string);
  - the full immutable/editable/golden mutation audit re-runs around the
    gate's own regeneration (review SS4.1);
  - phases: CLEAN -> REGENERATE -> COMPILE -> LINK -> EXECUTE_TESTS ->
    PARSE_RESULTS (normative H.4e; LINK is its own recorded phase);
  - GateEvidence is self-validating and its ref covers the plan digest,
    every phase (name/cmd/rc/log), counts, and H4/H5 - any plan or phase
    change changes the ref and therefore the evaluation identity.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
from dataclasses import dataclass

from . import contract as C
from . import materialize as M


@dataclass(frozen=True)
class GatePlan:
    """Canonical phase commands + artifact binding for one gate family."""
    clean_dirs: tuple[str, ...]      # tool-writable build outputs, NONEMPTY
    regen_cmd: str                   # MUST match the contract generator
    build_cmd: str                   # compile producing the objects
    link_cmd: str                    # link producing exe_path (H.4e LINK)
    exe_path: str                    # workspace-relative artifact
    test_args: tuple = ()            # argv TOKENS for the executed artifact
    schema: str = "tmake-gate-v3"

    def __post_init__(self):
        if not self.clean_dirs or not self.exe_path:
            raise C.ContractError(
                "GatePlan requires nonempty clean_dirs and exe_path - an "
                "unbound plan is not eligibility-capable")
        for f in ("regen_cmd", "build_cmd", "link_cmd"):
            if not getattr(self, f):
                raise C.ContractError(f"GatePlan.{f} must be nonempty")
        if not isinstance(self.test_args, tuple) or any(
                not isinstance(a, str) or not a or a.isspace()
                for a in self.test_args):
            raise C.ContractError(
                "GatePlan.test_args must be a tuple of nonempty string "
                "tokens (free-form shell strings are refused)")
        # canonical, traversal-free paths ONLY (review SS4.2)
        for p in (*self.clean_dirs, self.exe_path):
            if ".." in p.split("/") or p.startswith("/") or C._canon(p) != p:
                raise C.ContractError(
                    f"GatePlan path {p!r} not canonical/relative")
        # the artifact must live inside a declared clean root (rebuilt fresh)
        if not any(self.exe_path == d or self.exe_path.startswith(d + "/")
                   for d in self.clean_dirs):
            raise C.ContractError(
                "GatePlan.exe_path must be inside a clean root (otherwise a "
                "stale artifact could survive CLEAN)")

    def test_cmd(self) -> str:
        """The EXECUTED command is derived from the declared artifact with
        every argument token SHELL-QUOTED (corrective2 review SS4.1: a token
        beginning with `;` is an inert argument, never a second command).
        Full argv-tuple execution end-to-end lands with the docker-runner
        argv migration (named deferred)."""
        import shlex
        return " ".join([f"./{self.exe_path}",
                         *[shlex.quote(str(a)) for a in self.test_args]])

    def digest(self) -> str:
        blob = json.dumps({"clean": list(self.clean_dirs),
                           "regen": self.regen_cmd, "build": self.build_cmd,
                           "link": self.link_cmd, "exe": self.exe_path,
                           "args": list(self.test_args),
                           "schema": self.schema},
                          sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class TraceGatePlan:
    """Canonical clean/regenerate/build/trace plan for NVDLA-style gates.

    This is deliberately a sibling of GatePlan.  A trace build performs
    compile+link in one authoritative tmake invocation, so recording a fake
    LINK phase would manufacture evidence.  The trace driver, cwd, environment
    and editable partition are all registered data; callers cannot append
    free-form shell fragments at evaluation time.
    """
    clean_dirs: tuple[str, ...]
    regen_cmd: str
    build_cmd: str
    exe_path: str
    test_cwd: str
    test_env: tuple[tuple[str, str], ...]
    test_driver: str
    editable_roots: tuple[str, ...]
    schema: str = "tmake-trace-gate-v1"

    def __post_init__(self):
        if not self.clean_dirs or not self.exe_path:
            raise C.ContractError(
                "TraceGatePlan requires nonempty clean_dirs and exe_path")
        for f in ("regen_cmd", "build_cmd", "test_cwd", "test_driver",
                  "schema"):
            if not getattr(self, f):
                raise C.ContractError(f"TraceGatePlan.{f} must be nonempty")
        for p in (*self.clean_dirs, self.exe_path, self.test_cwd,
                  self.test_driver, *self.editable_roots):
            if (".." in p.split("/") or p.startswith("/")
                    or C._canon(p) != p):
                raise C.ContractError(
                    f"TraceGatePlan path {p!r} not canonical/relative")
        if not self.editable_roots:
            raise C.ContractError(
                "TraceGatePlan requires an explicit editable partition")
        if not any(self.exe_path == d or self.exe_path.startswith(d + "/")
                   for d in self.clean_dirs):
            raise C.ContractError(
                "TraceGatePlan.exe_path must be inside a clean root")
        if (not isinstance(self.test_env, tuple)
                or any(not isinstance(x, tuple) or len(x) != 2
                       for x in self.test_env)):
            raise C.ContractError(
                "TraceGatePlan.test_env must be a tuple of (name,value)")
        names = []
        for name, value in self.test_env:
            if not isinstance(name, str) or not re.fullmatch(
                    r"[A-Z_][A-Z0-9_]*", name):
                raise C.ContractError(
                    f"TraceGatePlan invalid environment name {name!r}")
            if (not isinstance(value, str) or not value
                    or "\x00" in value or "\n" in value):
                raise C.ContractError(
                    f"TraceGatePlan invalid value for {name}")
            names.append(name)
        if len(set(names)) != len(names):
            raise C.ContractError(
                "TraceGatePlan.test_env contains duplicate names")

    def scope_compatible(self, scope: C.CampaignScope | None) -> bool:
        if scope is None:
            return False
        return all(any(t == root or t.startswith(root + "/")
                       for root in self.editable_roots)
                   for t in scope.editable_targets)

    def test_cmd(self) -> str:
        env = " ".join(
            f"{name}={shlex.quote(value)}" for name, value in self.test_env)
        driver = shlex.quote("./" + self.test_driver)
        return (f"cd {shlex.quote(self.test_cwd)} && "
                f"env {env} {driver}")

    def digest(self) -> str:
        blob = json.dumps({
            "clean": list(self.clean_dirs), "regen": self.regen_cmd,
            "build": self.build_cmd, "exe": self.exe_path,
            "test_cwd": self.test_cwd,
            "test_env": [list(x) for x in self.test_env],
            "test_driver": self.test_driver,
            "editable_roots": list(self.editable_roots),
            "schema": self.schema,
        }, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()


# canonical plan registry (one per contract family/IP; duplicate rejected)
_GATE_PLANS: dict[str, GatePlan | TraceGatePlan] = {}


def register_gate_plan(ip: str, plan: GatePlan | TraceGatePlan):
    if not isinstance(plan, (GatePlan, TraceGatePlan)):
        raise C.ContractError(
            "gate plan must be GatePlan or TraceGatePlan")
    if ip in _GATE_PLANS:
        raise C.ContractError(f"gate plan for {ip!r} already registered")
    _GATE_PLANS[ip] = plan
    return plan


def get_gate_plan(ip: str) -> GatePlan | TraceGatePlan | None:
    return _GATE_PLANS.get(ip)


def _reset_gate_plans():
    """TEST-ONLY."""
    _GATE_PLANS.clear()


_HEX64_OK = C._is_sha256


@dataclass(frozen=True)
class GatePhase:
    name: str
    cmd: str
    rc: int | None
    log_sha: str
    log_tail: str = ""

    def __post_init__(self):
        if self.name not in ("CLEAN", "REGENERATE", "COMPILE", "LINK",
                             "BUILD", "EXECUTE_TESTS", "PARSE_RESULTS"):
            raise C.ContractError(f"unknown gate phase {self.name}")
        if self.log_sha and not _HEX64_OK(self.log_sha):
            raise C.ContractError("phase log_sha must be 64-hex")


_PHASE_ORDER = ("CLEAN", "REGENERATE", "COMPILE", "LINK", "EXECUTE_TESTS",
                "PARSE_RESULTS")


@dataclass(frozen=True)
class GateEvidence:
    """Immutable, SELF-VALIDATING gate evidence (review SS4.4): phase order,
    count sanity, and hash shapes are checked at construction; the ref covers
    plan digest + every phase + counts + H4/H5, so ANY plan/phase change
    changes the ref (review SS4.7)."""
    phases: tuple
    tests_passed: int
    tests_failed: int
    passed: bool
    candidate_aware: bool
    detail: str
    exe_sha: str
    h4_root: str
    h5_root: str
    plan_digest: str

    def __post_init__(self):
        names = [p.name for p in self.phases]
        if names != list(_PHASE_ORDER[:len(names)]):
            raise C.ContractError(f"gate phases out of order: {names}")
        if self.tests_passed < 0 or self.tests_failed < 0:
            raise C.ContractError("negative test counts")
        for f in ("exe_sha", "h4_root", "h5_root"):
            v = getattr(self, f)
            if v and not _HEX64_OK(v):
                raise C.ContractError(f"GateEvidence.{f} must be 64-hex")
        if not _HEX64_OK(self.plan_digest):
            raise C.ContractError("GateEvidence.plan_digest must be 64-hex")
        if self.candidate_aware and not (
                self.passed and self.exe_sha and self.tests_passed > 0
                and self.h4_root and self.h4_root == self.h5_root
                and len(self.phases) == len(_PHASE_ORDER)):
            raise C.ContractError(
                "candidate_aware requires passed + full phases + exe hash + "
                "tests>0 + H5==H4 (inconsistent evidence rejected)")

    def ref(self) -> str:
        blob = json.dumps({
            "plan": self.plan_digest,
            "phases": [[p.name, p.cmd, p.rc, p.log_sha] for p in self.phases],
            "tests": [self.tests_passed, self.tests_failed],
            "exe": self.exe_sha, "h4": self.h4_root, "h5": self.h5_root},
            sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()


_TRACE_PHASE_ORDER = ("CLEAN", "REGENERATE", "BUILD", "EXECUTE_TESTS",
                      "PARSE_RESULTS")


@dataclass(frozen=True)
class TraceGateEvidence:
    """Self-validating evidence for a combined-build trace gate."""
    phases: tuple
    tests_passed: int
    tests_failed: int
    passed: bool
    candidate_aware: bool
    detail: str
    exe_sha: str
    driver_sha: str
    h4_root: str
    h5_root: str
    plan_digest: str

    def __post_init__(self):
        names = [p.name for p in self.phases]
        if names != list(_TRACE_PHASE_ORDER[:len(names)]):
            raise C.ContractError(
                f"trace gate phases out of order: {names}")
        if self.tests_passed < 0 or self.tests_failed < 0:
            raise C.ContractError("negative trace-test counts")
        for f in ("exe_sha", "driver_sha", "h4_root", "h5_root"):
            v = getattr(self, f)
            if v and not _HEX64_OK(v):
                raise C.ContractError(
                    f"TraceGateEvidence.{f} must be 64-hex")
        if not _HEX64_OK(self.plan_digest):
            raise C.ContractError(
                "TraceGateEvidence.plan_digest must be 64-hex")
        if self.candidate_aware and not (
                self.passed and self.exe_sha and self.driver_sha
                and self.tests_passed > 0 and self.tests_failed == 0
                and self.h4_root and self.h4_root == self.h5_root
                and len(self.phases) == len(_TRACE_PHASE_ORDER)):
            raise C.ContractError(
                "trace candidate_aware requires passed + full phases + "
                "artifact/driver hashes + tests>0 + H5==H4")

    def ref(self) -> str:
        blob = json.dumps({
            "plan": self.plan_digest,
            "phases": [[p.name, p.cmd, p.rc, p.log_sha]
                       for p in self.phases],
            "tests": [self.tests_passed, self.tests_failed],
            "exe": self.exe_sha, "driver": self.driver_sha,
            "h4": self.h4_root, "h5": self.h5_root,
        }, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()


# Runner summaries come in two shapes: "3 PASS, 1 FAIL" (legacy iverilog TBs)
# and "Done: 1 passed, 0 failed" (the NVDLA trace runner). The optional ED
# suffix covers both. WITHOUT it the NVDLA summary silently failed to match —
# the pattern required a comma immediately after PASS, but the runner writes
# "passed," — so `sums` came back empty and the parser fell through to marker
# heuristics, inventing pass=2/fail=1 on a run the runner itself reported as
# "1 passed, 0 failed" (2026-07-25 false FAIL; NVDLA release packet stuck 5/6).
_RE_SUMMARY = re.compile(r"(\d+) +PASS(?:ED)?, *(\d+) +FAIL(?:ED)?",
                         re.IGNORECASE)
# Runner POLICY/help text is not a result. The NVDLA trace runner prints
# "TEST_TIMEOUT_SEC=4500 (per test; exceeded => failed)" as a banner; the word
# "failed" there is documentation. Removed at PATTERN level, never by dropping
# whole lines (corrective2 review SS4.6), so a genuine FAIL sharing a line is
# still counted.
_RE_POLICY_TEXT = re.compile(r"exceeded\s*=>\s*fail(?:ed)?", re.IGNORECASE)
_RE_PASSMARK = re.compile(r"\[PASS\]|::.*PASS|\bPASSED\b", re.IGNORECASE)
_RE_FAILMARK = re.compile(r"\[FAIL\]|::.*FAIL|\bFAILED\b", re.IGNORECASE)
# zero-count fail counters ("Failed: 0", "0 FAILED", "errors: 0") are NOT
# failures and must be stripped before counting FAIL markers (2026-07-23; the
# OpenTitan Verilator TBs print "Failed: 0" on a pass). Only exact-zero counts.
_RE_ZEROFAIL = re.compile(
    r"(?:fail(?:ed|ures)?|errors?)\s*[:=]?\s*0+\b"
    r"|\b0+\s+(?:fail(?:ed|ures)?|errors?)\b", re.IGNORECASE)


def parse_test_results(out: str) -> tuple[int, int, str]:
    """FAIL evidence is scanned over the COMPLETE output with only the summary
    and zero-count PATTERN text removed (never whole lines - corrective2 review
    SS4.6); line exclusion exists only to avoid double-counting PASS. Markers
    are case-insensitive."""
    sums = {(int(m.group(1)), int(m.group(2)))
            for m in _RE_SUMMARY.finditer(out)}
    if len(sums) > 1:
        return 0, 0, f"contradictory summaries {sorted(sums)}"
    fails = len(_RE_FAILMARK.findall(
        _RE_POLICY_TEXT.sub("", _RE_ZEROFAIL.sub("", _RE_SUMMARY.sub("", out)))))
    body = "\n".join(l for l in _RE_POLICY_TEXT.sub("", out).splitlines()
                     if not re.search(r"TOTAL|SUMMARY", l, re.IGNORECASE))
    # The summary line itself carries the words "passed"/"failed" and would be
    # double-counted as a PASS marker in the no-summary fallback below.
    body = _RE_SUMMARY.sub("", body)
    if len(sums) == 1:
        p, f = next(iter(sums))
        if f == 0 and fails > 0:
            return p, fails, "summary PASS contradicted by FAIL markers"
        return p, f, ""
    return (len(_RE_PASSMARK.findall(body)), fails, "")


def _validated_clean(ws_root, ctr, clean_dirs):
    """Validated filesystem deletion (review SS4.2): every clean root must be
    canonical, unaliased, and RESOLVE inside a tool-writable root before
    anything is removed. Never builds an `rm -rf` shell string."""
    tw = ctr.path_classes()["tool_writable"]
    for d in clean_dirs:
        if not any(d == t or d.startswith(t + "/") for t in tw):
            raise C.ContractError(f"clean dir {d} outside tool-writable class")
        # alias validation runs UNCONDITIONALLY (SS4.7): a nonexistent leaf
        # never skips the parent-component symlink walk
        C._assert_unaliased(ws_root, d, "clean dir")
        p = ws_root / d
        rp, rr = p.resolve(), ws_root.resolve()
        if not (str(rp) == str(rr) or str(rp).startswith(str(rr) + "/")):
            raise C.ContractError(f"clean dir {d} escapes the workspace")
        if p.exists():
            shutil.rmtree(p)


def run_tmake_gate(ws, ctr: C.TmakeContract, mrun: "M.MaterializationRun",
                   plan: GatePlan | TraceGatePlan | None = None, runner=None,
                   scope=None, timeout: int = 1800
                   ) -> GateEvidence | TraceGateEvidence:
    runner = runner or ws.run
    plan = plan or _GATE_PLANS.get(ctr.spec.name)
    if isinstance(plan, TraceGatePlan):
        return _run_trace_gate(ws, ctr, mrun, plan, runner=runner,
                               scope=scope, timeout=timeout)
    state = {"passed": False, "aware": False, "detail": "", "exe": "",
             "tp": 0, "tf": 0}
    phases: list[GatePhase] = []

    def evidence() -> GateEvidence:
        return GateEvidence(
            phases=tuple(phases), tests_passed=state["tp"],
            tests_failed=state["tf"], passed=state["passed"],
            candidate_aware=state["aware"], detail=state["detail"],
            exe_sha=state["exe"], h4_root=mrun.mat.h4_root,
            h5_root=mrun.mat.h5_root if mrun.mat.h5 else "",
            plan_digest=plan.digest() if plan else "0" * 64)

    if plan is None:
        state["detail"] = "no canonical GatePlan registered for this contract"
        return evidence()

    # CAUSALITY (review SS4.1): the regeneration phase must BE the contract's
    # registered generator recipe - an arbitrary command is refused
    canonical_regen = (f"cd {ctr.layout.generator_cwd} && "
                       f"{ctr.layout.generator_cmd}")
    if plan.regen_cmd != canonical_regen:
        state["detail"] = ("plan regen_cmd is not the contract generator "
                          f"recipe ({canonical_regen!r} required)")
        return evidence()

    def phase(name, cmd, tmo) -> tuple[bool, str]:
        r = runner(cmd, tmo)
        out = (r.stdout or "") + (r.stderr or "")
        phases.append(GatePhase(
            name=name, cmd=cmd, rc=r.returncode,
            log_sha=hashlib.sha256(out.encode()).hexdigest(),
            log_tail=out[-400:]))
        if r.returncode != 0:
            state["detail"] = f"phase {name} rc={r.returncode}"
            return False, out
        return True, out

    # audit baseline around the GATE's own tool invocations (review SS4.1)
    imm0 = M.immutable_manifest(ws.root, ctr)
    edit0 = {rel: C._hash_file(ws.root / rel) for rel in mrun.mat.h2}

    # CLEAN: validated fs deletion; artifact must be GONE afterwards
    try:
        _validated_clean(ws.root, ctr, plan.clean_dirs)
    except C.ContractError as e:
        state["detail"] = str(e)
        return evidence()
    phases.append(GatePhase(
        name="CLEAN", cmd=f"<validated rmtree {plan.clean_dirs}>", rc=0,
        log_sha=hashlib.sha256(str(plan.clean_dirs).encode()).hexdigest()))
    if (ws.root / plan.exe_path).exists():
        state["detail"] = "stale artifact survived CLEAN"
        return evidence()

    # REGENERATE (the contract recipe, verified above)
    ok, _ = phase("REGENERATE", plan.regen_cmd, timeout)
    if not ok:
        return evidence()

    # COMPILE then LINK (H.4e: separate recorded phases)
    ok, _ = phase("COMPILE", plan.build_cmd, timeout)
    if not ok:
        return evidence()
    ok, _ = phase("LINK", plan.link_cmd, timeout)
    if not ok:
        return evidence()
    exe = ws.root / plan.exe_path
    if not exe.is_file() or exe.is_symlink():
        state["detail"] = f"link produced no artifact ({plan.exe_path})"
        return evidence()
    state["exe"] = C._hash_file(exe)

    # EXECUTE_TESTS: structurally executes the DECLARED artifact
    ok, test_out = phase("EXECUTE_TESTS", plan.test_cmd(), timeout)
    if not ok:
        return evidence()
    if not exe.is_file() or C._hash_file(exe) != state["exe"]:
        state["detail"] = "executed artifact changed during tests"
        return evidence()

    # PARSE_RESULTS over the FULL execution output
    tp, tf, note = parse_test_results(test_out)
    phases.append(GatePhase(
        name="PARSE_RESULTS", cmd="<parser tmake-gate-v2>", rc=0,
        log_sha=hashlib.sha256(test_out.encode()).hexdigest(),
        log_tail=f"passed={tp} failed={tf} {note}"))
    state["tp"], state["tf"] = tp, tf
    if note:
        state["detail"] = note
        return evidence()
    if tp + tf == 0:
        state["detail"] = "gate executed zero tests"
        return evidence()
    if tf > 0:
        state["detail"] = f"{tf} tests failed"
        return evidence()

    # gate-invocation mutation audit (review SS4.1): the gate's own tools may
    # write ONLY the tool-writable class
    if M.immutable_manifest(ws.root, ctr) != imm0:
        state["detail"] = "gate mutated an immutable dependency"
        return evidence()
    if {rel: C._hash_file(ws.root / rel) for rel in mrun.mat.h2} != edit0:
        state["detail"] = "gate mutated editable sources"
        return evidence()

    # H5 stability + golden re-verification + frozen receipt (steps 9-10)
    if not M.post_gate(ws, ctr, mrun, scope=scope):
        state["detail"] = mrun.mat.detail
        return evidence()

    state["passed"] = True
    state["aware"] = (mrun.mat.h5_root == mrun.mat.h4_root and tp > 0
                      and bool(state["exe"]))
    return evidence()


def _run_trace_gate(ws, ctr: C.TmakeContract,
                    mrun: "M.MaterializationRun", plan: TraceGatePlan, *,
                    runner, scope, timeout: int
                    ) -> TraceGateEvidence:
    """Run the canonical combined-build NVDLA trace gate.

    A failed trace is still parsed so the evidence distinguishes a counted
    functional failure from a tool/runner failure.  Only a zero-rc,
    positive-count trace with stable artifact, driver, immutable/editable
    state and H5 can become candidate-aware.
    """
    state = {"passed": False, "aware": False, "detail": "", "exe": "",
             "driver": "", "tp": 0, "tf": 0}
    phases: list[GatePhase] = []

    def evidence() -> TraceGateEvidence:
        return TraceGateEvidence(
            phases=tuple(phases), tests_passed=state["tp"],
            tests_failed=state["tf"], passed=state["passed"],
            candidate_aware=state["aware"], detail=state["detail"],
            exe_sha=state["exe"], driver_sha=state["driver"],
            h4_root=mrun.mat.h4_root,
            h5_root=mrun.mat.h5_root if mrun.mat.h5 else "",
            plan_digest=plan.digest())

    canonical_regen = (f"cd {ctr.layout.generator_cwd} && "
                       f"{ctr.layout.generator_cmd}")
    if plan.regen_cmd != canonical_regen:
        state["detail"] = (
            "trace plan regen_cmd is not the contract generator recipe "
            f"({canonical_regen!r} required)")
        return evidence()
    if not plan.scope_compatible(scope):
        state["detail"] = (
            "trace plan editable partition does not cover campaign scope")
        return evidence()

    def phase(name, cmd, tmo):
        try:
            r = runner(cmd, tmo)
            out = (r.stdout or "") + (r.stderr or "")
            rc = r.returncode
        except Exception as e:
            # Normalize tool/timeout failures into evidence; do not let an
            # incomplete gate escape as an uncaught orchestration exception.
            out = f"{type(e).__name__}: {e}"
            rc = None
        phases.append(GatePhase(
            name=name, cmd=cmd, rc=rc,
            log_sha=hashlib.sha256(out.encode()).hexdigest(),
            log_tail=out[-400:]))
        return rc, out

    try:
        imm0 = M.immutable_manifest(ws.root, ctr)
        edit0 = {rel: C._hash_file(ws.root / rel)
                 for rel in mrun.mat.h2}
    except (C.ContractError, OSError) as e:
        state["detail"] = f"trace preflight audit failed: {e}"
        return evidence()

    try:
        _validated_clean(ws.root, ctr, plan.clean_dirs)
    except C.ContractError as e:
        state["detail"] = str(e)
        return evidence()
    phases.append(GatePhase(
        name="CLEAN", cmd=f"<validated rmtree {plan.clean_dirs}>", rc=0,
        log_sha=hashlib.sha256(str(plan.clean_dirs).encode()).hexdigest()))
    exe = ws.root / plan.exe_path
    if exe.exists():
        state["detail"] = "stale trace artifact survived CLEAN"
        return evidence()

    rc, _ = phase("REGENERATE", plan.regen_cmd, min(timeout, 900))
    if rc != 0:
        state["detail"] = f"phase REGENERATE rc={rc}"
        return evidence()
    try:
        regenerated_root = C.manifest_root(ctr.fingerprint(ws.root))
    except C.ContractError as e:
        state["detail"] = f"trace regeneration fingerprint failed: {e}"
        return evidence()
    if regenerated_root != mrun.mat.h4_root:
        state["detail"] = (
            "trace regeneration did not reproduce the candidate-generated "
            "manifest")
        return evidence()

    rc, _ = phase("BUILD", plan.build_cmd, max(timeout, 7200))
    if rc != 0:
        state["detail"] = f"phase BUILD rc={rc}"
        return evidence()
    if not exe.is_file() or exe.is_symlink():
        state["detail"] = (
            f"trace build produced no regular artifact ({plan.exe_path})")
        return evidence()
    state["exe"] = C._hash_file(exe)

    driver_rel = C._canon(f"{plan.test_cwd}/{plan.test_driver}")
    try:
        C._assert_unaliased(ws.root, driver_rel, "trace driver")
    except C.ContractError as e:
        state["detail"] = str(e)
        return evidence()
    driver = ws.root / driver_rel
    if not driver.is_file() or driver.is_symlink():
        state["detail"] = (
            f"trace driver missing/non-regular ({driver_rel})")
        return evidence()
    state["driver"] = C._hash_file(driver)

    test_rc, test_out = phase(
        "EXECUTE_TESTS", plan.test_cmd(), max(timeout, 21600))
    tp, tf, note = parse_test_results(test_out)
    phases.append(GatePhase(
        name="PARSE_RESULTS", cmd="<parser tmake-trace-gate-v1>", rc=0,
        log_sha=hashlib.sha256(test_out.encode()).hexdigest(),
        log_tail=f"passed={tp} failed={tf} {note}"))
    state["tp"], state["tf"] = tp, tf

    try:
        if not exe.is_file() or C._hash_file(exe) != state["exe"]:
            state["detail"] = "trace artifact changed during tests"
            return evidence()
        if not driver.is_file() or C._hash_file(driver) != state["driver"]:
            state["detail"] = "trace driver changed during tests"
            return evidence()
        if M.immutable_manifest(ws.root, ctr) != imm0:
            state["detail"] = "trace gate mutated an immutable dependency"
            return evidence()
        if ({rel: C._hash_file(ws.root / rel) for rel in mrun.mat.h2}
                != edit0):
            state["detail"] = "trace gate mutated editable sources"
            return evidence()
    except (C.ContractError, OSError) as e:
        state["detail"] = f"trace post-test audit failed: {e}"
        return evidence()

    if note:
        state["detail"] = note
        return evidence()
    if tp + tf == 0:
        state["detail"] = "trace gate executed zero tests"
        return evidence()
    if tf > 0:
        state["detail"] = f"{tf} trace tests failed (rc={test_rc})"
        return evidence()
    if test_rc != 0:
        state["detail"] = (
            f"trace runner rc={test_rc} without a counted functional failure")
        return evidence()

    if not M.post_gate(ws, ctr, mrun, scope=scope):
        state["detail"] = mrun.mat.detail
        return evidence()
    state["passed"] = True
    state["aware"] = (
        mrun.mat.h5_root == mrun.mat.h4_root and tp > 0
        and bool(state["exe"]) and bool(state["driver"]))
    return evidence()
