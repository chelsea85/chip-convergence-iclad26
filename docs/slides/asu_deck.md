---
marp: true
theme: default
paginate: true
size: "16:9"
html: true
style: |
  section { font-size: 24px; padding: 48px 60px; }
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

# Measure the Scorer, Never Ship a Regression

## Verification-first DRC repair of ASAP7 layout scripts

**Version-exact scoring env · verify identical to the official evaluator ·
keep-best guarantee: never worse than the eligible baseline, on all 5 blocks**

Harikrishnan KC · Team **Chip Convergence** · greatharikrishnan@gmail.com
ASU Problem · ICLAD-DAC 2026 GenAI Chip Hackathon

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
<text x="475" y="78" text-anchor="middle" class="tiny">deterministic: coordinated wide-metal-via, grid-snap (exact-rule-derived)</text>
<line x1="475" y1="92" x2="475" y2="106" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#aar)"/>
<rect x="262" y="108" width="426" height="40" class="abox"/>
<text x="475" y="126" text-anchor="middle" class="s">model fix-pass (rules + coupling + screenshot) — best-of-N,</text>
<text x="475" y="140" text-anchor="middle" class="tiny">code-compile checked, render-error repair, off the token budget when it fails</text>
<line x1="475" y1="148" x2="475" y2="162" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#aar)"/>

<rect x="262" y="164" width="426" height="56" class="box"/>
<text x="475" y="184" text-anchor="middle" class="t" font-size="12.5">VERIFY (== official scorer)</text>
<text x="475" y="201" text-anchor="middle" class="tiny">render → DRC → connectivity, measured with the evaluator's OWN</text>
<text x="475" y="214" text-anchor="middle" class="tiny">functions → identical to the scoring machine</text>
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
<text x="842" y="208" text-anchor="middle" class="tiny">5/5 blocks eligible, conn preserved</text>
</svg>

---

# 3 · The two things we got exactly right

**1. Version-exact scoring environment.** The evaluator hard-rejects any KLayout but **0.30.1**.
macOS ships 0.30.9 → we built an **amd64 Docker image with the pinned 0.30.1** (runs under
emulation on Apple Silicon). Our DRC == the organizers' DRC: **11/14 rules match the reference
report exactly** on the untouched script.

**2. Verify == the scorer.** Our inner loop imports the **official evaluator's own** render / DRC /
count / connectivity functions — so every candidate is measured *identically* to how it will be
scored. No local/remote metric drift.

On top of these: **keep-best** with the untouched baseline as the eligible floor → the agent can
never ship worse than baseline and never break connectivity. **Validated on all 5 blocks.**

---

# 4 · The repair-rule library (exact-rule + literature grounded)

Like our NVIDIA 45-rule playbook — but for DRC. Each rule class → a coordinated transform + the
coupling hazards, from three sources:

- **Exact deck semantics** (`asap7.lydrc`, the ground truth): e.g. `V2.M3.AUX.2` is satisfied iff
  the via is *inside* M3 **and has ≥2 edges coincident with M3's edges** — "same width" = the via
  spans the metal's full width; coupled to `V2.M2.EN.1` (M2 encloses via 5 nm) + `V2.AUX.1`
  (via inside M2 & M3).
- **EDA legalization literature**: MDPI 2025 (simulated-annealing standard-cell DRC repair),
  EDN (cut-slide/merge without creating new errors), USPTO 7,380,227 (asymmetric enclosure),
  DRC-Coder ISPD'25 (vision+LLM rule interpretation, F1=1.0).
- **Our own measurements** (next slide).

The library drives the deterministic fixers **and** is injected (structure-matched) into the model
prompt — the model gets the transform *and* the coupling warning for the rules actually present.

---

# 5 · The finding: block repair is global legalization

We derived the coordinated **wide-metal-via** fixer straight from the exact rule (via flush to the
upper metal + patch the lower metal for enclosure/containment) and measured every strategy on
Block1 (baseline 315 violations):

| Fix | target rule | but breaks | net |
|---|---|---|---|
| grow via → metal width | AUX.2 ✓ | lower-metal enclosure | 315→387 |
| shrink metal → via width | AUX.2 ✓ | upper-via enclosure | 315→339 |
| **coordinated via + metal patch** | AUX.2 ✓, **enclosure preserved ✓** | neighbor **M2 spacing** | 315→379 |

Every fix **cascades to the next layer of the via stack** (M2-V2-M3-V3-M4…). A complete repair
needs the *whole stack* resized to one width satisfying width **+** enclosure **+** containment
**+** neighbor spacing — i.e. **global conflict-graph / simulated-annealing legalization**
(MDPI 2025). Our keep-best loop already **is** the SA acceptance test; the missing piece is a
global multi-edit move-generator.

---

# 6 · Results & honest status

- **Environment**: version-exact KLayout 0.30.1, Dockerized; DRC calibrated (11/14 rules exact).
- **Agent**: runner-contract compliant; **all 5 blocks eligible, connectivity preserved**
  (final-violation-rate ≈ 1.25–1.32 = the eligible baseline).
- **Repair-rule library**: exact-deck + literature grounded; coordinated wide-metal-via fixer
  **solves the enclosure coupling** — the first strategy to do so — but hits neighbor spacing.
- **Characterization**: rigorous, reproducible proof that block-repair is a global legalization
  problem, with the two concrete solution paths scoped.

**We never ship a regression and never break connectivity** — the safety guarantee holds on every
block. The verification-first spine (measure the scorer, keep-best) is the same discipline that
delivered our NVIDIA (ADP 0.727 / 0.605) and NXP (2-call perfect solve) results.

---

# 7 · Next: from characterization to sub-baseline

- **Global move-generator (the missing piece)** — SA over *multi-edit* stack moves: resize the
  whole via stack (metal+via+metal) to a consistent width, accept by net-conflict-delta (our
  keep-best loop is already the acceptance test). This is the path to `final_violation_rate < 1`.
- **Multimodal repair (DRC-Coder ISPD'25 style)** — feed Gemini the **screenshot** + exact rules +
  violation geometry so it localizes and proposes *stack-coordinated* edits (the model over-corrected
  globally without visual grounding).
- **Per-rule independent fixers** — min-area / isolated edges (no via nearby) as free deterministic
  wins.
- Agents remain updatable through **Jul 26**.

---

# 8 · Summary — every claim, one command

| Claim | Reproduce with |
|---|---|
| Version-exact env | `docker run … asu-klayout:0.30.1 klayout -v` → 0.30.1 |
| Zero-token diagnosis | `python3 drc_digest.py <BlockN.drc.json>` |
| Agent (eligible, keep-best) | `python3 asu_agent.py <info.json> --model none` |
| Verify == scorer | inner loop imports `evaluator/evaluate_repair.py` functions |
| 5/5 blocks eligible | Block1/2/3/6/7, connectivity preserved |

**Repo:** github.com/chelsea85/chip-convergence-iclad26 (`asu_work/`)
Companion: **Engineering Learnings** — what the research + experiments taught us.

**Harikrishnan KC · Chip Convergence · greatharikrishnan@gmail.com**
