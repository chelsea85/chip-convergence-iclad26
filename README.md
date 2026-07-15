# Chip Convergence — ICLAD-DAC 2026 GenAI Chip Hackathon

Solo team (Hari Krishnan), Cloud track. **Three agents, one verification-first architecture:**

| Track | Agent | Headline result (live gemini-3-flash-preview) |
|-------|-------|------------------------------------------------|
| **NVIDIA** — RTL PPA optimization | `nvidia_work/agent/` | sha512 **ADP 0.727**, WNS −97→**+335 ps (MET), LEC-proven** (agent's live rewrite beat our best hand-derived 0.787); prim **ADP 0.605** (power −67%) in 6 calls |
| **NXP** — SoC generation from diagrams | `nxp_work/agent/` | **Perfect solve in 2 model calls / 42 s**: self-test 30/30, KAT 79/79 on both oracles, STG differential cycle-identical to reference over 3,662 cycles |
| **ASU** — block DRC repair | `asu_work/agent/` | Version-exact (KLayout 0.30.1) Dockerized env; verify identical to the official scorer; **keep-best guarantee: eligible + connectivity-preserved on all 5 blocks**; exact-rule-grounded repair-rule library + rigorous characterization of block-repair as global legalization |

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
python3 -m ppa.controller --ip sha512 --rounds 3 --k 3 --model vertex \
    --max-calls 20 --emit-best ../submission/sha512
# offline loop check: --model stub --rounds 1 --k 1
```

## Quickstart — ASU

```bash
docker build --platform linux/amd64 -t asu-klayout:0.30.1 asu_work/docker   # KLayout 0.30.1
# runner contract (inside the image; klayout on PATH):
docker run --rm --platform linux/amd64 -v <ASU_repo>:/asu -v $PWD/asu_work/agent:/agent \
    asu-klayout:0.30.1 python3 /agent/asu_agent.py /asu/task/.../BlockN_info.json --model none
python3 asu_work/agent/drc_digest.py <BlockN.drc.json>   # zero-token DRC diagnosis
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
| ASU 5-block validation | `asu_agent.py <info.json> --model none` (in KLayout 0.30.1 image) | 5/5 eligible, connectivity preserved |

## Repo layout

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
