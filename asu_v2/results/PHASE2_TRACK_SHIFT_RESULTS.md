# Phase 2 — track-shift pass: RESULTS (2026-07-26)

## Headline (run `runs/ts_all6`, artifacts frozen in `submission/`)

| Block | v1 shipped FVR | **v2 FVR** | violations | eligible | credible |
|---|---|---|---|---|---|
| Block1 | 0.730 | **0.316** | 178 → 77 | ✓ | ✓ |
| Block2 | 0.765 | **0.279** | 52 → 19 | ✓ | ✓ |
| Block3 | 0.764 | **0.393** | 68 → 35 | ✓ | ✓ |
| Block6 | 0.676 | **0.243** | 167 → 60 | ✓ | ✓ |
| Block7 | 0.682 | **0.307** | 522 → 235 | ✓ | ✓ |

Zero model tokens. Pass stats: 149/150 off-grid tracks moved (1 skipped on
Block6); global component check needed only 4 times.

## Mechanism (same "invert the seeding" logic as via-bar)

The M4/M5/M6.AUX.1 class is seeded by TRANSLATING whole tracks off the routing
grid (proven: both constrained edges off by the same delta on every off-grid
polygon, all 5 blocks). `track_shift_pass` (asu_v2/agent/v2_repairs.py):

1. Translate each off-grid rect track back to grid — min-width tracks to the
   2G routing-track PITCH (offgrid_cl/M*.AUX.2 skips off-base-grid polys, which
   is why AUX.2 was invisible before the edge fix), wider rails to the G edge
   grid. Nearest position first, opposite direction as fallback.
2. Co-translate the V3 cuts riding M4 tracks (flush by construction) and patch
   the M3 end-cap (5 nm) where a shifted cut would lose enclosure — 31 nm
   tip-clearance precheck; the whole track is skipped if a patch is infeasible.
3. Net-topology safety = the credibility gate's own quantity: fast windowed
   contact-set filter (provably sufficient when unchanged); on change, exact
   global 2D-union component count recomputed in-pass — keep only if
   identical, else opposite direction, else revert.

Iteration history (each falsified by exact DRC/credibility, all in runs/):
ts1 nearest-edge-grid only → M4.AUX.2 +8 phase collateral; ts2 pitch-aware →
Block1 77 but Blocks 6/7 net-merge (credible=False); ts_all2 same-layer-touch
precheck → no effect (shorts were cross-layer in the 2D projection union);
ts_all4 strict local contact-set → credible but over-conservative (Block1
regressed to 150 — local contact changes are usually harmless inside one big
projected blob); ts_all6 fast-filter + exact global check → best of both.

## Collateral ledger (Block1): M4.S.2 +1, M4.S.3 +2 (tip spacing from large
pitch moves) — net −101 vs keeping those tracks off-grid. Residual after v2:
V0.M1.AUX.3 (37/12/21/21/97, falsified as locally unfixable), M1.S.*,
V1.M1.EN.1, V4/V5.AUX.1 bar collateral (7/2/2/8/12), M4.S.5, M2.S.7.

## Submission readiness

* `official_submission/agent.py` — stdlib-only, composed FROM the proven
  sources (via-bar part asserted == asu_work repairs.py; track-shift part
  embedded from v2_repairs.py), emits byte-identical output to the measured
  ts_all6 candidates on all 5 blocks.
* Acceptance test PASSED: read-only `python:3.10-slim` (no KLayout), all 5
  outputs byte-identical; usage write best-effort (ASU-P-01 lesson applied).
* Frozen artifacts + per-block manifests (sha256) in `submission/`.

## Not done / open

* Full `official_eval/run_official_eval.py` end-to-end (needs Hari's
  EXPRESS_MODE_KEY; v1 flow in ~/organizer_repro is the template).
* External (Codex) review of asu_v2 before resubmission — recommended per
  project discipline (self-approval of assurance-relevant code is not enough).
* Optional further wins: V4/V5.AUX.1 bar collateral (M5-trim per-site),
  per-site M1 neck for V0 (low confidence), M1.S.*/V1.M1.EN.1 (uncharacterized).
