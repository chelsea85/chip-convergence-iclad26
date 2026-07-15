# ASU Block-Repair Track — Daily Run Log

Third contest track (ASU): repair ASAP7 KLayout Python layout scripts to reduce DRC
violations while preserving connectivity. Scoring is gated-lexicographic: eligibility
(valid render+DRC AND connectivity preserved) → minimize `final_violation_rate` →
tiebreak maximize `repair_rate`.

## 2026-07-14 — Step 1: environment + baseline (GO/NO-GO) → **GO**

**Environment (Docker, exact-version).** Organizers score with **KLayout 0.30.1** on the host
and the evaluator hard-rejects any other version (string-equality on `klayout -v`). macOS
Homebrew only offers 0.30.9 (also hit Gatekeeper quarantine) → abandoned that path. Built an
amd64 Docker image (`asu_work/docker/Dockerfile`): Ubuntu 24.04 + the pinned
`klayout_0.30.1-1_amd64.deb` from klayout.org + google-genai/shapely. Host is Apple Silicon
(arm64) so the container runs under Docker emulation — slower but version-exact and matches how
the organizers evaluate. `docker run ... klayout -v` → **KLayout 0.30.1**.

**Pipeline verified end-to-end** on the unmodified Block1 (zero model calls): render → GDS →
ASAP7 DRC → connectivity check → factors JSON all run inside the container. `valid_repair=True`,
`connectivity_preserved=True` (824 sources), `eligible_for_scoring=True`.

**Calibration finding (important, understood).** Feeding the *unmodified* script back scores
`final_violation_rate = 1.29`, not 1.0 — our container DRC finds 315 violations vs the reference
report's 244. Per-rule diff shows **11/14 rules match the reference EXACTLY** (V2.M3.AUX.2=72,
V4.M5.AUX.2=48, V0.M1.AUX.3=37, all S-rules, …). The gap is **3 metal AUX.1 rules inflated by
clean integer factors**: M4.AUX.1 18→72 (4×), M5.AUX.1 8→16 (2×), M6.AUX.1 3→12 (4×). Diagnosis:
a shape-representation/multiplicity artifact when the layout *script* is rebuilt to GDS (the
reference 244 was recorded from a merged/canonical form). NOT an environment mismatch — the exact
match on 11 rules proves the DRC deck + version are calibrated. Those inflated AUX.1 rules are
also extra repair surface. **To investigate in step 2:** whether a shape-merge/cleanup in the
script removes the multiplicity (free wins) and whether the organizers' denominator is the
recorded 244 (fixed) or a re-run — either way, local iteration in this container is trustworthy
because it is the scoring environment.

**Workspace:** `asu_work/{docker,agent,baselines,runs}`; contest tree untouched (venv + Docker
mount only). 5 public blocks: Block1/2/3/6/7.

**Verdict: GO.** Environment is version-exact and calibrated, full pipeline runs locally with
zero-token DRC diagnosis available, connectivity gate works. Proceed to build the repair agent.

## 2026-07-14 — Step 2: agent built, verify+keep-best proven, deterministic passes characterized

**Agent (`asu_work/agent/`, stdlib + pya, mirrors our NVIDIA/NXP design):**
- `drc_digest.py` — DRC report → per-rule findings, classified by fix-kind (grid/spacing/
  enclosure/width/area) from the rule DESCRIPTION text. Zero tokens. Block1: 244 ref violations,
  14 rules; biggest = via-width-match AUX.2 (V2.M3/V4.M5/V0.M1/V5.M6 = 181), then grid AUX.1.
- `verify.py` — render + DRC + connectivity measured with the OFFICIAL evaluator's OWN functions
  (imported), so inner-loop numbers are identical to the scoring machine. Reproduces baseline
  exactly (total=315, fvr=1.29, eligible, connectivity preserved 824 sources).
- `repairs.py` — deterministic geometric passes emitted as pya code appended to the ORIGINAL
  script (original untouched → connectivity preserved by construction; pass runs before write).
