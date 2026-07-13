# DAC-DAY RUNBOOK — Jul 26 (hidden testcases released; agents updatable until EOD)

Premise (organizer email Jul 12): testcases drop ON the day; we iterate live. Our edge =
fast loop (NXP solve 42 s; NVIDIA round ~2 min) + oracles that need no golden knowledge.
Unlimited-Gemini GCP account from Jul 19 (else .env keys).

## 0. Pre-day checklist (do by Jul 25)
- [ ] Laptop: Docker image present, ASAP7 extracted, iverilog, google-genai, keys in .env.
- [ ] Both regression suites green that morning (5 min): nxp stub e2e + tests; nvidia
      test_cold_start + test_model_iface + discover --validate.
- [ ] `git pull` contest repos EARLY; diff for runner/AGENT_GUIDE/library changes —
      especially rtl_gen_lib (our schema/exemplar extraction adapts automatically, but
      CHECK the three known bugs: if dma cfg_rdata got fixed, our patch no-ops safely).
- [ ] Hotel wifi fallback: phone hotspot tested.

## 1. NXP hidden testcase triage (per testcase)
1. Locate new problem dir (docs/, tb skeleton, maybe new tier name). Read info.json if
   runner-driven; else point dev mode at it.
2. **Dry run first (0 tokens):** `python3 nxp_agent.py --model stub` won't apply to a new
   architecture — instead run the gates standalone: skeleton parse (port_contract input),
   `required_params_table` output sanity, tier detection.
3. Real run: `python3 nxp_agent.py <info.json> --model gemini-3-flash-preview`
   (or dev: `--model vertex`). Expect: schema-guided YAML → 8?/N generated → gates.
4. Read the ledger + typed errors. Failure routing:
   - generator rejections persist → check required_params_table picked up NEW ip_types
     (it auto-extracts; verify the new generator files are globbed).
   - stitch violations oscillate → check module_interfaces made it into the prompt
     (interface index size vs prompt cap); raise slice caps if the SoC is bigger.
   - compile OK but no self-check TB for the tier → rely on KAT-MODEL oracle:
     `python3 kat_engine.py --gen-smoke` needs easy-tier addresses — for a NEW map,
     regenerate the vec program from the inferred YAML address map first (params plumb in).
   - Multi-clock tier → reset_lint may false-positive (single-net assumption): use
     `--no-strict-reset`? (NOT IMPLEMENTED — if hit, relax reset_lint by hand, one line.)
5. Iterate ≤3 real runs before stepping back to analyze raw responses (ledger/raw pattern
   from NVIDIA applies — add dump if needed).
6. Budget guide: easy-like tier ≈ 2-6 calls/run. Keep a per-testcase call tally.

## 2. NVIDIA hidden testcase triage (per IP)
1. `python3 -m ppa.discover --ip <repo-relative-path>` — verify sources/clocks/resets/gate
   look sane. If discovery misses (new conventions), hand-write an IPSpec entry (10 min).
2. Fresh baseline: `python3 -m ppa.evaluate --ip <path> --baseline` (Docker). Sanity: cells,
   WNS, gate runner exists.
3. Bounded first campaign:
   `python3 -m ppa.controller --ip <path> --rounds 3 --k 3 --model vertex --max-calls 20 \
        --emit-best ../submission/<name>`
4. Read round ledger: if 0 parsed candidates → check raw dumps (format drift) before
   burning more calls. If gate-fails dominate → inspect the gate cmd discovered.
5. Escalation ladder (unlimited quota): more rounds; k=4; try --model-name gemini-3-pro
   for proposals; targeted tags via playbook.
6. ALWAYS finish each IP with --emit-best so a submission artifact exists at any cutoff.

## 3. Timeboxing (competition hours H0..H8, adjust to schedule)
- H0-H1: pull, regressions, read ALL released testcases, rank by expected value
  (NXP easy-like first: fastest verified points; NVIDIA small IPs before big trees).
- H1-H4: first pass over every testcase (breadth > depth) — bank best-effort everywhere.
- H4-H7: depth on the 2-3 highest-leverage cases.
- H7-H8: freeze, emit-best everywhere, verify manifests, submit, snapshot ledgers.

## 4. Panic modes
- Vertex down/quota: swap GEMINI_API_KEY (AI Studio) — auto-detected; or organizer GCP acct.
- Docker breaks: baselines only via host? NO — synth needs container; rebuild image from
  Dockerfile (~20 min) — do NOT debug tools during comp hours, rebuild.
- TCC/file-access outage (hit us 3×): toggle Terminal Documents permission; keep repo copy
  on non-Documents path as backup workspace (e.g. ~/dac_backup, rsync'd Jul 25).
- Model returns garbage repeatedly: drop temperature to 0, raise thinking_budget to 16384,
  single-rung rounds (k=1) with the strongest tag.
