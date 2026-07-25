#!/usr/bin/env python3
"""P0-4 checkpoint-1b: REAL-material NVDLA characterization (no Docker).

Codex review SS3.1 required exact assertions against the actual contest tree:
323 ordered sources (266 generated nvdla + 55 generated vlibs + 2 non-outdir),
22 include roots, 4 defines, 4 `.vh` include-universe files, and 532 members
(528 .v + 4 .vh) in the complete generated manifest. The 532/528 counts are
tied to the current contest-material commit; the source/include assertions are
structural. Read-only: nothing under the contest tree is written (.golden is
never created here; only the candidate side is characterized).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ppa import contract as C                                    # noqa: E402
from ppa.config import REPO, IPSpec                              # noqa: E402

PASS = FAIL = 0


def check(name, ok):
    global PASS, FAIL
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    PASS, FAIL = PASS + int(bool(ok)), FAIL + int(not ok)


NVDLA_SPEC = IPSpec(
    name="nvdla", top="NV_nvdla", rtl_dir="NVDLA/vmod/nvdla",
    sources=(), syn_dir="NVDLA/syn/yosys_syn",
    gate_dir="NVDLA", gate_cmd="./verif/traceplayer/run_varilator_test.sh",
    subtrees=("NVDLA",), contract="tmake",
    filelist="NVDLA/syn/yosys_syn/nvdla_yosys.f")

# DECLARED literal layout (re-review SS5.1): the production registry entry
# declares these values explicitly - nothing is derived from subtrees[0].
NVDLA_LAYOUT = C.TmakeLayout(
    root="NVDLA", config="nv_small",
    editable_root="NVDLA/vmod/nvdla",
    generated_root="NVDLA/outdir/nv_small/vmod",
    mapping_root="NVDLA/outdir/nv_small/vmod/nvdla",
    filelist="NVDLA/syn/yosys_syn/nvdla_yosys.f",
    filelist_base="NVDLA/syn/yosys_syn",
    generator_cwd="NVDLA",
    generator_cmd="./tools/bin/tmake -clean -build vmod")


def main():
    if not (REPO / "NVDLA").is_dir():
        # distinct non-green outcome (re-review SS5.4): a missing prerequisite
        # must never read as satisfied checkpoint evidence
        print("PREREQ-MISSING: contest NVDLA tree not present at", REPO)
        return 3
    C._reset_tmake_registry()
    C.register_tmake("nvdla", C.TmakeRegistration(layout=NVDLA_LAYOUT))
    ctr = C.get_contract(NVDLA_SPEC)   # the production path: sealed registry

    model = ctr.filelist_model(REPO)
    nvdla = [s for s in model.sources
             if s.startswith("NVDLA/outdir/nv_small/vmod/nvdla/")]
    vlibs = [s for s in model.sources
             if s.startswith("NVDLA/outdir/nv_small/vmod/vlibs/")]
    nonout = [s for s in model.sources if "outdir" not in s]
    check("323 ordered sources", len(model.sources) == 323)
    check("266 generated nvdla sources", len(nvdla) == 266)
    check("55 generated vlibs sources", len(vlibs) == 55)
    check("2 non-outdir sources (NV_DW_lsd.v + nvdla_ram_blackbox.v)",
          sorted(nonout) == ["NVDLA/syn/yosys_syn/nvdla_ram_blackbox.v",
                             "NVDLA/vmod/vlibs/NV_DW_lsd.v"])
    check("22 include roots", len(model.include_roots) == 22)
    check("`-I.` resolved to the syn dir",
          "NVDLA/syn/yosys_syn" in model.include_roots)
    check("4 defines",
          sorted(model.defines) == ["DESIGNWARE_NOEXIST", "NO_PLI",
                                    "NO_PLI_OR_EMU", "SYNTHESIS"])
    # independent order verification (re-review SS5.4): re-parse the raw
    # filelist here and require the model to match it entry-for-entry
    import os
    raw = (REPO / NVDLA_SPEC.filelist).read_text().splitlines()
    expect = [os.path.normpath(os.path.join("NVDLA/syn/yosys_syn", ln.strip()))
              for ln in raw
              if ln.strip() and not ln.strip().startswith(("#", "-"))]
    check("exact filelist order preserved (independently re-parsed)",
          list(model.sources) == expect)

    inc = ctr.include_universe(REPO, model)
    check("4 .vh include-universe files",
          len(inc) == 4
          and any(i.endswith("include/simulate_x_tick.vh") for i in inc)
          and any(i.endswith("include/NV_HWACC_NVDLA_tick_defines.vh")
                  for i in inc)
          and any(i.endswith("vlibs/assertion_header.vh") for i in inc)
          and any(i.endswith("vlibs/assertion_task.vh") for i in inc))

    rels = ctr.fingerprint_rels(REPO)
    v = [r for r in rels if r.endswith(".v")]
    vh = [r for r in rels if r.endswith(".vh")]
    check("complete generated manifest: 532 members on current contest commit",
          len(rels) == 532)
    check("528 generated .v + 4 generated .vh", len(v) == 528 and len(vh) == 4)
    check("manifest members all under the COMPLETE generated root",
          all(r.startswith("NVDLA/outdir/nv_small/vmod/") for r in rels))
    check("non-outdir tool sources NOT in the generated manifest",
          not any(r in rels for r in nonout))

    di = ctr.design_inputs(REPO, "candidate")
    check("candidate DesignInputs: 323 sources, 22 roots, 4 defines, 4 .vh, "
          "per-file -defer",
          len(di.ordered_sources) == 323 and len(di.include_roots) == 22
          and len(di.defines) == 4 and len(di.include_files) == 4
          and di.per_file_defer)
    check("DesignInputs digest deterministic",
          di.digest() == ctr.design_inputs(REPO, "candidate").digest())

    s = "NVDLA/vmod/nvdla/pdp/NV_NVDLA_PDP_core.v"
    g = "NVDLA/outdir/nv_small/vmod/nvdla/pdp/NV_NVDLA_PDP_core.v"
    check("mapping round trip on a real leaf",
          ctr.source_to_generated(s) == (g,)
          and ctr.generated_to_source(g) == s)
    check("generated vlibs does not reverse-map to editable",
          ctr.generated_to_source(
              "NVDLA/outdir/nv_small/vmod/vlibs/AN2D4PO4.v") is None)
    check("tmake requires scope + host validation PENDING",
          ctr.requires_scope() and ctr.validation_state() == "PENDING"
          and ctr.worker_cap() == 1)

    print(f"\ntest_contract_real: {PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
