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
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import IPS, LEDGER_DIR, REPO
from .workspace import Workspace, pristine_source
from . import evaluate as E
from . import skills
from . import sta_feedback as S
from .objective import Objective, ParetoFrontier
from .pool import DesignPool
from .proposer import (Model, PromptContext, build_prompt, build_reflect_prompt,
                       build_repair_prompt, make_model, parse_reflection,
                       parse_response, pick_strategies, LADDER)

_TAG_TO_RUNGS = {
    "arith-carry-chain": ["balanced-tree", "carry-save", "arith-arch"],
    "mux-select": ["restructure-select", "share-resources"],
    "wide-gate-decode": ["restructure-select"],
    "control-boolean-network": ["restructure-select", "micro-opt"],
    "mixed-comb-depth": ["balanced-tree", "micro-opt"],
}

_SDC_PERIODS = {"sha512": 1500.0, "async_fifo": 300.0,
                "ascon": 100.0}   # setup-critical clock (ascon: 10GHz, unmeetable)


def _dossier(ip: str) -> str:
    spec = IPS[ip]
    lines = [f"## Design dossier: {ip}"]
    lines.append(f"Top module: {spec.top}. Clocks: " +
                 ", ".join(f"{c.name} ({c.period_ns}ns sim)" for c in spec.clocks) +
                 ". Resets: " + ", ".join(f"{n} (active-{lvl})"
                                          for n, lvl in spec.resets) + ".")
    for rel in spec.sources:
        text = pristine_source(ip, rel)
        n = text.count("\n")
        lines.append(f"- {Path(rel).name}: {n} lines")
    if ip == "async_fifo":
        lines.append("NOTE: dual-clock CDC FIFO — synchronizers and gray-code "
                     "pointer properties are sacred (see AVOID bullets).")
    return "\n".join(lines)