- `asu_agent.py` — runner contract (info.json → output + usage) + keep-best loop (gated-
  lexicographic, matches contest): try candidates, keep best ELIGIBLE, always ship (baseline is
  the eligible floor).
- `model_repair.py` — stub/vertex/endpoint models; model writes a pya fix-pass, verified +
  kept-only-if-better.

**Key finding — naive geometric repair regresses; keep-best protects us.** Grid-snap eliminated
ALL grid violations (M4/M5/M6.AUX.1: 72/16/12 → 0, −102) but broke via enclosure (V3.M4.EN.2
0→97, V3/V4.AUX.1 0→48 each) → net 315→510. Outward-snap (grow-to-grid, enclosure-preserving)
was worse still (spacing blowout: 315→1451). Both modes, all layer subsets: every deterministic
whole-layer pass REGRESSED and was correctly DISCARDED → agent ships eligible baseline (fvr 1.29,
connectivity intact). Lesson: metal edges are coupled to their vias/neighbours; repair must be
surgical (per-flagged-edge, enclosure-aware) or model-guided. The verification-first keep-best
architecture guarantees we never ship worse-than-baseline and never break connectivity — the same
"always ship eligible" discipline as NXP.

**Env:** version-exact KLayout 0.30.1 in amd64 Docker (`asu_work/docker/Dockerfile`); agent runs
inside the image (klayout on PATH). Container info.json needs host→/asu path remap for local runs
(the contest runner writes env-correct paths).

**Model path validated (Key 1 recovered).** Single vertex call on Block1 succeeded; the model's
one-shot pya fix-pass rendered ineligible → correctly discarded → baseline shipped. Full agent now
exercises all three paths (deterministic / model / keep-best) end-to-end and safely ships the
eligible baseline when nothing beats it.

**Honest status:** ASU block-repair is dense-layout legalization — a genuinely hard problem where
neither naive geometric passes nor one-shot model repair beat the eligible baseline in the time
available. What we HAVE is a complete, runner-contract-compliant, verification-first agent that
(1) never ships worse than the eligible baseline, (2) never breaks connectivity, (3) measures
identically to the official scorer, (4) has zero-token DRC diagnosis + keep-best — the same thesis
as our NVIDIA/NXP tracks. A real improvement needs surgical per-edge enclosure-aware repair (future
work) or best-of-N model passes with more budget.

## 2026-07-14 — Step 3: rules library + model path; the coupled-conflict-graph finding

Built `drc_rules.json` (structured DRC-repair rule library: per-rule-class coordinated transform
+ coupling hazards + provenance from rule semantics / EDA legalization literature [MDPI Electronics
2025 SA-based standard-cell DRC repair; EDN cut-slide/merge; USPTO 7,380,227 enclosure] / our
measurements). Wired into digest (rule-matching) + model prompt (structure-matched injection, like
the NVIDIA 45-rule playbook) + best-of-N model loop with code-compile validation and render-error
repair feedback.

**Exhaustive candidate-generation results on Block1 (baseline 315 violations, fvr 1.29):**
| approach | result | why it fails |
|---|---|---|
| grid-snap nearest (whole layer) | 315→510 | moves via-enclosing edges → V*.EN + V*.AUX blow up |
| grid-snap outward | 315→1451 | grow-to-grid → spacing blowout |
| via-aware grid-snap (via-free only) | 315→315 (0 edits) | EVERY off-grid edge is via-connected |
| grow via → metal width | 315→387 | breaks lower-metal enclosure + via grid |
| shrink metal → via width | 315→339 | breaks upper-via enclosure + grid |
| model best-of-N (coupled-stack prompt) | 315→13823 / 23057 | over-corrects globally |

**Finding (robust, literature-consistent):** Block1's seeded violations form a TIGHTLY COUPLED
conflict graph on via stacks (M2-V2-M3-V3-M4...). Every local edit — deterministic surgical,
deterministic coordinated, or model-proposed — creates more violations than it removes; the fix
propagates up/down the stack. This is exactly the regime the MDPI paper solves with a global
conflict-graph simulated-annealing optimizer (quantify conflict, accept moves that reduce NET
conflict) — a substantial algorithm, not a local-edit pass. Our keep-best loop IS the SA acceptance
test; what's missing is a move-generator that produces net-conflict-reducing multi-edits.

