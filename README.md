# Chip Convergence — ICLAD-DAC 2026 GenAI Chip Hackathon

Solo team (Hari Krishnan), Cloud track. **Three agents, one verification-first architecture:**

| Track | Agent | Headline result (live gemini-3-flash-preview) |
|-------|-------|------------------------------------------------|
| **NVIDIA** — RTL PPA optimization | `nvidia_work/agent/` | sha512 **ADP 0.727**, WNS −97→**+335 ps (MET), LEC-proven** (agent's live rewrite beat our best hand-derived 0.787); prim **ADP 0.5824** (power −70%, `late-input-cofactor`). Equally important — async_fifo **ships baseline on purpose**: a fully **LEC-PROVEN** 0.961 candidate was withdrawn as a **CDC glitch hazard** that formal and simulation structurally cannot see |
| **NXP** — SoC generation from diagrams | `nxp_work/agent/` | **2 model calls / 42 s, perfect against our full verification stack**: self-test 30/30, KAT 79/79 on both oracles, STG differential cycle-identical to reference over 3,662 cycles (organizer hidden testbench is not in the public checkout, so the official score is organizer-confirmed only) |
| **ASU** — block DRC repair | `asu_work/official_submission/` (v2 Rev3; sources in `asu_v2/`) | **Final-violation-rate 0.374–0.582 on all 7 blocks** (mean 0.477; via-bar-safe + track-shift + v1-patch, derived from the exact rules) — eligible, connectivity-preserved under the published checker, AND **layer-aware electrical partition proven identical** original→repaired; Block4/5 (released Jul 25) scored **blind** = the agent's two best results; version-exact KLayout 0.30.1 env; verify identical to the official scorer; 3-round independent review trail in `asu_v2/reviews/` |

All three agents are verification-first: every model output passes deterministic gates
(equivalence checks, port contracts, structural diffs, known-answer tests, DRC/connectivity)
before anything is accepted. Detailed engineering logs: `nvidia_work/NVIDIA_DAILY_RUN_LOG.md`,
`nxp_work/NXP_DAILY_RUN_LOG.md`, `asu_work/ASU_DAILY_RUN_LOG.md`.

## Setup

1. Clone the contest repo INTO this repo's root (agents locate it by relative path):
   ```bash
   git clone --recurse-submodules \
       https://github.com/ICLAD-Hackathon/ICLAD-Hackathon-2026
   ```
   (or symlink an existing clone: `ln -s /path/to/ICLAD-Hackathon-2026 .`)
2. Tools: python3 (stdlib only for NXP), iverilog/vvp; for NVIDIA synthesis additionally
   Docker (`iclad-dev:v1` built per the contest repo's ENV_PREPARATION.md) + ASAP7 in
   `ICLAD-Hackathon-2026/.../techlib/`; for ASU, Docker + the pinned KLayout 0.30.1 image
   (`docker build --platform linux/amd64 -t asu-klayout:0.30.1 asu_work/docker`).
3. Model access: `pip install google-genai`; export `EXPRESS_MODE_KEY` (Vertex AI Express
   Mode, per AgentSetup.md) or `GEMINI_API_KEY` (AI Studio). See `docs/GEMINI_SETUP.md`.

## Quickstart — NXP

```bash
cd nxp_work/agent
python3 nxp_agent.py --model stub      # offline e2e: expect 30/30 + KAT 79/79 + 79/79
python3 nxp_agent.py --model vertex    # real diagram inference
python3 nxp_agent.py <info.json> --model <name>   # contest runner contract
```

## Quickstart — NVIDIA

```bash
cd nvidia_work/agent
# real campaign (Vertex Express; needs EXPRESS_MODE_KEY + Docker + ASAP7):
python3 nvidia_agent.py --ip sha512
#   -> staged optimizer; writes best VERIFIED RTL (delta) + manifest to submission/sha512/
# offline smoke (no model/network, replays a proven variant):
python3 nvidia_agent.py --ip async_fifo --model stub --stub-replay ../exp1_graycomb
# full control: python3 -m ppa.controller --ip <name> --model vertex --diagnose on ...
```
Each `submission/<ip>/manifest.json` records the true `verification_per_layer` +
`assurance` reached (e.g. sha512 = full 5-layer; aes = differential-only).

## Quickstart — ASU

**Official submission package** (what the organizers run): `asu_work/official_submission/`
— a self-contained, stdlib-only `agent.py` that needs **no KLayout at agent runtime**
(the official image is `python:3.10-slim`; the evaluator renders/scores afterward on the
host). **v2 Rev3 (2026-07-26):** applies the deterministic via-bar-safe + track-shift +
v1-patch repairs; its output is **byte-identical** to the independently re-scored
`asu_v2/submission/Block*_repaired.py` — **FVR 0.393–0.582** (was 0.68–0.76), eligible,
passes the published connectivity checker, AND **preserves layer-aware electrical
connectivity original→repaired exactly** (immutable-anchor partition proof; three-round
independent review + P1-5 official-runner rehearsal in `asu_v2/` — see
`asu_v2/README.md`, `asu_v2/reviews/`, `asu_v2/submission/RELEASE_MANIFEST.json` and
`P15_OFFICIAL_RUN_ADDENDUM.md`). The v1 via-bar-only artifacts remain under
`asu_work/submission/` as history; a layer-aware audit found 49 electrical merges in
them that the published checkers cannot see (documented in `asu_v2/reviews/`), which
Rev3 removes.

```bash
# Official runner (needs Docker + EXPRESS_MODE_KEY for the model-wrapper, though the
# deterministic agent makes no model call):
python3 official_eval/run_official_eval.py --run-id r1 \
    --submission-dir <this_repo>/asu_work/official_submission --agent-entrypoint agent.py
#   -> emits BlockN_repaired.py; the host evaluator scores FVR 0.393-0.582
#      (rehearsed 2026-07-26, run rev3p15: totals 142/35/35/102/444, zero model calls)

# Dev agent (keep-best loop; needs KLayout 0.30.1 image — for local measurement/ablation):
docker build --platform linux/amd64 -t asu-klayout:0.30.1 asu_work/docker
docker run --rm --platform linux/amd64 -v <ASU_repo>:/asu -v $PWD/asu_work/agent:/agent \
    asu-klayout:0.30.1 python3 /agent/asu_agent.py /asu/task/.../BlockN_info.json --model none
python3 asu_work/agent/drc_digest.py <BlockN.drc.json>   # zero-token DRC diagnosis
```

## Running with a real model — the organizer path (verified live 2026-07-15)

Each track is invoked differently by the organizers. Export `EXPRESS_MODE_KEY` first;
these are the exact real-model commands we validated end-to-end (incl. from a fresh
tarball extract):

```bash
# NXP — contest runner starts a Vertex-backed model service; agent runs in endpoint mode
cd <contest>/problem-categories/ICLAD26-NXP-Problems
python3 runner/run_benchmark.py --problem easy \
    --agent <this_repo>/nxp_work/agent/nxp_agent.py --model gemini-3-flash-preview --run-id r1
#   -> 2 model calls, 8 IP .v + SoC top, GATE 30/30 + KAT 79/79 x2

# NVIDIA — NO wrapper; the agent calls Vertex directly (AgentSetup.md). Needs Docker + ASAP7.
cd <this_repo>/nvidia_work/agent
python3 nvidia_agent.py --ip sha512          # staged live campaign -> submission/sha512/
#   the shipped submission/sha512 (ADP 0.7266, full 5-layer) re-synthesizes keyless:
python3 -m ppa.evaluate --ip sha512 --baseline
python3 -m ppa.evaluate --ip sha512 --variant-dir ../submission/sha512/sha512/src/rtl \
    --full-verify --workers 1 --no-proxy     # -> ADP 0.7266, LEC PROVEN

# ASU — the submitted agent is DETERMINISTIC (no model call); official runner scores after:
python3 <contest>/.../ICLAD26-ASU-Problems/official_eval/run_official_eval.py --run-id r1 \
    --submission-dir <this_repo>/asu_work/official_submission --agent-entrypoint agent.py
#   -> BlockN_repaired.py (FVR 0.393-0.582). Runner requires EXPRESS_MODE_KEY even though
#      our ASU agent makes no model call.
```

## Regression suites (all green as of last sync)

| Suite | Command | Expected |
|-------|---------|----------|
| NXP e2e (offline) | `nxp_work/agent$ python3 nxp_agent.py --model stub` | 30/30, KAT 79/79 ×2 |
| NXP structural sabotage | `python3 test_structural.py` | 8/8 |
| NXP runner contract | `python3 test_runner_mode.py` | 6/6 |
| NXP IP reference models | `python3 test_ip_models.py` | 12/12 |
| NVIDIA model interface | `nvidia_work/agent$ python3 test_model_iface.py` | 13/13 |
| NVIDIA cold-start drill | `python3 test_cold_start.py` (needs Docker) | 6/6 |
| NVIDIA discovery fixtures | `python3 -m ppa.discover --validate` | 3 MATCH |
| ASU v2 safety controls + composer | `asu_v2/tests/run_controls.sh` (needs Docker) | 12/12 PASS |
| ASU official agent (v2 Rev3) | `official_eval/run_official_eval.py --submission-dir asu_work/official_submission` | 7/7 FVR 0.374–0.582, eligible + electrically proven |
| ASU v1 dev agent (historical) | `asu_agent.py <info.json> --model none` (in KLayout 0.30.1 image) | superseded by v2 — see `asu_v2/` |

## Repo layout

**Why both `asu_work/` and `asu_v2/`:** the organizers' documented ASU entry point is
`asu_work/official_submission/agent.py`, and that file IS the current v2 Rev3 agent
(generated from `asu_v2/agent/v2_repairs.py`). `asu_v2/` carries the v2 sources, safety
controls, frozen artifacts + manifests, and the independent review trail; the rest of
`asu_work/` is the v1 development history (kept intact — including the v1 artifacts whose
49 layer-aware electrical merges the v2 review found and fixed). The v2 code deliberately
IMPORTS the v1 verifier from `asu_work/agent/` so "verify == official scorer" has a single
source of truth — the two-folder layout is that architecture, not duplication.

- `nvidia_work/` — ppa agent package, learned playbook, evidence ledgers (baselines,
  round logs, raw model responses), proven variants (exp1/exp2), `submission/` emit-best
  artifacts with manifests, per-track README + daily log + upgrade spec.
- `nxp_work/` — agent (validators, KAT engine, reference models for all 20 library
  ip_types, STG differential, mock contest endpoint), 30-check self-test TB, hand-derived
  reference SoC (stub answers + differential reference), per-track README + logs.
- `asu_work/` — block DRC-repair agent (zero-token DRC diagnosis, exact-rule-grounded
  repair-rule library `drc_rules.json`, verify identical to the official scorer, keep-best
  loop), version-exact KLayout 0.30.1 Dockerfile, per-track README + daily log.
- `docs/` — slide material & outlines (incl. NVIDIA/NXP/ASU decks + Engineering Learnings
  companions), DAC-day runbook, Gemini setup, research notes (~586-paper survey distillation).
- `sync.sh` — refreshes this repo from the working tree (agents are updatable until
  Jul 26 per organizers).

## Contest toolkit bugs found & reported

1. NVIDIA aes: `generated/all_modules.v` duplicates 84 modules → yosys redefinition error
   masked by the run script's success banner (invalidates naive aes baselines).
2. NXP `apb_watchdog`: kick reload overridden by same-block countdown (last-NBA-wins) —
   kick never reloads while counting.
3. NXP `dma_engine`: generated RTL does not compile (`cfg_rdata` declared wire, driven
   procedurally); our agent auto-patches behavior-neutrally.
