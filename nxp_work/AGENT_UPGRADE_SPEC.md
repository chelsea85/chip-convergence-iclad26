# NXP nxp_agent.py — UPGRADE SPEC (from deep-read research, 2026-07-02)

Implementation-grade task list distilled from Spec2RTL-Agent (2506.13905, NVIDIA/Ren),
AssertionForge (2503.19174 + NVlabs repo), EvolVE (2601.18067), SpecAssess (2512.00045),
SLDB (2507.06376 + sld-columbia repo, Apache-2.0), AutoHarness (2603.03329), MAKER
(2511.09030), RLAC (2511.01758), DeepCode (2512.07921), LEAP (2606.03303), ACE, BATS, EFC.
Full context: ../RESEARCH_NOTES.md. Scoring: passed/22 hidden tests; compile fail = 0;
tokens = tiebreak.

**Strategic headline (double-evidenced):** reset semantics (polarity + sync/async) is the #1
silent killer — most-misspecified spec element (SpecAssess: LLM judges rate broken-reset specs
0.9 while round-trip reconstruction scores 0.0) AND violated at integration even when explicitly
prompted (SLDB: o3-mini 100% syntax / 10% functional). Constraints must be enforced by TOOLING,
not prompting.

---

## Phase 0 — Correctness firewall (compile-fail=0 insurance) ~7h

- [x] **0.1 Port-exactness hard gate** **DONE Jul 5** (validators.port_contract, non-bypassable). (non-bypassable): token-level diff of
      `secure_periph_soc.v` module header vs skeleton (name/dir/width/order). Even frontier
      models alter ports they're told not to touch (SLDB). Run before every submission. (1h)
- [~] **0.2 Reset triple-layer** **PARTIAL Jul 5**: (b)-variant reset_lint (por_n topology + single synced net) + (c) reset-first test stage; mandatory YAML reset field pending.: (a) YAML schema makes `reset:{name, polarity, sync|async}`
      MANDATORY per IP — validation fails without it; (b) deterministic RTL lint: every
      sequential block's sensitivity list must match YAML (`posedge clk` iff sync;
      `posedge clk or negedge rst_n` iff async active-low); (c) reset behavior = first
      self-test stage. (2-3h)
- [~] **0.3 Deterministic YAML validator** **PARTIAL Jul 5**: typed/consolidated errors, type whitelist, param ranges, dup names; skeleton cross-checks + address-map overlap pending. (AutoHarness `is_legal`): port/width legality vs
      skeleton, every skeleton port in exactly one IP's map, clock-domain consistency,
      address-map non-overlap, IRQ lines land on controller inputs. Typed, consolidated error
      output. Two-sided credit assignment: validator passed but downstream failed → log
      validator gap, refine the VALIDATOR too. (3-4h)

## Phase 1 — Self-test toward hidden-golden parity ~12h

- [x] **1.1 Fractional score** **DONE Jul 5** (run_gate passed/total + first-fail stage).: self-test returns passed/total ∈ [0,1]; repairs accepted only
      on strict improvement; keep best-so-far. EvolVE's "functional gradient": halved
      nodes-to-solution, −60% output tokens (= our tiebreak). (0.5h)
- [x] **1.2 Structured stimulus generation** **DONE Jul 7, differential form** (agent/stg_diff.py: LCG random+burst stimulus, dual-SoC trace diff; catches FIFO_DEPTH sabotage tb_selfcheck passes 30/30). (EvolVE STG, LLM-free): regex-classify skeleton
      signals {clock/reset, control, datapath}; control width ≤8 → exhaustive 2^w sweep;
      wider → constrained-random; datapath → random + corner seeds (0, max, alternating).
      Pure generator script, zero tokens. (3-4h)
- [ ] **1.3 Spec-derived checkers** (AssertionForge): two cheap calls — (i) NL test plans as
      `SIGNAL: behavior` lines from YAML, dedupe; (ii) mechanical conversion to iverilog-safe
      `always @(posedge clk) if (...) $error` checkers with HARD constraint "USE ONLY THESE
      SIGNALS: {yaml ports}" (their #1 failure = hallucinated signal names — we eliminate it
      deterministically). (3-4h)
- [x] **1.4 Structural graph diff** **DONE Jul 7, regex form** (validators.structural_diff: census/dangling/irq-reach/fabric/bridge; 8/8 sabotage suite in test_structural.py).: NetworkX graph from YAML (intended: has_port/connected_to/
      generatesInterrupt) vs PyVerilog-extracted graph of generated+stitched RTL (actual);
      diff = TB-independent stitch-error catcher. Reuse patterns from NVlabs/AssertionForge
      `rtl_kg.py`/`rtl_analyzer.py`. (4h)