**What we HAVE (complete, honest third-track entry):** version-exact Dockerized env; runner-
contract-compliant agent; zero-token DRC diagnosis + structured repair-rules library; verify
measured identically to the official scorer; keep-best guarantee (never worse than eligible
baseline, connectivity always preserved). ASU result: eligible baseline (fvr 1.29) + a rigorous,
literature-grounded characterization of why block-repair needs global conflict-graph optimization.

## 2026-07-14 — Research + exact-rule coordinated fixer: the stack-cascade proof

Research (LAD/ISPD per Hari): DRC-Coder (ISPD 2025, NVIDIA) — vision+LLM DRC rule interpretation,
F1=1.0 — validates the multimodal (screenshot) lever. Wide-metal via enclosure (PDK/patents): a
wide metal needs a wide via, not a min-via. Decoded EXACT rule geometry from asap7.lydrc (the
authoritative source, not the report descriptions): V2.M3.AUX.2 satisfied iff via is inside M3 AND
has >=2 edges COINCIDENT with M3 edges (via spans M3 full width perpendicular to length); coupled
rules V2.M2.EN.1 (M2 encloses via 5nm on 2 opposite sides), V2.AUX.1 (via inside M2 & M3).

Built the coordinated wide-metal-via fixer (via flush to upper metal + lower-metal patch = via+5nm)
from the exact geometry. V2/M3 result: **AUX.2 72->0, and enclosure/containment NO LONGER BREAK
(the M2 patch works — solved the coupling that killed grow-via)** — but the 136-tall via forces a
136-tall M2 that crowds neighbor M2 tracks -> M2.S.4 +96 / S.2 +23 / S.7 +18. Net 315->379.

**Decisive conclusion:** every single-stack fix cascades — grow-via->M2 spacing; shrink-M3->V3
enclosure; coordinate-via+M2->M2 spacing. A complete fix needs the WHOLE via stack resized to one
width that simultaneously meets width+enclosure+containment+spacing incl. neighbors = global
conflict-graph / simulated-annealing legalization (MDPI 2025), a multi-day algorithm. Our keep-best
loop already IS the SA acceptance test; the missing piece is a global move-generator.

Deliverable is complete + honest: Dockerized version-exact env, runner-contract agent, zero-token
DRC diagnosis, exact-rule-grounded structured repair-rules library, verify == official scorer,
keep-best guarantee (never worse than eligible baseline, connectivity always preserved), and a
rigorous literature-grounded characterization of why block-repair is global legalization. Multimodal
(DRC-Coder-style) + conflict-graph SA are the identified future-work paths.

## 2026-07-14 — Perturbation characterization: exact seeded mechanism identified

Compared flagged vs correct via stacks (deterministic, 0 tokens). DECISIVE, systematic pattern:
- CORRECT stacks: min-via in min-metal, matched. V0/M1 (72,72)×749, V2/M3 (72,72)×198,
  V4/M5 (96,96)×21.
- FLAGGED stacks: a CORRECT min-via sitting in a WIDE metal — uniform per layer:
  V2/M3 via72-in-M3=136 (×72), V4/M5 via96-in-M5=480 (×48), V5/M6 via128-in-M6=640 (×24).
- Full stack at flagged V2/M3: M2(below)=12528×72 thin rail · V2=72×72 · M3=360×136 wide ·
  V3(above)=72×96. The wide M3 is LEGITIMATELY wide — it correctly encloses the upper via V3(96).

**So it is NOT a simple revert.** The rule-correct fix (via spans M3 -> grow via to 136y) then needs
the via INSIDE M2 (V2.AUX.1), but M2 is a 72-tall rail whose y-neighbours are one track away ->
widening M2 to contain a 136-tall via collides with neighbour rails. via-spans-M3 + via-inside-M2 +
M2-spacing cannot all hold without RELOCATING neighbour rails = global placement change. Confirms
block-repair (dominant via-width class) needs global legalization; local resize is over-constrained.

