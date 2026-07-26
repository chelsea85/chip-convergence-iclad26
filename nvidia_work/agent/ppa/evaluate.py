"""Candidate evaluation: cheap proxy pre-filter, full synth+STA measurement,
parallel workers, and the JSONL ledger.

Pipeline per candidate (each stage only if the previous passed):
  verify layers 1-3 (lint/compile/TB gate)
    -> proxy   yosys stat+ltp in seconds: gate-count + longest topological
               path + bag-of-gates fingerprint. Kills obviously-worse
               candidates and near-duplicates before paying for synthesis.
    -> measure full Yosys synth + OpenSTA via harness measure.sh
    -> (optional) verify layers 4-5 (LEC + dualsim) for accept-grade candidates

Every evaluation appends a record to ledger/<ip>.jsonl — the raw material for
the proposer's feedback, the skill library, and offline prompt evolution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .config import IPS, LEDGER_DIR, IPSpec, IMAGE
from .workspace import (RegenError, Workspace, candidate_from_dir,
                        pristine_source)
from . import verify as V

_LEDGER_LOCK = threading.Lock()


# ── data types ────────────────────────────────────────────────────────────────
@dataclass
class Candidate:
    ip: str
    files: dict[str, str]              # repo-relative path -> content
    cid: str = ""
    meta: dict = field(default_factory=dict)   # strategy, parent, prompt id...

    def __post_init__(self):
        if not self.cid:
            h = hashlib.sha256()
            for rel in sorted(self.files):
                h.update(rel.encode())
                h.update(self.files[rel].encode())
            self.cid = h.hexdigest()[:12]


@dataclass
class EvalResult:
    cid: str
    status: str                        # accepted-for-scoring pipeline status
    verify: dict = field(default_factory=dict)
    proxy: dict | None = None
    ppa: dict | None = None
    detail: str = ""
    wall_s: float = 0.0

    def row(self) -> str:
        p = self.ppa or {}
        return (f"{self.cid} {self.status:<12} "
                f"area={p.get('area', '-')} setup={p.get('setup', '-')} "
                f"cells={p.get('cells', '-')} ({self.wall_s:.0f}s)")


# ── proxy pre-filter (yosys stat + ltp, seconds) ─────────────────────────────
_PROXY_SCRIPT = ("read_verilog -sv {srcs}; hierarchy -check -top {top}; "
                 "proc; memory; flatten; opt -fast; techmap; opt -fast; "
                 "stat; ltp -noff")


def proxy_metrics(ws: Workspace) -> dict | None:
    spec = ws.spec
    cmd = _PROXY_SCRIPT.format(srcs=" ".join(spec.sources), top=spec.top)
    r = ws.run(f"yosys -p '{cmd}' 2>&1", timeout=600)
    out = r.stdout + r.stderr
    if r.returncode != 0:
        return None
    # yosys 0.63 stat table: "  449 cells" then indented "   60   $_AND_" rows
    cells = None
    hist: dict[str, int] = {}
    stat_m = re.search(r"^\s+(\d+) cells\s*$(.*?)(?:\n\n|\Z)", out, re.S | re.M)
    if stat_m:
        cells = int(stat_m.group(1))
        for n, t in re.findall(r"^\s+(\d+)\s+(\$?[A-Za-z0-9_$]+)\s*$",
                               stat_m.group(2), re.M):
            hist[t] = hist.get(t, 0) + int(n)
    depth_m = re.search(r"Longest topological path.*\(length=(\d+)\)", out)
    depth = int(depth_m.group(1)) if depth_m else None
    if cells is None or depth is None:
        return None
    return {"cells": cells, "depth": depth, "hist": hist}


def fingerprint_cosine(h1: dict[str, int], h2: dict[str, int]) -> float:
    keys = set(h1) | set(h2)
    dot = sum(h1.get(k, 0) * h2.get(k, 0) for k in keys)
    n1 = math.sqrt(sum(v * v for v in h1.values())) or 1.0
    n2 = math.sqrt(sum(v * v for v in h2.values())) or 1.0
    return dot / (n1 * n2)


def proxy_verdict(cand: dict, base: dict, slack_pct: float = 5.0) -> str:
    """'worse' only when BOTH depth and cells regress beyond noise — a depth
    win at cell cost (or vice versa) must go to real synthesis."""
    d_up = cand["depth"] > base["depth"] * (1 + slack_pct / 100)
    c_up = cand["cells"] > base["cells"] * (1 + slack_pct / 100)
    return "worse" if (d_up and c_up) else "ok"


# ── full measurement (synth + STA via harness) ───────────────────────────────
_PPA_RE = re.compile(
    r"area=(\S+)\s+cells=(\S+)\s+ff=(\S+)\s+\|\s+setup=(\S+)ps\s+hold=(\S+)ps"
    r"\s+\[(\w+)\]\s+\|\s+pwr=(\S+)W")


# mandatory scoring metrics; area/cells/ff/power must be finite AND > 0,
# setup/hold must be finite (may be <= 0). Any violation => measurement rejected.
_MEASURE_SCHEMA = "top-area-v2"
_REQ_POSITIVE = ("area", "cells", "ff", "power")
_REQ_FINITE = ("setup", "hold")


def measure(ws: Workspace, label: str = "m") -> dict | None:
    """Full synth+STA measurement. FAIL CLOSED: returns None (never a partial
    dict) if measure.sh exits nonzero or any mandatory metric is missing/
    nonnumeric/nonfinite — so a bogus baseline or candidate is never cached or
    compared. measure.sh already exits nonzero when it cannot parse a metric."""
    spec = ws.spec
    r = ws.run(f"bash /harness/measure.sh {spec.syn_dir} {label} RVT TT 0 "
               f"{spec.skip_sv2v} {spec.top}", timeout=7200)
    if getattr(r, "returncode", 1) != 0:
        return None
    line = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
    m = _PPA_RE.search(line)
    if not m:
        return None

    def num(s):
        try:
            v = float(s)
        except (TypeError, ValueError):
            return None
        return v if math.isfinite(v) else None

    ppa = {"area": num(m[1]), "cells": num(m[2]), "ff": num(m[3]),
           "setup": num(m[4]), "hold": num(m[5]), "timing_met": m[6] == "MET",
           "power": num(m[7])}
    if any(ppa[k] is None or ppa[k] <= 0 for k in _REQ_POSITIVE):
        return None
    if any(ppa[k] is None for k in _REQ_FINITE):
        return None
    return ppa


def _save_reports(ws: Workspace, cand: Candidate):
    """Keep the STA reports of measured candidates for sta_feedback."""
    src = ws.root / IPS[cand.ip].syn_dir / "reports"
    dst = reports_dir(cand.ip, cand.cid)
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("sta_timing_*.txt"):
        (dst / f.name).write_text(f.read_text())


def reports_dir(ip: str, cid: str) -> Path:
    return LEDGER_DIR / "reports" / ip / cid


# ── ledger ────────────────────────────────────────────────────────────────────
def ledger_append(ip: str, record: dict):
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **record}
    with _LEDGER_LOCK:
        with open(LEDGER_DIR / f"{ip}.jsonl", "a") as f:
            f.write(json.dumps(record) + "\n")


def ledger_read(ip: str) -> list[dict]:
    p = LEDGER_DIR / f"{ip}.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


# ── baseline (cached) ─────────────────────────────────────────────────────────
def baseline(ip: str, refresh: bool = False) -> dict:
    cache = LEDGER_DIR / f"{ip}_baseline.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    ws = Workspace.create(ip, tag="baseline")
    try:
        prox = proxy_metrics(ws)
        ppa = measure(ws, f"{ip}-base")
        # FAIL CLOSED: a failed/invalid measurement must NOT be cached and must
        # NEVER overwrite an existing known-good cache with null metrics.
        if not ppa:
            raise RuntimeError(
                f"baseline measurement for {ip} failed (missing/invalid metric); "
                f"refusing to write baseline cache")
        data = {"ppa": ppa, "proxy": prox, "schema": _MEASURE_SCHEMA,
                "image": IMAGE}
        LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, indent=1))
        return data
    finally:
        ws.destroy()


# ── per-candidate pipeline ────────────────────────────────────────────────────
_PRISTINE_LAYER_CACHE: dict[tuple, bool] = {}
_PRISTINE_LOCK = threading.Lock()


def _pristine_layer_fails(ip: str, layer: str) -> bool:
    """Does this verify layer fail on the PRISTINE design? Cached per IP.
    Used for differential gating: pre-existing fileset artifacts must not
    block candidates (they fail with or without the change). Lock-guarded so
    that k parallel workers do exactly ONE pristine build (unique tag), not a
    directory-colliding race."""
    key = (ip, layer)
    with _PRISTINE_LOCK:
        if key not in _PRISTINE_LAYER_CACHE:
            ws = Workspace.create(ip, tag=f"prist_{layer}_{os.getpid()}")
            try:
                fn = {"compile": V.compile_gate, "gate": V.tb_gate}[layer]
                status, _ = fn(ws)
                _PRISTINE_LAYER_CACHE[key] = status == "FAIL"
            finally:
                ws.destroy()
    return _PRISTINE_LAYER_CACHE[key]


def measure_candidate(cand: Candidate) -> dict | None:
    """Synthesize+STA a candidate to get its PPA, regardless of functional
    correctness. Used to rank GATE-FAILED candidates for repair: a broken
    netlist's timing still reveals whether its transform would improve PPA if
    the functional bug were fixed (2026-07-13, PPA-prioritised repair)."""
    ws = Workspace.create(cand.ip, cand.files, tag="mc_" + cand.cid[:6])
    try:
        return measure(ws, f"{cand.ip}-mc-{cand.cid[:6]}")
    except Exception:
        return None
    finally:
        ws.destroy()


def evaluate_one(cand: Candidate, base: dict, *,
                 use_proxy: bool = True,
                 full_verify: bool = False,
                 seen_fingerprints: list[tuple] | None = None) -> EvalResult:
    t0 = time.time()
    spec = IPS[cand.ip]
    res = EvalResult(cid=cand.cid, status="?")

    vr = V.VerifyResult()
    status, detail = V.lint(spec, cand.files)
    vr.record("lint", status, detail)
    if not vr.ok:
        res.status, res.detail = "lint-fail", detail
        return _finish(cand, res, vr, t0)

    try:
        ws = Workspace.create(cand.ip, cand.files, tag=cand.cid[:8])
    except RegenError as e:
        vr.record("regen", "FAIL", str(e))
        res.status, res.detail = "regen-fail", str(e)
        return _finish(cand, res, vr, t0)
    try:
        status, detail = V.compile_gate(ws)
        if status == "FAIL" and _pristine_layer_fails(cand.ip, "compile"):
            # DIFFERENTIAL GATING (2026-07-13, kmac finding): the pristine
            # fileset itself fails this iverilog layer (sv2v artifact — e.g.
            # kmac's hw2reg variable driven by an instance output; legal SV,
            # illegal V2001; yosys accepts it fine). A layer that fails
            # identically on pristine cannot indict the candidate.
            vr.record("compile", "PRE-EXISTING", detail[-200:])
            status = "PRE-EXISTING"
        else:
            vr.record("compile", status, detail)
        if status == "FAIL":
            res.status, res.detail = "compile-fail", detail
            return _finish(cand, res, vr, t0)

        if status != "PRE-EXISTING":
            status, detail = V.tb_gate(ws)
            vr.record("gate", status, detail)
            if status == "FAIL":
                res.status, res.detail = "gate-fail", detail
                return _finish(cand, res, vr, t0)
        else:
            # no iverilog elaboration -> TB/dualsim unavailable; LEC (yosys)
            # remains the correctness gate for this IP
            vr.record("gate", "SKIP-preexisting", "")

        if use_proxy:
            res.proxy = proxy_metrics(ws)
            if res.proxy and base.get("proxy"):
                if seen_fingerprints is not None:
                    # exact structural profile match only — cosine similarity
                    # falsely merges large designs that differ in 1000s of cells
                    fp_now = (res.proxy["depth"], tuple(sorted(res.proxy["hist"].items())))
                    if fp_now in seen_fingerprints:
                        res.status = "duplicate"
                        return _finish(cand, res, vr, t0)
                    seen_fingerprints.append(fp_now)
                if proxy_verdict(res.proxy, base["proxy"]) == "worse":
                    res.status = "proxy-reject"
                    res.detail = (f"depth {base['proxy']['depth']}->"
                                  f"{res.proxy['depth']}, cells "
                                  f"{base['proxy']['cells']}->{res.proxy['cells']}")
                    return _finish(cand, res, vr, t0)

        res.ppa = measure(ws, f"{cand.ip}-{cand.cid[:8]}")
        if not res.ppa:
            res.status = "synth-fail"
            return _finish(cand, res, vr, t0)
        _save_reports(ws, cand)

        if full_verify:
            status, detail = V.lec(ws)
            vr.record("lec", status, detail)
            if vr.layers.get("compile") == "PRE-EXISTING":
                vr.record("dualsim", "SKIP-preexisting", "")
            else:
                status, detail = V.dualsim(ws)
                vr.record("dualsim", status, detail)
                if status == "FAIL":
                    res.status, res.detail = "dualsim-fail", detail
                    return _finish(cand, res, vr, t0)

        res.status = "measured"
        return _finish(cand, res, vr, t0)
    finally:
        ws.destroy()


def _finish(cand: Candidate, res: EvalResult, vr: V.VerifyResult,
            t0: float) -> EvalResult:
    res.verify = vr.layers
    res.wall_s = time.time() - t0
    ledger_append(cand.ip, {
        "cid": cand.cid, "status": res.status, "meta": cand.meta,
        "verify": {k: v["status"] for k, v in vr.layers.items()},
        # Retain the normalized proof note (recipe/rc/total/proven/unproven)
        # and other layer details. Status-only ledgers made the 2026-07-24
        # banking review unable to audit LEC counts after workspaces were
        # destroyed.
        "verify_evidence": {
            k: v["detail"] for k, v in vr.layers.items() if v["detail"]},
        "proxy": {k: v for k, v in (res.proxy or {}).items() if k != "hist"},
        "ppa": res.ppa, "wall_s": round(res.wall_s, 1),
        "detail": res.detail[:500]})
    return res


# ── parallel driver ───────────────────────────────────────────────────────────
def _refuse_tmake(ip: str, where: str):
    """Explicit fail-closed dispatch (corrective review SS4.9): tmake IPs are
    evaluated ONLY by ppa.orchestrate - the legacy spec.sources path cannot
    express their contract and must refuse, not accidentally fail."""
    from . import contract as _C
    if _C.get_contract(IPS[ip]).name == "tmake":
        raise _C.ContractError(
            f"{where}: tmake contract '{ip}' must be evaluated through "
            f"ppa.orchestrate.evaluate_tmake_candidate (legacy evaluator "
            f"refuses tmake)")


def _tmake_image_digest() -> str:
    """Resolve the immutable local image identity used by evaluation IDs."""
    from . import contract as _C
    r = subprocess.run(
        ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"],
        capture_output=True, text=True)
    digest = (r.stdout or "").strip()
    if r.returncode != 0 or not (
            digest.startswith("sha256:")
            and _C._is_sha256(digest[7:])):
        raise _C.ContractError(
            f"cannot bind tmake evaluation to {IMAGE!r} image digest")
    return digest


def _evidence_ref(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _valid_ppa(ppa) -> bool:
    if not isinstance(ppa, dict):
        return False
    for k in _REQ_POSITIVE:
        v = ppa.get(k)
        if (not isinstance(v, (int, float)) or isinstance(v, bool)
                or not math.isfinite(v) or v <= 0):
            return False
    return all(isinstance(ppa.get(k), (int, float))
               and not isinstance(ppa.get(k), bool)
               and math.isfinite(ppa.get(k)) for k in _REQ_FINITE)


def _tmake_adapter_result(cand: Candidate, rec: dict,
                          wall_s: float) -> EvalResult:
    """Map rich policy evidence to the legacy controller's narrow result.

    Only an eligible policy row can become ``measured``.  Diagnostic PPA may
    be retained on an ineligible result (notably PENDING validation), but the
    controller cannot pool it because the status remains non-measured.
    """
    verify = rec.get("verify") if isinstance(rec.get("verify"), dict) else {}
    ppa = rec.get("ppa") if _valid_ppa(rec.get("ppa")) else None
    gate = rec.get("gate") or {}
    proof = rec.get("proof") or {}
    meas = rec.get("measurement") or {}
    classification = rec.get("classification")

    if classification != "proceed":
        status = "regen-fail"
    elif not gate.get("passed"):
        status = ("gate-fail" if gate.get("tests", [0, 0])[1] > 0
                  else "gate-flow-fail")
    elif proof.get("verdict") != "PROVEN":
        status = ("lec-error" if proof.get("verdict") == "ERROR"
                  else "lec-inconclusive")
    elif not meas.get("ok") or ppa is None:
        status = "synth-fail"
    elif rec.get("refusal_reason") == "CONTRACT_VALIDATION_PENDING":
        status = "contract-pending"
    elif not rec.get("eligible"):
        status = "policy-reject"
    else:
        status = "measured"
    return EvalResult(
        cid=rec.get("cid") or cand.cid, status=status, verify=verify,
        ppa=ppa, detail=rec.get("detail") or rec.get("assurance", ""),
        wall_s=wall_s)


def _evaluate_tmake_many(cands: list[Candidate], *, scope, profile,
                         container_digest: str | None,
                         tool_versions: dict | None) -> list[EvalResult]:
    from . import contract as _C
    from . import gate as _G
    from . import measure_tmake as _MT
    from . import orchestrate as _O
    from . import policy as _P
    from .proposer import fence_violation

    ip = cands[0].ip
    plan = _G.get_gate_plan(ip)
    provider = _MT.get_measure_provider(ip)
    if plan is None or provider is None or scope is None:
        missing = [
            name for name, value in (
                ("canonical gate plan", plan),
                ("measurement provider", provider),
                ("campaign scope", scope))
            if value is None]
        _refuse_tmake(ip, "evaluate_many (partial tmake wiring: "
                      + ", ".join(missing) + ")")
    ctr = _C.get_contract(IPS[ip])
    _C.check_scope_compat(ctr, scope)
    base = baseline(ip)
    period_ps = (IPS[ip].clocks[0].period_ns * 1000.0
                 if IPS[ip].clocks else None)
    if not period_ps or period_ps <= 0:
        raise _C.ContractError(
            f"{ip}: tmake measurement requires a positive clock period")
    image_digest = container_digest or _tmake_image_digest()
    versions = tool_versions or {"toolchain_image": IMAGE}

    out = []
    for cand in cands:
        t0 = time.time()
        violation = fence_violation(ip, cand.files)
        checks_payload = {
            "schema": "tmake-template-scope-check-v1",
            "ip": ip, "scope": scope.scope_id(),
            "paths": sorted(cand.files), "fence_violation": violation,
        }
        checks = _P.CheckEvidence(
            ok=violation is None, ref=_evidence_ref(checks_payload))
        proxy = _P.CheckEvidence(
            ok=True, ref=_evidence_ref({
                "schema": "tmake-proxy-policy-v1",
                "decision": "full measurement required; cheap legacy proxy "
                            "does not express contract inputs"}))
        budget_ok = cand.meta.get("budget_authorized") is True
        budget = _P.CheckEvidence(
            ok=budget_ok, ref=_evidence_ref({
                "schema": "controller-budget-v1",
                "authorized": budget_ok,
                "round": cand.meta.get("round"),
                "strategy": cand.meta.get("strategy"),
            }))
        record = []
        full_cid = _O.source_cid(cand.files)
        measure_fn = provider(
            base["ppa"], period_ps, label=f"{ip}-{full_cid[:12]}",
            record=record)
        rec = _O.evaluate_tmake_candidate(
            ip, cand.files, scope, plan, profile=profile,
            measure_fn=measure_fn, checks=checks, proxy=proxy, budget=budget,
            container_digest=image_digest, tool_versions=versions)
        out.append(_tmake_adapter_result(cand, rec, time.time() - t0))
    return out


def _clamped_workers(ip: str, requested: int) -> int:
    """Contract hard worker cap consumed at the executor (SS11 step 3 /
    SSH.5): min(requested, contract cap). NVDLA/tmake: 1 (743 MB workspaces +
    regeneration cost). The clamp is logged - never silent."""
    from . import contract as _C
    cap = _C.get_contract(IPS[ip]).worker_cap()
    if requested > cap:
        print(f"[{ip}] workers clamped {requested} -> {cap} "
              f"(contract hard cap)")
        return cap
    return requested


def evaluate_many(cands: list[Candidate], *, max_workers: int = 4,
                  use_proxy: bool = True, full_verify: bool = False,
                  scope=None, profile=None, container_digest: str | None = None,
                  tool_versions: dict | None = None) -> list[EvalResult]:
    assert cands
    ip = cands[0].ip
    if any(c.ip != ip for c in cands):
        raise ValueError(f"evaluate_many: mixed-IP batch "
                         f"({sorted({c.ip for c in cands})}) - the contract "
                         f"worker cap and baseline are per-IP authorities")
    from . import contract as _C
    if _C.get_contract(IPS[ip]).name == "tmake":
        max_workers = _clamped_workers(ip, max_workers)
        return _evaluate_tmake_many(
            cands, scope=scope, profile=profile,
            container_digest=container_digest, tool_versions=tool_versions)
    max_workers = _clamped_workers(ip, max_workers)
    base = baseline(ip)
    fps: list[tuple] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(evaluate_one, c, base, use_proxy=use_proxy,
                          full_verify=full_verify, seen_fingerprints=fps)
                for c in cands]
        return [f.result() for f in futs]


# ── CLI ───────────────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description="evaluate RTL candidates")
    ap.add_argument("--ip", required=True,
                    help="IP name or repo-relative path; unknown names are "
                         "auto-discovered (hidden testcases)")
    ap.add_argument("--baseline", action="store_true",
                    help="(re)measure and cache the pristine baseline")
    ap.add_argument("--variant-dir", action="append", default=[],
                    help="evaluate variant dir(s); repeatable for parallel runs")
    ap.add_argument("--full-verify", action="store_true",
                    help="also run LEC + dualsim on measured candidates")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-proxy", action="store_true")
    a = ap.parse_args(argv)

    if a.ip not in IPS:
        from .discover import get_spec, register
        spec = get_spec(a.ip)
        register(spec)
        a.ip = spec.name
        print(f"[discover] onboarded '{a.ip}'")

    if a.baseline:
        data = baseline(a.ip, refresh=True)
        print(json.dumps(data["ppa"], indent=1))
        print("proxy:", {k: v for k, v in (data["proxy"] or {}).items()
                         if k != "hist"})
        return 0

    cands = [Candidate(a.ip, candidate_from_dir(a.ip, Path(d)),
                       meta={"variant_dir": d}) for d in a.variant_dir]
    assert cands, "--baseline or --variant-dir required"
    t0 = time.time()
    results = evaluate_many(cands, max_workers=a.workers,
                            use_proxy=not a.no_proxy,
                            full_verify=a.full_verify)
    for r in results:
        print(r.row())
        if r.detail:
            print(f"    {r.detail[:300]}")
    print(f"total wall: {time.time() - t0:.0f}s for {len(cands)} candidate(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
