#!/usr/bin/env python3
"""P0-4 checkpoint-1d sandbox tests (no Docker; fake tmake runs locally).

Fixture mirrors the REAL NVDLA topology (vmod/nvdla templates; non-generated
vlibs + syn-dir sources; filelist with defines/-I/`-I.`/traversal entries;
tmake regenerating the COMPLETE outdir/nv_small/vmod tree). Checkpoint-1c
adds one regression per adversarial finding in NVIDIA_P04_SLICE_CODE_REREVIEW
SS4 (internal-symlink redirection, scopeless/wrong-IP classification,
self-bound validation, premature proof eligibility, golden alias-following,
include ambiguity, malformed manifests).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ppa import contract as C                                    # noqa: E402
from ppa.config import IPS, IPSpec                               # noqa: E402

PASS = FAIL = 0


def check(name, ok):
    global PASS, FAIL
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    PASS, FAIL = PASS + int(bool(ok)), FAIL + int(not ok)


def raises(fn, name):
    try:
        fn()
        check(name, False)
    except C.ContractError:
        check(name, True)


_TMAKE = r"""#!/bin/bash
# fake tmake: only "-clean -build vmod" is supported. Deterministic.
cd "$(dirname "$0")/../.."
rm -rf outdir/nv_small/vmod
find vmod/nvdla -name '*.v' | sort | while read -r src; do
  rel=${src#vmod/nvdla/}
  out=outdir/nv_small/vmod/nvdla/$rel
  mkdir -p "$(dirname "$out")"
  { echo "// GENERATED from $rel"; grep -v '^//STRIP' "$src"; } > "$out"
done
mkdir -p outdir/nv_small/vmod/vlibs outdir/nv_small/vmod/include
echo "module gen_lib(); endmodule" > outdir/nv_small/vmod/vlibs/gen_lib.v
echo "// tick defines" > outdir/nv_small/vmod/include/defs.vh
echo "tmake: build vmod done"
"""

_FILELIST = """\
-DSYNTHESIS
-DNO_PLI
-I../../outdir/nv_small/vmod/include
-I../../outdir/nv_small/vmod/vlibs
-I../../outdir/nv_small/vmod/nvdla/pdp
-I.
../../outdir/nv_small/vmod/nvdla/pdp/core.v
../../outdir/nv_small/vmod/nvdla/pdp/unit.v
../../outdir/nv_small/vmod/nvdla/top/top.v
../../outdir/nv_small/vmod/vlibs/gen_lib.v
../../vmod/vlibs/NV_DW_lsd.v
./fake_ram_blackbox.v
"""


def make_tree(base: Path) -> Path:
    fk = base / "FAKE"
    for rel, text in {
        "vmod/nvdla/pdp/core.v": "module core(input a, output y);\n"
                                 "assign y = a;\nendmodule\n",
        "vmod/nvdla/pdp/unit.v": "module unit(input b, output z);\n"
                                 "assign z = b;\nendmodule\n",
        "vmod/nvdla/top/top.v": "module FAKE_top(input a, output y);\n"
                                "core c(.a(a), .y(y));\nendmodule\n",
        "vmod/nvdla/defs.h": "`define WIDTH 8\n",
        "vmod/vlibs/NV_DW_lsd.v": "module NV_DW_lsd(); endmodule\n",
        "vmod/rams/model/ram.v": "module ram(); endmodule\n",
        "spec/defs/project.h": "// fake spec\n",
        "tree.make": "# fake tree.make\n",
        "Makefile": "# fake Makefile\n",
        "syn/yosys_syn/fake_ram_blackbox.v": "module fake_ram(); endmodule\n",
        "syn/yosys_syn/fake_yosys.f": _FILELIST,
    }.items():
        p = fk / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    tm = fk / "tools/bin/tmake"
    tm.parent.mkdir(parents=True, exist_ok=True)
    tm.write_text(_TMAKE)
    tm.chmod(0o755)
    return fk


def spec_for(base: Path) -> IPSpec:
    return IPSpec(
        name="fakenv", top="FAKE_top", rtl_dir="FAKE/vmod/nvdla",
        sources=("FAKE/outdir/nv_small/vmod/nvdla/top/top.v",),
        syn_dir="FAKE/syn/yosys_syn", gate_dir="FAKE", gate_cmd="true",
        subtrees=("FAKE",), contract="tmake",
        filelist="FAKE/syn/yosys_syn/fake_yosys.f")


def runner_for(root: Path):
    return lambda cmd, timeout=600: subprocess.run(
        ["bash", "-lc", cmd], cwd=root, capture_output=True, text=True,
        timeout=timeout)


TARGET = "FAKE/vmod/nvdla/pdp/core.v"
GEN_TARGET = "FAKE/outdir/nv_small/vmod/nvdla/pdp/core.v"
NONOUT_VLIB = "FAKE/vmod/vlibs/NV_DW_lsd.v"
NONOUT_BB = "FAKE/syn/yosys_syn/fake_ram_blackbox.v"
SHA_A, SHA_B = "a" * 64, "b" * 64


def main():
    base = Path(tempfile.mkdtemp(prefix="p04_"))
    try:
        make_tree(base)
        spec = spec_for(base)
        PROF = C.ValidationProfile(
            contract_schema="contract-v1", contest_commit="7623b53",
            container_digest="sha256:e258fff66f93", generator_digest="g1",
            reproduction_digest="r1", host_arch="arm64",
            evidence_root="nvdla_p04_evidence/")
        C._reset_tmake_registry()
        C.register_tmake("fakenv", C.TmakeRegistration(
            layout=C.default_tmake_layout(spec),
            bound_validation_digest=PROF.digest()))
        ctr = C.get_contract(spec)
        run = runner_for(base)
        scope = C.CampaignScope(ip="fakenv", editable_targets=(TARGET,),
                                verification_policy="gate+lec")
        import dataclasses as _dc

        # ── resolution / families / layout registry ──────────────────────────
        check("tmake key resolves TmakeContract", isinstance(ctr, C.TmakeContract))
        check("async_fifo -> DirectContract",
              isinstance(C.get_contract(IPS["async_fifo"]), C.DirectContract))
        check("ascon (sv_sources) -> Sv2vContract",
              isinstance(C.get_contract(IPS["ascon"]), C.Sv2vContract))
        raises(lambda: C.get_contract(_dc.replace(spec, contract="tmakke")),
               "unknown contract string fails closed")
        raises(lambda: C.get_contract(_dc.replace(spec, name="fakenv3")),
               "tmake WITHOUT a declared registration fails closed")
        raises(lambda: C.register_tmake("fakenv", C.TmakeRegistration(
                   layout=C.default_tmake_layout(spec))),
               "duplicate/late re-registration rejected (no silent binding "
               "swap)")
        raises(lambda: C.default_tmake_layout(_dc.replace(spec, filelist="")),
               "layout construction without explicit filelist fails closed")
        fake_lay = C.TMAKE_REGISTRY["fakenv"].layout
        raises(lambda: _dc.replace(fake_lay, mapping_root="FAKE/elsewhere"),
               "layout with mapping_root outside generated_root fails closed")
        raises(lambda: _dc.replace(fake_lay, filelist_base="OTHER/syn"),
               "layout with filelist_base outside root fails closed")

        # ── sv2v real mappings ───────────────────────────────────────────────
        asc, aspec = C.get_contract(IPS["ascon"]), IPS["ascon"]
        sv = aspec.sv_sources[1]
        gen_v = f"{aspec.rtl_dir}/ascon_core.v"
        check("sv2v mode (a): .sv <-> authoritative generated .v both ways",
              asc.source_to_generated(sv) == (gen_v,)
              and asc.generated_to_source(gen_v) == sv)
        check("sv2v mode (b): no-.sv generated .v maps to itself",
              asc.source_to_generated(f"{aspec.rtl_dir}/other.v")
              == (f"{aspec.rtl_dir}/other.v",)
              and asc.generated_to_source(f"{aspec.rtl_dir}/other.v")
              == f"{aspec.rtl_dir}/other.v")
        check("sv2v: unrelated path reverse-maps to None",
              asc.generated_to_source("opentitan/hw/ip/x/rtl/x.svh") is None)
        dc = C.get_contract(IPS["async_fifo"])
        check("direct: rtl_dir .v editable == legacy rule",
              dc.is_editable("async_fifo/rtl/fifomem.v")
              and not dc.is_editable("async_fifo/tb/x.v"))

        # ── filelist model: strict parse, exact order, dup rejection ─────────
        ok, _ = ctr.regenerate(base, run)
        check("regenerate rc ok", ok)
        model = ctr.filelist_model(base)
        check("filelist: 6 ordered sources, exact order preserved",
              len(model.sources) == 6
              and model.sources[0] == GEN_TARGET
              and model.sources[4] == NONOUT_VLIB
              and model.sources[5] == NONOUT_BB)
        check("filelist: traversal entries resolved canonically",
              not any(".." in s or s.startswith("./") for s in model.sources))
        check("filelist: 4 include roots incl. `-I.` -> syn dir",
              len(model.include_roots) == 4
              and model.include_roots[3] == "FAKE/syn/yosys_syn")
        check("filelist: defines parsed", model.defines == ("SYNTHESIS", "NO_PLI"))
        fl = base / spec.filelist
        fl_raw = fl.read_text()
        (base / NONOUT_BB).rename(base / (NONOUT_BB + ".x"))
        raises(lambda: ctr.filelist_model(base),
               "missing declared source fails closed")
        (base / (NONOUT_BB + ".x")).rename(base / NONOUT_BB)
        fl.write_text(fl_raw + "-DSYNTHESIS\n")
        raises(lambda: ctr.filelist_model(base),
               "duplicate define fails closed")
        fl.write_text(fl_raw + "-I.\n")
        raises(lambda: ctr.filelist_model(base),
               "duplicate include root fails closed")
        fl.write_text(fl_raw)

        # ── include-token ambiguity (re-review SS4.6) ────────────────────────
        amb = base / "FAKE/outdir/nv_small/vmod/vlibs/defs.vh"
        amb.write_text("// second defs.vh\n")
        raises(lambda: ctr.include_universe(base, ctr.filelist_model(base)),
               "ambiguous include token across two roots fails closed")
        amb.unlink()

        # ── complete generated universe ──────────────────────────────────────
        m1 = ctr.fingerprint(base)
        check("fingerprint = COMPLETE generated tree (nvdla+vlibs+include)",
              len(m1) == 5
              and any("vlibs/gen_lib.v" in e.rel for e in m1)
              and any(e.rel.endswith("include/defs.vh") for e in m1)
              and not any(e.rel in (NONOUT_VLIB, NONOUT_BB) for e in m1))
        ok2, _ = ctr.regenerate(base, run)
        check("1: two clean materializations byte-identical",
              ok2 and C.manifest_root(ctr.fingerprint(base)) == C.manifest_root(m1))
        shutil.rmtree(base / "FAKE/outdir")
        raises(lambda: ctr.fingerprint(base),
               "missing generated root -> flow error, not empty manifest")
        ctr.regenerate(base, run)

        # ── golden snapshot: exact membership, NO alias following ────────────
        gman = ctr.snapshot_golden(base)
        h3 = ctr.fingerprint(base)
        check("golden universe covers generated + non-outdir inputs + filelist",
              {NONOUT_VLIB, NONOUT_BB, spec.filelist} <= {e.rel for e in gman}
              and {e.rel for e in h3} <= {e.rel for e in gman})
        ctr.regenerate(base, run)
        check("3: golden snapshot survives candidate tmake -clean",
              ctr.verify_golden(base, gman))
        extra = base / ctr.golden_dir() / "FAKE/outdir/nv_small/vmod/extra.v"
        extra.write_text("// planted\n")
        check("extra golden member fails exact-membership verification",
              not ctr.verify_golden(base, gman))
        extra.unlink()
        gfile = base / ctr.golden_dir() / GEN_TARGET
        saved_bytes = gfile.read_bytes()
        gfile.unlink()
        gfile.symlink_to(base / GEN_TARGET)   # alias back to candidate tree
        check("ADV-5: golden symlink aliasing the candidate tree fails "
              "verification", not ctr.verify_golden(base, gman))
        gfile.unlink(); gfile.write_bytes(saved_bytes)
        check("golden verification restored", ctr.verify_golden(base, gman))

        # ── symmetric side-bound DesignInputs ────────────────────────────────
        gi = ctr.design_inputs(base, "golden")
        ci = ctr.design_inputs(base, "candidate")
        check("golden inputs fully under .golden/",
              all(p.startswith(".golden/") for p in
                  (*gi.ordered_sources, *gi.include_roots, *gi.include_files)))
        check("candidate inputs never read .golden/",
              not any(p.startswith(".golden/") for p in ci.ordered_sources))
        check("both sides: all 6 sources incl. both non-outdir inputs",
              len(gi.ordered_sources) == len(ci.ordered_sources) == 6)
        g0, c0 = gi.digest(), ci.digest()
        gpath = base / ctr.golden_dir() / NONOUT_VLIB
        saved = gpath.read_text()
        gpath.write_text("module NV_DW_lsd_mut(); endmodule\n")
        check("golden non-outdir mutation changes ONLY the golden digest",
              ctr.design_inputs(base, "golden").digest() != g0
              and ctr.design_inputs(base, "candidate").digest() == c0)
        gpath.write_text(saved)
        (base / NONOUT_BB).write_text("module fake_ram_v2(); endmodule\n")
        check("candidate non-outdir mutation changes ONLY the candidate digest",
              ctr.design_inputs(base, "candidate").digest() != c0
              and ctr.design_inputs(base, "golden").digest() == g0)
        (base / NONOUT_BB).write_text("module fake_ram(); endmodule\n")
        d0 = ci.digest()
        check("5a: digest changes when a define changes",
              _dc.replace(ci, defines=ci.defines[:-1]).digest() != d0)
        check("5b: digest changes when source order changes",
              _dc.replace(ci, ordered_sources=tuple(
                  reversed(ci.ordered_sources))).digest() != d0)
        (base / "FAKE/outdir/nv_small/vmod/include/defs.vh").write_text("// x\n")
        check("5c: digest changes when an include file changes",
              ctr.design_inputs(base, "candidate").digest() != d0)
        ctr.regenerate(base, run)
        ys = ci.yosys_read()
        check("yosys adapter: per-file -defer reads with defines/includes",
              ys.count("read_verilog -sv -defer") == len(ci.ordered_sources)
              and "-DSYNTHESIS" in ys and "-I" in ys)

        # ── scope authority ──────────────────────────────────────────────────
        raises(lambda: C.validate_candidate(ctr, base, {TARGET: "x"}, None),
               "tmake candidate WITHOUT scope refused")
        wrong_ip = C.CampaignScope(ip="othernv", editable_targets=(TARGET,),
                                   verification_policy="gate+lec")
        raises(lambda: C.validate_candidate(ctr, base, {TARGET: "x"}, wrong_ip),
               "scope for another IP refused")
        raises(lambda: C.CampaignScope(ip="fakenv", editable_targets=(TARGET,),
                                       verification_policy="gate+lec",
                                       schema="contract-v0"),
               "unknown scope schema refused")
        alias = C.CampaignScope(ip="fakenv",
                                editable_targets=("FAKE/vmod/nvdla/pdp/./core.v",),
                                verification_policy="gate+lec")
        check("aliased target canonicalized AND STORED canonical",
              alias.editable_targets == (TARGET,)
              and alias.scope_id() == scope.scope_id())
        check("scope_id is full sha256", len(scope.scope_id()) == 64)

        def rejects(rel, scope_=scope):
            try:
                C.validate_candidate_path(ctr, base, rel, scope_)
                return False
            except C.ContractError:
                return True
        check("outdir overlay rejected (flow control)", rejects(GEN_TARGET))
        check(".h edit rejected", rejects("FAKE/vmod/nvdla/defs.h"))
        check("absolute path rejected", rejects(str(base / TARGET)))
        check("`..` rejected", rejects("FAKE/vmod/nvdla/../../x.v"))
        check("in-universe but out-of-scope rejected",
              rejects("FAKE/vmod/nvdla/pdp/unit.v"))
        link = base / "FAKE/vmod/nvdla/pdp/evil.v"
        outside = base.parent / f"{base.name}_outside.v"
        outside.write_text("module m; endmodule\n")
        link.symlink_to(outside)
        sc2 = C.CampaignScope(ip="fakenv",
                              editable_targets=("FAKE/vmod/nvdla/pdp/evil.v",),
                              verification_policy="gate+lec")
        check("external symlink escape rejected",
              rejects("FAKE/vmod/nvdla/pdp/evil.v", sc2))
        link.unlink(); outside.unlink()

        # ADV-1: internal symlink redirection into an immutable dependency
        core = base / TARGET
        core_bytes = core.read_bytes()
        core.unlink()
        core.symlink_to(base / NONOUT_VLIB)
        check("ADV-1: scoped path symlinked to an in-workspace immutable "
              "file rejected", rejects(TARGET))
        core.unlink(); core.write_bytes(core_bytes)
        dirlink = base / "FAKE/vmod/nvdla/pdplink"
        dirlink.symlink_to(base / "FAKE/vmod/nvdla/pdp")
        sc3 = C.CampaignScope(ip="fakenv",
                              editable_targets=("FAKE/vmod/nvdla/pdplink/core.v",),
                              verification_policy="gate+lec")
        check("ADV-1b: intermediate-directory symlink rejected",
              rejects("FAKE/vmod/nvdla/pdplink/core.v", sc3))
        dirlink.unlink()
        raises(lambda: C.validate_candidate(
            ctr, base, {TARGET: "x", "FAKE/vmod/nvdla/pdp/unit.v": "y"},
            C.CampaignScope(ip="fakenv",
                            editable_targets=(TARGET,
                                              "FAKE/vmod/nvdla/pdp/unit.v"),
                            verification_policy="gate+lec",
                            max_changed_files=1)),
               "max_changed_files enforced")
        raises(lambda: C.CampaignScope(ip="fakenv", editable_targets=(),
                                       verification_policy="gate+lec"),
               "empty targets rejected")
        raises(lambda: C.CampaignScope(ip="fakenv",
                                       editable_targets=(TARGET, TARGET),
                                       verification_policy="gate+lec"),
               "duplicate targets rejected")
        raises(lambda: C.CampaignScope(ip="fakenv",
                                       editable_targets=("a/../x.v",),
                                       verification_policy="gate+lec"),
               "raw '..' target rejected")

        # ── worker authority ─────────────────────────────────────────────────
        sc_w4 = C.CampaignScope(ip="fakenv", editable_targets=(TARGET,),
                                verification_policy="gate+lec",
                                requested_workers=4)
        check("10: requested workers 4 -> effective 1 for tmake",
              C.effective_workers(sc_w4, ctr) == 1
              and C.effective_workers(sc_w4, dc) == 4)
        check("requested_workers is provenance-only (excluded from scope_id)",
              sc_w4.scope_id() == scope.scope_id())
        raises(lambda: C.effective_workers(sc_w4, dc, global_cap=0),
               "invalid global worker cap fails closed (no silent max(1,..))")

        # ── reverse map + path classes ───────────────────────────────────────
        check("source->generated->source round trip",
              ctr.source_to_generated(TARGET) == (GEN_TARGET,)
              and ctr.generated_to_source(GEN_TARGET) == TARGET)
        check("generated vlibs file does NOT reverse-map to editable",
              ctr.generated_to_source(
                  "FAKE/outdir/nv_small/vmod/vlibs/gen_lib.v") is None)
        pc = ctr.path_classes()
        check("five path classes; golden is its own class; outdir/verif "
              "tool-writable",
              set(pc) == {"editable", "tool_writable", "immutable_deps",
                          "golden", "evidence"}
              and "FAKE/outdir" in pc["tool_writable"]
              and ".golden" in pc["golden"]
              and "FAKE/vmod/vlibs" in pc["immutable_deps"]
              and spec.filelist in pc["immutable_deps"])

        # ── H1/H2-aware, SCOPE-AUTHORITATIVE classification ──────────────────
        src = base / TARGET
        pristine = src.read_text()

        def mat_for(edit_text):
            m = C.Materialization(h3=h3)
            m.h1 = {TARGET: C._hash_file(src)}
            src.write_text(edit_text)
            m.h2 = {TARGET: C._hash_file(src)}
            ok, _ = ctr.regenerate(base, run)
            assert ok
            m.h4 = ctr.fingerprint(base)
            return C.classify_materialization(ctr, m, scope, profile=PROF)

        m = mat_for(pristine + "//STRIP reviewer note\n")
        check("2: stripped-comment edit -> no-effective-change",
              m.classification == "no-effective-change")
        m = mat_for(pristine.replace("assign y = a;", "assign y = a & 1'b1;"))
        check("logic edit -> proceed, changed == mapped generated file",
              m.classification == "proceed" and m.changed == (GEN_TARGET,))

        # ADV-2: classifier enforces scope authority itself
        good = C.Materialization(h3=h3, h1=dict(m.h1), h2=dict(m.h2),
                                 h4=tuple(m.h4))
        raises(lambda: C.classify_materialization(ctr, good, None,
                                                  profile=PROF),
               "ADV-2: classifier refuses missing Tmake scope")
        raises(lambda: C.classify_materialization(ctr, good, wrong_ip,
                                                  profile=PROF),
               "ADV-2b: classifier refuses wrong-IP scope")
        two_t = C.CampaignScope(ip="fakenv",
                                editable_targets=(TARGET,
                                                  "FAKE/vmod/nvdla/pdp/unit.v"),
                                verification_policy="gate+lec",
                                max_changed_files=2)
        part = C.Materialization(h3=h3, h1=dict(m.h1), h2=dict(m.h2),
                                 h4=tuple(m.h4))
        C.classify_materialization(ctr, part, two_t, profile=PROF)
        check("partial H1/H2 coverage of the scoped set -> flow-error",
              part.classification == "flow-error")

        m_nosrc = C.Materialization(h3=h3, h1={TARGET: SHA_A},
                                    h2={TARGET: SHA_A},
                                    h4=ctr.fingerprint(base))
        C.classify_materialization(ctr, m_nosrc, scope, profile=PROF)
        check("H1==H2 with generated change -> collateral-drift (derived "
              "VALIDATED via bound contract + matching profile)",
              m_nosrc.classification == "collateral-drift")
        m_pend = C.Materialization(h3=h3, h1={TARGET: SHA_A},
                                   h2={TARGET: SHA_A},
                                   h4=ctr.fingerprint(base))
        C.classify_materialization(ctr, m_pend, scope)   # default PENDING
        check("same drift under PENDING determinism -> flow-error, not a "
              "host-proven drift claim",
              m_pend.classification == "flow-error"
              and "UNVALIDATED" in m_pend.detail)
        m_bad = C.Materialization(h3=h3, h4=ctr.fingerprint(base))
        C.classify_materialization(ctr, m_bad, scope)
        check("missing H1/H2 -> flow-error", m_bad.classification == "flow-error")
        m_hash = C.Materialization(h3=h3, h1={TARGET: "junk"},
                                   h2={TARGET: SHA_B},
                                   h4=ctr.fingerprint(base))
        C.classify_materialization(ctr, m_hash, scope)
        check("invalid H1/H2 hash text -> flow-error",
              m_hash.classification == "flow-error")
        ctr.regenerate(base, run)
        (base / "FAKE/outdir/nv_small/vmod/nvdla/pdp/unit.v").write_text("//t\n")
        m2 = C.Materialization(h3=h3, h1=dict(m.h1), h2=dict(m.h2),
                               h4=ctr.fingerprint(base))
        C.classify_materialization(ctr, m2, scope, profile=PROF)
        check("collateral drift on unmapped generated file rejected",
              m2.classification == "collateral-drift")
        ctr.regenerate(base, run)
        victim = base / "FAKE/outdir/nv_small/vmod/nvdla/top/top.v"
        saved_v = victim.read_text(); victim.unlink()
        m3 = C.Materialization(h3=h3, h1=dict(m.h1), h2=dict(m.h2),
                               h4=ctr.fingerprint(base))
        C.classify_materialization(ctr, m3, scope, profile=PROF)
        check("missing generated file -> flow-error (membership change)",
              m3.classification == "flow-error")
        victim.write_text(saved_v)
        # ADV-7b: malformed deserialized manifest cannot bypass validation
        m4 = C.Materialization(h3=(C.ManifestEntry("x.v", -1, "nothex"),),
                               h1=dict(m.h1), h2=dict(m.h2), h4=tuple(m.h4))
        C.classify_materialization(ctr, m4, scope, profile=PROF)
        check("ADV-7: malformed deserialized H3 -> flow-error",
              m4.classification == "flow-error")

        # ── H5 gate stability ────────────────────────────────────────────────
        src.write_text(pristine.replace("assign y = a;",
                                        "assign y = a & 1'b1;"))
        ctr.regenerate(base, run)
        m.h4 = ctr.fingerprint(base)
        m.h5 = ctr.fingerprint(base)
        check("H5 == H4 passes gate-stability", C.check_gate_stability(m))
        src.write_text(pristine)
        ctr.regenerate(base, run)
        m.h5 = ctr.fingerprint(base)
        check("13: H5 != H4 -> flow-error reject",
              not C.check_gate_stability(m)
              and m.classification == "flow-error")

        # ── manifest hardening ───────────────────────────────────────────────
        lnk = base / "FAKE/outdir/nv_small/vmod/nvdla/pdp/link.v"
        target_out = base.parent / f"{base.name}_ext.v"
        target_out.write_text("module ext(); endmodule\n")
        lnk.symlink_to(target_out)
        raises(lambda: ctr.fingerprint(base),
               "leaf symlink inside manifest tree rejected")
        lnk.unlink(); target_out.unlink()
        dlink = base / "FAKE/alias"
        dlink.symlink_to(base / "FAKE/vmod")
        raises(lambda: C.tree_manifest(base, ["FAKE/alias/nvdla/pdp/core.v"]),
               "ADV-7b: parent-component symlink in manifest entry rejected")
        dlink.unlink()
        raises(lambda: C.tree_manifest(base, []),
               "empty manifest set is a flow error")
        raises(lambda: C.tree_manifest(base, [TARGET, TARGET]),
               "duplicate manifest paths rejected")
        raises(lambda: C.manifest_root(()),
               "ADV-7c: empty manifest_root rejected")
        raises(lambda: C.manifest_root((C.ManifestEntry("a.v", -1, SHA_A),)),
               "negative size rejected")
        raises(lambda: C.manifest_root((C.ManifestEntry("a.v", 1, "junk"),)),
               "non-sha256 hash rejected")
        raises(lambda: C.manifest_root((C.ManifestEntry("a.v", 1, SHA_A),
                                        C.ManifestEntry("a.v", 1, SHA_B))),
               "manifest_root rejects duplicate rels")

        # ── copy independence + escaping-symlink rejection ───────────────────
        from ppa.workspace import _clone_tree
        cdst = base / "clonecheck"
        method = _clone_tree(base / "FAKE/vmod", cdst)
        probe_src = base / "FAKE/vmod/nvdla/pdp/core.v"
        probe_dst = cdst / "nvdla/pdp/core.v"
        before = probe_src.read_bytes()
        no_hl = probe_dst.stat().st_ino != probe_src.stat().st_ino
        probe_dst.write_text("// mutated in copy\n")
        check(f"copy independence (method={method}); no shared hardlink",
              probe_src.read_bytes() == before and no_hl)
        shutil.rmtree(cdst)
        evil_dir = base / "FAKE/vmod/evil"
        evil_dir.mkdir()
        ext = base.parent / f"{base.name}_extfile"
        ext.write_text("secret\n")
        (evil_dir / "leak").symlink_to(ext)
        raises(lambda: _clone_tree(base / "FAKE/vmod", base / "clonecheck2"),
               "clone with escaping symlink rejected post-copy")
        shutil.rmtree(evil_dir); ext.unlink()

        # ── editable-state seeding ───────────────────────────────────────────
        raises(lambda: ctr.pristine_editable_state(None, repo=base),
               "tmake seeding without scope refuses")
        raises(lambda: ctr.pristine_editable_state(wrong_ip, repo=base),
               "seeding with wrong-IP scope refuses")
        seed = ctr.pristine_editable_state(scope, repo=base)
        check("7: seed contains editable vmod path only, never generated",
              set(seed) == {TARGET} and "outdir" not in next(iter(seed)))

        # ── validation binding: immutable trusted registration (ADV-3/1d) ────
        spec2 = _dc.replace(spec, name="fakenv2")
        C.register_tmake("fakenv2", C.TmakeRegistration(
            layout=C.default_tmake_layout(spec2)))     # UNBOUND (pre-H-1)
        unbound = C.get_contract(spec2)
        check("ADV-3: self-created profile can NEVER validate an UNBOUND "
              "contract (no caller digest parameter exists)",
              unbound.validation_state(PROF) == "PENDING"
              and unbound.validation_state() == "PENDING")
        try:
            unbound.bound_validation_digest = PROF.digest()
            check("1d: public binding assignment raises (read-only property)",
                  False)
        except AttributeError:
            check("1d: public binding assignment raises (read-only property)",
                  True)
        # 1e: the BACKING state is sealed too - ordinary private-attribute
        # assignment raises and the state stays PENDING (re-review3 SS4 probe)
        try:
            unbound._bound_validation_digest = PROF.digest()
            sealed_ok = False
        except AttributeError:
            sealed_ok = True
        check("1e: backing-attribute assignment raises (sealed contract) and "
              "state stays PENDING",
              sealed_ok and unbound.validation_state(PROF) == "PENDING")
        try:
            unbound._registration = C.TmakeRegistration(
                layout=C.default_tmake_layout(spec2),
                bound_validation_digest=PROF.digest())
            sealed_reg = False
        except AttributeError:
            sealed_reg = True
        check("1e: registration reference is non-reassignable",
              sealed_reg and unbound.validation_state(PROF) == "PENDING")
        # 1f (re-review4 SS4): DELETION is sealed too - `del _sealed` must not
        # re-enable assignment, and the contract stays usable and PENDING
        def del_rejected(attr):
            try:
                delattr(unbound, attr)
                return False
            except AttributeError:
                return True
        check("1f: del _sealed raises (deletion sealed)",
              del_rejected("_sealed"))
        check("1f: del _registration raises", del_rejected("_registration"))
        check("1f: del spec raises", del_rejected("spec"))
        try:
            unbound._bound_validation_digest = PROF.digest()
            post_del_assign = False
        except AttributeError:
            post_del_assign = True
        check("1f: assignment STILL raises after deletion attempts; contract "
              "usable and PENDING",
              post_del_assign
              and unbound.validation_state(PROF) == "PENDING"
              and unbound.layout.root == "FAKE")
        # 1e: the exported registry view is read-only - direct replacement
        # fails through the CONTAINER, not just the helper
        try:
            C.TMAKE_REGISTRY["fakenv2"] = C.TmakeRegistration(
                layout=C.default_tmake_layout(spec2),
                bound_validation_digest=PROF.digest())
            view_ro = False
        except TypeError:
            view_ro = True
        check("1e: TMAKE_REGISTRY public view rejects assignment (read-only "
              "MappingProxy)", view_ro
              and unbound.validation_state(PROF) == "PENDING")
        # 1e: no production constructor bypass exists any more
        try:
            C.TmakeContract(spec2, registration=C.TmakeRegistration(
                layout=C.default_tmake_layout(spec2),
                bound_validation_digest=PROF.digest()))
            no_bypass = False
        except TypeError:
            no_bypass = True
        check("1e: constructor accepts no ad hoc registration (production "
              "path = sealed registry only)", no_bypass)
        raises(lambda: C.TmakeRegistration(
                   layout=C.default_tmake_layout(spec2),
                   bound_validation_digest="not-a-digest"),
               "1e: malformed registration digest rejected at construction")
        raises(lambda: C.TmakeRegistration(
                   layout=C.default_tmake_layout(spec2),
                   bound_validation_digest=SHA_A + "\n"),
               "1f: 64-hex + trailing newline rejected (exact fullmatch)")
        raises(lambda: C.TmakeRegistration(
                   layout=C.default_tmake_layout(spec2),
                   bound_validation_digest=12345),
               "1f: non-string digest is a structured error, not TypeError")
        raises(lambda: unbound.validation_state("VALIDATED"),
               "1e: legacy string profile is a structured error, not an "
               "opaque crash")
        varied = _dc.replace(PROF, container_digest="sha256:other")
        check("VALIDATED only for the exact registration-bound profile digest",
              ctr.validation_state(PROF) == "VALIDATED"
              and ctr.validation_state(varied) == "PENDING"
              and ctr.validation_state() == "PENDING")
        (base / "FAKE/outdir/nv_small/vmod/nvdla/pdp/unit.v").write_text(
            "// drift\n")
        drift_unbound = C.Materialization(h3=h3, h1={TARGET: SHA_A},
                                          h2={TARGET: SHA_A},
                                          h4=ctr.fingerprint(base))
        ctr.regenerate(base, run)
        sc_ub = C.CampaignScope(ip="fakenv2", editable_targets=(TARGET,),
                                verification_policy="gate+lec")
        C.classify_materialization(unbound, drift_unbound, sc_ub, profile=PROF)
        check("1d: unbound contract can never reach the drift (VALIDATED) "
              "branch - no text path exists",
              drift_unbound.classification == "flow-error"
              and "UNVALIDATED" in drift_unbound.detail)
        raises(lambda: C.ValidationProfile(
            contract_schema="contract-v1", contest_commit="c",
            container_digest="x", generator_digest="g",
            reproduction_digest="r", host_arch="arm64", evidence_root=""),
               "empty evidence_root rejected (required field)")
        check("profile digest is full sha256", len(PROF.digest()) == 64)
        check("direct/sv2v families are VALIDATED (banked host evidence)",
              dc.validation_state() == "VALIDATED"
              and asc.validation_state() == "VALIDATED")

        # ── proof algebra: diagnostic record only (ADV-4) ────────────────────
        pr = C.ProofResult(verdict="PROVEN", reason="fully_proven", rc=0,
                           total=381209, proven=381209, unproven=0,
                           recipe_id=C.LEC_RECIPE_CONTRACT_V2)
        check("ADV-4: ProofResult exposes NO eligibility property",
              not hasattr(pr, "lec_eligible"))
        for label, kw in (
                ("bare PROVEN", {}),
                ("zero total", dict(rc=0, total=0, proven=0, unproven=0,
                                    recipe_id=C.LEC_RECIPE_CONTRACT_V2)),
                ("unproven nonzero", dict(rc=0, total=10, proven=9, unproven=1,
                                          recipe_id=C.LEC_RECIPE_CONTRACT_V2)),
                ("proven != total", dict(rc=0, total=10, proven=9, unproven=0,
                                         recipe_id=C.LEC_RECIPE_CONTRACT_V2)),
                ("nonzero rc", dict(rc=1, total=10, proven=10, unproven=0,
                                    recipe_id=C.LEC_RECIPE_CONTRACT_V2)),
                ("v1 diagnostic recipe", dict(rc=0, total=10, proven=10,
                                              unproven=0,
                                              recipe_id=C.LEC_RECIPE_DIAG_V1))):
            raises(lambda kw=kw: C.ProofResult(verdict="PROVEN",
                                               reason="fully_proven", **kw),
                   f"incomplete PROVEN rejected: {label}")
        check("timeout stays an INCONCLUSIVE reason",
              C.ProofResult(verdict="INCONCLUSIVE",
                            reason="timeout").verdict == "INCONCLUSIVE")
        raises(lambda: C.ProofResult(verdict="TIMEOUT", reason="timeout"),
               "TIMEOUT as verdict rejected")
        raises(lambda: C.ProofResult(verdict="INEQUIVALENT",
                                     reason="induction_counterexample_unconfirmed"),
               "unconfirmed witness cannot be INEQUIVALENT")

        # ── statelessness across workspaces ──────────────────────────────────
        base2 = Path(tempfile.mkdtemp(prefix="p04b_"))
        try:
            make_tree(base2)
            (base2 / TARGET).write_text("module core(input a, output y);\n"
                                        "assign y = ~a;\nendmodule\n")
            r2 = runner_for(base2)
            ctr.regenerate(base2, r2)
            ctr.regenerate(base, run)
            fA, fB = ctr.fingerprint(base), ctr.fingerprint(base2)
            check("contract reuse across workspaces: no state leakage",
                  C.manifest_root(fA) != C.manifest_root(fB)
                  and C.manifest_root(ctr.fingerprint(base))
                  == C.manifest_root(fA))
        finally:
            shutil.rmtree(base2, ignore_errors=True)

        # ── checkpoint-1d regressions: golden parent alias (4.3) ─────────────
        gr = base / ".golden"
        gr.rename(base / "golden_real")
        gr.symlink_to(base / "golden_real")
        check("1d-4.3: symlink AT .golden fails verification",
              not ctr.verify_golden(base, gman))
        gr.unlink(); (base / "golden_real").rename(gr)
        layer = base / ".golden/FAKE"
        layer.rename(base / ".golden/FAKE_real")
        layer.symlink_to(base / ".golden/FAKE_real")
        check("1d-4.3b: symlink at .golden/<layout-root> fails verification",
              not ctr.verify_golden(base, gman))
        layer.unlink(); (base / ".golden/FAKE_real").rename(layer)
        check("golden verification restored (after alias probes)",
              ctr.verify_golden(base, gman))
        lnk2 = base / ".golden_probe"
        lnk2.symlink_to(base / "golden_nonexistent")
        # snapshot into an aliased golden root must refuse BEFORE writes
        shutil.rmtree(base / ".golden")
        (base / ".golden").symlink_to(base / "FAKE")   # alias into candidate!
        raises(lambda: ctr.snapshot_golden(base),
               "1d-4.3c: snapshot refuses an aliased golden root pre-write")
        (base / ".golden").unlink(); lnk2.unlink()
        gman2 = ctr.snapshot_golden(base)
        check("golden re-snapshot after alias probe verifies",
              ctr.verify_golden(base, gman2))

        # ── checkpoint-1d: filelist read through a symlink (4.4) ─────────────
        flp = base / spec.filelist
        flbak = base / (spec.filelist + ".orig")
        flp.rename(flbak)
        ext_fl = base.parent / f"{base.name}_filelist_copy.f"
        ext_fl.write_bytes(flbak.read_bytes())         # identical bytes
        flp.symlink_to(ext_fl)
        raises(lambda: ctr.filelist_model(base),
               "1d-4.4: filelist leaf symlink rejected BEFORE reading "
               "(identical bytes do not launder the alias)")
        flp.unlink(); flbak.rename(flp); ext_fl.unlink()

        # ── checkpoint-1d: clone under a symlink-aliased ancestor (4.1) ──────
        realparent = base / "realparent"
        realparent.mkdir()
        aliasparent = base / "aliasparent"
        aliasparent.symlink_to(realparent)
        adst = aliasparent / "clonecheck3"             # lexical path via alias
        method2 = _clone_tree(base / "FAKE/vmod", adst)
        probe2 = adst / "nvdla/pdp/core.v"
        check(f"1d-4.1: clone under symlink-aliased ancestor works "
              f"(method={method2}, no /var-style crash)",
              probe2.is_file()
              and probe2.read_bytes() == (base / TARGET).read_bytes())
        shutil.rmtree(realparent); aliasparent.unlink()

        # ── 1e: hardlink handling is INVARIANT-based (re-review3 SS5) ────────
        # deterministic unit: a destination tree that DEFINITELY contains a
        # hardlink pair must be rejected by the scan helper, independent of
        # any copy method's semantics
        from ppa.workspace import _scan_dest_aliases
        import os as _os
        dsttree = base / "hl_dst"
        (dsttree / "sub").mkdir(parents=True)
        (dsttree / "a.v").write_text("module a(); endmodule\n")
        _os.link(dsttree / "a.v", dsttree / "sub/b.v")
        raises(lambda: _scan_dest_aliases(base / "hl_nosrc", dsttree),
               "1e-unit: destination tree containing a hardlink pair rejected "
               "by the scan helper")
        shutil.rmtree(dsttree)
        # end-to-end: a SOURCE hardlink pair must yield EITHER rejection (the
        # copy method preserved the pair) OR a verified independent
        # destination (the method de-linked it - safe, e.g. APFS cp -Rc)
        hlsrc = base / "hlsrc"
        (hlsrc / "sub").mkdir(parents=True)
        (hlsrc / "a.v").write_text("module a(); endmodule\n")
        _os.link(hlsrc / "a.v", hlsrc / "sub/b.v")
        try:
            _clone_tree(hlsrc, base / "hlclone")
            da, db = base / "hlclone/a.v", base / "hlclone/sub/b.v"
            sa = hlsrc / "a.v"
            independent = (
                (da.stat().st_dev, da.stat().st_ino)
                != (db.stat().st_dev, db.stat().st_ino)
                and (da.stat().st_dev, da.stat().st_ino)
                != (sa.stat().st_dev, sa.stat().st_ino))
            sb = hlsrc / "sub/b.v"
            independent = independent and (
                (db.stat().st_dev, db.stat().st_ino)
                != (sb.stat().st_dev, sb.stat().st_ino))
            da.write_text("// mutated\n")
            isolated = (db.read_text() == "module a(); endmodule\n"
                        and sa.read_text() == "module a(); endmodule\n")
            shutil.rmtree(base / "hlclone")
            # symmetric direction (re-review4 SS5.2): fresh copy, mutate db,
            # prove da and BOTH source paths unchanged
            _clone_tree(hlsrc, base / "hlclone")
            da2, db2 = base / "hlclone/a.v", base / "hlclone/sub/b.v"
            db2.write_text("// mutated other way\n")
            isolated = isolated and (
                da2.read_text() == "module a(); endmodule\n"
                and sa.read_text() == "module a(); endmodule\n"
                and sb.read_text() == "module a(); endmodule\n")
            check("1e: source hardlink pair -> rejected OR de-linked "
                  "independent copies, mutation-isolated BOTH ways",
                  independent and isolated)
            shutil.rmtree(base / "hlclone")
        except C.ContractError:
            check("1e: source hardlink pair -> rejected OR de-linked "
                  "independent isolated copies", True)
        shutil.rmtree(hlsrc)

        # ── checkpoint-1d: _validate_copy type/alias enforcement (5.1) ───────
        from types import SimpleNamespace
        from ppa.workspace import _validate_copy
        ed_root = base / "FAKE/vmod/nvdla"
        ed_root.rename(base / "FAKE/vmod/nvdla_real")
        ed_root.symlink_to(base / "FAKE/vmod/nvdla_real")
        raises(lambda: _validate_copy(SimpleNamespace(spec=spec, root=base)),
               "1d-5.1: required editable root as internal symlink rejected")
        ed_root.unlink()
        (base / "FAKE/vmod/nvdla_real").rename(ed_root)
        _validate_copy(SimpleNamespace(spec=spec, root=base))
        check("1d-5.1b: intact required roots pass post-copy validation", True)

        # ── checkpoint-1d: FilelistModel direct construction (5.4) ───────────
        raises(lambda: C.FilelistModel(("D", "D"), ("i",), ("s.v",), SHA_A),
               "1d-5.4: FilelistModel duplicate defines rejected at "
               "construction")
        raises(lambda: C.FilelistModel(("D",), ("i",), (), SHA_A),
               "1d-5.4b: FilelistModel empty sources rejected")
        raises(lambda: C.FilelistModel(("D",), ("i",), ("s.v",), "junk"),
               "1d-5.4c: FilelistModel non-sha digest rejected")

        # ── checkpoint-1d: dot manifest entry (5.5) ──────────────────────────
        raises(lambda: C.manifest_root((C.ManifestEntry(".", 1, SHA_A),)),
               "1d-5.5: manifest entry rel='.' rejected")

        # ── DesignInputs guards ──────────────────────────────────────────────
        raises(lambda: C.DesignInputs(side="gold", top="t",
                                      ordered_sources=("a.v",)),
               "bad DesignInputs.side rejected")
        raises(lambda: C.DesignInputs(side="golden", top="",
                                      ordered_sources=("a.v",)),
               "empty top rejected")
        raises(lambda: C.DesignInputs(side="golden", top="t",
                                      ordered_sources=("/abs/a.v",)),
               "absolute path in DesignInputs rejected")
        raises(lambda: C.DesignInputs(side="golden", top="t",
                                      ordered_sources=()),
               "empty ordered_sources rejected")
        raises(lambda: C.DesignInputs(side="golden", top="t",
                                      ordered_sources=("a.v", "a.v")),
               "duplicate sources rejected")
        raises(lambda: C.DesignInputs(side="golden", top="t",
                                      ordered_sources=("a.v",),
                                      include_roots=("i", "i")),
               "duplicate include roots rejected")
        raises(lambda: C.DesignInputs(side="golden", top="t",
                                      ordered_sources=("a.v",),
                                      defines=("D", "D")),
               "duplicate defines rejected")
        raises(lambda: C.DesignInputs(side="golden", top="t",
                                      ordered_sources=("b/./a.v",)),
               "non-canonical source path rejected")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print(f"\ntest_contract: {PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
