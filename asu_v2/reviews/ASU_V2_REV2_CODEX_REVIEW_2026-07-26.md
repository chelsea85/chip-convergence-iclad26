# ASU v2 Rev2 independent re-review — 2026-07-26

**Reviewed input:** `COPY_TO_CODEX_ASU_V2_REV2_2026-07-26.md`  
**Reference:** `ASU_V2_CODEX_REVIEW_2026-07-26.md`  
**Review mode:** read-only/keyless implementation and evidence review; no model calls  
**Verdict:** **HOLD / NO-GO for blind correctness-preserving resubmission.**

Rev2 is a substantial and honest improvement. It removes the 49 public electrical merges from
the proposed package, preserves the public original component counts, still beats the banked
v1 result on every block, fixes the missing-patch predicate input, covers the full published
stack, makes the release driver fail closed, generates the official agent from the measured
sources, and supplies a materially better release manifest.

Two focused P0 gaps remain. Both are ordinary geometric hidden cases—not in-process evidence
forgery—and both were reproduced with the generated official agent and pinned KLayout image:

1. `via-bar-safe` compares only **below-metal** electrical roots. It accepts a bar that preserves
   the below roots while shorting a separate upper-metal island.
2. Track-shift still compares a **layer-blind 2D projection**. It can disconnect one upper net
   and connect a different upper net while the projected fast-path predicate, total
   layer-aware component count, floating-via count, and M2 partition hash all remain unchanged.

Running P1-5's official wrapper will not close either gap. Rev2 should become GO after these two
acceptance predicates are made layer-aware and permanent negative controls are retained.

## 1. Answers to the three Rev2 questions

### 1.1 Does the via-bar-safe root-set guard close P0-1?

**It closes the demonstrated public 49-short regression, but not the general hidden-case
condition.**

The public result is valid:

| Block | Original components | Rev2 components | Result |
|---|---:|---:|---|
| Block1 | 222 | 222 | equal |
| Block2 | 93 | 93 | equal |
| Block3 | 115 | 115 | equal |
| Block6 | 218 | 218 | equal |
| Block7 | 866 | 866 | equal |

However, `v2_repairs.py:301-315` computes and compares only `below_roots`. A via connects two
adjacent metal layers. Preserving only one side is insufficient when the proposed bar can
touch additional upper-metal geometry.

**Required correction:** compare the complete electrical-root set touched on **both adjacent
metal layers** by the original cuts and by the candidate bar. The safe predicate should be
conceptually:

```text
roots(original cuts, below + above) == roots(candidate bar, below + above)
```

Using already-collapsed electrical roots is appropriate: contacting additional geometry that
is already in the same electrical root does not change topology; contacting a foreign root
must reject the bar.

### 1.2 Are there remaining hidden-case fail-open paths?

**Yes—two were demonstrated.**

- The one-sided via-bar guard described above.
- The track-shift projected-contact predicate plus incomplete final signature.

Full-stack enumeration and the M6/V6 refusal are good fixes, but “full stack” does not make a
flat projection layer-aware. The slow `_asu_comps()` fallback remains the same type of flat
union, now over more layers.

### 1.3 Is Rev2 GO after P1-5?

**No.** P1-5 is still required, but it is not sufficient.

GO requires:

1. two-sided via-bar root equality;
2. layer-aware track-move acceptance;
3. a complete stable-anchor final connectivity signature;
4. permanent positive and negative regression controls for both failures;
5. a clean five-block rerun, regenerated manifests, then P1-5.

## 2. What Rev2 successfully closes

### 2.1 The public v1 short regression is removed

The `safe3` candidates preserve original→candidate layer-aware component counts on all five
blocks. I also reran an independent positive-area, per-layer metal/via characterization over
the retained GDS files.

For Blocks 1, 2, 3, and 6, the stronger combined M1+M2 anchored partition hash is exactly
identical before and after. Block7 retains the exact M2 partition and component count; its
M1-based geometry hash changes because the one accepted `v1-patch` intentionally enlarges an
M1 polygon.

The public DRC improvements are internally consistent:

| Block | v1 banked total | Rev2 total | Rev2 FVR | Beats v1 |
|---|---:|---:|---:|---|
| Block1 | 178 | 142 | 0.5819672131 | yes |
| Block2 | 52 | 35 | 0.5147058824 | yes |
| Block3 | 68 | 35 | 0.3932584270 | yes |
| Block6 | 167 | 109 | 0.4412955466 | yes |
| Block7 | 522 | 444 | 0.5803921569 | yes |

This is the correct trade: less aggressive DRC reduction in exchange for removing known
electrical shorts.

### 2.2 The M3 patch omission is fixed as written

`v2_repairs.py:192-204` now inserts the patches into `patchreg` and includes them in the
post-move contact query. That closes the exact omission reported in Rev1.

