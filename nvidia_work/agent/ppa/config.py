"""Shared configuration for the PPA agent package (Chip Convergence).

Paths, per-IP specs (sources, top module, clocks/resets, gate command), and the
docker helper every module uses to reach the EDA tools in `iclad-dev:v1`.

Workspace model: a candidate is evaluated in its own scratch copy of the IP's
subtree, mounted at /workspace so all in-repo relative paths keep working; the
ASAP7 techlib (referenced by absolute /workspace/techlib/... paths) is
bind-mounted read-only on top. This makes parallel evaluation collision-free.
"""
from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

PKG = Path(__file__).resolve().parent            # .../nvidia_work/agent/ppa
AGENT = PKG.parent                               # .../nvidia_work/agent
NVWORK = AGENT.parent                            # .../nvidia_work
HARNESS = NVWORK / "harness"
REPO = (NVWORK.parent / "ICLAD-Hackathon-2026" /
        "problem-categories" / "ICLAD26-NVIDIA-Problems")
IMAGE = "iclad-dev:v1"
WORK = AGENT / "work"        # scratch workspaces, one dir per candidate
LEDGER_DIR = AGENT / "ledger"  # per-IP JSONL evaluation records

def require_repo() -> None:
    """Validate contest materials exist. Called at execution boundaries
    (workspace creation, docker runs) - NOT at import time, so config/contract
    modules stay importable for unit tooling without contest materials, and the
    check survives `python -O` (checkpoint-1b, review SS4.2)."""
    if not REPO.is_dir():
        raise RuntimeError(f"NVIDIA contest repo not found at {REPO}")


@dataclass(frozen=True)
class ClockSpec:
    name: str
    period_ns: float


@dataclass(frozen=True)
class IPSpec:
    name: str
    top: str                       # synthesis top module (env.sh DESIGN_NAME)
    rtl_dir: str                   # repo-relative dir the agent may edit
    sources: tuple[str, ...]       # repo-relative synthesis sources (env.sh VERILOG_FILES)
    syn_dir: str                   # dir containing run_syn.sh
    gate_dir: str                  # dir where the functional gate runs
    gate_cmd: str
    subtrees: tuple[str, ...]      # repo-relative dirs copied into a workspace
    skip_sv2v: int = 0
    clocks: tuple[ClockSpec, ...] = ()
    resets: tuple[tuple[str, int], ...] = ()   # (port, active_level)
    compare_mode: str = "cycle"    # cycle | transaction (latency-tolerant TB)
    workspace_ok: bool = True      # False -> serial in-repo eval (OpenTitan, later)
    # OpenTitan-style dual representation: the functional gate builds the .sv
    # sources (FuseSoC/Verilator) while synthesis reads pre-generated .v
    # (SKIP_SV2V=1). Candidates edit sv_sources; the workspace regenerates the
    # touched modules' generated/<module>.v via HOST sv2v (container binary is
    # x86-only). filelist supplies sv2v -I dirs + package files.
    sv_sources: tuple[str, ...] = ()   # repo-relative editable .sv files
    filelist: str = ""                 # repo-relative *_yosys.f for sv2v args
    clean_dirs: tuple[str, ...] = ()   # stale build dirs to purge in workspaces
    # source-contract family key resolved by contract.get_contract(); empty ->
    # classified from sv_sources (sv2v) / else direct. "tmake" is only ever set
    # explicitly (NVDLA) - never inferred. config never imports contract.
    contract: str = ""
    # Optional, per-IP LEC frontend recipe. Empty/default values preserve the
    # legacy single-command `_read_stanza` byte-for-byte. Large generated IPs
    # such as NVDLA opt into one deferred read per source plus their exact
    # define/include environment. These are trusted configuration facts, not
    # caller-provided command fragments.
    lec_defines: tuple[str, ...] = ()
    lec_includes: tuple[str, ...] = ()
    lec_defer: bool = False
    # Host-characterized pristine whole-design LEC wall time. A configured
    # tmake IP gets min(2400, max(1800, 2*pristine)) seconds; None leaves the
    # conservative existing tmake default (1800 s) unchanged.
    lec_pristine_seconds: int | None = None


