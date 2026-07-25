# NVIDIA Problem — Daily Run Log

**Category:** NVIDIA RTL Optimization (PPA). **Track:** Cloud. **Team:** Chip Convergence (solo).
**Remote phase ends ~July 10, 2026** → iterate daily. See `CATEGORY_DEEP_DIVE.md` + `CODE_STUDY.md`
for full background.

---

## Problem summary (quick reference)

- **Task:** AI agent rewrites given, working RTL to improve **Power / Performance / Area** while the
  existing testbench still passes. Optimization, not generation.
- **Gate:** functional testbench must pass (else score 0 for that IP).
- **Then measured:** Power, Performance (timing/slack at fixed SDC clock), Area (post-Yosys),
  **# LLM calls**, **token cost**. ⚠️ **Exact metric/weighting still UNPUBLISHED** by organizers.
- **IPs:** async_fifo, sha512, NVDLA, OpenTitan {aes, ascon, kmac, prim}.
- **Flow (validated):** `run_iverilog_tb.sh all` (gate) → `yosys_syn/run_syn.sh all` (Yosys + OpenSTA).
- **Toolchain:** Docker `iclad-dev:v1` (iverilog 13, yosys 0.63, OpenSTA 3.1.0) + ASAP7 PDK. All local.
- **Measurement harness:** `nvidia_work/measure.sh <synpath> <design> [VT] [CORNER] [ABC] [label]`.

### async_fifo baseline (reproduced bit-for-bit, RVT/TT/speed)
| Area (units) | Cells | Flip-flops | Setup worst slack @300ps | Hold slack | Power |
|---|---|---|---|---|---|
| 120.372 | 918 | 170 | +22.22 ps | +46.63 ps | 2.92 mW |
- Functional gate: **16/16 PASS** (SVUT, two threshold configs).
- Memory dominates FFs: 128 of 170 are the 16×8 mem array (inherent). Pointers/flags/sync ≈ 42.
- Timing met with margin → at the fixed clock, area & power are the controllable levers.

---

## Open questions for organizers
1. **What is the exact scoring metric?** Weighting of P vs P vs A; is it % improvement vs the
   committed baseline; how do token cost / LLM-call count fold in (penalty vs tiebreak)?
2. Is **performance** scored as slack at the fixed SDC clock, or do you re-tighten the clock / report fmax?
3. Is **power** scored from the un-annotated liberty estimate (no VCD/SAIF), or will switching activity be provided?
4. Are `VT` / `CORNER` / `ABC_AREA` synthesis knobs **in scope** for the agent to choose, or is the
   eval recipe fixed? (The `run_syn.sh` exposes them but `env.sh` appears to hard-set defaults.)
5. Per-IP scores aggregated how (sum / average / must-improve-all)?

---

## Day 1 — 2026-06-29

**Goal:** validate the optimize→gate→synth→measure loop on async_fifo with a real RTL change;
get a first measurable PPA improvement.

**Hypothesis / change (exp1 — "gray-comb"):** The design registers BOTH the binary pointer
(`wbin`/`rbin`) and the gray pointer (`wptr`/`rptr`). But registered `wptr` always equals
`gray(registered wbin)` (because `{wbin,wptr} <= {wbinnext, gray(wbinnext)}`). So the gray
register is **redundant**: replace with combinational `assign wptr = (wbin>>1)^wbin` (same read
side). Provably equivalent → should keep 16/16 and remove ~10 FFs (5 per side).
- CDC safety: synchronizer samples a value that is stable between launch-clock edges (derived from
  a stable registered binary) and still changes 1 bit per step → MTBF property preserved.

**Result (exp1 gray-comb, RVT/TT/speed):** variant saved in `nvidia_work/exp1_graycomb/`.

| Metric | Baseline | exp1 | Δ |
|---|---|---|---|
| Functional gate | 16/16 | **16/16 PASS** | correctness preserved ✅ |
| Flip-flops | 170 | 162 | **−8 FF** |
| Setup worst slack | +22.22 ps | +35.21 ps | **+13 ps (≈+58% margin)** |
| Hold slack | +46.63 ps | +46.63 ps | 0 |
| Total cells | 918 | 933 | +15 |
| Area (units) | 120.372 | 121.408 | **+0.86% (worse)** |
| Power | 2.92 mW | 2.91 mW | ~flat |

**Analysis:**
- The flow is fully validated: provably-equivalent RTL change → 16/16 → measurable PPA delta.
- Outcome is a **timing win, slight area loss.** Removing the gray FFs cut 8 flip-flops, but the
  combinational `gray = (bin>>1)^bin` + its fanout buffering added 15 cells, netting +0.86% area.
  Key lesson: **in ASAP7, FF count ≠ area** — DFFs here are cheap; trading them for combinational
  logic+buffers can cost area.
- Why timing improved: the synchronizer/compare path no longer waits on a gray register update;
  net +13 ps slack. But baseline **already met timing with margin**, so extra slack is only
  valuable if the metric rewards slack/fmax, or if we **spend** it on smaller/lower-power cells.
- **Verdict:** not a clear win under an area-weighted metric; a win under a timing-weighted metric.
  → This sharpens **organizer question #1/#2** (what does the metric actually reward?).

