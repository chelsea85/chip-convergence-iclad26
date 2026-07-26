# ASU v2 independent review — 2026-07-26

**Reviewed input:** `COPY_TO_CODEX_ASU_V2_REVIEW_2026-07-26.md`  
**Review mode:** documentation and read-only/keyless verification; no source-code changes and
no model calls  
**Decision:** **NO-GO for the current package as a correctness-preserving resubmission.**

The reported DRC improvement is real and the official agent reproducibly emits the measured
scripts. The new v2 delta also preserves a stronger, layer-aware public-block connectivity
partition relative to the already-submitted v1 output. Those are substantial positives.

The blocker is that the inherited v1 `via-bar` pass does **not** preserve layer-aware electrical
connectivity relative to the original rendered public layouts on four of five blocks. The
project-local `credible` check cannot detect this because it merges every conductor layer into
one two-dimensional projection. The official checker also cannot detect it because it parses
the original static source constructs and does not interpret the appended KLayout mutations.

This means that the packet's statements “connectivity-preserved,” “rendered-geometry net
component,” and “the same quantity as the credibility gate” are not adequate evidence of
physical connectivity preservation. The package may still be *eligible under the published
scorer*, but that is a different and narrower claim.

## 1. Verdicts on the packet's three questions

### 1.1 Any blocking correctness risk?

**Yes. Three are blocking.**

1. **P0 — the inherited via-bar repair merges layer-aware electrical components on four public
   blocks.**
2. **P0 — the blind hidden-case track-shift safety proof is incomplete.** All 149 accepted public
   track moves used the fast path, while 119 M3 patch polygons were added outside the fast
   contact-set comparison.
3. **P0 — the safety universe stops at M6/V5** even though the official block stack continues
   through M10/V9.

The v2-only public delta looks safe under the stronger characterization performed in this
review, but the emitted algorithm does not enforce that stronger property on hidden cases.

### 1.2 Is blind hidden-case application acceptable?

**Not in the current form.**

It is acceptable only after the pass fails closed for unsupported stack content and its
acceptance predicate covers every geometry mutation, including M3 patches. “No off-grid
tracks means no move” is useful but insufficient: a hidden block can contain an eligible
off-grid M6 track connected through V6/M7, which the current safety universe does not include.

The statement that v2 has “the same risk profile as v1” is also too broad. The current v2
agent performs 149 track translations and inserts 119 M3 patch polygons on the public set.
That is materially more geometric activity than v1, even though the measured public
layer-aware partition remained unchanged relative to v1.

### 1.3 What is required before resubmission?

The P0 connectivity issues below must be resolved or explicitly accepted by the organizers.
The full official-runner rehearsal is then a required release control, not merely an optional
one. A wrapper rehearsal alone will not resolve the connectivity issue.

## 2. What was independently confirmed

### 2.1 Score and evidence consistency

The retained `asu_v2/runs/final1/summary.json`, DRC reports, render logs, submission scripts,
and manifests agree on:

| Block | Original violations | v2 violations | v2 FVR |
|---|---:|---:|---:|
| Block1 | 315 | 77 | 0.3155737705 |
| Block2 | 90 | 19 | 0.2794117647 |
| Block3 | 111 | 35 | 0.3932584270 |
| Block6 | 321 | 60 | 0.2429149798 |
| Block7 | 957 | 234 | 0.3058823529 |

The parity evidence reproduces the shipped v1 totals `178/52/68/167/522`.

### 2.2 Official-agent composition and clean emission

The official agent's three generated snippets matched the development generators, and its
five emitted scripts matched both the measured `final1` candidate and the frozen submission
script. A read-only cached `python:3.10-slim` container, with bytecode disabled and no KLayout,
produced these full SHA-256 values:

| Block | Emitted script SHA-256 |
|---|---|
| Block1 | `b546cfab151e46827487bd6b6c295356913fc3e8ab0fb6c03d4fcac47eae8430` |
| Block2 | `824ec9b869ae3bcb1c26f089f24133a1015a8f445f1cb649f4d9d1f3cb443aca` |
| Block3 | `1ce5b335ba8fe42ba090b428eedee6fed76ce9aabb9198f5478b0873f2afdb3a` |
| Block6 | `b65149db494e868bea396cc5c2736a63afab14eda7a03663155721c1de3d52c3` |
| Block7 | `2b11ad90689490d62b8cce5c37d7d0868dc59a4d25b76cca55275ab8c1f794a7` |

This confirms the Python 3.10/read-only/output-composition claims without a model key.

### 2.3 The v2 delta preserves the public v1 layer-aware partition

I constructed a read-only KLayout 0.30.1 characterization that:

