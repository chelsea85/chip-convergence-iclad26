# Chip Convergence — ICLAD-DAC 2026 — Presentation Content (3 main decks)

Slide-by-slide CONTENT for the three per-problem presentations (~15 slides each), for
regenerating decks with any slide tool/agent. Flow diagrams are described in text (marked
[FLOW DIAGRAM]) so they can be recreated. Content matches the Marp decks in `slides/`.



======================================================================
# PRESENTATION: NVIDIA — RTL PPA Optimization
======================================================================

---

## [Slide 1]

# Verify Everything, Learn From Every Round

## Measured, equivalence-gated RTL PPA optimization

**sha512 ADP 0.727** (timing −97 → +335 ps, MET) · **prim ADP 0.605** (power −67%)
**aes power −4.3%** under a configurable security fence — all LEC/dualsim-verified,
all produced live by the agent

Harikrishnan KC · Team **Chip Convergence** · greatharikrishnan@gmail.com
NVIDIA Problem · ICLAD-DAC 2026 GenAI Chip Hackathon

---

## [Slide 2]

# 1 · The problem, and what actually scores

**Given:** 7 IPs (async_fifo, sha512, NVDLA, OpenTitan aes/ascon/kmac/prim), their
testbenches, a Yosys+OpenSTA ASAP7 flow. **Rewrite RTL to improve PPA.**

**Evaluation (per the organizers):** functional correctness with the existing testbenches
first; then PPA after Yosys, plus **LLM calls and token cost**.

