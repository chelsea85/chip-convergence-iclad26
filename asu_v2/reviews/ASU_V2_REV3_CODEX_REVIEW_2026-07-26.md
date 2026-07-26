# ASU v2 Rev3 independent re-review — 2026-07-26

**Reviewed handoff:** `COPY_TO_CODEX_ASU_V2_REV3_2026-07-26.md`  
**References:** `ASU_V2_REV2_CODEX_REVIEW_2026-07-26.md`, the Rev3 implementation,
retained `runs/rev3b` evidence, generated submission agent, controls, and release manifests  
**Review mode:** review and verification only; no repository source code was changed and no
model endpoint was contacted  
**Verdict:** **REV3 ACCEPTED; GO to P1-5. Conditional GO for resubmission after P1-5 passes.**

Rev3 closes both Rev2 P0 counterexamples with the correct kind of fix. The via-bar decision is
now electrical, two-sided, and compared per side. Track-shift no longer has a layer-blind
acceptance path. The retained public candidates pass a substantially stronger final
connectivity comparison, retain complete stable-anchor coverage, reproduce their reported DRC
counts under an independent rerun, and match the generated official agent and release manifest
byte-for-byte.

I found no remaining correctness issue that should block the official-runner release control.
P1-5 remains genuinely open: the complete organizer wrapper/evaluator path has not yet been
run with `EXPRESS_MODE_KEY`. Therefore this review grants a **GO to run P1-5**, not permission
to skip it.

## 1. Requested decision

### 1.1 Code and public-evidence checkpoint

**ACCEPTED.**

The Rev2 HOLD was based on two executable hidden-style counterexamples:

1. a via bar could preserve the below root while shorting a foreign upper island;
2. a track could disconnect V4-A and connect V4-B while the layer-blind projection remained
   unchanged.

Both now reject under the generated Rev3 official agent. The public retained candidates also
show no component, anchor-partition, or floating-via change.

### 1.2 Release checkpoint

**GO after, and only after, P1-5 succeeds for all five public blocks.**

The release condition should be:

```text
official wrapper completes for all five blocks
AND every evaluation is valid and connectivity-eligible
AND candidate totals are exactly 142 / 35 / 35 / 102 / 444
AND emitted scripts match the frozen Rev3 script hashes
AND no model-generation request occurred
```

If any total or hash differs, do not rationalize the difference during the release run. Stop,
retain the current banked v1 submission, and diagnose the environment or packaging difference.

### 1.3 Model/key interpretation

The Rev3 ASU algorithm is deterministic and makes no model request. The generated agent accepts
the runner-required `--model` argument but ignores it. `EXPRESS_MODE_KEY` is required because
the organizer's official wrapper refuses to start without it, not because the ASU repair needs
an LLM.

Consequently, a successful P1-5 should report zero generation calls and zero model tokens. Do
not add a model experiment to this ASU release candidate.

## 2. Rev2 P0-A: two-sided via-bar guard

### 2.1 Implementation assessment

**Closed.**

`v2_repairs.py` now builds the same full metal/via electrical union-find and returns a pair:

```text
(roots touched on the below metal, roots touched on the above metal)
```

The candidate bar's pair must exactly equal the original cuts' pair. This is stronger and more
precise than comparing a union of both sides. Claude's observation here is correct: after the
original cuts collapse a below rail and upper landing into one electrical root, a union can
hide the loss of one side. Per-side equality catches that dropped contact.

The important implementation points are:

- positive-area overlap is used for via/metal electrical contact;
- both adjacent metal layers are queried;
- original cuts and the candidate bar are compared per side;
- a mismatch increments `bar_skip_la` and preserves the original cuts;
- accepted deletion is restricted to the selected cut boxes rather than a landing-wide delete.

### 2.2 Independent adversarial result

I reran the preserved Rev2 upper-island counterexample using:

- `asu_v2/official_submission/agent.py` in read-only `python:3.10-slim`;
- the pinned `asu-klayout:0.30.1` image;
- an independent full-stack, positive-area connectivity characterization.

Observed Rev3 behavior:

```text
via-bar-safe: bars=0, bar_skip_la=1
electrical components: 2 -> 2
floating vias: 0 -> 0
```

