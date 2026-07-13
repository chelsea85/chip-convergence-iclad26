# NVIDIA optimize_agent.py — UPGRADE SPEC (from deep-read research, 2026-07-02)

> **STATUS 2026-07-12 — submission-ready (stub-validated); Vertex live-fire pending key.**
> Jul-11/12: cold-start drill 6/6 (test_cold_start.py; FOUND+FIXED discovery keying bug —
> DESIGN_NAME collision aliased hidden IPs onto known baselines); model iface 13/13
> (test_model_iface.py; EXPRESS_MODE_KEY|GEMINI_API_KEY auto-detect, EndpointModel fallback,
> 429+5xx retry); --emit-best drop-in artifact + manifest (banked sha512 ADP 0.787 emits from
> pool); evaluate/verify/sta_feedback CLIs free-form w/ auto-discovery.
>
> **STATUS 2026-07-03 — core build DONE, validated end-to-end (stub).**
> New package `agent/ppa/`: config, workspace (parallel per-candidate copies,
> repro exact baselines), verify (5-layer; exp1+exp2 formally PROVEN, sabotage
> caught), evaluate (proxy stat+ltp pre-filter, parallel workers, ledger,
> 3 sha512 candidates in 31s), objective (3 modes + ADP + frontier; exp2 ADP
> ratio 0.787), sta_feedback (distinct endpoints via -group_path_count patch;
> sha512 tagged arith-carry-chain 5/5), skills (20-bullet seeded playbook),
> pool (Thompson/Beta), proposer (ladder v0-v6, Alpha-RTL template,
> Stub/Vertex), controller (budget regimes, plateau, round ledger).
> Stub e2e: baseline→exp2 accepted (ADP 0.787), deepen-mode reselect, clean
> stop. Legacy `agent/optimize_agent.py` superseded.
> **Still open:** 0.3 netlist audit, 0.5 self-debug retry loop, 2.3 reflector
> LLM call, 2.4 history folding, 4.1 GEPA, 4.2 policy-as-code, OpenTitan IPs
> in IPS registry (workspace subtree strategy), knob-override measure mode.

