# Chip Convergence — ASU Block-Repair Agent (v1, historical)

> **SUPERSEDED (2026-07-26):** the submitted agent is now **v2 Rev3** —
> `asu_work/official_submission/agent.py`, generated from `asu_v2/agent/v2_repairs.py`
> (FVR 0.374–0.582 on all 7 blocks, layer-aware electrical preservation proven).
> This directory documents the v1 development agent; its verifier (`verify.py`) is
> still imported by v2 as the single source of scoring truth. A layer-aware review
> found the v1 via-bar output contained 49 electrical merges invisible to the
> published checker — see `asu_v2/reviews/` for the full trail.

Repairs ASAP7 KLayout Python layout scripts to reduce DRC violations while preserving
connectivity. Same verification-first architecture as our NVIDIA/NXP agents.

## Flow

```
info.json ──▶ DIAGNOSE ──▶ REPAIR (candidates) ──▶ VERIFY ──▶ KEEP-BEST ──▶ EMIT
             (0 tokens)                          (== scorer)   (safety)
```

- `drc_digest.py` — DRC report → per-rule findings, classified + matched to the repair-rule
  library. Zero model tokens.
- `drc_rules.json` — structured DRC-repair rule library (per-rule-class coordinated transform +
  coupling hazards + provenance). Grounded in the exact `asap7.lydrc` semantics + EDA legalization
  literature (MDPI 2025 SA repair; EDN cut-slide/merge; USPTO enclosure; DRC-Coder ISPD'25).
- `repairs.py` — deterministic geometric fix-passes, emitted as `pya` code appended to the
  ORIGINAL script (source declarations unedited; shapes mutated before `write`). PRIMARY is
  `via_bar_pass`: replaces each flagged multi-cut via array with one continuous via BAR (min via
  thickness → no metal widening → no enclosure/spacing cascade) — **FVR 0.68-0.76 on all 5 public
  blocks**. `grid_snap_pass` is secondary. Earlier *metal*-reshaping fixers regressed and were
  superseded by reshaping the VIA. Connectivity is not preserved "by construction" — it is VERIFIED
  per candidate (render+DRC+official connectivity + a rendered-geometry credibility proxy) and the
  eligible baseline is retained on any regression.
- `verify.py` — render + DRC + connectivity measured with the OFFICIAL evaluator's OWN functions,
  so inner-loop numbers are identical to the scoring machine.
- `asu_agent.py` — runner contract (info.json → output + usage; endpoint mode uses
  `info.json["model_endpoint"]`) + keep-best loop (gated-lexicographic, matches contest). Baseline
  is the eligible floor: never ships a candidate that regresses `final_violation_rate` or fails the
  official connectivity check.
- `model_repair.py` — stub/vertex/endpoint models; model writes a `pya` fix-pass, verified +
  kept-only-if-better; best-of-N with code-compile validation + render-error repair.

## Environment (version-exact, Dockerized)

The organizers score with **KLayout 0.30.1** (the evaluator hard-rejects other versions).
`../docker/Dockerfile` builds an amd64 image with the pinned 0.30.1 + deps. Host may be arm64
(Apple Silicon) → runs under Docker emulation; version-exact, matches organizer scoring.

```bash
docker build --platform linux/amd64 -t asu-klayout:0.30.1 ../docker
# runner contract (inside the image, klayout on PATH):
#   python3 asu_agent.py <info.json> --model <model_name>
# --model handling: a MODEL NAME (e.g. gemini-3.5-flash, as the contest runner
# passes) routes to endpoint mode against info.json["model_endpoint"]; the
# keyword `none` runs the deterministic path (eligible baseline, no model calls).
docker run --rm --platform linux/amd64 -v <ASU_repo>:/asu -v $PWD:/agent asu-klayout:0.30.1 \
    python3 /agent/asu_agent.py /asu/task/.../BlockN_info.json --model none
```

The contest runner (`scripts/run_block_benchmark.py --agent-path asu_work/agent/asu_agent.py`)
invokes `python3 asu_agent.py <info.json> --model <model_name>` — our agent matches that contract.
Whatever the model proposes, keep-best guarantees the emitted script is the best ELIGIBLE one
(the untouched baseline if nothing improves).

## Status

Validated eligible + connectivity-preserved on all 5 public blocks (Block1/2/3/6/7). The seeded
DRC violations form a coupled conflict graph on via stacks (M2-V2-M3-V3-M4...): fixing any layer
cascades to the next, so beating the eligible baseline requires GLOBAL conflict-graph /
simulated-annealing legalization (our keep-best loop already IS the SA acceptance test; the missing
piece is a global multi-edit move-generator). See `../../ASU_DAILY_RUN_LOG.md` for the full
experimental record. Multimodal (DRC-Coder-style screenshot) + SA move-generator are the identified
next steps.
