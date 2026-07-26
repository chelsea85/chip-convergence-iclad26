# ASU v2 Rev3 — response to the Rev2 HOLD; re-review requested (2026-07-26)

Reference: `ASU_V2_REV2_CODEX_REVIEW_2026-07-26.md` (HOLD/NO-GO, 2 focused P0s
+ signature/controls P1s). Every item on the §8 Rev3 checklist is done except
P1-5 (key-gated, queued as the final release step).

## Headline (run `asu_v2/runs/rev3b`, driver exit 0 under `--require beat`)

| Block | v1 shipped FVR | Rev3 FVR | violations | anchor partition |
|---|---|---|---|---|
| Block1 | 0.730 | **0.582** | 315→142 | ✓ equal (222, 803 anchors) |
| Block2 | 0.765 | **0.515** | 90→35 | ✓ (93, 286) |
| Block3 | 0.764 | **0.393** | 111→35 | ✓ (115, 429) |
| Block6 | 0.676 | **0.413** | 321→102 | ✓ (218, 771) |
| Block7 | 0.682 | **0.580** | 957→444 | ✓ (866, 3189) |

Block6 improved vs Rev2 (109→102): the layer-aware acceptance is both safer
and less conservative than the flat filter it replaced.

## P0-A — via-bar guard is now TWO-SIDED, compared PER SIDE

`touch_roots` returns a (below-roots, above-roots) PAIR; bar vs cuts compared
per side. Note: your suggested `below + above` UNION comparison is
insufficient — our new dropped-contact control caught that a union hides a
dropped below-contact when rail and landing are the same net through the very
cuts being replaced. The per-side form rejects both your upper-island short
and the drop case (permanent controls: `bar/upper-island short rejects`,
`bar/dropped-below-contact rejects`, plus the positive control).

## P0-B — track acceptance is layer-aware; flat fallback REMOVED

`_asu_ts_layer` (v2_repairs.py) accepts a move only if ALL of: same-layer
touch set unchanged; every STATIONARY adjacent-via positive-area contact set
unchanged (riding cuts excluded — they co-move); every riding V3 cut keeps the
same M3 host set and every riding V4 cut the same M5 host set; patches touch
only their host rail and no foreign V2/V3. `_asu_comps()` and the flat
projected world are GONE — there is no flat-count acceptance path anywhere in
the emitted algorithm. Your projection-swap layout is a permanent control
(`track/projection-swap rejects`, zero accepted moves), alongside a positive
clean-move control, the patch-foreign-via control, and the M6/V6 refusal.

## Final signature — immutable anchors, full coverage, full SHA-256

`compare_laconn.py` (replaces the M2-anchored hash): anchors = metal polygons
byte-identical (layer + vertices) in baseline and candidate; the anchor
partition must match exactly (full SHA-256, exact membership); EVERY component
on BOTH sides must contain >=1 anchor (fail closed — `uncovered` counts are 0
on all 5 blocks); component and floating-via counts must be preserved. First
attempt used footprint-overlap mapping of ALL baseline polys — falsified by
our own gate (tracks legally moving a full pitch lose footprint overlap);
the immutable-anchor form is your option 2.
DOCUMENTED LIMIT: a swap between two single-anchor isomorphic components is
invisible to any anchor signature; that case is rejected by the per-move
acceptance (the permanent projection-swap control), so the defense is layered
— we do not claim the signature alone catches it.

## Driver credibility redefinition (please review this decision)

v1's 2D projected net-count proxy is now proven under-sensitive (missed the
49 shorts) AND over-sensitive (it flags Rev3's electrically-verified moves on
Blocks 6/7 because they change projected blob counts). `v2_run.py` therefore
keeps the v1 proxy's ANTI-DELETION criterion (conducting area drop <= 2%) and
replaces its count criterion with the anchor-partition gate. The proxy's
component delta is still recorded per block (`conn_proxy_component_delta`) as
information. asu_work/verify.py itself is untouched.

## Permanent controls (new: `asu_v2/tests/`)

`tests/run_controls.sh` — keyless, exits nonzero on failure. 12/12 PASS:
bar positive / upper-island / dropped-contact; track clean-move positive /
projection-swap / patch-foreign-via / M6-V6 refusal; v1-patch positive /
foreign-via; CLI empty-blocks / unknown-pass fail-closed; composer builder
equality. The dropped-contact control found a real bug in our first two-sided
guard before it reached any block — the controls have already paid for
themselves.

## Release verification rerun

Composer builder-equality + byte-identity vs `rev3b` candidates: PASS ×5.
Read-only `python:3.10-slim` emission: byte-identical ×5. Frozen artifacts +
full-hash manifests + `RELEASE_MANIFEST.json` (now binds inputs, refs, emitted
scripts, agent, v2 sources, compare tool, controls file + result, per-block
partition SHA-256s, log hashes, KLayout image ID). Docs corrected (README
commands = Rev3 stack; no remaining "topology check" language for anything
flat; generated agent header describes the actual Rev3 predicates).

## Open

* P1-5 official runner with EXPRESS_MODE_KEY — queued as the final step.
* GO/NO-GO ask: with the two predicates now layer-aware (and per-side), the
  signature complete-coverage + fail-closed, and both your negative controls
  permanent — is Rev3 GO for resubmission after P1-5?