Implementation-grade task list distilled from Dr. RTL (2604.14989), Alpha-RTL (2606.05253),
Self-Evolved ABC (2604.15082, organizers' group), RTLScout (2606.06530), Pluto (2510.14756),
Agent Factories (2603.25719), Config-Over-Selection (2604.17102), TimingLLM (2604.23602),
GEPA (2507.19457), AB-MCTS (2503.04412), ACE (2510.04618), EFC (2605.29682), BATS (2511.17006),
AutoHarness (2603.03329). Full context: ../RESEARCH_NOTES.md.

**Strategic headline:** Alpha-RTL Table 4 — EVERY published method scored ZERO on async_fifo
(no compilable+correct rewrite; Yosys infers different synchronizer structures across flows).
We already have a gate-passing variant (exp1). async_fifo is a DIFFERENTIATOR IP, not
"low headroom" — bank any verified improvement there.

---

## Internal metric (DECIDED)

- **Headline: baseline-normalized Area-Delay-Product ratio** (organizer group's own headline
  metric), functional + equivalence gated. Track alongside: Pluto-style linear per-metric score
  and raw ratios (robust to weighted-sum/geomean variants).
- **Power: ratios under our own flow ONLY** (OpenSTA absolute power median error 31% cross-flow;
  area 0.6%, delay 8.2%). Lead with area/delay.
- **Candidate selection score (Dr. RTL, drop-in):**
  `Score = 0.5·WNS_n + 0.35·TNS_n + 0.15·Area_n + (0.5 if Area_n > 0.10)` where
  `X_n = (X_cand − X_base)/X_base`, lower better; select argmin among equivalence-passers;
  all fail → carry current design forward unchanged.
- **Staged partial-credit reward (Alpha-RTL) for ranking failures:**
  `r = 0.1·r_syn + 1.0·r_func + 10.0·(M_base/M_cand)`, `M = A·D` (·P optional),
  `r_syn = 1/(1+n_err)` (×0.3 if port-binding errors), `r_func ∈ {0,1}`.
- **Keep a Pareto frontier of variants per IP** — submission-time pick per final published metric.
- Log calls+tokens per candidate so any cost-penalty variant is recomputable.

## Phase 0 — Gate hardening (FIRST; protects every point) ~8h

- [ ] **0.1 Equivalence gate** after TB pass: yosys `miter`+`sat`/eqy where tractable; fallback =
      3-level sim gating (behavioral sim + post-synth gate-level netlist sim, same vectors —
      RTLScout). ANY mismatch → immediate reject (ABC paper rule). (3-5h)
- [ ] **0.2 TB integrity**: TB/test files read-only; diff-check candidate touched only the IP's
      RTL dir (revert-scope fix already done — extend to proposals). (1h)
- [ ] **0.3 Netlist sanity audit** on accept: cell-count/FF-count delta plausibility; flag
      suspicious wholesale logic disappearance. (1h)
- [ ] **0.4 async_fifo CDC rules**: prompt-level constraint block — never restructure
      2-FF synchronizers, preserve gray-code single-bit-change property; conservative variants
      only. (1h)
- [ ] **0.5 Self-debug on compile fail**: feed iverilog/yosys stderr back, ≤3 retries, doesn't
      count as full iteration (ABC paper). (1-2h)

## Phase 1 — Loop core ~14h

- [ ] **1.1 STA-localized feedback** ⭐ biggest quality lever (Dr. RTL ablation 21%→9% without):
      parse `report_checks -path_delay max` top-k paths → startpoint/endpoint registers +
      cell chain → map to RTL signals (pre-flatten names) → root-cause tag ∈ {comb-depth,
      high-fanout, control-data-coupling, reconvergent, wide-compare, mux-heavy, FSM-decode}.
      Feed (endpoints, slack, tag) to LLM, not raw reports. (4-6h)
- [ ] **1.2 Design-state pool + adaptive parent sampling** ⭐ (Alpha-RTL ablation: +32pp ADP vs
      no-reuse): keep every gate-passing variant with reward; sample parent via AB-MCTS-A(Beta):
      each node/GEN keeps Beta(1+Σr, 1+Σ(1−r)), Thompson sample, argmax; GEN=new strategy from
      node, child=repair that diff. r = 0 on gate fail else 0.5+0.5·clip(gain/target,−1,1).
      ~80 lines, no MCMC. Pays off from ~16+ calls/IP. (5-8h)
- [ ] **1.3 Best-of-N=3-5 via strategy ladder** (Agent Factories v0-v6, structured diversity >
      temperature): v0 conservative micro-opt / v1 balanced-tree reassociation (P2) / v2 CSA
      3:2-compressor (P2b) / v3 resource-share + FSM-recode / v4 arithmetic-architecture swap
      (Wallace/Dadda/CSA × Kogge-Stone/Brent-Kung/Sklansky/sparse-KS) / v5 retime-pipeline
      (ONLY TB-latency-tolerant IPs: sha512 confirmed) / v6 fanout/replication. Lineage
      diversity: parent and own child never in same comparison group. (3-4h)
- [ ] **1.4 Cheap pre-filters** before synth: (a) legality lint (ports unchanged, no latches,
      synthesizable subset); (b) yosys proxy `stat` + `ltp` (<1s: cells + longest topo path) —
      full synth only if depth/cells improved-or-noise; (c) ℓ2 bag-of-gates fingerprint — skip
      synth on near-duplicate candidates. (3h)

## Phase 2 — Knowledge & context ~9h

- [ ] **2.1 Design dossier**: first call generates structured Markdown profile (hierarchy, FSMs,
      CDC, arithmetic blocks, fragile regions) injected into all prompts. ABC paper spent 68% of
      tokens here and credits reliability to it; Markdown > prose. (2-3h)
- [ ] **2.2 Skill library** (~15 seed entries, ACE playbook format):
      `- id/section(timing|area|power|pitfall|AVOID)/helpful/harmful/content`.
      Seeds: our P1-P5(+P2b); Dr. RTL patterns→strategies (deep FSM decode→condition
      pre-computation; high-fanout→signal replication; wide compare→restructure; mux-heavy→
      selective register insertion; reconvergent→logic simplification); Alpha-RTL LZA case
      (wide casez priority chain → hierarchical 4-bit group-encode: −40% delay −32% area);
      RTLScout lessons ("named wire cut-points help Yosys partition"; "mux chain beats barrel
      shifter for index ≤11"); AVOID: rebalancing already-optimized logic; moving control
      updates across registers. Retrieve by 1.1's root-cause tag. (3h)
- [ ] **2.3 Reflector + deterministic curator** (ACE): after each accept/revert, one LLM call →
      lessons + helpful/harmful votes on cited bullets; curator merges deltas WITHOUT LLM
      (append new-ID, increment counters, embed-dedup >0.9 cosine). NEVER full-rewrite the
      playbook (context collapse: 18k tokens→122 tokens documented). EFC-gate promotion: only
      verified, novel, plan-changing events become bullets. (3h)
- [ ] **2.4 Context folding**: prompt = dossier + playbook hits + current RTL module/cone +
      last iteration verbatim + older iterations as one-line ledger entries. (2h)

## Phase 3 — Budget control ~6h

- [ ] **3.1 BATS budget block** after every tool result:
      `<budget>LLM calls used/left; tokens used/left; synth runs left. Make the best use of
      available resources.</budget>` + regime policy: ≥70% left → k=3-5 diverse ladder rungs;
      30-70% → k=2 refinements of frontier; <30% → single conservative tweak; <10% → stop, lock
      best accepted. Tracker alone ≈ +2pp in their ablations. (2h)
- [ ] **3.2 Plateau/pivot controller** (Alpha-RTL P2-P4 + EFC stop rule): best-so-far with
      Δr_min=2%; no improvement over W=3-5 rounds AND diverse candidates → stop IP (return
      best); candidates near-identical → switch strategy family; one dominates → exploit it.
      Repeated-attempt discount 1/(1+0.35·A) on (module,strategy) hashes. (2-3h)
- [ ] **3.3 Decoding config + routing**: temp 0-0.4, top_p 0.4-0.7 single-shot; diversity from
      k samples not temperature; ~25-call mini-sweep on OUR IPs when Vertex lands (configs
      don't transfer, Spearman ≈ 0). Cheap-model routing with escalation on plateau — CAUTION:
      Dr. RTL model scaling (Opus 21% / Sonnet 12% / Haiku 3% WNS; SEC 86/73/57%) — weak models
      break equivalence; route only mechanical repairs down. (1h + sweep later)
- [ ] **3.4 Prompt template** (Alpha-RTL, verbatim-proven on our toolchain): reference code +
      measured PPA + "produce functionally correct implementation with PPA-product lower than
      {M}" + feedback block with prev→current M and delta. (1h)

## Phase 4 — Offline (stub-testable now, tune when Vertex lands) ~12h

- [ ] **4.1 GEPA offline prompt evolution** from accept/revert ledger: b=3 minibatches,
      Pareto-per-IP candidate pool (sample ∝ instance-win count — greedy selection stalls after
      ~1 iter, +6.4% from Pareto), cheap minibatch acceptance gate before full re-eval, merge
      cap 5. Feedback text = structured STA/yosys diagnosis (needs 1.1). (6-10h)
- [ ] **4.2 Policy-as-code** (AutoHarness): parameterized scripts for mechanical transforms
      (VT/ABC_AREA knob sweeps once L4 resolved, pragma/attribute toggles) — zero runtime LLM
      calls. (4h)

## RTL work plan (parallel to agent work)
1. sha512 W-schedule P2 (`sha512_w_mem.v:200`, safe) → 2. sha512 pipelining variant (TB
   handshake-tolerant; separate frontier entry) → 3. ascon permutation round (first OT example)
   → 4. async_fifo conservative variant (differentiator; exp1 + lookahead sharing) → 5. aes
   S-box/MixColumns → 6. kmac (after ascon pattern proven) → 7. NVDLA baseline (#7), env.sh
   knobs (#8).

## Calibration numbers to remember
Expert headroom ≈ 19-23% per metric (Pluto); our sha512 P2 already exceeds it on delay.
Dr. RTL: K=10 iters × N=5, ~$50/20 designs, EDA-bound. Agent Factories: median 5.8M tokens/run
= ceiling to stay FAR under. eff@1 ≈ 0.8-0.95 × pass@1. Delay hardest for LLMs — our catalog
is the edge.
