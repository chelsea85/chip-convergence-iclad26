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