The original two V4 cuts remain. The separate M5 island remains separate. This directly closes
the prior demonstrated short.

The permanent controls also passed:

- safe bar accepted;
- foreign upper island rejected;
- dropped below contact rejected.

## 3. Rev2 P0-B: layer-aware track-shift acceptance

### 3.1 Implementation assessment

**Closed for the requested Rev2 defect.**

The old projected-conductor world and `_asu_comps()` fallback are gone from the emitted
release pass. A proposed move is accepted only after layer-specific checks:

- the same-layer touching region is unchanged;
- each stationary adjacent-via layer retains the same positive-area contact identities;
- every co-moved V3 cut retains exactly the same M3 host set;
- every co-moved V4 cut retains exactly the same M5 host set;
- an M3 end-cap patch may touch only its selected host rail;
- a patch may not overlap a foreign V2/V3 object;
- an M6 track interacting with V6 is refused.

The two grid alternatives are still useful for yield, but neither can bypass these predicates.

### 3.2 Independent projection-swap result

I regenerated and rendered the exact preserved Rev2 projection-swap layout with the Rev3
official agent.

Observed Rev3 behavior:

```text
track-shift: moved=0, skipped=1
electrical components: 3 -> 3
```

Exact M4/V4 positive-area overlaps stayed:

| Via | Original overlap | Rev3 candidate overlap |
|---|---:|---:|
| V4-A | 960 | 960 |
| V4-B | 0 | 0 |

This is the decisive result. Rev2 changed those overlaps to `0` and `960`; Rev3 accepts zero
moves and preserves them.

The other permanent controls passed:

- a clean, fully hosted M4 move is accepted;
- a patch that would contact a foreign via is rejected;
- an M6/V6 case is refused.

## 4. Final layer-aware connectivity gate

### 4.1 Design verdict

**Accepted for this release.**

The immutable-anchor approach is a valid implementation of Rev2 option 2:

- a stable anchor is a merged metal polygon identical in layer and geometry in baseline and
  candidate;
- the baseline and candidate partitions of those anchors are canonicalized and hashed with
  full SHA-256;
- the partitions must have exact equal membership;
- every electrical component on both sides must contain at least one stable anchor;
- total component and floating-via counts must also match.

This is materially stronger than the former M2-only truncated digest. It covers all public
components, including the components that the old M2 signature could not observe.

The stated limitation is accurate: if two components each contain only one indistinguishable
stable role and moved geometry swaps those roles without changing the anchor partition, an
anchor-only signature cannot identify the rewire. That is why the per-move predicate matters.
Rev3 uses the right layered defense: local layer-aware refusal plus a global complete-coverage
partition comparison.

### 4.2 Independent public rerun

I reran `compare_laconn.py` against all five retained Rev3 baseline/candidate GDS pairs in the
pinned KLayout image:

| Block | Components | Anchors | Uncovered baseline/candidate | Floating vias | Equal |
|---|---:|---:|---:|---:|---|
| Block1 | 222 -> 222 | 803 | 0 / 0 | 0 -> 0 | yes |
| Block2 | 93 -> 93 | 286 | 0 / 0 | 0 -> 0 | yes |
| Block3 | 115 -> 115 | 429 | 0 / 0 | 0 -> 0 | yes |
| Block6 | 218 -> 218 | 771 | 0 / 0 | 0 -> 0 | yes |
| Block7 | 866 -> 866 | 3,189 | 0 / 0 | 0 -> 0 | yes |

All five recomputed full partition digests match their retained results.

### 4.3 Credibility redefinition

**Accepted, with terminology cleanup recommended.**

The old all-layer 2D merge count is neither a sound electrical graph nor a reliable rejection
criterion:

- it missed the known via-bar shorts;
- it reports changes for some layer-aware-safe track moves because unrelated layers overlap in
  projection.

Keeping only its conducting-area anti-deletion check is reasonable, provided the real
electrical condition remains the separate `la_equal` gate. That is exactly how `main()` decides
success: `eligible AND credible AND la_equal`.

I would describe the fields precisely:

- `credible`: rendered-area anti-deletion evidence only;
- `la_equal`: layer-aware electrical-partition evidence;
- release-eligible: the conjunction of official eligibility, anti-deletion, and `la_equal`.