NEW idea unlocked by the characterization (testing next): instead of growing the via, NECK the wide
metal down to via-width at the lower-via landing (keeping it wide at the upper-via landing) — the via
stays min (M2 containment/enclosure untouched), and V3 unaffected if at a different position. Static
connectivity check (from original script text) is preserved regardless.

## 2026-07-14 — Cross-block evidence: the over-constraint is uniform (decisive)

Per-block violation-class breakdown (all 5 public blocks, from the DRC reports):

| Block | total | via-width-match | grid | enclosure | spacing |
|---|---|---|---|---|---|
| Block1 | 244 | 181 (74%) | 29 | 11 | 21 |
| Block2 |  68 |  52 (76%) | 10 |  2 |  3 |
| Block3 |  89 |  66 (74%) | 10 |  6 |  6 |
| Block6 | 247 | 183 (74%) | 30 | 10 | 20 |
| Block7 | 765 | 544 (71%) | 72 | 26 | 114 |

**Every block is ~74% the via-width-match class** proven irreducibly over-constrained (a min-via V2
and a larger via V3 stacked on ONE M3 that cannot be both flush-equal to V2=72 and enclose V3=96,
i.e. simultaneously 72 and >=106). The neck-down test confirmed V2/V3 share the landing (necking M3
broke V3.M3.EN.1 +48 / V3.AUX.1 +48). The remaining ~26% (grid/enclosure/spacing) sit on the same
stacks and regressed in every experiment.

**Final conclusion (proven, not asserted):** local geometric repair CANNOT beat the eligible baseline
on any of the 5 blocks. The only winning path is global neighbour relocation (full detailed-routing
legalization) — a multi-day incremental-conflict SA engine, out of scope for the remaining window.
The ASU deliverable is therefore: a complete, runner-contract, verification-first agent (version-exact
env, verify == scorer, keep-best guarantee, exact-rule-grounded rules library) + a rigorous,
reproducible diagnosis of the exact seeded-perturbation mechanism and its irreducibility. Redirecting
remaining time to the proven, scored NVIDIA/NXP tracks + submission.

## 2026-07-15 — Phase 0 (from the improvement-plan review): submission-critical hardening + freeze

Acting on the external review of ASU_IMPROVEMENT_PLAN.md.
1. **P0 fixed (would have zero-scored us):** the official runner runs the agent container read-only
   with the usage path mounted only into the wrapper; our agent's usage.json write failed → nonzero
   exit → no scoring. Usage write is now best-effort (try/except). Confirmed vs official_eval/run_official_eval.py.
2. **EndpointModel hardened:** request {model,prompt,max_output_tokens}; retry/backoff on HTTP 429/5xx
   and body {"retryable":true}/provider_status; NEVER raises (returns "" on unrecoverable → keep-best
   ships baseline). best-of-N loop wrapped crash-safe. Verified vs a mock endpoint (success /
   retry-then-success / total-fail-no-crash) AND a full container model-mode run (host mock endpoint,
   --model gemini-3.5-flash) → unhelpful passes discarded by keep-best, eligible baseline, EXIT 0.
   Note: under the official runner --model is ALWAYS a model name → we always run model mode, so this
   robustness is submission-critical.
3. **5 exact baselines FROZEN** (asu_work/baselines/baseline_table.json, with rule-deck/evaluator hashes):
   Block1 315 (fvr 1.291) · Block2 90 (1.324) · Block3 111 (1.247) · Block6 321 (1.300) · Block7 957 (1.251).
   Exact DRC ≈ 12–22 s/block (faster than the 40s estimate).
4. **Connectivity-integrity policy = Option A** (credible physical repair). Added a RENDERED-geometry
   connectivity signature (net/component count + conducting area + per-layer shape counts) and
   connectivity_credible(): a degenerate candidate that deletes M2 fools the official STATIC checker
   ("preserved") but our check catches it (nets 25→110). Winning candidates must pass BOTH the official
   gate and this credibility check.

