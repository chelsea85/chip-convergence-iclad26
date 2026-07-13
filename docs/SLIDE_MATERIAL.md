# SLIDE EVIDENCE DOSSIER — every number we can cite (as of 2026-07-12)

> Copy into repo root when file access returns. All figures verified in run
> logs / ledgers; citation notes in brackets.

## Team / frame
- Team "Chip Convergence" — solo (Hari), Cloud track, DAC in person Jul 26.
- Two problems: NVIDIA (RTL PPA optimization), NXP (SoC generation from diagrams).
- Agents updatable until end of Jul 26; hidden testcases released Jul 26 (organizer email,
  Vidya, Jul 12). GCP unlimited-Gemini accounts from Jul 19.

## NVIDIA track numbers

Baselines (our flow, Docker yosys 0.63 + OpenSTA, ASAP7; slack ps / cells / area um2):
| IP | area um2 | cells | WNS (ps) | timing |
|----|---------|-------|----------|--------|
| async_fifo | 120.37 | 918 | +22.22 | MET |
| sha512 | 3984.20 | 29307 | −97.30 | violated |
| ascon | 1789.77 | 12295 | −430.14 | violated |
| aes | 10100.51 | 74234 | −848.15 | violated (corrected; shipped −1083.58 was tainted by bug #1) |
| kmac | 13353.81 | 97078 | −1115.75 | violated |

Headline wins:
- **sha512 exp2 (balanced adder trees): ADP ratio 0.787 vs baseline, WNS −97.30 → +235.36 ps
  (timing now MET), area −0.6%, power 2.92→2.23 mW under our flow; yosys LEC PROVEN +
  dual-instance differential sim PASS.** [ledger/sha512_baseline.json, variants pool]
- async_fifo gate-passing + LEC-proven variant exists (exp1) — significant because Alpha-RTL
  Table 4: EVERY published method scored ZERO on async_fifo. [RESEARCH_NOTES §6]
- Live model rounds (Jul 12, gemini-3-flash-preview, Vertex Express):
  - Round A: 1 gate-fail candidate; reflector banked real lesson ("carry-save 3:2 compressor
    insertion → gate-level flow failures"). 4 calls.
  - Round B (post thinking-fix): 3/3 parsed. balanced-tree → REJECTED DUPLICATE (Gemini
    independently reinvented our hand win; fingerprint dedup caught it). carry-save →
    gate-fail. **arith-arch → ACCEPT, ADP 0.898 vs baseline, "improves perf, regresses
    none"** — first model-generated verified improvement. 4 calls, ~112k tokens.
  - Rounds C/D (deepen): **restructure-select ACCEPTED on top of arith-arch (ADP×0.985 →
    ≈0.884 composed)** — cross-round composition via Thompson parent sampling. 7 calls,
    ~203k tokens.
  - Global best remains exp2 (0.787); --emit-best correctly emits it with manifest.
- Verification stack: 5 layers — lint → iverilog compile → IP testbench gate → yosys LEC
  (+async2sync for CDC) → dual-instance differential simulation. Candidates only accepted
  after ALL layers (full_verify=True at acceptance).
- Hidden-testcase readiness: auto-discovery onboards unknown IPs from repo conventions
  (fixtures 3/3 MATCH vs hand registry; aes/kmac/prim/NVDLA onboard zero-config); cold-start
  drill test_cold_start.py 6/6 — incl. the found+fixed DESIGN_NAME-collision bug that would
  have scored hidden IPs against wrong baselines.
- Learned playbook (ACE-style): 23 bullets incl. measured AVOID rules ("ABC absorbs local
  restructuring; only global algebraic changes survive" — from exp3/exp4 measured no-ops)
  + 2 live-learned lessons.
- Token discipline: budget regimes (70/30/10), plateau stop, proxy pre-filter, exact-
  fingerprint dedup (saved re-synthesis when Gemini duplicated exp2).

## NXP track numbers

- Pipeline: diagram HTML → [model] YAML/IP → rtl_gen_lib → [model] stitch top → gates.
- **PERFECT SOLVE (Jul 12, attempt 5): 2 model calls, 42 s end-to-end. 8/8 specs generated,
  top contract-clean on attempt 1, self-test 30/30, KAT(golden-record) 79/79, KAT(model-
  oracle) 79/79, STG differential MATCH — 3,662 cycles, 0 differing vs hand-built reference
  (cycle-identical).** Even default_div=26 inferred (value absent from the doc; recovered
  via library-demo exemplars).
- Debug arc (5 attempts, each fix deterministic tooling):
  1. 5/8 specs missing required params, silent generator failures → typed generator-error
     feedback loop (the library's MissingParameter messages are LLM-directed by design).
  2. Model repeated omissions → required-params schema AUTO-EXTRACTED from generator source
     into prompt (prevention > repair); multi-doc YAML splitting.
  3. 8/8 generated; stitch guessed port names (irq_sources vs irq_src) → module-interface
     index (exact generated headers in prompt; DeepCode port-contract pattern).
  4. Working SoC, GATE 30/30, but KAT caught param divergence (div=1 vs 26) + IRQ bit-order
     swap → demo exemplars + doc IRQ-map extraction. KAT golden 68/79 / model 69/79.
  5. Perfect (above).
- Correctness stack (all validated by sabotage suites):
  - port_contract / yaml_validator / reset_lint / structural_diff (census, dangling ports,
    IRQ reachability, fabric hang-off, bridge bus) — 8/8 sabotage catches.
  - 30-check staged self-test TB (reset→rw→function→irq→watchdog→privilege).
  - KAT engine: 125-command vector program, 79 checks; TWO oracles — golden-record AND
    cycle-stepped Python reference models (calibrated 0-mismatch vs golden; trace-anchored).
    Catches FIFO-depth sabotage invisible to the 30-check TB (status 0x89 vs 0x88 = tx_full).
  - STG dual-SoC random-stimulus differential (LCG + index-scheduled bursts).
- **Reference models for ALL 20 library ip_types** — easy-8 calibrated 0-mismatch; other 12
  validated 12/12 in 2000-cycle lockstep vs library RTL (AES-128 bit-exact ≈150 blocks) —
  the medium/hard hedge + hidden-testcase oracle (needs no golden).
- Runner contract: python3 nxp_agent.py <info.json> --model <name> — 6/6 e2e vs mock
  endpoint implementing the contest protocol. Stdlib-only (eval env = python3+iverilog).
- Token efficiency: perfect solve = 2 calls (scoring tiebreak).

## Contest bugs found (3) — evidence of depth
1. NVIDIA aes: generated/all_modules.v duplicates 84 modules → yosys redefinition ERROR
   masked by run_syn.sh success banner; shipped baseline invalid (−1083.58 → clean −848.15).
2. NXP apb_watchdog: kick reload ctr<=ld1 overridden by later ctr<=ctr-1 (last-NBA-wins) —
   kick NEVER reloads. Our TB + models assert actual library behavior.
3. NXP dma_engine: generated RTL does not compile (cfg_rdata output wire driven from
   always@(*), gen_axi_ips.py:115) — agent auto-patches (behavior-neutral wire→reg).

## Live model findings (transferable, differentiating)
- gemini-3-flash-preview thinks by default: 62,913 thought tokens → EMPTY response
  (finish=MAX_TOKENS, 0 parts). Fix: max_output_tokens=65536 + thinking_budget.
- Token accounting must use total_token_count (thoughts billed).
- ~2/3 of responses ignore output-format instructions → module-name-based fence parsing.
- Raw response archiving (ledger/raw/) for postmortems.

## Research grounding (slide credibility)
~586-paper survey + 4 deep reads (RESEARCH_NOTES.md). Named techniques implemented:
ACE playbook, Thompson/Beta parent sampling (AB-MCTS-lite), Dr. RTL selection score,
Alpha-RTL prompt shape, EvolVE functional gradient + STG, AutoHarness is_legal,
Spec2RTL repair routing ideas, DeepCode port-contract index, SpecAssess reset findings,
GEPA (pending), organizer-group headline metric (baseline-normalized ADP).