The remaining issue is not that patches are absent; it is that `world` is still merged across
unrelated layers before the comparison.

### 2.3 Full-stack enumeration and M6/V6 refusal are implemented

`_ASU_COND` now includes M1 through pad/M10 and V0 through V9. M6 moves interacting V6 are
refused and recorded with `skip_upper`. This closes the prior M6/V6 omission.

### 2.4 The release driver is fail closed

`v2_run.py` now:

- rejects an empty block selection;
- exits nonzero on any eligibility, credibility, or `la_equal` failure;
- supports explicit `--require parity|beat`;
- exits nonzero when the selected release condition is not satisfied.

This closes P1-1.

### 2.5 Composition and clean Python 3.10 emission pass

The composer reported:

- builder equality: pass;
- byte identity against all five `safe3` candidates: pass.

The generated official agent was then loaded in a read-only `python:3.10-slim` container. Its
five emitted full hashes matched the release manifest:

| Block | Emitted SHA-256 prefix |
|---|---|
| Block1 | `5d1fe73f57557423…` |
| Block2 | `e56c0d676f9fa8f8…` |
| Block3 | `6241d0cb95afa816…` |
| Block6 | `870ade29dc6be118…` |
| Block7 | `1e63dfa64ef3bb36…` |

The core release-manifest hashes for the deck, evaluator, agent, v2 sources, characterization
tool, and five submission scripts also matched the files on disk.

## 3. P0-A — via-bar-safe is one-sided

### 3.1 Implementation issue

The helper correctly builds a full-stack electrical union-find. The acceptance code then
reduces it to:

```python
def below_roots(reg, rb):
    return set(find(t) for t in hits(below_ln, reg, rb))
```

It compares the bar and original cuts only on `below_ln`. The upper metal is not queried.

The assumption that the bar remains associated with only one upper landing is not sufficient:

- a merged landing may be nonrectangular;
- the candidate bar spans its bounding box;
- another upper-metal island can exist inside that bounding box;
- the bar can touch that island even though the original cuts did not.

### 3.2 Reproduced negative control

I constructed a supported V4/M4/M5 layout:

- one M4 root under two original V4 cuts;
- one U-shaped M5 landing connected through those cuts;
- a separate M5 island inside the U-shaped landing's bounding box.

The candidate continuous V4 bar touches the same single below-metal root as the original cuts,
so the current guard accepts it. It also touches the separate M5 island.

Observed result:

```text
via-bar-safe: bars=1, bar_skip_la=0
layer-aware components: 2 -> 1
```

This is a direct upper-side short. A complete original→candidate development gate catches the
component-count change, but the blind official agent cannot use that post-run result to revert
the bar on a hidden case.

### 3.3 Required regression

Retain this topology as a keyless KLayout test:

- positive control: bar touches the same roots on both sides → accepted;
- negative control: bar adds a foreign upper root → rejected;
- negative control: bar drops an original upper or lower root → rejected.

## 4. P0-B — track-shift can rewire nets while every Rev2 gate stays equal

### 4.1 Why full-stack projection is still insufficient

At `v2_repairs.py:83-85`, every nonmoving layer is collected into `CONDR`. At lines 122-133,
the regions are added together and merged without layer identity. The before/after queries at
lines 134-135 and 200-204 therefore compare projected geometry, not electrical roots.

Two unrelated objects on different layers can overlap or touch in projection and become one
`world` polygon. A moved track may stop contacting one physical via and start contacting
another while both queries return that same projected polygon.

The slow path at lines 206-208 does not close this: `_asu_comps()` also unions all layers in
2D.

### 4.2 Reproduced negative control

I constructed a supported M4/V4/M5 case:

- one off-pitch M4 track moves from `y=48..144` to `y=0..96`;
- stationary V4-A connects M4 to M5-A before the move but not after it;
- stationary V4-B connects M4 to M5-B after the move but not before it;
- an unrelated M1 polygon joins A and B only in the layer-blind XY projection.

The generated Rev2 agent reported:

```text
track-shift: moved=1, moved_gc=0, comp_checks=0
```

The physical contacts changed:

| Via | Original M4 overlap area | Candidate M4 overlap area |
|---|---:|---:|
| V4-A | 960 | 0 |
| V4-B | 0 | 960 |

Yet the Rev2 characterization reported:

```text
components: 3 -> 3
floating_vias: 0 -> 0
M2 partition: unchanged (empty)
```

Therefore the exact `la_equal` expression at `v2_run.py:145-147` evaluates true even though
M4 was rewired from M5-A to M5-B.

This is not a hash-collision argument. It is an anchor-coverage and layer-identity failure.

### 4.3 Required correction

