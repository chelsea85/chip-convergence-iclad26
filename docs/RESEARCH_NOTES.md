# RESEARCH_NOTES — Paper survey + NVIDIA headroom audit (2026-07-01)

Consolidated from 7 parallel research passes: (1) local NVIDIA per-IP audit; (2-5) dair-ai
AI-Papers-of-the-Week sweeps covering Jul 2025 – Jun 2026 (~520 papers screened); (6) deep read of
arXiv 2603.28052 + citation hunt; (7) ICLAD/LAD 2025+2026 accepted papers (66 papers).

---

## 1. Scoring-metric intelligence (biggest open unknown, partially answered)

- **Pluto benchmark (Brown, ICLAD'26, arXiv 2510.14756)** is the best public model of NVIDIA's
  unpublished metric: **eff@k — functional pass as gate, then PPA normalized against a Pareto
  reference implementation.** SOTA LLMs: 78% pass@1 but only ~64-66% area/delay/power efficiency.
  Mine its 114 problems + expert references for patterns that close the correctness→efficiency gap.
- **Self-Evolved ABC (Cunxi Yu + Haoxing Ren, NVIDIA, arXiv 2604.15082)** — organizers' own group;
  evaluates on **area, delay, AND switching activity**. Read for loop structure + metric hints.
- Local inference stands (Lesson L2): metric almost certainly **relative improvement vs committed
  baseline** (5/6 IPs ship failing timing; aes SDC = physically impossible 10 GHz; baseline reports
  committed in-repo under `syn_results/`).
- Organizer taste (from their papers: Spec2RTL-Agent, HeaRT, AssertionForge, Multimodal PD
  Assistant): structured intermediate representations, tree-structured agentic search, reflection
  loops, tool-grounded feedback, "automation degree" as a headline number.
- NXP publishes no papers; their 2025 challenge (netlist ECO repair) emphasized **deterministic
  correctness under a hidden evaluator** — consistent with our neuro-symbolic bet.
- **VeriContaminated** (ICLAD-core authors): public Verilog benchmarks are contaminated → expect
  novel, contamination-resistant hidden designs. Don't overfit to known IP behavior.

## 2. NVIDIA per-IP verdict (audit of logs + RTL, 2026-07-01)

| IP | Baseline | Verdict | Levers |
|---|---|---|---|
| sha512 | −97.3 ps @1500ps, 29307 cells | **Proven win** (P2: +235 ps, −0.6% area) | P2b CSA trees; W-schedule 4-op add (`sha512_w_mem.v:200`); W-mem 16×64 shift→pointer window (~1024 FF); pipelining (TB is handshake-based → latency-tolerant!) |
| ascon | −430 ps, 12295 cells, 38 files | Very likely; **best OT first target** | Permutation round (5-bit S-box + linear layer) P2/P4 |
| aes | −1084 ps, 74034 cells, 76 files | Likely, slow iterations | S-box (Canright GF inversion) + MixColumns reassociation/CSE |
| kmac | −1116 ps, 97078 cells | Likely, most expensive | Keccak θ/χ wide XOR/AND nets; do after ascon pattern proven |
| async_fifo | +22 ps, MET, 918 cells | Marginal | Shared ±1 lookahead incrementer (`wptr_full.v:39-40`, mirrored in rptr_empty); P1 (exp1) for slack |
| NVDLA | uncharacterized | Unknown (task #7) | SDC is relaxed 33 MHz → likely area/power-bound |
| prim | multi-top | Undefined scoring | Wait for organizer clarification |

Key finding: **sha512 TB (`tb_sha512_core.v`) polls `wait_ready()` — handshake-based → pipelining/
retiming likely legal.** aes/ascon/kmac TB latency-tolerance unverified; equivalence-preserving
P2/P4 safe everywhere. Also: env.sh VT/ABC_AREA clobber (L4/task #8) = zero-RTL-risk lever if knobs
are in scope.

## 3. Agent-design upgrades from the literature (ranked, deduplicated)

### NVIDIA optimize_agent.py
1. **Best-of-k cheap proposals + deterministic selection** (Weak-Model Boosting 2605.14163; Agent
   S3 2510.02250): k diverse samples from a cheap model, selection by sim/yosys/OpenSTA — cost
   scales with model size, not call count. Force diversity via distinct transformation directives
   per sample (Diversity Collapse 2604.18005); N≈4-10.
2. **Harden the accept gate against reward hacking** (School of Reward Hacks 2508.17511; Anthropic
   emergent-misalignment; One Token to Fool 2507.08794; SAGA 2512.21782; InfCode 2511.16004):
   yosys `equiv_*`/SAT or randomized regression beyond provided TB; TB files read-only; diff-check
   nothing touched test infra; netlist-sanity audit of *how* score improved; optionally generate
   adversarial extra stimuli per rewrite. LLM judges advisory only (Reliability w/o Validity
   2606.19544; TIR-Judge 2510.23038).
3. **Feedback quality per token is THE lever** (EFC scaling laws 2605.29682, R²=0.99; Meta-Harness
   2603.28052 ablation: raw traces beat summaries by 15 pts): full artifacts greppable on disk;
   distilled deltas in prompt ("area −3.2%, WNS +12ps, worst path: …"); persistent accept/revert
   ledger. Structured *diagnosis* not PASS/FAIL (PDDL-Instruct 2509.13351; Auto-Diagnose
   2604.12108). Two-tier context folding: last iter verbatim, older iters one-line (AgentFold
   2510.24699; Context Rot).
4. **Population + skill library, not greedy chain** (AlphaEvolve 2511.02864: show 2-3 diverse
   high-scoring ancestors as inspiration; Dr. RTL 2604.14989: 47-entry pattern→strategy library →
   21% WNS gains; Memento 2508.16153; ArcMemo 2509.04439; RTLScout 2606.06530 elite pool). Make
   OPTIMIZATION_CATALOG machine-readable; store accepted rewrites as (pattern, transform, PPA Δ);
   retrieve into prompts. ACE (2510.04618): maintain playbook via incremental delta updates, never
   full rewrites (context collapse).
5. **Budget-aware, persistent control loop** (BATS 2511.17006: inject "~N proposals left" into
   every prompt, explore early/exploit late; AutoLab 2606.05080: persistence is the #1 predictor —
   never stop while budget remains, keep best-so-far checkpoint; AB-MCTS 2503.04412: wider-vs-
   deeper decision from feedback; TUMIX 2510.01279: stop a module when marginal PPA/token drops).
6. **Cheap pre-filters before expensive verification** (AutoHarness 2603.03329: static legality
   gate — non-synthesizable constructs, port changes, latch inference — before any synth cycle;
   TimingLLM 2604.23602: heuristic pre-synthesis timing estimate (register-to-register logic
   depth, operator counts) to kill bad candidates early; DeepConf 2508.15260: early-abort signal
   pattern).
7. **Model routing + decoding config** (AdaptEvolve 2602.11931: cheap model default, escalate on
   plateau, −38% cost; Configuration Over Selection 2604.17102: temp/top-p tuning beats model
   choice, up to 25.5% pass-rate spread — but configs don't transfer across benchmarks, tune on
   OUR RTL; VeriDispatcher 2511.22749).
8. **Offline harness/prompt tuning, deploy frozen** (Meta-Harness; GEPA 2507.19457: reflective
   prompt evolution, 35× fewer rollouts than RL; AutoTTS 2605.08083: tune control policy offline
   against logged runs; SkillOpt 2605.23904). Search on practice IPs before scored runs.
9. **Structure each iteration** (Kimi-Dev 2509.23045; VeriDebug 2504.19099): fixed sub-steps —
   localize hotspot from STA report → targeted edit → verify. Localization separate from
   correction. Only send the module + logic cone being rewritten (context-wall principle,
   Yale ICLAD'26).
10. **Cap deliberation** (Inverse Scaling 2507.14417): several short tool-grounded iterations beat
    one giant reasoning pass.

### NXP nxp_agent.py
1. **Per-step verifier gating** (LEAP 2606.03303: <10%→70% by gating every step through the
   compiler): lint/compile/mini-TB each IP as generated, not only the final SoC.
2. **Schema projection + subtree repair** (Auton 2602.23720; STRUCTUREDAGENT 2603.05294): validate
   YAML against strict per-IP schema; re-prompt only failing fields/subtrees, never regenerate the
   whole design.
3. **Measure the diagram, don't ask it** (SpatialClaw 2606.13673; VISER 2506.22146; CodeVision
   2512.03746): tool loop — parse HTML DOM symbolically first, vision as cross-check; crop/zoom
   per block, enumerate sequentially (binding problem causes miscounts/mis-wiring).
4. **Reliability per field** (MAKER 2511.09030: microtask per IP/interface + 3-sample majority
   vote on error-prone fields like bus widths; RLAC 2511.01758: cheap critic names 2-3 likely
   failure modes per module → targeted checks).
5. **Self-generated assertions/tests toward golden parity** (AssertionForge 2503.19174, NVIDIA,
   code at NVlabs/AssertionForge: spec+RTL → assertions, ~95% correct; EvolVE 2601.18067:
   structured TB generation; InfCode adversarial test/patch co-refinement; SpecAssess 2512.00045:
   spec is good iff RTL is reconstructible from it — round-trip quality gate for YAML).
6. **Stateful port-contract index** (DeepCode 2512.07921): stitcher works from an explicit index
   of generated IPs + port contracts, never raw context re-reads. PreAct 2606.17929: compile
   verified spec patterns into the deterministic library → zero LLM calls for repeat IP classes.
7. **Architecture validation**: Spec2RTL-Agent (2506.13905, NVIDIA/Haoxing Ren) = published
   sibling of our design (structured plan IR + progressive codegen + reflection that traces which
   stage erred). HiVeGen 2412.05393 confirms per-IP decomposition. SLDB (2507.06376, Columbia) =
   closest public benchmark to the NXP task — practice data for the stitcher.
8. EvolVE split: **MCTS for functional correctness, idea-guided refinement for PPA** — separate
   "get it correct" from "optimize it" phases.

### Cross-cutting validation
General LLM + hard symbolic verifier beats bespoke pipelines (Numina-Lean-Agent 2601.14027, LEAP,
AlphaProof, AutoHarness, Auton). Single agent + persistent conversation beats multi-agent for
cost (OneFlow 2601.12307; Scaling Agent Systems 2512.08296; Talk Isn't Always Cheap 2509.05396).
Frontier models are weak on niche languages like Verilog (Q-language study 2508.06813) → few-shot
priming with idiomatic synthesizable-Verilog exemplars; build a small private eval to pick models
empirically. Expect agents to default to parameter-tweaks over structural rewrites unless prompted
(NanoGPT-Bench) — prompt for structural transformations explicitly.

## 4. Must-read shortlist (in order)
1. Self-Evolved ABC (2604.15082) — organizer group, metric hints
2. Pluto (2510.14756) — likely metric shape + minable problems/references
3. Dr. RTL (2604.14989) — our loop, validated, + skill library
4. RTLScout (2606.06530) — our exact Yosys+ASAP7 stack
5. Spec2RTL-Agent (2506.13905) — NXP architecture validation, NVIDIA-authored
6. AssertionForge (2503.19174) + code — NXP hidden-TB defense
7. Agent Factories for HLS (2603.25719) — general agents do hardware optimization, 7×
8. GEPA (2507.19457) — offline prompt evolution
9. AB-MCTS (2503.04412) — wider-vs-deeper budget allocation
10. Check github.com/masc-ucsc/hagent (Renau, "Are Skills Enough?" ICLAD'26, not yet on arXiv —
    agentic fmax optimization on large chips)

## 5. Prioritized plan (~9 days to Jul 10)

**Model-free now:**
1. Gate-hardening (equiv check, TB read-only, netlist audit) — cheap, protects everything.
2. optimize_agent.py upgrades: best-of-k + diversity, legality pre-gate, attempt ledger +
   distilled deltas, budget-aware loop, machine-readable catalog retrieval.
3. Bank RTL wins by hand: sha512 W-schedule P2 (safe) → sha512 pipelining variant (TB tolerates)
   → ascon permutation round (first OT example).
4. NXP: per-IP verification gates, YAML schema projection + field-level repair, port-contract
   index, self-test expansion toward golden parity (EvolVE/AssertionForge style).
5. Resolve env.sh knob clobber (#8); characterize NVDLA (#7, low pri); read shortlist top 5.

**When Vertex Express Mode lands** (try self-signup per AgentSetup.md FIRST): real inference runs;
tune k, routing thresholds, decoding config on practice IPs offline; GEPA-style prompt evolution
from the accept/revert ledger.

---

## 6. DEEP-READ RESULTS (2026-07-02) — see the two implementation specs

Four deep-read passes extracted implementation-grade detail (algorithms, formulas, verbatim
prompts, hyperparameters, ablations). Ordered task lists live in:
- `nvidia_work/AGENT_UPGRADE_SPEC.md` (phases 0-4 + RTL work plan)
- `nxp_work/AGENT_UPGRADE_SPEC.md` (phases 0-4 + failure-mode test list)

Facts that changed the strategy:
1. **async_fifo is a differentiator, not low-headroom**: Alpha-RTL (our exact iverilog/yosys/
   OpenSTA stack) — EVERY published method scored 0 on async_fifo (no correct rewrite within
   budget; Yosys synchronizer-structure variance). We have a proven passing variant (exp1).
2. **Metric shape converged**: organizers' group headlines **baseline-normalized area-delay
   product**, formal-equivalence gated, token-conscious (Self-Evolved ABC); Pluto eff@k =
   per-metric linear normalization vs Pareto reference, gated, best-of-k; Config-paper HQI =
   0.5·area+0.5·delay normalized. → our internal metric: ADP ratio headline, Dr. RTL candidate
   score, staged Alpha-RTL reward, Pareto frontier per IP. OpenSTA power unreliable (31% err) —
   ratios under own flow only, lead area/delay.
3. **Two quantified loop levers**: STA-localized feedback (Dr. RTL ablation 21%→9% WNS without)
   and design-state pool + adaptive parent sampling (Alpha-RTL: −13.3% vs −45.3% ADP = 32pp).
4. **Reset semantics = NXP killer #1** (SpecAssess spec-side + SLDB integration-side; LLM judges
   score broken-reset specs 0.9 while round-trip reconstruction gives 0.0). Mandatory YAML
   field + deterministic lint + first test stage.
5. **Fractional self-test score** (EvolVE): halved iterations, −60% output tokens (= NXP tiebreak).
6. **68% of Self-Evolved ABC's tokens went to upfront design profiling** (Markdown dossier) —
   budget for it.
7. Model scaling for equivalence-safe rewrites: Opus 21% / Sonnet 12% / Haiku 3% WNS (SEC pass
   86/73/57%) — cheap-model routing only for mechanical repairs, not creative rewrites.
8. Ready-to-use assets: Dr. RTL score formula; Alpha-RTL prompt template + plateau controller
   thresholds (Table 9); AB-MCTS-A Beta recipe (~80 lines); ACE playbook format; GEPA
   meta-prompt (gepa-ai/gepa repo); BATS budget block + 70/30/10 regimes; EvolVE STG recipe;
   AssertionForge repo (NVlabs) + SLDB wrappers (Apache-2.0) + MetRex (scale-lab) as data.