1. merges polygons only within each metal layer;
2. connects adjacent metal-layer components only through the corresponding via layer;
3. requires positive-area via/metal overlap;
4. covers the official block stack from M1/V1/M2 through M9/V9/M10;
5. compares stable M1/M2 and M2-only anchored net partitions.

The full v2 output retained exactly the same electrical-component count and M2-anchored
partition as the shipped v1 output on all five public blocks:

| Block | v1 components | v2 components | v1→v2 | M2 partition |
|---|---:|---:|---:|---|
| Block1 | 202 | 202 | 0 | exact match |
| Block2 | 91 | 91 | 0 | exact match |
| Block3 | 115 | 115 | 0 | exact match |
| Block6 | 213 | 213 | 0 | exact match |
| Block7 | 844 | 844 | 0 | exact match |

The track-shift-only output also retained the exact combined M1/M2 anchored partition on all
five blocks. Block7's full-output M1-based hash changes, as expected, because `v1-patch`
modifies one M1 polygon; its M2-only partition remains identical.

This is strong evidence that **track-shift plus v1-patch did not add a public-block short or
open relative to v1**. It does not cure the inherited v1 issue and it does not prove hidden
behavior.

## 3. Blocking findings

### P0-1 — The v1 via-bar pass changes layer-aware public connectivity

The same layer-aware characterization was applied to each original public GDS and its v1
via-bar output:

| Block | Original components | v1 components | Change |
|---|---:|---:|---:|
| Block1 | 222 | 202 | **−20** |
| Block2 | 93 | 91 | **−2** |
| Block3 | 115 | 115 | 0 |
| Block6 | 218 | 213 | **−5** |
| Block7 | 866 | 844 | **−22** |
| **Total** | **1,514** | **1,465** | **−49** |

The metal-component counts are unchanged and no via in this characterization is floating.
The M2-anchored partition hashes also change on the four affected blocks. Therefore these are
not artifacts caused by counting loose via polygons; the continuous via bars introduce new
cross-layer connections between previously distinct anchored components.

This behavior is consistent with the implementation in
`asu_work/agent/repairs.py`: a bar spans the full length of an upper-metal landing. Where
multiple lower-metal components cross that landing, the continuous via shape can electrically
join them.

#### Why the existing gates miss it

`asu_work/agent/verify.py:62-71` unions M1–M6 and V0–V5 into one flat 2D region. Metal shapes on
different layers that merely overlap in XY are therefore treated as connected even when no
legal via joins them. The comments at `verify.py:53-55` and `verify.py:70-71` call this a
via-linked net count, but the implementation is a layer-blind projection.

The official checker is a source parser. Its regex-based trace sees the original polygon and
instance declarations, but not the appended dynamic repair operations. Consequently,
`eligible=true` is correct under the published checker while not demonstrating rendered
electrical equivalence.

#### Required disposition

Choose one explicitly:

1. **Correctness path (recommended):** constrain/rework via-bar so that a replacement via may
   not join more than the same below/above metal-component pair as the original cuts, then
   require exact original→candidate layer-aware anchored-partition equality.
2. **Organizer-semantics path:** show the organizers this case and obtain explicit confirmation
   that eligibility is intentionally defined only by the published source checker, even when
   rendered layer-aware connectivity changes. If this path is chosen, remove the physical
   “connectivity-preserved” claim and say only “passes the published source-connectivity
   checker.”

Without one of those dispositions, the present package should not be represented as a
correctness-preserving repair.

### P0-2 — The fast-path proof excludes inserted patches

The packet correctly identifies this gap. It is not merely theoretical in the public workload:

| Block | Accepted track moves | Added M3 patch polygons |
|---|---:|---:|
| Block1 | 27 | 20 |
| Block2 | 9 | 7 |
| Block3 | 9 | 7 |
| Block6 | 29 | 22 |
| Block7 | 75 | 63 |
| **Total** | **149** | **119** |

The render statistics report `moved_gc=0` for every block. Thus every finally accepted public
move was accepted through the fast contact-set branch. Four global checks occurred while
trying displacement candidates, but none was the acceptance route.

At `asu_v2/agent/v2_repairs.py:106-107`, `moving` contains the track and riding cuts.
Patches are inserted at lines 162-166, but the post-move set at line 169 still tests only
`moving.transformed(tr)`. A patch can therefore change M3 contacts without affecting the XOR
predicate.

The stronger post-run characterization found no v2-added public partition change, so the
committed public artifacts are reassuring. The emitted hidden-case algorithm remains
fail-open at the exact point the packet identifies.

**Required:** include patch contacts in the acceptance predicate and add positive and negative
controls proving that a patch which touches a foreign M3 component is rejected. A final
layer-aware candidate check should be retained as evidence; the current flat component count
is not an electrical-equivalence check.

### P0-3 — The safety universe omits supported upper routing layers