**Next steps (Day 2 candidates):**
1. **ABC area-mode check.** Earlier `ABC_AREA=1` produced identical results — suspect `env.sh`
   hard-sets `ABC_AREA=0` and clobbers the CLI value. If so, genuinely enabling area mode is a
   direct, RTL-free area lever. (In-scope: it's area optimization, not the VT rat-hole.) Verify +
   measure. Also pending organizer Q4 (are knobs in scope?).
2. **Spend the slack for area:** combine exp1's timing headroom with area-oriented synthesis to
   recover/reduce area → aim for net area win at still-positive slack.
3. **Target combinational area directly:** the almost-full/almost-empty lookahead
   (`wgraynextp1`/`rgraynextm1` = extra incrementer+gray each) is required by the awfull/arempty
   outputs, but may be computable more cheaply. Explore equivalence-preserving simplification.
4. Capture a **sha512** baseline to have a second, larger IP in play.

### Day 1 (continued) — rest-of-IP analysis + transferable-asset plan

**Strategy pivot (model access ~July 19):** build **transferable harnesses + per-IP baselines +
optimization-pattern catalog + a model-pluggable agent scaffold** now, so we just plug Gemini in
later. Per-IP characterization underway.

**sha512 baseline (RVT/TT/speed) — ⭐ FAILS TIMING (prime optimization target):**
| Area | Cells | FF | Setup WNS @1500ps | Hold | Power | Gate |
|---|---|---|---|---|---|---|
| 3984.20 | 29307 | 3674 | **−97.30 ps (VIOLATED)** | +48.66 ps | 2.23 mW | all TCs PASS |
- Clock target 1500 ps (666.7 MHz); critical path ≈1597 ps. Unlike async_fifo, **timing is
  genuinely failing** → closing it is a clear win under any metric. SHA-512 critical path is
  typically the round-compression adder chain (a/e updates) → candidates: CSA/adder restructure,
  balancing, (pipelining would change latency/interface → risk to TB).

**🔑 OpenTitan unblock (transferable):** synth flows reference `sv2v` (x86-only, broken under
Rosetta) **but** `syn.tcl` honors **`SKIP_SV2V=1`**, reading the committed `generated/*.v` instead
(aes 76, ascon 38, kmac 65, prim 147 files). → We **can** run OpenTitan PPA locally with
`SKIP_SV2V=1`. (ascon synth test running.) Functional gates use **verilator** (handles SV natively,
no sv2v needed).

**Per-IP baseline table (RVT/TT/speed) — MEASURED:**
| IP | Area (units) | Cells | FF | Setup WNS | Clock | Timing | PPA-local? |
|---|---|---|---|---|---|---|---|
| async_fifo | 120.37 | 918 | 170 | **+22.22 ps** | 300 ps | ✅ MET | ✅ |
| sha512 | 3984.20 | 29307 | 3674 | **−97.30 ps** | 1500 ps | ❌ FAIL | ✅ |
| aes | ~ (74034 cells) | 74034 | — | **−1083.58 ps** | 100 ps | ❌ FAIL | ✅ SKIP_SV2V |
| ascon | 1789.77 | 12295 | — | **−430.14 ps** | — | ❌ FAIL | ✅ SKIP_SV2V |
| kmac | 13353.81 | 97078 | — | **−1115.75 ps** | — | ❌ FAIL | ✅ SKIP_SV2V |
| prim | (multi-top lib) | — | — | n/a | — | n/a | ✅ synth-only |
| NVDLA | TBD | — | — | TBD | — | TBD | TBD |

**🔑 Strategic inference (L2):** **5 of 6 IPs ship FAILING timing** (only async_fifo meets it),
incl. aes at a physically-impossible 100 ps / 10 GHz. → The metric is almost certainly **relative
PPA improvement vs baseline** (shrink WNS/area/power), NOT absolute timing closure. → optimization
goal = reduce the violation / area / power vs the committed baseline. (Confirm with organizers — Q1.)
- Note: `prim` is a **multi-top primitive library** (prim_crc32, prim_trivium, prim_ascon_duplex…)
  → single-top STA doesn't apply; synth works. Lower-priority target.

### ✅ Transferable assets built today (in `nvidia_work/`)
1. **Harness** — `harness/measure.sh` (synth+STA → PPA line; handles generic & OpenTitan report
   naming, SKIP_SV2V), `harness/run_gate.sh` (functional gate PASS/FAIL, ANSI/summary-robust),
   `harness/registry.tsv` (per-IP: gate tool/dir/cmd, syn path, SKIP_SV2V, baseline slack).
2. **Per-IP baselines** — table above; reproducible bit-for-bit.
3. **Optimization catalog** — `OPTIMIZATION_CATALOG.md` (patterns P1–P5, lessons L1–L5).
4. **Model-pluggable agent** — `agent/optimize_agent.py`: full optimize→gate→synth→measure→
   accept/revert loop. **Validated end-to-end with StubModel** (gate PASS, baseline parsed,
   clean revert). `VertexModel` mirrors `AgentSetup.md` — drop in when `EXPRESS_MODE_KEY` lands;
   no loop changes needed. Acceptance metric is pluggable (`better()`), to be tuned to organizer Q1.

**Day-2 plan:** (a) NVDLA baseline; (b) hand-prototype **P2 (CSA adder restructure) on sha512** to
quantify achievable WNS reduction — gives us a known-good pattern + target number before model
access; (c) refine `better()` once organizers reply on the metric.

---

## Day 2 — 2026-06-29 (cont.) — Verilator check + first real win on IP #2 (sha512)

**Verilator gate status (transferable):** Verilator 4.218 binary works, BUT the **OpenTitan
functional gate is currently BLOCKED** — `./run_verilator_tb.sh all` on aes fails at **FuseSoC**
dependency resolution (empty `files_verilator_waiver` fileset in `jtag_dtm.core`/`adapter_dmi.core`
rejected by FuseSoC 2.4.6, + `tlul_adapter_dmi` version conflict). Verilator itself never runs. →
Until FuseSoC `.core` files are patched / FuseSoC version aligned, we **cannot run the correctness
gate for aes/ascon/kmac** → can't safely close the optimize loop on them. iverilog IPs
(async_fifo, sha512) are unaffected. (Logged as a blocker; candidate Day-3 fix: patch the two
`.core` filesets or pin a compatible FuseSoC.)

**exp2 — sha512 balanced adder trees (P2) — ⭐ CLEAN WIN (variant: `nvidia_work/exp2_sha512_balanced/`):**
| Metric | Baseline | exp2 | Δ |
|---|---|---|---|
| Functional gate | 24/24 | **24/24 PASS** ✅ | preserved |
| Setup worst slack @1500ps | **−97.30 ps (VIOLATED)** | **+235.36 ps (MET)** | **+332.7 ps** |
| Area (units) | 3984.20 | 3960.29 | **−0.6%** |
| Cells | 29307 | 28955 | −352 |
| FF / Power | 3674 / 2.23 mW | 3674 / 2.23 mW | unchanged |

- **Change:** rewrote the SHA round's serial 7-/6-operand add chains (`a_new`, `e_new`) as balanced
  binary trees; exposed Σ0/Σ1/Ch/Maj as module wires. Associativity of mod-2^64 add → provably
  equivalent. (See pattern **P2** in `OPTIMIZATION_CATALOG.md`.)
- **Significance:** turned a **timing-FAILING** baseline into **timing-MET (+235 ps)** AND reduced
  area — a win under *any* plausible metric. Validates the optimize→gate→synth→measure loop on a
  second, complex IP, and gives the agent a proven high-value pattern + a worked example.

**Updated transferable assets:** `OPTIMIZATION_CATALOG.md` P2 now MEASURED (big win) + P2b (CSA) as
next level; `TOOLCHAIN.md` created (full open-source tool map). Harness handles OT report naming +
`SKIP_SV2V`. agent `better()` already accepts this kind of result (timing↑, area not worse).

**Day-3 candidates:** (a) feed exp2 pattern to the agent path (CSA / P2b as a harder generation
task); (b) unblock OpenTitan gate (FuseSoC `.core` patch) so aes/ascon/kmac become optimizable;
(c) NVDLA baseline; (d) tune `better()` to organizer metric when they reply.

---

## Day 3 — 2026-06-30 — ✅ OpenTitan functional gate UNBLOCKED

**Root cause (transferable):** exactly **2** `.core` files —
`opentitan/hw/ip/tlul/jtag_dtm.core` and `…/adapter_dmi.core` — declared their
`files_verilator_waiver` fileset with an empty **`files: []`**. FuseSoC 2.4.6's CAPI2 schema
enforces `minItems:1` on a fileset's `files`, so it **rejected (ignored) those two .core files**,
which broke `lowrisc_tlul_adapter_dmi` dependency resolution → the whole aes/ascon/kmac Verilator
build failed before Verilator even ran.

**Fix:** removed the empty `files: []` line in both files → valid **depend-only** filesets
(they only pull in `lowrisc:lint:common`; the real waiver file was already commented out). 2-line
repo patch, no Docker rebuild, no FuseSoC version change.

**Result — aes gate now 4/4 PASS:**
| Testbench | Result |
|---|---|
| aes_sbox_tb | ✅ SIMULATION PASSED |
| aes_cipher_core_tb | ✅ SIMULATION PASSED |
| aes_wrap_tb | ✅ SIMULATION PASSED |
| aes_tb (full GCM, DPI) | ✅ SIMULATION PASSED |
| **ALL TESTBENCHES** | **Passed: 4 / Failed: 0** |

→ **The optimize→gate→synth→measure loop is now runnable on the OpenTitan IPs** (aes confirmed;
ascon/kmac verifying). Combined with `SKIP_SV2V=1` for their synth, aes/ascon/kmac are now fully
optimizable locally. Verilator 4.218 satisfies their `>=4.210` requirement.

**Files touched (local dev patches, like the Dockerfile fixes):** `tlul/jtag_dtm.core`,
`tlul/adapter_dmi.core`. Documented here + in `CODE_STUDY.md`.

**Other OT gates confirmed:** ascon ✅ SIMULATION PASSED, kmac ✅ SIMULATION PASSED. → all of
aes/ascon/kmac now have a working correctness gate (Verilator 4.218 ≥ required 4.210).

**Agent loop validated on an OpenTitan IP (ascon, stub):** `ascon GATE: PASS`; baseline parsed
(area 1789.77, 12295 cells, 1769 FF, setup −430.14 ps, pwr 18.4 mW); stub → no change → clean stop.
→ the full optimize→gate→synth→measure loop works on OT IPs (Verilator gate + `SKIP_SV2V` synth).

**🐞 Latent agent bug found & fixed (important):** `optimize_agent.py` `revert()` did
`git checkout -- opentitan` for OT IPs (it took `IP_RTL[ip][0].split("/")[0]` = "opentitan"),
which **wiped the shared tlul/.core fix on every OT run** and would silently corrupt the repo /
other IPs during real model-driven runs. Fixed: `revert()` now scopes the checkout to the IP's
exact RTL dir (`IP_RTL[ip][0]`). Re-validated: `.core` fix survives the agent run.

**Repo state:** clean except 3 intentional patches — `Dockerfile`, `tlul/jtag_dtm.core`,
`tlul/adapter_dmi.core`. (These must persist; re-apply if any git op reverts them.)

### Day-3 outcome summary
- **4 of 6 timing-relevant IPs are now fully optimizable locally:** async_fifo + sha512 (iverilog
  gate) and aes/ascon/kmac (Verilator gate + SKIP_SV2V synth). NVDLA flow still uncharacterized.
- Transferable infra proven across BOTH gate types (iverilog + Verilator). Swap StubModel→VertexModel
  when access lands and the loop runs on any of these IPs.

### NEXT TASKS — NVIDIA (tracked in task list)
1. Hand-prototype a P2-style optimization on **aes or ascon** (huge −430…−1083 ps headroom) → bank
   another proven worked example for the agent.
2. Characterize **NVDLA** (gate via `run_varilator_test.sh`, baseline synth) to complete coverage.
3. Investigate the `env.sh` `VT`/`ABC_AREA` clobber (L4) — confirm whether synthesis-knob levers
   are usable; fix env if so.
4. When organizers reply on the metric → tune agent `better()` acceptance function (Q1).
5. When Vertex/Express access lands (~Jul 19) → swap in `VertexModel`, run real optimize rounds.

## Day 4 — 2026-07-01/02 — 📚 Research sprint: metric intelligence + agent design (see RESEARCH_NOTES.md)

~586 papers screened (dair-ai weekly lists Jul'25–Jun'26 + ICLAD/LAD 2025+2026 accepted papers),
4 deep-read passes for implementation-grade detail. Everything consolidated in **RESEARCH_NOTES.md**;
ordered implementation specs in **nvidia_work/AGENT_UPGRADE_SPEC.md** + **nxp_work/AGENT_UPGRADE_SPEC.md**.

**Strategy-changing findings (NVIDIA):**
1. **Metric shape converged** (3 independent sources): organizers' own group (Self-Evolved ABC,
   Cunxi Yu + Haoxing Ren) headlines **baseline-normalized area-delay product**, formal-equivalence
   gated, token-conscious; Pluto (ICLAD'26) = eff@k, per-metric linear normalization vs reference,
   gated on TB pass; HQI = 0.5·area + 0.5·delay normalized. → internal metric: **ADP ratio headline,
   Pareto-first acceptance**, weights configurable. OpenSTA power unreliable (31% cross-flow error)
   → ratios under our own flow only.
2. **async_fifo is a DIFFERENTIATOR, not low-headroom**: Alpha-RTL (our exact iverilog/yosys/OpenSTA
   stack) reports every published method scored **0** on async_fifo (no correct rewrite within
   budget). We have a proven passing variant (exp1). Bank any verified improvement there.
3. **Two ablation-backed loop levers**: STA-localized feedback (Dr. RTL: 21%→9% WNS gains without)
   and design-state pool + adaptive parent sampling (Alpha-RTL: −45.3% vs −13.3% ADP = 32pp).
4. **Reward hacking is real** (5 papers): models delete TB-unexercised logic under PPA pressure →
   equivalence gate + differential vectors are mandatory, LLM judges never gate accepts.
5. sha512 TB is `wait_ready()` handshake-based → **pipelining/latency changes likely legal** there.

## Day 5 — 2026-07-03 — 🏗️ New agent BUILT + validated end-to-end: `nvidia_work/agent/ppa/`

Replaced the 187-line scaffold with an 8-module package implementing the upgrade spec's
Phases 0–3 core. **Every module validated against known ground truth.**

**Modules:** `config` (per-IP specs, docker mounts), `workspace` (per-candidate scratch copies —
parallel-safe), `verify` (5-layer gate stack), `evaluate` (proxy pre-filter + parallel workers +
JSONL ledger), `objective` (pareto/weighted/lex + ADP + Pareto frontier), `sta_feedback`
(path parsing + root-cause tags), `skills` (20-bullet ACE playbook), `pool` (Thompson/Beta
parent sampling), `proposer` (strategy ladder v0–v6, Alpha-RTL prompt, Stub/Vertex),
`controller` (budget regimes, plateau stop).

**Validation results:**
| Check | Result |
|---|---|
| exp2 (sha512 balanced adders) full stack | ✅ all 5 layers, **LEC=PROVEN** (formally verified), 12.6s |
| exp1 (async_fifo graycomb) full stack | ✅ all 5 layers, **LEC=PROVEN**, dual-clock dualsim works |
| Sabotaged live logic (H3_new wrong reg) | ✅ caught 3 ways: gate 0/4, LEC 12391 unproven, dualsim mismatches |
| Workspace baseline reproduction | ✅ bit-exact: sha512 3984.2037/−97.30; async_fifo 918 cells/+22.22 |
| Parallel eval (3 sha512 candidates) | ✅ 31s wall total |
| STA feedback on sha512 | ✅ 5 distinct endpoints, all tagged **arith-carry-chain** (correct) |
| End-to-end stub loop (2 rounds) | ✅ select→propose→verify→measure→accept→backup→plateau-stop |

**exp2 quantified under the likely metric: ADP ratio 0.787 (−21.3% area-delay product).**

**Fixes/discoveries along the way:**
- **L4 SOLVED (task #8):** `run_syn.sh` sources `env.sh` which unconditionally exports
  VT/CORNER/ABC_AREA (clobbers caller), while the STA step uses caller values → knob overrides
  would synth one lib and time another. Knobs only usable via workspace-patched env (deferred).
- **OpenSTA trap:** harness `-endpoint_count 10` = 10 paths through ONE endpoint;
  `-group_path_count 10` gives 10 distinct endpoints. Workspaces auto-patch run_sta.tcl
  (repo untouched).
- exp2's `t1`/`t2` wires are dead code (a_new/e_new computed standalone) — first sabotage test
  "passed" because the mutation was genuinely unreachable; stack verdict was correct.
- Fingerprint dedup: cosine >0.999 falsely merges 25k-cell designs → exact histogram+depth match.
- Old `agent/optimize_agent.py` superseded (kept for reference).

**Session ledger:** stub run = 2 calls / ~30k tokens tracked; all evaluations in
`agent/ledger/sha512.jsonl` + round records in `sha512_rounds.jsonl`.

### NEXT TASKS — NVIDIA
1. **W-schedule P2 rewrite** (`sha512_w_mem.v:200` serial 4-operand add → balanced) composed on
   top of exp2 → bank via the new pipeline.
2. sha512 pipelining variant (TB latency-tolerant) as a separate frontier entry.
3. Add OpenTitan IPs to the `IPS` registry (ascon first) — needs subtree strategy for workspaces.
4. Small open spec items: self-debug compile retry (0.5), netlist audit (0.3), reflector LLM call
   (2.3), history folding (2.4), GEPA offline (4.1), policy-as-code (4.2).
5. Vertex Express Mode self-signup attempt → real rounds + decoding-config mini-sweep.

**Day-5 addendum — exp3 (W-schedule P2) result: NEUTRAL, lesson banked.**
Composed variant (exp2 core + `w_new = (w_0+d0) + (w_9+d1)`) → all 5 verify layers PASS,
LEC=PROVEN, PPA **bit-identical** to exp2 (3960.2925 / +235.36 / 28955 cells): ABC already
rebalances pure N-operand sums. Refined P2 applicability (playbook `p2-pure-sum-noop`):
source balancing pays only when serial adds are ENTANGLED with nonlinear logic between terms
(exp2's Ch/Maj/σ case, +332ps), not on clean sums. Also observed: proxy `ltp` depth is blind to
ABC-level restructuring (76 for baseline, exp2 AND exp3) — pre-filter only, never a win signal.
exp3 NOT added to frontier (no improvement); exp2 remains best sha512 (ADP 0.787).

## Day 5 (cont.) — ascon on the new pipeline: infra DONE, profile in hand

**OpenTitan dual-representation trap SOLVED:** gate builds `rtl/*.sv` (FuseSoC) while synth reads
`generated/*.v` (SKIP_SV2V=1) → editing either alone is self-deception. Flow now: candidates edit
`.sv`; workspace regenerates touched modules via **host ARM sv2v 0.0.13 (brew)** — container sv2v
is x86-only/Rosetta-dead. Host regeneration validated **byte-identical** to committed output
(prim_ascon_round). Workspaces: **APFS copy-on-write clones** (`cp -Rc`): 700M opentitan in 2.0s,
~zero disk; stale obj_fusesoc/BUILD purged per candidate for clean gate builds.

**Validation:** baseline reproduces exactly (area 1789.7679 / 12295 cells / −430.14ps / 18.4mW;
proxy depth 83). Self-check (pristine prim_ascon_round.sv round-trip): lint/compile/gate PASS,
**LEC=PROVEN**, dualsim PASS — all 5 layers work on OT designs.

**Profile (new fact):** WNS −430.14 but **TNS −642,245 ps** — essentially every reg-to-reg path
violates the 100ps (10 GHz, unmeetable-by-design) clock → cone-wide depth reduction beats
single-path surgery; TNS is the number to watch. Top paths depth 15, OR4/AND4/AOI-heavy
(wide-gate-decode) + one XOR-flavored. Architecture: **1 permutation round/cycle**; reg→reg cone =
input mux → ARK ⊕ rcon → S-box (affine-in ⊕ / χ AOI / affine-out ⊕) → linear (⊕ of 2 rotations)
→ 4-way writeback mux → FF. rcon from `get_ascon_rcon(counter)` decode.

**exp4 (ascon lever B — writeback-mux late-signal isolation): REJECTED, key lesson banked.**
All 5 verify layers PASS incl **LEC=PROVEN** (pure refactor confirmed), but timing slightly WORSE:
setup −430.14→−442.89 ps, area +0.37%, +101 cells, **proxy depth 83→83 (unchanged)**. ABC's
timing-driven mapping already isolates late mux inputs; the RTL hint was absorbed and the extra
`sel==ROUND` compare added cells. **This is exp3's lesson confirmed on a 2nd design/family:** ABC
recovers LOCAL restructuring (pure-sum reassoc, mux balancing); only GLOBAL algebraic changes it
can't reverse survive (exp2 entangled adder tree; GF-basis swaps for AES). Playbook:
`ascon-mux-isolation-noop`. Infra win: the OpenTitan dual-file hand-candidate path (edit .sv for the
Verilator gate + matching generated .v for synth/LEC/dualsim, skip-regen rule) works end-to-end.

**Strategic reassessment of ascon headroom:** −430 ps ≠ large RTL headroom. ascon runs **1
permutation round/cycle** against a **physically-absurd 100 ps (10 GHz)** target; the round cone
(~15 levels: input-mux → ARK → S-box χ/affine → linear ⊕-of-rotations → writeback-mux) is already
near-minimal and ABC-optimized. The permutation algebra (Ascon is a lightweight cipher, designed
lean) offers little ABC-resistant structure. Remaining ascon lever = **pipeline within the round**
(split S-box|linear across cycles) — but that changes latency AND needs round-counter FSM surgery;
high risk, TB-tolerance unverified. ⇒ ascon reclassified **LOW practical RTL headroom**.

## Day 6 — 2026-07-04 — 🎯 Hidden-testcase readiness: auto-onboarding built + contest bug found

**Context shift (organizer email):** submission due **Jul 15 AoE** (slides ~15 + agent w/ run
instructions); presentations = limited cloud-track slots selected from these; **final scoring at
DAC on HIDDEN testcases run through the submitted agent via Vertex** (token/API usage extracted
there). ⇒ the AGENT is the submission; hand RTL wins matter as evidence + skill fuel only.
NVIDIA and NXP graded separately → two writeups. Repo-vs-email submission TBD (office decision).

**Auto-onboarding (`ppa/discover.py`) BUILT + VALIDATED** — constructs IPSpec from repo
conventions alone (run_syn.sh anchor; env.sh DESIGN_NAME/VERILOG_FILES/FILELIST; *_yosys.f;
constraint.sdc create_clock; TB-runner detection; clk/rst port classification w/ active-level
inference incl. wrst/rstn/trailing-_ forms; OT dual-representation + skip_sv2v detection;
subtree/clean-dir inference). Hand entries = validation fixtures: **async_fifo, sha512, ascon all
MATCH**; **aes, kmac, prim, NVDLA onboarded with zero hand config** (NVDLA: 323 sources, partition
clocks found). `get_spec()` prefers hand entries, falls back to discovery by name or path.

**🐞 CONTEST REPO BUG (aes):** ships `generated/all_modules.v` aggregating ALL 84 modules that
also exist as per-module files → yosys "Re-definition of module" ERROR under SKIP_SV2V=1, and
`run_syn.sh` **masks it with a SUCCESS banner** (netlist never written; STA then fails).
Verified 84/84 duplicated, none unique; only aes has this file. Fix = workspace clones drop
all_modules.v (repo pristine); discovery excludes it. ⇒ **aes recorded baseline −1083.58 was from
a tainted flow; clean reproducible baseline = area 10100.51, 74234 cells, 7478 FF, setup
−848.15 ps, 65.6 mW, proxy depth 188.** Worth reporting to organizers (also a slide-worthy find).

**Agent completions:** self-debug repair loop (compile/regen failures → ≤2 retries w/ stderr,
budget-gated) + reflector (round outcomes → playbook votes/ADDs via deterministic curator; no-op
on stub). Vertex signup steps handed to Hari (Step 1 needs his Google account).

**Day 6 completion (2026-07-05):** kmac baseline via discovery = **EXACT match** to recorded
(13353.81 / 97078 cells / −1115.75; proxy depth 139, only 788 FF — huge comb design). aes Verilator
gate PASS through a discovered-spec workspace (clean FuseSoC build). run_gate.sh now accepts
explicit gate_dir/gate_cmd (registry-free → hidden IPs); controller CLI auto-discovers unknown
IP names. **Hidden-testcase readiness: COMPLETE** — the agent can onboard, gate, synth, verify,
and optimize a never-seen design directory with zero hand configuration.
All 7 IPs now have clean baselines through ONE flow:
| IP | area | cells | setup | note |
|---|---|---|---|---|
| async_fifo | 120.37 | 918 | +22.22 | MET; differentiator |
| sha512 | 3984.20 | 29307 | −97.30 | exp2 banked: 3960.29 / +235.36, ADP 0.787 |
| ascon | 1789.77 | 12295 | −430.14 | low practical headroom (Day-5) |
| aes | 10100.51 | 74234 | **−848.15** | clean flow (old −1083.58 tainted by all_modules bug) |
| kmac | 13353.81 | 97078 | −1115.75 | 788 FF / 97k cells |

### Day-6 wrap — state, blockers, open decisions (2026-07-05)

**Validated today (full list):**
- `ppa/discover.py` auto-onboarding: 3 hand fixtures MATCH; aes/kmac/prim/NVDLA onboarded
  zero-config. `get_spec()` = hand registry first, discovery fallback (by name or repo path).
- aes: contest bug (all_modules.v re-definition, masked by SUCCESS banner) found + workspace-level
  fix; clean baseline area 10100.51 / 74234 cells / setup −848.15 / 65.6mW / proxy depth 188;
  Verilator gate PASS through discovered-spec workspace (clean FuseSoC build).
- kmac: baseline via discovery EXACT match (13353.81 / 97078 / −1115.75 / 105mW / depth 139).
- run_gate.sh: optional gate_dir/gate_cmd args (registry-free); validated via sha512 (PASS through
  explicit-override path). verify.tb_gate always passes spec gate location now.
- controller CLI: unknown --ip → auto-discover + register (hidden-testcase entry point).
- Self-debug repair loop (≤2 stderr-fed retries on compile/regen fail, budget-gated) and
  reflector (VOTE/ADD → deterministic curator) wired into controller rounds.

**BLOCKED on Vertex Express Mode key (Hari action — AgentSetup.md Step 1):**
real handshake test → real rounds on sha512/ascon → decoding-config mini-sweep (~25 calls,
temp 0-0.4 / top_p 0.4-0.7 region) → aes/kmac agent runs → reflector/repair live validation.

**Open decisions:**
1. Report aes all_modules.v bug to organizers? (affects everyone's aes evaluation; good pre-Jul-15
   flag; draft ready on request)
2. Next work block while blocked: NXP Phase 0 (port-exactness gate, reset triple-layer, YAML
   validator — model-free, spec in nxp_work/AGENT_UPGRADE_SPEC.md) vs NVIDIA slide outline.
   Lean: NXP Phase 0 first; slides once real-model results exist.
3. Submission repo vs email: waiting on Hari's office decision (Jul 15 deadline).

**Housekeeping note:** HANDOFF.md is now stale (predates the research sprint, ppa package,
discovery, submission-email context) — refresh before any session handoff. Current
ground truth = this log + RESEARCH_NOTES.md + nvidia_work/AGENT_UPGRADE_SPEC.md status header.

## 2026-07-11/12 — Submission-readiness sprint: cold-start drill (bug found+fixed), model iface hardened, --emit-best

**Context:** Hari expects the Vertex key only ~week before DAC; Jul-15 submission = slides +
agent runnable with existing models. NVIDIA has NO runner contract (per README: "build your own
agent on top of Vertex AI (AgentSetup.md)"; they run it with Vertex to extract tokens/calls;
promised eval metric never published — repo untouched since May 28). Hari has a personal Gemini
subscription → GEMINI_API_KEY path added (below), key setup pending.

**Cold-start hidden-testcase drill — FOUND+FIXED a scoring-critical bug:** planted a copy of
async_fifo in the contest repo as an unknown IP. Discovery keyed it by env.sh DESIGN_NAME
('async_fifo') → aliased onto the existing registry entry and **silently reused async_fifo's
cached baseline** (no fresh measurement). A hidden testcase whose top-module name collides with
any known IP would be scored against the WRONG baseline. Fix (discover.py): registry/ledger key
is now LOCATION-derived (ip_root.name, NVDLA syn/ quirk handled, md5-suffix if a different
location collides); env.sh DESIGN_NAME remains the synthesis `top` only. Fixtures re-validated
(async_fifo/sha512/ascon MATCH; aes/kmac/prim/NVDLA/mystery onboarded). Drill now: fresh
baseline measured+cached under its own key, full round (propose via replay → verify → measure →
objective decision; exp1 graycomb honestly REJECTED: regresses area). **Repeatable:
`python3 test_cold_start.py` → 6/6** (asserts key-not-DESIGN_NAME, no aliasing, fresh baseline,
explicit decision).

**Model interface hardened (proposer.py):** VertexModel auto-detects EXPRESS_MODE_KEY (Vertex
Express, = organizers' eval path) vs GEMINI_API_KEY (AI Studio, personal-key dev); lazy
google-genai import with pip-install message; retry ladder now 429+5xx w/ capped backoff.
NEW EndpointModel (NXP-runner-style POST /generate, stdlib urllib) in case their harness fronts
Vertex with an endpoint — also lets the NXP mock endpoint smoke this agent offline. Controller
CLI: --model {stub,vertex,endpoint}, --model-name, --endpoint, --temperature/--top-p.
**Validated: `python3 test_model_iface.py` → 13/13** (fake google-genai module exercises the
REAL VertexModel path: both client-init modes, usage-metadata token accounting, config
passthrough, 429→503→success retry, non-retryable raise, missing-key SystemExit; EndpointModel
against a live local HTTP server incl retry).

**--emit-best (controller.py):** submission artifact — winning candidate's files in
repo-relative DROP-IN layout + manifest.json (result, cid, changed_files, baseline vs best PPA,
ADP ratio, verification statement — candidates pass the full 5-layer stack incl LEC at
acceptance — calls/tokens, per-round history). Validated both ways: sha512 recovered the BANKED
pool winner (ADP 0.787, 5 files → nvidia_work/submission/sha512/) with zero new proposals
(pool persistence = wins survive across runs); async_fifo → manifest-only "no-improvement:
baseline is the submission".

**CLI unstaled:** evaluate/verify --ip now free-form with auto-discovery (was hardcoded
{async_fifo,sha512,ascon}); sta_feedback ditto. (Also confirmed: evaluate --baseline DOES force
refresh; async_fifo full Docker synth+STA reproduces the recorded baseline bit-for-bit in ~2.3s.)

**Regression (all green):** model iface 13/13 | discover fixtures 3 MATCH | evaluate fresh
baseline OK | cold-start 6/6.

**Open:** GEMINI_API_KEY/EXPRESS_MODE_KEY setup + first real handshake (Hari's key, then
`--model vertex --model-name ...` 1 round on sha512); decoding-config sweep; aes/kmac agent
targets; README/run instructions for the submission package; slides (start Jul 12).

## 2026-07-12 (cont.) — FIRST REAL-MODEL ROUNDS (Vertex Express Mode live)

**Key live (Hari's personal Express Mode signup, stored in .env, chmod 600, gitignored;
key never entered the session transcript).** Handshake: gemini-3-flash-preview responds.
SDK: google-genai on system py3.9 (EOL warnings, harmless).

**LIVE FINDING #1 — thinking-model empty responses:** round 2's three proposals all returned
EMPTY text while consuming ~20k tokens each. Probe on a real prompt: finish=MAX_TOKENS,
0 parts, **62,913 thought tokens** — gemini-3-flash-preview thinks by default and burned the
whole default cap on thoughts. FIX (both agents' VertexModel): explicit
`max_output_tokens=65536` + `thinking_config={"thinking_budget": 8192}` (thinking_level not
supported by SDK schema; budget-capped probe: finish=STOP, thoughts 590, real text).
Also: token accounting now uses usage.total_token_count (INCLUDES thoughts = what billing/eval
sees — the old prompt+candidates sum undercounted by the entire thinking spend);
empty-text response = one bonus retry.

**LIVE FINDING #2 — format compliance:** Gemini emits fenced code blocks w/o our `// FILE:`
markers ~2/3 of the time. parse_response now falls back to mapping ``` fences by declared
module name → source path. Raw responses now dumped to ledger/raw/<ip>/ (controller._dump_raw)
for postmortems + the config sweep.

**ROUND RESULTS (sha512, k=3, arith-carry-chain tag):**
- Round 1 (pre-fixes): 1/3 parsed, candidate gate-failed; reflector banked a REAL lesson:
  "manual carry-save (3:2 compressor) insertion in sha512 → gate-level flow failures".
- Round 3 (post-fixes): 3/3 parsed. balanced-tree → rejected DUPLICATE (Gemini independently
  reinvented our hand-derived exp2-style rewrite; fingerprint dedup caught it — validates both
  the strategy and the dedup). carry-save → gate-fail (consistent w/ lesson). **arith-arch →
  ACCEPT: first model-generated, gate-passing, measured improvement — ADP 0.898 vs baseline**
  ("improves perf, regresses none"). Banked exp2 (0.787) still global best; emit-best correct.
  ~112k total tokens/round (thoughts included), ~2.3 min wall.
- Deepen rounds (2 more, parent-sampled) launched; results TBD below.

Carry-save note: 2/2 gate-fails with "GATE: FAIL (pass=0 fail=0)" — TB produced no results
(hang or output-format break). Raw dumps will tell; candidate for a directed AVOID rule if it
repeats in the sweep.

**Deepen-round results (2 rounds, 7 calls, ~203k tokens):** round 1 parent=arith-arch: 3
rejects (1 measured-worse, 2 gate-fail — honest gates). Round 2: **second ACCEPT —
restructure-select ON TOP of arith-arch ("improves perf,area, regresses none", ADP vs parent
0.985 → composed model-generated line ≈0.884 vs baseline).** Banked exp2 (0.787) still global
best and correctly emitted. Frontier=2. The loop demonstrably composes improvements across
rounds via parent sampling.

## 2026-07-13 — Offline hand-candidate campaign across all 7 IPs (zero-token, pre-Vertex)

Goal (Hari): run the agent ourselves on every IP before Vertex — author candidates, push through
the full verify+measure machinery, bank wins / distill AVOID rules.

**All 7 IPs baselined** (was 5/7). NVDLA: 952,591 cells / WNS -5788 ps (full 323-src tree
synthesizes). prim: multi-design dir (crc32/ascon_duplex/trivium via DESIGN_NAME); prim_crc32
= 436 cells / -208.95 ps (violated → new small optimization target). Getting these two working
fixed 3 harness gaps (all hidden-testcase robustness): quoted ${VAR:-def} env parsing;
per-design report prefixes + DESIGN_NAME→TOP threading in measure.sh; adaptive run_syn.sh CLI
(prim takes no `all` arg). discover get_spec now matches location key OR DESIGN_NAME.

**Results per IP:**
- **sha512 — NEW BEST, ADP 0.7433** (was 0.787). exp6 = compose of exp2's balanced-tree core
  (touches only sha512_core.v) with the live model accepts' DISJOINT edits (w_mem/sha512.v/
  k_constants). LEC-PROVEN, all 5 layers, WNS -97→+308 ps. Human technique + model discovery
  composing. Exposed + fixed an acceptance-policy bug: pure Pareto vetoed exp6 for +0.23% area
  despite ADP 0.787→0.743 → added headline-metric override (strict ADP win accepted,
  power-guarded). Re-banked; submission manifest = 0.7433; cold-start still 6/6.
- **async_fifo — probed, rejected (P24).** exp5 gray-share (share gray(bin+1) across full/
  almost-full, reuse registered gray for hold): LEC-PROVEN tradeoff, +7.2ps slack for +3.7%
  cells/power. Correctly rejected (timing already MET); banked as a lever for a violated async
  pointer path.
- **kmac — measured no-op (P25 AVOID).** STA path analysis pointed at the entropy PRNG
  (kmac_entropy ltp=50), so exp7 flattened the 800-step serial Bivium/Trivium key-stream unroll
  into 65-wide data-parallel generation chunks. Python golden model PROVED equivalence over
  random states; but synth timing did NOT improve (-1115.75→-1119.68 ps, cells +0.7%) — ABC
  already retimes it. Honest negative. Also surfaced: kmac generated RTL fails iverilog
  elaboration on a PRE-EXISTING sv2v artifact (hw2reg driven by instance output; legal SV,
  illegal V2001, yosys-fine) → added **differential gating**: a verify layer that fails
  IDENTICALLY on pristine can't indict a candidate (compile=PRE-EXISTING → skip TB/dualsim,
  LEC remains correctness gate). Cached per-IP; cold-start + sha512 regressions green.
- **aes — lever identified, NOT pursued (scope question for Hari).** SecSBoxImpl=4 = DOM-masked
  S-box; switching to unmasked LUT/Canright is a big area/timing win but DOWNGRADES a
  side-channel countermeasure — a security-scope decision, not clean RTL optimization. Flagged,
  not claimed.
- **ascon — low practical headroom** (known from survey; not pursued this pass).
- **NVDLA / prim_crc32 — baselined, large timing headroom, un-campaigned** (expensive/new;
  candidates deferred to Vertex).

**Net:** 1 verified PPA win banked (sha512 0.743, improving on our prior best), 2 well-founded
AVOID/lever playbook rules from honest negatives, all 7 baselined, harness hardened 4 ways.
Playbook now 31 bullets. Ready for the Vertex campaigns across all IPs.

## 2026-07-13 — Vertex campaign #2: prim_crc32 (NULL RESULT, well-documented)

Second real-model campaign (first was sha512 Jul 12). Target: prim, baseline prim_crc32
436 cells / -208.95 ps (violated). 3 rounds, k=3→1, gemini-3-flash-preview, 10 calls,
~195k tokens (ledger note: the ~1.95M figure printed is cumulative-across-reruns; this run ≈195k),
~11 min wall. **Result: no improvement — baseline emitted (manifest-only).**

**Per-candidate outcomes (all 5 gate-passed via differential compile gating):**
- balanced-tree → targeted prim_ascon_round.v → DUPLICATE (fingerprint dedup; model reproduced
  a structure already seen).
- carry-save → prim_sha2.v → no meaningful change (measured, ADP≈1.0).
- micro-opt r1 → prim_alert_receiver.v → regresses perf,power (setup -208.95→worse).
- micro-opt r2 → prim_crc32.v → SYNTH-FAIL (bit-width inconsistency in inserted wire).
- micro-opt r3 → prim_sha2.v → no meaningful change (-208.95 held; +0 cells).

**Analysis (slide-worthy honesty):** (1) The agent explored the RIGHT modules unprompted
(crc32 itself, plus the other timing-relevant prim designs sha2/ascon_round). (2) It correctly
found NO win — prim primitives are small, already ABC-optimal; every measured candidate was
flat or worse. (3) The verification firewall did its job end-to-end on a REAL model: dedup
caught a repeat, differential compile gating let candidates through the pre-existing sv2v
elaboration failure (prim, like kmac, fails iverilog on the fileset — WITHOUT differential
gating all 5 would have been falsely rejected as compile-fail), and honest reject reasons fed
3 reflector lessons (AVOID restructuring primitives synthesis already optimizes; maintain
bit-width consistency; don't micro-opt at the tool's limit).

**Bug fixed mid-campaign:** first attempt crashed — `_pristine_layer_fails` (the new
differential-gating helper) used a fixed workspace tag, so k=3 parallel workers raced on one
directory (OSError dir-not-empty). Fixed: threading.Lock + pid-tagged pristine workspace; one
build shared across workers. Verified: cold-start 6/6, parallel k=3 smoke green, then re-ran.

**Takeaway for the deck:** a null result that STRENGTHENS the credibility story — the agent
picks sensible targets, the gates hold under a real model, dedup+differential-gating+reflector
all demonstrably fire, and we report "no headroom here" honestly rather than shipping a
regression. Contrast with sha512 where real headroom → real win (0.743). Different IPs, honest
outcomes both ways.

## 2026-07-13 — Attribution experiment + STRATEGY SHIFT: diagnose-with-tools before any model call

**Trigger:** the aes campaign's prompt was 174k tokens (all 75 files dumped as context) → slow,
self-throttling on free-tier TPM, token-wasteful. Context IS spent budget (tokens = the scoring
tiebreak), so context selection must be a first-class strategy, not plumbing.

**Experiment: which modules actually contribute to worst PPA? (aes, zero model tokens)**
Compared two attribution methods empirically instead of guessing:
- **Method A — depth ranking** (per-module standalone yosys `ltp` logic depth): top hits
  aes_ghash(263), aes_reg_top(241), aes_core(238), aes_key_expand(131) → points at the
  GHASH GF(2^128) datapath (the survey's "expected" ABC-resistant target).
- **Method B — real STA, hierarchy preserved** (`FLATTEN=0 ./run_syn.sh` → OpenSTA critical
  path carries full instance names): the ACTUAL delay-critical clk_i path runs
  `u_reg/u_chk` (TL-UL command-integrity checker, wide XOR chains) → `u_reg/u_prim_onehot_check`
  (register write-enable one-hot checker) → `u_aes_core/u_aes_control/u_aes_control_fsm`.

**THE TWO METHODS DISAGREE.** Depth says datapath/GHASH; real STA says register-bus integrity +
control FSM. Depth ranking flags deep-but-FAST logic and misses the slow path — it would have
misdirected the entire aes campaign. **Decision: use Method B (hierarchy-preserved OpenSTA
attribution) — depth≠delay.** Caveat: FLATTEN=0 shifts cross-boundary opt (WNS −2327 vs
flattened −848), so attribution is approximate for the real flattened design but still a real
timing analysis on real modules — far better than depth guessing.

**aes-specific consequence:** our datapath fence (cipher/mixcol/GF) points the model AWAY from
the real bottleneck (control/register logic). The integrity checkers are balanceable XOR trees
but are OpenTitan security-integrity features (S-box-like scope question); the aes_control_fsm
is fair game. aes strategy decision pending Hari.

**STRATEGIC SHIFT (applies to BOTH NVIDIA and NXP): tool-diagnosis precedes model calls.**
We have the diagnostic tools; run them FIRST, extract actionable findings, hand those to the
model. This (1) slashes tokens (send analysis + targeted files, not the whole tree), (2) improves
results (model gets actionable direction, not a haystack). New agent shape:
  DIAGNOSE (tools, 0 tokens) → INDEX+ANALYSIS (small call) → model REQUESTS files → EDIT (call).

**Toolchain inventory (container iclad-dev:v1):** yosys 0.63 (synthesis + area via `stat`),
OpenSTA 3.1.0 / `sta` (timing + power estimate). **Full OpenROAD (P&R) NOT present — and not
needed:** the contest scores POST-SYNTHESIS PPA (yosys+STA), not post-place-and-route, so our
flow matches the scoring flow exactly. abc is built into yosys; verilator+iverilog for sim.

## FUTURE IMPROVEMENTS (post-Jul-15; experiment post-Jul-19 on unlimited GCP) — for slides "future work"

Captured during the Jul-13 staged-optimizer build. All are additive to the shipped agent.

1. **Model selection & mixing (per-task).** Use the strongest reasoning model (e.g. Gemini
   Pro / gemini-3-pro) for the CREATIVE proposal step where equivalence-safe correctness is
   hardest, and a cheaper model (Flash) for MECHANICAL steps (gate-fail repair = "find the bug
   you nearly fixed", reflector distillation). Rationale: our own survey's model-scaling data
   (Opus 21% / Sonnet 12% / Haiku 3% WNS; SEC-pass 86/73/57%) shows strong models are
   dramatically better at CORRECT creative RTL rewrites — exactly the "12/16 tests pass"
   near-miss class we hit on sha512_core. Deliverable: per-step model routing (currently one
   model/run); benchmark Flash+repair vs Pro on the same stage (success rate, tokens, ADP).
   Pro is paid-only on the API today (free on the Jul-19 GCP accounts / at DAC where all Gemini
   models are available). Token tiebreak: Pro costs more/call but may need far fewer attempts,
   so total tokens for a successful optimization could be comparable or lower — measure it.
2. **Growing stage-batch curriculum.** Start 1 file/stage (max reliability); once the loop is
   landing wins consistently, grow the batch (2, 3, …) to cover more files/turn. Experiment
   with the batch schedule as a hyperparameter.
3. **Per-round re-diagnosis.** The critical path SHIFTS as earlier files are optimized; re-run
   the (zero-token) diagnosis each stage so the cursor tracks the CURRENT worst path, not the
   baseline one. (Currently static from baseline diagnosis.)
4. **Agentic file request (Phase 3).** Model reads the index+diagnosis and REQUESTS the files
   it needs (editable + read-only deps) rather than us pre-selecting — handles cross-file
   dependencies the static heuristic can miss.
5. **Budget-adaptive context.** Send more context early (explore), tighten as budget depletes.

## 2026-07-13 (late) — ROOT-CAUSE: naive context-trimming regressed reliability; fixed

**Symptom (Hari caught it):** before the staging edits, live sha512 runs reliably produced the
balanced-tree win (ADP 0.787). After staging (forced --diagnose on), 6/6 candidates gate-failed
on sha512_core. Investigated the raw responses rather than guessing.

**Root cause — TWO harness bugs (not model weakness; the model correctly chose balanced-tree,
0 aggressive-transform attempts):**
1. **Hallucinated out-of-scope edits kept.** Given ONLY sha512_core.v to edit, the model also
   returned edits to sha512_w_mem.v — a file it could NOT see (scoped out) but knew existed from
   the file list — inventing its content from training memory. Our filter only dropped
   `readonly` files (empty on stage 1), so the hallucinated w_mem was MERGED in → broke the hash
   → gate-fail. (3/6 candidates did this.)
2. **Scoped context starved grounding.** Even core-only edits gate-failed: without seeing
   w_mem/top/constants, the model can't follow the data flow into sha512_core, so its edits have
   functional bugs. Our winning exp2 touched ONLY sha512_core but was authored with FULL context
   visible.

**IMPORTANT: the SHIPPED sha512 was never regressed** — production uses --diagnose AUTO, which
keeps staging OFF for small IPs (<15 files) → full context → the proven path. The failure only
appears when staging is FORCED on for testing. Validates "full context when affordable".

**Fixes:**
1. **Strict batch-only filtering:** accept edits ONLY to the stage's batch files; drop any
   hallucinated/out-of-scope file (both proposal and gate-fail-repair paths).
2. **Dependency read-only grounding:** send the OTHER critical files (locked earlier stages +
   not-yet-reached dependencies) as READ-ONLY context (bounded by _RO_CAP=6), so the model
   understands the data flow without being able to edit them. sha512 stage 1 now sends core
   (editable) + [w_mem, sha512, h/k_constants] (read-only).

**Lesson for large IPs (slide-worthy):** context-trimming must preserve DEPENDENCIES, not just
send the target file alone — naive trimming trades tokens for correctness. Verified: stub e2e
coordinate-descent chains 0.787→advance; cold-start 6/6. Real-model re-run pending (next session,
possibly stronger model per the model-mixing future-work item).

## 2026-07-13 (night) — STAGED COORDINATE DESCENT: FIRST CLEAN END-TO-END WIN (run 1 post-fix)

sha512, fresh pool, Key 1, gemini-3-flash-preview, k=6→4, 1 file/stage, no retry, max 20 turns.

| stage | file | k | outcome |
|---|---|---|---|
| 1 | sha512_core.v | 6 | ✓ ACCEPT arith-arch, ADP 0.938 (5/6 candidates had out-of-scope w_mem edits — filter caught all) |
| 2 | sha512_w_mem.v | 4 | ✗ no win (2 regress, 2 duplicate) — kept best |
| 3 | sha512.v | 4 | ✓ ACCEPT balanced-tree vs stage-1 winner, 0.981 → accumulated 0.920 |
| 4 | sha512_h_constants.v | 4 | ✗ no win (constants: no timing headroom, as expected) |
| — | plateau stop (0.938→0.92 < 0.02 delta over 3 rounds) before stage 5 (k_constants) | | |

**Final: ADP 0.92 vs baseline; timing -97.3ps VIOLATED → +26.32ps MET; area 3984→3973.**
18/20 proposal turns, 22 calls total, ~650k tokens. Emitted → submission/sha512_staged_clean.
Both accepts full 5-layer verified (lint/compile/TB/LEC/dualsim). Coordinate descent CHAINED:
stage-3 win built on stage-1's locked file. Strict scope filter fired 9 times across the run —
every one would have been a silent gate-fail before the fix. Grounding+filter = the difference
between 0/6 accepts (previous run) and a clean staged descent.

Note: plateau stop cut stage 5 (saved 2 turns on a zero-headroom constants file) — acceptable;
consider disabling plateau in staged mode if full file coverage is ever preferred.
Fable code review same night: compile-repair scope filter added, empty-diagnosis fallback guard,
API-dropped calls no longer consume turns, stale retry comments removed.

## 2026-07-14 — A/B/C context-grounding experiment (sha512 stage 1, k=6, same strategies)

| config | context for target file | correct | out-of-scope attempts | accept | tokens |
|---|---|---|---|---|---|
| A grounded | + other crit files (full, read-only, _RO_CAP=6) | **3/6** | 5/6 | ✓ arith-arch 0.893 | 329k |
| B alone | target file only | 1/6 | 1/6 | ✓ arith-arch **0.727** (best-ever sha512, LEC-PROVEN, slack +334.6ps) | 232k |
| C stubs | + port-header stubs of instantiated modules (32 lines, 5% of full) | 0/5* | **0/5** | — | *quota-cut |

*C incomplete: Key 2 free tier = **20 requests/day** (request-count, not tokens!) — killed 1
proposal + the repair leg. C's gate-fails are genuine though (complete, compiling outputs;
pass=0 hang signature = behavioral starvation — port widths alone don't convey latency/protocol).

**Findings:** (1) grounding buys per-candidate correctness (3/6 vs 1/6) — the contracts matter;
(2) visible file bodies invite out-of-scope co-editing (5/6 vs 1/6) — the strict filter is what
protects either way (B still hallucinated w_mem from training memory!); (3) B's better winner is
n=1, plausibly sampling luck. **DECISION (Hari): config A (--grounding on) = staged default** —
2/2 runs with stage-1 accepts (0.938, 0.893), reproducible. C = right token-bounding shape for
huge IPs but needs richer stubs (+ latency notes) — post-Jul-15 item.
Robustness fixes from the experiment: repair calls (compile + gatefail) now crash-protected
against API errors (Key-2 429 killed run C's repair leg mid-flight).

## 2026-07-14 — aes staged campaign #1: 3 harness bugs found by real fire, all fixed

Run: 20-turn staged, config A, S-box fenced, Key 1. Result: no accepted win — but the run was
compromised by harness bugs it exposed (this is why we run before we trust):

1. **Fence ordering** — fence ran BEFORE scope filter, killing candidates whose S-box edits were
   out-of-scope anyway (scope would have dropped them harmlessly). Cost: 5 candidates across
   stages 1–3. Fix: fence now vetoes only SURVIVING (in-scope) edits.
2. **Fence false positive (the big one)** — fence checked token PRESENCE (`SecSBoxImpl =`), but
   pristine aes_core.v legitimately carries that parameter pass-through, so EVERY complete
   aes_core rewrite tripped it. **Wiped all 4 candidates of stage 4 (aes_core, the most promising
   file) without evaluation.** Fix: flag only if token-bearing lines DIFFER from pristine
   (whitespace-normalized). Verified: pristine/benign pass, value-change + sbox-file still reject.
3. **Netlist-collapse hazard** — a prim_onehot_check candidate synthesized to 3,903 cells vs
   baseline 74,234 (5% of aes: body edit broke elaboration, hierarchy pruned) and "improved"
   every metric. Saved only by the LAST layer (dualsim ERROR → reject); TB gate is skipped on aes
   (pre-existing pristine artifact) and LEC was INCONCLUSIVE. Fix: candidates <50% of parent
   cells now rejected as netlist-collapse BEFORE any PPA comparison.

Positives from run 1: grounded candidates 100% functionally correct at measurement (8/8 full
verify); honest measured rejections; repair correctly idle; model gravitates to the S-box
(5 fence hits) = timing headroom concentrated in fenced security logic, so non-S-box wins are
the realistic target. aes v2 rerun launched with all fixes (fresh pool, same protocol).

## 2026-07-14 — aes v2 (all fixes): first live aes accept; aes_core cleanly answered

20 turns, config A, fresh pool, Key 1, ~1.6M tokens, 22 calls. Stages: intg_chk ✗ ·
**gcm_reg_shadowed ✓ ACCEPT carry-save (power −4.3%, slack +1.2ps, area +0.26%, dualsim PASS)**
· onehot_check ✗ · **aes_core ✗ (3/3 candidates functionally CORRECT, all regress perf — first
fair evaluation of this file; v1's fence bug evaluated 0)** · plateau stop. Final ADP 1.0
(power win is ADP-neutral). Emitted → submission/aes_staged_v2.

**Conclusion (slide-worthy):** aes timing headroom is concentrated in the FENCED masked S-box
(model attempted it 5× in v1). With security fenced, legal critical-path rewrites are correct
but not better — ADP 1.0 is the honest fence-constrained answer. Machinery: 10/10 evaluated
candidates functionally correct in v2, zero harness interference, no hangs (HTTP timeout in).
Repair extension added post-v2: dualsim-fail now joins gate-fail as repairable (aes-class IPs
skip TB, so their broken-but-promising candidates surface at layer 5; PPA already measured).

## 2026-07-14 — prim staged: "no-improvement" IP flipped to our biggest percentage win

12-turn staged (only 6 spent — 1 critical file), fresh pool, Key 1, 167k tokens. Diagnosis
(after fixing a 4-vs-5 unpack crash in the no-timing-paths branch — hidden-testcase-shaped bug)
correctly scoped prim to prim_crc32.v alone (265 pre-map cells; the other 146 library files are
not in the design). Stage 1 k=6: **ACCEPT restructure-select — slack −208.95→−27.46ps (+181.5ps),
area −6.0%, power −67.4%, cells 436→409. TRUE ADP = 0.6045 (delay ratio 0.643 × area 0.940).**
Prior submission for prim was "no-improvement, baseline" — replaced by submission/prim_staged.

**ADP-reporting bug found via prim:** _SDC_PERIODS hand map lacked prim/aes → no period → ADP
printed None/1.0 while the real win was 40%. Fixed: _sdc_period() auto-parses `set clk_period N`
from each IP's own contest SDC (verified: prim 300 / aes 100 / sha512 1500 / kmac 100 /
async_fifo 300ps). prim manifest corrected (ADP 0.6045 + note). aes v2 accept re-computed with
period 100ps: ADP 1.001 — power win (−4.3%) is ADP-neutral, as reported.

Fence removed as default (Hari, 2026-07-14): contest scores tests-pass + PPA only — no
self-imposed restrictions. --fence on retained as an option; --focus flag added (explicit cursor
override). aes v3 launched: unfenced, cursor = [sbox_dom, sub_bytes, cipher_core, mix_columns,
core]. Caveat: aes dualsim is CYCLE-exact — v3 can verify latency-preserving S-box optimizations;
an impl swap (DOM→LUT) changes latency and is locally unverifiable (organizers' aes TB doesn't
run in our env). Transaction-mode dualsim → future improvements.

## 2026-07-14 — aes v3 (UNFENCED, S-box-focused): the complete aes answer

21 calls / 1.3M tokens, focus cursor [sbox_dom, sub_bytes, cipher_core, mix_columns, core],
Key 1 (two stage-3 calls lost to Express 429s — resilient fan-out held, turns not charged).
**1 accept: arith-arch on aes_sub_bytes — power −6% (0.0656→0.0617), slack +3.5ps, dualsim
PASS. ADP 1.0001 (neutral).** All other stages: honest measured rejections. Plateau stop.
Emitted → submission/aes_unfenced.

**The complete aes story:** fenced power −4.3% / unfenced (latency-preserving) power −6% —
both ADP-neutral. Even with the fence REMOVED, cycle-exact differential sim limits the
S-box axis to power wins; the delay headroom needs latency-CHANGING rewrites (impl swap),
locally unverifiable until transaction-mode dualsim (future work, top priority for Jul 19+).
aes is now fully characterized: not "we failed to improve it" but "we mapped exactly where
its headroom is and what verification unlock is needed to claim it."

## 2026-07-14 — submission repo push + fresh-clone verification (caught a shipping bug)

Pushed today's full work to github.com/chelsea85/chip-convergence-iclad26 (commits 5fe1da9 +
55f2770; 1088 files): staged optimizer + all fixes, 5 result manifests (sha512_best_0727 =
0.727, prim_staged = 0.605, aes_staged_v2, aes_unfenced, sha512_staged_clean), evidence
(ledgers/raw/variants), 4 decks (both tracks restructured to 5-act story + Engineering
Learnings companions; one-picture SVG flow diagrams for both).

**Fresh-clone verification (Hari's call — from GitHub, not local) caught a submission-breaking
gap:** nvidia_work/harness/ (run_gate.sh / measure.sh / registry.tsv — mounted into Docker by
the TB gate) was never in sync.sh → a graded fresh clone GATE-FAILED every candidate. Fixed in
sync.sh, pushed, re-verified. Final fresh-clone status: model-iface 13/13 · NVIDIA stub e2e
ACCEPT 0.961 through full 5-layer + Docker synth · NXP sabotage 8/8 · NXP runner e2e 6/6.
Layout requirement (contest repo cloned/symlinked into repo root) confirmed documented in README.

Slide decks (main + learnings, both tracks) live in docs/slides/ — pending Hari's review.

## 2026-07-15 → 07-18 — submission shipped + review-driven fixes (bridge)

Full submission pushed to github.com/chelsea85/chip-convergence-iclad26 (through commit 2b99406).
NVIDIA-relevant items acted on from three external reproducibility reviews:
- **P0 canonical sha512 fix (dcbb101):** the shipped submission/sha512 contained 3 stray
  non-pristine surrounding files (sha512.v, k_constants, w_mem) and measured ~0.7364, not the
  headline 0.7266 — while its manifest claimed changed_files=[sha512_core.v]. Reconciled to
  pristine baseline + optimized sha512_core.v only = the reviewer-verified 0.7266 winner. Root
  cause = sync.sh `cp -R` never deletes stale files → fixed to a clean copy. Independently
  re-synthesized keyless from a fresh clone: area 3967.62624 / setup +334.61 / **ADP 0.7266, full
  5-layer, LEC PROVEN**.
- **_emit_best hardened (ppa/emit.py + test_emit_replace.py, 2/2):** the artifact writer was a
  MERGE (left stale files) then a non-recoverable rmtree-then-rename. Now a clean staged
  replacement WITH ROLLBACK (stage → move-old-aside → swap → restore-on-failure); never destroys
  the last-known-good artifact.
- **Verification language aligned to the per-layer manifests:** prim = equivalence+differential
  (NOT full 5-layer; pristine compile/TB pre-existing); aes = differential-only; the emit `result`
  label now derives from actual ADP (not merely "did a file change").
- Live-key organizer paths validated end-to-end (NXP 2-call solve via run_benchmark; NVIDIA
  --model vertex live campaign) — all on Hari's keys, no repo/transcript leakage.

## 2026-07-19 — remaining IPs on the FREE organizer key: kmac (no-improve), ascon (0.9667 diff-only)

**Key setup (zero cost to Hari).** Organizer-provisioned project "GenAI Chip Hackathon-9207"
(ai-chip-design26lgb-9207, **Tier 3 — organizer-billed**); AI Studio key created via incognito
(so it's NOT Hari's billing) and stored in .env as `HACKATHON_AISTUDIO_KEY`. All campaigns run
`--model vertex --key-env HACKATHON_AISTUDIO_KEY` → proposer mode `ai-studio` (routing follows the
env-var NAME; no "EXPRESS" → no paid-Vertex path), plus `unset EXPRESS_MODE_KEY` in-process as
belt-and-suspenders. Free-tier fallback `GEMINI_API_KEY_2` (AI Studio, ~20/day) also available.
Model = gemini-3-flash-preview (works on AI Studio; a thinking model).

**kmac — honest no-improvement (ADP 1.0).** Zero-token diagnosis: WNS −1559 ps, arith-carry-chain;
the worst path runs through TL-UL/register infra (tlul_cmd_intg_chk, prim_subreg_shadow,
tlul_socket_1n, prim_packer_fifo), NOT the Keccak core; largest area = kmac_app.v (48.7k cells).
Bounded campaign (rounds 2, k 3, max-calls 10, diagnose on): **11 calls, accepted=0.** Every
candidate rejected by the gates — several **DUALSIM-FAIL** (the model's timing edits broke
functionality; differential sim caught them), plus duplicates and perf/power regressions. Emitted
baseline (0 changed files). Correct outcome: kmac's badly-violated bus timing has no safe
local-edit headroom → "baseline is the submission." (Prior offline exp7 = prim_trivium.v, the
masking PRNG, had LEC-ERROR — deliberately avoided this run.)

**ascon — real but weak-assurance win: ADP 0.9667 (−3.3%), DIFFERENTIAL-ONLY.** Diagnosis: WNS
−926 ps, same TL-UL infra critical path; small IP (largest prim_ascon_duplex 6k cells → fast
synth). Campaign (rounds 3, k 3, max-calls 15): **16 calls, 3 accepts**, best = arith-arch on
`tlul_cmd_intg_chk.v`. baseline area 1789.77 / setup −430.14 / cells 12295 → candidate area
1794.26 / setup −411.18 / cells 12031 (timing +19 ps, cells −2.1%, **area +0.25%**, power −1%).
verify: lint/compile/gate/dualsim PASS, **lec INCONCLUSIVE** → assurance = differential-only
(same tier as aes).

### Findings / open concerns (for Codex review)
1. **ascon assurance caveat.** The win edits `tlul_cmd_intg_chk.v` — the bus **command-integrity
   checker** — and LEC is **INCONCLUSIVE**, not PROVEN. gate+dualsim pass functionally, but a
   rewrite of an integrity/parity module that formal equivalence cannot prove is a legitimacy
   concern for a security IP; the gain is modest and area actually ticked up. Recommendation: keep
   ONLY if labeled honestly as differential-only (like aes), never as a headline/proven win.
   Alternatives: seek a LEC-PROVEN candidate (may resist, since the winning edit IS the integrity
   module), or drop it. **Pending Hari's decision.**
2. **kmac is a clean honest negative** — the verification spine correctly rejected every
   functionally-broken candidate. This is a *good* signal for the gates, not a flow failure.
3. **Emit-location bug (mine):** campaigns were run from `nvidia_work/agent` with
   `--emit-best submission/<ip>`, so artifacts landed in `agent/submission/<ip>` instead of the
   real `nvidia_work/submission/<ip>` (convention is `../submission/`). Both kmac + ascon artifacts
   are currently in `agent/submission/` pending a keep/relocate decision. Fix: use an ABSOLUTE
   `--emit-best` path for NVDLA.
4. **NVDLA campaign still pending** — the largest IP (323 sources); baseline only so far. Next.

## 2026-07-19 (rev, after Codex review) — ascon 0.9667 REJECTED as inequivalent; assurance-aware selection fixed

Codex's independent review (`NVIDIA_JULY19_CAMPAIGN_REVIEW.md`) overturned my earlier ascon
conclusion — correctly. **The ascon ADP 0.9667 candidate (`1b5c86d80918`, arith-arch) is
functionally INEQUIVALENT, not merely "differential-only".** It uses the WRONG integrity-bit
slices — `cmd_intg = tl_i[21:15]` (correct [14:8]), `data_intg = tl_i[14:8]` (correct [7:1]) — with
a hallucinated "overlap is expected" comment. A 100,000-vector module differential test found **7
mismatches including false negatives (MISSED integrity errors)** — disqualifying for a bus
command-integrity checker. Verified the slices directly against pristine + tlul_pkg. My "keep it,
honestly labeled" recommendation was wrong; the correct call is REJECT.

**Root cause (systemic) — assurance-blind selection. FIXED.** `frontier.best()` picked the PPA-best
entry regardless of LEC, so an LEC-INCONCLUSIVE candidate with a slightly better ADP displaced the
LEC-PROVEN one. Added `_canonical_best()` (ppa/controller.py): canonical = best-ADP **LEC-PROVEN**
improvement; an unproven (INCONCLUSIVE/ERROR) candidate is NEVER canonical, and if no proven
improvement exists the eligible baseline ships (unproven best recorded as `experimental_best`).
Validated on the existing ascon pool: old logic → `1b5c86d80918` (0.9666, INCONCLUSIVE); new logic
→ **`b153b877f996` (0.9792, PROVEN)**. Protects NVDLA.

**Candidate-aware coverage — FIXED.** For OpenTitan dual-representation IPs, compile/synth/LEC/
dualsim consume the changed generated `.v` but the Verilator TB gate builds the pristine `.sv`, so
a generated-`.v`-only edit's "gate PASS" never exercised the candidate. `_assurance()` no longer
counts a candidate-blind gate as full-5-layer; the manifest gains `candidate_aware_coverage`.

**Banked the valid ascon result:** `b153b877f996` re-emitted to canonical `nvidia_work/submission/
ascon` — one changed file (tlul_cmd_intg_chk.v, CORRECT slices), **ADP 0.97918 (−2.1%), assurance =
equivalence+differential (LEC PROVEN + dualsim PASS; gate ran pristine .sv → candidate .v not
exercised).** The rejected `1b5c86d80918` is quarantined at `submission/_rejected/
ascon_1b5c86d80918_INEQUIVALENT/` with a REJECTED.md — evidence, never canonical.

**Path preflight — FIXED.** `_emit_best` now resolves `--emit-best` to an absolute path, prints it,
and REFUSES to emit under `nvidia_work/agent/submission` (the relative-CWD mistake that mislocated
both artifacts). kmac baseline-only + the corrected ascon are now under `nvidia_work/submission/`.

**kmac — narrative narrowed (Codex).** Not "no safe local-edit headroom" but "no eligible
improvement in this bounded two-stage campaign." Precisely: 3 candidates DUALSIM-FAILed
(functionally broken, correctly rejected), some were duplicates, and 4 passed dualsim but regressed
ADP (none crossed the 0.995 threshold). Baseline remains the submission; a future revisit would
target the unexplored files (tlul_socket_1n, prim_packer_fifo, kmac_app for area) with stronger
proof requirements. Not the immediate next action.

**Billing wording corrected (Codex).** Incognito mode does NOT establish billing ownership; Gemini
keys bill to their linked project/account. Accurate claim: campaigns used the organizer-provided
key through the organizer project "GenAI Chip Hackathon-9207" (Tier 3) via the AI Studio client (no
personal Vertex Express key selected — code-confirmed); billing is *assumed* to remain with the
organizer-controlled project per their provisioning — verify in the project billing dashboard, not
proven by incognito. Also: `max-calls` = proposal-turn budget; manifest `llm_calls` = all successful
calls incl. reflect/repair (explains kmac 10→11, ascon 15→16).

**NVDLA — proceed only after this preflight/policy pass (now done):** absolute emit path, low
concurrency (workers=1, small first k), explicit PROVEN-vs-experimental acceptance, full per-layer
logs. Selection + coverage + path fixes are in; ready when Hari is.

## 2026-07-19 (rev2, after Codex RE-review) — P0 selector integration bug fixed; HOLD kmac Pro retry

Codex's re-review (`NVIDIA_JULY19_FIXES_REREVIEW.md`) caught a real **P0 integration bug** in my
selector fix and it was right. `_canonical_best()` searched `frontier.entries`, but the real
`ParetoFrontier` **evicts** the proven candidate: the invalid `1b5c86d80918` dominates
`b153b877f996` on area+setup+power, so the frontier held only `['1b5c86d80918']` and the selector
returned **None** (would emit a null baseline, not the proven candidate). My 3/3 test missed it
because it used a synthetic frontier that never exercised dominance eviction.

FIXED:
- **`_canonical_best(ip, pool, obj, base_ppa)`** now searches the **full accepted pool**
  (`pool.states.values()`), not the assurance-blind frontier. Validated with a real integration
  test: `ParetoFrontier` evicts the proven candidate (`entries=['1b5c86d80918']`) yet
  `_canonical_best(pool)` recovers `b153b877f996` (PROVEN). `test_selection.py` rewritten → **3/3**
  incl. the real-frontier eviction case. ascon re-emitted (b153b877f996, ADP 0.97918); manifest now
  also records `experimental_best` = 1b5c86d80918 (0.9666, INCONCLUSIVE, NOT canonical).
- **Baseline fallback** (best=None) now emits a COMPLETE manifest (`cid:"baseline"`,
  `best_ppa=baseline_ppa`, `adp_vs_baseline:1.0`) instead of nulls.
- **Rejected ascon manifest** made machine-unambiguously ineligible: `result:"rejected-inequivalent"`,
  `eligible:false`, `rejection_reason`, `targeted_differential:{result:FAIL,mismatches:7/100000}`;
  the old machine manifest preserved as `original_rejected_manifest.json` (forensic). So no
  eligible ADP-0.9667 claim survives anywhere machine-readable.

**KEY DECISION — HOLD the kmac Pro retry.** Every kmac whole-design LEC on record is **ERROR**, and
the new policy requires **PROVEN**, so no candidate can be canonical regardless of model — this is a
verifier-readiness problem, not a model problem. Prerequisites before any kmac retry: (1) a
**no-model whole-design LEC diagnostic** (classify ERROR = tool/setup / unsupported construct /
timeout; preserve the Yosys script+log), (2) an explicit eligibility predicate (e.g. module-level
LEC PROVEN + candidate-aware dualsim as a *labeled* fallback when top LEC is a pre-existing tool
error), and (3) the model-config migration below.

**Corrections (Codex).** (a) ascon was a MODEL error AND a FLOW failure (candidate-blind gate,
limited dualsim sampling, inconclusive-LEC policy, PPA-only frontier) — not "not a flow bug".
(b) Repo state: `HEAD == origin/main` at 2b99406 but the working tree is **not clean** (intended
uncommitted `sync.sh` + these fixes). (c) kmac timing: my model-question cited WNS −1559 ps (the
FLATTEN=0 diagnosis worst-path STA); the baseline report/manifest record −1115.75 ps (baseline
synth STA) — different STA passes; reconcile provenance before a retry. (d) Quota: Tier 3 is
**paid** organizer-project capacity (no personal cost expected, but a finite shared resource) —
"only downside is quota" understated the tradeoffs; formal verification, not model size, is the
safety boundary.

**Model readiness (P1, before any Pro campaign) — NOT yet done:** current client hard-codes
`thinking_budget=8192` (numeric) + `temperature=0.2`/`top_p=0.6`; Google's Gemini-3 guidance says
use `thinking_level` (medium for 3.5-flash, high for 3.1-pro) and default sampling — and installed
`google-genai 1.47.0` has no `thinking_level`. Before a new-model run: pin a supported SDK/Python,
make generation config model-aware, drop the sampling overrides unless A/B-justified, add model/SDK
provenance to manifests, and smoke each model's parser/finish/token metadata.

**DEFERRED (Codex, not blocking canonical correctness):** staged parent-selection + plateau are
still assurance-blind (`frontier.best()`) so rounds 2–3 built on the unproven parent — make
canonical/proven progress drive parent/plateau and log ACCEPT-PROVEN vs ACCEPT-EXPERIMENTAL; harden
the path guard to require the resolved target under NVWORK/submission; preserve per-layer LEC/dualsim
logs+hashes in the ledger; the evaluate.py `layers.get("compile")=="PRE-EXISTING"` dict-vs-string
comparison is always False (dualsim runs anyway — keep, but make the policy explicit + tested).

## 2026-07-19 (rev3, Codex verdict `NVIDIA_JULY19_REREVIEW_FIXES_VERDICT.md`) — P0 CLOSED; last P1 fixed

Codex confirmed the **P0 selector defect is closed** (pool-based `_canonical_best` recovers the
frontier-evicted proven candidate; a separate PROVEN frontier is unnecessary) and the baseline/
rejected manifests are substantially correct. **One P1 remained before commit — now fixed:** a
baseline-only campaign recorded **baseline itself** as `experimental_best`. Extracted
`_experimental_best(ip, ppa_best, best, obj, base_ppa)` (never baseline, never a non-improvement,
never the canonical winner) + regression → `test_selection` now **4/4**; ascon's experimental_best
is still correctly `1b5c86d80918` (a real improving unproven candidate). Per Codex the selector work
is now commit-ready. **Sequence from here:** commit these fixes → **no-model kmac whole-design LEC
diagnostic** (preserve full failure evidence, then design the eligibility predicate from the actual
error — no speculative exception) → **assurance-aware parent/plateau** (blocks NVDLA, not the
selector commit) → **model-config migration** (thinking_level/SDK pin) → bounded Pro kmac only if a
proof path exists. HOLD on kmac Pro stands.

## 2026-07-19 (rev4) — committed 1997ed4; kmac no-model LEC diagnostic complete

Committed + pushed the selector/manifest fixes → **1997ed4**. Then ran the no-model kmac LEC
diagnostic (Codex's gate; evidence in `kmac_lec_diag/`, writeup `NVIDIA_KMAC_LEC_DIAGNOSTIC.md`):
- **Whole-design LEC = pre-existing yosys tool crash.** `verify --ip kmac --baseline --layers lec`
  (pristine-vs-pristine, identical designs) crashes IN the equiv_make pass:
  `ERROR: Assert count_id(wire->name)==0 failed in kernel/rtlil.cc:2961` — a wire-name collision on
  the 60+-module flatten, BEFORE any equivalence check. Candidate-independent + pre-existing → kmac
  can NEVER reach whole-design lec==PROVEN under this flow (fully explains the campaign's uniform
  lec:ERROR).
- **Module-level LEC = PROVEN** on all 3 editable modules (isolated -top flatten, pristine-vs-
  pristine): tlul_socket_1n (8109 $equiv cells), prim_packer_fifo (157), kmac_app (6760) — all
  "Equivalence successfully proven!". So a module-equivalence fallback is *viable*, not hypothetical.
- Proposed eligibility predicate (NOT implemented): whole-design error proven pre-existing + every
  changed module module-level-LEC PROVEN + candidate-aware dualsim + no interface/latency/reset/
  integrity change → assurance "module-equivalence + differential; whole-design LEC pre-existing".
  Needs a per-module LEC harness in verify.py + a richer assurance predicate in _canonical_best.
- **Open (asked Codex):** try a yosys prep workaround (uniquify/rename/equiv_opt/newer yosys) to get
  REAL whole-design PROVEN before building the fallback — cheaper+stronger if it works. Also: make
  the predicate generic (NVDLA may hit the same wall). HOLD on kmac Pro still stands pending Codex.

## 2026-07-20 (rev5) — kmac model probes: Pro & 3.5-Flash; kmac CLOSED as bounded negative

Answered Codex's "is it the model?" with 3 bounded probes on the free organizer key (Tier 3), all
emitted to /tmp scratch (submission/kmac untouched; selector shipped baseline every time).
FINDING 1 — **kmac has NO ADP headroom with ANY model.** Pro (tlul_socket_1n 6c, kmac_app 4c) and
3.5-flash (tlul_socket_1n 6c) all accepted=0, ADP 1.0 — regress/no-change/dup/synth-fail. With the
earlier flash campaign (tlul_cmd_intg_chk broke, prim_subreg_shadow regressed) + dead prim_packer_fifo,
ALL diagnosis-selected kmac files are now attempted incl. the strongest model → **kmac is a bounded
negative; baseline is the submission; stop kmac search.** FINDING 2 — **model matters for CORRECTNESS:
Pro > 3.5-flash > old-flash.** Same file (tlul_socket_1n, 6 cands): Pro 0 broken; 3.5-flash 3 broken
(1 dualsim-fail + 2 synth-fail); old-flash 3 dualsim-fail. So a stronger model avoids the ascon-class
functional breaks — but doesn't create headroom. ROUTING: Pro for hard/correctness-critical;
3.5-flash for breadth (gates catch its ~50% defect rate); retire 3-flash-preview. thinking_budget=8192
worked for both new models (config migration still recommended, not blocking). Wrote
NVIDIA_KMAC_MODEL_PROBE_FINDINGS.md for Codex. YOSYS FIX: doesn't help kmac (no headroom) but is the
right GENERIC investment for NVDLA/hidden — flow-workaround (portable, same 0.63) preferred over
bundling a custom binary; must pass positive+negative controls. NEXT (pending Codex): fix-first yosys
spike + NVDLA no-model preflight (may not hit the same equiv_make wall). HOLD on kmac Pro is now moot
(kmac closed).

## 2026-07-20 (rev6) — CORRECTIONS to rev5 overclaims (per Codex review of the model-probe findings)

Codex reviewed `NVIDIA_KMAC_MODEL_PROBE_FINDINGS.md` (`NVIDIA_KMAC_MODEL_PROBE_REVIEW.md`). It
**approved the operational decision** (kmac closed as a bounded negative, baseline retained, no more
kmac search) but flagged that several rev5 statements are stronger than the evidence. Correcting them
here so they don't bias future work. The decision does NOT change; only the calibration does.

- **RETRACT "kmac has NO ADP headroom with ANY model."** Supported claim: *None of the 16 candidates
  generated in the bounded kmac probes improved on baseline ADP.* That justifies a resource decision
  (kmac operationally closed, baseline canonical), NOT architectural impossibility for all models /
  all transformations / all microarchitectures. New label: **bounded negative result; operationally
  closed; baseline retained.** Reopen only on an explicit trigger (concrete high-impact cone from
  non-model analysis; a working formal path for a materially different transform class; NVDLA +
  submission-hardening done with quota/time to spare; a newer model/flow shown on a matched benchmark
  to raise valid-candidate yield).
- **RETRACT "Pro produced 0 broken candidates."** Correct: *No Pro proposal in these probes was
  rejected by synthesis or the available differential test; equivalence was NOT formally proven, so
  functional correctness is not claimed.* Whole-design LEC never reached a proof (equiv_make crash),
  and there is no candidate-specific module-level proof for these proposals. Ascon is the standing
  counterexample: dualsim-PASS ≠ equivalent. Do NOT say the gates "catch all defects" — they catch
  the failures they exercise. Note: some Pro `kmac_app` candidates changed stateful request-tracking
  / X-sensitive (case-equality) expressions, which can alter 4-state behavior even when sampled
  simulation passes — extra reason not to claim correctness.
- **DOWNGRADE the model ranking to a one-probe pilot signal.** The only clean matched experiment is
  `tlul_socket_1n`, 6 candidates: 0/6 Pro rejected by synth+diff vs 3/6 for 3.5-flash. That is a
  useful early yield signal, NOT a proven/stable ranking across modules/strategies/seeds. The
  old-flash "same file" comparison in rev5 is **wrong** — old flash was measured on *different* files
  (tlul_cmd_intg_chk, prim_subreg_shadow), so it was not a matched A/B. Retire `gemini-3-flash-preview`
  as a superseded preview (stable successor + Google migration guidance), NOT on a conclusive
  head-to-head.
- **FIX call/cost language.** rev5's "~17 free calls" is imprecise. Evidence shows **18 apparent
  successful calls** across the three probes = 16 candidate-generating calls + 2 apparent
  reflector/coordination calls (any API smoke test counts separately). Replace "free" with
  **"organizer-provided key/project, no expected personal charge"** — Tier 3 is paid-project capacity
  with finite shared quota; billing ownership was not independently verified in the artifacts.
- **Provenance gap (for NVDLA):** the candidate ledger does not durably bind each candidate to model
  ID / SDK version / effective gen-config / prompt revision / call-type. Narrative attribution is
  insufficient for a contest audit. Before the NVDLA campaign: one append-only machine-readable run
  manifest per campaign, written as the run happens.
- **Supersede stale earlier-rev LEC wording:** where earlier revs implied whole-design LEC is
  universally candidate-independent or that the module-level fallback is already "viable/complete" —
  correct to: the equiv_make crash is candidate-independent *for kmac's pristine-vs-pristine case*
  (demonstrated), and module-level proof is *demonstrated for pristine modules only*, NOT a complete
  candidate-aware eligibility fallback (needs changed-module discovery, real params/generates, black
  boxes, candidate-specific sources, hierarchical effects, proof logs + labels).
- **Model-interface migration is now a PREREQUISITE for a consequential NVDLA model campaign** (not
  merely "recommended"). Numeric thinking_budget being *accepted* ≠ recommended/comparable config;
  Google guidance recommends supported SDK + `thinking_level` + default sampling for Gemini 3.x. Fine
  for an isolated smoke call; must be done before NVDLA to keep cross-model comparison interpretable.

NEXT (Codex-approved order): (1) this correction [done]; (2) NVDLA **no-model preflight** (no model
calls, no canonical changes — env/repro, design discovery, baseline stability ×2, pristine-vs-pristine
LEC + compare signature to kmac's equiv_make assert, agent-mechanics dry run in scratch, go/no-go);
(3) **in parallel**, a tightly timeboxed whole-design Yosys spike (same-pinned-0.63 prep fixes first —
uniquify/rename/hierarchy/flatten-order/equiv_opt; newer-build only as a diagnostic/internal-proof
path, clearly distinguished from the official scorer); (4) finish model-interface migration +
assurance-aware parent/plateau controls BEFORE the first consequential NVDLA model run. On the
Docker/Apple host, serialize the heaviest Yosys phases (don't run two memory-heavy jobs at once).

## 2026-07-20 (rev7) — NVDLA no-model preflight DONE (Codex §A–§F); wrote NVIDIA_NVDLA_PREFLIGHT_FINDINGS.md

Ran the full preflight, no model calls, no canonical changes (submission/nvdla doesn't even exist).
Disposable workspace in scratch; evidence in `nvdla_lec_diag/`.
- **§A env:** iclad-dev:v1 e258fff6 (Yosys 0.63), ASAP7 NLDM, contest 7623b53, submission 1997ed4.
  Host 48 GB but **Docker VM caps ~7.65 GB** — that's the real ceiling (both heavy jobs fit under it).
- **§B discovery:** top `NV_nvdla` = 5 partitions (a/c/m×2/o/p), 320 modules, 323 sources,
  `hierarchy -check` PASS, **RAMs blackboxed** (nvdla_ram_blackbox.v), clocks 30/60 ns, FLATTEN=0.
- **§C baseline stability = DETERMINISTIC, tol 0.0:** ledger + 2 fresh clean runs identical to the
  digit (cells 952591, ff 42457, area 78346.607, WNS −5788.40 ps, hold +42.40, power 1.04e-02).
  Wall 598 s synth+STA. **WNS −5788 ps on a 30 ns clock = real timing headroom** (unlike kmac).
- **§D whole-design LEC = `Equivalence successfully proven!`** — 381,209 $equiv cells (35,523 groups)
  all proven, 758 s, peak 1478 MB, RC=0. **NVDLA does NOT hit kmac's equiv_make assert.** ⇒ the
  equiv_make crash is **kmac-specific, not a generic large-design wall**; the whole-design assurance
  gate is AVAILABLE for NVDLA; the **Yosys spike stays kmac-only and timeboxed** (not blocking NVDLA).
  Caveat (ascon lesson): this proves the flow (identical designs prove, no crash), NOT yet a
  candidate-aware proof — a real edited candidate hasn't been LEC'd; that's a named prereq.
- **§E agent mechanics:** tests pass (selection 4/4, emit 2/2, model-iface 13/13, cold-start 6/6);
  path guard present; baseline fallback + rejected-non-canonical + full-pool selector all hold; no
  canonical mutation. **Surfaced 2 NVDLA discovery gaps + confirmed 1 known gap:**
  (1) `discover.py` sets `rtl_dir = NVDLA/vmod/vlibs` (the CELL-LIBRARY dir, not the functional RTL
  under outdir/.../nvdla/) → a campaign would edit the wrong files → **NVDLA needs an explicit
  IPSpec**; (2) discovered clocks 10/14 ns vs real 30/60 ns (harmless for synth PPA — synth reads the
  SDC — but wrong for diagnosis); (3) **parent/plateau still assurance-blind** (controller.py:273-286,
  PPA-only) — unproven improver can seed later rounds; must fix before iterative model rounds.
- **§F verdict:** **GO** for NVDLA verification/infra work (both hard unknowns — baseline repro & LEC
  at scale — cleared). **NO-GO for a model campaign** until 4 prereqs land: (1) explicit NVDLA IPSpec
  + edit-scope assertion; (2) NVDLA functional-gate + candidate-aware LEC validation on a no-op edit;
  (3) model-interface migration + per-campaign run manifest; (4) assurance-aware parent/plateau.
Next (user's call): author NVDLA IPSpec → validate gate/candidate-LEC → model-config migration →
parent/plateau patch → staged campaign. Yosys spike deprioritized for NVDLA (LEC works).

## 2026-07-20 (rev8) — CORRECTIONS to rev7 (per Codex review `NVIDIA_NVDLA_PREFLIGHT_REVIEW.md`)

Codex approved the core result (NVDLA custom top-level LEC completes ⇒ kmac's `equiv_make` crash is
NOT an NVDLA-scale blocker; keep the Yosys spike PARKED for kmac/hidden-trigger only) and the NO-GO,
but flagged rev7 overstatements + 4 new P0s. Corrections (decision unchanged; calibration + expanded
gate):
- **"timing headroom" was WRONG.** WNS −5788 ps is a reproducible **setup violation** (~35.8 ns
  critical path vs 30 ns). Worse, the worst paths are **reset-synchronizer/distribution** paths the
  SDC comments intend to false-path — likely a constraint-application artifact, NOT a datapath
  opportunity. Correct: *reproducible measured setup violation; valid datapath opportunity NOT shown;
  target validity pends a constraint-intent audit.* Do NOT optimize this WNS (risks reset/CDC edits).
- **Baseline area cache is WRONG (P0 bug).** `NVDLA_baseline.json area=0.75816` is a **submodule**
  area: `harness/measure.sh:43` greps the FIRST `"Chip area for module"` and misses the hierarchical
  `"Chip area for top module" = 78346.606860`. rev7's determinism table mislabeled 78346.607 as "the
  ledger value" — it's the report value, not the cached one. **Blast radius = NVDLA ONLY** — every
  other IP sets `FLATTEN=1` (collapses to one top module, so grep -m1 hits the top): async_fifo/
  sha512/ascon/aes/kmac/prim ledger areas are all correct top-scale values; **banked sha512 0.7266 /
  ascon 0.97918 are UNAFFECTED.** Fix (prereq): parse top-module area explicitly, fail closed if
  absent/ambiguous, add a hierarchical-report fixture, refresh the NVDLA cache, verify the returned
  PPA object (not just reports), store raw metric source-lines + hashes.
- **LEC diagnostic ≠ agent LEC (P0).** rev7 said the .ys "mirrors verify.py::lec exactly" — FALSE.
  The diagnostic uses per-file `read_verilog -defer` + 4 defines + 22 includes; `_read_stanza` uses a
  single `read_verilog -sv <files>` with none → agent LEC would FAIL on NVDLA as-is. Result proves
  **flow feasibility, not agent readiness.** Prereq: move the recipe into the real verification path;
  golden=immutable pristine, gate=regenerated candidate, distinct hashes; run pristine + known-
  equivalent + **mandatory known-INEQUIVALENT negative control** (a no-op test alone is insufficient);
  raise/scale the 900 s timeout (baseline LEC already 758 s → 142 s margin); timeout/error = ineligible.
- **`outdir`-only edit target is NOT the fix (P0).** `vmod/nvdla` is the ePerl source-of-truth;
  `outdir/nv_small/vmod/nvdla` is generated by `tmake -build vmod`; the gate (`run_varilator_test.sh`)
  runs `tmake -clean -build vmod` FIRST → an `outdir`-only candidate is overwritten / candidate-blind
  (OpenTitan dual-representation again). Needs: editable=`vmod/nvdla`, explicit source→generated map,
  regenerate-in-workspace-after-overlay-before-every-consumer, candidate-survival tripwire, gate-does-
  not-erase-candidate guard, manifest emits the source delta, clean-build reproduces the generated RTL.
- **Also (P1):** NVDLA `proxy: null` (cheap-gate cascade not functioning for NVDLA — same read-config
  gap); the real acceptance predicate is unspecified (controller needs dualsim PASS to pool-admit,
  selector needs LEC PROVEN — NVDLA dualsim untested/maybe impractical; define one predicate and align
  pool-admit/parent/plateau/canonical/manifest); baseline is "metric-repeatable in this env", NOT
  "fully deterministic / any delta trustworthy" (keep the 1 ps / 0.5% epsilons, not tol=0).
- **Prereq list SUPERSEDED:** the rev7 4-item list → Codex's **10-item go/no-go gate** (source
  contract; top-module metric+cache; timing/constraint intent + safe cone; NVDLA compile/proxy;
  candidate-aware gate w/o overwrite; candidate-aware LEC + pos/neg controls; full eligibility
  predicate; assurance-aware parent/plateau; model SDK/config + provenance; explicit quota/compute/
  wall/disk/stop budget). Codex 6-phase order: (1) correct the record [this rev]; (2) source contract;
  (3) metric+timing repair + pick ONE safe leaf; (4) candidate-aware LEC+gate w/ controls + predicate;
  (5) parent/plateau + model migration (parallel OK, hard gate before any model call); (6) first
  bounded campaign = ONE leaf unit / ONE file / 1 round / 3 proposals (≤4–6 calls) / 1 worker / no
  clock-reset-CDC-RAM-vlibs-top-interface edits / no canonical emit / stop on any control deviation.
  Model migration may run in parallel but source-regen + metrics + verification come FIRST.
- **Provenance nits:** record the NESTED NVIDIA repo commit (`08cc17e`) not just outer contest HEAD;
  use full image digest `sha256:e258fff6…` + arch `arm64`; "six partition instances (5 types; m ×2)".

## 2026-07-20 (rev9) — P0-A parser fix + NVDLA Phase 2 source contract DONE

**Parser fix (P0-A):** `harness/measure.sh` area extractor now takes the TOP-module area — prefer
`"Chip area for top module"` (STAT, hierarchical/full-precision) → `"Total Area"` (FINAL, universal
top total) → by-name `"Chip area for module '\<TOP>'"` → **fail closed** (empty, so evaluate.py flags
a missing metric rather than trusting a wrong one). Was `grep -m1 "Chip area for module"` = first line
= a SUBMODULE for hierarchical designs. New `harness/test_measure_area.sh` = **4/4** (hierarchical→top,
flat→Total Area, opentitan→by-name, fail-closed). Validated on real reports: NVDLA→78346.606860 (was
0.75816), sha512→3903.649. **Corrected `ledger/NVDLA_baseline.json` area 0.75816 → 78346.60686**
(other NVDLA metrics were already correct). Confirmed **blast radius = NVDLA only** for the CACHE, but
the parser was also *fragile* for OpenTitan IPs (ascon/aes stats list submodules first and can reorder
between baseline/candidate) — the fix hardens all of them. **Banked submission manifests re-verified
top-scale + internally consistent (ascon 1789/1801, aes 10100/10139, sha512 3984/3968, kmac 13353,
prim 70/66, async_fifo 120/121) → submission UNAFFECTED.**

**Phase 2 source contract (empirically proven, `NVIDIA_NVDLA_PHASE2_SOURCE_CONTRACT.md`):**
`vmod/nvdla/**` (266 .v + 9 .h, #include templates) is the EDITABLE source-of-truth; `tmake -clean
-build vmod` (Perl, **24 s**) expands #includes → `outdir/nv_small/vmod/nvdla/**` (same relative
paths) which synth+LEC consume; the gate rebuilds vmod→outdir every run. **Candidate-survival tests
in iclad-dev:v1: (1) a vmod-source marker PROPAGATES into regenerated outdir (RC=0); (2) an
outdir-only marker is WIPED by the gate's tmake (count 0) while the vmod marker SURVIVES (count 1).**
⇒ edit `vmod/nvdla` (never `outdir`). Workspace must copy the FULL NVDLA tree (~743 MB) — tmake needs
tools/vmod/spec/tree.make/Makefile; a minimal outdir+syn copy FAILS (spec/defs/project.h). Pipeline:
overlay vmod → tmake regenerate → proxy/synth/LEC/gate read regenerated outdir → tripwire asserts the
candidate marker/hash survives + golden≠gate generated hashes. Per-candidate compute ≈ 24 s regen +
~600 s synth + ~758 s LEC + trace-gate. NEXT: Phase 3 (timing/constraint intent audit — reset
false-path — + proxy fix + pick ONE safe leaf using corrected area) then Phase 4.

## 2026-07-20 (rev10) — kmac LEC control matrix: the equiv_make assert is OUR recipe (fixable), not a yosys/kmac limit

Motivated by the NVDLA whole-design LEC PROVING with a proper recipe: re-tested whether kmac's
whole-design `equiv_make` assert (`count_id(wire->name)==0`, rtlil.cc:2961) is really an unfixable
tool bug (as `NVIDIA_KMAC_LEC_DIAGNOSTIC.md` §2.1 claimed) or **our LEC recipe**. Control matrix
(`kmac_lec_diag/CONTROL_MATRIX_RESULTS.txt`, evidence + .ys saved), all in iclad-dev:v1, 65 generated
.v, top=kmac:
- v0 baseline (proc/memory/async2sync/flatten/opt_clean → equiv_make): **ASSERT** (reproduced).
- v1 `uniquify`-before-flatten: ASSERT. v2 no-flatten (hierarchical): ASSERT. → flatten/uniquify are
  NOT the fix; the collision is inherent to combining two kmac copies in equiv_make.
- v3 add **`rename -hide`** (hide internal public wires) before stash: **assert CLEARED — equiv_make
  PASSES.** Then whole-design equiv **OOMs in equiv_induct (~490s) at the 7.65 GB Docker-VM cap** (a
  RESOURCE wall, not a tool bug; may clear on a bigger machine).
- module-level (hierarchy -top <module>) + rename -hide: pristine → **PROVEN** (231 MB, fast);
  **negative control** (mutated tlul_socket_1n: `hold_all_requests` `!=`→`==`) → **NON-PROVEN, 498
  unproven $equiv** (66s). So the module-level gate **catches inequivalence** — real gate, not a
  rubber stamp.
**CONCLUSION (corrects rev-earlier + `NVIDIA_KMAC_LEC_DIAGNOSTIC.md`): the equiv_make assert is
OUR-recipe-fixable via `rename -hide`, NOT a "pre-existing unfixable yosys bug", and "kmac can NEVER
reach whole-design PROVEN" was WRONG.** kmac IS formally checkable (module-level, both-way validated).
The kmac LEC blocker is REMOVED; kmac stays operationally closed only on HEADROOM grounds (no
ADP-improving candidate found), not on LEC. **Fix for `verify.py::lec`:** add `rename -hide` to the
read stanza (generic — also unblocks NVDLA candidate LEC), and for IPs whose whole-design equiv OOMs,
run module-level LEC on the CHANGED module (proves + fits memory + catches errors). This is exactly
the NVDLA Phase-4 assurance work — one fix serves kmac + NVDLA. NOTE: this does NOT reopen kmac by
itself (headroom unchanged), but it retires the "LEC is our code" concern the user raised.

## 2026-07-20 (rev11) — RETRACTION: `rename -hide` is a FALSE FIX (rev10 was wrong); module-level LEC (no hide) is the valid route

Tried to fold `rename -hide` into `verify.py::_read_stanza` (LEC path) per rev10. It REGRESSED every
working IP: **sha512 baseline LEC PROVEN → INCONCLUSIVE (33 unproven); async_fifo → INCONCLUSIVE
(12)**. Reverted immediately. Root cause + proof it's a false fix (`kmac_lec_diag/
CONTROL_MATRIX_RESULTS.txt` rewritten):
- module-level **pristine** (identical) + rename -hide → **502 unproven** (can't even prove identical
  designs); module-level **mutated** + rename -hide → 498 unproven. Indistinguishable → rename -hide
  hides the internal signals `equiv_induct` needs, so it proves NOTHING. It clears the assert but is
  worthless — exactly the "stops the assert but proves nothing" trap.
- My rev10 negative control (498 unproven on the mutated module) was therefore INVALID — that number
  was the rename -hide breakage, not the mutation.
- **VALID control matrix (module-level, NO rename -hide):** pristine → **PROVEN (0 unproven)**;
  mutated (tlul_socket_1n `hold_all_requests` `!=`→`==`) → **NON-PROVEN, exactly 1 unproven $equiv**
  (`neg_modlevel_nohide.log`). So module-level LEC proves identical designs AND precisely detects the
  bug. This is the real, both-way-validated gate.
**CORRECTED CONCLUSION (supersedes rev10):** the whole-design kmac `equiv_make` assert has **NO valid
workaround found** in pinned Yosys 0.63 (uniquify/no-flatten don't clear it; rename -hide clears it
but false-proves). Whole-design kmac LEC stays BLOCKED. **The valid route is a MODULE-LEVEL LEC
FALLBACK** (prove each CHANGED module via `hierarchy -top <module>`, no rename -hide) — proves + catches
inequivalence + fits memory. That is the correct `verify.py::lec` enhancement (Phase-4 work), NOT
rename -hide. `verify.py` is REVERTED/unchanged; agent tests still valid. kmac still closed on headroom
regardless. LESSON: a prep pass that clears an assert MUST be validated with a positive control
(pristine must still PROVE) before trusting any negative — I skipped that in rev10 and it was wrong.

## 2026-07-21 (rev12) — acting on Codex postpreflight review: closed P0-1/P0-2/P0-3 (P0-4 = design, remains)

Codex `NVIDIA_POSTPREFLIGHT_WORK_REVIEW.md` = conditional GO + 4 P0s. Closed three:
- **P0-1 measurement FAIL-CLOSED end-to-end.** New `harness/_metrics.sh` (single sourceable
  production helpers: `extract_top_area`, `is_number`, `is_pos_number`). `measure.sh` sources it and
  **exits 3** if any mandatory metric (area/cells/ff/power > 0; setup/hold finite) is missing/`?`.
  `evaluate.measure()` now checks the return code + requires finite metrics → returns **None** (never a
  partial dict) on any failure; `baseline()` **raises rather than caching** an invalid record (won't
  overwrite a good cache with nulls) + writes `schema="top-area-v2"` + `image` provenance. Tests:
  `harness/test_measure_area.sh` **16/16** (now exercises the REAL sourced helper, not a copy — Codex
  P1), new `agent/test_measure_failclosed.py` **13/13** (real `measure()`: rc≠0/`?`/nan/inf/neg/0/empty
  all → None). Existing suites still green (selection 4/4, emit 2/2, model-iface 13/13, **cold-start
  6/6** incl. a real baseline through the new path).
- **P0-2 kmac control matrix PRESERVED** (`kmac_lec_diag/preserved/`): reran module-level pos/neg with
  **`equiv_status -assert`** (process-level signal, not a bare print). **pos_ctrl (pristine) rc=0
  "Equivalence successfully proven!"; neg_ctrl (mutated tlul_socket_1n !=->==) rc=1 "Found 1 unproven
  $equiv" + assert ERROR;** noninterference **sha512 baseline LEC = PROVEN** (reverted recipe). Bundle:
  ENV (image sha256:e258fff6, arm64), mutation patch, source hashes, both .ys, both raw logs, RESULTS,
  README. Fixes the missing-log gap Codex flagged.
- **P0-3 NVDLA source-contract EVIDENCE** (`nvdla_phase2_evidence/EVIDENCE.txt` + tmake logs): fresh
  tree, full hash chain + a **logic-bearing structural control** (appended `& 1'b1`, LEC-equivalent).
  Proven with sha256: vmod edit → generated hash 7d0f8b65→60d80cfe (`& 1'b1` visible in generated RTL
  line 105, not just a comment); outdir-only tamper 5895c05f → after `tmake` back to 60d80cfe (wiped,
  count 0) while the vmod edit survives (count 1); regen deterministic (after-gate == candidate hash).
  All tmake rc=0.
STILL OPEN — **P0-4: explicit NVDLA source/generated/regeneration ABSTRACTION** (editable_sources/
generated_sources/regenerate() hook/reverse-map/full-tree copy/tripwire — NOT just an IPSpec; the
current `Workspace.overlay`/`candidate_from_dir` can't express it). Plus Codex's other preflight
blockers (timing/reset false-path audit, NVDLA proxy null, assurance-aware parent/plateau, model-iface
migration + provenance, campaign budget) and the P1s (cache schema/provenance done partially; one-leaf
`.v` scope; whole-design LEC timeout → max(1800, 2×pristine); curated sync file-list). verify.py area
path + baseline now schema-versioned. Repo submission still 1997ed4 untouched; agent working-tree
changes: measure.sh, _metrics.sh, test_measure_area.sh, test_measure_failclosed.py, evaluate.py,
NVDLA_baseline.json.

## 2026-07-22 (rev13) — P0-4: Codex-revised design (rev2) + vertical slice implemented, 37/37 + all suites green

Codex design review (`NVIDIA_NVDLA_P04_DESIGN_REVIEW.md`) = architecture GO, revise-before-
implementing. Actions:
- **Design rev2** (`NVIDIA_NVDLA_P04_DESIGN_REV2_FOR_REVIEW.md`, supersedes rev1 — banner added):
  adopts ALL corrections — immutable `CampaignScope` (two-layer overlay validation), candidate-state
  invariant (pool/parents/prompt/emit = editable sources ONLY), corrected cheap-first pipeline with
  **H5 (post-gate) as the canonical effective input** (H5==H4 required), corrected fingerprint
  definition (323 = 321 outdir + NV_DW_lsd.v + nvdla_ram_blackbox.v; .vh included; 3 manifests +
  root hash), golden at workspace-root `.golden/NVDLA` (7 Codex conditions), gate = runtime
  evidence (run_gate.sh `|| true` rc-swallow to be fixed), **eligibility decision: NVDLA v1 =
  candidate-aware gate PASS + whole-design LEC PROVEN; dualsim diagnostic-only until separately
  validated**, AES/prim/kmac corrected to Sv2vContract, discovery capability FULL/BASELINE_ONLY/
  UNSUPPORTED, expanded touchpoints (pool/diagnose/sta_feedback/CLI/gate/emitter), 20-case sandbox
  + host test plan. §12 addendum (flagged external, from vibeic/vibe-ic review): LEC vacuous-PROVEN
  guard (success line + total $equiv>0 + counts in ledger + plausibility band), equiv_induct -seq
  4/16/64 escalation, INCONCLUSIVE sub-classification, provenance JSONL schema.
- **Vertical slice implemented** (Codex checkpoint 1 scope; NO consumer migration yet):
  `ppa/contract.py` (SourceContract + Direct/Sv2v/Tmake, CampaignScope, DesignInputs w/ per-tool
  yosys adapter, manifest/root-hash fingerprints, materialization classification §6.3,
  check_gate_stability H5==H4, validate_candidate two-layer + symlink-escape/canonical-path,
  get_contract resolution — contract imports config, never the reverse; regenerate takes an
  injected runner, no docker assumption). `IPSpec.contract: str = ""` (one field). `workspace.py`
  overlay delegates validation to contract+scope (direct/sv2v semantics preserved verbatim).
- **Tests: `test_contract.py` 37/37 PASS** on a fake-tmake tree mirroring the real layout
  (determinism ×2, golden survives -clean, include-leak guard, digest sensitivity, outdir/.h/
  scope/symlink rejections, no-effective-change vs proceed vs collateral-drift vs flow-error,
  H5!=H4 reject, editable-only seeding, sv2v both modes, family resolution). Regressions all
  green: selection 4/4, emit 2/2, **model-iface 13/13** (fixed the env-sensitive "missing key"
  test — now pops all candidate key names), fail-closed 13/13, area 16/16. NOTE: this sandbox has
  no Docker — cold-start 6/6 + host sentinels still pending on the macOS host.
- OPEN (host, before strict collateral-drift enforcement + campaign): H-1 two-run full
  generated-manifest determinism, H-2 evidence fixups (relative patch, full digest), H-3 second
  pristine LEC wall measurement. Next: Codex code review of the slice, then consumer migration
  (§11 touchpoints).

## 2026-07-22 (rev14) — Rev2 review: conditional GO for checkpoint-1; Rev2.1 addendum written; slice aligned, 49/49

Codex `NVIDIA_NVDLA_P04_DESIGN_REV2_REVIEW.md`: rev2 = "implementable design with a bounded
correction list"; GO conditionally for the vertical slice; NO-GO unchanged for campaign/emission.
Notable CORRECTION accepted: my §12.1 zero-cell claim was wrong — standard yosys `equiv_status`
does NOT print the success line for a 0-cell miter (it reports no cells found); the defensive
count-binding parser stays, with corrected rationale (Rev2.1 §A.1). Induction -seq escalation
DEFERRED from v1 (weak-induction semantics; pinned recipe = equiv_simple -short + equiv_induct
-seq 4); induction counterexamples classed UNCONFIRMED until reset-reachable (§A.3).
- Wrote `NVIDIA_NVDLA_P04_DESIGN_REV21_ADDENDUM.md` resolving all §4 P0s + §5 P1s: exhaustive
  15-condition eligibility predicate (one policy object), evaluation ID includes
  design_inputs_manifest_digest, pinned LEC semantic template w/ 5 substitutions, gate CLEAN
  REBUILD from H5 + stale-binary negative control, portable copy strategy, 4 path classes,
  mechanical manifest universe (.v+.vh, membership counts), worker authority, kw-only scope,
  fail-closed registry, CONTRACT_VALIDATION_PENDING until host H-1, test 19/20 splits, count
  bands = anomaly only, provenance schema strengthened.
- Slice code aligned (contract.py/workspace.py/test_contract.py): kw-only CampaignScope w/
  construction validation + canonical scope_id; effective_workers(min of requested/contract-cap/
  global); TmakeContract.worker_cap()=1; unknown contract key → structured ContractError;
  DesignInputs side/absolute-path guards; portable `_clone_tree` (darwin -Rc → GNU --reflink=auto
  → copytree) wired into Workspace.create, method recorded for provenance.
- **test_contract.py 49/49** (12 new checks incl. membership-change flow-error, non-outdir-input
  digest sensitivity, statelessness across workspaces, Linux copy fallback). Regressions green:
  4/4, 2/2, 13/13, 13/13, 16/16. Slice handoff updated (`NVIDIA_P04_SLICE_FOR_REVIEW.md` UPDATE 2)
  with the invariant→implementation→test map per review §8.4. Submission repo untouched @1997ed4.
Next: Codex checkpoint-1 CODE review of the slice; then consumer migration (§11); host H-1..H-3.

## 2026-07-22 (rev15) — Rev2.1 ACCEPTED by Codex; checkpoint-1 GO; §H (Rev2.1a) frozen + slice at 59/59

`NVIDIA_NVDLA_P04_DESIGN_REV21_ADDENDUM_REVIEW.md`: addendum accepted as governing design; no
further architectural revision; 3 normative clarifications → appended as §H to the addendum:
H.1 versioned LEC recipes (nvdla-lec-diag-v1 retained/historical vs nvdla-lec-contract-v2 =
+explicit `-seq 4` +`equiv_status -assert`, controls required before eligibility, template guard
targets v2), H.2 proof result algebra (verdict+reason; timeout et al = INCONCLUSIVE reasons;
only PROVEN eligible), H.3 checkpoint-1 vs migration test ownership (deferred ≠ waived),
H.4 = review §4 items (mechanical .vh include universe, validation-profile DIGEST not boolean,
ephemeral vs retained logs, copy INDEPENDENCE test + hardlink rejection, structural gate phases
CLEAN→…→PARSE_RESULTS, 15-condition predicate as named per-condition evidence).
Slice coded for the in-scope pieces: ProofResult algebra w/ pair validation, recipe-ID constants,
ValidationProfile + validation_state() (tmake PENDING by default; direct/sv2v VALIDATED).
**test_contract.py 59/59**; regressions 4/4·2/2·13/13·13/13·16/16. Model campaign: NO-GO
(unchanged). Next: hand the slice package to Codex for checkpoint-1 CODE review; then consumer
migration; host H-1..H-3 unchanged.

## 2026-07-22 (rev16) — checkpoint-1b: all 12 Codex code-review corrections implemented; 94/94 + 18/18 real-material

Codex `NVIDIA_P04_SLICE_CODE_REVIEW.md` held checkpoint-1: decisive finding = TmakeContract
conflated the mapping root (outdir/nv_small/vmod/nvdla) with the COMPLETE generated root
(outdir/nv_small/vmod) → real tree saw only 268/323 sources, 1/22 -I, 0/4 .vh. All verified
against the tree (4 -D, 22 -I, 323 = 266+55+2, 528 .v + 4 .vh = 532). Checkpoint-1b patch:
- contract.py REWRITTEN: explicit `TmakeLayout` (complete generated_root ≠ mapping_root; declared
  filelist required); strict `filelist_model()` (exact order, ../..//. resolution, fail-closed on
  missing/dup/escape — no silent .exists() filtering); complete-root fingerprints (fail-closed on
  missing/empty); mechanical `.vh` include_universe; symmetric golden/candidate `design_inputs`
  from ONE model (side digests cover every source+include; both non-outdir inputs bound);
  snapshot_golden = FULL golden universe manifest, verify_golden = exact membership; scope
  authority (requires_scope for tmake, scope.ip check, canonical-stored targets, overlay override
  REMOVED, no asserts); ProofResult PROVEN unconstructible without rc0/total>0/proven==total/
  unproven0/v2-recipe; ValidationProfile full fields + VALIDATED only on bound-digest match;
  tree_manifest/manifest_root/clone fail closed on symlinks/dups/escapes; H1/H2-aware
  classification (derived edits; H1==H2 + generated change = collateral-drift; partial closure =
  flow-error); real Sv2v forward/reverse mappings (both modes); path_classes() 4-class API;
  full-sha256 IDs; Python >=3.10 import guard (host 3.9.6 → structured error; use python3.12).
  Documented amendment per review §3.3 opt-2: requested_workers = provenance-only, out of scope_id.
- config.py: import-time repo assert → require_repo() at execution boundaries (workspace/docker).
- **Tests: test_contract.py 94/94** (real-topology fixture: vlibs+include+syn-dir non-outdir
  inputs, filelist with -I./traversal entries) + **test_contract_real.py 18/18** (Codex's exact
  323/266/55/2/22/4/4/532 characterization vs the real contest tree, read-only, no Docker).
  Regressions 4/4·2/2·13/13·13/13·16/16. Handoff UPDATE 4; COPY_TO_CODEX.md refreshed for the
  checkpoint-1b re-review. Submission repo untouched @1997ed4. Campaign NO-GO unchanged.

## 2026-07-22 (rev17) — checkpoint-1c: all 10 re-review corrections + 7 adversarial regressions; 111/111 + 18/18 + charact 5/5

Codex re-review (`NVIDIA_P04_SLICE_CODE_REREVIEW.md`): HOLD w/ focused 1c list; requested_workers
amendment accepted-in-principle. All closed:
- Shared `_assert_unaliased` component-walk validator (candidate/filelist/manifest/golden) —
  internal-symlink redirection into immutable/out-of-scope files now impossible (ADV-1/1b tests).
- Validation binding contract-OWNED: caller digest param deleted; TmakeContract carries
  bound_validation_digest from the registry (None until H-1 ⇒ PENDING); evidence_root required.
- ProofResult.lec_eligible REMOVED (diagnostic record only; policy object owns eligibility).
- `check_scope_compat` shared everywhere; classifier: complete scoped H1/H2 membership,
  max_changed_files, hash-format checks, drift label gated on VALIDATED determinism (PENDING ⇒
  flow-error "campaign must be refused").
- `validate_manifest` for deserialized evidence; parent-symlink rejection in tree_manifest;
  verify_golden reconstructs via followlinks=False walk (golden→candidate alias fails) + size.
- Strict filelist: dup defines/-I/empty tokens rejected; include-token ambiguity table (two
  physical files for one token ⇒ error). Real tree unchanged: 323/266/55/2/22/4/4/532.
- TMAKE_LAYOUTS explicit registry (unregistered tmake fails closed); TmakeLayout field
  validation; real test declares the NVDLA layout as literals + independent order re-parse +
  PREREQ-MISSING exit 3.
- _clone_tree rejects source-hardlink aliases; _validate_copy checks required roots post-clone;
  effective_workers fails closed on invalid caps; docker_run calls require_repo(); DesignInputs
  dup-roots/defines/top guards; 5th explicit `golden` path class.
- Addendum **H.5** (normative): semantic vs execution limits; worker counts provenance-only,
  persisted, result-neutral.
- NEW `test_workspace_charact.py` (permanent Direct/Sv2v characterizations vs real tree): 5/5 in
  sandbox; sv2v source-edit leg PREREQ-gated (host sv2v) — run on macOS host for full green.
**Tests: contract 111/111 · real 18/18 · charact 5/5(+prereq) · regressions 4/4·2/2·13/13·13/13·
16/16.** COPY_TO_CODEX refreshed (reply → NVIDIA_P04_SLICE_CODE_REREVIEW2.md). Submission repo
untouched @1997ed4. Host H-1..H-3 + checkpoint-2 open; campaign NO-GO.

## 2026-07-22 (rev18) — checkpoint-1d: 4 P0s + P1s closed; exact patch supplied; 129/129

Codex re-review2 (`NVIDIA_P04_SLICE_CODE_REREVIEW2.md`): HOLD w/ 4 P0s. §H.5 ACCEPTED; macOS
charact 7/7 (incl. host sv2v). Notable: default macOS core suite crashed in _clone_tree
(/var vs /private/var — lexical child vs resolved root). All fixed:
- _clone_tree: ONE path domain (p.relative_to(dst), lexical-vs-lexical; resolved only vs
  resolved) + internal-destination-hardlink rejection (cp -a can preserve pairs); regression
  clones through a symlink-aliased ancestor. Codex asked to re-run default macOS suite w/o
  TMPDIR override.
- Validation authority now immutable: frozen TmakeRegistration(layout, bound_digest);
  TMAKE_REGISTRY rejects duplicate/late registration (test-only _reset); bound_validation_digest
  = read-only property (public assignment raises AttributeError); classifier's raw
  validation_state text param DELETED — takes ValidationProfile|None and derives via
  contract.validation_state(); unbound contract provably cannot reach the drift branch.
- Golden root path _assert_unaliased before snapshot writes AND verify (symlink at .golden /
  .golden/<root> / alias-into-candidate snapshot-refusal regressions).
- Filelist validated unaliased BEFORE is_file/read (identical-bytes external symlink rejected).
- _validate_copy: unaliased + real-type required roots (fake tree gained spec/rams/tree.make/
  Makefile to exercise it); TmakeLayout containment (filelist_base/generator_cwd/filelist);
  FilelistModel self-validating; manifest '.'-rel rejected.
- **Exact 1c→1d patch** (632 lines, 4 files) at nvidia_work/agent/P04_CHECKPOINT_1D.patch
  (1c snapshot taken pre-edit) — closes the §5.6 diff-evidence gap.
Tests: contract **129/129** · real 18/18 · charact 5/5(+sv2v prereq-gated; host re-run
requested) · regressions all green · no opentitan hardlink false-positives. COPY_TO_CODEX
refreshed (reply → NVIDIA_P04_SLICE_CODE_REREVIEW3.md). Submission repo untouched @1997ed4;
campaign NO-GO unchanged.

## 2026-07-22 (rev19) — checkpoint-1e: validation authority SEALED + invariant-based hardlink evidence; 136/136

Codex re-review3: HOLD on exactly 2 items (3 of 4 prior P0s clean; macOS default suite 128/129 —
the hardlink test wrongly demanded rejection when APFS safely de-links; authority still mutable
via _bound_validation_digest + direct TMAKE_REGISTRY dict replacement). Fixed:
- Registry private (_TMAKE_REGISTRY) + read-only MappingProxyType public view (assignment raises
  through the container); TmakeContract retains ONLY the frozen TmakeRegistration — layout +
  bound digest are derived properties (no writable scalar); sealed __setattr__ post-construction
  (private backing assignment raises, state stays PENDING); constructor bypass REMOVED (registry
  = the sole production authority; tests use register_tmake + test-only reset); frozen-retention
  verified (private-dict mutation cannot affect an existing contract); malformed digests rejected
  at registration; legacy string profile → structured ContractError; stale 1b header fixed.
- _scan_dest_aliases factored out of _clone_tree: deterministic unit (dst tree WITH a hardlink
  pair must be rejected) + invariant-based end-to-end (source pair ⇒ rejection OR verified
  independent isolated destination — APFS de-link passes, cp -a preservation rejected).
**Tests: contract 136/136 · real 18/18 (production-path resolution) · charact 5/5(+sv2v prereq)
· regressions 4/4·2/2·13/13·13/13·16/16.** Exact 1d→1e patch (317 lines, 4 files) at
nvidia_work/agent/P04_CHECKPOINT_1E.patch. COPY_TO_CODEX refreshed (reply →
NVIDIA_P04_SLICE_CODE_REREVIEW4.md); host re-runs requested (default no-TMPDIR core suite
expected green). Submission repo untouched @1997ed4; H-1..H-3/checkpoint-2/campaign unchanged.

## 2026-07-22 (rev20) — checkpoint-1f: deletion sealed (the sole 1e blocker); 142/142

Codex re-review4: HOLD on ONE item — inherited permissive __delattr__ let `del contract._sealed`
re-enable assignment (unbound → VALIDATED). Hardlink correction ACCEPTED; all host suites had
passed (core 136/136 default no-TMPDIR, real 18/18, charact 7/7, legacy green). Fixed:
- TmakeContract.__delattr__ mirrors the __setattr__ seal (any attr deletion raises post-
  construction; contract stays usable + PENDING). Six required deletion regressions added.
- §5.1: shared _is_sha256() exact-fullmatch + typed helper across ALL evidence validators
  (trailing-newline 64-hex rejected; non-string digest → ContractError not TypeError).
- §5.2: symmetric end-to-end hardlink isolation (mutate db in a fresh copy; da + both sources
  proven unchanged).
**Tests: contract 142/142 · real 18/18 · charact 5/5(+sv2v prereq) · regressions green.** Exact
1e→1f patch (158 lines, 2 files) at nvidia_work/agent/P04_CHECKPOINT_1F.patch. COPY_TO_CODEX
refreshed (reply → NVIDIA_P04_SLICE_CODE_REREVIEW5.md); host re-runs requested. Submission repo
untouched @1997ed4; H-1..H-3/checkpoint-2/campaign unchanged NO-GO.

## 2026-07-22 (rev21) — ✅ P0-4 CHECKPOINT 1 ACCEPTED by Codex; §11 consumer migration GO

`NVIDIA_P04_SLICE_CODE_REREVIEW5.md`: **ACCEPTED / GO** after 6 review cycles (design rev1→rev2→
rev2.1→§H; code 1b→1c→1d→1e→1f). Final host matrix all green: core 142/142 (default, no TMPDIR),
real 18/18 (323/266/55/2/22/4/4/532), workspace charact 7/7 incl. host sv2v, legacy suites green,
submission clean @1997ed4. Deletion exploit closed (symmetric __setattr__/__delattr__ seal);
digest validation exact+typed; hardlink evidence symmetric + copy-method-independent. Authority
boundary accepted for the normal-operation threat model (hostile reflection explicitly out of
scope). Acceptance boundaries: H-1..H-3, checkpoint-2, and the campaign remain OPEN/NO-GO;
carry-forward guardrails (review §8) become regression gates for the migration. Approved §7
order; first slice = literal NVDLA registration + immutable run context + capability gate +
mandatory PENDING refusal (no model-call path while pending).

## 2026-07-22 (rev22) — §11 migration slice 1 delivered: NVDLA registration + RunContext + PENDING gate; 16/16

Per re-review5 §7.1-2/§10 (checkpoint-1 ACCEPTED, migration GO, first slice scoped):
- NEW ppa/registry.py: literal NVDLA_SPEC (NV_nvdla; 30/60ns clocks; dla_reset_rstn +
  direct_reset_ active-low, verified vs real top ports; explicit filelist) + literal
  NVDLA_LAYOUT; ensure_registered() idempotent via sealed registry; H-1 digest UNBOUND
  (production stays PENDING); IPS entry keeps NVDLA out of discovery. controller.main() registers
  before IP resolution.
- contract.py: frozen RunContext + build_run_context (derived validation state; §H.5 worker
  provenance requested/contract-cap/global-cap/effective resolved once); pure campaign_refusal()
  (structured CONTRACT_VALIDATION_PENDING record w/ expected/current digests).
- controller._campaign_gate at top of run(): persists refusal to ledger/refusals.jsonl + raises
  BEFORE any model call for real models on PENDING contracts; stub/keyless allowed (E.4).
- test_migration1.py **16/16** (zero-model-calls-while-pending proof; persisted refusal;
  idempotency; real-tree literal-layout characterization 323/22/4; RunContext provenance +
  immutability). All prior suites green (142/142, 18/18, 5/5+prereq, legacy). Patch:
  P04_MIGRATION_SLICE1.patch (330 lines). COPY_TO_CODEX refreshed (reply →
  NVIDIA_P04_MIGRATION1_REVIEW.md). Submission untouched @1997ed4; campaign NO-GO.

## 2026-07-22 (rev23) — §11 migration slice 2: H1–H5 materialization path; 20/20 (user: "crank through it")

User directive: push for wins on all IPs, time no constraint. Plan: NVDLA pipeline first (slices
2-7 + host evidence + checkpoint-2 + bounded campaign), then reopen aes/prim with the same
machinery; kmac stays closed (headroom, 2× Codex-confirmed). Slice 2 (re-review5 §7 step 3):
- NEW ppa/materialize.py: frozen steps 3-7 orchestrator (pristine regen → golden+H3 pre-overlay →
  validated overlay → candidate regen → H1/H2/H4 + scope-authoritative classification);
  mutation-class guard per generator invocation (immutable file deps + editable sources + golden
  re-verified — any non-tool-writable drift = flow-error); post_gate() steps 9-10 (H5==H4 +
  golden); **effective_inputs() = the sole path to candidate tool inputs** (refuses non-proceed /
  non-gate-stable); golden_inputs() re-verifies at use. Runner-injected, Docker-free.
- evaluate._clamped_workers: contract hard cap consumed at evaluate_many (nvdla 4→1, logged).
- test_materialize.py **20/20** incl. 3 evil-generator guards (candidate-invocation-only side
  effects caught), effective-input refusal matrix, worker clamp. Full battery green: 16/16 ·
  142/142 · 18/18 · 5/5+prereq · legacy. Patch: P04_MIGRATION_SLICE2.patch. COPY_TO_CODEX now
  requests slices 1+2 together (reply → NVIDIA_P04_MIGRATION1_REVIEW.md). Submission untouched
  @1997ed4; campaign NO-GO. Next: slice 3 = §7 step 4 (gate/proof adapters + policy result — the
  v2 LEC recipe with vacuous-proof guards lands here).

## 2026-07-22 (rev24) — slices 3+4: LEC v2 for ALL IPs + structural gate adapter + policy result + evaluation identity; 26/26. Campaign runbook written (user-directed 5-IP × 2-model rerun)

User directive: finish remaining dev, then re-campaign sha512/ascon/aes/prim/kmac (+NVDLA
wanted; stays gated) with HACKATHON_AISTUDIO_KEY on gemini-3.1-pro + gemini-3.5-flash.
- verify.py: canonical nvdla-lec-contract-v2 recipe for ALL IPs (equiv_simple -short →
  equiv_induct -seq 4 explicit → equiv_status -assert); lec_verdict() H.2 normalization —
  PROVEN = rc0+success+total>0+proven==total+unproven==0 TOGETHER (vacuous + success-string
  traps closed); unproven → INCONCLUSIVE/nonconvergent; counts in ledger notes; lec_v2_script()
  two-sided pinned template from side-bound DesignInputs; timeout tmake 1800s / legacy 900s.
  ⚠️ HOST POSITIVE CONTROLS REQUIRED pre-campaign (recipe changed for legacy too — runbook §2).
- NEW ppa/gate.py: structural phases w/ real rc; banner≠rc; zero-tests rejected; clean-dirs
  class-checked; candidate_aware = runtime H5==H4+tests evidence. run_gate.sh now RECORDS real
  rc (GATE-RC line; legacy semantics unchanged).
- NEW ppa/policy.py: single nvdla-eligibility-v1 result — 15 named conditions, deterministic
  reduction, composite assurance label, per-condition evidence record.
- contract.evaluation_id(): full B.2 identity (incl. design_inputs digest, recipes, container).
- test_migration3.py **26/26**; full battery green (20/20·16/16·142/142·18/18·legacy).
- NVIDIA_CAMPAIGN_RUNBOOK_JULY22.md: pre-flight, MANDATORY LEC-v2 pristine controls, 5-IP×2-model
  commands (unset EXPRESS_MODE_KEY; organizer key; flash→pro; aes/prim first, kmac bounded 10
  calls), quota ceilings ~280 calls, scratch-only emit, banking rules, H-1 recipe (scratch-copy
  caveat). NVDLA campaign NO-GO unchanged. COPY_TO_CODEX → slices 1–4 + campaign-state signoff
  request. Patches: SLICE2 (401), SLICE34 (716). Submission untouched @1997ed4.

## 2026-07-22 (rev25) — corrective slice: all 8 fail-open gaps closed; production authority chain wired; 34/34 + 27/27 + 19/19

Codex migration review (`NVIDIA_P04_MIGRATION1_REVIEW.md`): checkpoint-1 foundation stands;
slices 1-4 HELD (8 adversarial fail-open gaps — the assurance chain was library-only, stub
identity spoofable by class NAME, pristine-invocation + immutable-DIR mutations unguarded, H5
TOCTOU, print-only gate "candidate-aware", contradictory LEC logs → PROVEN, caller-asserted
policy, legacy gate rc fail-open); legacy campaigns NO-GO. Corrective slice per its §8 order:
- NEW ppa/orchestrate.py: THE production tmake path (RunContext→materialize→gate→H5 receipt→
  receipt-revalidated proof/measure→frozen EvaluationEvidence→policy→evaluation_identity→ledger;
  cached_evaluation = exact-id or MISS). ADV-26 end-to-end green on the fake tree.
- isinstance stub identity (name spoof REFUSED, ADV-1); run(profile=); workers resolved once.
- materialize: recursive immutable manifests (dirs incl. tools/spec/vlibs/rams) before pristine
  + after both invocations + on nonzero exit (ADV-5..8); frozen EffectiveDesign receipt;
  effective_inputs revalidates LIVE fingerprint + inputs digest at use (ADV-9/10).
- gate: full 5-phase machine; GatePlan mandatory clean dirs + exe binding (absent-after-clean /
  hashed-after-build / identical-after-tests); ADV-11..14 + stale-binary green.
- LEC: all-blocks parser (contradictory/late-unproven never PROVEN, ADV-16/16b); production
  lec_tmake() → frozen ProofEvidence w/ top/side-digests/script/log/H5 bindings (ADV-18/20).
- policy: evidence-derived 15 conditions, no caller booleans, evidence_root-validated results
  (ADV-21/22/24); evaluation_identity from the aggregate w/ typed digests (old free-string
  helper REMOVED); cache exact-or-miss (ADV-25).
- run_gate.sh: underlying rc wins (TEST PASSED+exit 7 → rc 7 FAIL, ADV-27); tb_gate requires
  rc0+GATE-RC:0+banner. P1s: mixed-IP refusal, ensure_registered verifies, runbook updated
  (campaigns NO-GO pending re-review; kmac REMOVED per SS5.9; scratch-safe H-1 SS5.8).
Patch: P04_CORRECTIVE_SLICE.patch (2181 lines). Tests: 34/34·27/27·19/19·142/142·18/18·charact·
legacy ALL GREEN. COPY_TO_CODEX → corrective re-review (reply NVIDIA_P04_CORRECTIVE_REVIEW.md).
Submission untouched @1997ed4. Campaigns + NVDLA remain NO-GO pending Codex §7.2 release.

## 2026-07-22 (rev26) — corrective slice 2: causality/containment/freezing/identity/cache/legacy-parser; 47/47 + 29/29

Codex corrective review: HOLD w/ 10 items (gate causality via arbitrary plans; clean-dir
traversal could delete editable RTL; immutable symlink targets invisible; shallow freezing;
correct-root forgery; -inf measurements; plan-invariant identity; tampered cache rows; 3 more
legacy-parser holes; orchestrator still not the enforced path). All ten closed:
- GatePlan canonical at construction (.. /absolute rejected; exe inside a clean root; full
  digest; per-IP registry); CLEAN = validated rmtree (no rm -rf strings); REGENERATE must BE
  the contract generator recipe; separate LINK; test phase derived from the declared artifact;
  gate-invocation immutable/editable/golden audit; self-validating GateEvidence (ref covers
  plan+phases+counts+H4/H5 → any command change ⇒ new identity).
- Symlinks under immutable roots structurally forbidden (leaf + dir; SS8.7 regressions).
- freeze_receipt() → transitively frozen self-validating MaterializationReceipt; policy consumes
  ONLY frozen exact types; builder mutation after freeze provably inert (SS8.8b).
- MeasurementEvidence rejects NaN/±inf/neg; ALL refs 64-hex; EligibilityResult FACTORY-GUARDED
  (correct-root manual construction refused, SS8.10); proof bindings complete (top + both side
  digests incl. new golden_inputs_digest + script/log/H5; ProofEvidence self-validates).
- evaluation_identity includes plan digest + gate ref + receipt ref + RECOMPUTED source CID;
  registration digest includes IPSpec facts; cache rows VALIDATED (tampered ⇒ MISS, SS8.15).
- run_gate.sh: contradictory summaries FAIL; FAIL markers override banners; uncounted banners
  FAIL; functional failure exits nonzero (4 shell probes green). evaluate_many REFUSES tmake
  (SS8.17); orchestrator finally-destroys workspaces.
Deferred honestly (UPDATE 13): raw-log store, pre-equiv interface sigs (yosys), executor-wide
worker consumption, CLI profile, controller/pool consumption (= the migration itself).
**Tests: 47/47 · 29/29 · 19/19 · 142/142 · 18/18 · charact · legacy ALL GREEN.** Patch:
P04_CORRECTIVE2_SLICE.patch (1718). COPY_TO_CODEX → corrective-2 re-review (reply
NVIDIA_P04_CORRECTIVE2_REVIEW.md). Submission untouched @1997ed4. Campaigns/NVDLA NO-GO.

## 2026-07-23 (rev27) — four in-scope corrective-2 fixes + SCOPING MEMO (user-directed stopping rule)

User: worried the Codex loop is going off-track (late rounds increasingly probe in-process
self-forgery, which 1f ruled OUT). Directed: fix the 4 load-bearing items, then send a scoping
memo instead of another full self-adversarial slice.
- FIX-1: both gate parsers (run_gate.sh + gate.parse_test_results) scan FAIL evidence over the
  COMPLETE output — only the summary PATTERN text stripped, never whole lines; case-insensitive.
  A line with summary/banner + [FAIL] now FAILS (corrective2 SS4.6). 6 shell probes verified.
- FIX-2: GatePlan.test_args = validated argv tuple, shlex-quoted; `; echo` token inert on an
  exit-7 artifact → gate FAILS (SS4.1 injection). Free-form string refused.
- FIX-3: clean-path alias validation UNCONDITIONAL (nonexistent leaf under symlinked parent
  rejected; SS4.7).
- FIX-4: validate_cached_row requires every condition exactly once (15-copy forgery MISS; SS4.5).
- NVIDIA_P04_SCOPING_MEMO.md: proposes adopting the 1f threat model boundary-wide (honest-mistake
  + untrusted-input IN [parser/cache/symlink/manifest stay strict — logs & ledger rows are DATA];
  in-process self-forgery OUT), deciding legacy campaign release by REAL-tool per-family pos+neg
  gate controls (rev11 epistemology) not code inspection, and re-classing the open §4 items
  (IN-fixed / checkpoint-2-host / deferred-infra / out-1f). Banking stays per-candidate
  manifest-gated (waste quota at worst, never corrupt the submission).
Tests: 51/51 · 29/29 · 19/19 · 142/142 · 18/18 · charact · legacy ALL GREEN. Patch
P04_FOCUSED_FIXES.patch (223). COPY_TO_CODEX → scoping request (reply NVIDIA_P04_SCOPING_REVIEW.md).
Submission untouched @1997ed4. Campaigns/NVDLA NO-GO pending the scoping decision.

## 2026-07-23 (rev28) — ✅ SCOPING ACCEPTED: legacy campaigns conditional per-IP GO; NVDLA finite 12-item checkpoint-2; stopping rule set

`NVIDIA_P04_SCOPING_REVIEW.md`: threat model ACCEPTED (in-process self-forgery OUT, consistent
with 1f; honest-mistake + untrusted-input + persisted-rows IN); four focused fixes ACCEPTED;
legacy campaigns CONDITIONAL per-IP GO after a real-tool release packet; NVDLA NO-GO on a finite
12-item checkpoint-2. **No more speculative code cycles** — a blocking finding now requires a
production/public-path or untrusted-input route with a reproducible control.
- Built `ppa/release_control.py` (HOST): produces Codex's 6-item packet per IP — gate pos+neg +
  LEC-v2 pos+neg on disposable Workspaces, full provenance to /private/tmp/nvdla_release_evidence,
  FAIL-SAFE (negative must fire or IP is NOT-RELEASED). Mutation = invert an `assign <output>`
  RHS in an editable source both gate+LEC see (dual-rep → sv_source). Static-verified mutation
  sites resolve for all 4 IPs (sha512 read_data, ascon idle_o, aes idle_o, prim alert_ack_o).
- Runbook updated: status → CONDITIONAL per-IP GO; new §2 = the release-packet gate (must show
  RELEASED:True before campaigning that IP); reset rule (§3.3); stale counts fixed (materialize
  29, migration3 51, migration1 19).
- `NVIDIA_NVDLA_CHECKPOINT2_CHECKLIST.md`: the 12 items (mixed code+host). 2 CONFIRMED real bugs:
  #9 eval-identity omits measurement/policy (Codex repro'd same-ID improving-vs-regressing via
  the public orchestrator); #6 per-invocation mutation audit → build/link/test.
- Memory: new nvdla-p04-status.md (boundary + release procedure + checkpoint-2).
NEXT (user's Mac session): run the 4 release packets → campaign each RELEASED IP (flash then
3.1-pro, aes/prim first) → bring results back for banking review. Submission untouched @1997ed4.

## 2026-07-23 (rev29) — wrote CLAUDE_TO_RUN.md execution handoff for the unsandboxed host Claude

This sandbox confirmed to have NO Docker/EDA toolchain (yosys/OpenSTA/sv2v/iverilog all MISSING);
release controls + campaigns can only run on the host. User has a separate unsandboxed Claude
Opus 4.8 with Docker; wrote `CLAUDE_TO_RUN.md` as its ordered, safety-first execution handoff:
§0 SAFETY (unset EXPRESS_MODE_KEY every shell / organizer key only / never touch submission /
never bank / kmac+nvdla excluded / quota ceilings), §1 verify state (submission clean @1997ed4,
suites at expected counts, cold-start 6/6), §2 release packets per IP (release_control, with
--mut-file/--mut-signal fallback guidance + per-IP default targets), §3 campaigns per RELEASED IP
(flash then pro, scratch-only emit, ceilings+early-stop), §4 collect evidence + hand back (NO
autonomous banking), §5 decision latitude, §6 failure handling. NOTE: shared mount confirmed (user
reads sandbox-written files on the host), so release_control.py + all fixes are already present
host-side. Submission untouched @1997ed4.

## 2026-07-22 — ran CLAUDE_TO_RUN.md release packets (host, Docker): 0 released, 0 quota, LEC-v2 verdict bug found

Executed the sandbox handoff `CLAUDE_TO_RUN.md` §1–§4. §1 state green (submission clean @1997ed4;
no-Docker suite exact: contract 142/142, contract_real 18/18, workspace_charact 7/7, migration1 19/19,
materialize 29/29, migration3 51/51, + selection/emit/model-iface/failclosed/area; cold-start 6/6
Docker; verify.py `rename -hide`=0). §2 release packets **ALL NOT-RELEASED**: aes/prim/ascon gate+=FAIL,
sha512 gate+=PASS; **LEC+ = INCONCLUSIVE for ALL 4**; every negative control fired correctly. §3 NO
campaigns (nothing released) → **0 organizer quota spent** (no new ledger/raw for the campaign IPs).
**BLOCKING FINDING: `verify.py::lec_verdict` misclassifies every real proof as INCONCLUSIVE/
nonconvergent.** sha512 note: rc=0 total=12775 proven=12775 unproven=0 — a full proof — but the
`any_unproven` guard (lines ~248-249) matches the INITIAL "Found N unproven $equiv cells" progress line
present in EVERY successful equiv run (incl. NVDLA's own PROVEN run), so PROVEN is unreachable for all
designs. Reproduced deterministically no-Docker: `lec_verdict(0, <proven log>)` -> INCONCLUSIVE. I did
NOT patch it (runbook §5 — don't code around a control). Secondary: OpenTitan pristine gate FAIL
(aes/prim/ascon) vs sha512 PASS = a separate runner/flow issue, moot until LEC-v2 verdict fixed.
Evidence preserved in `nvdla_release_evidence/` (4 packets + logs) + `NVIDIA_CAMPAIGN_RESULTS_2026-07-22.md`.
Nothing banked, no submission/canonical/paid-key change. Next: sandbox Claude fixes lec_verdict
(+ fixture: proven-log->PROVEN, unproven-log->INCONCLUSIVE), re-run release packets, then campaign only
RELEASED IPs.

## 2026-07-23 (rev30) — host release-control caught TWO real regressions of mine; both FIXED + verified

The unsandboxed host Claude ran the release packets: 0 released, 0 quota spent — the control gate
worked. It surfaced two blocking bugs I introduced, both now fixed in the sandbox:
1. **LEC verdict made PROVEN unreachable** (blocked EVERY IP incl. NVDLA). `lec_verdict`'s
   any_unproven guard used `_RE_UNPROVEN = "Found N unproven $equiv cells"`, which matches the
   yosys `equiv_simple` ENTRY line (cells QUEUED for proving — present in every real proof;
   NVDLA logged "Found 381209 unproven"). Fixed: anchor to the `equiv_induct` RESIDUAL
   ("... unproven $equiv cells in module equiv"); final counts still from equiv_status + rc.
   Root cause was an UNREALISTIC test fixture (OK_OUT lacked the entry line) — replaced with a
   realistic yosys log + a dedicated regression. Reproduced INCONCLUSIVE on a 12775/12775/0
   proof, now PROVEN.
2. **run_gate.sh rejected the OpenTitan Verilator success format** (aes/prim/ascon gate+ FAIL,
   sha512 passed). The verilator TBs print "Simulation passed!" (single-verdict, no per-test
   count); my FIX-1 hardening's "banner with zero counted tests -> FAIL" over-rejected it.
   Fixed: a recognized sim-success banner + rc0 + zero fail markers = PASS (gate_cmd is fixed
   per-IP, not agent-injected -> uncounted banner isn't a production-reachable gaming vector
   under the agreed threat model; rc/fail-markers/contradictions still gate). 7-case shell matrix
   + a persisted regression ("Simulation passed!"->PASS, "Simulation failed!"->FAIL).
Both are correctness-on-real-tool-output fixes (in-scope). Tests: migration3 54/54, all suites
green. Expectation on re-run: pristine self-equiv LEC+ now PROVEN for all IPs; verilator gate+
now PASS -> all four IPs should RELEASE (unless the FuseSoC/verilator BUILD genuinely fails in
the container, which the packet gate_detail would show as a build error rather than "Simulation
passed!"). Submission untouched @1997ed4.

## 2026-07-23 — re-ran release packets after sandbox's 2 fixes + sha512 flash campaign (host, Docker)

Per CLAUDE_RERUN_NOTE.md. Both fixes VERIFIED (LEC-v2 verdict: real proven-log->PROVEN, residual->
INCONCLUSIVE; run_gate.sh "Simulation passed!"->PASS; migration3 54/54). RELEASE PACKETS:
**sha512 RELEASED** (4/4 clean); **ascon RELEASED** (auto-pick idle_o didn't fire the negative GATE —
status flag not KAT-checked; retried --mut-file prim_ascon_sbox.sv --mut-signal state_o (S-box, feeds
every KAT vector) -> gate- FAIL, RELEASED); **prim NOT-RELEASED** (pristine gate+ FAIL "banner+1 FAIL
marker" — likely a 2nd parser over-reject like the banner fix, prim has a banked win; + negatives
under-fire, alert_ack_o is a no-op under top prim_crc32 — see NVIDIA_PRIM_GATE_FINDING.md); **aes
INCOMPLETE** (killed for memory, re-run serially). **sha512 FLASH CAMPAIGN** (organizer key, ai-studio
free path, gemini-3.5-flash, 3 rounds, **13 calls ~471k tok**, 5 accepted): per-round frontier ADP
0.787->0.735->0.7216. **Canonical LEC-PROVEN best = 0.787 (WORSE than banked 0.7266); frontier 0.7216
was LEC-INCONCLUSIVE -> assurance selector correctly refused it -> NO bankable improvement, nothing
banked, banked 0.7266 stays.** SAFETY: paid EXPRESS_MODE_KEY never used (unset+pinned key-env, inline
gate); no submission/canonical change; submission clean @1997ed4; emits to scratch. HOST GOTCHAS:
(1) google-genai missing for py3.12 (PEP668) -> venv /private/tmp/campaign_venv w/ google-genai 1.47.0;
(2) macOS TCC blocks rmtree of workspace techlib dirs under Documents -> Workspace.create crashes on
reuse -> mv-aside workaround (crashed aes first); (3) Docker VM 7.65GB -> 3+ concurrent yosys LEC
thrash -> 40-60min zombie containers (LEC subprocess timeout doesn't docker-kill the container) ->
SERIALIZE heavy jobs. Full writeup: NVIDIA_CAMPAIGN_FINAL_REPORT_2026-07-22.md. Evidence:
nvidia_campaign_evidence/. NEXT: prim triage, aes serial re-run, ascon campaign (released, awaiting
go-ahead), optional sha512 pro run for a provable 0.7216-class candidate.

## 2026-07-23 (rev31) — host run assessed; 3 follow-up fixes landed; 3.1-pro full-run handoff written

Read the host Claude's NVIDIA_CAMPAIGN_FINAL_REPORT (both my fixes verified on REAL yosys/verilator;
sha512/ascon RELEASED, prim NOT, aes INCOMPLETE; sha512 flash = textbook assurance outcome — 0.7216
found but LEC-INCONCLUSIVE → correctly refused, nothing banked; safety held). Corrections + fixes:
- **prim analysis corrected:** banked prim manifest says gate=SKIP-preexisting (verilator gate NEVER
  ran for prim's banking) + run_verilator_tb.sh "all" runs 5 sub-TBs → the pristine-gate FAIL is
  AMBIGUOUS, not clearly a parser over-reject. Did NOT patch speculatively; decisive raw-line
  diagnostic + decision tree handed to the host.
- **Fix 1 (aes crash):** Workspace.create now always-unique dirs (macOS TCC rmtree crash gone).
- **Fix 2 (auto-picker):** release_control.mutate prefers datapath signals, penalizes status flags
  + tie-offs/unused (the ascon idle_o lesson); explicit override still wins. Verified per-IP.
- **Fix 3 (NEW ppa/lec_diagnostic.py, host-only):** classifies WHY a candidate is INCONCLUSIVE —
  COMBINATIONALLY_PROVABLE / SEQUENTIALLY_PROVABLE@seqN / INEQUIVALENT / TRULY_NONCONVERGENT.
  Evidence-only, never changes the shipping recipe. Reuses verify._read_stanza. This is the tool
  to classify sha512's 0.7216 for FREE (no model call) before spending 3.1-pro quota.
- Full battery green (contract 142/142, migration3 54/54, materialize 29/29, ...).
- **NVIDIA_RUN2_31PRO.md** handoff written: verify state → finish aes/prim packets → classify the
  0.7216 for free → campaign released IPs with gemini-3.1-pro-preview (organizer key, ~25 calls/IP,
  serialize) → lec_diagnostic any near-miss → collect for banking review. kmac/nvdla excluded;
  no auto-banking. Submission untouched @1997ed4.

## 2026-07-23 (rev32) — reviewed NXP + ASU tracks; wrote NXP_ASU_REVIEW_FOR_CODEX.md (P0 found)

While the host Claude runs the 3.1-pro campaigns, reviewed the two under-reviewed tracks. Key:
- **NXP P0 (reproduced here, rc=1):** organizer rtl_gen_lib/_load_yaml_minimal is unconditionally
  broken (`result, stack = {}, [(0, result)]` → UnboundLocalError) and is the intended no-PyYAML
  path. Our 30/30 validation had PyYAML; eval-env PyYAML is CONTRADICTORY in the organizer's own
  docs (DEPENDENCIES.md: stdlib-only; README:99: optional; on_prem reqs: PyYAML==6.0.3). If the
  runner env lacks PyYAML → rtl_gen crashes → no .v → RUNNER exits 1 → score 0. Agent doesn't
  defend against it (also makes test_ip_models 0/12 here). Proposed fix: ship a correct pure-Python
  yaml shim + prepend to the rtl_gen subprocess PYTHONPATH (keeps stdlib-only, robust either way).
- NXP runner-mode key safety CONFIRMED: RUNNER uses info[model_endpoint], never EXPRESS_MODE_KEY.
- NXP validated EASY only (contest ships only easy); anticipatory medium/hard modeling exists but a
  contest library bug (dma_engine non-compiling RTL) would fail hidden medium dma cases.
- ASU: deterministic via-bar, stdlib-only, self-guarding (no-op floor), 5 artifacts byte-committed
  + independently re-scored FVR 0.68-0.76. Low risk. Open question A1: is no-op == eligibility floor
  on hidden blocks? (needs the scoring policy read).
Doc NXP_ASU_REVIEW_FOR_CODEX.md written (P0/P1/P2 ranked + 4 questions for Codex). No code changed;
submissions untouched (NVIDIA @1997ed4). Next: review with Codex, then implement the NXP shim if
confirmed.

## 2026-07-23 (rev33) — acted on Codex NXP/ASU review: NXP P0 shim + endpoint hardening FIXED; ASU wording corrected

Codex verdicts: NXP HOLD (fix P0 no-PyYAML + cold-test), ASU GO (wording only), defer medium/hard.
Implemented + offline-verified:
- **NXP P0 FIXED**: NEW _yaml_compat/yaml.py fail-closed shim (flat subset the agent emits; raises on
  lists/tags/dups/non-mapping; no organizer walrus bug). _rtl_gen_env() prefers installed PyYAML,
  injects shim on the rtl_gen subprocess PYTHONPATH only when absent; wired into generate_ip +
  test_ip_models. VERIFIED: organizer rtl_gen crashes w/o PyYAML, generates 8/8 easy specs WITH the
  shim; ip_models no longer crashes (only iverilog remains, host-only).
- **NXP P1 FIXED**: EndpointModel.generate() typed + deadline-bounded — malformed JSON / bad UTF-8 /
  non-mapping body / missing-empty-nonstring text are typed transient (were uncaught JSONDecodeError/
  AttributeError); monotonic total_deadline_s caps retries; no content/secret leak. NEW test_endpoint
  .py 12/12.
- **NXP corrections**: dma_engine is ALREADY mitigated (validators.patch_library_rtl + 12-IP diff
  covers it) — I was wrong; medium/hard deferred (runner exposes only easy); DEV paid-key guard
  (P2) noted not applied (RUNNER already safe).
- **ASU wording corrected** (no geometry change, PROVEN emission-neutral — via_bar_snippet SHA
  d0591819 unchanged, banked artifact SHAs intact): README + agent.py docstring now say no-op =
  ELIGIBLE FALLBACK not FVR 1.0 (public no-op ~1.25-1.32), net-win not "never worse", connectivity
  = official(source-parser)+rendered-proxy. Geometry/predicate/manifests untouched.
Docs: NXP_ASU_ACTIONS_2026-07-23.md (actions + remaining HOST §6.1 matrix). Submission repos
untouched; NVIDIA @1997ed4. NXP working-copy → submission sync only after the host forced-no-PyYAML
cold matrix is green.

## 2026-07-23 — run 2: Gemini 3.1-pro on released IPs + aes/prim finish (per NVIDIA_RUN2_31PRO.md)

State verified (migration3 54/54, contract 142/142, cold_start 6/6, submission clean @1997ed4).
**NO BANKABLE IMPROVEMENTS — assurance gates worked perfectly.** sha512 3.1-pro: 3 rounds, **accepted 0**,
~15 calls/337k tok; canonical stays 0.787 PROVEN, banked 0.7266 best; the 0.7216 flash near-miss
classified **TRULY_NONCONVERGENT** (free lec_diagnostic). ascon 3.1-pro: round2 accepted a frontier
0.9546 (beats banked 0.97918) BUT lec_diagnostic = **INEQUIVALENT (real counterexample @seq4) — WRONG,
dropped**; canonical stays banked 0.9792; ~15 calls/804k tok. **Headline safety win: the LEC gate caught
a better-ADP-but-functionally-broken ascon candidate — ADP-alone would have banked a regression.**
aes: crash FIXED (unique dirs), ran to completion but NOT-RELEASED — gate+ FAIL (`Failed: 0` zero-count
matched by \bFAILED\b = parser over-reject) + lec+ INCONCLUSIVE (LEC **timeout 900s**, slow-not-crashed
→ needs raised timeout max(1800,2xpristine)). prim: raw-TB triage DEFINITIVE — all 5 sub-TBs
SIMULATION PASSED, rc 0, the "1 FAIL marker" is literally `Failed: 0` → same parser over-reject as aes;
LEC+ already PROVEN so prim should release after the zero-count fix. **ONE gate fix (strip zero-count
Failed:0) unblocks BOTH aes+prim.** QUOTA: ~30 3.1-pro calls/~1.14M tok organizer key (ai-studio free);
release+diagnostics 0 model calls; paid EXPRESS never used; nothing banked; submission clean @1997ed4.
ENV: aes unique-dirs fix confirmed; 3.1-pro candidates have slow/non-convergent LEC that burns 900s
timeout + orphans containers (killed stuck>15min to unblock — recommend docker-kill on TimeoutExpired).
Full report: NVIDIA_CAMPAIGN_RESULTS_2026-07-23.md; evidence nvidia_campaign_evidence/run2_31pro/.
NEXT (sandbox): zero-count gate strip + raised LEC timeout -> re-run aes/prim -> campaign if released.

## 2026-07-23 rev34 — sandbox fixes for aes/prim release (acting on run-2 report)

Implemented the exact three fixes the run-2 host report called for; all offline-verified,
submission untouched (@1997ed4), no model calls, no banking.

**Fix 1 — zero-count gate strip (unblocks BOTH aes + prim).** The single "FAIL marker" that
FAILed pristine aes/prim gate+ was literally the benign counter `Failed: 0`, which
`\bFAILED\b` (case-insensitive) matched. Stripped exact-zero fail/failure/error counters
(`Failed: 0`, `0 FAILED`, `Failures: 0`, `errors: 0`) before counting FAIL markers — in BOTH
parsers for consistency: `harness/run_gate.sh` (legacy shell gate) and
`ppa/gate.py::parse_test_results` (tmake structural gate, new `_RE_ZEROFAIL`). A zero count is
definitionally not a failure, so the strip can never mask a real one (mirrors the existing
"N PASS, M FAIL" summary strip). Verified 8-case matrix on each parser: aes/prim banner+`Failed: 0`
→ PASS; real `Failed: 3`/`Failed: 10`/`[FAIL]` → FAIL; `Failed: 0` AND a real `[FAIL]` → FAIL;
bare uncounted `0 FAILED` with no pass evidence → still FAIL (fail-closed uncounted rule intact).

**Fix 2 — size-tiered legacy LEC timeout (unblocks aes).** aes LEC was slow-not-stuck, exceeding
the flat 900 s on pristine self-equivalence. `ppa/verify.py::_lec_timeout` now gives legacy IPs with
>=40 sources the 2400 s cap (aes ~75 srcs); smaller legacy IPs keep the proven 900 s (a genuinely
non-convergent small candidate should not burn 40 min/attempt). tmake path unchanged (1800 s).

**Fix 3 — reap orphaned container on timeout (VM thrash).** `ppa/config.py::docker_run` now names
the container (`iclad_<uuid>`) and `docker kill`s it on `TimeoutExpired` (best-effort, never masks
the original timeout). Fixes the orphaned slow-yosys container that thrashed the 7.65 GB VM; the
host previously had to manually kill stuck >15 min containers.

Regression battery green: migration3 54/54, contract 142/142, selection 4/4, materialize 29/29,
measure_failclosed 13/13, emit_replace 2/2; all three edited files parse. cold_start still 1/5 —
FileNotFoundError on the `docker` binary only (sandbox has no Docker; my `except TimeoutExpired`
correctly does NOT swallow it, so behavior is unchanged for the no-docker path). Handoff
NVIDIA_RUN2_31PRO.md refreshed with the re-run instructions. NEXT (host): re-run aes + prim release
packets → campaign any that RELEASE (prim− control still needs a prim_crc32-datapath mutation like
`crc_out_o`).

## 2026-07-23 (run 2b) — rev34 re-run of aes+prim: zero-count fix works; both blocked by deeper issues

Applied sandbox rev34 (zero-count `Failed: 0` strip both parsers; legacy LEC 2400s for >=40-src;
docker_run container reap). State green (54/54, 142/142, cold_start 6/6, clean @1997ed4). **prim:**
gate+ now PASS (zero-count fix works), lec+ PROVEN; retried negative with `prim_crc32.sv crc_out_o`
(real datapath) — mutation applied (sha differs), **LEC caught it (32 unproven) but the verilator gate
PASSED the mutant** => prim gate is **CANDIDATE-BLIND** (doesn't exercise the mutated .sv); NOT-RELEASED;
no mut-signal fixes it (ascon-class candidate-blind gate; sandbox must make prim gate compile the
candidate). **aes:** gate+ PASS (zero-count) + unique-dirs crash fix confirmed, but **pristine
whole-design LEC TIMES OUT even at 2400s** (positive stage ran ~45min = gate + full 2400s LEC timeout);
NOT-RELEASED; aes too big for whole-design LEC in the 7.65GB VM (not a crash like kmac — just scale);
sandbox: candidate-aware/module LEC for aes or exclude it. NET run2: only sha512+ascon released+
campaigned (no bankable win); prim+aes blocked by deeper issues rev34's parser fix uncovered. Nothing
banked; submission clean @1997ed4; paid key never used. NOTE: host session pauses on permission prompts
— ~4h idle gap mid-run (user away); I mis-killed aes's idle LEC container thinking it an orphan, cleaned
up + re-ran aes. Evidence: nvidia_campaign_evidence/run2_31pro/ (+ prim 0723 packets). Report:
NVIDIA_CAMPAIGN_RESULTS_2026-07-23.md (RUN 2b section).

## 2026-07-23 (rev35, host/Fable-5) — prim gate mystery SOLVED (mechanism B, source-level); Codex research ask drafted

State verified (54/54, 142/142, clean @1997ed4). **prim clean-cache control matrix:** pristine+purged
caches -> 5/5 PASS 37s; MUTANT (crc_out_o inversion, verified present in workspace .sv)+purged caches
-> STILL 5/5 PASS. Then read the TB source: `prim_crc32_sim.sv` is a **print-only smoke TB** ($display
+ $finish, NO expected-value comparison; C++ success = reached $finish). **The prim gate cannot catch
functional corruption BY CONSTRUCTION — not stale cache.** prim stays NOT-RELEASED; banked prim win
unaffected (banked via LEC PROVEN + dualsim, the stronger path). Policy question handed to sandbox/
Codex: substitute dualsim-negative for gate-negative on smoke-only-TB IPs? Also: **drafted the Codex
research consultation** (`COPY_TO_CODEX.md`): 5 asks — new timing-targeted LEC-safe rungs
(late-arrival-shannon, arrival-aware and-or, fanout-duplicate, onehot-select, unshare-timing),
tag→rung mapping critique, technique EV ranking under yosys+ABC (evidence: area-motivated restructure
keeps worsening slack), prompt guardrails vs broken candidates, bounded pipelining-policy verdict
(sha512 handshake TB). Literature scan sourced (ASPEN, POET, 2009.08844, 2507.16808, PipeRTL). No
model calls today yet; no code changes; submission clean @1997ed4.

## 2026-07-24 (host) — campaigns done (2 banking candidates!); NVDLA packet first real run: STOPPED on trace-runtime finding

CAMPAIGNS (ladder v2+v3, organizer key, ~60/80 calls): **async_fifo 0.9099 FULL-5-LAYER PROVEN**
(balanced-tree; −8 redundant FFs = gray-deregister class; CDC aspect flagged) and **prim 0.5824 vs
banked 0.6045, LEC PROVEN+dualsim** (late-input-cofactor — first v2-rung proven win) → BOTH packaged
for Codex banking review (COPY_TO_CODEX.md). sha512 0.6546 near-miss = TRULY_NONCONVERGENT; ascon
0.9129 = INEQUIVALENT (refused); **kmac: right-strategies rerun (xor/sum-cluster/templates leading,
keccak fence held) = 0 accepted/ADP 1.0 → bounded-negative CONFIRMED at high confidence** (only
remaining headroom is inside the masked core, off-limits by design). kmac keccak masking fence added
to FENCE (blocks keccak_2share/keccak_round/prim_dom_and; verified both ways).
NVDLA BUILDOUT (Codex implemented): battery independently verified (25/25 buildout + full matrix
green). First real-tool release packet run: Verilator build SUCCEEDED; tmake/hash chain clean; traces
scoped correctly; traces are SELF-CHECKING (CHECK_CRC). **STOPPED at trace 2: each trace ≈ 59 min CPU;
suite = 85 traces (15 pdp) → ~30 h/packet as configured → infeasible.** Finding + revision options
(single shortest scope-matched trace / --trace-tests override / timeout margin) handed to Codex
(COPY_TO_CODEX addendum). Partial evidence: nvidia_campaign_evidence/nvdla_packet_partial_0724/.
Next: aes real-flow campaign (user-directed, overnight); NXP/ASU host matrix pending (user: tomorrow).
Submission clean @1997ed4 throughout; paid key never used; nothing banked.

## 2026-07-24 (host, day close) — real-flow sweep COMPLETE; aes closed; LEC-timeout regression found+worked around

aes (workers 4, 23GB VM): rounds 1-2 accepted 0 -> early-stop verdict, baseline stands. During the
run: **REGRESSION — campaign LEC path lost timeout enforcement post-buildout** (2 LEC jobs ran 5h at
100% CPU vs the 2400s cap; external container kill unwedged instantly; both candidates recorded
lec ERROR fail-closed — no unsound result, wall-clock only). aes process later died silently pre-emit
(rounds ledger intact; outcome unaffected). Both filed as COPY_TO_CODEX Addendum 2 with fix asks.
Docker VM raised 7.65->23.19GB mid-day (claude-sandbox containers lost as expected). SWEEP TOTALS:
2 banking candidates (async_fifo 0.9099 full-5-layer; prim 0.5824 late-input-cofactor), 3 correct
refusals, kmac closed high-confidence, aes closed, NVDLA buildout at first-real-contact with 2
findings for revision. ~78/80 calls. Consolidated report: NVIDIA_CAMPAIGN_RESULTS_2026-07-24.md.
Submission clean @1997ed4; nothing banked; paid key never used.

## 2026-07-24 (host, late) — NVDLA release packet: 5/6, holdout = pristine trace failure; banking A/B executed; NXP matrix GREEN

NVDLA packet rerun (`pdp_1x3x8_8x8_ave_int8_0`, TEST_TIMEOUT_SEC=4500) COMPLETED — release_nvdla_0724_144931.json:
LEC POSITIVE **PROVEN 381209/381209** through the production recipe; LEC NEGATIVE INCONCLUSIVE (mutant,
80 unproven) — correct; tripwire candidate_aware=True, generated roots match pristine/candidate,
mutation_audit_ok; determinism 2x PASS; gate NEGATIVE fires (1 pass/4 fail). The lone holdout: gate
POSITIVE = FAIL because the tmake-regenerated PRISTINE tree fails 1 of 3 pdp_1x3x8 traces (2 pass/1 fail).
KEY RUNTIME FINDING: even the second-smallest trace sims ~73 min — trace cost is dominated by whole-design
init, NOT data volume; the "single small trace" speedup only helped via the degenerate 1x1x1 (which fails
pristine for lack of PDP data). So per-candidate trace gating remains expensive; the pristine-trace-failure
is a build-config/golden-reference mismatch to diagnose (NOT a contract-machinery fault — hashes + PROVEN
LEC confirm the candidate pipeline is exact). NVDLA stays NO-GO (unchanged; checkpoint-2 + this diag).
BANKING (user-directed, Codex-reviewed): (A) prim d17234c34395 0.5824 BANKED into nvidia_work/submission/prim
(old 0.6045 archived; Codex evidence JSON attached); (B) async_fifo REVERTED to pristine baseline —
Codex DENIED the 0.961 banked candidate as a CDC glitch hazard (combinational gray at the crossing);
host safe-rebuild (registered crossing retained) verified 5-layer PROVEN but measured ADP 0.9984 (noise) —
the gains WERE the unsafe FF removal; async_fifo ships baseline. Playbook p1-gray-deregister RETRACTED→UNSAFE.
NXP §6.1 host acceptance matrix GREEN (30/30, 79/79 golden+model, ip_models/runner/structural/endpoint all
pass in BOTH normal-PyYAML and forced-no-PyYAML; shim conditional + byte-identical on 8 real specs + tag =
inert string). NXP working copy eligible to sync (pending user commit). Docker VM now 23.19GB/12CPU.
Submission: chip-convergence-iclad26 git still clean @1997ed4 (0 changes); nvidia_work/submission staging
holds today's user-directed banking. Paid key never used; excluded IPs untouched.