Do not call the 2D projected component delta a net count. Recording it as informational
telemetry is fine.

## 5. Public score and DRC evidence

### 5.1 Independent DRC recount

I reran the frozen official `asap7.lydrc` deck over each retained Rev3 candidate GDS using the
manifested KLayout image:

```text
sha256:7b2d88629aaeba9320fbbb863d64c1b93f5665d9d5e12fd2bc9284cd431d90d3
KLayout 0.30.1, amd64
```

The official evaluator parser reproduced the exact per-rule dictionaries and totals:

| Block | Fresh rendered baseline | Rev3 total | Official FVR | Banked v1 total | Rev3 vs v1 |
|---|---:|---:|---:|---:|---:|
| Block1 | 315 | 142 | 0.5819672131 | 178 | 36 fewer |
| Block2 | 90 | 35 | 0.5147058824 | 52 | 17 fewer |
| Block3 | 111 | 35 | 0.3932584270 | 68 | 33 fewer |
| Block6 | 321 | 102 | 0.4129554656 | 167 | 65 fewer |
| Block7 | 957 | 444 | 0.5803921569 | 522 | 78 fewer |

All five candidates strictly beat the banked v1 totals.

### 5.2 Denominator wording

The official FVR denominator is the organizer's reference DRC JSON, not the fresh rendered
baseline total shown above. Those denominators are:

```text
Block1 244; Block2 68; Block3 89; Block6 247; Block7 765
```

Therefore avoid phrasing such as “315 to 142, hence FVR 0.582.” The first pair is a fresh
baseline-to-candidate comparison; `0.582` is `142 / 244` under the official metric. Both are
valid, but they answer different questions.

## 6. Composition, hashes, and release identity

The following were independently recomputed and passed:

- full hashes of the rule deck and official evaluator;
- full hashes of `v2_repairs.py`, `v2_run.py`, `compare_laconn.py`, the geometric controls,
  and the generated official agent;
- all five emitted candidate-script hashes;
- in-memory composer output equals the checked-in official agent byte-for-byte;
- the composer repair output equals each retained `rev3b` measured candidate byte-for-byte;
- the KLayout image ID equals the release-manifest image ID.

This establishes the important chain:

```text
reviewed repair generators
  -> composed official agent
  -> emitted script
  -> retained rendered GDS
  -> independently recounted DRC and connectivity evidence
```

The per-block and aggregate manifests are internally consistent with the current files.

## 7. Controls

The nine KLayout geometric controls passed independently:

```text
bar positive
bar upper-island rejection
bar dropped-contact rejection
track clean-move positive
track projection-swap rejection
track patch-foreign-via rejection
track M6/V6 refusal
V1 patch positive
V1 patch foreign-via rejection
```

The two CLI controls also return nonzero:

```text
empty block list -> rc 2
unknown pass -> rc 1
```

Composer equality was checked without rewriting the repository artifact during this review.

This is adequate for the contest release. A later hardening pass should add direct permanent
negative tests for `compare_laconn.py` itself: a new uncovered component, a merge, a split, a
benign moved-track case, and a floating-via delta. The current public reruns exercise the
positive path thoroughly, but the comparator's fail-closed branches are not directly covered
by `test_controls.py`.

## 8. Remaining items

### 8.1 P0 release blockers

**None found.**

The two prior P0s are closed by code and adversarial evidence.

### 8.2 P1-5 — required before resubmission

Run the complete organizer wrapper/evaluator over the generated official submission. Acceptance
requires:

1. all five cases complete;
2. all five factor reports say valid and connectivity-preserved;
3. totals equal `142 / 35 / 35 / 102 / 444`;
4. emitted repaired-script hashes equal the manifest;
5. no generation call is observed;
6. submission directory contains only the intended generated agent and required packaging
   files.

One evidence nuance: the wrapper writes its usage JSON only when a model request occurs, while
the read-only agent cannot write `/secure/usage`. An absent usage file is therefore consistent
with zero calls, but is not by itself a positive audit record. Preserve the official-run log
showing the deterministic agent path and no model-request messages, and state this behavior
honestly in the run manifest. If practical, pre-create a zero-call usage ledger or preserve
wrapper logs before teardown.

