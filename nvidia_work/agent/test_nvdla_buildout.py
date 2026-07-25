#!/usr/bin/env python3
"""Offline regressions for NVIDIA_NVDLA_BUILDOUT_SPEC_2026-07-24.

No Docker/model calls. Covers the explicit production spec/read recipe,
legacy byte-identity, mandatory fence, reset-path sanitization, exact scoped
variant mapping, and the H3/H4/H5 candidate-survival tripwire with fake tmake.
"""
import dataclasses
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ppa import contract as C                                    # noqa: E402
from ppa import controller as CTRL                               # noqa: E402
from ppa import diagnose as D                                    # noqa: E402
from ppa import materialize as M                                 # noqa: E402
from ppa import proposer as P                                    # noqa: E402
from ppa import registry                                         # noqa: E402
from ppa import release_control as R                              # noqa: E402
from ppa import verify as V                                      # noqa: E402
from ppa.config import IPS, IPSpec, REPO                         # noqa: E402
from ppa.workspace import candidate_from_dir                     # noqa: E402
from test_contract import (GEN_TARGET, TARGET, make_tree,         # noqa: E402
                           runner_for, spec_for)
from test_materialize import FakeWs, PROF                        # noqa: E402

PASS = FAIL = 0
PROJECT = Path(__file__).resolve().parents[2]


def check(name, ok):
    global PASS, FAIL
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    PASS, FAIL = PASS + int(bool(ok)), FAIL + int(not ok)


def raises_contract(name, fn):
    try:
        fn()
        check(name, False)
    except C.ContractError:
        check(name, True)


def _normal_read(line: str, base: str = "") -> tuple:
    """Normalize only physical paths; retain command/option order exactly."""
    out = []
    for tok in shlex.split(line):
        if tok.startswith("-I"):
            out.append("-I" + C._canon(os.path.join(base, tok[2:])))
        elif tok.endswith((".v", ".sv")):
            out.append(C._canon(os.path.join(base, tok)))
        else:
            out.append(tok)
    return tuple(out)


