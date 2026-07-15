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
    if f"{ws.spec.name} GATE: PASS" in out:
        return "PASS", ""
    return "FAIL", out[-2000:]


# ── L4: yosys equivalence ─────────────────────────────────────────────────────
def _read_stanza(files: list[str], top: str, for_sat: bool = False) -> str:
    srcs = " ".join(files)
    # async2sync only for the SAT-based equivalence flow ($adff has no SAT
    # model); dualsim keeps real async-reset semantics.
    extra = "async2sync\n" if for_sat else ""
    return (f"read_verilog -sv {srcs}\n"
            f"hierarchy -check -top {top}\n"
            f"proc\nmemory\n{extra}flatten\nopt_clean\n")


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
        _read_stanza(gold_files, spec.top, for_sat=True) + "design -stash gold\n" +
        _read_stanza(list(spec.sources), spec.top, for_sat=True) + "design -stash gate\n" +
        f"design -copy-from gold -as gold {spec.top}\n"
        f"design -copy-from gate -as gate {spec.top}\n"
        "equiv_make gold gate equiv\n"
        "hierarchy -top equiv\n"
        "equiv_simple -short\n"
        "equiv_induct\n"
        "equiv_status\n")
    ws.write(".lec/lec.ys", script)
    try:
        r = ws.run("yosys .lec/lec.ys 2>&1", timeout=900)
    except subprocess.TimeoutExpired:
        return "INCONCLUSIVE", "yosys equiv timeout"
    out = r.stdout + r.stderr
    if "Equivalence successfully proven!" in out:
        return "PROVEN", ""
    m = re.search(r"Found (\d+) unproven \$equiv cells", out)
    if m:
        return "INCONCLUSIVE", f"{m.group(1)} unproven $equiv cells"
    return "ERROR", out[-2000:]


# ── L5: golden differential vectors (dual-instance sim) ──────────────────────
def _flatten_design(ws: Workspace, files: list[str], top: str, newname: str,
                    dump_ports: bool) -> tuple[bool, str]:
    script = (_read_stanza(files, top) +
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
