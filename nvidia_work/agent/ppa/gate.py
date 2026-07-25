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


# canonical plan registry (one per contract family/IP; duplicate rejected)
_GATE_PLANS: dict[str, GatePlan] = {}


def register_gate_plan(ip: str, plan: GatePlan) -> GatePlan:
    if ip in _GATE_PLANS:
        raise C.ContractError(f"gate plan for {ip!r} already registered")
    _GATE_PLANS[ip] = plan
    return plan


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
                             "EXECUTE_TESTS", "PARSE_RESULTS"):
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


_RE_SUMMARY = re.compile(r"(\d+) +PASS, *(\d+) +FAIL", re.IGNORECASE)
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
        _RE_ZEROFAIL.sub("", _RE_SUMMARY.sub("", out))))
    body = "\n".join(l for l in out.splitlines()
                     if not re.search(r"TOTAL|SUMMARY", l, re.IGNORECASE))
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
                   plan: GatePlan | None = None, runner=None, scope=None,
                   timeout: int = 1800) -> GateEvidence:
    runner = runner or ws.run
    plan = plan or _GATE_PLANS.get(ctr.spec.name)
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
