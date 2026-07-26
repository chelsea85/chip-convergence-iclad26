"""NXP Phase-0 correctness firewall — deterministic validators (no LLM).

  port_contract   compile-fail=0 insurance: token-level diff of the generated
                  top's ports vs the skeleton TB's DUT instantiation (names,
                  directions, widths). SLDB showed frontier models alter ports
                  they were told not to touch; this gate is non-bypassable.
  yaml_validator  typed, consolidated errors for inferred specs BEFORE any
                  generation (AutoHarness 'is_legal'); logs validator gaps for
                  two-sided credit assignment.
  reset_lint      the #1 hidden-TB killer (SpecAssess + SLDB): por_n must feed
                  ONLY the reset synchronizer; every IP's presetn must come
                  from the synchronized net.
  structural_diff TB-independent stitch-error catcher (spec 1.4, regex form):
                  instance census, top-port connectivity, IRQ reachability
                  into the aggregator, APB slaves hang off the fabric,
                  bridge master bus reaches the fabric. Checks activate only
                  for module roles actually present in gen_modules, so it is
                  hidden-testcase-safe.

All return (ok, [typed error strings]); errors are consolidated for cheap,
informative repair prompts.
"""
from __future__ import annotations

import re
from pathlib import Path

SUPPORTED_IP_TYPES = {
    "sync_fifo", "async_fifo", "sram_sp", "sram_dp", "reset_sync", "cdc_sync",
    "apb_uart", "apb_gpio", "apb_timer", "apb_watchdog", "irq_aggregator",
    "ahb_to_apb_bridge", "apb_fabric", "axi_lite_crossbar", "axi_lite_sram",
    "dma_engine", "perf_counter", "tilelink_router", "tilelink_ni", "aes128"}


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


# ── port contract ─────────────────────────────────────────────────────────────
_HDL_KEYWORDS = {
    "module", "endmodule", "input", "output", "inout", "reg", "wire", "logic",
    "integer", "parameter", "localparam", "initial", "always", "assign",
    "begin", "end", "if", "else", "case", "endcase", "for", "while", "repeat",
    "task", "function", "generate", "endgenerate", "posedge", "negedge",
    "defparam", "genvar", "real", "time", "event", "specify", "endspecify",
}


