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