IPS: dict[str, IPSpec] = {
    "async_fifo": IPSpec(
        name="async_fifo", top="async_fifo", rtl_dir="async_fifo/rtl",
        sources=tuple(f"async_fifo/rtl/{f}" for f in (
            "async_fifo.v", "fifomem.v", "rptr_empty.v",
            "sync_r2w.v", "sync_w2r.v", "wptr_full.v")),
        syn_dir="async_fifo/yosys_syn",
        gate_dir="async_fifo", gate_cmd="./run_iverilog_tb.sh all",
        subtrees=("async_fifo",),
        clocks=(ClockSpec("wclk", 10.0), ClockSpec("rclk", 14.0)),
        resets=(("wrst_n", 0), ("rrst_n", 0)),
    ),
    "sha512": IPSpec(
        name="sha512", top="sha512", rtl_dir="sha512/src/rtl",
        sources=tuple(f"sha512/src/rtl/{f}" for f in (
            "sha512.v", "sha512_core.v", "sha512_w_mem.v",
            "sha512_k_constants.v", "sha512_h_constants.v")),
        syn_dir="sha512/yosys_syn",
        gate_dir="sha512", gate_cmd="./run_iverilog_tb.sh all",
        subtrees=("sha512",),
        clocks=(ClockSpec("clk", 10.0),),
        resets=(("reset_n", 0),),
        # TB is wait_ready() handshake-based -> transaction-tolerant, but keep
        # cycle-exact as the default gate; pipelined variants opt in explicitly.
        compare_mode="cycle",
    ),
    "ascon": IPSpec(
        name="ascon", top="ascon",
        rtl_dir="opentitan/hw/ip/ascon/yosys_syn/generated",
        sources=tuple(sorted(
            f"opentitan/hw/ip/ascon/yosys_syn/generated/{p.name}"
            for p in (REPO / "opentitan/hw/ip/ascon/yosys_syn/generated"
                      ).glob("*.v"))),
        syn_dir="opentitan/hw/ip/ascon/yosys_syn",
        gate_dir="opentitan/hw/ip/ascon/pre_dv",
        gate_cmd="./run_verilator_tb.sh all",
        subtrees=("opentitan",),
        skip_sv2v=1,
        clocks=(ClockSpec("clk_i", 10.0),),
        resets=(("rst_ni", 0),),
        sv_sources=(
            "opentitan/hw/ip/ascon/rtl/ascon.sv",
            "opentitan/hw/ip/ascon/rtl/ascon_core.sv",
            "opentitan/hw/ip/ascon/rtl/ascon_reg_top.sv",
            "opentitan/hw/ip/prim/rtl/prim_ascon_duplex.sv",
            "opentitan/hw/ip/prim/rtl/prim_ascon_round.sv",
            "opentitan/hw/ip/prim/rtl/prim_ascon_sbox.sv",
        ),
        filelist="opentitan/hw/ip/ascon/yosys_syn/ascon_yosys.f",
        clean_dirs=("opentitan/hw/ip/ascon/pre_dv/obj_fusesoc",
                    "opentitan/hw/ip/ascon/BUILD"),
    ),
}


def docker_run(cmd: str, *, root: Path, timeout: int = 3600,
               ) -> subprocess.CompletedProcess:
    """Run `cmd` in the EDA container with `root` mounted as /workspace.

    techlib is bind-mounted read-only at /workspace/techlib (absolute-path
    references in env.sh/syn.tcl), harness scripts at /harness.
    """
    require_repo()   # execution boundary (P0-4: no import-time check)
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
            or timeout <= 0):
        raise ValueError(f"docker timeout must be positive, got {timeout!r}")
    # Two independent watchdogs are intentional:
    #
    # 1. An IN-CONTAINER GNU `timeout` owns the payload. It still expires if
    #    the Python controller/docker client is OOM-killed or otherwise dies.
    #    That closes the 2026-07-24 failure where attached LEC containers ran
    #    for ~5 h after the campaign process disappeared.
    # 2. The host subprocess timeout is a slightly-later backstop. On expiry
    #    it kills the named container explicitly.
    #
    # A marker converts the inner watchdog's rc into TimeoutExpired so every
    # caller retains the existing fail-closed timeout algebra.
    name = f"iclad_{uuid.uuid4().hex[:16]}"
    timeout_s = f"{timeout:g}s"
    watchdog = (
        'timeout_s="$1"; payload="$2"; '
        'timeout --signal=TERM --kill-after=30s "$timeout_s" '
        'bash -lc "$payload"; rc=$?; '
        'if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then '
        'printf "__ICLAD_CONTAINER_TIMEOUT__ %s\\n" "$timeout_s" >&2; '
        'fi; exit "$rc"'
    )
    args = [
        "docker", "run", "--rm", "--name", name,
        "-v", f"{root}:/workspace",
        "-v", f"{REPO / 'techlib'}:/workspace/techlib:ro",
        "-v", f"{HARNESS}:/harness:ro",
        "-w", "/workspace", IMAGE, "bash", "-lc", watchdog,
        "iclad-watchdog", timeout_s, cmd,
    ]

    def reap() -> None:
        # Best effort only: the container may already have exited/--rm'd.
        try:
            subprocess.run(["docker", "kill", name],
                           capture_output=True, timeout=30)
        except (subprocess.SubprocessError, OSError):
            pass

    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout + 45)
    except subprocess.TimeoutExpired as e:
        reap()
        raise subprocess.TimeoutExpired(
            cmd, timeout, output=e.output, stderr=e.stderr) from None
    if "__ICLAD_CONTAINER_TIMEOUT__" in (result.stderr or ""):
        reap()
        raise subprocess.TimeoutExpired(
            cmd, timeout, output=result.stdout, stderr=result.stderr)
    return result
