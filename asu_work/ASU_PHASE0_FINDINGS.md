# ASU Improvement — Phase 0 + First Experiment: Findings (for review)

**Date:** 2026-07-15
**Basis:** executed the reviewer's revised plan (`ASU_IMPROVEMENT_PLAN_FINDINGS.md`): Phase 0
(runner/endpoint hardening, baseline freeze, connectivity policy) then the first falsifiable
experiment (S1 x-clear V2/M3 neck). This document reports what was done, the exact evidence, and the
decision point. **Please challenge the S1 falsification and the "consolidate" recommendation.**

**Headline:** Phase 0 *materially fixed the ASU submission* (it would otherwise have zero-scored),
and the S1 experiment is **cleanly falsified by exact DRC** — no x-clear V2/M3 neck is a net win,
because the neck's own shoulders trip `M3.S.4`. All changes are committed to
`chip-convergence-iclad26` (commits through `1e6a0251`).

---

## 1. Phase 0 — done; the P0 was submission-critical

### 1.1 ASU-P-01 (P0) — CONFIRMED real and FIXED
The reviewer predicted our agent's `usage.json` write aborts the official run. Verified against
`official_eval/run_official_eval.py`:
- the agent container runs `--read-only` with only `result`/`temp`/`/tmp` writable;
- the usage path (`/secure/usage/...`) is mounted **only into the wrapper**, not the agent;
- our agent wrote `usage.json` in model mode → write fails → nonzero exit →
  `subprocess.run(..., check=True)` raises **before scoring**.
**Impact:** ASU would have scored **zero** in model mode. **Fix:** usage write is now best-effort
(`try/except OSError`); verified it cannot crash. (`asu_agent.py`)

### 1.2 Endpoint hardened + crash-safe (ASU-P-11, §4.2)
Under the official runner, `--model <name>` is ALWAYS a model name → our agent ALWAYS runs
model/endpoint mode. So endpoint robustness is submission-critical, not optional. `EndpointModel`
now:
- sends `{model, prompt, max_output_tokens}` per AGENT_GUIDE;
- retries with exponential backoff on HTTP 429/500/502/503/504 and body `{"retryable": true}` /
  `provider_status`;
- **never raises** — returns `""` on unrecoverable failure so keep-best just ships the baseline;
- parses the nested `usage.total_tokens`.
The best-of-N loop is wrapped crash-safe. **Verified:** (a) unit test vs a mock endpoint
(success / retry-then-success / total-fail-no-crash); (b) full container run in model mode with a
host mock endpoint (`--model gemini-3.5-flash`) → unhelpful passes discarded → eligible baseline →
**exit 0**. This is the evidence that a model-enabled official run reaches the evaluator.

### 1.3 Five exact baselines FROZEN (ASU-P-04)
`asu_work/baselines/baseline_table.json` (rule-deck + evaluator hashes included):

| Block | reference | exact rerun | baseline FVR | eligible | conn | wall |
|---|---:|---:|---:|---|---|---:|
| Block1 | 244 | 315 | 1.2910 | yes | yes | 13.5 s |
| Block2 | 68 | 90 | 1.3235 | yes | yes | 11.8 s |
| Block3 | 89 | 111 | 1.2472 | yes | yes | 12.3 s |
| Block6 | 247 | 321 | 1.2996 | yes | yes | 13.4 s |
| Block7 | 765 | 957 | 1.2510 | yes | yes | 22.2 s |

Note: exact DRC ≈ **12–22 s/block**, faster than the plan's 40 s estimate (better search budget).

### 1.4 Connectivity policy = Option A (credible physical repair) — implemented (ASU-P-02/P-08)
The official checker parses SOURCE text and cannot see appended geometry mutations. We keep it as the
eligibility gate and add a **rendered-geometry credibility check** (`verify.py`
`_conn_signature` + `connectivity_credible`): net/component count + conducting area + per-layer shape
counts from the rendered GDS. **Verified it catches the exploit:** a candidate that deletes M2 passes
the official *static* checker ("preserved") but our check flags it — rendered nets 25 → 110. Winning
candidates must pass BOTH gates.

---

## 2. First experiment — S1 (x-clear V2/M3 neck) — FALSIFIED

### 2.1 What was built (the reviewer's precise recipe)
Orthogonal neck of M3 down to the via's y-extent, only in an x-window that avoids adjacent V3,
operating on the **flattened merged** M3 region (not just the top-level rectangle). x-clear predicate:
no V3 on the same M3 overlaps the neck window `[v2.left-endcap, v2.right+endcap]` (endcap = 5 nm =
20 dbu).