The fastest safe solution is to make each move's acceptance signature layer-specific:

- M4 same-layer neighbors must remain the same;
- moved V3 cuts must touch the same M3 electrical roots before and after, including patches;
- moved V4 cuts must touch the same M5 electrical roots before and after;
- M5 moves must retain the same stationary V4 and V5 electrical contacts;
- M6 moves must retain the same V5 contacts and continue to refuse any V6 interaction;
- if any relevant root/contact identity cannot be established, revert the move.

Do not use the flat global component count as an alternative acceptance path. Replace it with a
layer-aware electrical predicate or remove the fallback.

Retain the projection-swap case above as a negative test. It must produce zero accepted moves.

## 5. P1 — final connectivity signature is incomplete

`characterize_laconn.py:80-91` hashes only the partition of M2 polygon bounding boxes and
truncates the digest to 16 hex characters. `v2_run.py` combines that with total component count
and the number of floating vias.

M2 does not anchor every public electrical component. In the retained public baselines:

| Block | Total components | Components with an M2 anchor |
|---|---:|---:|
| Block1 | 222 | 120 |
| Block2 | 93 | 45 |
| Block3 | 115 | 64 |
| Block6 | 218 | 103 |
| Block7 | 866 | 410 |

Consequently, compensating merge/split or rewiring among unanchored components can pass. The
projection-swap control proves this behavior.

**Required:** fingerprint the partition of stable anchors covering every baseline electrical
component. Suitable approaches include:

1. map every original M1/M2/pin polygon into the candidate's layer-aware component and compare
   the complete partition;
2. use all immutable source/pin anchors and fail closed if a component has no stable anchor;
3. compare an explicit layer-aware connectivity graph with canonical stable node identities.

Use full SHA-256, retain the actual baseline and candidate signatures, and require exact
membership—not merely equal component and floating-via counts.

## 6. P1 — claimed negative controls are not permanent tests

No test file exists under `asu_v2`, and I found no preserved executable control for:

- foreign M3 patch contact;
- foreign upper-metal bar contact;
- dropped bar contact;
- M6/V6 refusal;
- layer-projection contact swap;
- incomplete M2 anchor coverage;
- fail-closed CLI modes.

The composer is a valuable composition regression, but it verifies byte identity, not geometric
safety. The packet should not call an observation in a public run a positive/negative control
unless the negative case is explicitly constructed and asserted.

## 7. P1-5 and release documentation

The complete key-dependent official runner remains open and is still required after the P0
fixes.

Two documentation issues should be corrected in the same release:

- `asu_v2/README.md` still shows the old `via-bar` commands rather than the Rev2 stack and
  `--require beat`.
- Comments and the generated header should stop calling flat `_asu_comps()` a topology or
  full-stack electrical check. It is a full-stack **projected conductor-region count**.

## 8. Focused acceptance checklist for Rev3

Do not redesign the entire flow. A focused Rev3 is sufficient:

- [ ] via-bar compares original/candidate roots on both adjacent metal layers;
- [ ] upper-island bar negative control rejects;
- [ ] track acceptance is layer-aware and has no flat-count acceptance fallback;
- [ ] projection-swap negative control accepts zero moves;
- [ ] patch foreign-root negative control is permanent and rejects;
- [ ] M6/V6 negative control is permanent and rejects;
- [ ] final signature covers every baseline component with stable anchors;
- [ ] signature uses full SHA-256 and exact membership;
- [ ] fail-closed CLI behavior has keyless tests;
- [ ] all five public blocks rerun with `--require beat`;
- [ ] composer equality and clean Python 3.10 emission rerun;
- [ ] release manifest regenerated and audited;
- [ ] official runner P1-5 passes with zero model calls/tokens.

## 9. Final assessment

### Public `safe3` artifacts

**Accepted as a genuine, connectivity-improved correction over the withdrawn Rev1 package.**
The known public 49-short defect is gone and the retained public evidence is internally
consistent.

### Blind hidden-case algorithm

**HOLD.** The current emitted algorithm still has two concrete layer-awareness failures.

### Resubmission

**NO-GO until the focused Rev3 checklist above is complete.** Once the two predicates and final
signature are corrected, the remaining work is conventional release verification rather than
another architectural review.

## 10. Review limitations

- No model endpoint was contacted and no model token was used.
- No source-code content was changed; only this review document and temporary out-of-tree
  geometric probes were created.
- The five public DRC jobs were not rerun from source in a new tag. Their retained reports,
  GDS outputs, logs, composition equality, hashes, and connectivity signatures were audited.
- The generated official agent was exercised in cached Python 3.10 and the geometric probes
  used the pinned local `asu-klayout:0.30.1` image.
- The complete official wrapper/evaluator flow was not run because it requires the organizer
  key.