Next: Phase 1 target selection (count x-clear V2/M3 sites; find isolated minority-class sites) →
Phase 2 two smallest falsifiable experiments (S1 center neck, S5 isolated minority).

## 2026-07-15 — Phase 2 Experiment A (S1 x-clear V2/M3 neck)

Implemented the reviewer's orthogonal neck: neck M3 to the via's y-extent only in an x-window that
avoids adjacent V3, on the flattened merged M3. Block1 result: **V2.M3.AUX.2 72→48 (fixed 24 x-clear
sites), connectivity-CREDIBLE (rendered nets unchanged)** — the first move that fixes a chunk of the
target AND passes the Option-A credibility check. BUT the neck shoulders create **M3.S.4 0→48**
(parallel-run/spacing collateral with nearby M3), net 315→339. S1 mechanism validated; the collateral
is the barrier. Trying per-site greedy acceptance next (keep only necks that net-reduce exact DRC).

## 2026-07-15 — S1 FALSIFIED by per-site exact DRC (the decisive experiment)

Per-site neck deltas (Block1): center x-clear site **+1**, left/right partial-overlap **+3** each.
Root cause (exact): each neck fixes 1 V2.M3.AUX.2 but its TWO shoulders each create an M3.S.4
(parallel-run-length) violation with the adjacent horizontal M3 track → net +1 even at the most
feasible site. The neck's own geometry is illegal. **S1 (the review's top pick) is ruled out with
exact-DRC data — no x-clear V2/M3 neck is a net win.** This sharpens the characterization: the
via-width class resists even a surgical, connectivity-credible neck because M3 routing neighbors make
the neck shoulders trip M3.S.4. Remaining plan options (S4 template-mining, S5 isolated-minority) have
low expected payoff given every class tested cascades; decision point for whether to invest more
compute vs. ship the (now hardened) submission + sharpened characterization.

## 2026-07-15 — BREAKTHROUGH: via-bar repair — FVR 0.68–0.76 on ALL 5 blocks (real win)

Acting on the ASU_PHASE0_FINDINGS review (which was RIGHT — "don't consolidate"): tested the
reviewer's V2-bar hypothesis and it WORKS.
- Grid-multiplicity (P0-F05): FALSIFIED as an artifact — the 72 M4.AUX.1 etc. are UNIQUE geometries
  (max multiplicity 1), so the +71 gap is real distinct off-grid edges (script-vs-GDS render diff),
  not duplicated markers. Canonicalization-of-markers won't help.
- **V2-bar (P0-F03): the win.** The seeded errors split each via-in-wide-metal landing into a
  multi-cut array (all V.M.AUX.2 counts are multiples of 3); replacing each flagged array with ONE
  continuous via BAR spanning the metal length (min thickness kept → NO lower-metal widening → no
  cascade) fixes the whole class cleanly. V2/M3 alone: Block1 315→243 (fvr 0.996). Extending to
  V4/M5 + V5/M6 (upper routing only): **Block1 315→178 (fvr 0.730)**. V0/M1 EXCLUDED (device layer:
  bars there explode V0.M1.EN.1→389 + break connectivity).
- **All 5 blocks (V-bar, 3 upper pairs), verified eligible + rendered-connectivity-credible:**
  Block1 0.730 · Block2 0.765 · Block3 0.764 · Block6 0.676 · Block7 0.682. All BELOW FVR 1.0.
- Productionized: `repairs.via_bar_pass()` (primary deterministic pass) + credibility gate ENFORCED
  in keep-best (P0-F01 fixed — candidates must pass rendered-connectivity, not just the static
  checker). Full agent end-to-end: Block1 emits fvr 0.730, repair_rate 0.59.

ASU flips from "honest negative result" to a REAL repair beating the reference denominator on the
whole public set. The reviewer's exact-geometry reasoning was correct; my "consolidate" call was wrong.
