# Chip Convergence — ICLAD-DAC 2026 GenAI Chip Hackathon — Project Summary

**Purpose of this file:** a complete handoff for a reviewing agent. It describes what was built
across all three contest tracks, the results (with exact numbers), the architecture, the key
decisions and findings, where the evidence lives, and the honest status of each track.

- **Team:** Chip Convergence (solo — Harikrishnan KC), Cloud track.
- **Submission repo:** `github.com/chelsea85/chip-convergence-iclad26` (a curated mirror of the
  working tree; refreshed by `sync.sh`). Working tree root: `~/Documents/Hari/DAC_2026_hackathon/`.
- **Contest materials (read-only):** `ICLAD-Hackathon-2026/problem-categories/` — cloned/symlinked
  into the repo root; agents locate it by relative path.
- **Deadline:** Jul 15 23:59 AoE (~Jul 16 05:00 local). Agents remain updatable through DAC (Jul 26).
- **Model:** Google Gemini `gemini-3-flash-preview` via google-genai. Two keys: `EXPRESS_MODE_KEY`
  (Vertex Express, key1) and `GEMINI_API_KEY_2` (AI Studio, key2; free tier = 20 requests/day).
  Keys live in `.env` (chmod 600, gitignored) — never in the repo or logs.

## The unifying thesis (all three agents)

**Verification-first: tools before tokens; nothing is accepted until measured and proven.** Every
agent (1) runs deterministic tools FIRST to diagnose (zero model tokens), (2) has the model propose,
(3) verifies every proposal with independent gates, and (4) keeps only measured improvements /
eligible outputs. The model is the *proposer*; deterministic tooling is the *judge*.

---

## Track 1 — NVIDIA (RTL PPA optimization)  ✅ strongest results

**Task:** rewrite RTL to improve PPA (area/delay/power) on a Yosys + OpenSTA ASAP7 flow; scored on
functional correctness (existing TBs) then PPA, plus LLM calls/tokens. 7 IPs (async_fifo, sha512,
NVDLA, OpenTitan aes/ascon/kmac/prim).

**Agent:** `nvidia_work/agent/` — the `ppa` Python package. Metric = baseline-normalized
**Area-Delay-Product (ADP) ratio**, functional- and equivalence-gated.

**Architecture (staged coordinate-descent optimizer):**
- `ppa/diagnose.py` — zero-token 3-axis PPA diagnosis: hierarchy-preserved STA (`FLATTEN=0`) attributes
  the worst timing path to source files; per-module area; power proxy; a structure classifier tag
  (arith-carry-chain / mux-select / …). SDC clock period auto-parsed from each IP's own SDC.
- `ppa/controller.py` — the staged loop: per-file cursor (worst file first), k parallel strategies
  (k=6 on stage 1, then 4), lock-and-chain (each stage builds on the best-so-far), proposal-only
  turn budget (default 20; repairs/reflection are OFF-budget). Flags: `--diagnose`, `--grounding
  {on,off,stubs}`, `--focus`, `--fence {on,off}`, `--emit-best`.
- `ppa/proposer.py` — `VertexModel` (auto-detects key by env name), prompt builder, `parse_response`,
  fence logic. `thinking_config` capped (gemini-3 thinks by default and burned 63k thought-tokens →
  empty output; fixed). HTTP timeout on the client (a hung socket once stalled a run 47 min).
- `ppa/evaluate.py` — 5-layer verification: lint → compile → functional TB gate → synth+STA measure →
  yosys-LEC (+async2sync) + dual-instance differential sim. Differential gating for IPs with
  pre-existing pristine-flow issues (kmac/prim sv2v artifacts). `measure_candidate()` for PPA-ranked
  gate-fail repair.
- `ppa/pool.py` / frontier — design pool + Pareto frontier; Thompson-sampling parent selection
  (non-staged) or best-so-far pinning (staged).
- `playbook.json` — 95 entries (45 curated core rules from literature + measured experiments; the rest reflector-learned live during runs).
- Harness: `nvidia_work/harness/{run_gate.sh,measure.sh,registry.tsv}` (mounted into Docker for the
  TB gate + synthesis). **Docker is required** for NVIDIA synthesis.