- [x] **1.5 Python behavioral model per IP** **ALL 20 DONE Jul 8** (agent/ref_models.py: cycle-stepped, library-bug-faithful, trace-anchored predict, calibrated 0-mismatch vs golden; ip_models.py adds the other 12, validated 12/12 lockstep vs library RTL by test_ip_models.py; found LIBRARY BUG #3: dma_engine RTL doesn't compile -> patch_library_rtl fixup). — (Spec2RTL "higher-level executable reference"):
      from YAML — register map r/w, reset values, IRQ set/clear — generates expected-value
      vectors for deep-behavior tests (wdt 2-stage timeout, gpio edge-IRQ, UART serialization:
      exactly our known coverage gaps). (4h, incremental per IP)
- [x] **1.6 Stage-decomposed test order** **DONE Jul 5** (tb_selfcheck v2 STAGE banners, first-fail reporting). (SLDB Configure→Load→Compute→Store analog):
      reset → register access via bridge → peripheral function → interrupt path; report FIRST
      failing stage (= repair router's signal). (1h)

## Phase 2 — Spec inference quality (the untested half) ~10h

- [ ] **2.1 YAML schema v2** (SpecAssess 5 dimensions): per IP require `intent`,
      `ports[{name,dir,width,semantics}]`, `function`, `clocking{edge, reset{...}}`,
      `connections`; plus `pertinent_references` per inferred fact (diagram/skeleton evidence
      cite — Spec2RTL; makes repair routing tractable). (2h)
- [ ] **2.2 Round-trip validation** (SpecAssess RR): fresh context (NO diagram) renders YAML
      back to architecture description + port list; diff vs skeleton + diagram facts; anything
      not surviving the round trip → re-infer that field. LLM-judge self-review is BANNED as a
      gate (judges give 0.9 to reconstruction-0.0 specs). (3h)
- [ ] **2.3 Diagram measurement loop** (SpatialClaw/VISER): parse HTML DOM symbolically FIRST;
      vision only as cross-check; crop/zoom per block, enumerate blocks sequentially (binding
      problem → miscounted instances / mis-wired buses). Fuzzy signal matcher with active-low
      awareness (rst/rst_n/RESET_B, Levenshtein ∝ length) for label↔port binding. (4h)
- [ ] **2.4 Ambiguity policy**: 3-5 DIVERSE YAML hypotheses (each conditioned on previous to
      force diversity — EvolVE IGR), scored by validator+structural checks, argmax; 3-sample
      majority vote on error-prone scalar fields (bus widths — MAKER). Explicit "unsure" path
      instead of silent guessing. (2h)

## Phase 3 — Repair loop ~8h

- [ ] **3.1 Four-path repair router** (Spec2RTL, −52% interventions in ablation): Analysis call
      classifies failure → (i) YAML wrong (diagram misread — check pertinent_references),
      (ii) generator parameterization wrong, (iii) stitcher/port-map wrong, (iv) unknown →
      conservative default. Fix routed to that stage only; never regenerate whole design
      (field/subtree-level re-prompt). (3-4h)
- [ ] **3.2 Learned-constraints block** (Spec2RTL prompt optimizer): after any successful
      repair, append the constraint ("APB PREADY registered"; "reset active-low named rst_n")
      to a persistent prompt block — compounds into Medium/Hard tiers. ACE playbook mechanics
      (IDs, counters, deterministic merge, no full rewrites). (2h)
- [ ] **3.3 Consolidated error feedback**: batch ≤5 failure instances per repair call,
      consolidate error TYPES first (AutoHarness); RLAC-style critic names top-3 likely
      failure modes per module (reset polarity, off-by-one width, handshake) → targeted checks
      before broad ones. (1h)
- [ ] **3.4 Port-contract index** (DeepCode): stitcher works from explicit index of generated
      IPs + port contracts, never raw-context re-reads. Bridge/fabric first in risk ranking:
      standalone smoke-sim (one APB write+read through bridge alone) before full-SoC stitch —
      SLDB failures cluster at protocol handshake boundaries. (2h)
- [ ] **3.5 Budget tracker** (BATS block) + token discipline: invest in check quality, not
      retries — every avoided retry is tiebreak margin. (1h)

## Phase 4 — Medium/Hard readiness
- [ ] **4.1 Pattern compilation** (PreAct): verified spec pattern for an IP class → compiled
      into deterministic library; repeat IPs cost zero LLM calls.
- [ ] **4.2 Generic interconnect stitcher** (strategy lever L5 from NXP log) informed by SLDB's
      10 golden DMA wrappers (Apache-2.0: harvest as foreign port lists to stress-test the
      port-exactness differ + stitcher; analogy not drop-in — tile/NoC vs our memory-mapped
      peripherals).
- [ ] **4.3 GEPA two-module split** offline when ledger exists: diagram→YAML module +
      YAML-repair module, round-robin, Pareto-per-design selection.

## Known failure modes to test against (from papers)
Reset polarity/sync (both papers); DMA/bus handshake state transitions; signal-port mapping
errors; weak self-tests blinding the repair router (Spec2RTL's reported failure — our 14-check
suite must grow first); performance degradation with long context (fold history).
