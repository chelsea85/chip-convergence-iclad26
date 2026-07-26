# ASU v2 — resubmission review packet (2026-07-26)

**Ask:** independent GO/NO-GO review of the ASU v2 improvement before Hari
resubmits. The submitted v1 artifact (`asu_work/`, FVR 0.68–0.76) is untouched
and remains the fallback; v2 lives entirely in `asu_v2/`.

## Claim

Final stack **via-bar (v1, imported) + track-shift + v1-patch**, zero model
tokens, on all 5 public blocks (run `asu_v2/runs/final1/`):

| Block | v1 shipped FVR | v2 FVR | violations | eligible | credible |
|---|---|---|---|---|---|
| Block1 | 0.730 | **0.316** | 315→77 | ✓ | ✓ |
| Block2 | 0.765 | **0.279** | 90→19 | ✓ | ✓ |
| Block3 | 0.764 | **0.393** | 111→35 | ✓ | ✓ |
| Block6 | 0.676 | **0.243** | 321→60 | ✓ | ✓ |
| Block7 | 0.682 | **0.306** | 957→234 | ✓ | ✓ |

Measured with the official evaluator's own functions (`asu_work/agent/verify.py`,
imported read-only) in the version-exact KLayout 0.30.1 container; eligibility =
render + DRC + official static connectivity; credible = rendered-geometry
net-component/area gate (v1's Option-A check, UNCHANGED).

## What's new (all in `asu_v2/agent/v2_repairs.py`)

1. **track-shift** (the big win, ~100/32/32/104/264 counts): the M4/M5/M6.AUX.1
   class is seeded by TRANSLATING whole tracks off-grid — verified: both
   constrained edges off by the same delta on every off-grid merged polygon
   (`results/grid_char_Block1.json`). Inverse transform: translate back
   (min-width tracks to the 2G routing-track pitch — decoded from `offgrid_cl`,
   which SKIPS off-base-grid polys, hence M*.AUX.2 was invisible pre-fix;
   wider rails to the G edge grid), co-translate riding V3 cuts, patch M3
   end-caps (5 nm) with 31 nm tip precheck. Net-topology safety: fast windowed
   contact-set filter; where the contact set changes, EXACT global 2D-union
   component count recomputed in-pass (the credibility gate's own quantity);
   opposite-pitch fallback; revert last. 149/150 tracks moved across the set.
2. **v1-patch** (marginal, +1 on Block7): exact V1.M1.EN.1 predicate from the
   deck (inside(M1) AND one axis slacks >=2nm & >=5nm), minimal single-axis
   patch, 4 orientations, topology-gated. Only 1/37 failing V1s is safely
   patchable — the rest trade an EN marker for an S marker (documented).

## Verification chain (what to re-run if desired)

* Parity gate: `asu_v2/run_docker.sh --tag parity --passes via-bar` must
  reproduce shipped 178/52/68/167/522 exactly (it did; `runs/parity/`).
* Frozen-hash guard: every run asserts rule-deck/evaluator/block-script SHA-256
  vs `asu_work/baselines/baseline_table.json` (submission-time hashes).
* Final run: `asu_v2/run_docker.sh --tag <t> --passes via-bar,track-shift,v1-patch`.
* Submission path: `asu_v2/official_submission/agent.py` — stdlib-only,
  COMPOSED from the proven sources (via-bar builder asserted == v1 repairs.py;
  v2 snippet builders asserted == the pass generators), output byte-identical
  to the measured `runs/final1/*/cand.py` on all 5 blocks, and re-verified in
  a read-only python:3.10-slim container (no KLayout), usage-write best-effort
  (ASU-P-01). Frozen artifacts + SHA manifests: `asu_v2/submission/`.

## Falsified alternatives (full record in results/ + runs/)

`results/PHASE0_RESIDUALS.md`, `results/PHASE2_TRACK_SHIFT_RESULTS.md`,
`results/PHASE4_M1_STACK_FINDINGS.md`. Highlights: V0 widening falsified
zero-cost (188/188 LISD containment); track-shift went through 5 falsified
safety designs (runs ts1→ts_all6) before the fast-filter + exact-global-check
architecture; V0 finger reconstruction falsified per-site with exact
width_check/space_check post-conditions (16 stepped-pad slivers + 21
adjacent-V1 conflicts of 37 Block1 sites) → V0/V1/M1.S cluster is locally
irreducible, needs global legalization; v0-finger EXCLUDED from the stack.

## Self-identified risks (please scrutinize)

1. **Fast-filter gap:** the track-shift contact-set XOR does not include the
   M3 end-cap patches (only the moved track+cuts). Backstop: the per-candidate
   credibility gate in verify.py — which passed on all 5 blocks — and the
   in-pass global comps check on the slow path. Is the backstop sufficient, or
   should patches be folded into the filter before shipping?
2. **Hidden testcases:** the official agent applies the transforms BLINDLY (no
   KLayout in the agent container → no keep-best there). Both v2 passes are
   self-limiting no-ops on clean geometry (no off-grid tracks → no moves; no
   failing V1s → no patches), same risk profile as the reviewed v1 via-bar.
   The emitted pya passes DO run comps checks at the organizer's render — extra
   render cost (measured fine under our slower emulation), and behavior on
   pathological hidden blocks falls back to per-track/per-patch revert.
3. **v1-patch spacing probe = 25 nm** (tip-to-side), not the 31 nm worst case:
   rationale = patch edges are tips, neighbor pad edges are sides; a rare
   tip-tip neighbor would at worst trade 1-for-1 (block-level DRC refereed the
   final numbers). Only 1 patch ships.
4. **Accepted collateral:** Block1 +3 (M4.S.2 +1, M4.S.3 +2) from large pitch
   moves — net −101 for the class; per-site revert would cost more than it
   saves. V4/V5.AUX.1 bar collateral (31 total, pre-existing v1 behavior)
   remains unfixed and documented.
5. The credibility gate is v1's 2D-projection proxy, UNCHANGED — v2 conforms
   to it rather than weakening it; the in-pass global check mirrors it exactly.
6. Determinism: no randomness anywhere; same inputs → byte-identical outputs
   (byte-identity verified across driver and official agent).

## GO/NO-GO questions

1. Any blocking correctness risk in the track-shift architecture or the
   emitted-script runtime checks?
2. Is the hidden-testcase blind-application posture acceptable (as it was for
   v1 via-bar)?
3. Anything required before resubmission beyond the optional full
   `official_eval/run_official_eval.py` pass with the key?