**Verified results (assurance level stated PER artifact in each manifest's `verification_per_layer`
+ `assurance` fields; artifacts in `nvidia_work/submission/`):**
- **sha512: ADP 0.727** — WNS −97.3 → **+334.6 ps (timing MET)**, area 3984→3968; strategy
  `arith-arch` on `sha512_core`; **FULL 5-layer: lint+compile+TB gate PASS, LEC PROVEN, dualsim PASS**;
  8 calls / ~232k tokens. BEAT our best hand-derived rewrite (0.787). Artifact: `submission/sha512/`.
- **async_fifo: ADP 0.961** — `micro-opt`; **FULL 5-layer (LEC PROVEN + dualsim PASS)**; the IP where
  published LLM methods score 0.
- **prim (`prim_crc32`): ADP 0.605** — slack +181.5 ps, area −6%, power −67%; `restructure-select`;
  6 calls. Assurance = **equivalence+differential** (LEC PROVEN + dualsim PASS; official functional
  gate SKIPPED because the pristine flow has a pre-existing compile issue — NOT a candidate failure).
- **aes:** fenced power −4.3%, unfenced power −6%; both **ADP-neutral (~1.0)**. Assurance =
  **differential-only** (dualsim PASS; LEC INCONCLUSIVE at ~75k cells, gate skipped). Characterized:
  aes timing headroom is in the masked S-box; cycle-exact dualsim bounds it to power wins.
- kmac / ascon: offline candidates + baselines (not live-campaigned). NVDLA: baseline only
  (~950k cells; deferred — each synth ~15 min).

**Key decisions / findings (see `nvidia_work/NVIDIA_DAILY_RUN_LOG.md`):**
- Method A (per-module logic depth) vs Method B (hierarchy-preserved STA) DISAGREE on aes; depth
  would misdirect the campaign → we use STA attribution.
- **Context is a strategy (A/B/C ablation)**: A = target file + other critical files read-only
  (3/6 candidates correct); B = target file alone (1/6, but produced the 0.727 win); C = interface
  stubs (0/5). Adopted A as default; strict scope filter drops hallucinated out-of-scope edits.
- The S-box **fence was our own decision, then removed** — the contest scores tests-pass + PPA only,
  with no security requirement; `--fence` retained as an option (default off).
- Robustness hardening found by live fire: resilient fan-out (one API failure ≠ dead run), HTTP
  timeout, netlist-collapse guard (a candidate that lost half its cells "improves" everything —
  caught at layer 5 then guarded), fence presence→change check, gate-fail/dualsim-fail PPA-ranked repair.

**Toolkit bug found & reported:** aes `generated/all_modules.v` duplicates 84 modules → yosys
redefinition error masked by the run script's success banner (invalidates naive aes baselines).

**Regression status:** cold-start drill 6/6, model-interface 13/13, discovery fixtures 3/3.

---

## Track 2 — NXP (SoC generation from diagrams)  ✅ perfect solve

**Task:** from an architecture HTML (diagrams) + a TB skeleton (top port contract) + `rtl_gen_lib`
(YAML→Verilog generators), infer YAML specs per IP, generate, and stitch `secure_periph_soc`. Scored
on a hidden golden TB (passed/total) + token cost. Runner contract: `python3 nxp_agent.py <info.json>
--model <name>`.

**Agent:** `nxp_work/agent/` — stdlib-only Python + iverilog.
- `nxp_agent.py` — runner contract + orchestration: extract constraints (0 tokens) → model call 1
  (YAML specs) → validators/repair → rtl_gen_lib → model call 2 (stitch top) → contract check →
  verification firewall.
- `validators.py` — port-contract diff (vs TB skeleton), YAML validator, reset lint, structural diff,
  known-library-bug fixups.
- `kat_engine.py` — 79-check known-answer-test vector engine with a DUAL oracle.
- `ref_models.py` / `ip_models.py` — cycle-stepped reference models for all 20 library ip_types,
  transcribed from the generated RTL statement-for-statement (**bugs preserved** — the golden TB is
  built on the same library, so a "first-principles correct" model would fail it).