### 2.2 Full-pass result (Block1)
| rule | baseline | after x-clear neck |
|---|---:|---:|
| V2.M3.AUX.2 | 72 | **48** (fixed 24 x-clear sites) |
| M3.S.4 | 0 | **48** (new) |
| **total** | **315** | **339** |
- Connectivity credibility: **TRUE** (rendered nets unchanged) — first move to clear that bar.

### 2.3 Per-site result — the decisive data
Necking ONE site at a time (exact DRC delta vs baseline 315):
- center V2 (x-clear): **+1**
- left V2 (partial V3 overlap): **+3**
- right V2 (partial V3 overlap): **+3**

**Every single neck is net-positive (worse).** Root cause, exact: each neck fixes **1**
`V2.M3.AUX.2`, but its **two shoulders** each create an `M3.S.4` (minimum-parallel-run-length)
violation against the adjacent horizontal M3 routing track. **1 fixed − 2 created = net +1**, even at
the most feasible site. **The neck's own geometry is illegal.**

### 2.4 Conclusion
S1 — the reviewer's highest-priority experiment — is **ruled out by exact-DRC data**, not
speculation. This is the "small falsifiable experiment first" discipline working as intended: ~1 hour
of compute closed off the top strategy instead of a multi-day general legalizer. It also **sharpens
the characterization**: the via-width class resists even a *surgical, connectivity-credible* neck,
because M3 routing neighbors force the neck shoulders to violate `M3.S.4`.

---

## 3. Where the revised plan stands

| Plan phase / strategy | Status |
|---|---|
| Phase 0 (runner/endpoint, baselines, connectivity policy) | **DONE** — submission fixed + hardened |
| S1 (x-clear V2/M3 neck) | **FALSIFIED** with exact per-site DRC |
| S5 (isolated minority-class fix) | not run; low expected payoff — every class tested (grid/spacing/enclosure) cascaded, and now even a credible neck trips M3.S.4 |
| S4 (homolog/template mining) | not run; the site is already a via array (ASU-P-07); would need a legal unflagged homolog, uncertain |
| S2 (stack-widen + neighbor nudge) | not attempted; demoted by the review + our connectivity policy |
| S3 (declarative multimodal LLM) | not attempted; endpoint path is ready but the geometry problem is the barrier, not the proposer |

## 4. Honest assessment & the decision

**What we have now (strong, honest):**
- A **working, robust, credible** ASU submission (Phase 0 fixed a zero-score P0 + hardened the
  endpoint + added a real credibility gate).
- A **rigorous, exact-DRC-backed characterization**: the dominant via-width class (~74% of every
  block) resists local repair, and specifically resists the surgical x-clear neck because the neck's
  shoulders trip `M3.S.4`.

**What we do NOT have:** a sub-baseline repair. Odds of finding one via S4/S5 in the remaining
window look low given the consistent cascading.

**Recommendation (challenge this):** **consolidate and ship.** The Phase 0 hardening is the real
prize; S1's clean falsification is a credible result, not a failure. Continuing to spend compute on
S4/S5 is defensible but low-EV against a real deadline.

## 5. Open questions for the reviewer

1. **Is S1 truly dead, or is there a neck variant that avoids `M3.S.4`?** e.g. only neck sites whose
   shoulders are >parallel-run-distance from any other M3 (a stricter predicate) — but per-site data
   shows even the isolated center site is +1, so the adjacent track is always close. Is there a block
   where an x-clear site is ALSO M3-neighbor-clear?
2. **Is `M3.S.4` avoidable by a non-neck move** that still gives V2 two coincident M3 edges (e.g.
   extend the via along M3 length rather than reshape M3)? We have not tried via-side reshapes that
   keep M3 intact.
3. **Is S5 worth the compute?** Given every class cascades, is there a genuinely isolated minority
   violation (no via, no neighbor) on any block — or should we accept the characterization?
4. **Given the deadline, is "consolidate + ship the hardened submission + sharpened characterization"
   the right call, or is one more targeted experiment (which?) worth it?**

## 6. Reproduction

- Phase 0 code: `asu_work/agent/{asu_agent,model_repair,verify}.py`; baselines
  `asu_work/baselines/baseline_table.json`; full log `asu_work/ASU_DAILY_RUN_LOG.md`.
- S1 experiment scripts are transient (in the container run); the exact per-site deltas and the
  full-pass per-rule table are in the daily log (2026-07-15 entries).
- Everything runs in `asu-klayout:0.30.1`; `verify.measure(script, ctx, want_conn_sig=True)` returns
  the exact-DRC Result + rendered-connectivity signature.
