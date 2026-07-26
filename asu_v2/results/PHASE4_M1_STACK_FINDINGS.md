# Phase 4 — M1-stack residuals: findings (2026-07-26)

Targets after track-shift: V0.M1.AUX.3 (188), V1.M1.EN.1 (55), M1.S.* (~120).
Joint forensics (`agent/characterize_m1.py`, `results/m1_char_Block{1,7}.json`):
all three classes share the SAME anatomy — non-rectangular M1 pads (200–880
dbu wide) carrying min 72×72 V0s AND min 72×72 V1s (the pad width is not
justified by via sizes; the seeder reshaped/merged pad geometry).

## v1-patch (V1.M1.EN.1) — MARGINAL (kept, +1)

Exact-predicate pass (inside(M1) AND one axis with slacks >=2nm & >=5nm — from
the deck's v1_m1en1 implementation), minimal patch, all 4 orientations tried,
topology-gated. Iterations: uniform-5nm-ring version FALSE-POSITIVED 353
patches (+375 net violations — discarded by keep-best as designed); exact
version identifies precisely the failing 11/26 cuts (matches DRC counts).
Result: **only 1/37 sites safely patchable** (Block7 235→234). The rest are
blocked by real 18–25 nm clearances to neighboring pads: the patch would trade
an EN marker for an S marker. Class is over-constrained, not mis-diagnosed.

## v0-finger (V0.M1.AUX.3) — FALSIFIED at per-site granularity

Idea: reconstruct the original narrow finger by cutting rule-compliant slits
flanking each flagged V0 (width 80 = 20 nm for side/corner spacing, depth >144
so walls are side-class) + FILL the finger rectangle where the V0 overhangs
pad steps. Exact post-conditions per site: KLayout width_check(72) and
space_check(72) deltas must be zero, foreign-via standoff on removals,
overlap-only on fills, global component count unchanged.

Six design iterations (margin heuristic → adaptive widening → morphological
open [wrong: flags concave corners] → width_check → cut+fill → split via
guard), each falsified by measurement. Final anatomy of all 37 Block1 sites:
* 16: any slit exposes a pre-existing pad STEP as sub-min-width M1 (the V0s
  overhang 36-dbu-narrower bases; debug: `scratchpad/debug_finger.py`).
* 21: an adjacent V1 sits 36–72 dbu from the V0 edge — inside ANY rule-legal
  slit zone; cutting strips its 5&2 nm enclosure.

**Conclusion (proven, not asserted): the V0/V1/M1.S residual cluster is
locally irreducible — every rule-legal local edit is blocked by an exact
geometric post-condition. Fixing it requires coordinated multi-pad, multi-via
reshaping (global legalization), consistent with the Jul-14 conflict-graph
finding, now demonstrated per-site with zero-token checks.**

## Final v2 stack decision

`via-bar + track-shift + v1-patch` (v0-finger excluded — zero yield, would be
dead code in the emitted script). M1.S.* not attacked separately: same pad
anatomy, same over-constraint. Bar collateral (V4/V5.AUX.1, 31 counts) remains
the only tractable future item.