def _budget_line(model: Model, max_calls: int, max_tokens: int) -> tuple[str, float]:
    frac = 1.0 - max(model.calls / max_calls if max_calls else 0,
                     model.tokens / max_tokens if max_tokens else 0)
    line = (f"<budget>LLM calls used {model.calls}/{max_calls}; tokens used "
            f"~{model.tokens}/{max_tokens}. Make the best use of the "
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
        emit_best: str | None = None) -> dict:
    spec = IPS[ip]
    obj = Objective(mode=mode, clk_period_ps=_SDC_PERIODS.get(ip))
    pool = DesignPool(ip)
    frontier = ParetoFrontier()

    # ── baseline state (measure + reports, cached) ───────────────────────────
    base = E.baseline(ip)
    base_ppa = base["ppa"]
    if "baseline" not in pool.states:
        pool.add("baseline", base_ppa,
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

    dossier = _dossier(ip)
    best_adp_history: list[float] = []
    summary = {"rounds": [], "accepted": 0}

    for rnd in range(1, rounds + 1):
        budget_line, frac = _budget_line(model, max_calls, max_tokens)
        k_now = _k_for_regime(k, frac)
        if k_now == 0:
            print(f"[{ip}] budget exhausted — stopping")
            break

        parent_cid, sel_mode = pool.select_parent()
        parent = pool.states[parent_cid]
        parent_files = (pool.files_of(parent_cid) if parent_cid != "baseline"
                        else {rel: pristine_source(ip, rel)
                              for rel in spec.sources})

        rep_dir = E.reports_dir(ip, parent_cid)
        if not (rep_dir / "sta_timing_paths.txt").exists():
            rep_dir = E.reports_dir(ip, "baseline")
        sta_block = S.feedback(rep_dir, top_k=3)
        tag = S.dominant_tag(rep_dir) or "mixed-comb-depth"

        preferred = _TAG_TO_RUNGS.get(tag, [])
        rungs = [r for r in LADDER if r["key"] in preferred][:k_now]
        if len(rungs) < k_now:
            more = pick_strategies(k_now - len(rungs), obj.weights,
                                   exclude={r["key"] for r in rungs})
            rungs += more
        if sel_mode == "deepen" and parent.strategy in {r["key"] for r in LADDER}:
            # push the parent's own strategy line first when deepening
            rungs.sort(key=lambda r: r["key"] != parent.strategy)

        bullets = skills.retrieve([tag], sections=None, k=5)
        ctx = PromptContext(
            ip=ip, files=parent_files, ppa=parent.ppa, sta_block=sta_block,
            playbook_block=skills.render(bullets), dossier=dossier,
            weights=obj.weights, budget_line=budget_line,
            ref_note=(f"(baseline for relative scoring: area="
                      f"{base_ppa['area']}, setup={base_ppa['setup']}ps)"))

        print(f"\n[{ip}] round {rnd}: parent={parent_cid[:12]} ({sel_mode}), "
              f"tag={tag}, k={k_now}, rungs={[r['key'] for r in rungs]}")

        with ThreadPoolExecutor(max_workers=k_now) as ex:
            resps = list(ex.map(
                lambda r: (r, model.generate(build_prompt(ctx, r))), rungs))

        cands = []
        for rung, resp in resps:
            _dump_raw(ip, rnd, rung["key"], resp)
            files = parse_response(ip, resp)
            if not files:
                print(f"  [{rung['key']}] no usable code blocks — skipped "
                      f"(raw kept in ledger/raw/{ip}/)")
                continue
            merged = dict(parent_files)
            merged.update(files)
            cands.append(E.Candidate(ip, merged, meta={
                "strategy": rung["key"], "parent": parent_cid, "round": rnd}))
        if not cands:
            summary["rounds"].append({"round": rnd, "accepted": 0,
                                      "note": "no candidates"})
            best_adp_history.append(best_adp_history[-1] if best_adp_history
                                    else 1.0)
            if _plateaued(best_adp_history, plateau_rounds, plateau_delta):
                print(f"[{ip}] plateau — stopping")
                break
            continue

        results = E.evaluate_many(cands, max_workers=workers,
                                  full_verify=True)

        # self-debug: compile failures get <=2 cheap repair attempts with the
        # tool stderr fed back (doesn't count as a full round)
        base_eval = E.baseline(ip)
        for i, (cand, res) in enumerate(zip(cands, results)):
            attempts = 0
            while (res.status in ("compile-fail", "regen-fail")
                   and attempts < 2 and _budget_line(model, max_calls,
                                                     max_tokens)[1] > 0.05):
                attempts += 1
                resp = model.generate(build_repair_prompt(
                    {r: t for r, t in cand.files.items()
                     if r not in parent_files or cand.files[r] != parent_files.get(r)},
                    res.detail or "unknown error"))
                fixed = parse_response(ip, resp)
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
            adp = (obj.adp_ratio(res.ppa, parent.ppa)
                   if res.ppa else None)
            reward = pool.reward_from_eval(res.status, adp)
            pool.backup(parent_cid, reward)
            verdict, reason = (obj.better(res.ppa, parent.ppa)
                               if res.status == "measured" and res.ppa
                               else (False, res.status))
            dualsim_ok = res.verify.get("dualsim", {}).get("status") == "PASS"
            if verdict and dualsim_ok:
                pool.add(cand.cid, res.ppa, cand.files, parent_cid,
                         cand.meta["strategy"])
                frontier.offer(cand.cid, res.ppa,
                               {"strategy": cand.meta["strategy"]})
                accepted += 1
                summary["accepted"] += 1
                print(f"  ACCEPT {cand.cid[:12]} [{cand.meta['strategy']}] "
                      f"{reason} | ADP vs parent={adp and round(adp, 3)}")
            else:
                print(f"  reject {cand.cid[:12]} [{cand.meta['strategy']}] "
                      f"{res.status}: {reason}")

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

    best = frontier.best(obj, base_ppa)
    summary.update({
        "best": best and {"cid": best["cid"], "ppa": best["ppa"],
                          "adp_vs_baseline": round(
                              obj.adp_ratio(best["ppa"], base_ppa) or 1.0, 4)},
        "frontier_size": len(frontier.entries),
        "calls": model.calls, "tokens": model.tokens})
    print(f"\n[{ip}] DONE: {json.dumps(summary['best'], indent=1)}\n"
          f"frontier={summary['frontier_size']} calls={model.calls} "
          f"tokens~{model.tokens} accepted={summary['accepted']}")
    if emit_best:
        _emit_best(ip, best, pool, base_ppa, summary, Path(emit_best))
    return summary


def _emit_best(ip: str, best, pool, base_ppa: dict, summary: dict,
               out_dir: Path):
    """Submission artifact: the winning candidate's files in repo-relative
    layout (drop-in over the contest repo) + manifest.json. Accepted
    candidates passed the full 5-layer verification (lint/compile/TB gate/
    yosys LEC/dual-instance differential sim) at acceptance time."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    if best and best["cid"] != "baseline":
        files = pool.files_of(best["cid"])
        for rel, text in files.items():
            dst = out_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text)
    manifest = {
        "ip": ip,
        "result": ("optimized" if files else
                   "no-improvement: baseline is the submission"),
        "cid": best["cid"] if best else None,
        "changed_files": sorted(files),
        "baseline_ppa": base_ppa,
        "best_ppa": best["ppa"] if best else None,
        "adp_vs_baseline": summary["best"]["adp_vs_baseline"]
        if summary.get("best") else None,
        "verification": ("full 5-layer at acceptance: lint, compile, TB "
                         "gate, yosys LEC (+async2sync), dual-instance "
                         "differential sim" if files else "baseline (n/a)"),
        "llm_calls": summary["calls"],
        "llm_tokens_approx": summary["tokens"],
        "rounds": summary["rounds"],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"[{ip}] emitted {'best candidate' if files else 'manifest only'} "
          f"-> {out_dir} ({len(files)} file(s))")


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
    a = ap.parse_args(argv)

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
                  top_p=a.top_p)
    elif a.model == "endpoint":
        kw = dict(endpoint=a.endpoint, model_name=a.model_name)
    model = make_model(a.model, **kw)
    run(a.ip, a.rounds, a.k, model, mode=a.mode, workers=a.workers,
        max_calls=a.max_calls, max_tokens=a.max_tokens,
        emit_best=a.emit_best)
    return 0


if __name__ == "__main__":
    sys.exit(main())
