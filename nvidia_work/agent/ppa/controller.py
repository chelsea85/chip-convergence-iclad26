"""Main optimization loop: budget-aware, pool-based, plateau-controlled.

Per round:
  1. budget regime (BATS 70/30/10) sets this round's candidate count k
  2. Thompson-select a parent state from the pool (AB-MCTS wider/deeper)
  3. pick k distinct strategy-ladder rungs biased by the STA root-cause tag
     and objective weights; build k prompts; k model calls
  4. evaluate candidates in parallel (lint/compile/gate -> proxy -> synth+STA
     -> LEC+dualsim); acceptance = objective.better() vs the parent
  5. accepted states join the pool + Pareto frontier; rewards back up the tree
  6. plateau controller: stop when the frontier's best ADP hasn't improved
     >=2% in the last 3 rounds (Alpha-RTL / EFC stop rule)

Everything is logged: per-candidate records via evaluate's ledger, per-round
records in ledger/<ip>_rounds.jsonl (the raw material for GEPA/ACE offline
passes).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import IPS, LEDGER_DIR, REPO, NVWORK, AGENT
from .emit import staged_replace
from .workspace import Workspace, pristine_source
from . import evaluate as E
from . import skills
from . import sta_feedback as S
from .objective import Objective, ParetoFrontier
from .pool import DesignPool
from .proposer import (Model, PromptContext, build_prompt, build_reflect_prompt,
                       build_repair_prompt, build_gatefail_repair_prompt,
                       make_model, parse_reflection, parse_response,
                       pick_strategies, fence_violation, cdc_ff_violation,
                       FENCE, LADDER)

# Tag -> preferred rung order, v2 per the Codex expanded literature review
# (`NVIDIA_TIMING_STRATEGY_EXPANDED_LITERATURE_REVIEW.md` §8.1/§14).
# balanced-tree / carry-save are DEMOTED from early selection (kmac evidence:
# ABC re-balances source-level re-association away; see playbook
# R-abc-rebalance-caution) — they remain in LADDER only as pick_strategies
# fallback. arith-carry-chain also carries xor-depth-resynthesize as a BRIDGE:
# the current classifier's xor+carry rule mislabels XOR-heavy crypto cones as
# carry chains (kmac path mix was 40% XOR), until a dedicated
# xor-linear-network tag lands in diagnose.py (sandbox follow-up).
_TAG_TO_RUNGS = {
    "arith-carry-chain": ["sum-cluster-expose", "xor-depth-resynthesize",
                          "late-input-cofactor"],
    # xor-linear-network: new classifier tag (sta_feedback.classify split,
    # Codex §3.6) — GF(2) linear layers get the XOR rung first, then the
    # audited small-cone templates; adder strategies are inert here.
    "xor-linear-network": ["xor-depth-resynthesize",
                           "small-cone-arrival-template",
                           "late-input-cofactor"],
    "mux-select": ["late-input-cofactor", "priority-prefix-select",
                   "restructure-select"],
    "wide-gate-decode": ["compare-decode-prefix", "priority-prefix-select",
                         "restructure-select"],
    "control-boolean-network": ["late-input-cofactor",
                                "compare-decode-prefix",
                                "small-cone-arrival-template"],
    "mixed-comb-depth": ["sum-cluster-expose", "late-input-cofactor",
                         "micro-opt"],
}

# Safety net for UNKNOWN tags on timing-violated designs (hidden testcases):
# interleaved into `preferred` by _timing_biased. Order = the review's
# expected-value ranking of the broadly-applicable approved rungs.
_TIMING_RUNGS = ["sum-cluster-expose", "late-input-cofactor",
                 "compare-decode-prefix"]


def _sta_prompt_block(ip: str, reports_dir: str | Path) -> str:
    """Return model-facing flat STA feedback.

    NVDLA's generic report is headed by the host-confirmed reset-distribution
    artifact. Its diagnosis path independently ranks non-reset paths (and
    falls back to area), so exposing the generic block would undo that
    sanitization at the prompt boundary.
    """
    if ip == "nvdla":
        return ("NVDLA raw worst-path feedback suppressed: reset/CDC "
                "distribution paths are excluded. Use the sanitized "
                "diagnosis and area ranking above.")
    return S.feedback(reports_dir, top_k=3)


def _timing_biased(preferred: list, setup) -> list:
    """WNS-aware rung bias (2026-07-23): when the baseline VIOLATES timing
    (setup < 0), interleave _TIMING_RUNGS with the tag-preferred rungs
    (tag0, T0, tag1, T1, ...) so every best-of-k batch carries at least one
    late-arrival/fanout move alongside the historically-proven tag rungs.
    Timing-met designs are returned unchanged. Search-side only — no gate or
    acceptance change."""
    if (setup or 0) >= 0:
        return list(preferred)
    merged, t = [], list(_TIMING_RUNGS)
    for p in preferred:
        if p not in merged:
            merged.append(p)
        if t:
            nxt = t.pop(0)
            if nxt not in merged:
                merged.append(nxt)
    merged += [x for x in t if x not in merged]
    return merged


# High-delta rungs = the approved literature-backed template strategies
# (Codex expanded review §10) — the only ones admitted at severe violation.
_HIGH_DELTA = {"sum-cluster-expose", "xor-depth-resynthesize",
               "late-input-cofactor", "priority-prefix-select",
               "compare-decode-prefix", "small-cone-arrival-template"}


def _risk_gated(preferred: list, setup, period_ps) -> list:
    """rho-normalized risk gate (Codex expanded review §8.3):
    rho = max(0, -WNS) / clock_period.
      rho < 0.05 (met/near-met): no duplication-class rungs — drop
        late-input-cofactor; favor clustering/width/template moves.
      0.05 <= rho <= 1.0: the full interleaved set.
      rho > 1.0 (severe, e.g. ascon's unmeetable 10 GHz SDC): only
        high-delta template rungs; generic micro-edit repetition is cut.
    WNS controls risk appetite; the structure tag controls applicability
    (§8.2) — this gate never ADDS a rung the tag didn't justify."""
    out = _timing_biased(preferred, setup)
    rho = (max(0.0, -(setup or 0.0)) / period_ps) if period_ps else 0.0
    if rho < 0.05:
        out = [r for r in out if r != "late-input-cofactor"]
    elif rho > 1.0:
        out = [r for r in out if r in _HIGH_DELTA]
    return out

_SDC_PERIODS = {"sha512": 1500.0, "async_fifo": 300.0,
                "ascon": 100.0}   # setup-critical clock (ascon: 10GHz, unmeetable)


def _sdc_period(ip: str) -> float | None:
    """Clock period (ps) from the IP's own SDC (`set clk_period N` /
    `set <name>_period N`). Without it, slack can't convert to delay and
    ADP is unreportable (2026-07-14: prim's real ADP was 0.60 but printed
    as 1.0 because the hand map lacked prim). Hand map = fallback."""
    spec = IPS[ip]
    syn = REPO / spec.syn_dir
    cands = (sorted(syn.glob(f"*{spec.top}*constraint*.sdc"))
             or sorted(syn.glob("constraint.sdc")) or sorted(syn.glob("*.sdc")))
    for f in cands:
        try:
            m = re.search(r"set\s+\w*_?period\s+(\d+(?:\.\d+)?)", f.read_text())
        except OSError:
            continue
        if m:
            return float(m.group(1))
    return _SDC_PERIODS.get(ip)


def _dossier(ip: str, sources: tuple[str, ...] | list[str] | None = None
             ) -> str:
    spec = IPS[ip]
    lines = [f"## Design dossier: {ip}"]
    lines.append(f"Top module: {spec.top}. Clocks: " +
                 ", ".join(f"{c.name} ({c.period_ns}ns sim)" for c in spec.clocks) +
                 ". Resets: " + ", ".join(f"{n} (active-{lvl})"
                                          for n, lvl in spec.resets) + ".")
    for rel in (spec.sources if sources is None else sources):
        text = pristine_source(ip, rel)
        n = text.count("\n")
        lines.append(f"- {Path(rel).name}: {n} lines")
    if ip == "async_fifo":
        lines.append("NOTE: dual-clock CDC FIFO — synchronizers and gray-code "
                     "pointer properties are sacred (see AVOID bullets).")
    return "\n".join(lines)


# ── diagnosis-driven staged context (large IPs) ────────────────────────────────
_DIAG_MIN_FILES = 15        # below this, full context is already cheap
_RO_CAP = 6                 # max read-only grounding files sent alongside the
                            # editable batch (bounds tokens on huge IPs)


def _is_stub(model) -> bool:
    """NON-SPOOFABLE execution authority (migration review SS4.2): identity is
    the actual production class, never a mutable __name__ string - an
    arbitrary object named 'StubModel' is a REAL model here and is refused
    while PENDING."""
    from .proposer import StubModel
    return isinstance(model, StubModel)


def _campaign_gate(spec, model, profile=None):
    """Capability gate (SS11 step 2): a host-validation-requiring contract
    (NVDLA/tmake) that is not VALIDATED refuses every REAL model campaign with
    a persisted structured refusal. Only the genuine keyless StubModel
    (isinstance-checked) is the explicit validation mode (design rev2.1
    SSE.4); the matching immutable ValidationProfile flows in via run(profile=)
    once real H-1 evidence is bound. Invariant: no model call while PENDING."""
    from . import contract as _C
    refusal = _C.campaign_refusal(_C.get_contract(spec), profile)
    if refusal is None or _is_stub(model):
        return
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_DIR / "refusals.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            **refusal}) + "\n")
    raise _C.ContractError(
        f"{refusal['reason']}: {spec.name} refuses model campaigns - "
        f"{refusal['detail']} (refusal persisted to ledger/refusals.jsonl)")


def _stage_batch_files(diag, cursor: int, batch: int) -> list[str]:
    """Coordinate-descent scope: stage 1 = worst file only; every later stage =
    `batch` files. Returns repo-relative source paths for [cursor:cursor+n]."""
    n = 1 if cursor == 0 else batch
    return list(diag.critical_files[cursor:cursor + n])


def _scope_files(batch_paths: list, parent_files: dict) -> dict:
    """{rel: content} for just this stage's files (their full source, so the
    model rewrites complete files). Falls back to full context if none map."""
    sub = {rel: parent_files[rel] for rel in batch_paths if rel in parent_files}
    return sub or parent_files


def _extract_header(src: str) -> str:
    """Port header of a Verilog module — `module ...;` (ANSI: full port list)
    plus any following non-ANSI input/output/parameter declaration lines.
    Pure text extraction, zero model tokens."""
    m = re.search(r"\bmodule\b.*?;", src, re.S)
    if not m:
        return ""
    decls = []
    for line in src[m.end():].splitlines():
        ls = line.strip()
        if not ls or ls.startswith("//"):
            continue
        if re.match(r"(input|output|inout|parameter|localparam)\b", ls):
            decls.append(line.rstrip())
        elif re.match(r"(reg|wire|integer)\b", ls):
            continue        # internal decls interleave with ports; keep scanning
        else:
            break           # body starts — ports are done
    return (m.group(0) + ("\n" + "\n".join(decls) if decls else "")
            + "\n// ... body omitted (interface stub) ...\nendmodule")


def _iface_stubs(ip: str, batch_paths: list, parent_files: dict,
                 cap: int = _RO_CAP) -> dict:
    """Config C grounding: for each module INSTANTIATED by the batch file(s),
    extract just its port header from its source. Gives the model the
    interface contracts it needs (widths, directions, params) at a tiny
    fraction of full-file tokens — and nothing tempting to edit.
    Pure regex over already-loaded text, zero model tokens."""
    stems = {Path(s).stem: s for s in IPS[ip].sources}
    deps: list[str] = []
    for bp in batch_paths:
        text = parent_files.get(bp, "")
        for stem, rel in stems.items():
            if rel in batch_paths or rel in deps:
                continue
            # instantiation: module name, optional #(params), instance name (
            if re.search(rf"\b{re.escape(stem)}\s+(?:#|\w+\s*\()", text):
                deps.append(rel)
    stubs = {}
    for rel in deps[:cap]:
        stub = _extract_header(parent_files.get(rel, ""))
        if stub:
            stubs[rel] = stub
    return stubs


def _budget_line(model: Model, max_calls: int, max_tokens: int) -> tuple[str, float]:
    # max_calls bounds PROPOSAL calls only (candidate file-edit attempts) —
    # reflector/repair overhead does not consume the turn budget, so
    # "N turns = N file-edit attempts" holds regardless of overhead.
    frac = 1.0 - max(model.proposal_calls / max_calls if max_calls else 0,
                     model.tokens / max_tokens if max_tokens else 0)
    line = (f"<budget>proposal turns used {model.proposal_calls}/{max_calls}; "
            f"tokens ~{model.tokens}/{max_tokens}. Make the best use of the "
            f"available resources.</budget>")
    return line, frac


def _k_for_regime(k: int, frac: float) -> int:
    if frac >= 0.7:
        return k
    if frac >= 0.3:
        return max(2, k - 1)
    if frac >= 0.1:
        return 1
    return 0


def run(ip: str, rounds: int, k: int, model: Model, *,
        mode: str = "pareto", workers: int = 4,
        max_calls: int = 40, max_tokens: int = 2_000_000,
        plateau_rounds: int = 3, plateau_delta: float = 0.02,
        emit_best: str | None = None, diagnose: str = "auto",
        stage_batch: int = 1, fresh_pool: bool = False,
        k_first: int = 6, grounding: str = "on",
        fence: bool = False, focus: list | None = None,
        profile=None) -> dict:
    spec = IPS[ip]
    _campaign_gate(spec, model, profile)  # PENDING never sees a model call
    # NVDLA's reset/CDC/bus-interface fence is an assurance requirement, not
    # an optional security-conscious knob. Other IPs retain the existing CLI
    # behavior exactly.
    fence = fence or bool(
        FENCE.get(ip, {}).get("mandatory", False))
    # ONE worker resolution (SSH.5): contract hard cap applied here, once;
    # every executor below receives this value (evaluate_many re-clamps only
    # as an idempotent defense)
    from . import contract as _C
    ctr = _C.get_contract(spec)
    is_tmake = ctr.name == "tmake"
    requested_workers = workers
    _cap = ctr.worker_cap()
    if workers > _cap:
        print(f"[{ip}] workers resolved {workers} -> {_cap} (contract cap)")
        workers = _cap
    obj = Objective(mode=mode, clk_period_ps=_sdc_period(ip))
    pool = DesignPool(ip, fresh=fresh_pool)
    frontier = ParetoFrontier()

    # ── diagnosis-driven context selection (large IPs) ───────────────────────
    # Run the PPA tools FIRST (zero model tokens); scope each candidate to the
    # critical-path files instead of dumping the whole tree. Auto-on for large
    # IPs under a real model; off for stub (keeps the proven replay path) and
    # small IPs (full context is already cheap). See NVIDIA_DAILY_RUN_LOG
    # 2026-07-13.
    diag = None
    _large = len(spec.sources) > _DIAG_MIN_FILES
    _want = (diagnose == "on" or
             (diagnose == "auto" and is_tmake) or
             (diagnose == "auto" and _large and not _is_stub(model)))
    if _want:
        from .diagnose import diagnose as _run_diag
        try:
            diag = _run_diag(ip)
            print(f"[{ip}] diagnosis: WNS={diag.wns_ps}ps "
                  f"structure={diag.structure} "
                  f"crit_files={[Path(f).name for f in diag.critical_files[:4]]}")
            if not diag.critical_files:
                # no attribution (e.g. unparseable reports on a hidden IP):
                # staging would scope-drop EVERY edit and burn the budget on
                # nothing — fall back to full context instead.
                print(f"[{ip}] diagnosis found no critical files — "
                      f"full-context fallback")
                diag = None
        except Exception as e:
            print(f"[{ip}] diagnosis failed ({e}) — full-context fallback")
    if diag and focus:
        # --focus: explicit cursor override (basenames). The campaign walks
        # THESE files in the given order instead of the diagnosis ranking —
        # for targeted campaigns (e.g. unfenced aes S-box) and DAC-day triage.
        by_name = {Path(s).name: s for s in (
            diag.critical_files if is_tmake else spec.sources)}
        want = [by_name[n] for n in focus if n in by_name]
        missing = [n for n in focus if n not in by_name]
        if missing:
            print(f"[{ip}] --focus: unknown files ignored: {missing}")
        if want:
            diag.critical_files = want
            print(f"[{ip}] focus cursor: {[Path(f).name for f in want]}")

    campaign_scope = None
    source_paths = list(spec.sources)
    if is_tmake:
        from . import gate as _G
        from . import registry as _registry
        plan = _G.get_gate_plan(ip)
        if not isinstance(plan, _G.TraceGatePlan):
            raise _C.ContractError(
                f"{ip}: ordinary campaign requires a registered "
                "TraceGatePlan")
        ranked = [
            rel for rel in (diag.critical_files if diag else ())
            if plan.scope_compatible(_C.CampaignScope(
                ip=ip, editable_targets=(rel,),
                verification_policy="trace-gate+lec-v2+measurement",
                requested_workers=requested_workers))]
        target = (ranked[0] if ranked
                  else _registry.NVDLA_DEFAULT_TARGET)
        if focus:
            focused = [rel for rel in (diag.critical_files if diag else ())
                       if Path(rel).name in set(focus)]
            if focused:
                target = focused[0]
        campaign_scope = _C.CampaignScope(
            ip=ip, editable_targets=(target,),
            verification_policy="trace-gate+lec-v2+measurement",
            requested_workers=requested_workers,
            max_changed_files=1)
        if not plan.scope_compatible(campaign_scope):
            raise _C.ContractError(
                f"{ip}: selected target {target} is not exercised by the "
                "registered trace plan")
        source_paths = [target]
        # NVDLA v1 is an explicit one-target campaign. Diagnosis still ranks
        # the real design, but the controller walks only the highest-ranked
        # target covered by the registered PDP trace.
        if diag is not None:
            diag.critical_files = [target]
        print(f"[{ip}] trace-bound campaign target: {target}")

    # ── baseline state (measure + reports, cached) ───────────────────────────
    base = E.baseline(ip)
    base_ppa = base["ppa"]
    if "baseline" not in pool.states:
        pool.add("baseline", base_ppa,
                 ctr.pristine_editable_state(campaign_scope)
                 if is_tmake else
                 {rel: pristine_source(ip, rel) for rel in spec.sources},
                 parent=None, strategy="baseline")
    if not (E.reports_dir(ip, "baseline") / "sta_timing_paths.txt").exists():
        ws = Workspace.create(ip, tag="basereports")
        try:
            E.measure(ws, f"{ip}-basereports")
            E._save_reports(ws, E.Candidate(ip, {}, cid="baseline"))
        finally:
            ws.destroy()
    for s in pool.states.values():
        frontier.offer(s.cid, s.ppa, {"strategy": s.strategy})

    dossier = _dossier(ip, source_paths)
    best_adp_history: list[float] = []
    summary = {"rounds": [], "accepted": 0}
    # staged-context cursor (only used when diag is active)
    scope_cursor = 0        # index into diag.critical_files
    n_crit = len(diag.critical_files) if diag else 0

    for rnd in range(1, rounds + 1):
        budget_line, frac = _budget_line(model, max_calls, max_tokens)
        if diag:
            # staged mode: FIXED k per stage (k_first on stage 1 = worst file,
            # k after), walking one file/stage until the turn budget runs out.
            # Last stage may be partial (whatever budget remains). No regime
            # tapering — turns are spent covering files, cleanly.
            # A trace-bound tmake run has one expensive target and honors the
            # user's --k literally; the legacy k_first fan-out would turn the
            # documented k=1 validation command into six 2-hour evaluations.
            k_stage = (k if is_tmake
                       else k_first if scope_cursor == 0 else k)
            k_now = min(k_stage, max_calls - model.proposal_calls)
        else:
            k_now = _k_for_regime(k, frac)     # BATS 70/30/10 regime
        if k_now <= 0:
            print(f"[{ip}] turn budget exhausted — stopping")
            break

        # PARENT SELECTION. Staged mode = coordinate descent: pin the parent to
        # the best-so-far (frontier best), so each stage provably builds on the
        # accumulated wins of the earlier stages. Non-staged = Thompson sample.
        if diag:
            fb = frontier.best(obj, base_ppa)
            parent_cid = fb["cid"] if fb else "baseline"
            sel_mode = "deepen"
        else:
            parent_cid, sel_mode = pool.select_parent()
        parent = pool.states[parent_cid]
        parent_files = (pool.files_of(parent_cid) if parent_cid != "baseline"
                        else (ctr.pristine_editable_state(campaign_scope)
                              if is_tmake else
                              {rel: pristine_source(ip, rel)
                               for rel in spec.sources}))
        parent_adp = round(obj.adp_ratio(parent.ppa, base_ppa) or 1.0, 4)

        rep_dir = E.reports_dir(ip, parent_cid)
        if not (rep_dir / "sta_timing_paths.txt").exists():
            rep_dir = E.reports_dir(ip, "baseline")
        sta_block = _sta_prompt_block(ip, rep_dir)
        # prefer the diagnosis structure tag (per-file critical path) over the
        # flat STA tag when diagnosis is active
        tag = (diag.structure if (diag and diag.structure)
               else S.dominant_tag(rep_dir) or "mixed-comb-depth")

        preferred = _risk_gated(_TAG_TO_RUNGS.get(tag, []),
                                base_ppa.get("setup"), _sdc_period(ip))
        rungs = [r for r in LADDER if r["key"] in preferred]
        rungs.sort(key=lambda r: preferred.index(r["key"]))
        rungs = rungs[:k_now]
        if len(rungs) < k_now:
            more = pick_strategies(k_now - len(rungs), obj.weights,
                                   exclude={r["key"] for r in rungs})
            rungs += more
        if sel_mode == "deepen" and parent.strategy in {r["key"] for r in LADDER}:
            # push the parent's own strategy line first when deepening
            rungs.sort(key=lambda r: r["key"] != parent.strategy)

        bullets = skills.retrieve([tag], sections=None, k=5)
        diag_block = (diag.bundle_text() + "\n\n" if diag else "") + sta_block

        # STAGED context (large IPs, coordinate descent): this stage targets a
        # small batch of critical-path files (stage 1 = worst file; later
        # stages = `stage_batch` files each). All k rungs share this scope and
        # vary by STRATEGY; the parent is the best-so-far, so each stage builds
        # on the prior stage's locked-in win rather than re-optimising it. No
        # retry: the cursor always advances (k is the per-stage diversity).
        # Small IPs / stub keep full context (proven path).
        batch_paths = (_stage_batch_files(diag, scope_cursor, stage_batch)
                       if diag else [])
        stage_files = (_scope_files(batch_paths, parent_files)
                       if batch_paths else parent_files)
        # read-only GROUNDING context: the OTHER critical files (both the
        # already-locked earlier stages AND the not-yet-reached ones the batch
        # file interacts with). Sending the target file ALONE starved the model
        # of the surrounding data flow -> functional bugs + hallucinated edits
        # (2026-07-13 regression root-cause). Bounded by _RO_CAP for huge IPs.
        readonly = None
        iface_block = ""
        if diag and grounding == "on":
            ro = [rel for rel in diag.critical_files
                  if rel not in batch_paths and rel in parent_files][:_RO_CAP]
            readonly = {rel: parent_files[rel] for rel in ro}
        elif diag and grounding == "stubs":
            stubs = _iface_stubs(ip, batch_paths, parent_files)
            iface_block = "\n\n".join(
                f"// STUB of {Path(r).name}:\n{t}" for r, t in stubs.items())
        scope_note = ""
        if diag:
            scope_note = (
                "IMPORTANT: You may edit ONLY the file(s) under FILES TO "
                "OPTIMISE. Any edit to ANY other file is DISCARDED by the "
                "harness — your change must be entirely self-contained and "
                "correct against the other files exactly as they are.")
        ctx = PromptContext(
            ip=ip, files=stage_files, ppa=parent.ppa, sta_block=diag_block,
            playbook_block=skills.render(bullets), dossier=dossier,
            weights=obj.weights, budget_line=budget_line,
            readonly_files=readonly, scope_note=scope_note,
            iface_block=iface_block, fence=fence,
            ref_note=(f"(baseline for relative scoring: area="
                      f"{base_ppa['area']}, setup={base_ppa['setup']}ps)"))

        if diag:
            locked = [Path(f).name for f in diag.critical_files[:scope_cursor]]
            print(f"\n[{ip}] ── STAGE @cursor {scope_cursor} ──")
            print(f"    parent={parent_cid[:8]} ADP={parent_adp} (best-so-far)")
            print(f"    EDITING: {[Path(f).name for f in batch_paths]}")
            if grounding == "stubs":
                stub_names = re.findall(r"// STUB of (\S+):", iface_block)
                stub_lines = iface_block.count("\n") + 1 if iface_block else 0
                print(f"    interface stubs ({stub_lines} lines): "
                      f"{stub_names} (locked: {locked or 'none'})")
            else:
                print(f"    read-only grounding: "
                      f"{[Path(f).name for f in (readonly or {})]}"
                      f" (locked: {locked or 'none'})")
            print(f"    strategies (k={k_now}): {[r['key'] for r in rungs]}")
        else:
            print(f"\n[{ip}] round {rnd}: parent={parent_cid[:12]} ({sel_mode}), "
                  f"tag={tag}, k={k_now}, rungs={[r['key'] for r in rungs]}")

        # RESILIENT fan-out: a transient API failure (503/429 after retries, or
        # any per-call error) drops THAT candidate to None — it must never kill
        # the whole campaign. With k parallel shots, losing one still leaves the
        # rest. Critical for DAC-day robustness.
        def _safe_gen(r):
            try:
                return (r, model.generate(build_prompt(ctx, r)))
            except Exception as e:
                print(f"  [{r['key']}] model call failed ({type(e).__name__}: "
                      f"{str(e)[:80]}) — dropped")
                return (r, None)
        with ThreadPoolExecutor(max_workers=k_now) as ex:
            resps = list(ex.map(_safe_gen, rungs))
        # turn budget = proposals only; an API-dropped call produced no edit
        # attempt, so it doesn't spend a turn
        model.proposal_calls += sum(1 for _, resp in resps if resp is not None)

        cands = []
        for rung, resp in resps:
            if resp is None:            # dropped by resilient fan-out
                continue
            _dump_raw(ip, rnd, rung["key"], resp)
            files = parse_response(
                ip, resp,
                allowed_paths=(batch_paths if is_tmake else None))
            if not files:
                print(f"  [{rung['key']}] no usable code blocks — skipped "
                      f"(raw kept in ledger/raw/{ip}/)")
                continue
            if diag:
                # STRICT scope: accept edits ONLY to this stage's batch files.
                # The model often HALLUCINATES edits to files it can't see (it
                # knows they exist from the file list) — e.g. a made-up
                # sha512_w_mem that doesn't match the real one → breaks
                # functionality. Drop anything outside the batch. (root-cause
                # of the 2026-07-13 staged-run regression.)
                allowed = set(batch_paths)
                extra = [Path(r).name for r in files if r not in allowed]
                files = {r: t for r, t in files.items() if r in allowed}
                if extra:
                    print(f"  [{rung['key']}] dropped out-of-scope/hallucinated "
                          f"edits: {extra}")
                if not files:
                    print(f"  [{rung['key']}] no in-scope edits — skipped")
                    continue
            # fence AFTER scoping (2026-07-14, aes finding): an out-of-scope
            # S-box edit is dropped harmlessly above — the fence must only veto
            # candidates whose SURVIVING edits touch fenced logic. Fence is
            # OFF by default (Hari, 2026-07-14): contest scores tests+PPA only.
            if fence:
                fv = fence_violation(ip, files)
                if fv:
                    print(f"  [{rung['key']}] FENCE-REJECT: {fv}")
                    continue
            edited = [Path(r).name for r in files]
            merged = dict(parent_files)
            merged.update(files)
            cand_meta = {
                "strategy": rung["key"], "parent": parent_cid, "round": rnd,
                "edited": edited, "budget_authorized": True}
            if is_tmake:
                from .orchestrate import source_cid as _source_cid
                cands.append(E.Candidate(
                    ip, merged, cid=_source_cid(merged), meta=cand_meta))
            else:
                cands.append(E.Candidate(ip, merged, meta=cand_meta))

        # The genuine StubModel is the accepted keyless validation mode for a
        # PENDING tmake contract.  With no replay queue it intentionally emits
        # no RTL; synthesize one semantics-neutral comment-only delta so the
        # materialize -> trace -> LEC -> measure chain is still exercised.
        # The policy remains ineligible while PENDING, so this candidate can
        # never enter the pool or be emitted.
        if is_tmake and _is_stub(model) and not cands:
            rel = campaign_scope.editable_targets[0]
            text = parent_files[rel].rstrip() + (
                f"\n// P0-4 keyless validation candidate round {rnd}\n")
            files = {rel: text}
            from .orchestrate import source_cid as _source_cid
            cands.append(E.Candidate(
                ip, files, cid=_source_cid(files),
                meta={"strategy": "stub-validation", "parent": parent_cid,
                      "round": rnd, "edited": [Path(rel).name],
                      "budget_authorized": True,
                      "validation_only": True}))
            print(f"  [stub-validation] generated comment-only delta for "
                  f"{Path(rel).name}")
        if not cands:
            summary["rounds"].append({"round": rnd, "accepted": 0,
                                      "note": "no candidates"})
            best_adp_history.append(best_adp_history[-1] if best_adp_history
                                    else 1.0)
            # staged mode: a barren stage still advances the cursor (no retry),
            # so we never loop on one file.
            if diag and n_crit:
                batch_n = 1 if scope_cursor == 0 else stage_batch
                print(f"[{ip}] STAGE @cursor {scope_cursor}: no candidates — "
                      f"advancing cursor {scope_cursor}→{scope_cursor + batch_n}")
                scope_cursor += batch_n
                if scope_cursor >= n_crit:
                    print(f"[{ip}] all {n_crit} critical files staged")
                    break
                continue
            if _plateaued(best_adp_history, plateau_rounds, plateau_delta):
                print(f"[{ip}] plateau — stopping")
                break
            continue

        results = E.evaluate_many(
            cands, max_workers=workers, full_verify=True,
            scope=campaign_scope, profile=profile)

        # self-debug: compile failures get <=2 cheap repair attempts with the
        # tool stderr fed back (doesn't count as a full round)
        base_eval = E.baseline(ip)
        for i, (cand, res) in enumerate(zip(cands, results)):
            attempts = 0
            while (res.status in ("compile-fail", "regen-fail")
                   and attempts < 2
                   and _budget_line(model, 0, max_tokens)[1] > 0.05):  # token-gated
                attempts += 1
                try:
                    resp = model.generate(build_repair_prompt(
                        {r: t for r, t in cand.files.items()
                         if r not in parent_files or cand.files[r] != parent_files.get(r)},
                        res.detail or "unknown error"))
                except Exception as e:      # API failure must not kill the run
                    print(f"  [repair] model call failed "
                          f"({type(e).__name__}: {str(e)[:80]}) — skipped")
                    break
                fixed = parse_response(
                    ip, resp,
                    allowed_paths=(batch_paths if is_tmake else None))
                if diag:      # strict scope applies to compile repair too
                    fixed = {rr: tt for rr, tt in fixed.items()
                             if rr in set(batch_paths)}
                if not fixed:
                    break
                merged = dict(cand.files)
                merged.update(fixed)
                cand = E.Candidate(ip, merged, meta={
                    **cand.meta, "repair_attempt": attempts})
                res = E.evaluate_one(cand, base_eval, full_verify=True)
                print(f"  [repair {attempts}] {cand.cid[:12]} -> {res.status}")
            cands[i], results[i] = cand, res

        accepted = 0
        for cand, res in zip(cands, results):
            # netlist-collapse guard (2026-07-14, aes finding): an edit that
            # breaks hierarchy elaboration can synthesize to a tiny fragment
            # that "improves" every metric. That is measurement garbage, not
            # optimization — reject before comparing.
            if (res.ppa and parent.ppa.get("cells")
                    and res.ppa.get("cells", 0) < 0.5 * parent.ppa["cells"]):
                print(f"  reject {cand.cid[:12]} [{cand.meta['strategy']}] "
                      f"netlist-collapse: {res.ppa['cells']:.0f} cells vs "
                      f"parent {parent.ppa['cells']:.0f} — elaboration broke")
                pool.backup(parent_cid, 0.10)
                continue
            # CDC structural invariant (2026-07-25, async_fifo finding): in a
            # MULTI-CLOCK design, removing flip-flops relative to the pristine
            # baseline is the signature of de-registering a clock-domain
            # crossing — a glitch hazard that LEC (PROVEN) and zero-delay
            # dualsim (PASS) both structurally cannot see. Refuse before the
            # candidate can be compared, pooled, or become canonical.
            if res.ppa:
                cdcv = cdc_ff_violation(spec, base_ppa, res.ppa)
                if cdcv:
                    print(f"  reject {cand.cid[:12]} "
                          f"[{cand.meta['strategy']}] {cdcv}")
                    pool.backup(parent_cid, 0.10)
                    continue
            adp = (obj.adp_ratio(res.ppa, parent.ppa)
                   if res.ppa else None)
            reward = pool.reward_from_eval(res.status, adp)
            pool.backup(parent_cid, reward)
            verdict, reason = (obj.better(res.ppa, parent.ppa)
                               if res.status == "measured" and res.ppa
                               else (False, res.status))
            dualsim_ok = (
                res.verify.get("dualsim", {}).get("status") == "PASS"
                or (is_tmake and res.status == "measured"
                    and res.verify.get("lec", {}).get("status") == "PROVEN"))
            if verdict and dualsim_ok:
                pool.add(cand.cid, res.ppa, cand.files, parent_cid,
                         cand.meta["strategy"])
                frontier.offer(cand.cid, res.ppa,
                               {"strategy": cand.meta["strategy"]})
                accepted += 1
                summary["accepted"] += 1
                ed = cand.meta.get("edited", [])
                print(f"  ACCEPT {cand.cid[:12]} [{cand.meta['strategy']}] "
                      f"edited={ed} {reason} | ADP vs parent="
                      f"{adp and round(adp, 3)}")
            else:
                print(f"  reject {cand.cid[:12]} [{cand.meta['strategy']}] "
                      f"{res.status}: {reason}")

        # ── PPA-prioritised gate-fail repair (2026-07-13) ────────────────────
        # If the stage produced NO win, the gate-failed candidates are often
        # near-wins (compile+timing-improving, one functional bug). Measure
        # their real PPA, keep the ones that WOULD improve, repair the top-2
        # (1 attempt each). Repair calls are OFF the turn budget (proposals
        # only) — gated by the token budget, not proposal count.
        if (not is_tmake and accepted == 0
                and _budget_line(model, 0, max_tokens)[1] > 0.05):
            # "broken but maybe promising" = gate-fail (TB caught it) OR
            # dualsim-fail (IPs whose TB is skipped — aes — fail at layer 5
            # instead; 2026-07-14). dualsim-fail candidates were already
            # measured, so their PPA is free.
            broken = [(c, r) for c, r in zip(cands, results)
                      if r.status in ("gate-fail", "dualsim-fail")]
            # measure the broken candidates' real PPA IN PARALLEL (each is a
            # full synth+STA in its own workspace; bounded by --workers so we
            # don't thrash on huge IPs). 4 broken candidates finish in ~1 synth
            # time, not 4×.
            with ThreadPoolExecutor(max_workers=workers) as ex:
                measured = list(ex.map(
                    lambda cr: (cr[0], cr[1],
                                cr[1].ppa or E.measure_candidate(cr[0])),
                    broken))
            scored = []
            for c, r, ppa in measured:
                adp = obj.adp_ratio(ppa, parent.ppa) if ppa else None
                if adp is not None and adp < 0.995:      # would improve if fixed
                    scored.append((adp, c, r, ppa))
            scored.sort(key=lambda x: x[0])
            if scored:
                print(f"  [gatefail-repair] {len(scored)} broken-but-PPA-"
                      f"improving candidate(s); repairing top "
                      f"{min(2, len(scored))}")
            for adp, c, r, ppa in scored[:2]:
                changed = {rel: t for rel, t in c.files.items()
                           if t != parent_files.get(rel)}
                try:
                    resp = model.generate(build_gatefail_repair_prompt(
                        changed, r.detail or "", f"ADP {adp:.3f} vs parent"))
                except Exception as e:   # API failure must not kill the run
                    print(f"  [gatefail-repair] model call failed "
                          f"({type(e).__name__}: {str(e)[:80]}) — skipped")
                    continue
                fixed = parse_response(ip, resp)
                if diag:      # strict: repair may only touch the batch files too
                    fixed = {rr: tt for rr, tt in fixed.items()
                             if rr in set(batch_paths)}
                if not fixed:
                    print(f"  [gatefail-repair] {c.meta['strategy']}: no fix returned")
                    continue
                merged = dict(parent_files); merged.update(fixed)
                rc = E.Candidate(ip, merged, meta={
                    **c.meta, "repair": "gatefail"})
                rr = E.evaluate_one(rc, base_eval, full_verify=True)
                radp = obj.adp_ratio(rr.ppa, parent.ppa) if rr.ppa else None
                verdict, reason = (obj.better(rr.ppa, parent.ppa)
                                   if rr.status == "measured" and rr.ppa
                                   else (False, rr.status))
                dsok = rr.verify.get("dualsim", {}).get("status") == "PASS"
                if verdict and dsok:
                    pool.add(rc.cid, rr.ppa, rc.files, parent_cid, c.meta["strategy"])
                    frontier.offer(rc.cid, rr.ppa, {"strategy": c.meta["strategy"]})
                    accepted += 1; summary["accepted"] += 1
                    print(f"  ACCEPT (repaired) {rc.cid[:12]} "
                          f"[{c.meta['strategy']}] {reason} | ADP="
                          f"{radp and round(radp, 3)}")
                else:
                    print(f"  [gatefail-repair] {c.meta['strategy']} -> "
                          f"{rr.status} (still no win)")

        # staged-context cursor: lock this stage's outcome and advance.
        if diag and n_crit:
            # NO retry (2026-07-13): the higher k IS the per-stage diversity —
            # always advance the cursor to the next file. Accumulated-best is
            # preserved regardless, so a barren stage costs nothing but its k
            # calls. Budget goes to COVERING more critical files, not re-trying.
            batch_n = 1 if scope_cursor == 0 else stage_batch
            fb = frontier.best(obj, base_ppa)
            acc_adp = round(obj.adp_ratio(fb["ppa"], base_ppa) or 1.0, 4) if fb else 1.0
            staged = [Path(f).name for f in batch_paths]
            mark = "✓ LOCKED" if accepted > 0 else "✗ no win (kept best)"
            print(f"[{ip}] STAGE {staged} {mark} — accumulated best "
                  f"ADP={acc_adp}. Advancing cursor {scope_cursor}→"
                  f"{scope_cursor + batch_n}")
            scope_cursor += batch_n
            if scope_cursor >= n_crit:
                print(f"[{ip}] all {n_crit} critical files staged — final "
                      f"accumulated ADP={acc_adp}")
                break

        # reflector: distill round outcomes into playbook votes/lessons
        # (deterministic curator applies them; stub output parses to nothing)
        if cands:
            outcomes = [
                f"[{c.meta['strategy']}] {r.status}"
                + (f" setup {parent.ppa['setup']}->{r.ppa['setup']}ps area "
                   f"{parent.ppa['area']}->{r.ppa['area']}"
                   if r.ppa else f" ({(r.detail or '')[:120]})")
                for c, r in zip(cands, results)]
            votes, adds = parse_reflection(model.generate(
                build_reflect_prompt(ip, outcomes, bullets)))
            for bid, helpful in votes:
                skills.vote(bid, helpful)
            for section, tag, content in adds:
                skills.add_bullet(section, [tag, ip], f"({ip}, agent) {content}")
            if votes or adds:
                print(f"  reflector: {len(votes)} votes, {len(adds)} lessons")

        best_adp = min((obj.adp_ratio(e['ppa'], base_ppa) or 1.0)
                       for e in frontier.entries)
        best_adp_history.append(best_adp)
        _round_log(ip, {"round": rnd, "parent": parent_cid, "tag": tag,
                        "rungs": [r["key"] for r in rungs],
                        "accepted": accepted, "best_adp": best_adp,
                        "calls": model.calls, "tokens": model.tokens})
        summary["rounds"].append({"round": rnd, "accepted": accepted,
                                  "best_adp": round(best_adp, 4)})
        if _plateaued(best_adp_history, plateau_rounds, plateau_delta):
            print(f"[{ip}] plateau (best ADP {best_adp:.3f} flat "
                  f"{plateau_rounds} rounds) — stopping")
            break

    # ASSURANCE-AWARE canonical selection (2026-07-19 ascon finding): the PPA-best
    # frontier entry is NOT necessarily the canonical winner. An LEC-INCONCLUSIVE/
    # -ERROR candidate must never displace an LEC-PROVEN improvement just because its
    # ADP is a little better — a rare functional mismatch can slip past limited
    # differential sim (the rejected ascon candidate used WRONG integrity-bit slices,
    # measured a better ADP, and missed real integrity errors). Canonical = best-ADP
    # LEC-PROVEN improvement; if none is proven, ship the eligible baseline and keep
    # the unproven PPA-best only as EXPERIMENTAL (never canonical).
    ppa_best = frontier.best(obj, base_ppa)
    best = _canonical_best(ip, pool, obj, base_ppa)   # full pool, not the frontier
    _adp = lambda e: round(obj.adp_ratio(e["ppa"], base_ppa) or 1.0, 4)
    _exp = _experimental_best(ip, ppa_best, best, obj, base_ppa)
    if best is None and _exp is not None:
        print(f"[{ip}] canonical: PPA-best {_exp['cid']} (ADP {_exp['adp_vs_baseline']}) is not "
              f"LEC-PROVEN and no proven improvement exists -> shipping baseline; kept EXPERIMENTAL.")
    elif best is not None and _exp is not None:
        print(f"[{ip}] canonical: preferring LEC-PROVEN {best['cid']} (ADP {_adp(best)}) over "
              f"higher-ADP-but-unproven {_exp['cid']} (ADP {_exp['adp_vs_baseline']}).")
    summary.update({
        "best": best and {"cid": best["cid"], "ppa": best["ppa"],
                          "adp_vs_baseline": _adp(best)},
        "experimental_best": _exp,
        "frontier_size": len(frontier.entries),
        "calls": model.calls, "tokens": model.tokens})
    print(f"\n[{ip}] DONE: {json.dumps(summary['best'], indent=1)}\n"
          f"frontier={summary['frontier_size']} calls={model.calls} "
          f"tokens~{model.tokens} accepted={summary['accepted']}")
    if emit_best:
        _emit_best(ip, best, pool, base_ppa, summary, Path(emit_best))
    return summary


def _verify_status(ip: str, cid: str) -> dict:
    """Look up the accepted candidate's actual per-layer verification status
    from the ledger (lint/compile/gate/lec/dualsim), so the manifest states
    what was ACHIEVED, not a blanket claim."""
    led = LEDGER_DIR / f"{ip}.jsonl"
    if not cid or not led.exists():
        return {}
    last = {}
    for line in led.read_text().splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("cid") == cid and d.get("verify"):
            v = d["verify"]
            last = {k: (v[k].get("status") if isinstance(v.get(k), dict)
                        else v.get(k))
                    for k in ("lint", "compile", "gate", "lec", "dualsim")
                    if v.get(k) is not None}
    return last


def _verify_evidence(ip: str, cid: str) -> dict:
    """Retained normalized layer evidence for the selected candidate.

    In particular, the LEC entry carries recipe/rc/total/proven/unproven so a
    manifest's PROVEN label can be audited after disposable workspaces are
    gone. Older ledger rows legitimately return an empty mapping.
    """
    led = LEDGER_DIR / f"{ip}.jsonl"
    if not cid or not led.exists():
        return {}
    last = {}
    for line in led.read_text().splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("cid") == cid and isinstance(d.get("verify_evidence"), dict):
            last = dict(d["verify_evidence"])
    return last


def _assurance(v: dict, gate_blind: bool = False) -> str:
    """Summarise the assurance level actually reached for this candidate.

    gate_blind=True (2026-07-19 ascon finding): for an OpenTitan generated-.v edit,
    the Verilator TB gate builds the pristine .sv, so its PASS did NOT exercise the
    candidate — it must not be counted as a candidate-aware functional layer."""
    if not v:
        return "unknown (no ledger verify record)"
    passed = lambda k, *ok: v.get(k) in ok
    gate_ok = passed("gate", "PASS") and not gate_blind
    if (passed("lint", "PASS") and passed("compile", "PASS")
            and gate_ok and passed("lec", "PROVEN") and passed("dualsim", "PASS")):
        return "full 5-layer: lint+compile+TB gate PASS, yosys LEC PROVEN, dualsim PASS"
    if passed("lec", "PROVEN") and passed("dualsim", "PASS"):
        note = ("gate ran the pristine .sv — candidate .v not exercised"
                if gate_blind else f"gate={v.get('gate')}, compile={v.get('compile')}")
        return f"equivalence+differential: LEC PROVEN + dualsim PASS ({note})"
    if passed("dualsim", "PASS"):
        return (f"differential-only: dualsim PASS (lec={v.get('lec')}, "
                f"gate={v.get('gate')}"
                + (", candidate-blind" if gate_blind else "") + ")")
    return "measurement-only / see per_layer"


def _canonical_best(ip: str, pool, obj, base_ppa: dict):
    """Assurance-aware canonical winner, taken from the FULL accepted POOL — NOT
    the Pareto frontier. A LEC-PROVEN candidate can be PPA-dominated by an unproven
    one and thus EVICTED from the frontier (2026-07-19 ascon re-review: the invalid
    INCONCLUSIVE candidate dominated the proven runner-up on area+setup+power, so a
    frontier-only search returned None). Search every accepted state, keep only
    LEC-PROVEN improvements, return the best-ADP one; None if none exists (caller
    ships the eligible baseline). An unproven (INCONCLUSIVE/ERROR) candidate is
    never canonical, however good its ADP."""
    spec = IPS.get(ip)   # None only for unregistered/synthetic IPs; see
                         # cdc_ff_violation() on why that is unreachable live
    proven = []
    for s in pool.states.values():
        if s.cid == "baseline":
            continue
        adp = obj.adp_ratio(s.ppa, base_ppa)
        if adp is None or adp >= 1.0:
            continue                                  # not an ADP improvement
        # CDC structural invariant, re-checked AT SELECTION (2026-07-25). The
        # admission check in the round loop only guards candidates produced
        # from now on; a pool persisted BEFORE that check existed can still
        # contain a de-registered CDC candidate (the shipped async_fifo pool
        # contains exactly one, d8364e88b637, ff=162 vs baseline 170). Because
        # such a candidate is LEC-PROVEN, the proven-preferring rule below is
        # precisely what would promote it. Re-check here so no persisted state
        # can ever become canonical, regardless of when it entered the pool.
        cdcv = cdc_ff_violation(spec, base_ppa, s.ppa)
        if cdcv:
            print(f"[{ip}] canonical: REFUSING {s.cid[:12]} — {cdcv}")
            continue
        if _verify_status(ip, s.cid).get("lec") == "PROVEN":
            proven.append((adp, s))
    if not proven:
        return None
    _, s = min(proven, key=lambda ae: ae[0])
    return {"cid": s.cid, "ppa": s.ppa}


def _experimental_best(ip: str, ppa_best, best, obj, base_ppa: dict):
    """The demoted, REAL (ADP-improving), UNPROVEN candidate — or None. It is never
    baseline, never a non-improvement (adp >= 1.0), and never the canonical winner.
    A baseline-only campaign therefore has NO experimental best (Codex 2026-07-19
    P1: this previously recorded baseline itself)."""
    if ppa_best is None or ppa_best["cid"] == "baseline":
        return None
    adp = obj.adp_ratio(ppa_best["ppa"], base_ppa)
    if adp is None or adp >= 1.0:
        return None
    if best is not None and best["cid"] == ppa_best["cid"]:
        return None
    return {"cid": ppa_best["cid"], "adp_vs_baseline": round(adp, 4),
            "lec": _verify_status(ip, ppa_best["cid"]).get("lec"),
            "note": "higher ADP but not LEC-PROVEN — NOT canonical"}


def _emit_best(ip: str, best, pool, base_ppa: dict, summary: dict,
               out_dir: Path):
    """Submission artifact: ONLY the files the winning candidate actually
    changed vs pristine (a drop-in DELTA — does not overwrite unrelated
    source) + manifest.json with the ACTUAL per-layer verification status."""
    # PATH PREFLIGHT (2026-07-19): a relative --emit-best resolved against the
    # agent CWD once silently emitted under nvidia_work/agent/submission. Reject
    # that location and always print the resolved ABSOLUTE target so a mistake is
    # visible before writing.
    out_dir = Path(out_dir).resolve()
    _bad = (AGENT / "submission").resolve()
    if out_dir == _bad or _bad in out_dir.parents:
        raise SystemExit(
            f"[{ip}] refusing to emit under {_bad} (relative-path mistake); pass an "
            f"absolute --emit-best under {NVWORK / 'submission'} (canonical) instead")
    print(f"[{ip}] emit target (resolved): {out_dir}")
    changed = {}
    if best and best["cid"] != "baseline":
        cand_files = pool.files_of(best["cid"])
        for rel, text in cand_files.items():
            try:
                pristine = pristine_source(ip, rel)
            except Exception:
                pristine = None
            if pristine is None or text != pristine:   # real delta only
                changed[rel] = text
    per_layer = _verify_status(ip, best["cid"]) if best else {}
    # CANDIDATE-AWARE COVERAGE (2026-07-19 ascon): for OpenTitan dual-representation
    # IPs, compile/synth/LEC/dualsim consume the changed generated .v, but the
    # Verilator TB gate builds the pristine .sv — so a generated-.v-only edit's
    # "gate PASS" did NOT exercise the candidate and must not count as a
    # candidate-aware functional layer.
    spec = IPS.get(ip)
    gate_blind = bool(getattr(spec, "sv_sources", ()) and changed
                      and all("/generated/" in f and f.endswith(".v") for f in changed))
    _adp = summary["best"]["adp_vs_baseline"] if best else None
    # label from the actual ADP outcome, not merely "did any file change" — a
    # changed candidate that did NOT improve ADP (e.g. a power tradeoff) must not
    # be called "optimized".
    if changed and _adp is not None and _adp < 1.0:
        _result = "optimized"
    elif changed:
        _result = "explored-no-adp-gain"
    else:
        _result = "no-improvement: baseline is the submission"
    manifest = {
        "ip": ip,
        "result": _result,
        "cid": best["cid"] if best else "baseline",
        "changed_files": sorted(changed),          # true delta
        "baseline_ppa": base_ppa,
        # baseline fallback (no proven improvement): a COMPLETE baseline manifest,
        # not nulls — ADP 1.0 and best_ppa == baseline_ppa (Codex 2026-07-19 P1).
        "best_ppa": best["ppa"] if best else base_ppa,
        "adp_vs_baseline": (summary["best"]["adp_vs_baseline"]
                            if summary.get("best") else 1.0),
        # the unproven higher-ADP candidate (if any) — recorded, NEVER substituted
        # for the canonical/baseline result.
        "experimental_best": summary.get("experimental_best"),
        "verification_per_layer": per_layer,       # actual statuses
        "verification_evidence": (
            _verify_evidence(ip, best["cid"]) if best else {}),
        "candidate_aware_coverage": ({
            "compile": "candidate .v", "lec": "candidate .v",
            "dualsim": "candidate .v",
            "gate": "pristine .sv (candidate .v NOT exercised)" if gate_blind
                    else "candidate"} if changed else None),
        "assurance": _assurance(per_layer, gate_blind) if changed else "baseline (n/a)",
        "llm_calls": summary["calls"],
        "llm_tokens_approx": summary["tokens"],
        "rounds": summary["rounds"],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    # CLEAN staged replacement WITH ROLLBACK — never merges into an existing dir
    # (no stale-file recurrence) and restores the prior artifact if the swap fails
    # (a failed emit never destroys the last known-good package). See ppa/emit.py.
    staged_replace(Path(out_dir), changed, manifest)
    print(f"[{ip}] emitted {len(changed)} changed file(s) -> {out_dir} "
          f"| assurance: {manifest['assurance']}")


def _plateaued(history: list[float], w: int, delta: float) -> bool:
    if len(history) <= w:
        return False
    return history[-1] > min(history[:-w]) * (1 - delta)


def _dump_raw(ip: str, rnd: int, rung: str, text: str):
    """Keep every raw model response for postmortems (format compliance,
    prompt tuning during the config sweep). Cheap, invaluable."""
    d = LEDGER_DIR / "raw" / ip
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{time.strftime('%m%d_%H%M%S')}_r{rnd}_{rung}.txt").write_text(text)


def _round_log(ip: str, rec: dict):
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_DIR / f"{ip}_rounds.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec})
                + "\n")


# ── CLI ───────────────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description="PPA optimization loop")
    ap.add_argument("--ip", required=True,
                    help="IP name or repo-relative path; unknown names are "
                         "auto-discovered from repo conventions (hidden "
                         "testcases)")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--model", default="stub",
                    choices=["stub", "vertex", "endpoint"])
    ap.add_argument("--model-name", default="gemini-3-flash-preview",
                    help="model id for vertex/endpoint")
    ap.add_argument("--endpoint", default="http://127.0.0.1:8080",
                    help="model service URL for --model endpoint")
    ap.add_argument("--key-env",
                    help="env var holding the API key (multi-account "
                         "parallelism); mode follows the name "
                         "(*EXPRESS*=vertex, else ai-studio)")
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--top-p", type=float, default=0.6)
    ap.add_argument("--mode", default="pareto",
                    choices=["pareto", "weighted", "lexicographic"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-calls", type=int, default=40)
    ap.add_argument("--max-tokens", type=int, default=2_000_000)
    ap.add_argument("--stub-replay", action="append", default=[],
                    help="variant dir(s) the stub model replays in order")
    ap.add_argument("--emit-best", metavar="DIR",
                    help="write the winning candidate's files (repo-relative "
                         "layout, drop-in) + manifest.json to DIR")
    ap.add_argument("--diagnose", default="auto", choices=["auto", "on", "off"],
                    help="staged diagnosis-driven context (large IPs): auto "
                         "(on for >15-file IPs under a real model), on, off")
    ap.add_argument("--fresh-pool", action="store_true",
                    help="ignore prior banked wins — clean demo")
    ap.add_argument("--stage-batch", type=int, default=1,
                    help="new files per stage after the first "
                         "(default 1 = one file/stage, most reliable)")
    ap.add_argument("--k-first", type=int, default=6,
                    help="parallel candidates on stage 1 (worst file, "
                         "most important); k for later stages")
    ap.add_argument("--focus", default=None,
                    help="comma-separated file basenames: explicit staged "
                         "cursor override (targeted campaigns / DAC triage)")
    ap.add_argument("--fence", choices=["on", "off"], default="off",
                    help="scope fence (aes S-box). OFF by default — the "
                         "contest scores tests-pass + PPA only; keep 'on' "
                         "available as a security-conscious option")
    ap.add_argument("--grounding", choices=["on", "off", "stubs"], default="on",
                    help="staged-mode context: full critical files read-only "
                         "(on), batch file strictly alone (off), or interface "
                         "stubs of instantiated submodules (stubs, config C) "
                         "— A/B/C 2026-07-14")
    a = ap.parse_args(argv)

    # production registrations first (NVDLA): an explicit registry entry can
    # never fall through to generic discovery (SS11 step 1)
    from . import registry as _registry
    _registry.ensure_registered()

    if a.ip not in IPS:
        from .discover import get_spec, register
        spec = get_spec(a.ip)
        register(spec)
        a.ip = spec.name
        print(f"[discover] onboarded '{a.ip}': {len(spec.sources)} sources, "
              f"gate={spec.gate_dir}")

    kw = {}
    if a.model == "stub":
        kw["replay_dirs"] = [Path(d) for d in a.stub_replay]
    elif a.model == "vertex":
        kw = dict(model_name=a.model_name, temperature=a.temperature,
                  top_p=a.top_p, key_env=a.key_env)
    elif a.model == "endpoint":
        kw = dict(endpoint=a.endpoint, model_name=a.model_name)
    model = make_model(a.model, **kw)
    run(a.ip, a.rounds, a.k, model, mode=a.mode, workers=a.workers,
        max_calls=a.max_calls, max_tokens=a.max_tokens,
        emit_best=a.emit_best, diagnose=a.diagnose, stage_batch=a.stage_batch,
        fresh_pool=a.fresh_pool, k_first=a.k_first,
        grounding=a.grounding, fence=a.fence == "on",
        focus=[s.strip() for s in a.focus.split(",")] if a.focus else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