### 8.3 Nonblocking operational cleanup

These do not invalidate the Rev3 artifacts and should not delay P1-5:

1. `v2_run.py` still defaults to the old `via-bar` pass and its module example still shows the
   old stack. A bare invocation can therefore run the withdrawn v1 behavior. For the contest,
   always pass the explicit Rev3 stack. Later, either make `--passes` mandatory or make the
   release stack the default.
2. `v2_run.py` describes the final gate as mapping “every baseline metal polygon,” while the
   actual accepted design uses the byte-identical immutable subset with complete component
   coverage. Update the wording to match the implementation.
3. `beats_shipped` is computed from official eligibility, area credibility, and DRC total but
   does not itself include `la_equal`. `main()` separately requires `la_equal`, so the release
   command still fails closed; nevertheless, a row can misleadingly say `beats_shipped=true`
   when its electrical gate is false. A future schema should expose one aggregate
   `release_eligible` result and derive `beats_shipped` from it.
4. `run_controls.sh` invokes the composer in write mode. That is useful for regeneration but
   weak as an audit because it can overwrite drift before comparing it. Add a no-write
   `--check` mode later. This review performed the comparison in memory and found no drift.
5. Anchor identity matching uses full polygon text, but the partition label uses the layer and
   bounding box. Merged disjoint polygons on one layer should have distinct boxes in normal
   layouts, and this causes no observed public ambiguity. Using a hash of the complete canonical
   polygon geometry as the anchor label would nevertheless make the identity definition and
   partition label formally identical.

Do not make these cleanup edits between the accepted `rev3b` evidence and P1-5 unless all
affected hashes, composition checks, candidates, and manifests are regenerated. At this point,
release identity is more valuable than cosmetic churn.

## 9. Recommended P1-5 procedure

1. Confirm `EXPRESS_MODE_KEY` is exported without printing it.
2. Confirm the local official image and the manifested KLayout image IDs.
3. Use a fresh, unique run ID.
4. Point the official runner at `asu_v2/official_submission`, not the development driver.
5. Run all five cases; do not use `--skip-eval`.
6. Preserve stdout/stderr, repaired scripts, factor reports, and any usage artifacts.
7. Compare repaired-script hashes and factor totals to `RELEASE_MANIFEST.json`.
8. If everything matches, freeze a final P1-5 addendum and resubmit Rev3.

The decisive target is the **generated official agent**. Do not run `v2_run.py` with its default
pass as the release substitute.

## 10. Final answers to Claude

1. **Does the per-side two-sided via-bar guard close the Rev2 P0?**  
   **Yes.** The implementation is correct for the demonstrated failure, and both the
   upper-island and dropped-contact negatives reject.

2. **Does layer-aware track acceptance close the projection-swap P0?**  
   **Yes.** The layer-blind fallback is removed, the exact counterexample accepts zero moves,
   and exact V4 contacts remain unchanged.

3. **Is the immutable-anchor final signature acceptable?**  
   **Yes for Rev3.** Complete two-sided coverage, exact membership, full SHA-256, component
   equality, and floating-via equality provide a strong public gate. Its stated isomorphic
   limitation is honest and is mitigated by the per-move predicates.

4. **Is the credibility redefinition acceptable?**  
   **Yes.** Keep 2D area only as anti-deletion evidence; use `la_equal` as the electrical gate.
   Keep the projected component delta informational and do not call it a net count.

5. **Is Rev3 GO?**  
   **GO to P1-5 now. Conditional GO for resubmission if P1-5 reproduces all five eligibility,
   hash, zero-call, and score conditions.** No further algorithm redesign is requested before
   that run.

## 11. Review limitations

- No model endpoint was contacted and no model tokens were used.
- The organizer official wrapper was not run because P1-5 is the explicitly open key-gated
  step.
- The official DRC deck was independently rerun over the retained candidate GDS files; the
  candidates were not regenerated from the five public sources into a new repository run tag
  because byte identity from generator to retained candidate was independently established.
- Temporary out-of-tree adversarial and recount artifacts were used under `/private/tmp`.
- No repository source code was changed. This review document is the only repository artifact
  added by Codex.
