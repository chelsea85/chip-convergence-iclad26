# Chip Convergence — NVIDIA RTL PPA-Optimization Agent

An optimize→verify→measure→learn loop over the contest IPs (and any unseen IP in the same
repo conventions). Every acceptance is a **measured strict improvement** under the synthesis
flow, gated by verification recorded **per layer** in each manifest. The assurance level is
whatever the pristine flow actually supports, and is never overstated:

- **full 5-layer** — lint + compile + TB gate + yosys LEC + dual-instance differential sim all
  PASS (e.g. sha512, async_fifo);
- **equivalence+differential** — LEC PROVEN + dualsim PASS, when the *pristine* design already
  fails compile/TB so those layers can't indict the candidate (e.g. prim: compile PRE-EXISTING,
  gate SKIP-preexisting);
- **differential-only** — dualsim PASS with LEC INCONCLUSIVE (e.g. aes, an exploratory power
  tradeoff that did **not** improve ADP — not part of the headline set).

Each `manifest.json` carries `verification_per_layer` + an `assurance` string; prose here and in
the slides is driven by those fields, not the other way round.

## Layout

```
agent/
  ppa/                the package
    controller.py     round loop: propose→verify→measure→select→learn (+--emit-best)
    proposer.py       prompt ladder, models (Stub/Vertex/Endpoint), repair+reflect
    discover.py       auto-onboarding of unseen IPs (hidden-testcase entry)
    verify.py         lint → compile → TB gate → yosys LEC → differential sim
    evaluate.py       Docker synth+STA measurement, proxy pre-filter, dedup, ledger
    objective.py      Pareto / weighted / lexicographic + ADP ratio
    workspace.py      parallel APFS-clone workspaces, harness fixups
    pool.py           Thompson/Beta parent sampling
    skills.py         ACE playbook (learned, measured rules)
    sta_feedback.py   endpoint extraction + root-cause tags
  playbook.json       current learned playbook
  ledger/             baselines, per-candidate + per-round records, raw model responses
  test_cold_start.py  hidden-testcase drill (6/6)
  test_model_iface.py model-interface mock tests (13/13)
```

## Setup

Docker image + ASAP7 per the contest repo's ENV_PREPARATION.md (image `iclad-dev:v1`).
`pip install google-genai`; key: `EXPRESS_MODE_KEY` (Vertex Express, AgentSetup.md) or
`GEMINI_API_KEY` (AI Studio) — auto-detected.

## Run

```bash
cd agent
# optimize an IP (name, or repo-relative path for UNSEEN hidden testcases):
python3 -m ppa.controller --ip sha512 --rounds 3 --k 3 --model vertex \
    --max-calls 20 --emit-best ../submission/sha512

# offline pipeline check (no network):
python3 -m ppa.controller --ip async_fifo --rounds 1 --k 1 --model stub

# baseline / verify / evaluate standalone:
python3 -m ppa.evaluate --ip <name|path> --baseline
python3 -m ppa.verify   --ip sha512 --variant-dir <dir-of-.v-files>
```

`--emit-best DIR` writes the winning candidate's files in drop-in repo layout plus
`manifest.json` (baseline vs best PPA, ADP ratio, verification statement, calls/tokens,
round history). If nothing beats baseline, the manifest says so explicitly.

## Regressions

```bash
python3 test_model_iface.py        # 13/13 (mocked SDK + live local endpoint)
python3 test_cold_start.py         # 6/6 (unseen-IP drill; needs Docker)
python3 -m ppa.discover --validate # discovery fixtures vs hand registry
```

## Results snapshot (2026-07-14)

- **sha512: ADP 0.7266 vs baseline, WNS −97.30→+334.61 ps (MET), full 5-layer (LEC PROVEN)**
  — live `arith-arch` rewrite, emitted in `submission/sha512/` (pristine baseline + optimized
  `sha512_core.v` only; `manifest.json` records `best_ppa` + per-layer verification).
- **prim: ADP 0.6045** (power −67%), setup −208.95→−27.46 ps (still not met) — assurance is
  **equivalence+differential** (compile/TB PRE-EXISTING on the pristine design; LEC PROVEN +
  dualsim PASS), not full 5-layer.
- **async_fifo: ADP 0.961** (timing already MET at baseline) — full 5-layer, keyless stub-replay
  reproducible.
- **aes: ADP 1.0001 (no improvement)** — exploratory power tradeoff, **differential-only**
  assurance (LEC INCONCLUSIVE); intentionally *not* in the headline set.
- Duplicates of known variants are fingerprint-rejected without wasted synthesis.
- Thinking-model note: gemini-3 requires bounded `thinking_budget` (default 8192 here) —
  unbounded, it can spend the entire token cap thinking and return empty text.