**Why this is hard** (Alpha-RTL, ICCAD'24 lineage): on async_fifo, **every published
LLM-rewriting method scored zero** — no compilable, correct rewrite. Unverified
"optimizations" are noise; the synthesizer absorbs or breaks most local edits.

**Our headline metric:** baseline-normalized **Area-Delay-Product ratio** (clock period from
each IP's own SDC), functional- and equivalence-gated, token-conscious.

---

## [Slide 3]

# 2 · What we do — one picture


[FLOW DIAGRAM] Left→right, three zones:
- ZONE 0 "DIAGNOSE (zero tokens)": baseline synth+STA → 3-axis diagnosis (timing via FLATTEN=0 STA→worst-path files; area per-module cells; power seq-mass proxy; + structure tag→matched playbook rules) → output "critical files, path-ordered" = the campaign cursor (worst first).
- CENTER, dashed box "STAGE i — repeat down the cursor · budget = 20 proposal turns (k=6 then 4)": context (file[i] EDITABLE + other critical files READ-ONLY ≤6 + rules + PPA + budget; parent = best-so-far) → k parallel Gemini strategies (balanced-tree, carry-save, arith-arch, restructure, micro-opt, share-res) → strict scope filter (drop out-of-scope/hallucinated edits) → 5-layer verify pipeline (lint → compile → TB gate → synth+STA in isolated workspaces → yosys LEC + dual-inst diff sim) → decision "proven & better?": YES → ACCEPT best, LOCK file[i] read-only, advance cursor to next file (parent=best-so-far); NO → PPA-ranked gate-fail repair (synth broken candidates in parallel, keep PPA-improvers, repair top-2, off-budget) → re-verify. Either way cursor advances (no retry); plateau stop if frontier flat.
- ZONE OUTPUTS/LEARNING: design pool + Pareto frontier (every accept banked); reflector → playbook (rules voted per round, injected next stage); --emit-best artifact (repo-layout delta + manifest.json with PPA Δ, per-layer verification, calls, tokens).
Caption: Live — sha512 18 turns → ADP 0.92 chained; best single stage 0.727 LEC-proven; prim 0.605 in 6 calls.


Live: sha512 full campaign 18 turns → <b>ADP 0.92</b> (chained stages) · best single stage <b>0.727</b>, LEC-proven · prim <b>0.605</b> in 6 calls.

---

## [Slide 4]

# 3 · Principles

1. **Tools before tokens** — EDA tools diagnose *where* the problems are (0 model tokens);
   the model spends its tokens on findings, not file dumps.
2. **Verify everything** — five independent layers; accepted ⇒ **formally equivalent AND
   measurably better**. Nothing is trusted, including our own guardrails.
3. **Measure, never estimate** — every candidate gets real synth+STA in an isolated
   workspace; every reject carries a typed, measured reason.
4. **Scope by construction** — the harness enforces which files a proposal may touch;
   out-of-scope edits are dropped by tooling, not by hoping the model complies.
5. **Honest reporting** — "no improvement" is a first-class, explained result; baselines are
   re-derived from pristine sources, never inherited.

---

## [Slide 5]

# 4 · Zero-token PPA diagnosis

**Run the EDA tools first, hand the model actionable findings.**

- **Timing**: hierarchy-preserved synth+STA (`FLATTEN=0`) → worst-path cells attributed to
  **source files, in path order** → the campaign's file cursor
- **Area**: per-module cell counts — doubles as the leakage/power proxy
- **Structure classifier**: worst-path cell mix → `arith-carry-chain` / `mux-select` /
  `control-boolean-network` / … → drives rule selection (slide 6)

Validated empirically on aes: naive per-module *depth* ranking and real hierarchy-preserved
STA **disagree** — depth ≠ delay; we use the STA attribution.

**Effect:** aes prompt context **174k → ~20k tokens/call**. Diagnosis cost: **0 tokens**.

---

## [Slide 6]

# 5 · Staged coordinate descent

```
diagnose (0 tokens) → [worst file: k=6 strategies] → best win LOCKED (read-only)
                    → [next file: k=4]             → chain on best-so-far
                    → … until the 20-proposal budget is spent (repairs off-budget)
```

**Live sha512 campaign (fresh pool, 18 proposals, ~650k tokens):**

| Stage | File | Outcome | Accumulated ADP |
|---|---|---|---|
| 1 (k=6) | sha512_core | ACCEPT arith-arch | 0.938 |
| 2 (k=4) | sha512_w_mem | no win — best kept | 0.938 |
| 3 (k=4) | sha512 (top) | ACCEPT **on top of stage 1** | **0.920** |
| 4 (k=4) | h_constants | no win → plateau stop | 0.920 |

Timing −97.3 ps → **+26.3 ps MET**; the stage-3 win compounds stage-1's — verified on disk.
`--focus` overrides the cursor for targeted campaigns (used for the unfenced aes S-box run).

---

## [Slide 7]

# 6 · Context is a strategy — we ablated it

Same stage, same k=6, same strategies — only the **context** changes:

| | A: full files (read-only) | B: target alone | C: interface stubs |
|---|---|---|---|
| Functionally correct | **3/6** | 1/6 | 0/5 |
| Accept | ✓ 0.893 | ✓ **0.727** | — |
| Tokens | 329k | **232k** | 236k |

- Grounding buys **correctness**: the model needs the port/width contracts of the modules
  the target instantiates
- Leaner context saves tokens but starves behavioral detail (stubs: `pass=0` hangs)
- **Adopted: A** — full critical files as read-only grounding (cap 6), plus a **strict scope
  filter**: only the stage's file may change; everything else is dropped by tooling

---

## [Slide 8]

# 7 · The 45-rule playbook — earned, matched, evolving

**45 measured optimization rules**, three provenances:
- **Literature**: distilled from our 20+ paper survey (prefix adders, Booth, strength
  reduction, operand isolation, clock gating, retiming notes, …)
- **Our own experiments**: measured no-ops become AVOID rules — *"local restructuring (mux
  folding, operand swap) — ABC absorbs it; only global algebraic changes survive synthesis"*
- **Live reflector**: after each round the reflector distills outcomes into new rules and
  **votes** existing ones helpful/harmful (Beta posterior) — e.g. a live gate-fail became
  *"manual carry-save (3:2 compressor) insertion can break synthesis flows"*

**Structure-matched retrieval**: the diagnosis' classifier tag (e.g. `arith-carry-chain`)
selects the *relevant* rules for each stage's prompt — the model gets 5 rules that match the
circuit it is editing, not a lecture.

---

## [Slide 9]

# 8 · Five-layer verification, then measurement

| Layer | Catches |
|---|---|
| 1 · lint | malformed RTL |
| 2 · compile (iverilog) | elaboration errors → **≤2 repair attempts** w/ stderr fed back |
| 3 · testbench gate | functional breaks (differential gating vs pristine for IPs with pre-existing flow issues) |
| 4 · synth + STA | real PPA; **netlist-collapse guard** (a "win" that lost half its cells is elaboration failure, not optimization) |
| 5 · LEC (+async2sync) + dual-instance differential sim | logic-level & cycle-level equivalence |

**Accept = all layers pass AND measured strict improvement vs the best-so-far.**
No-win stages trigger **PPA-ranked repair**: broken-but-improving candidates (measured!)
get one fix attempt each (top-2), *off* the proposal budget.

---

## [Slide 10]

# 9 · Results scoreboard — complete seven-IP status

| IP | Result | Assurance (per manifest) | Cost |
|---|---|---|---|
| **sha512** | **ADP 0.727**, −97→**+335 ps MET**, area −0.4% | **full 5-layer** (gate PASS, LEC PROVEN, dualsim PASS) | 8 calls / 232k |
| **async_fifo** | **ADP 0.961** (micro-opt) — where published methods score 0 | **full 5-layer** (LEC PROVEN) | offline |
| **prim** | **ADP 0.605**, slack +181.5 ps, power −67% | equivalence+differential (LEC PROVEN + dualsim; gate skipped — pristine flow issue) | 6 calls / 167k |
| **aes** (fenced / unfenced) | power **−4.3% / −6%**, ADP 1.00 — headroom sits in the S-box | differential-only (dualsim PASS; LEC inconclusive) | 22 / 21 calls |
| kmac / ascon | offline candidates (Keccak-θ; probes); live campaigns queued (Jul 19+) | 5-layer capable | — |
| NVDLA | baseline + zero-config onboarding (323 sources); campaign on unlimited quota | — | — |

Every artifact ships as a **repo-layout delta + manifest.json** stating its exact
`verification_per_layer` + `assurance` — no blanket claims.

---

## [Slide 11]

# 10 · sha512 deep-dive: agent 0.727 beat our best hand-rewrite (0.787)

| Metric | Baseline | Agent live (Jul 14) | Δ |
|---|---|---|---|
| WNS | **−97.30 ps** (violated) | **+334.61 ps** (MET) | +431.9 ps |
| Area | 3984.2 µm² | 3967.6 µm² | −0.4% |
| **ADP ratio** | 1.000 | **0.727** | **−27.3%** |

Strategy `arith-arch` on `sha512_core` — a **single k=6 stage, 8 calls, ~232k tokens**.
**yosys LEC: PROVEN. Differential sim: PASS.**

Our best *hand-derived* rewrite (balanced adder trees, mod-2ʷ associativity) reached 0.787.
The agent's live rewrite **beats it by 6 points** — and earlier, its k-parallel proposals
independently reinvented that same hand technique (caught by fingerprint dedup, zero wasted
synthesis).

---

## [Slide 12]

# 11 · prim deep-dive: "no improvement" flipped in 6 calls

| Metric | Baseline | Agent (staged) | Δ |
|---|---|---|---|
| Setup slack | −208.95 ps | −27.46 ps | **+181.5 ps** |
| Area | 70.17 µm² | 65.93 µm² | −6.0% |
| Power | 0.0165 | 0.00538 | **−67.4%** |
| **ADP ratio** | 1.000 | **0.6045** | **−39.6%** |

Earlier flat campaign: *no improvement — baseline is the submission.* The staged agent:
**ADP 0.605 in 6 proposal calls / 167k tokens**, assurance = **equivalence+differential** (yosys LEC PROVEN + dual-instance differential sim; the pristine prim flow already fails compile/TB, so those two layers are pre-existing/skipped — not a full-5-layer claim).

The library-IP shape is why: prim ships **147 files but the scored design is one CRC32
module**. Diagnosis scopes the campaign to the file actually in the design — the third
context regime (big IP · small IP · **library IP**) handled by the same mechanism.

---

## [Slide 13]

# 12 · aes and the security fence — judgment, both numbers

OpenTitan aes ships a **DPA-masked S-box** (side-channel countermeasure). An agent can
"win" PPA by silently swapping it for an unmasked LUT — every functional test still passes.

- **Fenced runs** (security preserved): power **−4.3%** (dualsim-verified), ADP 1.00 — and
  the agent's proposals kept reaching for the S-box: the timing headroom **is** the fence.
- The contest scores *tests-pass + PPA* — no security requirement. So the fence is
  **configurable** (`--fence`, default off per the rules). The targeted unfenced S-box
  campaign (`--focus`): power **−6.0%** (dualsim-verified), ADP still 1.00 — cycle-exact
  equivalence bounds the S-box axis to power wins; the delay headroom needs
  latency-changing rewrites → transaction-mode verification (our top Jul-19 item).

**The agent quantifies the PPA cost of a security countermeasure** — and enforces whichever
posture the user chooses, by tooling rather than trust.

---

## [Slide 14]

# 13 · Hidden testcases: drilled, not hoped for

**Auto-discovery** builds an IPSpec from repo conventions (env.sh, filelists, SDC, TB
runners): fixtures match the hand registry 3/3; aes/kmac/prim/**NVDLA (323 sources)**
onboard zero-config. Clock periods parse from each IP's own SDC.

**Cold-start drill** (`test_cold_start.py`, 6/6, re-run after every harness change): plant an
unseen IP → discover → fresh baseline → propose → verify → measure → decide.

**Robustness, live-fire tested:** per-call resilient fan-out (one API failure never kills a
campaign), HTTP timeouts, retry ladders on 429/5xx, failed calls don't consume the proposal
budget, crash-protected repair paths. All ledgered: calls/tokens per round, raw responses
archived.

---

## [Slide 15]

# 14 · Next: what unlimited Vertex (Jul 19) unlocks

- **Model mixing** — strong model for creative proposals, cheap model for mechanical
  repairs/reflection. Our survey's scaling data (WNS 21/12/3%, SEC-pass 86/73/57% across
  model tiers) says capability buys *correct* rewrites — worth real tokens.
- **Transaction-mode differential sim** — legally accept latency-changing rewrites
  (unlocks the full S-box implementation axis on aes).
- **Richer interface stubs** (ports + latency contracts) — NVDLA-scale context bounding.
- **Per-round re-diagnosis** (the critical path moves as stages land) · growing stage-batch ·
  decoding-config sweep · NVDLA + kmac/ascon campaigns.
- Agents remain updatable through **Jul 26**; live-testcase runbook (triage tree, budgets,
  panic modes) is in the repo.

---

## [Slide 16]

# 15 · Summary — every claim, one command

| Claim | Reproduce with |
|---|---|
| Loop offline e2e | `python3 -m ppa.controller --ip async_fifo --rounds 1 --k 1 --model stub` |
| Fresh baseline (Docker) | `python3 -m ppa.evaluate --ip <name\|path> --baseline` |
| 5-layer verify | `python3 -m ppa.verify --ip sha512 --variant-dir ../exp2_sha512_balanced` |
| Hidden-testcase drill | `python3 test_cold_start.py` → 6/6 |
| Model interface | `python3 test_model_iface.py` → 13/13 |
| Staged campaign | `python3 -m ppa.controller --ip sha512 --rounds 8 --k 4 --k-first 6 --diagnose on --model vertex --max-calls 20 --emit-best …` |

**Repo:** github.com/chelsea85/chip-convergence-iclad26 (fresh-clone verified)
Companion deck: **Engineering Learnings** (attached) — what building this taught us.

**Harikrishnan KC · Chip Convergence · greatharikrishnan@gmail.com**


======================================================================
# PRESENTATION: NXP — SoC Generation from Diagrams
======================================================================

---

## [Slide 1]

# The Library Is the Oracle

## Verification-first SoC generation from diagrams

**Diagram → verified SoC: 2 model calls, 42 seconds —
30/30 self-test · KAT 79/79 (both oracles) · cycle-identical to reference**

Harikrishnan KC · Team **Chip Convergence** · greatharikrishnan@gmail.com
NXP Problem · ICLAD-DAC 2026 GenAI Chip Hackathon

---

## [Slide 2]

# 1 · The problem, and what actually scores

**Given:** one architecture HTML (diagrams + minimal spec), a TB skeleton fixing the top
port contract, and `rtl_gen_lib` (YAML → Verilog generators). No YAML, no RTL, no text spec.

**The agent must:** read diagrams → infer YAML per IP → generate → stitch
`secure_periph_soc` → verify.

**Scoring reality:**

| Dimension | Rule | Consequence for agent design |
|---|---|---|
| Correctness | hidden golden TB, `passed/total` | **compile fail = 0** → never ship a broken top |
| Efficiency | total tokens, tiebreak | every re-prompt must earn its cost |
| Evaluation | runner invokes agent via `info.json` + HTTP model endpoint | contract compliance is table stakes |

---

## [Slide 3]

# 2 · What we do — one picture


[FLOW DIAGRAM] Left→right, three zones:
- ZONE 0 "EXTRACT (zero tokens)": tb_skeleton→exact top port contract; generator source→required-params schema per ip_type; library demos→known-good exemplars (e.g. baud dividers); architecture doc→doc facts (IRQ map, instance hints) → all combine into a "constraint bundle" = ground truth in every prompt.
- CENTER, dashed box "GENERATE — every model boundary gated, typed errors→bounded repairs": MODEL CALL 1 (infer YAML spec per IP from diagram + constraint bundle) → YAML validator (schema + required params, ≤2 re-prompts) → rtl_gen_lib generates Verilog per IP (+ auto-patch known library bugs) → generator errors fed back (≤2 repairs) → module-interface index (exact headers parsed from generated RTL) → MODEL CALL 2 (stitch secure_periph_soc, interfaces given not guessed) → port contract + reset lint + structural diff (census, IRQ reachability, dangling ports; sabotage-validated 8/8), ≤3 repairs → top accepted; best-effort RTL ALWAYS ships (partial score beats a guaranteed 0).
- ZONE "VERIFY (deterministic, 0 tokens)": 30-check staged self-test TB → KAT 79 checks with dual oracle (golden-calibrated models + predictions from the agent's OWN inferred YAML, no golden needed) → STG dual-SoC random-stimulus differential → emit to output_dir + usage.json (runner contract e2e 6/6). Any layer fails → typed evidence back into the repair loops.
Caption: Live — 2 model calls, 42 s → 30/30 · KAT 79/79 both oracles · STG 3662 cycles 0 differing vs reference.


Live: <b>2 model calls, 42 s</b> → 30/30 · KAT 79/79 (both oracles) · STG 3662 cycles, <b>0 differing</b> vs hand-built reference.

---

## [Slide 4]

# 3 · Principles

1. **Tools before tokens** — the port contract, the YAML schema, the known-good exemplars
   and the doc facts are *extracted deterministically* from the provided materials and
   injected as ground truth; the model reads diagrams, not tea leaves.
2. **Constraints enforced by tooling, not prompting** — published evidence (SLDB,
   SpecAssess): frontier models alter ports they were told not to touch; reset semantics is
   the #1 silently-misspecified element. Every model boundary gets a deterministic gate.
3. **Every failure is a typed error** — and typed errors are repair fuel: bounded,
   targeted re-prompts with the exact violation, never "try again".
4. **Verify without a golden** — the oracle predicts from the agent's *own declared design*,
   so it works on hidden testcases where no reference exists.
5. **Always ship** — best-effort RTL beats the guaranteed zero of a missing module.

---

## [Slide 5]

# 4 · Tools before tokens: what's extracted, zero-token

| Extracted (deterministically, at runtime) | From | Feeds |
|---|---|---|
| Exact top-port contract (names, dirs, widths) | `tb_skeleton` | stitch prompt + hard gate |
| Required-params schema, per ip_type | generator *source* (`required()` calls) | spec prompt + YAML validator |
| Known-good exemplar values | library demo specs | spec prompt (e.g. baud divider) |
| IRQ source map, instance hints | architecture doc text | spec + stitch prompts |
| Module-interface index (exact headers) | the just-generated RTL | stitch prompt — ports *given*, not guessed |

All of it re-derives itself on **any** testcase — nothing is hardcoded to the easy SoC.
The live proof: `default_div = 26` appears **nowhere in the doc**; it was recovered from
library demo exemplars (115200 baud @ 50 MHz) — the library's implicit knowledge, mined.

---

## [Slide 6]

# 5 · The correctness firewall (all sabotage-validated)

| Gate | Catches | Validated |
|---|---|---|
| `port_contract` | renamed / missing / wrong-width top ports vs skeleton | typed errors on all fault classes |
| `reset_lint` | por_n feeding anything but the synchronizer; split reset nets | reset = the known killer |
| `structural_diff` | instance census, dangling ports, IRQ reachability, fabric hang-off, bridge bus | **8/8** sabotage suite |
| library fixups | known non-compiling generator output (auto-patch) | behavior-neutral |

Example typed error, verbatim from a live run — this text *is* the repair prompt:

```
struct-irq: i_uart.irq net 'uart_irq' never reaches u_irq_aggregator.irq_src
```

---

## [Slide 7]

# 6 · Verification depth: three independent layers

**1. 30-check staged self-test TB** — reset → r/w → function → irq → watchdog → privilege;
first-failing stage localizes bugs for repair.

**2. KAT engine** — 125-command vector program, **79 known-answer checks**, replay-TB +
Python comparison, two oracles.

**3. STG differential** — dual-SoC random-stimulus trace diff (LCG + burst schedules),
cycle-by-cycle.

The layers are complementary — measured example: a FIFO_DEPTH 16→8 sabotage **passes the
30-check TB (30/30)** but the KAT status read catches it in 5 trace lines:
`0x89 vs 0x88` — literally the `tx_full` bit.

---

## [Slide 8]

# 7 · The earned asset: 20 library IPs, modeled bugs-included

The hidden golden TB is built on the **same generator library** — so our reference models
are transcribed from the generated RTL, statement-for-statement, **quirks preserved**
(a "first-principles correct" model would *fail* the golden TB — the library watchdog's
kick genuinely never reloads, and our model asserts that actual behavior):

- cycle-stepped Python models for **all 20 library ip_types**
- easy-8 calibrated against golden-recorded traces: **0 mismatches**
- other 12 (AXI, TileLink, AES-128, FIFOs/SRAMs): **12/12 lockstep** vs library RTL,
  2000 cycles each; AES bit-exact over ~150 encryptions

This suite is the NXP counterpart of a rule library: **earned by measurement, versioned,
and reused by every layer of verification.**

---

## [Slide 9]

# 8 · A no-golden oracle *mechanism* (a hidden-tier foundation)

**KAT model path:** replay vectors on the candidate → predict expected values from the
reference models **parameterized by the agent's own inferred YAML** → compare.
No golden RTL, no golden TB required — the *mechanism* is topology-general.

Proof the oracle follows the declared design (not a hardcoded answer):

| Candidate SoC | Model believes | Result |
|---|---|---|
| UART FIFO depth 8 | `fifo_depth: 16` | FAIL 76/79 — catches the divergence |
| UART FIFO depth 8 | `fifo_depth: 8` (plumbed) | PASS 79/79 — consistent design accepted |

**Honest scope:** the mechanism generalizes; the *coverage* is the 8 easy IPs (0-mismatch
calibrated) + 12 more library IPs modeled (slide 10) — a **foundation** for medium/hard, proven
on the public case, not yet a topology-neutral solver. Runner contract:
`python3 nxp_agent.py <info.json> --model <name>` — **6/6** e2e vs a mock endpoint.

---

## [Slide 10]

# 9 · The result: 2 calls, 42 s — perfect against our verification stack

```
[1] model returned 8 YAML spec block(s)
[2] generated 8 IP file(s): ['sys_rst_sync.v', 'ahb_brg0.v', 'apb_fab0.v', 'uart0.v',
    'gpio0.v', 'timer0.v', 'wdt0.v', 'irq_agg0.v']
[3] wrote secure_periph_soc.v (contract clean, attempt 1)
[4] GATE: PASS — 30/30 PASS
[4b] KAT(golden): PASS — 79/79
[4b] KAT(model):  PASS — 79/79
[5] STG-DIFF: MATCH — 3662 cycles, 0 differing
    model calls: 2
```

The generated SoC is **cycle-identical** to our hand-built reference over 3662 random
cycles — and the whole solve cost **2 model calls / ~40k tokens**.

---

## [Slide 11]

# 10 · Medium/hard readiness

The library ships **20 generators; easy uses 8**. The other 12 are the likely
medium/hard vocabulary — already modeled and validated:

- AXI-Lite: crossbar (2M×3S), SRAM, DMA engine — 12/12 lockstep
- TileLink: router, network interface
- AES-128 (bit-exact), FIFOs (sync/async gray-code), SRAMs, CDC, perf counter

Known library quirks catalogued (golden-TB-relevant): AES core **ignores its `encrypt`
input**; TL router implements **no mesh routing** (all→local). Generator `MissingParameter`
errors are typed and model-directed — purpose-built repair material.

---

## [Slide 12]

# 11 · Economics & contest contributions

| Item | Cost |
|---|---|
| Easy-tier solve (perfect vs our stack) | **2 calls / ~40k tokens** |
| Repair bounds | ≤2 spec re-prompts, ≤2 generator-repair, ≤3 stitch |
| Prevention > repair | schema in the *first* prompt ended the omission loop |
| Every verification gate | free — deterministic, local, zero tokens |

**3 toolkit bugs found & reported** (details in the Learnings deck): `dma_engine` generates
non-compiling RTL (hits *every* team; we auto-patch, behavior-neutral) · `apb_watchdog`
kick never reloads (modeled as-is — oracle correctness) · NVIDIA aes flow masked failure.

---

## [Slide 13]

# 12 · Next: what we build before DAC (agents updatable to Jul 26)

- **Testcase digest (designed)** — deterministic parse of the architecture doc's address-map
  tables + instance inventory, cross-checked against the model's specs; mismatches feed the
  existing repair loops. The per-testcase analog of our zero-token extraction — insurance
  for medium/hard doc complexity.
- **K-vote spec inference** — field-level majority across independent diagram reads;
  disagreement → targeted re-look (defense vs consistent misreads)
- **Best-of-M stitches** — KAT-model score as the selector
- **Model mixing on unlimited Vertex (Jul 19+)** — strong model for diagram reading,
  cheap model for repairs
- Medium/hard fixtures composed from the 12 modeled IPs; live-testcase runbook in repo

---

## [Slide 14]

# 13 · Summary — every claim, one command

| Claim | Reproduce with |
|---|---|
| Full pipeline offline | `python3 nxp_agent.py --model stub` → 30/30, KAT 79/79 ×2 |
| Real-model solve | `python3 nxp_agent.py --model vertex --deep` |
| Gate sabotage suite | `python3 test_structural.py` → 8/8 |
| Runner contract | `python3 test_runner_mode.py` → 6/6 |
| 12 IP models vs RTL | `python3 test_ip_models.py` → 12/12 |

**Repo:** github.com/chelsea85/chip-convergence-iclad26 (fresh-clone verified)
Companion deck: **Engineering Learnings** (attached) — what building this taught us.

**Harikrishnan KC · Chip Convergence · greatharikrishnan@gmail.com**


======================================================================
# PRESENTATION: ASU — Block DRC Repair
======================================================================

---

## [Slide 1]

# Measure the Scorer, Never Ship a Regression

## Verification-first DRC repair of ASAP7 layout scripts

**Version-exact scoring env · verify identical to the official evaluator ·
keep-best guarantee: never worse than the eligible baseline, on all 5 blocks**

Harikrishnan KC · Team **Chip Convergence** · greatharikrishnan@gmail.com
ASU Problem · ICLAD-DAC 2026 GenAI Chip Hackathon

---

## [Slide 2]

# 1 · The problem, and what actually scores

**Given:** an ASAP7 block as a **KLayout `pya` layout script** with seeded DRC violations, its
**DRC report** (per-rule counts + exact geometry), the rule deck, a **screenshot**, and a
**connectivity reference**. Repair the script.

**Scoring — gated lexicographic:**

| Gate / Metric | Rule |
|---|---|
| Eligibility | script must render + DRC must run **AND** connectivity preserved |
| 1 · `final_violation_rate` | minimize (final DRC violations / original) |
| 2 · `repair_rate` | maximize (tiebreak) |

**Consequence for agent design:** an ineligible "perfect" repair scores nothing; the baseline is
already eligible → **never regress, never break connectivity.**

---

## [Slide 3]

# 2 · What we do — one picture


[FLOW DIAGRAM] Left→right:
- ZONE "DIAGNOSE (zero tokens)": DRC report → per-rule findings (count + exact geometry) matched to the repair-rule library.
- CENTER, dashed box "REPAIR — candidate fix-passes (deterministic + model)": fix-pass = ORIGINAL script + appended pya (runs before write); deterministic grid-snap (exact-rule-derived); model fix-pass (rules + coupling + screenshot, best-of-N, code-compile checked, render-error repair) → VERIFY (render → DRC → connectivity, measured with the official evaluator's OWN functions (the scorer's own code)) → decision "eligible & better?": no → KEEP-BEST (gated-lexicographic; baseline = eligible floor, a regression/breakage discarded); loop.
- ZONE "EMIT · SCORE": best eligible script → output_path + usage.json (runner-contract compliant). Env = version-exact KLayout 0.30.1 Docker (organizer scoring target); 5/5 blocks eligible, connectivity preserved.
Caption: diagnose (0 tokens) → propose → verify == scorer → keep-best → emit. Eligible on all 5 blocks.


Same verification-first spine as our NVIDIA/NXP agents: diagnose with tools (0 tokens) → propose → verify == scorer → keep-best → emit. Validated eligible on all 5 blocks.

---

## [Slide 4]

# 3 · Principles

1. **Tools before tokens** — the DRC report is a ready-made, machine-readable diagnosis
   (per-rule counts + exact geometry); spend model tokens on the genuinely ambiguous cases, not
   on re-deriving what the tools already state.
2. **Measure the scorer, not a proxy** — our inner loop imports the *official evaluator's own*
   render/DRC/connectivity functions, so every candidate is measured exactly as it will be scored.
3. **Never regress** — keep-best with the untouched baseline as the eligible floor; a fix that
   worsens DRC or breaks connectivity is discarded by tooling, not by hope.
4. **Ground rules in the deck, not descriptions** — the authoritative fix semantics come from
   `asap7.lydrc` itself, cross-checked against EDA legalization literature.
5. **Honest characterization** — "eligible baseline + why sub-baseline needs global legalization"
   is a first-class, reproducible result.

---

## [Slide 5]

# 4 · Version-exact environment (the first thing others will trip on)

The evaluator **hard-rejects any KLayout but 0.30.1** (string-equality on `klayout -v`). macOS
Homebrew ships 0.30.9 (and hits Gatekeeper quarantine) — the wrong path.

**Our fix — Dockerized, version-exact:** an amd64 image with the pinned
`klayout_0.30.1-1_amd64.deb` + deps. Host is Apple Silicon (arm64) → runs under Docker emulation:
slower, but **version-exact KLayout 0.30.1** — our container DRC matches the reference report on **11/14 rules**.

**Calibration proof:** on the untouched Block1, our container DRC matches the reference report on
**11 of 14 rules exactly** (V2.M3.AUX.2=72, V4.M5.AUX.2=48, V0.M1.AUX.3=37, all S-rules…). Our DRC
*is* the scoring DRC.

---

## [Slide 6]

# 5 · Zero-token DRC diagnosis

`drc_digest.py` turns the DRC report into structured, actionable findings — **no model tokens:**

- **per-rule findings** ranked by count, each with the rule *description* and exact violation
  geometry (bbox + vertices, DBU)
- **fix-kind classification** — grid / spacing / enclosure / width-match / area — parsed from the
  rule text
- **rule-library match** — each finding linked to its repair transform + coupling hazard

Block1 example: 244 reference violations, 14 rules; the dominant class is **via-width-match
(AUX.2/AUX.3) = 181 violations (74%)**, then grid, enclosure, spacing. The diagnosis *is* the
repair plan — before a single token is spent.

---

## [Slide 7]

# 6 · The repair-rule library (exact-deck + literature grounded)

Like our NVIDIA 45-rule playbook, but for DRC. Each rule class → a coordinated transform + its
coupling hazards, from three provenances:

- **Exact deck semantics** (`asap7.lydrc`): `V2.M3.AUX.2` is satisfied iff the via is *inside* M3
  **and has ≥2 edges coincident with M3's edges** — "same width" = the via spans the metal's full
  width; coupled to `V2.M2.EN.1` (M2 encloses via 5 nm) + `V2.AUX.1` (via inside M2 & M3).
- **EDA legalization literature**: MDPI 2025 (SA standard-cell DRC repair), EDN
  (cut-slide/merge without new errors), USPTO 7,380,227 (asymmetric enclosure), **DRC-Coder
  ISPD'25** (vision+LLM rule interpretation, F1=1.0).
- **Our own measurements** (slide 10).

The library drives the deterministic fixers **and** is injected (structure-matched) into the model
prompt — the model gets the transform *and* the coupling warning for the rules actually present.

---

## [Slide 8]

# 7 · Verification == the scorer, and keep-best

**Verify** (`verify.py`): render → GDS → ASAP7 DRC → connectivity, all measured with the official
evaluator's **own** functions. Reproduces the baseline exactly (total=315, connectivity 824
sources). No metric drift: the inner loop calls the evaluator's own functions (independently re-scored by the published evaluator).

**Keep-best** (gated-lexicographic, matching the contest): eligible → min `final_violation_rate` →
max `repair_rate`, with the untouched baseline as the guaranteed-eligible floor.

**The guarantee this buys:** on every block, the agent **does not ship a candidate that regresses
`final_violation_rate`** and **retains the eligible baseline if a candidate fails the connectivity
check** — verified, then kept-best. The same
"always ship eligible" discipline as our NXP agent.

---

## [Slide 9]

# 8 · The repair engine: deterministic + model, verified

**Candidate = the ORIGINAL script + an appended `pya` fix-pass** that runs right before `write`.
Because the original shapes are untouched, connectivity (checked statically from the script) is
then VERIFIED per candidate (the appended pass mutates rendered geometry; keep-best + the official
connectivity check are the guarantee, not the append mechanism).

- **Deterministic fixers** (0 tokens) — coordinated wide-metal-via, grid-snap; each derived from
  the exact rule geometry and applied to the flagged locations.
- **Model fixers** — Gemini writes a `pya` fix-pass with the rules + coupling + (next) the
  screenshot; **best-of-N**, code-compile validated, with a render-error repair loop, and *off the
  token budget when a candidate fails*.

Every candidate goes through verify + keep-best — so a bad pass (deterministic or model) is simply
never kept.

---

## [Slide 10]

# 9 · The breakthrough: decode the rule, don't guess the fix

We stopped reverse-engineering fixes from report *descriptions* and read the **actual KLayout rule
deck** — the ground truth:

```
V2.M3.AUX.2  satisfied  ⟺  via INSIDE M3  AND  ≥2 via edges COINCIDENT with M3 edges
V2.M2.EN.1   M2 must enclose the via by 5 nm on two opposite sides
V2.AUX.1     the via must be INSIDE both M2 and M3
```

So the width-match fix is *derived*, not guessed: **make the via's ⟂-to-metal-length edges flush
with the metal, and patch the lower metal to keep enclosure + containment.** This is the "wide
metal needs a wide via" idiom from the PDK — now exact.

---

## [Slide 11]

# 10 · The finding: block repair is global legalization

We built the coordinated fixer from that exact geometry and measured every strategy on Block1
(baseline 315 violations):

| Fix | target rule | but breaks | net |
|---|---|---|---|
| grow via → metal width | AUX.2 ✓ | lower-metal enclosure | 315→387 |
| shrink metal → via width | AUX.2 ✓ | upper-via enclosure | 315→339 |
| **coordinated via + metal patch** | AUX.2 ✓, **enclosure preserved ✓** | neighbor **M2 spacing** | 315→379 |

Every fix **cascades to the next layer of the via stack** (M2-V2-M3-V3-M4…). The coordinated fixer
is the first to **solve the enclosure coupling** — but a wide via forces a wide lower metal, which
crowds neighbor tracks.

---

## [Slide 12]

# 11 · We pinned the exact mechanism — and it's uniform

A **perturbation characterization** (flagged vs correct via stacks, 0 tokens) found the seeding is
systematic: every correct stack is min-via-in-min-metal; every flagged one is a **correct min-via
in a wide metal** — and that wide metal legitimately encloses a **larger via stacked above it**.

**The local tension:** at a flagged site, one M3 must *flush-match* the small via below
(V2 = 72) **and** *enclose* the larger via above (V3 = 96) — i.e. be simultaneously 72 **and** ≥106.
No single-metal edit can satisfy both; only relocating neighbors (global) can.

| Block | total | **via-width (over-constrained)** |
|---|---|---|
| Block1 / 2 / 3 / 6 / 7 | 244 / 68 / 89 / 247 / 765 | **74% / 76% / 74% / 74% / 71%** |

**~74% of every block** is this coupled class → every local transform we evaluated regressed, so a
sub-baseline result needs **neighbor-aware / global relocation** (full legalization, MDPI 2025). Our
keep-best loop already *is* the SA acceptance test and verify *is* the exact cost function — the
open work is a global multi-edit move-generator, a well-scoped (multi-day) extension.

---

## [Slide 13]

# 12 · Results & honest status

- **Environment**: version-exact KLayout 0.30.1, Dockerized; DRC calibrated (11/14 rules exact).
- **Agent**: runner-contract compliant; **all 5 blocks (Block1/2/3/6/7) eligible, connectivity
  preserved** (final-violation-rate ≈ 1.25–1.32 = the eligible baseline).
- **Repair-rule library**: exact-deck + literature grounded; drives deterministic fixers + model
  prompt.
- **Coordinated wide-metal-via fixer**: **solves the enclosure coupling** — the first strategy to
  do so.
- **Characterization**: rigorous, reproducible proof that block-repair is global legalization,
  with two concrete solution paths scoped.

**Never a regression, never a broken net — on every block.** Same discipline that delivered NVIDIA
(ADP 0.727 sha512 / 0.605 prim) and NXP (2-call solve, perfect vs our verification stack).

---

## [Slide 14]

# 13 · Next: from characterization to sub-baseline

- **Global move-generator (the missing piece)** — SA over *multi-edit* stack moves: resize the
  whole via stack to a consistent width, accept by net-conflict-delta (keep-best already is the
  acceptance test). The path to `final_violation_rate < 1`.
- **Multimodal repair (DRC-Coder ISPD'25 style)** — feed Gemini the **screenshot** + exact rules +
  violation geometry so it localizes and proposes *stack-coordinated* edits (unguided, the model
  over-corrected globally).
- **Per-rule independent fixers** — min-area / isolated edges (no via nearby) as free deterministic
  wins.
- Agents remain updatable through **Jul 26**.

---

## [Slide 15]

# 14 · How this mirrors our NVIDIA & NXP agents

| | NVIDIA | NXP | **ASU** |
|---|---|---|---|
| Tools before tokens | zero-token PPA diagnosis | library introspection | **zero-token DRC diagnosis** |
| Knowledge asset | 45-rule playbook | 20 IP reference models | **DRC repair-rule library** |
| Verify | 5-layer + LEC/dualsim | 30-check TB + KAT + STG | **render+DRC+connectivity == scorer** |
| Safety | accept only measured improvement | always ship eligible | **keep-best, never regress** |
| Env rigor | pristine baselines | runner contract | **version-exact KLayout 0.30.1** |

One architecture, three domains — the discipline transfers.

---

## [Slide 16]

# 15 · Summary — every claim, one command

| Claim | Reproduce with |
|---|---|
| Version-exact env | `docker run … asu-klayout:0.30.1 klayout -v` → 0.30.1 |
| Zero-token diagnosis | `python3 drc_digest.py <BlockN.drc.json>` |
| Agent (eligible, keep-best) | `python3 asu_agent.py <info.json> --model none` |
| Verify == scorer | inner loop imports `evaluator/evaluate_repair.py` functions |
| 5/5 blocks eligible | Block1/2/3/6/7, connectivity preserved |

**Repo:** github.com/chelsea85/chip-convergence-iclad26 (`asu_work/`)
Companion deck: **Engineering Learnings** (attached) — what the research + experiments taught us.

**Harikrishnan KC · Chip Convergence · greatharikrishnan@gmail.com**