def main():
    if not (REPO / "NVDLA").is_dir():
        print("PREREQ-MISSING: contest NVDLA tree not present at", REPO)
        return 3

    # ── production spec + read recipe ───────────────────────────────────────
    registry.ensure_registered()
    spec = IPS["nvdla"]
    ctr = C.get_contract(spec)
    model = ctr.filelist_model(REPO)
    check("explicit NVDLA top + real clocks + corrected gate path",
          spec.top == "NV_nvdla"
          and [(c.name, c.period_ns) for c in spec.clocks]
              == [("dla_core_clk", 30.0), ("dla_csb_clk", 60.0)]
          and spec.gate_cmd == "./run_varilator_test.sh")
    check("pinned frontend: defer + 4 defines + 22 include roots",
          spec.lec_defer and len(spec.lec_defines) == 4
          and len(spec.lec_includes) == 22)
    check("pinned frontend agrees with authoritative filelist",
          set(spec.lec_defines) == set(model.defines)
          and spec.lec_includes == model.include_roots)
    check("NVDLA timeout policy = max(1800,2x758) = 1800",
          V._lec_timeout(spec) == 1800)

    # Default-off behavior is a literal byte-for-byte guard for the old
    # `_read_stanza` implementation.
    files = ["rtl/a.v", "rtl/b.v"]
    expected_legacy = (
        "read_verilog -sv rtl/a.v rtl/b.v\n"
        "hierarchy -check -top top\n"
        "proc\nmemory\nasync2sync\nflatten\nopt_clean\n")
    default_spec = IPSpec(
        name="legacy", top="top", rtl_dir="rtl", sources=tuple(files),
        syn_dir="syn", gate_dir=".", gate_cmd="true", subtrees=("rtl",))
    check("default-off LEC fields preserve legacy stanza byte-identically",
          V._read_stanza(files, "top", for_sat=True)
          == expected_legacy
          == V._read_stanza(files, "top", for_sat=True, spec=default_spec))

    # Compare all 323 frontend commands with the retained host-proven recipe.
    diag = (PROJECT / "nvdla_lec_diag/nvdla_lec.ys").read_text()
    diag_reads = []
    for line in diag.splitlines():
        if line.startswith("hierarchy "):
            break
        if line.startswith("read_verilog "):
            diag_reads.append(_normal_read(
                line, "NVDLA/syn/yosys_syn"))
    generated = V._read_stanza(
        list(model.sources), spec.top, for_sat=True, spec=spec)
    generated_reads = [_normal_read(line)
                       for line in generated.splitlines()
                       if line.startswith("read_verilog ")]
    check("NVDLA read recipe has one deferred read per ordered source",
          len(generated_reads) == 323)
    check("NVDLA read recipe matches host-proven v1 frontend modulo paths",
          generated_reads == diag_reads)
    di = ctr.design_inputs(REPO, "candidate")
    check("contract-side v2 frontend uses the same pinned recipe",
          di.yosys_read().splitlines()
          == V._read_stanza(list(model.sources), spec.top, spec=spec)
              .split("hierarchy ", 1)[0].splitlines())
    check("v2 proof tail remains explicit -seq 4 + -assert",
          "equiv_induct -seq 4\n" in V._EQUIV_PASSES
          and V._EQUIV_PASSES.endswith("equiv_status -assert\n"))
    bad_spec = dataclasses.replace(
        default_spec, lec_defines=("OK; shell",))
    raises_contract("malformed per-IP LEC token fails closed",
                    lambda: V._read_stanza(files, "top", spec=bad_spec))

    # Timeout is INCONCLUSIVE/ineligible, never a pass or a raw exception.
    lec_tmp = Path(tempfile.mkdtemp(prefix="nvdla_lec_timeout_"))
    try:
        class TimeoutWs:
            def write(self, rel, text):
                p = lec_tmp / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)

        def timeout_runner(cmd, timeout):
            raise subprocess.TimeoutExpired(cmd, timeout)

        timeout_result, timeout_log = V.run_lec_v2_script(
            TimeoutWs(), "read_verilog -sv x.v\n",
            runner=timeout_runner, timeout=7)
        check("NVDLA LEC timeout is INCONCLUSIVE/ineligible",
              timeout_result.verdict == "INCONCLUSIVE"
              and timeout_result.reason == "timeout"
              and timeout_result.rc is None
              and timeout_log == "TIMEOUT after 7s")
    finally:
        shutil.rmtree(lec_tmp, ignore_errors=True)

    # ── mandatory NVDLA fence ────────────────────────────────────────────────
    allowed = "NVDLA/vmod/nvdla/pdp/NV_NVDLA_PDP_nan.v"
    forbidden = (
        "NVDLA/vmod/nvdla/car/NV_NVDLA_core_reset.v",
        "NVDLA/vmod/nvdla/cdp/NV_NVDLA_CDP_DP_syncfifo.v",
        "NVDLA/vmod/nvdla/top/NV_NVDLA_partition_p.v",
        "NVDLA/vmod/nvdla/nocif/NV_NVDLA_MCIF_csb.v",
        "NVDLA/vmod/vlibs/NV_DW_lsd.v",
        "NVDLA/vmod/rams/synth/ram.v",
        "NVDLA/outdir/nv_small/vmod/include/defs.vh",
    )
    check("NVDLA fence is mandatory and allows an ordinary PDP leaf",
          P.FENCE["nvdla"]["mandatory"]
          and P.fence_violation("nvdla", {allowed: ""}) is None)
    check("NVDLA fence rejects reset/sync/partition/bus/dependency paths",
          all(P.fence_violation("nvdla", {rel: ""})
              for rel in forbidden))
    pctx = P.PromptContext(
        ip="nvdla", files={allowed: "module x; endmodule\n"},
        ppa={"area": 1, "cells": 1, "setup": -1, "power": 1},
        sta_block="", playbook_block="", dossier="", weights={"area": 1},
        budget_line="", fence=False)
    prompt = P.build_prompt(pctx, P.LADDER[0])
    check("mandatory NVDLA fence appears even when optional CLI fence is off",
          "SCOPE FENCE (nvdla, mandatory)" in prompt)

    mut_rel, mut_text, mut_desc = R.mutate(
        IPS["nvdla"], allowed, "nan_preproc_pd")
    pristine_nan = R.pristine_source("nvdla", allowed)
    check("NVDLA release mutation selects the live assignment, not a comment",
          mut_rel == allowed
          and "`datin_d`" in mut_desc
          and "assign nan_preproc_pd = ~(datin_d);" in mut_text
          and "//assign nan_preproc_pd = {datin_info" in mut_text
          and mut_text != pristine_nan)
    trace_tokens, trace_timeout = R._validated_trace_settings(
        R.NVDLA_TRACE_TESTS, R.NVDLA_TRACE_TIMEOUT_SEC)
    check("host single-trace revision is scope-matched and timeout-bounded",
          trace_tokens == ("pdp_1x1x1_3x3_ave_int8_0",)
          and trace_timeout == 4500
          and R._trace_family(allowed) == "pdp")
    raises_contract(
        "trace CLI value cannot inject a shell command",
        lambda: R._validated_trace_settings(
            "pdp_1x1x1_3x3_ave_int8_0; touch /tmp/pwned", 4500))
    raises_contract(
        "invalid per-trace timeout fails closed",
        lambda: R._validated_trace_settings("pdp_1x1x1_3x3_ave_int8_0", 0))

    reset_block = (
        " u_partition_o/u_sync_core_reset/"
        "sync_reset_synced_rstn/NV_GENERIC_CELL/_5_/D\n"
        "-5.0 slack (VIOLATED)\n")
    data_sync_block = (
        " u_partition_o/u_NV_NVDLA_cdp/u_dp/"
        "u_NV_NVDLA_CDP_DP_syncfifo/u_data_sync_fifo/_5_/D\n"
        "-4.0 slack (VIOLATED)\n")
    check("reset artifact excluded but ordinary data sync FIFO retained",
          D._excluded_timing_artifact("nvdla", reset_block)
          and not D._excluded_timing_artifact("nvdla", data_sync_block)
          and not D._excluded_timing_artifact("sha512", reset_block))
    sta_prompt = CTRL._sta_prompt_block("nvdla", "/unused")
    check("NVDLA prompt suppresses unsanitized raw reset-path STA feedback",
          "raw worst-path feedback suppressed" in sta_prompt
          and "Use the sanitized diagnosis" in sta_prompt)

    # Nested tmake paths must bind through the exact one-file scope.
    variant_dir = Path(tempfile.mkdtemp(prefix="nvdla_variant_"))
    try:
        (variant_dir / Path(allowed).name).write_text("module x; endmodule\n")
        scope = C.CampaignScope(
            ip="nvdla", editable_targets=(allowed,),
            verification_policy="gate+lec")
        mapped = candidate_from_dir("nvdla", variant_dir, scope)
        check("variant basename maps to exact scoped nested NVDLA path",
              tuple(mapped) == (allowed,))
        raises_contract(
            "tmake variant mapping refuses a missing explicit scope",
            lambda: candidate_from_dir("nvdla", variant_dir))
    finally:
        shutil.rmtree(variant_dir, ignore_errors=True)

    # ── candidate-survival tripwire with mock tmake ──────────────────────────
    base = Path(tempfile.mkdtemp(prefix="nvdla_buildout_"))
    try:
        make_tree(base)
        fake_spec = spec_for(base)
        fake_scope = C.CampaignScope(
            ip="fakenv", editable_targets=(TARGET,),
            verification_policy="gate(candidate-aware)+lec")
        C._reset_tmake_registry()
        C.register_tmake("fakenv", C.TmakeRegistration(
            layout=C.default_tmake_layout(fake_spec),
            bound_validation_digest=PROF.digest()))
        fake_ctr = C.get_contract(fake_spec)
        ws = FakeWs(fake_spec, base, fake_scope)
        run = runner_for(base)
        pristine = (base / TARGET).read_text()
        edit = pristine.replace("assign y = a;",
                                "assign y = a & 1'b1;")
        mrun = M.materialize_candidate(
            ws, fake_ctr, fake_scope, {TARGET: edit},
            runner=run, profile=PROF)
        check("mock tmake: source edit changes exactly its mapped generated file",
              mrun.ok and mrun.mat.changed == (GEN_TARGET,)
              and mrun.mat.h3_root != mrun.mat.h4_root)
        ok, _ = fake_ctr.regenerate(base, run)   # gate's own regeneration
        check("mock gate rebuild reproduces candidate and establishes H5",
              ok and M.post_gate(ws, fake_ctr, mrun,
                                 scope=fake_scope)
              and mrun.mat.h5_root == mrun.mat.h4_root)
        # A post-gate generated revert/tamper must never soft-pass.
        (base / GEN_TARGET).write_text("// reverted after gate\n")
        check("mock tripwire: post-gate generated mismatch fails closed",
              not M.post_gate(ws, fake_ctr, mrun, scope=fake_scope)
              and mrun.mat.classification == "flow-error")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    # ── release-packet decision logic without Docker ────────────────────────
    # The fake-tmake block reset the process-local sealed registry.
    registry.ensure_registered()
    orig = (R._nvdla_pristine_control, R._nvdla_negative_control,
            R._nvdla_pristine_manifest_control, R._image_digest)
    root = "a" * 64
    try:
        R._nvdla_pristine_control = lambda: {
            "gate_status": "PASS", "lec_status": "PROVEN",
            "tripwire_ok": True, "pristine_generated_root": root}
        R._nvdla_negative_control = lambda rel, text: {
            "gate_status": "FAIL", "lec_status": "INCONCLUSIVE",
            "tripwire_ok": True, "changed_generated": ["mapped.v"]}
        R._nvdla_pristine_manifest_control = lambda: {
            "ok": True, "generated_root": root}
        R._image_digest = lambda: "sha256:" + "b" * 64
        packet = R._run_nvdla(None, None)
        check("NVDLA release requires all six controls and labels dualsim skip",
              packet["released"] and all(packet["checks"].values())
              and "dualsim SKIP(size)" in packet["assurance_policy"]
              and packet["trace_selection"]["prefixes"]
                  == ["pdp_1x1x1_3x3_ave_int8_0"]
              and packet["trace_selection"]["per_trace_timeout_s"] == 4500
              and packet["campaign_status"].endswith(
                  "PENDING_REVIEW_AND_PROFILE_BINDING"))
        R._nvdla_pristine_manifest_control = lambda: {
            "ok": True, "generated_root": "c" * 64}
        refused = R._run_nvdla(None, None)
        check("NVDLA release fails closed on 2x determinism mismatch",
              not refused["released"]
              and not refused["checks"]["6_pristine_determinism_2x"])
    finally:
        (R._nvdla_pristine_control, R._nvdla_negative_control,
         R._nvdla_pristine_manifest_control, R._image_digest) = orig

    log_tmp = Path(tempfile.mkdtemp(prefix="nvdla_release_logs_"))
    try:
        log_packet = {"positive": {"_raw_log": "full evidence\n"}}
        R._persist_raw_logs(log_packet, log_tmp, "packet")
        ref = log_packet["positive"]["_raw_log"]
        check("release raw logs are externalized with digest/size/path",
              ref["sha256"] == C._sha256(b"full evidence\n")
              and ref["bytes"] == len(b"full evidence\n")
              and Path(ref["path"]).read_text() == "full evidence\n")
    finally:
        shutil.rmtree(log_tmp, ignore_errors=True)

    print(f"\ntest_nvdla_buildout: {PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
