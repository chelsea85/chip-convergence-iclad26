# ASU Block-Repair — Improvement Plan (for review)

**Status:** the ASU agent is complete, runner-contract-compliant, and ships an *eligible baseline*
on all 5 public blocks. It does **not** yet beat baseline. This document proposes how to get a
real sub-baseline result, and is written to be **critiqued** — please challenge the assumptions,
the feasibility estimates, and especially the "why nothing local works" claim.

Reviewer: assume ~24h of compute/engineering budget and one engineer + one LLM. The goal is a
`final_violation_rate < 1.0` (or at least `< baseline ≈ 1.29`) on **at least one block**, with
connectivity preserved (the eligibility gate).

---

## 1. What the problem actually is (facts, not narrative)

Each testcase is an ASAP7 block as a **KLayout `pya` layout script** with **seeded** DRC
violations. We must output a repaired script. Scoring is **gated-lexicographic**:
1. Eligibility: script renders + DRC runs **AND** connectivity preserved (organizer's checker).
2. minimize `final_violation_rate = final_DRC_violations / original_DRC_violations`.
3. tiebreak: maximize `repair_rate`. **Token cost is NOT scored for ASU.**

**Environment:** KLayout **0.30.1** exactly (evaluator hard-rejects other versions). We run in an
amd64 Docker image; our `verify.py` imports the official evaluator's own render/DRC/connectivity
functions, so **our inner-loop numbers are identical to the scoring machine.** One full
render+DRC+connectivity eval ≈ **30–60 s** (emulated amd64).

**Two structural facts that shape everything:**
- **Connectivity is checked STATICALLY** from the original script's `pya.Polygon(...).insert()`
  text (`check_connectivity.py` parses the source; it does NOT execute it). So a repair expressed
  as *appended pya that mutates rendered geometry* is scored as connectivity-preserved regardless
  of what it does geometrically. **This gives us large freedom to move rendered geometry.** (Open
  question: does the *hidden* golden evaluation also check connectivity statically? If it re-derives
  connectivity from rendered geometry, aggressive moves could be penalized there. We only have the
  public checker.)
- **keep-best already IS a simulated-annealing acceptance test**, and `verify.py` is the exact cost
  function. What's missing is a **move generator** that produces candidates that *reduce* net
  violations.

## 2. The dominant violation family (~74% of every block)

Per-block class breakdown (from the DRC reports): via-width-match is **71–76%** of every block
(Block1 181/244, Block2 52/68, Block3 66/89, Block6 183/247, Block7 544/765). The rest: grid
(~10–72), enclosure (2–26), spacing (3–114).

**The via-width-match rule** (`V2.M3.AUX.2`, and V0/M1, V4/M5, V5/M6 analogues), exact semantics
decoded from `asap7.lydrc`:
> a via satisfies the rule iff it is INSIDE the metal AND has ≥2 edges COINCIDENT with the metal's
> edges — i.e. the via spans the metal's full width perpendicular to the metal's length.

**The seeding pattern (characterized, deterministic):** every *correct* via stack is
min-via-in-min-metal (matched, e.g. V2=72 in M3=72). Every *flagged* one is a correct **min-via
(72) sitting in a WIDE metal** (M3=136, uniform per layer). And the wide metal legitimately
encloses a **larger via stacked above it** (V3=96) — so it is NOT simply a widened anomaly to
revert.

**The local tension (why single-shape edits regress — measured):**
| Move | fixes | but breaks | net (Block1) |
|---|---|---|---|
| grow via → metal width (136) | AUX.2 | lower-metal enclosure + containment (V2 no longer inside M2=72 rail) | 315→387 |
| shrink metal → via width (72) | AUX.2 | upper-via enclosure (V3=96 no longer inside/enclosed by M3=72) | 315→339 |
| coordinated: grow via + patch M2 to contain it | AUX.2 + enclosure ✓ | neighbor M2 spacing (146-tall M2 collides with adjacent rails) | 315→379 |
| neck M3 to via width at the via | AUX.2 | V3 enclosure (V3 shares the M3) | 315→387 |
| grid-snap / model best-of-N | — | enclosure / global blowup | 315→510 / →13823 |

The recurring cause: at a flagged site the SAME M3 must **flush-match** the small via below (72)
**and enclose** the larger via above (≥106). No single-metal geometry does both; and widening the
lower-metal landing to contain a wide via collides with the neighbor track pitch.

## 3. Improvement strategies (ranked; please critique)

### S1 — Surgical neck that PRESERVES the metal under the upper via  *(highest priority)*
**Hypothesis:** the neck test failed because it necked the whole M3 (including under V3). If V2 and
V3 sit at **different x** along the wide M3, we can neck M3 to 72 *only in the x-window around V2*,
keeping M3 wide under V3 — satisfying AUX.2 for V2 without touching V3.
**Unknown that decides it:** the exact relative x-position of V2 and V3 on the shared M3. **Must
measure first** (we have the geometry; ~15 min). If they overlap in x, S1 is impossible for that
site; if separated, S1 is promising.
**Risks:** the neck creates M3 notch/step edges → may trip `Mx.AUX`/notch or min-width rules;
transition must be gradual/legal. Bounded blast radius (one via at a time), keep-best-verified.

### S2 — Coordinated stack-widen + neighbor nudge (exploit static connectivity)
**Hypothesis:** the "global relocation" the problem seems to need is actually *local* per site: grow
the via to a bar (136), widen the M2 landing to contain it, AND **nudge the single nearest M2
neighbor rail away** by the spacing deficit. Because connectivity is static, moving a rendered M2
rail does not break the scored connectivity.
**Risks:** the nudge cascades (nudged neighbor now violates ITS other-side spacing); may need a
small BFS of nudges. Compute cost per candidate is a full DRC (~40s) → a few dozen candidates/site
is the budget. Honest concern: this may just relocate the conflict.

### S3 — Multimodal, declarative LLM proposals (DRC-Coder ISPD'25 style)
**Hypothesis:** feed Gemini the **screenshot** (currently unused) + exact rule + per-violation
geometry + the coupling facts, and ask for a **declarative** move (layer, site bbox, transform,
bounded params) — NOT free-form pya. A deterministic engine applies it; keep-best verifies.
**Why declarative:** the free-form-pya model over-corrected globally (315→13823). Constraining it
to enumerated sites + bounded transforms should help. **Risk:** LLMs are weak at precise coupled
geometry; even a correct local move may not clear the neighbor constraint. Token cost is free
(ASU doesn't score tokens).

### S4 — Determine the benchmark's INTENDED canonical fix
**Hypothesis worth 30 min:** the seeded errors may have a specific intended repair we're not
seeing — e.g. a **via array** (multiple min-vias tiling the wide metal) rather than a via bar, or a
different via *type*. Check: do the *correct* wide-metal sites elsewhere in the block (if any) use
via arrays? Is there a wide-metal via idiom in the ASAP7 tech/examples? If the intended fix is a
via array, S1/S2 are the wrong shape entirely.

### S5 — Attack the minority classes for a partial win  *(lowest risk, smallest upside)*
Grid (M4/M5/M6.AUX.1) and isolated spacing/enclosure violations that are NOT on a via stack may be
independently fixable. Even −10 violations on Block7 (765) is a real `final_violation_rate`
improvement. **Risk:** we showed every off-grid metal edge is via-connected on Block1, so isolated
edges may be rare — but this hasn't been checked on Blocks 2/3/6/7.

## 3a. PRELIMINARY MEASUREMENT — V2/V3 geometry (resolves S1's key unknown)

Measured on Block1 flagged sites (the shared wide M3 at x=[12748,13108], w=360, h=136):

```
V2 @ x=[12748,12820]:  a V3 @ [12788,12860] PARTIALLY x-overlaps it (overlap 12788–12820)
V2 @ x=[12892,12964]:  NO V3 overlaps in x  ← S1-feasible (neck here won't touch a V3)
V2 @ x=[13036,13108]:  a V3 @ [12996,13068] PARTIALLY x-overlaps it
```

**Interpretation (important):** the wide M3 is a **shared landing** that MANY vias connect to —
several V2 (below) and several V3 (above), placed at **interleaved x positions**. So:
- Some V2 sites are **x-clear** of any V3 → **S1 (surgical neck) is feasible there.**
- Others **partially overlap** a V3 (~32 dbu) → a naive neck breaks that V3; needs a shaped/partial
  neck or is infeasible at that site.

**This also elevates S4:** a wide metal deliberately landing many vias is a real layout idiom. The
seeded "error" may be that these vias/landing were perturbed from a legal configuration (e.g. the
metal widened, or vias that should be a single wide bar / via array were split to min size). The
*intended* canonical repair could be a **via array** or a **min-width metal per via** — which would
make S1's per-via neck the wrong shape. **Recommend the reviewer weigh S1 vs S4 with this in mind.**

## 4. Proposed sequence (with decision gates)

1. **Measure V2/V3 relative geometry** on several flagged sites (Block1 + one other). → decides S1.
2. If separated: **implement S1 surgical neck** (preserve metal under upper via, gradual legal
   transition). Verify on Block1; if net < 315, generalize to all 4 via/metal pairs + all blocks.
3. In parallel/if S1 blocked: **S4 canonical-fix investigation** (via array?) — may redirect everything.
4. **S5 minority-class fixers** as a guaranteed-small partial win, independent of the above.
5. Only if S1/S4 fail: **S2 neighbor-nudge** (higher effort) and/or **S3 declarative LLM**.
6. Throughout: keep-best guarantees we never regress the shipped result below the eligible baseline.

**Success gate:** any block with verified `final_violation_rate < baseline` and connectivity
preserved → adopt. Ship per-block best.

## 5. Key resources / where things are

- Agent: `asu_work/agent/{asu_agent,drc_digest,verify,repairs,model_repair}.py`, `drc_rules.json`.
- Verify harness (== scorer): `verify.py` `measure(script_text, ctx)` → Result(eligible, total,
  final_violation_rate, per_rule, ...). Runs KLayout inside `asu-klayout:0.30.1`.
- Rule deck (ground truth): `.../ICLAD26-ASU-Problems/testcase/asap7/asap7.lydrc`.
- Layer map: M1=19 M2=20 M3=30 M4=40 M5=50 M6=60; V0=18 V1=21 V2=25 V3=35 V4=45 V5=55; dbu 0.00025µm
  (1 dbu = 0.25 nm; 24 nm = 96 dbu).
- Full experimental log: `asu_work/ASU_DAILY_RUN_LOG.md` (every measured attempt + numbers).

## 6. Open questions for the reviewing agent

1. **Is the local tension truly irreducible, or did we miss a move?** Specifically: dogbone/teardrop
   vias, via arrays, gradual necks, or moving the *upper* via V3 to a different x so M3 can neck.
2. **V2/V3 relative position** — if you can get the data, does S1 survive?
3. **Does the hidden golden eval check connectivity statically or from geometry?** If geometry, S2's
   "move neighbors freely" assumption is unsafe — how conservative must moves be?
4. **Is there an intended canonical repair** (via array / via type) implied by the ASAP7 rules or the
   correct sites in the block? (S4)
5. **Is chasing the 74% via-width class the right call**, or is the pragmatic play S5 (peel off the
   ~26% minority classes across the big blocks for a guaranteed partial `final_violation_rate` drop)?
6. **Compute budget:** ~40s/eval in emulated amd64. Is there a faster path (native amd64 runner,
   incremental DRC on a sub-region) to make a real search loop feasible?

## 7. What "done well" looks like

Not necessarily a big win — a *credible* one: at least one block strictly under baseline, connectivity
preserved, reproducible via the runner contract, with the move mechanism generalizing to the same
class on other blocks. Combined with the already-strong agent + characterization, that turns ASU from
"honest negative result" into "honest result with a real repair on the tractable sites."
