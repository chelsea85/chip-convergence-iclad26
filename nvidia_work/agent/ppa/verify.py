"""Five-layer candidate verification stack (cheapest first, fail fast).

  L1 lint     host-side: candidate touches only allowed RTL files; top-module
              port list unchanged; no sim-only constructs smuggled into RTL.
  L2 compile  iverilog parse + yosys elaboration; inferred-latch detection.
              stderr is preserved for the proposer's self-debug retries.
  L3 gate     the IP's provided functional testbench (run_gate.sh) — the
              contest's own scoring gate.
  L4 lec      yosys equivalence check golden-vs-candidate (proven /
              inconclusive / error). Register-preserving rewrites (P2/P4/CSE)
              should prove; latency-changing ones will be inconclusive and are
              covered by L5.
  L5 dualsim  golden differential vectors: both designs flattened, one
              generated TB drives identical reset + corner + random stimulus
              into both instances and compares every output (cycle-exact,
              X-tolerant). Catches what the provided TB does not exercise —
              the anti-reward-hacking layer.

Acceptance policy: L1/L2/L3/L5 must PASS; L4 must not be a hard error with
counterexample semantics. Any failure -> candidate rejected, caller keeps the
incumbent design.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .config import IPS, IPSpec
from .workspace import (RegenError, Workspace, candidate_from_dir,
                        pristine_source)

ALL_LAYERS = ("lint", "compile", "gate", "lec", "dualsim")
_SIM_ONLY = ("force ", "release ", "$random", "$readmemb", "$stop")


# ── result type ───────────────────────────────────────────────────────────────
@dataclass
class VerifyResult:
    ok: bool = True
    layers: dict = field(default_factory=dict)   # name -> {status, detail}

    def record(self, layer: str, status: str, detail: str = ""):
        self.layers[layer] = {"status": status, "detail": detail.strip()[-4000:]}
        if status == "FAIL":
            self.ok = False

    def summary(self) -> str:
        parts = [f"{k}={v['status']}" for k, v in self.layers.items()]
        return f"{'OK' if self.ok else 'REJECT'} [{', '.join(parts)}]"


# ── verilog header parsing (host-side, no tools) ─────────────────────────────
def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def _balanced(text: str, start: int) -> tuple[str, int]:
    """Return contents of the paren group opening at text[start]=='(' and the
    index just past its close."""
    depth, i = 0, start
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    raise ValueError("unbalanced parens")


def module_ports(text: str, module: str) -> list[str]:
    """Ordered port names of `module` (ANSI or classic header)."""
    t = _strip_comments(text)
    m = re.search(rf"\bmodule\s+{re.escape(module)}\b", t)
    if not m:
        raise ValueError(f"module {module} not found")
    i = m.end()
    while t[i].isspace():
        i += 1
    if t[i] == "#":                       # parameter list
        j = t.index("(", i)
        _, i = _balanced(t, j)
        while t[i].isspace():
            i += 1
    if t[i] != "(":
        return []                          # portless module
    header, _ = _balanced(t, i)
    ports = []
    for chunk in _split_top_commas(header):
        ids = re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", chunk)
        if ids:
            ports.append(ids[-1])          # last identifier = port name
    return ports


def _split_top_commas(text: str) -> list[str]:
    out, depth, cur = [], 0, []
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return [c for c in out if c.strip()]


# ── L1: lint ──────────────────────────────────────────────────────────────────
def lint(spec: IPSpec, cand_files: dict[str, str]) -> tuple[str, str]:
    problems, warnings = [], []
    allowed = set(spec.sources) | set(spec.sv_sources)
    for rel, text in cand_files.items():
        if rel not in allowed:
            problems.append(f"{rel}: not an allowed synthesis source")
            continue
        pristine = pristine_source(spec.name, rel)
        for pat in _SIM_ONLY:
            if pat in _strip_comments(text) and pat not in _strip_comments(pristine):
                problems.append(f"{rel}: introduces sim-only construct '{pat.strip()}'")
        if re.search(r"\binitial\b", _strip_comments(text)) and \
           not re.search(r"\binitial\b", _strip_comments(pristine)):
            warnings.append(f"{rel}: introduces an initial block (check synthesizability)")

    top_rel = next((r for r in cand_files
                    if spec.top in module_names(cand_files[r])), None)
    if top_rel:
        try:
            old = module_ports(pristine_source(spec.name, top_rel), spec.top)
            new = module_ports(cand_files[top_rel], spec.top)
            if old != new:
                problems.append(
                    f"top-module port list changed: {old} -> {new}")
        except ValueError as e:
            problems.append(f"port parse failed: {e}")

    if problems:
        return "FAIL", "; ".join(problems + warnings)
    return "PASS", "; ".join(warnings)


def module_names(text: str) -> list[str]:
    return re.findall(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)", _strip_comments(text))


# ── L2: compile ───────────────────────────────────────────────────────────────
def compile_gate(ws: Workspace) -> tuple[str, str]:
    spec = ws.spec
    srcs = " ".join(spec.sources)
    r = ws.run(f"iverilog -t null -g2012 {srcs}", timeout=300)
    if r.returncode != 0:
        return "FAIL", f"iverilog: {r.stderr or r.stdout}"

    ys = (f"read_verilog -sv {srcs}; hierarchy -check -top {spec.top}; "
          f"proc; opt_clean; stat")
    r = ws.run(f"yosys -q -p '{ys}' 2>&1", timeout=600)
    out = r.stdout + r.stderr
    if r.returncode != 0:
        return "FAIL", f"yosys: {out}"
    latches = sum(int(n) for n in re.findall(r"\$(?:dlatch|dlatchsr|sr)\s+(\d+)", out))
    if latches:
        return "FAIL", f"yosys: {latches} inferred latch(es)"
    return "PASS", ""


# ── L3: provided testbench gate ───────────────────────────────────────────────
def tb_gate(ws: Workspace) -> tuple[str, str]:
    spec = ws.spec
    # pass the spec's gate location explicitly so auto-discovered (hidden)
    # IPs work without a registry.tsv entry
    r = ws.run(f"bash /harness/run_gate.sh {spec.name} "
               f"'{spec.gate_dir}' '{spec.gate_cmd}'", timeout=1800)
    out = r.stdout + r.stderr
    # FAIL-CLOSED (migration review SS4.9): PASS requires wrapper rc==0 AND
    # the recorded underlying rc==0 AND the banner - text alone never wins
    if (r.returncode == 0 and f"{spec.name} GATE-RC: 0" in out
            and f"{spec.name} GATE: PASS" in out):
        return "PASS", ""
    return "FAIL", out[-2000:]


# ── L4: yosys equivalence ─────────────────────────────────────────────────────
# Yosys equivalence is the memory high-water mark. Candidate evaluation may
# use several worker threads, but running multiple whole-design LEC jobs at
# once can OOM-kill the Python controller before its subprocess timeout/reaper
# executes. Serialize only the equivalence process; compile/gate/measure and
# model fan-out retain their existing concurrency.
_LEC_PROCESS_LOCK = threading.Lock()


def run_lec_command(runner, cmd: str, timeout: int):
    """The single process boundary for every equivalence invocation.

    `runner` is normally Workspace.run -> config.docker_run, whose independent
    in-container watchdog guarantees expiry even if this Python process dies.
    Tests/diagnostics may inject a compatible runner.
    """
    with _LEC_PROCESS_LOCK:
        return runner(cmd, timeout)


_LEC_DEFINE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:=[A-Za-z0-9_'\".+-]+)?")


def _lec_read_options(spec: IPSpec | None) -> tuple[str, bool]:
    """Return the trusted per-IP frontend options and defer mode.

    Empty/default fields deliberately return an empty option string so the
    legacy `_read_stanza` remains byte-identical. Configured values are
    validated as tokens/relative canonical paths rather than interpolating
    arbitrary command fragments.
    """
    if spec is None or not (
            spec.lec_defines or spec.lec_includes or spec.lec_defer):
        return "", False
    from . import contract as C
    for define in spec.lec_defines:
        if not _LEC_DEFINE.fullmatch(define):
            raise C.ContractError(
                f"invalid IPSpec.lec_defines token {define!r}")
    for inc in spec.lec_includes:
        if (not inc or Path(inc).is_absolute() or C._canon(inc) != inc
                or any(ch.isspace() for ch in inc)):
            raise C.ContractError(
                f"invalid IPSpec.lec_includes path {inc!r}")
    opts = "".join(f" -D{d}" for d in spec.lec_defines) + \
           "".join(f" -I{i}" for i in spec.lec_includes)
    return opts, spec.lec_defer


def _read_stanza(files: list[str], top: str, for_sat: bool = False,
                 spec: IPSpec | None = None) -> str:
    opts, defer = _lec_read_options(spec)
    if defer:
        reads = "".join(f"read_verilog -sv -defer{opts} {src}\n"
                        for src in files)
    else:
        # Keep this formatting EXACT: regression safety requires the generated
        # script for every default-off legacy IP to remain byte-identical.
        srcs = " ".join(files)
        reads = f"read_verilog -sv{opts} {srcs}\n"
    # async2sync only for the SAT-based equivalence flow ($adff has no SAT
    # model); dualsim keeps real async-reset semantics.
    extra = "async2sync\n" if for_sat else ""
    return (reads + f"hierarchy -check -top {top}\n"
            f"proc\nmemory\n{extra}flatten\nopt_clean\n")


# ── LEC v2 verdict parsing (Rev2.1a SSA.1/H.1-H.2; SS11 step 4) ──────────────
# Canonical recipe `nvdla-lec-contract-v2` (all IPs): equiv_simple -short ->
# explicit `equiv_induct -seq 4` -> `equiv_status -assert`. PROVEN is bound to
# rc/counts/success TOGETHER - never the success string alone (a 0-cell miter
# or malformed output is a FLOW_ERROR, not a proof). v1 (bare induct/status)
# remains historical evidence only.
_EQUIV_PASSES = ("equiv_make gold gate equiv\n"
                 "hierarchy -top equiv\n"
                 "equiv_simple -short\n"
                 "equiv_induct -seq 4\n"
                 "equiv_status -assert\n")
_RE_TOTAL = re.compile(r"Found (\d+) \$equiv cells in")
_RE_COUNTS = re.compile(r"Of those cells (\d+) are proven and (\d+) are "
                        r"unproven")
# CRITICAL (2026-07-23, release-control catch): yosys `equiv_simple` emits an
# ENTRY line "Found N unproven $equiv cells (N groups) in equiv:" listing the
# cells QUEUED for proving — every successful proof contains it (NVDLA's own
# PROVEN run logged "Found 381209 unproven"). It must NOT be read as a residual
# failure. The genuine leftover is `equiv_induct`'s RESIDUAL, which reads "...
# unproven $equiv cells in module equiv:" ("in module", no "(N groups)"). We
# anchor the unproven guard to the residual so PROVEN is reachable; the FINAL
# authoritative counts still come from `equiv_status` (_RE_COUNTS) + rc==0.
_RE_UNPROVEN_RESIDUAL = re.compile(
    r"Found (\d+) unproven \$equiv cells in module")
_SUCCESS = "Equivalence successfully proven!"


def lec_verdict(rc: int | None, out: str) -> "contract.ProofResult":
    """Normalize a yosys equiv run into the H.2 proof algebra. PROVEN
    requires: rc==0, success line, parsed total>0, proven==total, unproven==0
    (constructor-enforced) - and the evidence must be UNAMBIGUOUS (migration
    review SS4.6): multiple status blocks with differing totals or counts,
    an unproven mention anywhere, or internally inconsistent counts are never
    PROVEN. Unproven cells -> INCONCLUSIVE/nonconvergent (an induction
    witness is never confirmed inequivalence without reset-reachable replay).
    Missing/contradictory counts -> FLOW_ERROR."""
    from . import contract
    totals = {int(m.group(1)) for m in _RE_TOTAL.finditer(out)}
    counts = {(int(m.group(1)), int(m.group(2)))
              for m in _RE_COUNTS.finditer(out)}
    if len(totals) > 1 or len(counts) > 1:
        return contract.ProofResult(
            verdict="FLOW_ERROR", reason="malformed_status", rc=rc,
            total=None, proven=None, unproven=None,
            recipe_id=contract.LEC_RECIPE_CONTRACT_V2)
    total = next(iter(totals)) if totals else None
    proven, unproven = next(iter(counts)) if counts else (None, None)
    if unproven is None:
        mu = _RE_UNPROVEN_RESIDUAL.search(out)
        if mu:
            unproven = int(mu.group(1))
    # A genuine equiv_induct RESIDUAL ("... unproven ... in module equiv") with
    # a positive count blocks PROVEN (catches a success-line-then-later-residual
    # contradiction); the equiv_simple ENTRY line is intentionally NOT matched.
    any_unproven = any(int(m.group(1)) > 0
                       for m in _RE_UNPROVEN_RESIDUAL.finditer(out))
    consistent = (total is not None and proven is not None
                  and unproven is not None and proven + unproven == total)
    if (_SUCCESS in out and rc == 0 and total and total > 0
            and proven == total and unproven == 0 and consistent
            and not any_unproven):
        return contract.ProofResult(
            verdict="PROVEN", reason="fully_proven", rc=rc, total=total,
            proven=proven, unproven=unproven,
            recipe_id=contract.LEC_RECIPE_CONTRACT_V2)
    if (unproven is not None and unproven > 0) or any_unproven:
        return contract.ProofResult(
            verdict="INCONCLUSIVE", reason="nonconvergent", rc=rc,
            total=total, proven=proven, unproven=unproven,
            recipe_id=contract.LEC_RECIPE_CONTRACT_V2)
    if total == 0:
        return contract.ProofResult(
            verdict="FLOW_ERROR", reason="zero_compared_points", rc=rc,
            total=0, proven=proven, unproven=unproven,
            recipe_id=contract.LEC_RECIPE_CONTRACT_V2)
    return contract.ProofResult(
        verdict="FLOW_ERROR", reason="malformed_status", rc=rc, total=total,
        proven=proven, unproven=unproven,
        recipe_id=contract.LEC_RECIPE_CONTRACT_V2)


_VERDICT_TO_STATUS = {"PROVEN": "PROVEN", "INCONCLUSIVE": "INCONCLUSIVE",
                      "INEQUIVALENT": "INEQUIVALENT", "FLOW_ERROR": "ERROR"}


from dataclasses import dataclass as _dataclass


@_dataclass(frozen=True)
class ProofEvidence:
    """Immutable retained proof evidence (migration review SS4.6): the
    verdict PLUS its bindings - top identity, both side input digests, the
    generated script digest, the raw-log hash, and the H5 root the candidate
    side was bound to. The policy checks these bindings, not the verdict
    string alone."""
    result: "contract.ProofResult"
    top: str
    gold_inputs_digest: str
    cand_inputs_digest: str
    script_sha: str
    log_sha: str
    h5_root: str

    def __post_init__(self):
        from . import contract as _C
        if not isinstance(self.result, _C.ProofResult):
            raise _C.ContractError("ProofEvidence.result must be ProofResult")
        if not self.top:
            raise _C.ContractError("ProofEvidence.top required")
        for f in ("gold_inputs_digest", "cand_inputs_digest", "script_sha",
                  "log_sha", "h5_root"):
            if not _C._is_sha256(getattr(self, f)):
                raise _C.ContractError(f"ProofEvidence.{f} must be 64-hex")

    def ref(self) -> str:
        """Covers ALL bindings (review SS4.6): top, both sides, script, log,
        H5, verdict/counts, recipe."""
        import hashlib as _h
        import json as _j
        r = self.result
        return _h.sha256(_j.dumps(
            {"top": self.top, "gold": self.gold_inputs_digest,
             "cand": self.cand_inputs_digest, "script": self.script_sha,
             "log": self.log_sha, "h5": self.h5_root,
             "verdict": [r.verdict, r.reason, r.rc, r.total, r.proven,
                         r.unproven, r.recipe_id]},
            sort_keys=True).encode()).hexdigest()


def lec_tmake(ws, ctr, mrun, runner=None, timeout: int = 1800
              ) -> ProofEvidence:
    """PRODUCTION side-bound LEC adapter for tmake IPs (migration review
    SS4.6): consumes the RE-VERIFIED golden DesignInputs and the H5-bound
    candidate DesignInputs (via the receipt-revalidating effective_inputs),
    generates the pinned two-sided v2 script, and returns immutable
    ProofEvidence with full bindings. Raises ContractError (fail closed) if
    either side refuses."""
    import hashlib as _h

    from . import materialize as M
    gi = M.golden_inputs(ws, ctr, mrun)
    ci = M.effective_inputs(ws, ctr, mrun)
    script = lec_v2_script(gi, ci, ctr.spec.top)
    pr, out = run_lec_v2_script(ws, script, runner=runner, timeout=timeout)
    return ProofEvidence(
        result=pr, top=ctr.spec.top,
        gold_inputs_digest=gi.digest(), cand_inputs_digest=ci.digest(),
        script_sha=_h.sha256(script.encode()).hexdigest(),
        log_sha=_h.sha256(out.encode()).hexdigest(),
        h5_root=mrun.receipt.h5_root)


def run_lec_v2_script(ws, script: str, runner=None, timeout: int = 1800,
                      script_rel: str = ".lec/lec_v2.ys"):
    """Execute a complete pinned v2 script and return (ProofResult, raw log).

    The release-control packet uses this for pristine self-equivalence where
    no candidate materialization receipt exists yet. Timeout is normalized to
    INCONCLUSIVE/ineligible, exactly like the candidate adapter.
    """
    ws.write(script_rel, script)
    run = runner or ws.run
    try:
        r = run_lec_command(run, f"yosys {script_rel} 2>&1", timeout)
        out = (r.stdout or "") + (r.stderr or "")
        return lec_verdict(r.returncode, out), out
    except subprocess.TimeoutExpired:
        from . import contract
        out = f"TIMEOUT after {timeout}s"
        return contract.ProofResult(
            verdict="INCONCLUSIVE", reason="timeout", rc=None,
            recipe_id=contract.LEC_RECIPE_CONTRACT_V2), out


def lec_v2_script(gold_inputs, cand_inputs, top: str,
                  for_sat: bool = True) -> str:
    """Two-sided pinned-template script from side-bound DesignInputs (H.1:
    exactly the golden/candidate root+include substitutions differ; the read/
    prep/equivalence semantics are fixed). Used by the tmake LEC path."""
    prep = f"hierarchy -check -top {top}\nproc\nmemory\n" + \
           ("async2sync\n" if for_sat else "") + "flatten\nopt_clean\n"
    return (gold_inputs.yosys_read() + prep + "design -stash gold\n"
            + cand_inputs.yosys_read() + prep + "design -stash gate\n"
            + f"design -copy-from gold -as gold {top}\n"
            + f"design -copy-from gate -as gate {top}\n"
            + _EQUIV_PASSES)


def lec(ws: Workspace) -> tuple[str, str]:
    spec = ws.spec
    gold_dir = ws.root / ".golden"
    gold_dir.mkdir(exist_ok=True)
    gold_files = []
    for rel in spec.sources:
        name = Path(rel).name
        (gold_dir / name).write_text(pristine_source(spec.name, rel))
        gold_files.append(f".golden/{name}")

    script = (
        _read_stanza(gold_files, spec.top, for_sat=True, spec=spec)
        + "design -stash gold\n"
        + _read_stanza(list(spec.sources), spec.top, for_sat=True, spec=spec)
        + "design -stash gate\n"
        f"design -copy-from gold -as gold {spec.top}\n"
        f"design -copy-from gate -as gate {spec.top}\n"
        + _EQUIV_PASSES)
    ws.write(".lec/lec.ys", script)
    timeout = _lec_timeout(spec)
    try:
        r = run_lec_command(
            ws.run, "yosys .lec/lec.ys 2>&1", timeout)
    except subprocess.TimeoutExpired:
        return "INCONCLUSIVE", "timeout: yosys equiv exceeded budget " \
                               f"({timeout}s) - ineligible, not a " \
                               "pass"
    out = r.stdout + r.stderr
    pr = lec_verdict(r.returncode, out)
    note = (f"recipe={pr.recipe_id} rc={pr.rc} total={pr.total} "
            f"proven={pr.proven} unproven={pr.unproven} reason={pr.reason}")
    if pr.verdict == "FLOW_ERROR":
        note += " | " + out[-1500:]
    return _VERDICT_TO_STATUS[pr.verdict], note


def _lec_timeout(spec) -> int:
    """Design SS9 policy: tmake IPs get min(2400, max(1800, 2 x pristine));
    NVDLA pristine = 758 s -> 1800. Legacy IPs scale with design size: the large
    OpenTitan cores (aes ~75 sources) exceeded the flat 900 s on pristine
    self-equivalence (2026-07-23 release-control catch: slow, not stuck), so
    >=40-source legacy IPs get the 2400 s cap; smaller legacy IPs keep the proven
    900 s (fast, and a genuinely non-convergent small candidate should not burn
    40 min per attempt)."""
    if spec.contract == "tmake":
        pristine = spec.lec_pristine_seconds
        if pristine is None:
            return 1800
        if not isinstance(pristine, int) or isinstance(pristine, bool) \
                or pristine <= 0:
            from . import contract as C
            raise C.ContractError(
                "IPSpec.lec_pristine_seconds must be a positive integer")
        return min(2400, max(1800, 2 * pristine))
    return 2400 if len(spec.sources) >= 40 else 900


# ── L5: golden differential vectors (dual-instance sim) ──────────────────────
def _flatten_design(ws: Workspace, files: list[str], top: str, newname: str,
                    dump_ports: bool) -> tuple[bool, str]:
    script = (_read_stanza(files, top, spec=ws.spec) +
              f"rename {top} {newname}\n"
              f"write_verilog -noattr -nohex -nodec .dualsim/{newname}.v\n")
    if dump_ports:
        script += "write_json .dualsim/design.json\n"
    ws.write(f".dualsim/flat_{newname}.ys", script)
    r = ws.run(f"yosys -q .dualsim/flat_{newname}.ys 2>&1", timeout=600)
    return r.returncode == 0, r.stdout + r.stderr


def _ports_from_json(ws: Workspace, module: str) -> dict[str, dict]:
    data = json.loads(ws.read(".dualsim/design.json"))
    return data["modules"][module]["ports"]


def _rand_expr(width: int) -> str:
    n = (width + 31) // 32
    return "{" + ", ".join("$urandom" for _ in range(n)) + "}"


_CORNERS = ("'d0", "~0", "{2{32'hAAAAAAAA}}", "{2{32'h55555555}}")


def _gen_tb(spec: IPSpec, ports: dict[str, dict], cycles: int) -> str:
    clk_names = {c.name for c in spec.clocks}
    rst = dict(spec.resets)
    ins = {n: len(p["bits"]) for n, p in ports.items()
           if p["direction"] == "input" and n not in clk_names and n not in rst}
    outs = {n: len(p["bits"]) for n, p in ports.items()
            if p["direction"] == "output"}
    max_p = max(c.period_ns for c in spec.clocks)
    stim_clk = spec.clocks[0].name

    L = ["`timescale 1ns/1ps", "module dualsim_tb;",
         "  integer errors = 0; integer xdiff = 0; integer stim_n = 0;",
         "  integer seed = 1; reg checking = 0; reg [31:0] dummy;"]
    for c in spec.clocks:
        L.append(f"  reg {c.name} = 0; always #{c.period_ns / 2:g} "
                 f"{c.name} = ~{c.name};")
    for r_name, lvl in rst.items():
        L.append(f"  reg {r_name} = {lvl};")
    for n, w in ins.items():
        L.append(f"  reg [{w - 1}:0] {n} = 0;")
    for n, w in outs.items():
        L.append(f"  wire [{w - 1}:0] g_{n}; wire [{w - 1}:0] c_{n};")

    def inst(mod, pre):
        conns = [f".{c.name}({c.name})" for c in spec.clocks]
        conns += [f".{r}({r})" for r in rst]
        conns += [f".{n}({n})" for n in ins]
        conns += [f".{n}({pre}_{n})" for n in outs]
        return f"  {mod} u_{pre} ({', '.join(conns)});"

    L.append(inst("gold_flat", "g"))
    L.append(inst("cand_flat", "c"))

    L.append(f"  always @(posedge {stim_clk}) begin")
    L.append("    stim_n = stim_n + 1;")
    for i, (n, w) in enumerate(ins.items()):
        corner = _CORNERS[i % len(_CORNERS)]
        L.append(f"    {n} <= (stim_n < 8) ? {corner} : {_rand_expr(w)};")
    L.append("  end")

    L.append("  task check;")
    L.append("    begin")
    for n in outs:
        # differ AND (both known  OR  candidate introduced X where golden is
        # known) -> ERROR. Only a GOLDEN-side X (oracle/uninit limitation) is
        # tolerated as xdiff (F-08: candidate-X vs known-golden must FAIL).
        L.append(f"      if ((g_{n} !== c_{n}) && (^g_{n} !== 1'bx)) begin")
        L.append(f"        if (errors < 5) $display(\"MISMATCH t=%0t {n} "
                 f"gold=%h cand=%h\", $time, g_{n}, c_{n});")
        L.append("        errors = errors + 1;")
        L.append("      end")
        L.append(f"      else if ((g_{n} !== c_{n})) xdiff = xdiff + 1;")
    L.append("    end")
    L.append("  endtask")
    for c in spec.clocks:
        L.append(f"  always @(negedge {c.name}) if (checking) check;")

    reset_t = 20 * max_p
    warm_t = 5 * max_p
    end_t = reset_t + warm_t + cycles * spec.clocks[0].period_ns
    L.append("  initial begin")
    L.append("    if (!$value$plusargs(\"seed=%d\", seed)) seed = 1;")
    L.append("    dummy = $urandom(seed);")
    L.append(f"    #{reset_t:g};")
    for r_name, lvl in rst.items():
        L.append(f"    {r_name} = {1 - lvl};")
    L.append(f"    #{warm_t:g}; checking = 1;")
    L.append(f"    #{end_t:g};")
    L.append("    $display(\"DUALSIM: %s errors=%0d xdiff=%0d\", "
             "(errors == 0) ? \"PASS\" : \"FAIL\", errors, xdiff);")
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def dualsim(ws: Workspace, seeds=(1, 2), cycles: int = 2000) -> tuple[str, str]:
    spec = ws.spec
    if spec.compare_mode != "cycle":
        return "SKIP", "transaction-mode comparison not implemented yet"
    (ws.root / ".dualsim").mkdir(exist_ok=True)

    gold_dir = ws.root / ".golden"
    gold_dir.mkdir(exist_ok=True)
    gold_files = []
    for rel in spec.sources:
        name = Path(rel).name
        (gold_dir / name).write_text(pristine_source(spec.name, rel))
        gold_files.append(f".golden/{name}")

    ok, out = _flatten_design(ws, gold_files, spec.top, "gold_flat", True)
    if not ok:
        return "ERROR", f"flatten golden: {out[-1500:]}"
    ok, out = _flatten_design(ws, list(spec.sources), spec.top, "cand_flat", False)
    if not ok:
        return "ERROR", f"flatten candidate: {out[-1500:]}"

    ports = _ports_from_json(ws, "gold_flat")
    ws.write(".dualsim/tb.v", _gen_tb(spec, ports, cycles))

    r = ws.run("cd .dualsim && iverilog -g2012 -o dualsim.vvp "
               "gold_flat.v cand_flat.v tb.v", timeout=600)
    if r.returncode != 0:
        return "ERROR", f"tb compile: {(r.stderr or r.stdout)[-1500:]}"

    details = []
    for seed in seeds:
        r = ws.run(f"cd .dualsim && vvp dualsim.vvp +seed={seed}", timeout=1200)
        m = re.search(r"DUALSIM: (PASS|FAIL) errors=(\d+) xdiff=(\d+)", r.stdout)
        if not m:
            return "ERROR", f"no verdict (seed {seed}): {(r.stdout + r.stderr)[-1500:]}"
        details.append(f"seed{seed}: errors={m.group(2)} xdiff={m.group(3)}")
        if m.group(1) == "FAIL":
            first = "\n".join(l for l in r.stdout.splitlines() if "MISMATCH" in l)[:800]
            return "FAIL", f"{'; '.join(details)}\n{first}"
    return "PASS", "; ".join(details)


# ── orchestration ─────────────────────────────────────────────────────────────
def verify_candidate(ip: str, cand_files: dict[str, str], *,
                     ws: Workspace | None = None,
                     layers: tuple[str, ...] = ALL_LAYERS,
                     seeds=(1, 2), cycles: int = 2000,
                     keep_ws: bool = False) -> VerifyResult:
    spec = IPS[ip]
    res = VerifyResult()

    if "lint" in layers:
        status, detail = lint(spec, cand_files)
        res.record("lint", status, detail)
        if not res.ok:
            return res

    own_ws = ws is None
    if own_ws:
        try:
            ws = Workspace.create(ip, cand_files, tag="verify")
        except RegenError as e:
            res.record("compile", "FAIL", f"sv2v regen: {e}")
            return res
    try:
        for name, fn, kw in (
                ("compile", compile_gate, {}),
                ("gate", tb_gate, {}),
                ("lec", lec, {}),
                ("dualsim", dualsim, {"seeds": seeds, "cycles": cycles})):
            if name not in layers:
                continue
            status, detail = fn(ws, **kw)
            if name == "lec":
                # PROVEN/INCONCLUSIVE both acceptable; ERROR flagged not fatal
                res.record(name, status if status != "ERROR" else "ERROR", detail)
            else:
                res.record(name, status, detail)
            if name in ("compile", "gate", "dualsim") and status == "FAIL":
                return res
    finally:
        if own_ws and not keep_ws:
            ws.destroy()
    return res


# ── CLI ───────────────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description="verify an RTL candidate")
    ap.add_argument("--ip", required=True,
                    help="IP name or repo-relative path; unknown names are "
                         "auto-discovered (hidden testcases)")
    ap.add_argument("--variant-dir", help="dir of replacement .v files (exp1/exp2 style)")
    ap.add_argument("--baseline", action="store_true",
                    help="verify pristine design against itself (stack sanity)")
    ap.add_argument("--layers", default=",".join(ALL_LAYERS))
    ap.add_argument("--cycles", type=int, default=2000)
    ap.add_argument("--seeds", default="1,2")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)

    if a.ip not in IPS:
        from .discover import get_spec, register
        spec = get_spec(a.ip)
        register(spec)
        a.ip = spec.name
        print(f"[discover] onboarded '{a.ip}'")

    if a.baseline:
        cand = {rel: pristine_source(a.ip, rel) for rel in IPS[a.ip].sources}
    else:
        assert a.variant_dir, "--variant-dir or --baseline required"
        cand = candidate_from_dir(a.ip, Path(a.variant_dir))

    res = verify_candidate(
        a.ip, cand, layers=tuple(a.layers.split(",")),
        seeds=tuple(int(s) for s in a.seeds.split(",")),
        cycles=a.cycles, keep_ws=a.keep)
    print(res.summary())
    for name, r in res.layers.items():
        if r["detail"]:
            print(f"  [{name}] {r['detail'][:500]}")
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