- `stg_diff.py` — dual-SoC random-stimulus differential.

**Result:** **perfect solve in 2 model calls / 42 s** — self-test 30/30, KAT 79/79 on BOTH oracles,
STG differential cycle-identical to the reference over 3,662 cycles. `default_div=26` inferred
correctly (value appears nowhere in the doc — recovered from library demo exemplars).

**Zero-token extraction:** required-param schema (from generator source `required()` calls), demo
exemplars, module-interface index (from generated RTL headers), doc IRQ-map — all injected as ground
truth so the model doesn't guess.

**Regression status:** offline e2e 30/30 + KAT 79/79 ×2; structural sabotage 8/8; runner contract
6/6; IP models 12/12.

**Toolkit bugs found:** `apb_watchdog` kick never reloads (last-NBA-wins); `dma_engine` generates
non-compiling RTL (`cfg_rdata` wire driven procedurally) — auto-patched behavior-neutrally.

---

## Track 3 — ASU (block DRC repair)  ✅ complete agent + rigorous negative result

**Task:** repair an ASAP7 KLayout `pya` layout script to reduce DRC violations while preserving
connectivity. Scored gated-lexicographic: eligibility (renders + DRC runs AND connectivity preserved)
→ minimize `final_violation_rate` → maximize `repair_rate`. 5 public blocks (Block1/2/3/6/7).

**Agent:** `asu_work/agent/` — stdlib + KLayout `pya`.
- `drc_digest.py` — zero-token DRC report → per-rule findings, classified + matched to the rule library.
- `drc_rules.json` — structured DRC-repair rule library (per-class transform + coupling hazards +
  provenance), grounded in exact `asap7.lydrc` semantics + EDA legalization literature.
- `verify.py` — render + DRC + connectivity measured with the OFFICIAL evaluator's OWN functions
  (imported) → inner-loop numbers identical to the scoring machine.
- `repairs.py` — deterministic geometric fix-passes (grid-snap; the coordinated wide-metal-via fixer
  was tested but regressed and is NOT retained in the shipped agent — see the daily log), emitted as pya
  appended to the ORIGINAL script. Connectivity is VERIFIED per candidate (not preserved "by construction").
- `asu_agent.py` — runner contract (endpoint mode uses info.json model_endpoint) + keep-best loop; baseline
  is the eligible floor (never ships a candidate that regresses final_violation_rate or fails the connectivity check).
- `model_repair.py` — stub/vertex/endpoint models; best-of-N with code-compile validation + render-error
  repair.
- `docker/Dockerfile` — **version-exact KLayout 0.30.1** (the evaluator hard-rejects other versions);
  amd64 image (runs under emulation on Apple Silicon). **The agent runs INSIDE this image.**

**Status:** **repaired all 5 public blocks below FVR 1.0** (Block1 0.730, Block2 0.765, Block3 0.764,
Block6 0.676, Block7 0.682) — eligible AND rendered-connectivity-credible. Environment calibrated
(11/14 DRC rules match the reference report exactly).

**The result (the via-bar repair):** the seeded errors split each via-in-wide-metal landing into a
MULTI-CUT array of minimum vias; every min-via then fails the exact via-width-match rule (V.M.AUX.2/.3
— counts are all multiples of 3). The fix, derived from the exact rule (not guessed): replace each
flagged array with ONE continuous via BAR spanning the metal's length, keeping the minimum via
thickness so the lower metal needs NO widening (which is what sank every earlier grow-via attempt). Its
ends coincide with the metal edges → rule satisfied; no enclosure/spacing cascade. Applied to the
upper routing pairs (V2/M3, V4/M5, V5/M6; device layer V0/M1 EXCLUDED — bars there explode enclosure +
break nets): **all 5 blocks drop to FVR 0.68-0.76, eligible + rendered-connectivity-credible.** The
agent's production keep-best ENFORCES a rendered-connectivity credibility check (net count + conducting
area) so the win is a real physical repair, not an evaluator artifact. Provenance: a review-and-falsify
loop — the metal-neck idea was falsified by exact DRC (net +1, M3.S.4 shoulders); reshaping the VIA
into a bar was the win. Full record in ASU_DAILY_RUN_LOG + ASU_PHASE0_FINDINGS.

