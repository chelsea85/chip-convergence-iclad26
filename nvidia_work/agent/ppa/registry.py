"""Production tmake registrations (SS11 migration step 1; re-review5 SS7.1).

The LITERAL NVDLA configuration: nothing is derived from subtrees[0]
conventions (re-review SS5.1). The H-1 validation digest is deliberately
UNBOUND - per the accepted checkpoint-1 guardrails (re-review5 SS8.2), the
production NVDLA contract stays PENDING, and campaign_refusal() refuses every
model call, until real host H-1 determinism evidence is configured here as a
frozen TmakeRegistration(bound_validation_digest=<full sha256>).

Registering NVDLA in config.IPS also keeps it out of the discovery path: an
explicit registry entry can never be silently onboarded as a generic
dual-representation IP (design rev2 SS10.4).
"""
from __future__ import annotations

from .config import IPS, ClockSpec, IPSpec
from .contract import (TMAKE_REGISTRY, TmakeLayout, TmakeRegistration,
                       register_tmake)
from .gate import TraceGatePlan

# Exact frontend environment from NVDLA/syn/yosys_syn/nvdla_yosys.f and the
# host-proven nvdla_lec_diag/nvdla_lec.ys. Keep the diagnostic's define order:
# the generated read recipe is compared modulo side-path prefixes in the
# NVDLA buildout regression.
NVDLA_LEC_DEFINES = (
    "NO_PLI_OR_EMU", "NO_PLI", "DESIGNWARE_NOEXIST", "SYNTHESIS",
)
NVDLA_LEC_INCLUDES = tuple(
    f"NVDLA/outdir/nv_small/vmod/{suffix}" for suffix in (
        "include", "vlibs",
        "nvdla/bdma", "nvdla/cacc", "nvdla/car", "nvdla/cbuf",
        "nvdla/cdma", "nvdla/cdp", "nvdla/cmac", "nvdla/csc",
        "nvdla/glb", "nvdla/nocif", "nvdla/pdp", "nvdla/retiming",
        "nvdla/rubik", "nvdla/sdp", "nvdla/top", "nvdla/csb_master",
        "nvdla/cfgrom", "nvdla/apb2csb", "rams/synth",
    )
) + ("NVDLA/syn/yosys_syn",)

# Facts: NVIDIA_NVDLA_PREFLIGHT_FINDINGS.md (top NV_nvdla, clocks dla_core_clk
# 30ns / dla_csb_clk 60ns, FLATTEN=0) + PHASE2_SOURCE_CONTRACT.md (vmod->
# outdir/tmake) + the checked-in filelist (323 sources / 22 -I / 4 -D).
NVDLA_SPEC = IPSpec(
    name="nvdla", top="NV_nvdla",
    rtl_dir="NVDLA/vmod/nvdla",
    sources=(),                       # tool inputs come from the filelist
    syn_dir="NVDLA/syn/yosys_syn",
    gate_dir="NVDLA",
    gate_cmd="./run_varilator_test.sh",
    subtrees=("NVDLA",),
    clocks=(ClockSpec("dla_core_clk", 30.0), ClockSpec("dla_csb_clk", 60.0)),
    resets=(("dla_reset_rstn", 0), ("direct_reset_", 0)),
    workspace_ok=True,
    contract="tmake",
    filelist="NVDLA/syn/yosys_syn/nvdla_yosys.f",
    lec_defines=NVDLA_LEC_DEFINES,
    lec_includes=NVDLA_LEC_INCLUDES,
    lec_defer=True,
    lec_pristine_seconds=758)

NVDLA_LAYOUT = TmakeLayout(
    root="NVDLA", config="nv_small",
    editable_root="NVDLA/vmod/nvdla",
    generated_root="NVDLA/outdir/nv_small/vmod",
    mapping_root="NVDLA/outdir/nv_small/vmod/nvdla",
    filelist="NVDLA/syn/yosys_syn/nvdla_yosys.f",
    filelist_base="NVDLA/syn/yosys_syn",
    generator_cwd="NVDLA",
    generator_cmd="./tools/bin/tmake -clean -build vmod")

NVDLA_TRACE_TARGET_ROOT = "NVDLA/vmod/nvdla/pdp"
NVDLA_DEFAULT_TARGET = \
    "NVDLA/vmod/nvdla/pdp/NV_NVDLA_PDP_nan.v"
NVDLA_DEFAULT_TRACE = "pdp_1x3x8_8x8_ave_int8_0"
NVDLA_TRACE_TIMEOUT_SEC = 4500
NVDLA_TRACE_PLAN = TraceGatePlan(
    clean_dirs=("NVDLA/outdir/nv_small/verilator",),
    regen_cmd="cd NVDLA && ./tools/bin/tmake -clean -build vmod",
    build_cmd="cd NVDLA && ./tools/bin/tmake -build verilator",
    exe_path="NVDLA/outdir/nv_small/verilator/VNV_nvdla",
    test_cwd="NVDLA/verif/verilator",
    test_env=(
        ("PROJECT", "nv_small"),
        ("OUTDIR", "outdir"),
        ("TEST_PREFIXES", NVDLA_DEFAULT_TRACE),
        ("TEST_TIMEOUT_SEC", str(NVDLA_TRACE_TIMEOUT_SEC)),
    ),
    test_driver="run_all_trace_tests.sh",
    # The declared trace exercises PDP.  The controller must choose its exact
    # one-file campaign scope from this partition; a plan for another
    # partition requires a separately registered trace recipe.
    editable_roots=(NVDLA_TRACE_TARGET_ROOT,),
)


def ensure_registered() -> None:
    """Idempotent production registration, called from CLI entry points
    before IP resolution. Never overwrites an existing registration (the
    sealed registry rejects duplicates); never binds an H-1 digest. A prior
    entry is VERIFIED equal to the literal expectation, never assumed
    (migration review SS5.7)."""
    from .contract import ContractError
    if "nvdla" in TMAKE_REGISTRY:
        reg = TMAKE_REGISTRY["nvdla"]
        if reg.layout != NVDLA_LAYOUT or \
                reg.bound_validation_digest is not None:
            raise ContractError(
                "existing nvdla registration differs from the literal "
                "production registration - refusing to proceed")
    else:
        register_tmake("nvdla", TmakeRegistration(layout=NVDLA_LAYOUT))
    if "nvdla" in IPS:
        if IPS["nvdla"] != NVDLA_SPEC:
            raise ContractError("existing nvdla IPS entry differs from the "
                                "literal production spec")
    else:
        IPS["nvdla"] = NVDLA_SPEC

    # Consumer wiring is just as canonical as the source contract.  Partial
    # registration is refused by evaluate.evaluate_many(); verify a prior
    # process-local binding rather than overwriting it.
    from . import gate as G
    prior_plan = G.get_gate_plan("nvdla")
    if prior_plan is None:
        G.register_gate_plan("nvdla", NVDLA_TRACE_PLAN)
    elif prior_plan != NVDLA_TRACE_PLAN:
        raise ContractError(
            "existing nvdla gate plan differs from the canonical trace plan")

    from . import measure_tmake as MT
    prior_measure = MT.get_measure_provider("nvdla")
    if prior_measure is None:
        MT.register_measure_provider("nvdla", MT.make_measure_fn)
    elif prior_measure is not MT.make_measure_fn:
        raise ContractError(
            "existing nvdla measure provider differs from the canonical "
            "tmake provider")