The official checker defines the block stack through M10/V9
(`check_connectivity.py:76-80`). The v2 safety universe contains only M1–M6 and V0–V5
(`v2_repairs.py:29-30`).

The pass moves M6 but does not co-translate V6 and does not include V6/M7 in its local or
global proxy. A hidden block containing M6-to-M7 connectivity can therefore be altered
without that connection participating in the safety decision.

**Fastest safe correction:** make track-shift fail closed/no-op when any unsupported
upper-stack conductor is present, and specifically refuse an M6 move that interacts with V6.
The more general correction is to model the full official stack layer-by-layer.

## 4. P1 release and evidence findings

### P1-1 — `v2_run.py` returns success after failed gates

`v2_run.py:173-177` computes `ok` and `parity`, prints them, and always returns zero.
It also records `beats_shipped` without enforcing it. A parity or final run can therefore
fail its stated release condition while shell automation still succeeds.

The release command must exit nonzero on:

- any render/DRC/connectivity/credibility failure;
- a parity mismatch during a parity run;
- any final block that does not strictly beat the banked result;
- a missing/empty block selection.

### P1-2 — The official-agent header still describes v1, not v2

`asu_v2/official_submission/agent.py:18-25` says the winning repair is only via-bar and that the
agent emits the byte-identical `asu_work/submission` v1 artifact. The executable code emits
via-bar + track-shift + v1-patch. This is a material handoff error even though runtime behavior
is correct.

### P1-3 — Builder equality is claimed but not preserved as a test

The README says the snippet builders are asserted equal to the development generators. I found
no permanent assertion/regression under `asu_v2`. The equality is true today—I independently
confirmed it—but it should be an executable, keyless release test to prevent drift.

### P1-4 — Manifests are too thin for the stated assurance

Each manifest records only a 16-hex script digest prefix plus summary metrics. It does not bind:

- the full input-script, rule-deck, evaluator, connectivity-reference, or official-agent hash;
- the full emitted-script hash;
- the KLayout image ID/version;
- per-rule counts;
- original, v1, and v2 connectivity signature values;
- render/DRC log hashes;
- the official-agent-to-measured-artifact equality result.

Use full SHA-256 values and make one top-level release manifest bind the entire five-block
packet.

### P1-5 — The complete official flow remains unexercised for v2

The clean Python 3.10 emission path passed. The complete
`official_eval/run_official_eval.py` path was not run in this review because it unconditionally
requires `EXPRESS_MODE_KEY` and starts the model wrapper even though this agent makes no model
requests.

After the P0 disposition, run all five blocks through the exact official submission path and
retain the factors, agent logs, wrapper usage showing zero calls/tokens, output hashes, and
evaluator reports.

## 5. Recommended release sequence

Given the short contest timeline, use this order:

1. **Stop the current resubmission. Keep the already-banked v1 result.**
2. Reproduce P0-1 with the organizers or adopt a layer-aware public test in the project.
3. Decide correctness path versus explicit organizer-semantics path.
4. If pursuing correctness, repair via-bar first; do not spend time tuning residual DRC until
   original→candidate anchored connectivity is exact on all five blocks.
5. Close the patch fast-path and upper-stack fail-closed gaps.
6. Add permanent positive/negative connectivity controls and make `v2_run.py` fail closed.
7. Regenerate full manifests from a clean run.
8. Run the exact official wrapper/evaluator flow on all blocks.
9. Resubmit only after one person reviews the final emitted hashes and factor files.

## 6. Risk-calibrated final decision

### Correctness-preserving submission

**NO-GO.** The present evidence disproves rendered layer-aware connectivity preservation from
the original on four public blocks.

### Published-scorer optimization

**Technically likely to score and clearly better on public DRC**, because:

- the source-based official checker reports eligible;
- the scripts render and DRC successfully;
- the official agent emits the measured artifacts deterministically;
- v2 does not add a detected public layer-aware partition change relative to banked v1.

I do not recommend silently treating that as a correctness GO. It relies on the difference
between the scorer's source model and the rendered physical effect. If the team deliberately
chooses this route, it should do so with organizer awareness and precise language.

## 7. Review limitations

- No source code was changed.
- No model endpoint was contacted and no model token was used.
- The clean emission check used the cached Python 3.10 image.
- The KLayout characterizations used the pinned local `asu-klayout:0.30.1` image and retained
  GDS artifacts.
- I did not rerun all DRC jobs from source in a fresh tag or execute the key-dependent official
  wrapper. The retained DRC/evaluator evidence was audited for consistency.
- The layer-aware characterization is geometric extraction, not a sign-off LVS tool. It is
  nevertheless materially stronger than the current layer-blind projection and provides a
  concrete positive-area connectivity counterexample to the packet's preservation claim.
