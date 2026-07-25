"""Campaign release-control runner (HOST/Docker only).

Produces the 6-item real-tool release packet Codex requires per IP before a
legacy campaign (NVIDIA_P04_SCOPING_REVIEW.md SS6.2):

  1. pristine gate POSITIVE   -> GATE: PASS, underlying rc 0, tests > 0
  2. functional gate NEGATIVE -> GATE: FAIL (wrapper nonzero)
  3. LEC-v2 pristine POSITIVE -> PROVEN, rc 0, total>0, proven==total, unproven==0
  4. LEC-v2 functional NEGATIVE -> anything other than PROVEN (same mutation as #2)
  5. identity/provenance      -> image digest, commands, mutation diff+digest,
                                 rcs, counts, raw logs, timestamps
  6. restoration check        -> contest/submission trees unchanged after

Legacy IPs reuse verify.tb_gate / verify.lec / Workspace. NVDLA uses its
accepted tmake SourceContract: pristine/candidate regeneration, H3/H4/H5
tripwires, the organizer trace suite, and the same pinned LEC-v2 parser. It is
FAIL-SAFE: if any positive is not PASS/PROVEN, any negative does not fire, a
tripwire changes, or the two pristine manifests differ, the IP is marked
NOT-RELEASED.

The negative-control mutation inverts the RHS of one `assign <output> = ...;`
in an editable source that BOTH the gate and LEC consume (for dual-rep IPs
that means an sv_source, so regeneration propagates to the Verilator gate and
the generated .v). Non-equivalent by construction, still compiles. Override
with --mut-file / --mut-signal when the auto-pick does not fire.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

from . import contract as C
from . import gate as G
from . import materialize as M
from . import verify as V
from .config import IPS, IMAGE, REPO
from .discover import get_spec, register
from .proposer import fence_violation
from .workspace import Workspace, pristine_source

EVIDENCE = Path("/private/tmp/nvdla_release_evidence")
NVDLA_DEFAULT_MUTATION = \
    "NVDLA/vmod/nvdla/pdp/NV_NVDLA_PDP_nan.v"

# 2026-07-24 host revision (Codex handoff Addendum 1, user-approved): the gate
# phase runs a SCOPE-MATCHED TRACE SUBSET instead of the full suite. Rationale
# (host-measured): each trace is a whole-design cycle-accurate sim, ~59 min for
# a mid-size pdp trace; the full suite is 85 traces -> ~30 h/packet as
# previously configured, infeasible. The tiered-gating policy: the in-packet /
# in-loop gate needs a trace that EXERCISES the mutated unit (the negative
# control's purpose); suite BREADTH belongs to banking-time validation of the
# one finalist; LEC-v2 PROVEN remains the equivalence authority throughout.
# Default = the smallest PDP trace (1x1x1 cube, ~2000x less data than the
# 59-min trace) matching the default PDP-leaf mutation. The organizer runner
# natively supports these env overrides (TEST_PREFIXES / TEST_TIMEOUT_SEC) —
# no organizer files are modified. CLI: --trace-tests / --trace-timeout.
NVDLA_TRACE_TESTS = "pdp_1x1x1_3x3_ave_int8_0"
NVDLA_TRACE_TIMEOUT_SEC = 4500
_TRACE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def _validated_trace_settings(
        tests: str, timeout: int) -> tuple[tuple[str, ...], int]:
    """Validate the organizer-runner environment values before interpolation.

    TEST_PREFIXES is a space-separated prefix list, not a shell fragment.
    Direct callers and the CLI share this guard.
    """
    if not isinstance(tests, str):
        raise C.ContractError("NVDLA trace selection must be a string")
    tokens = tuple(tests.split())
    if not tokens or any(not _TRACE_TOKEN.fullmatch(t) for t in tokens):
        raise C.ContractError(
            "NVDLA trace selection must contain only space-separated "
            "[A-Za-z0-9_.-] prefixes")
    if (not isinstance(timeout, int) or isinstance(timeout, bool)
            or not 1 <= timeout <= 21600):
        raise C.ContractError(
            "NVDLA per-trace timeout must be an integer in [1, 21600]")
    return tokens, timeout


def _trace_family(rel: str) -> str:
    """Editable partition name used by the organizer trace prefixes."""
    marker = "NVDLA/vmod/nvdla/"
    if not rel.startswith(marker):
        raise C.ContractError(f"NVDLA mutation path outside vmod/nvdla: {rel}")
    family = rel[len(marker):].split("/", 1)[0].lower()
    if not _TRACE_TOKEN.fullmatch(family):
        raise C.ContractError(f"invalid NVDLA mutation partition {family!r}")
    return family


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _image_digest() -> str:
    r = subprocess.run(["docker", "image", "inspect", IMAGE, "--format",
                        "{{.Id}}"], capture_output=True, text=True)
    return (r.stdout or "").strip() or "unknown"


def _editable_targets(spec) -> list[str]:
    """Sources both the gate and LEC see. Dual-rep IPs -> sv_sources (a
    generated-.v-only edit would be gate-blind); direct IPs -> spec.sources;
    NVDLA -> one known trace-exercised PDP leaf unless the host supplies an
    explicit --mut-file."""
    ctr = C.get_contract(spec)
    if ctr.name == "tmake":
        return [NVDLA_DEFAULT_MUTATION]
    return list(spec.sv_sources) if spec.sv_sources else list(spec.sources)


# signal-name heuristics (2026-07-23): a KAT/data-checking TB only fires the
# negative gate when the mutation corrupts the CHECKED DATAPATH. Status flags
# (idle/ready/valid/ack/alert/...) are often unchecked, so the mutant still
# passes the gate (the ascon idle_o lesson). Prefer datapath outputs; penalize
# status-flag names. The explicit --mut-signal override always wins.
_STATUS_FLAG = re.compile(
    r"(idle|ready|valid|ack|alert|busy|done|err|error|irq|req|stall|"
    r"empty|full|wait|active|enable|_en|grant|intr)", re.I)
_DATAPATH = re.compile(
    r"(data|out|state|result|digest|hash|crc|cipher|sbox|round|mac|tag|"
    r"read_data|_o\b|_out|_q\b|sum|prod|acc|mix|perm)", re.I)


def _signal_score(name: str) -> int:
    s = 0
    if _DATAPATH.search(name):
        s += 2
    if _STATUS_FLAG.search(name):
        s -= 3
    if re.search(r"unused|tieoff|tie_off|_nc\b|no_connect|spurious", name, re.I):
        s -= 5                       # tie-off signals are LEC/gate no-ops
    return s


def _comments_to_space(text: str) -> str:
    """Remove comments while preserving every character offset/newline."""
    def blank(m):
        return "".join("\n" if ch == "\n" else " " for ch in m.group(0))
    text = re.sub(r"/\*.*?\*/", blank, text, flags=re.S)
    return re.sub(r"//[^\n]*", blank, text)


def mutate(spec, mut_file: str | None, mut_signal: str | None
           ) -> tuple[str, str, str]:
    """Return (rel, mutated_text, description). Inverts the RHS of one
    `assign <output> = <expr>;`, preferring a DATAPATH output over a status
    flag so a KAT/data TB actually catches the mutation. Raises if no suitable
    site is found."""
    targets = ([mut_file] if mut_file else _editable_targets(spec))
    ctr = C.get_contract(spec)
    if ctr.name == "tmake":
        for rel in targets:
            # The release negative is itself subject to the production fence.
            # A reset/CDC/bus mutation would not establish release for the
            # permitted first-campaign domain.
            if not ctr.is_editable(rel):
                raise C.ContractError(
                    f"NVDLA release mutation outside editable universe: {rel}")
            fv = fence_violation(spec.name, {rel: ""})
            if fv:
                raise C.ContractError(fv)
    out_re = re.compile(r"\boutput\b[^;]*?\b(\w+)\s*[,;)]")
    best = None                      # (score, rel, mutated, desc)
    for rel in targets:
        text = pristine_source(spec.name, rel)
        active = _comments_to_space(text)
        outputs = (set(out_re.findall(active))
                   if not mut_signal else {mut_signal})
        for m in re.finditer(
                r"(assign\s+(\w+)\s*=\s*)([^;]+)(;)", active):
            lhs = m.group(2)
            if lhs not in outputs:
                continue
            score = 100 if mut_signal else _signal_score(lhs)
            prefix = text[m.start(1):m.end(1)]
            rhs = text[m.start(3):m.end(3)]
            suffix = text[m.start(4):m.end(4)]
            mutated = (text[:m.start()] + prefix + "~(" + rhs
                       + ")" + suffix + text[m.end():])
            kind = ("datapath" if _DATAPATH.search(lhs)
                    else "status-flag" if _STATUS_FLAG.search(lhs) else "other")
            desc = (f"invert assign {lhs} [{kind}] in {rel}: "
                    f"`{rhs.strip()[:40]}` -> ~(...)")
            if best is None or score > best[0]:
                best = (score, rel, mutated, desc)
    if best is None:
        raise RuntimeError(
            f"no `assign <output> = ...;` site found in {targets}; pass "
            f"--mut-file/--mut-signal explicitly")
    if best[0] < 0:
        print(f"[{spec.name}] WARNING: best auto-mutation is a status flag "
              f"(may not fire the KAT negative gate); consider --mut-signal a "
              f"datapath output")
    return best[1], best[2], best[3]


def _gate_lec(ip: str, cand_files: dict | None, tag: str) -> dict:
    ws = Workspace.create(ip, cand_files, tag=tag)
    try:
        gate_status, gate_detail = V.tb_gate(ws)
        lec_status, lec_note = V.lec(ws)
        return {"gate_status": gate_status, "gate_detail": gate_detail[-1500:],
                "lec_status": lec_status, "lec_note": lec_note}
    finally:
        ws.destroy()


def _phase(ws: Workspace, name: str, cmd: str, timeout: int) -> dict:
    """Run one NVDLA release phase with raw, hash-bound evidence."""
    try:
        r = ws.run(cmd, timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        return {"name": name, "cmd": cmd, "rc": r.returncode,
                "log_sha": _sha(out), "log_tail": out[-1500:],
                "_raw_log": out}
    except subprocess.TimeoutExpired:
        out = f"TIMEOUT after {timeout}s"
        return {"name": name, "cmd": cmd, "rc": None,
                "log_sha": _sha(out), "log_tail": out,
                "_raw_log": out}


def _proof_record(pr, out: str, script: str) -> dict:
    return {
        "lec_status": V._VERDICT_TO_STATUS[pr.verdict],
        "lec_note": (f"recipe={pr.recipe_id} rc={pr.rc} total={pr.total} "
                     f"proven={pr.proven} unproven={pr.unproven} "
                     f"reason={pr.reason}"),
        "proof": {
            "verdict": pr.verdict, "reason": pr.reason, "rc": pr.rc,
            "total": pr.total, "proven": pr.proven,
            "unproven": pr.unproven, "recipe": pr.recipe_id,
            "script_sha": _sha(script), "log_sha": _sha(out),
            "_raw_log": out,
        },
    }


def _run_nvdla_gate(ws: Workspace, ctr: C.TmakeContract, golden,
                    expected_generated_root: str, *,
                    mrun: "M.MaterializationRun | None" = None) -> dict:
    """Run the real NVDLA clean-build trace gate and its H5 tripwire.

    A functional negative is allowed to return a nonzero test rc; generated,
    editable, immutable, and golden state are still audited and post_gate()
    still establishes H5 so the same mutant can run LEC.
    """
    phases = []
    try:
        trace_tokens, trace_timeout = _validated_trace_settings(
            NVDLA_TRACE_TESTS, NVDLA_TRACE_TIMEOUT_SEC)
    except C.ContractError as e:
        return {"gate_status": "FLOW_ERROR", "gate_detail": str(e),
                "candidate_aware": False, "tripwire_ok": False,
                "phases": phases}
    imm0 = M.immutable_manifest(ws.root, ctr)
    editable = (mrun.mat.h2 if mrun is not None else {})
    edit0 = {rel: C._hash_file(ws.root / rel) for rel in editable}

    def audit_state() -> tuple[bool, str, str]:
        """Audit mutation classes after every gate exit, including failure."""
        reasons = []
        actual_root = ""
        try:
            if M.immutable_manifest(ws.root, ctr) != imm0:
                reasons.append("immutable dependency changed")
            if {rel: C._hash_file(ws.root / rel)
                    for rel in editable} != edit0:
                reasons.append("editable source changed")
            if not ctr.verify_golden(ws.root, golden):
                reasons.append("golden snapshot changed")
            actual_root = C.manifest_root(ctr.fingerprint(ws.root))
            if actual_root != expected_generated_root:
                reasons.append("generated manifest differs from candidate")
        except (C.ContractError, OSError) as e:
            reasons.append(f"state audit error: {e}")
        return not reasons, "; ".join(reasons), actual_root

    def flow_error(detail: str) -> dict:
        audit_ok, audit_note, actual_root = audit_state()
        if audit_note:
            detail = f"{detail}; mutation audit: {audit_note}"
        return {
            "gate_status": "FLOW_ERROR", "gate_detail": detail,
            "candidate_aware": False, "tripwire_ok": False,
            "mutation_audit_ok": audit_ok,
            "expected_generated_root": expected_generated_root,
            "actual_generated_root": actual_root,
            "phases": phases,
        }

    # A copied stale simulator must not satisfy the positive control.
    try:
        G._validated_clean(
            ws.root, ctr, ("NVDLA/outdir/nv_small/verilator",))
    except C.ContractError as e:
        return flow_error(str(e))

    regen_cmd = (f"cd {ctr.layout.generator_cwd} && "
                 f"{ctr.layout.generator_cmd}")
    phases.append(_phase(ws, "REGENERATE", regen_cmd, 900))
    if phases[-1]["rc"] != 0:
        return flow_error("gate regeneration failed/timeout")

    try:
        regenerated_root = C.manifest_root(ctr.fingerprint(ws.root))
    except C.ContractError as e:
        return flow_error(str(e))
    if regenerated_root != expected_generated_root:
        return flow_error(
            "gate regeneration did not reproduce the candidate-generated "
            "manifest")

    phases.append(_phase(
        ws, "BUILD",
        "cd NVDLA && ./tools/bin/tmake -build verilator", 7200))
    if phases[-1]["rc"] != 0:
        return flow_error("Verilator clean build failed/timeout")

    phases.append(_phase(
        ws, "TRACE_TESTS",
        "cd NVDLA/verif/verilator && "
        f"TEST_PREFIXES={shlex.quote(' '.join(trace_tokens))} "
        f"TEST_TIMEOUT_SEC={trace_timeout} "
        "./run_all_trace_tests.sh", 21600))
    test_phase = phases[-1]
    tp, tf, parse_note = G.parse_test_results(test_phase["_raw_log"])

    state_ok, audit_note, _ = audit_state()
    if audit_note:
        parse_note = f"{parse_note}; state audit: {audit_note}".strip("; ")
    if mrun is not None and state_ok:
        state_ok = M.post_gate(ws, ctr, mrun, scope=ws.scope)

    if not state_ok:
        status = "FLOW_ERROR"
        detail = parse_note or "post-gate H5/golden/mutation-class audit failed"
    elif parse_note or tp + tf == 0:
        status = "FLOW_ERROR"
        detail = parse_note or "trace gate executed/reported zero tests"
    elif test_phase["rc"] == 0 and tp > 0 and tf == 0:
        status, detail = "PASS", ""
    elif tf > 0:
        status = "FAIL"
        detail = f"trace tests rc={test_phase['rc']} pass={tp} fail={tf}"
    else:
        status = "FLOW_ERROR"
        detail = (f"trace runner rc={test_phase['rc']} without a counted "
                  "functional failure")
    return {
        "gate_status": status, "gate_detail": detail,
        "candidate_aware": state_ok and (tp + tf > 0),
        "tripwire_ok": state_ok,
        "mutation_audit_ok": state_ok,
        "tests_passed": tp, "tests_failed": tf,
        "expected_generated_root": expected_generated_root,
        "actual_generated_root": (
            C.manifest_root(ctr.fingerprint(ws.root)) if state_ok else ""),
        "phases": phases,
    }


def _nvdla_pristine_control() -> dict:
    spec = IPS["nvdla"]
    ctr = C.get_contract(spec)
    ws = Workspace.create("nvdla", tag="rel_pos_nvdla")
    try:
        ok, regen_log = ctr.regenerate(ws.root, ws.run)
        if not ok:
            return {"gate_status": "FLOW_ERROR",
                    "gate_detail": "pristine regeneration failed",
                    "lec_status": "ERROR",
                    "tripwire_ok": False,
                    "_raw_regen_log": regen_log}
        golden = ctr.snapshot_golden(ws.root)
        h3_root = C.manifest_root(ctr.fingerprint(ws.root))
        gate = _run_nvdla_gate(
            ws, ctr, golden, expected_generated_root=h3_root)
        out = {**gate, "pristine_generated_root": h3_root,
               "_raw_regen_log": regen_log}
        if gate["tripwire_ok"]:
            gi = ctr.design_inputs(ws.root, "golden")
            ci = ctr.design_inputs(ws.root, "candidate")
            script = V.lec_v2_script(gi, ci, spec.top)
            pr, lec_log = V.run_lec_v2_script(
                ws, script, timeout=V._lec_timeout(spec))
            out.update(_proof_record(pr, lec_log, script))
        else:
            out.update({"lec_status": "ERROR",
                        "lec_note": "LEC refused: pristine gate tripwire failed"})
        return out
    finally:
        ws.destroy()


def _nvdla_negative_control(rel: str, mutated: str) -> dict:
    spec = IPS["nvdla"]
    ctr = C.get_contract(spec)
    scope = C.CampaignScope(
        ip="nvdla", editable_targets=(rel,),
        verification_policy="gate(candidate-aware,trace)+lec-v2;dualsim-skip-size",
        requested_workers=1, max_changed_files=1)
    ws = Workspace.create("nvdla", tag="rel_neg_nvdla", scope=scope)
    try:
        mrun = M.materialize_candidate(
            ws, ctr, scope, {rel: mutated}, runner=ws.run)
        if not mrun.ok:
            return {"gate_status": "FLOW_ERROR",
                    "gate_detail": mrun.mat.detail, "lec_status": "ERROR",
                    "tripwire_ok": False,
                    "materialization": mrun.mat.classification,
                    "_raw_regen_log": mrun.regen_log}
        expected = ctr.source_to_generated(rel)
        changed = set(mrun.mat.changed)
        mapped_changed = (
            len(expected) == 1 and set(expected) == changed
            and mrun.mat.h3_root != mrun.mat.h4_root)
        if not mapped_changed:
            return {
                "gate_status": "FLOW_ERROR",
                "gate_detail": "candidate-survival tripwire: mapped generated "
                               f"change mismatch changed={sorted(changed)} "
                               f"expected={list(expected)}",
                "lec_status": "ERROR", "tripwire_ok": False,
                "materialization": mrun.mat.classification,
                "_raw_regen_log": mrun.regen_log,
            }
        gate = _run_nvdla_gate(
            ws, ctr, mrun.golden,
            expected_generated_root=mrun.mat.h4_root, mrun=mrun)
        out = {
            **gate, "materialization": mrun.mat.classification,
            "changed_generated": sorted(changed),
            "pre_gate_generated_root": mrun.mat.h4_root,
            "_raw_regen_log": mrun.regen_log,
        }
        if gate["tripwire_ok"] and mrun.receipt is not None:
            gi = M.golden_inputs(ws, ctr, mrun)
            ci = M.effective_inputs(ws, ctr, mrun)
            script = V.lec_v2_script(gi, ci, spec.top)
            pr, lec_log = V.run_lec_v2_script(
                ws, script, timeout=V._lec_timeout(spec))
            out.update(_proof_record(pr, lec_log, script))
        else:
            out.update({"lec_status": "ERROR",
                        "lec_note": "LEC refused: candidate tripwire failed"})
        return out
    finally:
        ws.destroy()


def _nvdla_pristine_manifest_control() -> dict:
    """Second clean pristine materialization for the release determinism pair."""
    ctr = C.get_contract(IPS["nvdla"])
    ws = Workspace.create("nvdla", tag="rel_det_nvdla")
    try:
        ok, log = ctr.regenerate(ws.root, ws.run)
        root = C.manifest_root(ctr.fingerprint(ws.root)) if ok else ""
        return {"ok": ok, "generated_root": root,
                "log_sha": _sha(log), "_raw_log": log}
    except C.ContractError as e:
        return {"ok": False, "generated_root": "", "detail": str(e),
                "log_sha": _sha(str(e)), "_raw_log": str(e)}
    finally:
        ws.destroy()


def _run_nvdla(mut_file: str | None, mut_signal: str | None) -> dict:
    spec = IPS["nvdla"]
    rel, mutated, mut_desc = mutate(spec, mut_file, mut_signal)
    pristine = pristine_source("nvdla", rel)
    trace_tokens, trace_timeout = _validated_trace_settings(
        NVDLA_TRACE_TESTS, NVDLA_TRACE_TIMEOUT_SEC)
    family = _trace_family(rel)
    if not any(t.lower().startswith(family + "_") for t in trace_tokens):
        raise C.ContractError(
            f"NVDLA trace selection {trace_tokens} does not exercise the "
            f"mutated {family!r} partition")

    print("[nvdla] positive controls (pristine trace gate + whole LEC-v2)...")
    pos = _nvdla_pristine_control()
    print(f"[nvdla]   gate={pos['gate_status']} "
          f"lec={pos.get('lec_status')}")
    print(f"[nvdla] negative controls ({mut_desc})...")
    neg = _nvdla_negative_control(rel, mutated)
    print(f"[nvdla]   gate={neg['gate_status']} "
          f"lec={neg.get('lec_status')}")
    print("[nvdla] second pristine materialization (determinism)...")
    det = _nvdla_pristine_manifest_control()

    checks = {
        "1_gate_positive_PASS": pos["gate_status"] == "PASS",
        "2_gate_negative_FAIL": neg["gate_status"] == "FAIL",
        "3_lec_positive_PROVEN": pos.get("lec_status") == "PROVEN",
        "4_lec_negative_not_PROVEN": (
            neg.get("lec_status") not in (None, "PROVEN")),
        "5_candidate_survival_tripwire": bool(
            pos.get("tripwire_ok") and neg.get("tripwire_ok")
            and neg.get("changed_generated")),
        "6_pristine_determinism_2x": bool(
            det.get("ok") and det.get("generated_root")
            == pos.get("pristine_generated_root")),
    }
    released = all(checks.values())
    return {
        "ip": "nvdla", "released": released,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "image_digest": _image_digest(),
        "lec_recipe": C.LEC_RECIPE_CONTRACT_V2,
        "assurance_policy":
            "organizer trace gate candidate-aware + whole-design LEC-v2 "
            "PROVEN; generic dualsim SKIP(size)",
        "trace_selection": {
            "prefixes": list(trace_tokens),
            "per_trace_timeout_s": trace_timeout,
            "mutation_partition": family,
            "tier": "scope-matched candidate/release control",
        },
        "campaign_status": (
            "RELEASE_PACKET_GREEN_PENDING_REVIEW_AND_PROFILE_BINDING"
            if released else "NO_GO"),
        "mutation": {"rel": rel, "desc": mut_desc,
                     "pristine_sha": _sha(pristine),
                     "mutated_sha": _sha(mutated)},
        "positive": pos, "negative": neg,
        "determinism_run2": det, "checks": checks,
        "6_restoration": "controls ran in disposable Workspace scratch dirs; "
                         "contest/submission trees not touched",
    }


def run_ip(ip: str, mut_file: str | None, mut_signal: str | None) -> dict:
    if ip == "nvdla":
        from . import registry
        registry.ensure_registered()
        return _run_nvdla(mut_file, mut_signal)
    if ip not in IPS:
        register(get_spec(ip))
    spec = IPS[ip]
    rel, mutated, mut_desc = mutate(spec, mut_file, mut_signal)
    pristine = pristine_source(spec.name, rel)

    print(f"[{ip}] positive controls (pristine gate + LEC)...")
    pos = _gate_lec(ip, None, f"rel_pos_{ip}")
    print(f"[{ip}]   gate={pos['gate_status']} lec={pos['lec_status']}")
    print(f"[{ip}] negative controls ({mut_desc})...")
    neg = _gate_lec(ip, {rel: mutated}, f"rel_neg_{ip}")
    print(f"[{ip}]   gate={neg['gate_status']} lec={neg['lec_status']}")

    from . import contract as C
    lec_recipe = C.LEC_RECIPE_CONTRACT_V2
    pos_ok = (pos["gate_status"] == "PASS" and pos["lec_status"] == "PROVEN")
    neg_gate_fires = neg["gate_status"] == "FAIL"
    neg_lec_fires = neg["lec_status"] != "PROVEN"
    released = pos_ok and neg_gate_fires and neg_lec_fires

    packet = {
        "ip": ip, "released": released,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "image_digest": _image_digest(),
        "lec_recipe": lec_recipe,
        "mutation": {"rel": rel, "desc": mut_desc,
                     "pristine_sha": _sha(pristine),
                     "mutated_sha": _sha(mutated)},
        "positive": pos, "negative": neg,
        "checks": {
            "1_gate_positive_PASS": pos["gate_status"] == "PASS",
            "2_gate_negative_FAIL": neg_gate_fires,
            "3_lec_positive_PROVEN": pos["lec_status"] == "PROVEN",
            "4_lec_negative_not_PROVEN": neg_lec_fires,
        },
        # 6: verify.py uses disposable Workspace scratch dirs and never writes
        # REPO/submission; restoration is structural (no in-place edits)
        "6_restoration": "controls ran in disposable Workspace scratch dirs; "
                         "contest/submission trees not touched",
    }
    return packet


def _persist_raw_logs(packet: dict, directory: Path, stem: str) -> None:
    """Externalize every `_raw*` value and replace it with a hash-bound ref."""
    counter = 0

    def walk(obj, trail):
        nonlocal counter
        if isinstance(obj, dict):
            for key in list(obj):
                value = obj[key]
                if key.startswith("_raw") and isinstance(value, str):
                    counter += 1
                    label = "_".join(
                        re.sub(r"[^A-Za-z0-9_.-]", "_", str(p))
                        for p in (*trail, key))
                    p = directory / f"{stem}_{counter:02d}_{label}.log"
                    p.write_text(value)
                    obj[key] = {
                        "path": str(p), "sha256": _sha(value),
                        "bytes": len(value.encode()),
                    }
                else:
                    walk(value, (*trail, key))
        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                walk(value, (*trail, i))

    walk(packet, ())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="campaign release controls")
    ap.add_argument("--ip", required=True,
                    help="aes|prim|sha512|ascon|nvdla (NOT kmac)")
    ap.add_argument("--mut-file", help="explicit editable source to mutate")
    ap.add_argument("--mut-signal", help="explicit output signal to invert")
    ap.add_argument("--trace-tests",
                    help="NVDLA only: space-separated trace-test name prefixes "
                         "for the gate phase (default: the smallest PDP trace; "
                         "MUST exercise the mutated unit)")
    ap.add_argument("--trace-timeout", type=int,
                    help="NVDLA only: per-trace wall seconds "
                         f"(default {NVDLA_TRACE_TIMEOUT_SEC})")
    a = ap.parse_args(argv)
    if a.ip != "nvdla" and (
            a.trace_tests is not None or a.trace_timeout is not None):
        ap.error("--trace-tests/--trace-timeout are NVDLA-only")
    if a.ip == "nvdla":
        tests = (a.trace_tests if a.trace_tests is not None
                 else NVDLA_TRACE_TESTS)
        timeout = (a.trace_timeout if a.trace_timeout is not None
                   else NVDLA_TRACE_TIMEOUT_SEC)
        try:
            tokens, timeout = _validated_trace_settings(tests, timeout)
        except C.ContractError as e:
            ap.error(str(e))
        globals()["NVDLA_TRACE_TESTS"] = " ".join(tokens)
        globals()["NVDLA_TRACE_TIMEOUT_SEC"] = timeout
    if a.ip == "kmac":
        print("REFUSED: kmac has no eligible whole-design LEC path")
        return 2

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    packet = run_ip(a.ip, a.mut_file, a.mut_signal)
    stamp = time.strftime("%m%d_%H%M%S")
    _persist_raw_logs(packet, EVIDENCE, f"release_{a.ip}_{stamp}")
    out = EVIDENCE / f"release_{a.ip}_{stamp}.json"
    out.write_text(json.dumps(packet, indent=2))

    print(f"\n=== {a.ip} release packet ===")
    for k, v in packet["checks"].items():
        print(f"  {'OK ' if v else 'XX '} {k}: {v}")
    print(f"  RELEASED: {packet['released']}")
    print(f"  packet -> {out}")
    if not packet["released"]:
        print(f"\n{a.ip} is NOT RELEASED - do NOT campaign it. Bring the "
              f"packet back for diagnosis (a negative control may not have "
              f"fired; try --mut-file/--mut-signal).")
        return 1
    print(f"\n{a.ip} RELEASED for a bounded scratch campaign (runbook SS3).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
