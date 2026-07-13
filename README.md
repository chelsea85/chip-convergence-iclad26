# Chip Convergence — ICLAD-DAC 2026 GenAI Chip Hackathon

Solo team (Hari Krishnan), Cloud track. Two agents:

| Track | Agent | Headline result (2026-07-12, live gemini-3-flash-preview) |
|-------|-------|------------------------------------------------------------|
| **NVIDIA** — RTL PPA optimization | `nvidia_work/agent/` | sha512 **ADP 0.787 vs baseline, WNS −97→+235 ps (timing MET), yosys-LEC-proven**; live rounds produced 2 verified model-generated accepts (composed ADP ≈0.884) |
| **NXP** — SoC generation from diagrams | `nxp_work/agent/` | **Perfect solve in 2 model calls / 42 s**: self-test 30/30, KAT 79/79 on both oracles, STG differential cycle-identical to reference over 3,662 cycles |

Both agents are verification-first: every model output passes deterministic gates
(equivalence checks, port contracts, structural diffs, known-answer tests) before anything
is accepted. Detailed engineering logs: `nvidia_work/NVIDIA_DAILY_RUN_LOG.md`,
`nxp_work/NXP_DAILY_RUN_LOG.md`.

## Setup

1. Clone the contest repo INTO this repo's root (agents locate it by relative path):
   ```bash
   git clone --recurse-submodules \
       https://github.com/ICLAD-Hackathon/ICLAD-Hackathon-2026
   ```
   (or symlink an existing clone: `ln -s /path/to/ICLAD-Hackathon-2026 .`)
2. Tools: python3 (stdlib only for NXP), iverilog/vvp; for NVIDIA synthesis additionally
   Docker (`iclad-dev:v1` built per the contest repo's ENV_PREPARATION.md) + ASAP7 in
   `ICLAD-Hackathon-2026/.../techlib/`.
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

## Repo layout

- `nvidia_work/` — ppa agent package, learned playbook, evidence ledgers (baselines,
  round logs, raw model responses), proven variants (exp1/exp2), `submission/` emit-best
  artifacts with manifests, per-track README + daily log + upgrade spec.
- `nxp_work/` — agent (validators, KAT engine, reference models for all 20 library
  ip_types, STG differential, mock contest endpoint), 30-check self-test TB, hand-derived
  reference SoC (stub answers + differential reference), per-track README + logs.
- `docs/` — slide material & outlines, DAC-day runbook, Gemini setup, research notes
  (~586-paper survey distillation).
- `sync.sh` — refreshes this repo from the working tree (agents are updatable until
  Jul 26 per organizers).

## Contest toolkit bugs found & reported

1. NVIDIA aes: `generated/all_modules.v` duplicates 84 modules → yosys redefinition error
   masked by the run script's success banner (invalidates naive aes baselines).
2. NXP `apb_watchdog`: kick reload overridden by same-block countdown (last-NBA-wins) —
   kick never reloads while counting.
3. NXP `dma_engine`: generated RTL does not compile (`cfg_rdata` declared wire, driven
   procedurally); our agent auto-patches behavior-neutrally.
