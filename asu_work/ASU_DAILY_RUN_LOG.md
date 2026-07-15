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