def skeleton_top_name(skel_text: str) -> str | None:
    """The DUT module name the skeleton TB instantiates.

    The agent must NOT assume a fixed top: `easy` instantiates
    `secure_periph_soc`, `medium` -> `noc_aes_soc`, `hard` -> `crypto_soc`, and
    an unseen organizer testcase may use anything. Hardcoding the easy name
    made the generated top unusable on every other problem — 22 correct IPs
    would still fail elaboration with "Unknown module type" (2026-07-25).

    A DUT instantiation is `<module> <instance> ( .port(sig), ... );` — the
    NAMED port connection is what distinguishes it from a declaration, so we
    key off that and reject HDL keywords. Returns None when nothing matches,
    and callers must then fail closed rather than guess.
    """
    t = _strip_comments(skel_text)
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\(\s*\.", t):
        mod = m.group(1)
        if mod.lower() in _HDL_KEYWORDS:
            continue
        return mod
    return None


def skeleton_contract(skel_text: str, top: str = "secure_periph_soc") -> dict:
    """Expected ports from the skeleton TB: {name: (dir, width)} where dir is
    from the DUT's perspective (TB reg -> input, TB wire -> output)."""
    t = _strip_comments(skel_text)
    decls = {}
    # the skeleton mixes styles: TB-side `reg`(->DUT input)/`wire`(->output)
    # decls AND explicit `input/output wire` decls written from the DUT's
    # perspective (e.g. the UART pins) — the explicit ones are authoritative
    for m in re.finditer(
            r"\b(?:(input|output)\s+)?(reg|wire)\s*"
            r"(?:\[(\d+)\s*:\s*(\d+)\])?\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)",
            t):
        explicit, kind, hi, lo = m.group(1), m.group(2), m.group(3), m.group(4)
        width = (abs(int(hi) - int(lo)) + 1) if hi is not None else 1
        dut_dir = explicit if explicit else ("input" if kind == "reg" else "output")
        for name in re.split(r"\s*,\s*", m.group(5)):
            decls[name] = (dut_dir, width)

    im = re.search(rf"\b{top}\s+\w+\s*\((.*?)\)\s*;", t, re.S)
    if not im:
        raise ValueError(f"no {top} instantiation found in skeleton")
    contract = {}
    for pm in re.finditer(r"\.(\w+)\s*\(\s*(\w*)\s*\)", im.group(1)):
        port, sig = pm.group(1), pm.group(2)
        contract[port] = decls.get(sig, ("output", 1))
    return contract


def top_ports(top_text: str, top: str = "secure_periph_soc") -> dict:
    """{name: (dir, width)} from the candidate top's ANSI module header."""
    t = _strip_comments(top_text)
    m = re.search(rf"\bmodule\s+{top}\b(.*?);", t, re.S)
    if not m:
        raise ValueError(f"module {top} not found")
    header = m.group(1)
    # Skip an optional #(...) PARAMETER block before the port list. Without
    # this, `module dma0 #( parameter DATA_W = 32 )( input wire aclk, ... )`
    # parsed the PARAMETERS as the port list: no input/output keywords appear
    # there, so the module reported ZERO ports and every direction check
    # silently passed (2026-07-25 — this is why the constant-driven-output
    # gate saw nothing on the AXI DMA).
    j = 0
    while j < len(header) and header[j].isspace():
        j += 1
    if j < len(header) and header[j] == "#":
        k = header.find("(", j)
        if k >= 0:
            try:
                header = header[_scan_paren(header, k):]
            except (ValueError, IndexError):
                pass
    i = header.find("(")
    if i < 0:
        return {}
    ports, cur_dir, cur_width = {}, None, 1
    depth, chunk, chunks = 0, [], []
    for ch in header[i + 1:]:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        if ch == "," and depth == 0:
            chunks.append("".join(chunk))
            chunk = []
        else:
            chunk.append(ch)
    if chunk:
        chunks.append("".join(chunk))
    for c in chunks:
        dm = re.search(r"\b(input|output|inout)\b", c)
        if dm:
            cur_dir = dm.group(1)
            wm = re.search(r"\[(\d+)\s*:\s*(\d+)\]", c)
            cur_width = (abs(int(wm.group(1)) - int(wm.group(2))) + 1) if wm else 1
        ids = re.findall(r"[A-Za-z_]\w*", re.sub(
            r"\b(input|output|inout|wire|reg|logic|signed)\b|\[[^\]]*\]", " ", c))
        if ids and cur_dir:
            ports[ids[-1]] = (cur_dir, cur_width)
    return ports


def port_contract(top_text: str, skel_text: str,
                  top: str = "secure_periph_soc") -> tuple[bool, list[str]]:
    errors = []
    try:
        want = skeleton_contract(skel_text, top)
        got = top_ports(top_text, top)
    except ValueError as e:
        return False, [f"port-contract: {e}"]
    for name, (d, w) in want.items():
        if name not in got:
            errors.append(f"port-missing: {name} ({d} [{w-1}:0])")
        else:
            gd, gw = got[name]
            if gd != d:
                errors.append(f"port-direction: {name} is {gd}, must be {d}")
            if gw != w:
                errors.append(f"port-width: {name} is {gw} bits, must be {w}")
    for name in got:
        if name not in want:
            errors.append(f"port-extra: {name} not in skeleton contract")
    return not errors, errors


# ── YAML spec validator ───────────────────────────────────────────────────────
_INT_RULES = {   # param -> (min, max, power_of_two)
    "fifo_depth": (2, 1024, True),
    "depth": (2, 65536, True),
    "gpio_width": (1, 64, False),
    "width": (1, 128, False),
    "data_width": (8, 128, False),
    "addr_width": (4, 64, False),
    "num_channels": (1, 16, False),
    "num_slaves": (1, 16, False),
    "stages": (2, 8, False),
    "default_div": (1, 65535, False),
}


def parse_flat_yaml(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        line = line.split("#")[0].rstrip()
        m = re.match(r"^([A-Za-z_]\w*):\s*(.+)$", line)
        if m:
            v = m.group(2).strip().strip("'\"")
            out[m.group(1)] = int(v, 0) if re.match(r"^(0x[0-9a-fA-F]+|\d+)$", v) else v
    return out


def yaml_validator(yaml_texts: list[str]) -> tuple[bool, list[str]]:
    errors = []
    names, types = set(), []
    for i, text in enumerate(yaml_texts):
        spec = parse_flat_yaml(text)
        tag = spec.get("name") or f"spec#{i}"
        if "ip_type" not in spec:
            errors.append(f"{tag}: missing required key ip_type")
            continue
        if spec["ip_type"] not in SUPPORTED_IP_TYPES:
            errors.append(f"{tag}: ip_type '{spec['ip_type']}' not supported "
                          f"by rtl_gen_lib")
        if "name" not in spec:
            errors.append(f"spec#{i} ({spec.get('ip_type')}): missing name")
        elif spec["name"] in names:
            errors.append(f"{tag}: duplicate instance name")
        names.add(spec.get("name"))
        types.append(spec.get("ip_type"))
        for key, val in spec.items():
            if key in _INT_RULES:
                lo, hi, p2 = _INT_RULES[key]
                if not isinstance(val, int):
                    errors.append(f"{tag}: {key}='{val}' must be an integer")
                elif not (lo <= val <= hi):
                    errors.append(f"{tag}: {key}={val} outside [{lo},{hi}]")
                elif p2 and val & (val - 1):
                    errors.append(f"{tag}: {key}={val} must be a power of two")
    return not errors, errors


# ── reset lint (stitched top) ─────────────────────────────────────────────────
def reset_lint(top_text: str, strict_names: bool = True) -> tuple[bool, list[str]]:
    t = _strip_comments(top_text)
    errors = []
    # por_n may feed ONLY the reset synchronizer instance
    por_users = set()
    for m in re.finditer(r"(\w+)\s+(\w+)\s*\(([^;]*?\.\w+\s*\(\s*por_n\s*\)[^;]*?)\)\s*;",
                         t, re.S):
        por_users.add(m.group(1))
    for mod in por_users:
        if "reset" not in mod.lower() and "rst" not in mod.lower():
            errors.append(f"reset: por_n wired into '{mod}' — only the reset "
                          f"synchronizer may consume the raw POR")
    # every presetn/resetn pin must be driven by one common synchronized net
    nets = set(re.findall(r"\.p?resetn?\s*\(\s*(\w+)\s*\)", t))
    nets |= set(re.findall(r"\.rst_n\s*\(\s*(\w+)\s*\)", t))
    nets.discard("")
    if "por_n" in nets:
        errors.append("reset: an IP's reset pin is tied to raw por_n instead "
                      "of the synchronized reset")
    if len(nets - {"por_n"}) > 1:
        errors.append(f"reset: multiple different reset nets {sorted(nets)} — "
                      f"expected one synchronized net")
    # accept prefixed/suffixed synchronizer module names (models name their
    # instances e.g. u_reset_sync — the YAML `name` becomes the MODULE name).
    # NAME-PATTERN check only: the SUBSTANTIVE rules above (raw por_n may feed
    # only a synchronizer, no IP reset pin on raw por_n, one common reset net)
    # are protocol-independent and always enforced. The literal
    # `reset_sync|rst_sync` spelling is an EASY-tier convention — on `medium`
    # the model legitimately named its synchronizer `u_rst` and this fired as a
    # FALSE violation, burning all three re-prompts on a design that elaborated
    # correctly (2026-07-25). Outside easy, accept any reset-ish module name,
    # which is exactly the vocabulary the por_n rule above already trusts.
    pattern = r"reset_sync|rst_sync" if strict_names else r"(?i)reset|rst"
    if not re.search(pattern, t):
        errors.append("reset: no reset synchronizer instance found in top")
    return not errors, errors


# ── library-output fixups (known rtl_gen_lib bugs) ────────────────────────────
_LIB_FIXUPS = [
    # CONTEST LIBRARY BUG #3: gen_axi_ips.py dma_engine declares cfg_rdata as
    # `output wire` but drives it from an always@(*) block -> every generated
    # dma_engine fails iverilog elaboration. Declaration-only fix.
    (re.compile(r"output wire \[31:0\]\s+cfg_rdata"),
     "output reg  [31:0]     cfg_rdata", "dma_engine cfg_rdata wire->reg"),
]


def patch_library_rtl(text: str) -> tuple[str, list[str]]:
    """Apply known-bug declaration fixes to library-generated RTL.
    Behavior-neutral by construction; returns (patched_text, notes)."""
    notes = []
    for pat, repl, why in _LIB_FIXUPS:
        if pat.search(text):
            text = pat.sub(repl, text)
            notes.append(why)
    return text, notes


# ── structural diff (stitched top vs generated IPs) ───────────────────────────
def _scan_paren(t: str, i: int) -> int:
    """i points at '('; return the index just past its matching ')'."""
    depth = 0
    while i < len(t):
        if t[i] == "(":
            depth += 1
        elif t[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced parentheses")


def parse_instances(top_text: str, module_names) -> list:
    """[(module, inst_name, {port: conn_expr})] for every instantiation of the
    given modules (named port connections; expressions kept verbatim)."""
    t = _strip_comments(top_text)
    out = []
    for mod in module_names:
        for m in re.finditer(rf"\b{re.escape(mod)}\b", t):
            i = m.end()
            pj = re.match(r"\s*#\s*\(", t[i:])          # optional #(params)
            if pj:
                i = _scan_paren(t, i + pj.end() - 1)
            im = re.match(r"\s*([A-Za-z_]\w*)\s*\(", t[i:])
            if not im or im.group(1) in ("if", "for", "case", "while"):
                continue                                 # not an instantiation
            popen = i + im.end() - 1
            body = t[popen + 1:_scan_paren(t, popen) - 1]
            conns = {}
            for pm in re.finditer(r"\.([A-Za-z_]\w*)\s*\(", body):
                e = _scan_paren(body, pm.end() - 1)
                conns[pm.group(1)] = body[pm.end():e - 1].strip()
            if conns:
                out.append((mod, im.group(1), conns))
    return out


def _assign_map(t: str) -> dict:
    """lhs -> rhs for `assign x = e;` and `wire [..] x = e;` (one level)."""
    amap = {}
    for m in re.finditer(r"\bassign\s+(\w+)(?:\s*\[[^\]]*\])?\s*=\s*([^;]+);", t):
        amap[m.group(1)] = m.group(2)
    for m in re.finditer(r"\bwire\s*(?:\[[^\]]*\]\s*)?(\w+)\s*=\s*([^;]+);", t):
        amap[m.group(1)] = m.group(2)
    return amap


_IDS = lambda expr: re.findall(r"[A-Za-z_]\w*", expr)


_LITERAL = re.compile(
    r"""^(?:
          \d*\s*'\s*[sS]?[bBoOdDhH]?[0-9a-fA-FxXzZ_?]+   # 1'b1, 4'hF, 2'd0
        | \d+                                            # bare 0, 1, 42
        )$""", re.X)


def _is_literal(expr: str) -> bool:
    """True only for an UNAMBIGUOUS constant. Deliberately conservative: a
    concatenation, slice, identifier or anything with a name in it is left
    alone, because a false accusation costs a re-prompt on correct RTL."""
    e = expr.strip()
    if not e:
        return False                     # `.port()` = intentionally unconnected
    return bool(_LITERAL.match(e))


def instance_port_directions(top_text: str, gen_files
                             ) -> tuple[bool, list[str]]:
    """An instance's OUTPUT/INOUT port may not be driven by a constant.

    Why this gate exists (2026-07-25). The stitcher tied literals to output
    ports — `.p0_d_size(3'd3)` on a TileLink router, `.m_rready(1'b1)` on an
    AXI DMA master. Verilog rejects both ("Output port expression must support
    a continuous assignment") so elaboration dies and the design scores zero.

    The port DIRECTIONS were already in the prompt (`output wire [1:0]
    p0_d_param`) and a prompt rule forbidding it was added — the model still
    complied on one problem and violated on another. That is the project's
    recurring lesson: a model instruction is probabilistic, a deterministic
    gate is not. This converts a hard compile failure into a typed error the
    existing re-prompt loop can repair, naming the exact instance and port.

    Tying an output high is often what the designer MEANT (an always-ready
    AXI master); the legal spelling is a wire, or `.port()` to leave it
    unconnected — both are suggested in the error text.
    """
    errors = []
    directions = {}
    for f in gen_files:
        try:
            text = Path(f).read_text()
        except OSError:
            continue
        m = re.search(r"\bmodule\s+(\w+)", _strip_comments(text))
        if not m:
            continue
        try:
            directions[m.group(1)] = top_ports(text, m.group(1))
        except ValueError:
            continue                     # unparseable header -> no opinion
    if not directions:
        return True, []
    for mod, inst, conns in parse_instances(top_text, list(directions)):
        ports = directions.get(mod, {})
        for port, expr in conns.items():
            d = ports.get(port, (None, None))[0]
            if d in ("output", "inout") and _is_literal(expr):
                errors.append(
                    f"port-direction: {inst}.{port} is an {d} of {mod} but is "
                    f"driven by constant '{expr}' — illegal Verilog. Connect it "
                    f"to a declared wire, or leave it unconnected as .{port}()")
    return not errors, errors


def repair_constant_driven_outputs(top_text: str, gen_files
                                   ) -> tuple[str, list[str]]:
    """LAST-RESORT mechanical repair: `.out_port(1'b1)` -> `.out_port()`.

    Only reached when the model has failed to fix the violation across every
    re-prompt. Leaving an output unconnected is legal Verilog and lets the
    design ELABORATE; shipping the constant guarantees a compile failure and a
    zero. A partially-correct design that builds beats one that does not, which
    is the same reasoning as the existing "ship best-effort" path.

    Deliberately narrow: only connections this module already flagged, only
    literal constants, and every edit is RETURNED as a note so the repair is
    logged rather than silent. Never touches inputs.
    """
    ok, errs = instance_port_directions(top_text, gen_files)
    if ok:
        return top_text, []
    notes, out = [], top_text
    for e in errs:
        m = re.match(r"port-direction: (\w+)\.(\w+) is an (\w+) of", e)
        if not m:
            continue
        inst, port = m.group(1), m.group(2)
        # rewrite only inside THIS instance's connection list
        pat = re.compile(rf"(\b{re.escape(inst)}\b[^;]*?\.{re.escape(port)}\s*\()"
                         rf"\s*[^()]*?\s*(\))", re.S)
        new, n = pat.subn(r"\1\2", out, count=1)
        if n:
            out = new
            notes.append(f"repaired {inst}.{port}: constant -> unconnected")
    return out, notes


def structural_diff(top_text: str, gen_modules: list,
                    top: str = "secure_periph_soc") -> tuple[bool, list[str]]:
    t = _strip_comments(top_text)
    errors = []
    mods = [m for m in gen_modules if m != top]
    inst = parse_instances(top_text, mods)
    counts = {m: 0 for m in mods}
    for mod, _, _ in inst:
        counts[mod] += 1

    # 1. census — every generated IP instantiated exactly once
    for mod, n in counts.items():
        if n != 1:
            errors.append(f"struct-census: {mod} instantiated {n}x, want exactly 1")

    # 2. every skeleton-contract top port must reach an instance or assign
    try:
        ports = top_ports(top_text, top)
    except ValueError as e:
        return False, [f"struct: {e}"]
    amap = _assign_map(t)
    used = set(amap)
    for rhs in amap.values():
        used |= set(_IDS(rhs))
    for _, _, conns in inst:
        for expr in conns.values():
            used |= set(_IDS(expr))
    for p in ports:
        if p not in used:
            errors.append(f"struct-dangling: top port {p} is connected to nothing")

    def netof(conns, port):
        ids = _IDS(conns.get(port, ""))
        return ids[0] if len(ids) == 1 else conns.get(port, "").strip()

    # 3. IRQ reachability — every peripheral *irq* pin must land in the
    #    aggregator's irq_src expression (one assign level deep)
    agg = next((x for x in inst if "irq_aggregator" in x[0]), None)
    if agg:
        reach = set(_IDS(agg[2].get("irq_src", "")))
        for i in list(reach):
            if i in amap:
                reach |= set(_IDS(amap[i]))
        for mod, name, conns in inst:
            if mod == agg[0]:
                continue
            for port, expr in conns.items():
                if "irq" not in port.lower():
                    continue
                for src in _IDS(expr):
                    if src not in reach:
                        errors.append(f"struct-irq: {name}.{port} net '{src}' "
                                      f"never reaches {agg[0]}.irq_src")

    # 4. APB slaves hang off the fabric — each slave's psel must be one of the
    #    fabric's sN_psel nets, and no two slaves may share one
    fab = next((x for x in inst if "fabric" in x[0]), None)
    bridge = next((x for x in inst if "bridge" in x[0]), None)
    if fab:
        sel_nets = {netof(fab[2], p): p for p in fab[2]
                    if re.match(r"s\d+_psel$", p)}
        owner = {}
        for mod, name, conns in inst:
            if mod == fab[0] or (bridge and mod == bridge[0]) or "psel" not in conns:
                continue
            n = netof(conns, "psel")
            if n not in sel_nets:
                errors.append(f"struct-fabric: {name}.psel '{n}' is not a "
                              f"{fab[0]} slave select")
            elif n in owner:
                errors.append(f"struct-fabric: {owner[n]} and {name} share "
                              f"slave select '{n}'")
            owner[n] = name

    # 5. bridge master APB bus must reach the fabric's m_* ports net-for-net
    if fab and bridge:
        for sig in ("psel", "penable", "pwrite", "paddr", "pwdata",
                    "prdata", "pready", "pslverr"):
            bn, fn = netof(bridge[2], sig), netof(fab[2], "m_" + sig)
            if bn != fn:
                errors.append(f"struct-bridge: {bridge[1]}.{sig} '{bn}' != "
                              f"{fab[1]}.m_{sig} '{fn}' — master bus broken")
    return not errors, errors
