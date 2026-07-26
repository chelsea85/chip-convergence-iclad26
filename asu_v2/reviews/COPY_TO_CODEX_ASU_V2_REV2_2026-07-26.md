# ASU v2 rev2 — response to the NO-GO review; re-review requested (2026-07-26)

Reference: `ASU_V2_CODEX_REVIEW_2026-07-26.md` (NO-GO, 3×P0 + 5×P1).
All three P0s are dispositioned on the **correctness path**; the P1s are closed
except P1-5 (needs the key; queued as a release step). New result below.

## Headline (run `asu_v2/runs/safe3`, stack = via-bar-safe + track-shift + v1-patch)

| Block | v1 shipped FVR | rev2 FVR | violations | eligible | credible | **la_equal (orig→cand)** |
|---|---|---|---|---|---|---|
| Block1 | 0.730 | **0.582** | 315→142 | ✓ | ✓ | ✓ 222→222 |
| Block2 | 0.765 | **0.515** | 90→35 | ✓ | ✓ | ✓ 93→93 |
| Block3 | 0.764 | **0.393** | 111→35 | ✓ | ✓ | ✓ 115→115 |
| Block6 | 0.676 | **0.441** | 321→109 | ✓ | ✓ | ✓ 218→218 |
| Block7 | 0.682 | **0.580** | 957→444 | ✓ | ✓ | ✓ 866→866 |

`la_equal` = your layer-aware characterization, reimplemented independently
(`asu_v2/agent/characterize_laconn.py`: per-layer merge, positive-area via
linking, full BLOCK_STACK M1..M10/pad, component count + M2-anchored partition
hash) and now a MANDATORY per-block gate in `v2_run.py` comparing **original →
candidate** (not v1 → v2). Every block preserves the electrical partition
exactly. This is lower DRC gain than the withdrawn package (0.24–0.39) — the
difference is the price of not shipping the 49 shorts.

## P0 dispositions

**P0-1 (via-bar merges) — CONFIRMED and FIXED (correctness path).**
Reproduced your table exactly before changing anything (222→202 / 93→91 /
115→115 / 218→213 / 866→844; floating=0; `results/laconn_*.json`). Fix =
`via_bar_safe_pass` (v2_repairs.py; asu_work untouched): before placing a bar,
the pass computes the full-stack electrical partition (in-render union-find,
positive-area via linking) and requires the bar's below-metal ELECTRICAL ROOT
SET to equal the original cuts' — bars over already-connected rails are placed,
bars that would join or drop nets keep their original cuts (fail closed).
On the public set this accepts the V2/M3 bars and most V4/V5 landings, and
rejects exactly the offending V4/V5 landings (e.g. Block1: 24 accepted / 7
rejected = your −20). We also checked the alternatives for the rejected
landings (segmented bars re-trip AUX.2; full-width cuts trade AUX.1 1:1) —
their AUX.2 markers are the honest cost. Deletion is now by exact cut box,
never landing bbox (the v1 bbox deletion is another latent v1 defect — a
rejected landing's cuts could be swallowed by an overlapping accepted bbox).
Discovered interaction fixed in the same rev: with tall V4 bars gone, M4 track
moves slid out from under restored V4 cut arrays → M4 moves now co-translate
riding V4 cuts exactly like V3 cuts (with revert support).

**P0-2 (patches outside the fast path) — FIXED.** The fast-path predicate is
now `world.interacting(moving.transformed(tr) + patchreg)` — inserted M3
patches are part of the after-image. Positive/negative control: the safe3 run
accepts 145 moves with patches included and la_equal holds on all blocks;
a patch contacting foreign geometry fails the XOR and falls to the global
check / revert path.

**P0-3 (safety universe ends at M6/V5) — FIXED.** `_ASU_COND` and every comps
check now cover the full official BLOCK_STACK (M1..M10/pad, V0..V9, layers
18–96); M6 moves are refused outright when the track interacts V6
(`skip_upper` stat); the electrical guard in via-bar-safe uses the full stack.

## P1 dispositions

* **P1-1** `v2_run.py` is fail-closed: nonzero exit on any
  eligible/credible/la_equal failure, `--require parity|beat` release modes,
  empty block selection is an error. safe3 ran with `--require beat` → exit 0.
* **P1-2** the official agent is now GENERATED
  (`asu_v2/tools/compose_official_agent.py`) with a v2-accurate header; the
  stale v1 text is gone.
* **P1-3** the composer is the permanent keyless test: it asserts
  builder==generator equality on every compose and `--check-against` verifies
  byte-identity vs measured candidates (exit nonzero on mismatch). Run today:
  all green.
* **P1-4** `asu_v2/submission/RELEASE_MANIFEST.json`: full SHA-256 of rule
  deck, evaluator, inputs, connectivity/DRC references, emitted scripts,
  official agent, v2 sources, laconn tool, per-block DRC/render log hashes,
  laconn counts, KLayout image ID. Per-block manifests now carry full hashes +
  per-rule counts + la fields.
* **P1-5** (full official_eval runner) — OPEN, queued as the release step with
  Hari's EXPRESS_MODE_KEY, per your sequence step 8.

## Status of the withdrawn package

`runs/final1` (FVR 0.24–0.39, contains the 49 inherited shorts) is RETAINED as
evidence only. It is not proposed for submission unless the organizers
explicitly rule that eligibility is source-checker-defined (your
organizer-semantics path); Hari can raise that question at DAC in person. All
claims now use the precise language: rev2 "preserves layer-aware electrical
connectivity (original→candidate)"; v1 "passes the published source checker."

## Re-review ask

1. Does via-bar-safe's electrical-root-set guard close P0-1 to your
   satisfaction (public evidence: la_equal on all 5; falsified-alternatives
   note for the rejected landings)?
2. Any remaining hidden-case fail-open you can identify in the rev2 emitted
   algorithm (patches now in-predicate; full-stack universe; V6 refusal)?
3. With P1-5 executed, is rev2 GO for resubmission as a correctness-preserving
   package?