**Full experimental record:** `asu_work/ASU_DAILY_RUN_LOG.md` (and `ASU_DAILY_RUN_LOG.md` at root).

---

## Slide decks (Marp) — in `slides/` and mirrored to `docs/slides/`

Six decks, all built to PDF, same 5-act structure + one-picture SVG flow diagram:
- `nvidia_deck` (16 slides) + `nvidia_learnings` (companion)
- `nxp_deck` (14) + `nxp_learnings`
- `asu_deck` (16) + `asu_learnings`
Build: `npx @marp-team/marp-cli@latest <deck>.md -o <deck>.pdf --html --allow-local-files`.

## How to verify (fresh-clone reproduction)

```bash
# clone repo + place contest materials at repo root (git clone or symlink ICLAD-Hackathon-2026)
# NVIDIA (needs Docker):
cd nvidia_work/agent && python3 test_model_iface.py            # 13/13
python3 -m ppa.controller --ip async_fifo --rounds 1 --k 1 --model stub --stub-replay ../exp1_graycomb  # ACCEPT
# NXP (stdlib + iverilog):
cd nxp_work/agent && python3 nxp_agent.py --model stub         # 30/30, KAT 79/79 x2
python3 test_structural.py                                     # 8/8
python3 test_runner_mode.py                                    # 6/6
# ASU (needs Docker + KLayout 0.30.1 image):
docker build --platform linux/amd64 -t asu-klayout:0.30.1 asu_work/docker
docker run --rm --platform linux/amd64 -v <ASU_repo>:/asu -v $PWD/asu_work/agent:/agent \
    asu-klayout:0.30.1 python3 /agent/asu_agent.py <BlockN_info.json> --model none   # eligible
```
NOTE: a prior fresh-clone check caught `nvidia_work/harness/` missing from `sync.sh` (would have
gate-failed every candidate on a graded clone) — now fixed. Always re-verify from a fresh clone.

## Evidence & logs (for auditing claims)

- `nvidia_work/NVIDIA_DAILY_RUN_LOG.md`, `NXP_DAILY_RUN_LOG.md`, `asu_work/ASU_DAILY_RUN_LOG.md`
  — chronological engineering logs with measured numbers and every decision.
- `nvidia_work/agent/ledger/` — per-IP JSONL run ledgers + raw model responses + baselines.
- `nvidia_work/agent/variants/` — persisted accepted RTL variants.
- `nvidia_work/submission/` — emit-best artifacts (repo-layout files + manifest.json with PPA Δ,
  verification, calls, tokens).

## Honest status / open items (for the reviewer)

- **Strongest, scored, in-git:** NVIDIA (0.727 / 0.605 verified) and NXP (perfect solve). These are
  the submission's core.
- **ASU:** complete verification-first agent + a rigorous, reproducible proof that the benchmark's
  dominant violation class is locally irreducible (needs global legalization). Honest negative result,
  not a PPA/repair win.
- **Not done / deferred:** NVDLA live campaign (compute-heavy), kmac/ascon live campaigns (offline
  candidates only), ASU global legalizer (multi-day), transaction-mode dualsim (would unlock aes
  latency-changing wins).
- **Pending at time of writing:** final NVIDIA/NXP slide read-through + submission email assembly
  (decks attached + repo link). All decks build; repo == origin/main; fresh-clone verified earlier.

## Reviewer guidance

Claims to spot-check: the sha512 0.727 and prim 0.605 manifests in `nvidia_work/submission/`; the NXP
2-call solve reproduces via `nxp_agent.py --model stub`; the ASU over-constraint via the daily-log
experimental table. Everything measured is in the logs/ledgers — nothing is asserted without a number.
The design ethos throughout is **correctness over speed**: prove a mechanism works reliably before
moving on; "no-improvement" and honest negative results are reported as first-class outcomes.
