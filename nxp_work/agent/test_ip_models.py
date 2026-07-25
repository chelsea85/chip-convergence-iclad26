#!/usr/bin/env python3
"""Per-IP differential validation of ip_models.py against the library RTL.

For each of the 12 ip_types: generate the RTL via rtl_gen_lib with a pinned
spec, auto-generate a lockstep TB from the model's PORTS declaration (LCG
random stimulus driven at negedge, all outputs dumped at posedge+1), drive
the Python model with the IDENTICAL stimulus stream, and diff per cycle.
Multi-clock IPs run all clocks from one base clock (logic equivalence, not
CDC timing). X-state is avoided by hierarchically zero-initializing
memories/unreset data regs at t=0 (models default to 0).

  python3 test_ip_models.py [--ncyc N] [--only ip_type]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import ip_models as IM

HERE = Path(__file__).resolve().parent
NXP = HERE.parent
REPO = (HERE.parents[1] / "ICLAD-Hackathon-2026" /
        "problem-categories" / "ICLAD26-NXP-Problems")
RTL_GEN = REPO / "rtl_gen_lib/rtl_gen_main.py"
WORK = NXP / "agent_out/tmp/ipmodels"

M32 = 0xFFFFFFFF
SEED = 0xC0FFEE11


def lcg(x): return (x * 1664525 + 1013904223) & M32


SPECS = {
    "sync_fifo":        "depth: 16\ndata_width: 32",
    "async_fifo":       "depth: 16\ndata_width: 32",
    "sram_sp":          "depth: 256\ndata_width: 32",
    "sram_dp":          "depth: 256\ndata_width: 32",
    "cdc_sync":         "data_width: 4\nstages: 2",
    "perf_counter":     "channels: 4\ncounter_width: 32",
    "axi_lite_sram":    "depth: 256\ndata_width: 32\naddr_width: 32",
    "dma_engine":       "",
    "axi_lite_crossbar": "",
    "tilelink_router":  "node_x: 1\nnode_y: 1\ndata_width: 32\naddr_width: 32",
    "tilelink_ni":      "",
    "aes128":           "",
}

MODEL_PARAMS = {
    "sync_fifo": dict(depth=16), "async_fifo": dict(depth=16),
    "sram_sp": dict(depth=256), "sram_dp": dict(depth=256),
    "cdc_sync": dict(data_width=4), "perf_counter": dict(channels=4),
    "axi_lite_sram": dict(depth=256),
}

# stimulus shaping: (ip, port) -> AND-mask, so addr-like inputs actually hit
# the interesting decode windows; identical on both sides
SHAPES = {
    ("perf_counter", "paddr"): 0xF,
    ("axi_lite_sram", "awaddr"): 0x3F, ("axi_lite_sram", "araddr"): 0x3F,
    ("dma_engine", "cfg_awaddr"): 0x1F, ("dma_engine", "cfg_araddr"): 0x1F,
    ("axi_lite_crossbar", "m0_awaddr"): 0x3FFFF,
    ("axi_lite_crossbar", "m0_araddr"): 0x3FFFF,
    ("axi_lite_crossbar", "m1_awaddr"): 0x3FFFF,
    ("axi_lite_crossbar", "m1_araddr"): 0x3FFFF,
}

# hierarchical t=0 zero-init for memories / unreset data regs (X avoidance)
MEMINIT = {
    "sync_fifo": ["for (mi=0; mi<16; mi=mi+1) dut.mem[mi]=0;", "dut.dout_r=0;"],
    "async_fifo": ["for (mi=0; mi<16; mi=mi+1) dut.mem[mi]=0;"],
    "sram_sp": ["for (mi=0; mi<256; mi=mi+1) dut.mem[mi]=0;", "dut.dout=0;"],
    "sram_dp": ["for (mi=0; mi<256; mi=mi+1) dut.mem[mi]=0;", "dut.rd_dout=0;"],
    "axi_lite_sram": ["for (mi=0; mi<256; mi=mi+1) dut.mem[mi]=0;"],
}


def gen_rtl(ip: str, work: Path) -> Path:
    spec = work / f"{ip}.yaml"
    spec.write_text(f"ip_type: {ip}\nname: m_{ip}\n{SPECS[ip]}\n")
    # use the agent's rtl_gen env (PyYAML shim when PyYAML is absent) so this
    # suite is valid under the forced-no-PyYAML acceptance path (Codex §6.1.9)
    import nxp_agent as _A
    r = subprocess.run([sys.executable, str(RTL_GEN), "--spec", str(spec),
                        "--outdir", str(work)], capture_output=True, text=True,
                       env=_A._rtl_gen_env())
    for ln in r.stdout.splitlines():
        if ln.startswith("[GEN]"):
            p = Path(ln.split("]")[1].strip().split()[0])
            import validators as V
            text, notes = V.patch_library_rtl(p.read_text())
            if notes:                  # known library bugs (dma cfg_rdata)
                p.write_text(text)
            return p
    raise RuntimeError(f"{ip}: generation failed: {r.stderr[-300:]}")


def module_name(rtl: Path) -> str:
    import re
    m = re.search(r"\bmodule\s+([A-Za-z_]\w*)", rtl.read_text())
    return m.group(1)


def gen_tb(ip: str, mod: str, cls, ncyc: int) -> str:
    ins = [(n, w) for n, w, d in cls.PORTS if d == "i"]
    outs = [(n, w) for n, w, d in cls.PORTS if d == "o"]
    decls = ["    reg clk, rst_n;"]
    decls += [f"    reg [{w-1}:0] {n};" for n, w in ins]
    decls += [f"    wire [{w-1}:0] {n};" for n, w in outs]
    conns = []
    for cname, rname in cls.CLKS:
        conns.append(f".{cname}(clk)")
        if rname:
            conns.append(f".{rname}(rst_n)")
    conns += [f".{n}({n})" for n, _ in ins + outs]
    drive = []
    for n, w in ins:
        words = (w + 31) // 32
        for k in range(words):
            sl = f"{n}[{min(w, (k+1)*32)-1}:{k*32}]" if words > 1 else n
            drive.append(f"            rnd = lcg(rnd); {sl} = rnd"
                         + (f" & 32'h{SHAPES[(ip, n)]:X}" if (ip, n) in SHAPES
                            and words == 1 else "") + ";")
    fmt = " ".join("%h" for _ in outs)
    args = ", ".join(n for n, _ in outs)
    init = "\n".join(f"        {s}" for s in MEMINIT.get(ip, []))
    return f"""`timescale 1ns/1ps
module tb_ip;
{chr(10).join(decls)}
    integer fd, c, mi;
    reg [31:0] rnd;
    {mod} dut ({', '.join(conns)});
    initial clk = 0;
    always #5 clk = ~clk;
    function [31:0] lcg(input [31:0] x);
        lcg = x * 32'd1664525 + 32'd1013904223;
    endfunction
    initial begin
{init}
        fd = $fopen("trace.txt", "w");
        rnd = 32'h{SEED:08X};
        rst_n = 0;
{chr(10).join(f'        {n} = 0;' for n, _ in ins)}
        repeat (3) @(negedge clk);
        rst_n = 1;
        for (c = 0; c < {ncyc}; c = c + 1) begin
            @(negedge clk);
{chr(10).join(drive)}
            @(posedge clk);
            #1 $fwrite(fd, "{fmt}\\n", {args});
        end
        $fclose(fd);
        $finish;
    end
endmodule
"""


def run_ip(ip: str, ncyc: int) -> tuple[bool, str]:
    cls = IM.MODELS[ip]
    work = WORK / ip
    work.mkdir(parents=True, exist_ok=True)
    rtl = gen_rtl(ip, work)
    mod = module_name(rtl)
    (work / "tb_ip.v").write_text(gen_tb(ip, mod, cls, ncyc))
    c = subprocess.run(["iverilog", "-g2005", "-o", "sim", str(rtl.name),
                        "tb_ip.v"], cwd=work, capture_output=True, text=True)
    if c.returncode != 0:
        return False, "compile: " + c.stderr[-300:]
    r = subprocess.run(["vvp", "sim"], cwd=work, capture_output=True,
                       text=True, timeout=600)
    if r.returncode != 0:
        return False, "sim: " + (r.stderr or r.stdout)[-300:]
    got = (work / "trace.txt").read_text().splitlines()

    # python lockstep with identical stimulus
    ins_p = [(n, w) for n, w, d in cls.PORTS if d == "i"]
    outs_p = [(n, w) for n, w, d in cls.PORTS if d == "o"]
    model = cls(**MODEL_PARAMS.get(ip, {}))
    rnd = SEED
    for cyc in range(ncyc):
        ins = {}
        for n, w in ins_p:
            v = 0
            for k in range((w + 31) // 32):
                rnd = lcg(rnd)
                word = rnd
                if (ip, n) in SHAPES and w <= 32:
                    word &= SHAPES[(ip, n)]
                v |= (word & M32) << (32 * k)
            ins[n] = v & IM._mask(w)
        model.step(ins)
        o = model.outputs(ins)
        exp = " ".join(f"{o[n] & IM._mask(w):0{(w + 3) // 4}x}"
                       for n, w in outs_p)
        if cyc >= len(got):
            return False, f"trace truncated at cycle {cyc}"
        if got[cyc] != exp:
            gt, et = got[cyc].split(), exp.split()
            diffs = [f"{n}: rtl={a} model={b}" for (n, _), a, b
                     in zip(outs_p, gt, et) if a != b]
            return False, f"cycle {cyc}: " + "; ".join(diffs[:4])
    return True, f"{ncyc} cycles lockstep"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ncyc", type=int, default=2000)
    ap.add_argument("--only")
    a = ap.parse_args()
    ips = [a.only] if a.only else list(IM.MODELS)
    fails = 0
    for ip in ips:
        try:
            ok, msg = run_ip(ip, a.ncyc)
        except Exception as e:
            ok, msg = False, f"harness error: {e}"
        print(f"[{'PASS' if ok else 'FAIL'}] {ip}: {msg}")
        fails += 0 if ok else 1
    print(f"ip_models differential: {len(ips)-fails}/{len(ips)} PASS")
    return fails


if __name__ == "__main__":
    sys.exit(main())
