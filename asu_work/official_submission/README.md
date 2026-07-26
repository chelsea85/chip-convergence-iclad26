# ASU Block-Repair — Official Submission Package (v2 Rev3, 2026-07-26)

This is the directory to hand to the organizers' official runner:

```bash
python3 official_eval/run_official_eval.py \
    --run-id <fresh-id> \
    --submission-dir <path-to>/asu_work/official_submission \
    --agent-entrypoint agent.py
```

`agent.py` runs in `python:3.10-slim`, read-only, no KLayout — the evaluator
renders and scores afterward. It is **generated** by
`asu_v2/tools/compose_official_agent.py` from `asu_v2/agent/v2_repairs.py`
(do not edit by hand).

## What it emits (deterministic, zero model calls)

`stripped(original) + via-bar-safe + track-shift + v1-patch` — three pya
repair passes that execute inside the organizer's KLayout render:

1. **via-bar-safe** — replaces each flagged multi-cut via array with one
   continuous bar ONLY where the bar touches exactly the same electrical
   components as the original cuts on BOTH adjacent metal layers (per-side
   comparison over a full-stack union-find). Landings that would short or
   open a net keep their original cuts (fail closed).
2. **track-shift** — translates off-grid M4/M5/M6 tracks back to the routing
   grid / track pitch, co-translating riding V3/V4 cuts and patching M3
   end-caps; each move is accepted only under layer-aware contact-set
   equality (no flat-projection acceptance path); M6 tracks interacting V6
   are refused.
3. **v1-patch** — minimal exact-predicate V1.M1.EN.1 enclosure restoration
   where provably safe.

On a block with no matching flagged geometry every pass is a no-op and the
original renders unchanged (eligible floor).

## Verified results (public blocks, official-runner rehearsal `rev3p15`)

| Block | violations | official FVR | v1 (history) |
|---|---|---|---|
| Block1 | 315→142 | 0.5820 | 0.7295 |
| Block2 | 90→35 | 0.5147 | 0.7647 |
| Block3 | 111→35 | 0.3933 | 0.7640 |
| Block6 | 321→102 | 0.4130 | 0.6761 |
| Block7 | 957→444 | 0.5804 | 0.6824 |

All valid + connectivity-preserved under the published checker, and —
verified separately — the **layer-aware electrical partition is preserved
exactly** original→repaired (immutable-anchor comparison, full SHA-256,
fail-closed coverage: `asu_v2/agent/compare_laconn.py`).

## Evidence & provenance

* `asu_v2/submission/` — frozen artifacts, per-block manifests,
  `RELEASE_MANIFEST.json` (full hashes incl. this agent),
  `P15_OFFICIAL_RUN_ADDENDUM.md` (official-runner rehearsal, zero model
  calls), `evidence/` (factor reports, logs, connectivity comparisons).
* `asu_v2/reviews/` — three-round independent review trail. Round 1 found
  that the v1 via-bar (previous submission) created 49 layer-aware electrical
  merges invisible to both the published source checker and our then-2D
  proxy; Rev3 removes them at a measured DRC cost.
* `asu_v2/tests/run_controls.sh` — 12 permanent keyless safety controls
  (including both review counterexamples).

Precise language: the v1 artifacts (`asu_work/submission/`, history) "pass
the published source checker"; Rev3 additionally "preserves layer-aware
electrical connectivity (original→repaired)".
