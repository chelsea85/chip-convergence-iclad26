# Phase 0 — Post-via-bar residual characterization (2026-07-26)

Parity gate PASSED first: v2 driver + imported `via_bar_pass` reproduces the
shipped totals exactly on all 5 blocks (178/52/68/167/522, eligible, credible).
Frozen-hash guard green (rule deck, evaluator, block scripts all match
submission-time hashes). Source: `runs/parity/summary.json`.

## Residual per-rule table (post-bar, our exact env)

| rule | Block1 | Block2 | Block3 | Block6 | Block7 | class |
|---|---|---|---|---|---|---|
| M4.AUX.1 | 72 | 24 | 24 | 72 | 216 | grid |
| V0.M1.AUX.3 | 37 | 12 | 21 | 21 | 97 | via-width (device) |
| M5.AUX.1 | 16 | 8 | 8 | 16 | 24 | grid |
| M1.S.2 | 12 | 2 | 5 | 12 | 25 | spacing |
| V1.M1.EN.1 | 11 | 2 | 6 | 10 | 26 | enclosure |
| M6.AUX.1 | 12 | 0 | 0 | 16 | 24 | grid |
| M1.S.6 | 0 | 0 | 0 | 4 | 34 | spacing |
| M1.S.4 | 2 | 0 | 1 | 1 | 21 | spacing |
| M3.S.2 | 2 | 0 | 0 | 3 | 15 | spacing |
| V4.AUX.1 | 4 | 2 | 2 | 4 | 6 | **bar collateral** |
| M4.AUX.2 | 2 | 1 | 1 | 4 | 9 | width |
| M1.S.5 | 0 | 0 | 0 | 0 | 14 | spacing |
| V5.AUX.1 | 3 | 0 | 0 | 4 | 6 | **bar collateral** |
| M4.S.5 | 4 | 1 | 0 | 0 | 1 | spacing |
| M2.S.7 | 1 | 0 | 0 | 0 | 4 | spacing |
| **TOTAL** | **178** | **52** | **68** | **167** | **522** | |

## Key findings

1. **Grid (M4/M5/M6.AUX.1) is the LARGEST residual class**: 100/32/32/104/264
   per block (56% of Block1's residue). Bonus: our env inflates these 2–4×
   vs the reference (Block1 M4.AUX.1: ref 18 vs ours 72 — unique geometries,
   NOT duplicate markers, per the Jul-15 P0-F05 falsification), and FVR =
   our-count / reference-denominator, so each grid fix pays 1 full count.
2. **V0.M1.AUX.3 is the #2 class**: 37/12/21/21/97. Deck semantics: "V0 must
   exactly be the same width as M1 along the direction perpendicular to the M1
   length" — same family as the beaten upper-layer AUX.2 class, but V0 is also
   coupled DOWNWARD: `V0.AUX.1` (must interact M1 & [LISD|LIG]),
   `V0.LISD.EN.2/3` (3 nm containment), `V0.LIG.AUX.2`, `V0.S.1` (17–27 nm
   V0↔V0). Per-site characterization in `v0_char_<Block>.json`.
3. **via-bar introduces small collateral**: `V4.AUX.1`/`V5.AUX.1`
   (7/2/2/8/12 per block) — "V4 must be inside M4 and M5": the bar spans the
   upper-metal landing but crosses gaps in the LOWER metal. Still net-positive
   at those sites (bar = 1 AUX.1 vs the 3 AUX.2 it removed). Candidate fix:
   per-site lower-metal patch under flagged bars only, with spacing precheck.
4. Long tail: M1.S.* spacing (mostly Block7), V1.M1.EN.1 enclosure, M4.AUX.2
   width — reassess after the big classes land.

## V0 widening — FALSIFIED (zero DRC runs spent)

Per-site characterization (`v0_char_<Block>.json`, from the rendered baseline
GDS + DRC markers; flagged counts match DRC exactly: 37/12/21/21/97):

* Every flagged V0 is a min 72×72 cut on a WIDE M1 pad (200–632 dbu perp
  width); **1 cut per pad — no multi-cut arrays → no bar analog exists**.
* **188/188 sites fail the LISD containment precheck**: the LISD landing under
  each via is small, so widening V0 to M1's perp width (what V0.M1.AUX.3
  demands) always breaks 3 nm V0.LISD.EN.2 from below. 64 sites also fail
  V0↔V0 spacing (<18 nm), 74 sit on non-rectangular M1.
* The wide M1 pad is the familiar over-constrained triangle (pad serves the V1
  above; V0 below is pinned to its LISD island). Remaining angle: per-site M1
  NECK at the via span (y-clear of V1, spacing-prechecked) — cheap falsifiable
  test, low confidence given the S1/M3-neck history.

## Grid class — track-shift hypothesis (ACTIVE)

`ongrid` fires on MERGED metal track edges (M4:y/24nm, M5:x/24nm, M6:y/32nm)
and every off-grid edge is via-connected (Jul-14). Hypothesis: the seeder
TRANSLATED whole tracks off-grid; the inverse is translate-track-back-to-grid
**co-translating its vias** (per-edge snap = resize + orphaned vias = the
regression seen Jul-14). If both constrained edges of each off-grid polygon are
off by the SAME delta, the hypothesis holds (`grid_char_<Block>.json`).

## Upside if all three addressable classes cleared (upper bound)

Block1 178→~64 (FVR ~0.26) · Block2 52→~14 · Block3 68→~33 · Block6 167→~51 ·
Block7 522→~137 (FVR ~0.18). Realistically partial; every site gated by exact
DRC + rendered-connectivity credibility, floor = shipped result.
