---
marp: true
theme: default
paginate: true
size: "16:9"
style: |
  section { font-size: 24px; padding: 48px 60px; }
  h1 { font-size: 40px; color: #1a3a6b; }
  h2 { font-size: 32px; color: #1a3a6b; }
  table { font-size: 20px; }
  code { font-size: 18px; }
  pre { font-size: 16px; line-height: 1.25; }
  section.lead h1 { font-size: 48px; }
  section.lead { text-align: center; }
  .ok { color: #1a7a2a; font-weight: 600; }
  .bad { color: #b03030; font-weight: 600; }
  footer { font-size: 14px; color: #888; }
footer: "Chip Convergence — ICLAD-DAC 2026 — NVIDIA RTL PPA Optimization"
---

<!-- _class: lead -->
<!-- _footer: "" -->

# Verify Everything, Learn From Every Round

## Measured, equivalence-gated RTL PPA optimization

**sha512: ADP 0.787, timing −97 ps → +235 ps (MET), LEC-proven —
and the agent found the same trick on its own**

Harikrishnan KC · Team **Chip Convergence** · greatharikrishnan@gmail.com
NVIDIA Problem · ICLAD-DAC 2026 GenAI Chip Hackathon

---

# The problem, and what actually scores

**Given:** 7 IPs (async_fifo, sha512, NVDLA, OpenTitan aes/ascon/kmac/prim), Verilator/
iverilog testbenches, a Yosys+OpenSTA ASAP7 flow. **Rewrite RTL to improve PPA.**

**Evaluation (per the organizers):** functional correctness with the existing testbenches
first; then PPA after Yosys, plus **LLM calls and token cost**.

**Why this is hard** (Alpha-RTL, ICCAD'24 lineage): on async_fifo, **every published
LLM-rewriting method scored zero** — no compilable, correct rewrite. Unverified "optimizations"
are noise; the synthesizer absorbs or breaks most local edits.

**Our headline metric:** baseline-normalized **Area-Delay-Product ratio**, functional- and
equivalence-gated, token-conscious.

---

# Thesis: nothing counts until it survives five gates and a measurement

```
        propose (k strategies)          ← prompt ladder + learned playbook + STA feedback
          │
        verify: lint → compile → TB gate → yosys LEC (+async2sync) → dual-instance
          │                                differential simulation
        measure: Docker Yosys synth + OpenSTA (parallel APFS-clone workspaces)
          │
        select: Pareto frontier / ADP, accept only measured strict improvement
          │
        learn: Thompson parent sampling · ACE playbook · reflector
```

**Accepted ⇒ formally equivalent AND measurably better.** Everything else is rejected
with a typed reason that feeds the next round.

---

# Headline result: sha512, LEC-proven

| Metric | Baseline | Optimized (exp2) | Δ |
|---|---|---|---|
| WNS | **−97.30 ps** (violated) | **+235.36 ps** <span class="ok">(MET)</span> | +332.66 ps |
| Area | 3984.2 µm² | 3960.3 µm² | −0.6% |
| Cells | 29,307 | 28,955 | −1.2% |
| Power (our flow) | 2.92 mW | 2.23 mW | −24% |
| **ADP ratio** | 1.000 | **0.787** | **−21.3%** |

Technique: serial N-operand addition chains → balanced adder trees (mod-2ʷ associativity ⇒
provably equivalent). **yosys LEC: PROVEN. Differential sim: PASS.**

Plus: a gate-passing, LEC-proven async_fifo variant — on the IP where published methods score 0.

---

# Honest measurement as a feature: the aes baseline story

While onboarding OpenTitan aes we found the shipped flow **silently broken**:

- `generated/all_modules.v` duplicates all 84 per-module files
- under `SKIP_SV2V=1`, yosys hits re-definition ERRORs — **masked by the run script's
  success banner**; no netlist is ever written
- the recorded aes baseline (−1083.58 ps) is **invalid**; clean baseline = **−848.15 ps**

Our workspaces auto-drop the duplicate file (contest repo untouched); every baseline we
report is re-derived from a pristine clone through one flow. **Toolkit bug #1 of 3 we found**
(the other two in the NXP toolkit — see our NXP deck).

---

# Live with Gemini (Jul 12): the empty-response mystery

First real rounds: proposals came back **empty** while consuming ~20k tokens each.

Probe on a real prompt:

```
finish_reason: MAX_TOKENS   parts: 0
thoughts_token_count: 62,913   candidates: 2,619
```

`gemini-3-flash-preview` **thinks by default** and burned the entire cap on thoughts.

**Fixes now in the agent:** explicit `max_output_tokens` + bounded `thinking_config`;
token accounting uses `total_token_count` (thoughts are billed!); empty-text retry;
raw responses archived for postmortems; fence-parsing fallback (models ignore format
instructions ~2/3 of the time).

---

# Live: the agent's first verified accepts

```
[sha512] round 1: parent=baseline, tag=arith-carry-chain, k=3
  reject 4f97bf841af0 [balanced-tree]  duplicate
  reject 78633e719135 [carry-save]     gate-fail
  ACCEPT 3939ed94c02f [arith-arch]     improves perf, regresses none | ADP 0.898
```

then, two rounds later, **composition** via Thompson parent sampling:

```
[sha512] round 2: parent=3939ed94c02f (arith-arch)
  ACCEPT e7fee825c983 [restructure-select]  improves perf,area | ADP vs parent=0.985
```

→ model-generated line at **≈0.884 vs baseline**, every layer verified.
Banked exp2 (**0.787**) remains global best — and is what the agent emits.

---

# The duplicate moment (validation money-shot)

In the same round, Gemini proposed the balanced-adder-tree rewrite — **independently
reinventing our hand-derived winning technique.**

```
reject 4f97bf841af0 [balanced-tree] duplicate: duplicate
```

- the **fingerprint dedup** recognized it instantly — **zero wasted synthesis, zero
  wasted verification**
- the strategy playbook and the model converge on the same transformations —
  evidence the approach generalizes rather than being hand-crafted luck

---

# The learning loop is real

**Playbook (ACE-style): 23 measured rules.** From measured no-ops (exp3/exp4):

> *AVOID: local restructuring (mux folding, operand swap) — ABC absorbs it;
> only global algebraic changes survive synthesis.*

**Live-learned (Jul 12), written by the reflector after a real gate-fail:**

> *(sha512) Manual carry-save (3:2 compressor) insertion can lead to gate-level
> synthesis flow failures.*

Rules are voted helpful/harmful per round (Beta posterior) and injected into future
prompts — failures compound into guidance, not just logs.

---

# Hidden testcases: drilled, not hoped for

**Auto-discovery** builds an IPSpec from repo conventions (env.sh, filelists, SDC, TB
runners): fixtures match the hand registry 3/3; aes/kmac/prim/**NVDLA (323 sources)**
onboard zero-config.

**Cold-start drill** (`test_cold_start.py`, repeatable, 6/6): plant an unseen IP → discover
→ fresh baseline → propose → verify → measure → decide.

The drill **caught a real scoring hazard**: discovery keyed IPs by `env.sh DESIGN_NAME`,
so a hidden testcase colliding with a known name would have been scored against the
**wrong cached baseline**. Fixed (location-derived keys) — found by drilling, not luck.

---

# Submission artifact: `--emit-best`

Every campaign ends with a drop-in artifact — even a no-improvement one (explicit manifest
beats silence):

```json
{
 "ip": "sha512",  "result": "optimized",
 "changed_files": ["sha512/src/rtl/sha512.v", "..." ],
 "baseline_ppa": {"area": 3984.2, "setup": -97.30, ...},
 "best_ppa":     {"area": 3960.3, "setup": 235.36, ...},
 "adp_vs_baseline": 0.787,
 "verification": "full 5-layer at acceptance: lint, compile, TB gate,
                  yosys LEC (+async2sync), dual-instance differential sim",
 "llm_calls": 7, "llm_tokens_approx": 202931
}
```

Files land in repo-relative layout — the evaluator (or a human) drops them straight in.

---

# Token economics

| Mechanism | Effect |
|---|---|
| Budget regimes (70/30/10) + `<budget>` line in prompts | model knows its remaining budget |
| Plateau stop (frontier ADP flat) | no burn on converged IPs |
| Proxy pre-filter (yosys stat/ltp) + exact-fingerprint dedup | cheap rejection before synthesis |
| Measured round cost | ~112k tokens (k=3, thinking included), ~2.3 min |
| Thinking budget capped | unbounded = 63k thought tokens for zero output |

All calls/tokens ledgered per round; usage extractable exactly as the organizers evaluate.

---

# Model-agnostic interface

- `--model vertex` — google-genai; auto-detects **Vertex Express Mode** key (the organizers'
  eval path, AgentSetup.md) or AI Studio key; retry ladder on 429/5xx
- `--model endpoint` — NXP-runner-style HTTP model service, in case eval fronts Vertex
- `--model stub` — full offline loop for CI (replayable variants)
- `--model-name`, `--temperature/--top-p` — the decoding-config sweep + model-mixing knobs

Mock-SDK test exercises the real code path with no network: **13/13**
(both key modes, usage accounting, retry behavior, endpoint protocol).

---

# By DAC (agents updatable through Jul 26)

- **Decoding-config sweep** (temp 0–0.4 / top_p 0.4–0.7) + **model mixing** (pro for
  proposals, flash for repairs) — on the Jul-19 unlimited-Gemini accounts
- **aes GF/tower-field + kmac Keccak-θ campaigns** — the ABC-resistant headroom our
  survey identified
- NVDLA baseline; GEPA offline prompt evolution
- Live-testcase runbook: triage tree, budgets, panic modes (in repo)

---

# Summary — every claim, one command

| Claim | Reproduce with |
|---|---|
| Loop offline e2e | `python3 -m ppa.controller --ip async_fifo --rounds 1 --k 1 --model stub` |
| Fresh baseline (Docker) | `python3 -m ppa.evaluate --ip <name\|path> --baseline` |
| 5-layer verify | `python3 -m ppa.verify --ip sha512 --variant-dir ../exp2_sha512_balanced` |
| Hidden-testcase drill | `python3 test_cold_start.py` → 6/6 |
| Model interface | `python3 test_model_iface.py` → 13/13 |
| Real campaign | `python3 -m ppa.controller --ip sha512 --rounds 3 --k 3 --model vertex --emit-best …` |

**Repo:** github.com/chelsea85/chip-convergence-iclad26 (fresh-clone verified)

**Harikrishnan KC · Chip Convergence · greatharikrishnan@gmail.com**
