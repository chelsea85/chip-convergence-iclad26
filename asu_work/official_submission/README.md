# ASU Block-Repair — Official Submission Package

This is the directory to hand to the organizers' official runner:

```bash
python3 official_eval/run_official_eval.py \
    --run-id <fresh-id> \
    --submission-dir <path-to>/asu_work/official_submission \
    --agent-entrypoint agent.py
```

- **Entry point:** `agent.py` (self-contained, Python **stdlib only**).
- **`requirements.txt`:** none — nothing to `pip install` (the runner then uses the
  base `python:3.10-slim` image directly).

## What it does

Deterministic via-bar repair, zero model tokens: it replaces each flagged
multi-cut via array (min via sitting in a wide metal) with **one continuous via
BAR** spanning the metal's length, keeping the min via thickness (so no
lower-metal widening → no enclosure/spacing cascade). Applied to upper-routing
pairs only — V2/M3, V4/M5, V5/M6. V0/M1 (device layer) is deliberately excluded.

The emitted `Block*_repaired.py` is **byte-identical** to
`asu_work/submission/Block*_repaired.py`, which were independently re-scored with
the published evaluator at **final-violation-rate 0.68–0.76**, eligible,
connectivity-preserved (SHA-256 prefixes: Block1 `fdae65dd`, Block2 `8c21ce2f`,
Block3 `bacc0531`, Block6 `a31d59ad`, Block7 `e5851416`).

## Why it does NOT render/DRC internally

The official agent image (`python:3.10-slim` + `google-genai`/`shapely`) has **no
`klayout` binary**, and the runner honors only a Python `requirements.txt` — not a
custom Dockerfile. Our development agent (`asu_work/agent/asu_agent.py`) measures
every candidate with the evaluator's own render+DRC to keep-best, which needs
KLayout at agent runtime; in the official image it can measure nothing and would
fall back to the untouched original.

This submission agent instead applies the **already-proven** deterministic
transform without measuring, and the **organizer's evaluator renders and scores
the emitted script afterward, on the host, in KLayout 0.30.1** — exactly where the
appended `pya` code was always meant to run.

## Behavior when KLayout is unavailable (i.e. always, in the official image)

Unaffected — the agent never calls KLayout. It reads the layout script, appends
the via-bar `pya` snippet, and writes `output_path`.

## Safety / fail-closed behavior

- The via-bar transform is **self-guarding at execution time**: `_asu_bar_pair`
  only reshapes vias whose perpendicular dimension is smaller than the interacting
  metal's (the flagged wide-metal/min-via pattern). A block with no such landing
  is a **no-op** (0 bars, geometry unchanged) → never worse than the original on
  the eligibility floor.
- If the input does not look like a `pya` layout builder, the original is emitted
  untouched.
- `usage_path` write is best-effort (the runner mounts the agent `--read-only`);
  a failed write never crashes the run.

## Hidden-case caveat (honest)

Because this agent does not render/DRC internally, it cannot catch a hidden legal
narrow-via/wide-metal idiom that happens to match the geometric predicate. On the
five public blocks this is proven safe. Tightening the predicate with exact
DRC-finding coordinates is tracked as future work (see the review findings).
