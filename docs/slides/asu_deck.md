---
marp: true
theme: default
paginate: true
size: "16:9"
html: true
style: |
  section { font-family: Arial, "Helvetica Neue", Helvetica, sans-serif; font-size: 24px; padding: 48px 60px; }
  h1 { font-size: 40px; color: #1a3a6b; }
  h2 { font-size: 32px; color: #1a3a6b; }
  table { font-size: 20px; }
  code { font-size: 18px; }
  pre { font-size: 16px; line-height: 1.25; }
  section.lead h1 { font-size: 50px; }
  section.lead { text-align: center; }
  .ok { color: #1a7a2a; font-weight: 600; }
  .bad { color: #b03030; font-weight: 600; }
  footer { font-size: 14px; color: #888; }
footer: "Chip Convergence — ICLAD-DAC 2026 — ASU Block DRC Repair"
---

<!-- _class: lead -->
<!-- _footer: "" -->

# ASU

## Block DRC Repair

ICLAD-DAC 2026 · GenAI Chip Hackathon

Harikrishnan KC · Team **Chip Convergence** · greatharikrishnan@gmail.com

---

# 1 · The problem, and what actually scores

**Given:** an ASAP7 block as a **KLayout `pya` layout script** with seeded DRC violations, its
**DRC report** (per-rule counts + exact geometry), the rule deck, a **screenshot**, and a
**connectivity reference**. Repair the script.

**Scoring — gated lexicographic:**

| Gate / Metric | Rule |
|---|---|
| Eligibility | script must render + DRC must run **AND** connectivity preserved |
| 1 · `final_violation_rate` | minimize (final DRC violations / original) |
| 2 · `repair_rate` | maximize (tiebreak) |

**Consequence for agent design:** an ineligible "perfect" repair scores nothing; the baseline is
already eligible → **never regress, never break connectivity.**

---

<!-- _footer: "" -->

# 2 · What we do — one picture

<svg viewBox="0 0 1160 430" style="width:100%;height:auto" xmlns="http://www.w3.org/2000/svg">
<defs>
<marker id="aar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#1a3a6b"/></marker>
<marker id="aarg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#1a7a2a"/></marker>
</defs>
<style>
.t{font:600 14px sans-serif;fill:#1a3a6b}.s{font:12px sans-serif;fill:#333}
.tiny{font:10.5px sans-serif;fill:#555}.w{font:600 12.5px sans-serif;fill:#fff}
.box{fill:#eef3fa;stroke:#1a3a6b;stroke-width:1.4;rx:8}
.gbox{fill:#e8f5e9;stroke:#1a7a2a;stroke-width:1.6;rx:8}
.abox{fill:#fdf3e0;stroke:#b07a1a;stroke-width:1.4;rx:8}
.hdr{fill:#1a3a6b;rx:8}
</style>

<rect x="8" y="12" width="210" height="30" class="hdr"/>
<text x="113" y="32" text-anchor="middle" class="w">DIAGNOSE — zero tokens</text>
<rect x="16" y="54" width="194" height="70" class="box"/>
<text x="113" y="74" text-anchor="middle" class="t" font-size="12.5">DRC report → findings</text>
<text x="113" y="92" text-anchor="middle" class="tiny">per-rule count + exact geometry</text>
<text x="113" y="108" text-anchor="middle" class="tiny">matched to repair-rule library</text>
<line x1="210" y1="89" x2="236" y2="89" stroke="#1a3a6b" stroke-width="2" marker-end="url(#aar)"/>

<rect x="240" y="12" width="470" height="404" fill="none" stroke="#1a3a6b" stroke-width="1.8" stroke-dasharray="7 4" rx="12"/>
<rect x="258" y="2" width="434" height="20" fill="#fff"/>
<text x="475" y="17" text-anchor="middle" class="t">REPAIR — candidate fix-passes (deterministic + model)</text>

<rect x="262" y="40" width="426" height="52" class="box"/>
<text x="475" y="60" text-anchor="middle" class="t" font-size="12.5">fix-pass = ORIGINAL script + appended pya (runs before write)</text>
<text x="475" y="78" text-anchor="middle" class="tiny">deterministic: via-bar-safe, track-shift, v1-patch (electrically guarded)</text>
<line x1="475" y1="92" x2="475" y2="106" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#aar)"/>
<rect x="262" y="108" width="426" height="40" class="abox"/>
<text x="475" y="126" text-anchor="middle" class="s">model fix-pass (rules + coupling + screenshot) — best-of-N,</text>
<text x="475" y="140" text-anchor="middle" class="tiny">code-compile checked, render-error repair, off the token budget when it fails</text>
<line x1="475" y1="148" x2="475" y2="162" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#aar)"/>

<rect x="262" y="164" width="426" height="56" class="box"/>
<text x="475" y="184" text-anchor="middle" class="t" font-size="12.5">VERIFY (== official scorer)</text>
<text x="475" y="201" text-anchor="middle" class="tiny">render → DRC → connectivity, measured with the evaluator's OWN</text>
<text x="475" y="214" text-anchor="middle" class="tiny">functions → the scorer's own render/DRC/connectivity code</text>
<line x1="475" y1="220" x2="475" y2="234" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#aar)"/>

<polygon points="475,236 560,268 475,300 390,268" fill="#eef3fa" stroke="#1a3a6b" stroke-width="1.6"/>
<text x="475" y="264" text-anchor="middle" class="t" font-size="12">eligible &amp;</text>
<text x="475" y="279" text-anchor="middle" class="t" font-size="12">better?</text>
<line x1="475" y1="300" x2="475" y2="322" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#aar)"/>
<rect x="330" y="324" width="290" height="40" class="gbox"/>
<text x="475" y="344" text-anchor="middle" class="t" font-size="12.5" fill="#1a7a2a">KEEP-BEST (gated-lexicographic)</text>
<text x="475" y="358" text-anchor="middle" class="tiny">baseline = eligible floor · a regression/breakage is discarded</text>
<line x1="560" y1="268" x2="612" y2="268" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#aar)"/>
<text x="586" y="260" class="tiny">no</text>
<path d="M 475 236 L 475 40" fill="none" stroke="#1a3a6b" stroke-width="1.2" stroke-dasharray="4 3"/>

<rect x="732" y="12" width="220" height="30" class="hdr"/>
<text x="842" y="32" text-anchor="middle" class="w">EMIT · SCORE</text>
<rect x="740" y="54" width="206" height="70" class="gbox"/>
<text x="842" y="74" text-anchor="middle" class="t" font-size="12.5" fill="#1a7a2a">best eligible script</text>
<text x="842" y="92" text-anchor="middle" class="tiny">→ output_path + usage.json</text>
<text x="842" y="108" text-anchor="middle" class="tiny">runner-contract compliant</text>
<path d="M 620 344 L 842 344 L 842 124" fill="none" stroke="#1a7a2a" stroke-width="2" marker-end="url(#aarg)"/>
<rect x="740" y="140" width="206" height="80" class="box"/>
<text x="842" y="160" text-anchor="middle" class="t" font-size="12.5">env: KLayout 0.30.1</text>
<text x="842" y="178" text-anchor="middle" class="tiny">version-exact Docker (organizer</text>
<text x="842" y="192" text-anchor="middle" class="tiny">scoring target); amd64 image</text>
<text x="842" y="208" text-anchor="middle" class="tiny">7/7 blocks FVR 0.37-0.58</text>
</svg>

<span style="font-size:16px;color:#555">Same verification-first spine as NVIDIA/NXP: diagnose (0 tokens) → propose → verify == scorer → keep-best (electrically gated) → emit. <b>v2 Rev3: FVR 0.37–0.58 on all 7 blocks.</b></span>

---

# 3 · Principles

1. **Tools before tokens** — the DRC report is a ready-made, machine-readable diagnosis
   (per-rule counts + exact geometry); spend model tokens on the genuinely ambiguous cases, not
   on re-deriving what the tools already state.
2. **Measure the scorer, not a proxy** — our inner loop imports the *official evaluator's own*
   render/DRC/connectivity functions, so every candidate is measured exactly as it will be scored.
3. **Never regress** — keep-best with the untouched baseline as the eligible floor; a fix that
   worsens DRC or breaks connectivity is discarded by tooling, not by hope.
4. **Ground rules in the deck, not descriptions** — the authoritative fix semantics come from
   `asap7.lydrc` itself, cross-checked against EDA legalization literature.
5. **Honest characterization** — "eligible baseline + why sub-baseline needs global legalization"
   is a first-class, reproducible result.

---

# 4 · Version-exact environment (the first thing others will trip on)

The evaluator **hard-rejects any KLayout but 0.30.1** (string-equality on `klayout -v`). macOS
Homebrew ships 0.30.9 (and hits Gatekeeper quarantine) — the wrong path.

**Our fix — Dockerized, version-exact:** an amd64 image with the pinned
`klayout_0.30.1-1_amd64.deb` + deps. Host is Apple Silicon (arm64) → runs under Docker emulation:
slower, but **version-exact KLayout 0.30.1** — our container DRC matches the reference report on **11/14 rules**.

**Calibration proof:** on the untouched Block1, our container DRC matches the reference report on
**11 of 14 rules exactly** (V2.M3.AUX.2=72, V4.M5.AUX.2=48, V0.M1.AUX.3=37, all S-rules…). Our DRC
*is* the scoring DRC.

---

# 5 · Zero-token DRC diagnosis

`drc_digest.py` turns the DRC report into structured, actionable findings — **no model tokens:**

- **per-rule findings** ranked by count, each with the rule *description* and exact violation
  geometry (bbox + vertices, DBU)
- **fix-kind classification** — grid / spacing / enclosure / width-match / area — parsed from the
  rule text
- **rule-library match** — each finding linked to its repair transform + coupling hazard

Block1 example: 244 reference violations, 14 rules; the dominant class is **via-width-match
(AUX.2/AUX.3) = 181 violations (74%)**, then grid, enclosure, spacing. The diagnosis *is* the
repair plan — before a single token is spent.

---

# 6 · The repair-rule library (exact-deck + literature grounded)

Like our NVIDIA 45-rule playbook, but for DRC. Each rule class → a coordinated transform + its
coupling hazards, from three provenances:

- **Exact deck semantics** (`asap7.lydrc`): `V2.M3.AUX.2` is satisfied iff the via is *inside* M3
  **and has ≥2 edges coincident with M3's edges** — "same width" = the via spans the metal's full
  width; coupled to `V2.M2.EN.1` (M2 encloses via 5 nm) + `V2.AUX.1` (via inside M2 & M3).
- **EDA legalization literature**: MDPI 2025 (SA standard-cell DRC repair), EDN
  (cut-slide/merge without new errors), USPTO 7,380,227 (asymmetric enclosure), **DRC-Coder
  ISPD'25** (vision+LLM rule interpretation, F1=1.0).
- **Our own measurements** (slide 10).

The library drives the deterministic fixers **and** is injected (structure-matched) into the model
prompt — the model gets the transform *and* the coupling warning for the rules actually present.

---

# 7 · Verification == the scorer, and keep-best

**Verify** (`verify.py`): render → GDS → ASAP7 DRC → connectivity, all measured with the official
evaluator's **own** functions. Reproduces the baseline exactly (total=315, connectivity 824
sources). No metric drift: the inner loop calls the evaluator's own functions (independently re-scored by the published evaluator).

**Keep-best** (gated-lexicographic, matching the contest): eligible → min `final_violation_rate` →
max `repair_rate`, with the untouched baseline as the guaranteed-eligible floor.

**The guarantee this buys:** on every block, the agent **does not ship a candidate that regresses
`final_violation_rate`** and **retains the eligible baseline if a candidate fails the connectivity
check** — verified, then kept-best. The same
"always ship eligible" discipline as our NXP agent.

---

# 8 · The repair engine: deterministic + model, verified

**Candidate = the ORIGINAL script + an appended `pya` fix-pass** that runs right before `write`.
Because the original shapes are untouched, connectivity (checked statically from the script) is
then VERIFIED per candidate (the appended pass mutates rendered geometry; keep-best + the official
connectivity check are the guarantee, not the append mechanism).

- **Deterministic fixers** (0 tokens) — coordinated wide-metal-via, grid-snap; each derived from
  the exact rule geometry and applied to the flagged locations.
- **Model fixers** — Gemini writes a `pya` fix-pass with the rules + coupling + (next) the
  screenshot; **best-of-N**, code-compile validated, with a render-error repair loop, and *off the
  token budget when a candidate fails*.

Every candidate goes through verify + keep-best — so a bad pass (deterministic or model) is simply
never kept.

---

# 9 · Decode the rule, then reshape the *via* — not the metal

The dominant class (~74% of every block) is via-width-match. The exact deck says:

```
V2.M3.AUX.2  satisfied  ⟺  via INSIDE the metal  AND  ≥2 via edges COINCIDENT with metal edges
```

We first tried reshaping the **metal** (a surgical neck) — falsified by exact DRC: the neck's own
shoulders trip `M3.S.4` (net +1 even at the best site). The key realization: **reshape the via.**
The seeding split each via landing into a **multi-cut array** of min-vias — and every min-via fails
the rule (the counts are all multiples of 3).

---

# 10 · The via-bar: replace the array with one continuous bar

**Fix:** at each flagged landing, replace the multi-cut min-via array with **one continuous via
bar** spanning the metal's length — keeping the **minimum via thickness**, so the lower metal needs
**no widening** (this is what sank every earlier "grow-via" attempt).

- ends **coincident** with the metal's edges → satisfies the width-match rule
- min thickness → no lower-metal enclosure/spacing cascade
- joins cuts that already shared the landing → **no net change** (connectivity preserved)
- **device layer V0/M1 excluded** (bars there explode enclosure + break nets)

Block1: `V2.M3.AUX.2 72→0`, then adding V4/M5 + V5/M6 → **315 → 178**, zero connectivity change
under the published checker. **v2 hardening (Jul 26):** a layer-aware review found some bars
electrically JOIN distinct nets crossing the landing — invisible to that checker. The v2
**via-bar-safe** pass places a bar only when it touches exactly the same electrical components
as the original cuts on BOTH adjacent layers (fail closed), and adds **track-shift** (off-grid
tracks translated back to the routing grid, vias co-translated) and **v1-patch**.

---

# 11 · Result (v2 Rev3): all 7 blocks, FVR 0.37–0.58, electrically proven

| Block | baseline (exact) | → Rev3 | **final_violation_rate** | eligible | electrical partition |
|---|---:|---:|---:|:--:|:--:|
| Block1 | 315 | 142 | **0.582** | ✓ | ✓ equal |
| Block2 | 90 | 35 | **0.515** | ✓ | ✓ |
| Block3 | 111 | 35 | **0.393** | ✓ | ✓ |
| **Block4** | 189 | 55 | **0.374** | ✓ | ✓ |
| **Block5** | 87 | 33 | **0.485** | ✓ | ✓ |
| Block6 | 321 | 102 | **0.413** | ✓ | ✓ |
| Block7 | 957 | 444 | **0.580** | ✓ | ✓ |

**Block4/5 were released the day before this talk** — the frozen agent scored them **blind**,
and they are its two best scores. "Electrical partition" = a layer-aware full-stack connectivity
proof (immutable-anchor partition, fail-closed) that original→repaired net topology is identical.

---

# 12 · How we got here — the discipline that found the win

The win came from a **review-and-falsify loop**, not a lucky guess:
- **Environment**: version-exact KLayout 0.30.1, Dockerized; DRC calibrated (11/14 rules exact);
  verify imports the official evaluator's own functions.
- **Falsified the wrong idea first**: the metal-neck (net +1, `M3.S.4` shoulders) — with exact DRC,
  in ~1 h, instead of building a multi-day legalizer.
- **Then the right one**: reshape the *via* into a bar — derived from the exact rule and verified.
- **Then reviewed our own win**: a 3-round independent layer-aware review found the v1 bars
  created **49 electrical merges invisible to BOTH the official checker and our 2D proxy**.
  We rebuilt the repair with per-side electrical guards and re-proved every block — trading a
  measured amount of DRC for correctness. **The review trail ships in the repo.**
- **Every candidate measured identically to how it will be scored** — no proxy, no drift.

**Three tracks, one architecture, three real results:** NVIDIA ADP 0.727 (sha512, full 5-layer) /
0.605 (prim, equivalence+differential) · NXP 2-call solve, perfect vs our verification stack ·
**ASU v2 Rev3: FVR 0.37–0.58 on all 7 blocks, electrical preservation proven.**

---

# 13 · What v2 added (all shipped 2026-07-26)

- **track-shift** — the grid class was seeded by translating whole tracks off-grid; the inverse
  transform (translate back to grid/pitch, co-translating riding vias, patching end-caps) cleared
  it under layer-aware per-move acceptance. Biggest single win after via-bar.
- **Layer-aware electrical gate** — built the per-layer metal/via reachability comparison
  (immutable-anchor partition); it is now a hard release gate AND found the v1 shorts.
- **12 permanent geometric safety controls** — including two adversarial counterexamples from
  the independent review; one control caught a real bug in our own fix before it shipped.
- **Falsified honestly**: V0/M1 (device layer) and the V1/M1.S cluster proven locally
  irreducible with exact per-site geometry — global legalization is the only remaining path.

---

# 14 · How this mirrors our NVIDIA & NXP agents

| | NVIDIA | NXP | **ASU** |
|---|---|---|---|
| Tools before tokens | zero-token PPA diagnosis | library introspection | **zero-token DRC diagnosis** |
| Knowledge asset | 45-rule playbook | 20 IP reference models | **DRC repair-rule library** |
| Verify | 5-layer + LEC/dualsim | 30-check TB + KAT + STG | **render+DRC+connectivity == scorer** |
| Safety | accept only measured improvement | always ship eligible | **keep-best, never regress** |
| Env rigor | pristine baselines | runner contract | **version-exact KLayout 0.30.1** |

One architecture, three domains — the discipline transfers.

---

# 15 · Summary — every claim, one command

| Claim | Reproduce with |
|---|---|
| Version-exact env | `docker run … asu-klayout:0.30.1 klayout -v` → 0.30.1 |
| Zero-token diagnosis | `python3 drc_digest.py <BlockN.drc.json>` |
| Agent (eligible, keep-best) | `python3 asu_agent.py <info.json> --model none` |
| Verify == scorer | inner loop imports `evaluator/evaluate_repair.py` functions |
| 5/5 blocks eligible | Block1/2/3/6/7, connectivity preserved |

**Repo:** github.com/chelsea85/chip-convergence-iclad26 (`asu_work/`)
Companion deck: **Engineering Learnings** (attached) — what the research + experiments taught us.

**Harikrishnan KC · Chip Convergence · greatharikrishnan@gmail.com**
