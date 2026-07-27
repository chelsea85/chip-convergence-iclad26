---
marp: true
theme: default
paginate: true
size: "16:9"
html: true
style: |
  section { font-family: Arial, "Helvetica Neue", Helvetica, sans-serif; font-size: 24px; padding: 44px 58px; }
  h1 { font-size: 38px; color: #1a3a6b; }
  h2 { font-size: 30px; color: #1a3a6b; }
  table { font-size: 19px; }
  code { font-size: 17px; }
  pre { font-size: 15px; line-height: 1.25; }
  section.lead h1 { font-size: 48px; }
  section.lead { text-align: center; }
  .ok { color: #1a7a2a; font-weight: 600; }
  .bad { color: #b03030; font-weight: 600; }
  .dim { color: #666; }
  footer { font-size: 14px; color: #888; }
footer: "Chip Convergence — ICLAD-DAC 2026 — Harikrishnan KC"
---

<!-- _class: lead -->
<!-- _footer: "" -->

# Chip Convergence

## Verification-first agents for chip design

**NVIDIA** RTL PPA · **NXP** SoC generation · **ASU** DRC repair

ICLAD-DAC 2026 · GenAI Chip Hackathon
Harikrishnan KC (solo) · greatharikrishnan@gmail.com

---

# 1 · One thesis, three problems

A language model will hand you hardware that is **smaller, faster — and wrong**.
Plausible-but-wrong RTL is worse than no RTL: it passes review and fails in silicon.

So we built the **verifier first** and put the model behind it.

<svg viewBox="0 0 1100 210" style="width:100%;height:auto" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="a" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto">
    <path d="M0,0 L0,6 L9,3 z" fill="#444"/></marker></defs>
  <rect x="10"  y="60" width="200" height="70" rx="8" fill="#eef3fb" stroke="#1a3a6b"/>
  <text x="110" y="88"  text-anchor="middle" font-size="19" font-weight="600" fill="#1a3a6b">MODEL</text>
  <text x="110" y="112" text-anchor="middle" font-size="16" fill="#444">proposes</text>
  <rect x="300" y="30" width="280" height="130" rx="8" fill="#f7f7f7" stroke="#444"/>
  <text x="440" y="58"  text-anchor="middle" font-size="19" font-weight="600" fill="#111">DETERMINISTIC GATES</text>
  <text x="440" y="84"  text-anchor="middle" font-size="15" fill="#444">equivalence · known-answer tests</text>
  <text x="440" y="106" text-anchor="middle" font-size="15" fill="#444">port contracts · structural diff</text>
  <text x="440" y="128" text-anchor="middle" font-size="15" fill="#444">DRC · connectivity</text>
  <rect x="670" y="20"  width="200" height="62" rx="8" fill="#eaf6ec" stroke="#1a7a2a"/>
  <text x="770" y="46"  text-anchor="middle" font-size="18" font-weight="600" fill="#1a7a2a">PROVEN → ship</text>
  <text x="770" y="68"  text-anchor="middle" font-size="15" fill="#1a7a2a">best verified result</text>
  <rect x="670" y="110" width="200" height="62" rx="8" fill="#fdeeee" stroke="#b03030"/>
  <text x="770" y="136" text-anchor="middle" font-size="18" font-weight="600" fill="#b03030">NOT proven → refuse</text>
  <text x="770" y="158" text-anchor="middle" font-size="15" fill="#b03030">ship the baseline</text>
  <line x1="212" y1="95" x2="296" y2="95" stroke="#444" stroke-width="2" marker-end="url(#a)"/>
  <line x1="582" y1="70" x2="666" y2="52" stroke="#1a7a2a" stroke-width="2" marker-end="url(#a)"/>
  <line x1="582" y1="120" x2="666" y2="140" stroke="#b03030" stroke-width="2" marker-end="url(#a)"/>
  <text x="915" y="100" font-size="15" fill="#666">default =</text>
  <text x="915" y="120" font-size="15" font-weight="600" fill="#666">refuse</text>
</svg>

The model is a **search heuristic over a verified space** — never an authority.
**The system's default is to ship nothing.**

---

# 2 · NVIDIA — improve PPA, stay functionally identical

**Given:** 7 IPs (async_fifo, sha512, NVDLA, OpenTitan aes/ascon/kmac/prim), their
testbenches, a Yosys + OpenSTA ASAP7 flow.
**Scored on:** area × delay vs baseline (**ADP**, lower is better), gated on correctness.

**Five verification layers** — every candidate, every round:

| # | layer | what it answers |
|---|-------|-----------------|
| 1 | lint | structurally sane? |
| 2 | compile | does it elaborate? |
| 3 | **gate** | the IP's own testbench — fail-closed: nonzero rc = FAIL |
| 4 | **LEC** | yosys *proves* equivalence to pristine |
| 5 | dualsim | cycle-exact co-simulation, baseline vs candidate |

**PROVEN binds all of:** `rc==0` + success line + `total>0` + `proven==total` + `unproven==0`.
Anything else is INCONCLUSIVE — never a pass.

**Canonical = LEC-PROVEN.** An unproven candidate is never shipped, however good its ADP.

---

# 3 · NVIDIA — the flow, end to end

<svg viewBox="0 0 1120 250" style="width:100%;height:auto" xmlns="http://www.w3.org/2000/svg">
<defs><marker id="ar" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#666"/></marker></defs>
<rect x="14" y="40" width="196" height="128" rx="9" fill="#eef3fb" stroke="#1a3a6b" stroke-width="1.6"/>
<text x="112" y="68" text-anchor="middle" font-size="17" font-weight="700" fill="#1a3a6b">DIAGNOSE</text>
<text x="112" y="98" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">diagnose.diagnose()</text>
<text x="112" y="118" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">sta_feedback.classify()</text>
<text x="112" y="150" text-anchor="middle" font-size="12" font-style="italic" fill="#1a3a6b">zero tokens</text>
<rect x="232" y="40" width="196" height="128" rx="9" fill="#eef3fb" stroke="#1a3a6b" stroke-width="1.6"/>
<text x="330" y="68" text-anchor="middle" font-size="17" font-weight="700" fill="#1a3a6b">SELECT</text>
<text x="330" y="98" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">_TAG_TO_RUNGS</text>
<text x="330" y="118" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">_risk_gated()</text>
<text x="330" y="150" text-anchor="middle" font-size="12" font-style="italic" fill="#1a3a6b">zero tokens</text>
<line x1="212" y1="104" x2="228" y2="104" stroke="#666" stroke-width="2" marker-end="url(#ar)"/>
<rect x="450" y="40" width="196" height="128" rx="9" fill="#fff4e5" stroke="#b45309" stroke-width="1.6"/>
<text x="548" y="68" text-anchor="middle" font-size="17" font-weight="700" fill="#b45309">PROPOSE</text>
<text x="548" y="98" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">build_prompt()</text>
<text x="548" y="118" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">model.generate()</text>
<text x="548" y="150" text-anchor="middle" font-size="12" font-style="italic" fill="#b45309">THE model call</text>
<line x1="430" y1="104" x2="446" y2="104" stroke="#666" stroke-width="2" marker-end="url(#ar)"/>
<rect x="668" y="40" width="196" height="128" rx="9" fill="#eaf6ec" stroke="#1a7a2a" stroke-width="1.6"/>
<text x="766" y="68" text-anchor="middle" font-size="17" font-weight="700" fill="#1a7a2a">VERIFY</text>
<text x="766" y="98" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">verify.lec()  +4</text>
<text x="766" y="118" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">5 layers</text>
<text x="766" y="150" text-anchor="middle" font-size="12" font-style="italic" fill="#1a7a2a">deterministic</text>
<line x1="648" y1="104" x2="664" y2="104" stroke="#666" stroke-width="2" marker-end="url(#ar)"/>
<rect x="886" y="40" width="196" height="128" rx="9" fill="#eaf6ec" stroke="#1a7a2a" stroke-width="1.6"/>
<text x="984" y="68" text-anchor="middle" font-size="17" font-weight="700" fill="#1a7a2a">DECIDE</text>
<text x="984" y="98" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">_canonical_best()</text>
<text x="984" y="118" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">LEC-PROVEN only</text>
<text x="984" y="150" text-anchor="middle" font-size="12" font-style="italic" fill="#1a7a2a">deterministic</text>
<line x1="866" y1="104" x2="882" y2="104" stroke="#666" stroke-width="2" marker-end="url(#ar)"/>
<text x="560" y="205" text-anchor="middle" font-size="15" fill="#444">STA tells us WHICH file and WHAT structure — so the model is asked for one named transform on one named cone, never &#8220;make it faster&#8221;.</text>
</svg>

**Green is free. Orange is the only probabilistic step. The last two stages are where the
model gets no vote** — five verification layers, then a selector that admits only
formally-proven candidates and otherwise ships the baseline untouched.

---

# 4 · NVIDIA — results, and the ones we refused

| IP | ADP | assurance |
|----|-----|-----------|
| **prim** | **0.5824** | LEC PROVEN + dualsim · power −70% |
| **sha512** | **0.7266** | full 5-layer · timing −97 → **+335 ps (MET)** |
| ascon | 0.97918 | LEC PROVEN + dualsim |
| aes | 1.0001 | differential-only — honestly *"explored-no-adp-gain"* |
| kmac | 1.0 | bounded negative — headroom is inside the masked core |
| **async_fifo** | **1.0 (baseline)** | **deliberately reverted — next slide** |

**Two refusals worth more than the wins:**

- **ascon:** a candidate *beat* the banked ADP — `lec_diagnostic` found a real
  counterexample → **refused**. The gate is load-bearing, not decorative.
- **sha512, live:** a candidate at **ADP 0.6546** — far better than anything we ship —
  was **refused for not being LEC-PROVEN**. The system gave up a 35 % headline number
  rather than ship something it could not prove.

---

# 5 · NVIDIA — the 4 % win that was the bug

Our agent found a **4 % ADP win** on an asynchronous FIFO.
It passed lint. Compile. The testbench. Formal equivalence **PROVED** it. Cycle-exact
differential simulation passed. **Five for five** — our best-verified candidate.

## It was broken.

It removed the registers on the **Gray-code pointer** and computed `gray(bin)`
combinationally. The logic function is identical — *which is why formal proved it*. But at a
**clock-domain crossing** a combinational encoder **glitches** mid-transition, and the
receiving domain samples asynchronously. Intermittent pointer corruption.

We reverted to the registered baseline, then rebuilt the *separable* part of the
optimization on the safe base and measured it: **ADP 0.9984 — noise.**

> **The entire 4 % "win" *was* the hazard.**

---

# 6 · NVIDIA — NVDLA: whole-design formal at scale

**~950,000 cells.** Whole-design equivalence **PROVEN: 381,209 / 381,209 `$equiv` cells**
through the production recipe — uncommon at this scale.

**Release packet: 6/6** — every gate control demonstrated live, including the negatives:

| control | result |
|---|---|
| pristine gate must PASS | ✅ 1 passed / 0 failed |
| **mutant gate must FAIL** | ✅ 0 passed / 1 failed |
| LEC positive PROVEN · LEC negative not-proven | ✅ ✅ |
| candidate-survival tripwire · determinism ×2 | ✅ ✅ |

**We found our own tooling lying.** The packet sat at 5/6 for a day. The failing check was a
bug in *our log parser* — it counted the word "failed" inside the runner's help banner
(`exceeded => failed`) as a test failure. Fixed, re-run, 6/6 — **and the negative control
still fires**, proving the fix did not simply blind the gate.

**Not claimed:** an NVDLA PPA result. The campaign plumbing is unfinished; on a hidden
NVDLA-like case the agent attempts, cannot prove, and **ships baseline**.

---

# 7 · NXP — generate a secure SoC from a block diagram

**Given:** an architecture document and a testbench port skeleton. **Produce synthesizable RTL.**

Model reads the diagram → emits **YAML specs per IP** → `rtl_gen_lib` generates Verilog →
model stitches the top → **correctness firewall** → gate.

**The firewall — deterministic, non-bypassable, ≤3 error-fed re-prompts:**

- **YAML validator** — typed errors *before* any RTL is generated
- **Port contract** — token-level diff of the top's ports vs the skeleton's DUT instantiation
- **Reset lint** — raw POR may feed *only* the synchronizer; one common synchronized net
- **Structural diff** — instance census, IRQ reachability, bus connectivity
- **Port-direction gate** — an instance's output may never be driven by a constant

**Result (easy tier): 2 model calls, ~42 s** — GATE **30/30**, KAT **79/79** against a golden
oracle *and* **79/79** against the model's own oracle, STG differential cycle-identical over
**3,662** cycles.

<span class="dim">Two oracles on purpose: self-consistency proves the model agrees with itself; the golden oracle proves it is right.</span>

---

# 8 · NXP — the night the hidden problems landed

The organizers released **medium** (2×3 TileLink NoC AES SoC) and **hard** (multi-domain
crypto SoC: 4×3 NoC, 4 AES, 2 DMA) — architectures the agent had never seen.

Running them exposed **nine defects in our own agent.** The worst three:

| defect | effect |
|---|---|
| top-module name hardcoded to the easy problem | every other tier failed elaboration |
| prompt budget sized for 8 IPs | **14 of 22** IP interfaces never shown → the model *guessed* ports |
| `top_ports` parsed `#(parameter…)` as the port list | **any parameterised module reported zero ports** — silently disabling direction checks |

**After the fixes — verified with `iverilog` outside the agent:**

| tier | top derived | contract | elaborates |
|------|-------------|----------|-----------|
| easy | `secure_periph_soc` | clean, attempt 1 | ✅ 30/30 + KAT 79/79 ×2 |
| **medium** | `noc_aes_soc` | clean, attempt 3 | ✅ |
| **hard** | `crypto_soc` | clean, attempt 2 | ✅ |

Easy is **byte-for-byte unchanged** — every generalization was made tier-aware so the proven
path was never disturbed.

---

# 9 · NXP — the flow, end to end

<svg viewBox="0 0 1120 250" style="width:100%;height:auto" xmlns="http://www.w3.org/2000/svg">
<defs><marker id="ar" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#666"/></marker></defs>
<rect x="14" y="40" width="196" height="128" rx="9" fill="#eef3fb" stroke="#1a3a6b" stroke-width="1.6"/>
<text x="112" y="68" text-anchor="middle" font-size="17" font-weight="700" fill="#1a3a6b">READ</text>
<text x="112" y="98" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">read_spec()</text>
<text x="112" y="118" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">skeleton_top_name()</text>
<text x="112" y="150" text-anchor="middle" font-size="12" font-style="italic" fill="#1a3a6b">zero tokens</text>
<rect x="232" y="40" width="196" height="128" rx="9" fill="#fff4e5" stroke="#b45309" stroke-width="1.6"/>
<text x="330" y="68" text-anchor="middle" font-size="17" font-weight="700" fill="#b45309">SPEC</text>
<text x="330" y="98" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">prompt_yaml()</text>
<text x="330" y="118" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">yaml_validator()</text>
<text x="330" y="150" text-anchor="middle" font-size="12" font-style="italic" fill="#b45309">THE model call</text>
<line x1="212" y1="104" x2="228" y2="104" stroke="#666" stroke-width="2" marker-end="url(#ar)"/>
<rect x="450" y="40" width="196" height="128" rx="9" fill="#eef3fb" stroke="#1a3a6b" stroke-width="1.6"/>
<text x="548" y="68" text-anchor="middle" font-size="17" font-weight="700" fill="#1a3a6b">GENERATE</text>
<text x="548" y="98" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">generate_ip()</text>
<text x="548" y="118" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">rtl_gen_lib</text>
<text x="548" y="150" text-anchor="middle" font-size="12" font-style="italic" fill="#1a3a6b">zero tokens</text>
<line x1="430" y1="104" x2="446" y2="104" stroke="#666" stroke-width="2" marker-end="url(#ar)"/>
<rect x="668" y="40" width="196" height="128" rx="9" fill="#fff4e5" stroke="#b45309" stroke-width="1.6"/>
<text x="766" y="68" text-anchor="middle" font-size="17" font-weight="700" fill="#b45309">STITCH</text>
<text x="766" y="98" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">prompt_top()</text>
<text x="766" y="118" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">4 validators</text>
<text x="766" y="150" text-anchor="middle" font-size="12" font-style="italic" fill="#b45309">THE model call</text>
<line x1="648" y1="104" x2="664" y2="104" stroke="#666" stroke-width="2" marker-end="url(#ar)"/>
<rect x="886" y="40" width="196" height="128" rx="9" fill="#eaf6ec" stroke="#1a7a2a" stroke-width="1.6"/>
<text x="984" y="68" text-anchor="middle" font-size="17" font-weight="700" fill="#1a7a2a">GATE</text>
<text x="984" y="98" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">run_gate()</text>
<text x="984" y="118" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">KAT x2 oracles</text>
<text x="984" y="150" text-anchor="middle" font-size="12" font-style="italic" fill="#1a7a2a">deterministic</text>
<line x1="866" y1="104" x2="882" y2="104" stroke="#666" stroke-width="2" marker-end="url(#ar)"/>
<text x="560" y="205" text-anchor="middle" font-size="15" fill="#444">No reference design exists — so the proof is CONTRACTS and INDEPENDENT ORACLES, not equivalence. Bad specs die before any RTL is generated.</text>
</svg>

**Two model calls total.** Everything around them is deterministic: the spec validator
runs *before* any Verilog exists, and the stitched top must clear four independent gates
— port contract, reset lint, structural diff, port directions — with typed errors feeding
up to three repair attempts.

---

# 10 · NXP — instructions are probabilistic. Gates are not.

A three-step experiment, run last night:

**1. The model already had the information.**
The port directions were *in the prompt*: `output wire [1:0] p0_d_param`.
It tied constants to those outputs anyway — illegal Verilog, elaboration dies.

**2. We added an explicit prohibition.**
*"An OUTPUT port may NEVER be connected to a constant."*
It complied on **medium** (2 runs of 2). It **violated it on hard.**

**3. We added a deterministic gate.**
`instance_port_directions` compares every connection against the real port direction.
Caught **4/4** violations. The typed error feeds the existing repair loop — and medium and
hard then reached contract-clean at attempts 3 and 2.

> **The model repaired its own output once the gate told it exactly what was wrong.**

Plus a mechanical last resort — `.m_rready(1'b1)` → `.m_rready()` — so a stubborn violation
degrades to an **elaborating** design instead of a zero.

---

# 11 · NXP — what we do and do not claim

**Claimed, and reproducible:**
- easy tier: 2 calls, 30/30 gate, KAT 79/79 on both oracles
- medium and hard: contract-conformant RTL that **elaborates against the organizer's skeleton**,
  on architectures the agent had never seen
- stdlib-only agent; a `_yaml_compat` shim that engages only when PyYAML is absent, parses all
  8 reference specs byte-identically, and returns an **inert string** for `!!python/object`

**Not claimed — and this matters:**
- **No golden testbench ships for *any* tier**, easy included. So medium and hard cannot be
  *scored*. "Elaborates and conforms" ≠ "functionally correct".
- The official runner still hardcodes `PROBLEMS = ["easy"]`; we drove the new tiers through the
  same `Paths.from_info` contract the runner uses.
- Our easy result is **"perfect against our verification stack"** — the organizer's hidden
  testbench is not in the public checkout.

---

# 12 · ASU — repair DRC violations in a layout block

**Given:** a KLayout `pya` layout script, its DRC report, connectivity and design rules.
**Scored on:** final-violation-rate (**FVR**, lower is better), gated on the repair being
valid and connectivity-preserving.

## The result that shows judgment: we took the model out.

The winning repair is **deterministic** — replace each flagged multi-cut via array with one
continuous via **bar**, derived directly from the rule. No model call at runtime.

**Why that was forced, and why it was right:** the official agent image is
`python:3.10-slim` with **no KLayout binary**, run `--read-only`. Our development agent
measured every candidate with the real evaluator to keep-best — impossible there.

So the submission agent applies the proven transform and emits an artifact **byte-identical**
to the independently re-scored development output.

<span class="dim">We used the model to *find* the transform. We did not need it to *apply* the transform.</span>

---

# 13 · ASU — v2 Rev3, all seven blocks, electrically proven

Same-day arc: a 3-round independent layer-aware review found the v1 via-bar created **49
electrical merges invisible to the published checker**; we rebuilt with per-side electrical
guards + a new **track-shift** pass, re-proved every block, and resubmitted (official runner
rehearsal, zero model calls).

| block | kind | valid | conn | v1 FVR | **Rev3 FVR** | electrical partition |
|-------|------|-------|------|--------|--------|------|
| Block1 | public | ✅ | ✅ | 0.7295 | **0.5820** | ✅ equal |
| Block2 | public | ✅ | ✅ | 0.7647 | **0.5147** | ✅ |
| Block3 | public | ✅ | ✅ | 0.7640 | **0.3933** | ✅ |
| Block6 | public | ✅ | ✅ | 0.6761 | **0.4130** | ✅ |
| Block7 | public | ✅ | ✅ | 0.6824 | **0.5804** | ✅ |
| **Block4** | **released Jul 25** | ✅ | ✅ | 0.6939 | **0.3741** | ✅ |
| **Block5** | **released Jul 25** | ✅ | ✅ | 0.7941 | **0.4853** | ✅ |

**7/7 eligible** · mean **0.477** (v1: 0.729) · **Block4/5 blind = its two best** · no-op ≈**1.25–1.32**

---

# 14 · ASU — why it generalized

No tuning. No retraining. No code change. The hidden blocks were released and the agent
scored them in the same band as the public ones.

**Because the repair is derived from the rule, not fitted to the data.**

A model that had been *optimized against the five public blocks* would have no reason to
transfer. A transform decoded from the DRC rule itself has every reason to.

**Three honesty points we put on the slide before anyone asks:**

- **No-op is not FVR 1.0.** FVR is the evaluator's *fresh* DRC total ÷ the *supplied reference*
  total, and those are not count-identical: public no-op FVR is **≈1.25–1.32**.
- **Our own review disqualified our own best number.** The withdrawn v2 draft scored FVR
  0.24–0.39 — but inherited 49 electrical shorts the published checker cannot see. Rev3 gives
  back part of the DRC win to make the connectivity claim *provable* (immutable-anchor
  partition equality, per block, in the repo).
- **Fail-closed by construction.** Landings/moves that cannot be proven electrically safe keep
  their original geometry; on clean or unfamiliar layouts every pass is a verified no-op.

---

# 15 · ASU — the flow, and why the model left it

<svg viewBox="0 0 1120 250" style="width:100%;height:auto" xmlns="http://www.w3.org/2000/svg">
<defs><marker id="ar" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#666"/></marker></defs>
<rect x="14" y="40" width="196" height="128" rx="9" fill="#eef3fb" stroke="#1a3a6b" stroke-width="1.6"/>
<text x="112" y="68" text-anchor="middle" font-size="17" font-weight="700" fill="#1a3a6b">DIAGNOSE</text>
<text x="112" y="98" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">drc_digest.load()</text>
<text x="112" y="118" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">match_rule()</text>
<text x="112" y="150" text-anchor="middle" font-size="12" font-style="italic" fill="#1a3a6b">zero tokens</text>
<rect x="232" y="40" width="196" height="128" rx="9" fill="#eef3fb" stroke="#1a3a6b" stroke-width="1.6"/>
<text x="330" y="68" text-anchor="middle" font-size="17" font-weight="700" fill="#1a3a6b">REPAIR</text>
<text x="330" y="98" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">repairs.via_bar_pass()</text>
<text x="330" y="118" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">deterministic</text>
<text x="330" y="150" text-anchor="middle" font-size="12" font-style="italic" fill="#1a3a6b">zero tokens</text>
<line x1="212" y1="104" x2="228" y2="104" stroke="#666" stroke-width="2" marker-end="url(#ar)"/>
<rect x="450" y="40" width="196" height="128" rx="9" fill="#eaf6ec" stroke="#1a7a2a" stroke-width="1.6"/>
<text x="548" y="68" text-anchor="middle" font-size="17" font-weight="700" fill="#1a7a2a">MEASURE</text>
<text x="548" y="98" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">verify.measure()</text>
<text x="548" y="118" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">pinned KLayout</text>
<text x="548" y="150" text-anchor="middle" font-size="12" font-style="italic" fill="#1a7a2a">deterministic</text>
<line x1="430" y1="104" x2="446" y2="104" stroke="#666" stroke-width="2" marker-end="url(#ar)"/>
<rect x="668" y="40" width="196" height="128" rx="9" fill="#eaf6ec" stroke="#1a7a2a" stroke-width="1.6"/>
<text x="766" y="68" text-anchor="middle" font-size="17" font-weight="700" fill="#1a7a2a">SHIP</text>
<text x="766" y="98" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">official agent.py</text>
<text x="766" y="118" text-anchor="middle" font-size="13" font-family="monospace" fill="#333">NO model call</text>
<text x="766" y="150" text-anchor="middle" font-size="12" font-style="italic" fill="#1a7a2a">deterministic</text>
<line x1="648" y1="104" x2="664" y2="104" stroke="#666" stroke-width="2" marker-end="url(#ar)"/>
<text x="560" y="205" text-anchor="middle" font-size="15" fill="#444">The model helped us FIND the transform. The shipped agent does not call it — the official image has no KLayout, so measure-and-keep-best is impossible there.</text>
</svg>

**Two agents.** The development agent measures every candidate with the organizers' own
evaluator and keeps the best — that is how we *found* the via-bar transform. The shipped
agent is seven functions, stdlib-only, and makes zero model calls.

---

# 16 · Three domains, one finding

|  | the model was told | what happened | what worked |
|---|---|---|---|
| **NVIDIA** | — | a candidate passed **all five layers incl. LEC-PROVEN** and was still unsafe (CDC glitch) | a **structural invariant**, not more checking |
| **NXP** | port directions, in the prompt | ignored them; obeyed an explicit rule on one problem, broke the other | a **deterministic gate** — 4/4, every time |
| **ASU** | — | hidden blocks scored in-band, untouched | the transform is **derived from the rule**, not fitted |

## Deterministic gates beat model instructions.

That is what makes **unseen inputs** survivable — and unseen inputs are the whole game.

---

# 17 · What formal and simulation structurally cannot see

LEC and zero-delay simulation reason in a model where **glitches and physical side-channels
do not exist.** Two classes of edit therefore pass every functional check and are still broken:

**1 · Side-channel masking removal** — aes S-box, kmac DOM-masked Keccak.
Un-masking preserves the logic function *exactly*, so **LEC returns PROVEN** while the
countermeasure is destroyed. Formally equivalent, cryptographically broken.

**2 · CDC glitch hazards** — async_fifo (slide 4).
Neither formal nor zero-delay simulation can represent a glitch.

## You cannot fix this by adding more checking.

The bug lives **outside the model the checkers use**. The answer is **structural policy**:
per-IP forbidden edit zones (FENCEs — implemented, mandatory for NVDLA), and a
registered-crossing invariant for CDC.

<span class="dim">Honest status: the FENCEs are enforced in tooling; the CDC invariant was implemented this week after we caught the agent re-selecting the candidate we had manually reverted — by running our own submission the way a judge would.</span>

---

# 18 · Every claim, one command

| track | headline | verify it |
|---|---|---|
| **NVIDIA** | prim **0.5824**, sha512 **0.7266**, both LEC-PROVEN | `submission/<ip>/manifest.json` — per-layer assurance is recorded per artifact |
| | NVDLA formal **381,209/381,209**; packet **6/6** | `python3.12 -m ppa.release_control --ip nvdla` |
| **NXP** | easy 2 calls · **30/30** · KAT **79/79 ×2** | `python3 nxp_agent.py --model stub` |
| | medium + hard **elaborate**, unseen | `iverilog -g2005 <rtl>/*.v <tb_top_skeleton.v>` |
| **ASU** | **7/7** eligible, Rev3 mean FVR **0.477**, electrical partition proven | `asu_v2/tests/run_controls.sh` + `evaluator/evaluate_repair.py --case Block4` |

**Reproducibility is the point.** NXP and ASU reproduce byte-identically. The NVIDIA
*artifacts* re-synthesize exactly; re-running the *search* is stochastic — and we say so.

**The architecture, in one line:** the model proposes, deterministic gates dispose, and the
default is to ship the baseline.

<!-- _footer: "" -->

---

<!-- _class: lead -->

# Backup

Flow diagrams · number sheet · what we do not claim

---

# B1 · NVIDIA — the full flow

<svg viewBox="0 0 1160 470" style="width:100%;height:auto" xmlns="http://www.w3.org/2000/svg">
<defs>
<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#1a3a6b"/></marker>
<marker id="arg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#1a7a2a"/></marker>
<marker id="ara" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#b07a1a"/></marker>
</defs>
<style>
.t{font:600 14px sans-serif;fill:#1a3a6b}.s{font:12px sans-serif;fill:#333}
.tiny{font:10.5px sans-serif;fill:#555}.w{font:600 12.5px sans-serif;fill:#fff}
.box{fill:#eef3fa;stroke:#1a3a6b;stroke-width:1.4;rx:8}
.gbox{fill:#e8f5e9;stroke:#1a7a2a;stroke-width:1.6;rx:8}
.abox{fill:#fdf3e0;stroke:#b07a1a;stroke-width:1.4;rx:8}
.hdr{fill:#1a3a6b;rx:8}
</style>

<!-- ── PHASE 0: diagnose (left column) ─────────────────────────── -->
<rect x="8" y="10" width="232" height="30" class="hdr"/>
<text x="124" y="30" text-anchor="middle" class="w">0 · DIAGNOSE — zero tokens</text>
<rect x="16" y="52" width="216" height="52" class="box"/>
<text x="124" y="72" text-anchor="middle" class="t" font-size="12.5">baseline synth + STA</text>
<text x="124" y="90" text-anchor="middle" class="tiny">pristine clone · Docker Yosys + OpenSTA → PPA₀</text>
<line x1="124" y1="104" x2="124" y2="122" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#ar)"/>
<rect x="16" y="124" width="216" height="88" class="box"/>
<text x="124" y="144" text-anchor="middle" class="t" font-size="12.5">3-axis diagnosis</text>
<text x="124" y="162" text-anchor="middle" class="tiny">timing: FLATTEN=0 STA → worst path → files</text>
<text x="124" y="177" text-anchor="middle" class="tiny">area: per-module cells · power: seq-mass proxy</text>
<text x="124" y="196" text-anchor="middle" class="tiny">+ structure tag → matched playbook rules</text>
<line x1="124" y1="212" x2="124" y2="230" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#ar)"/>
<rect x="16" y="232" width="216" height="64" class="gbox"/>
<text x="124" y="252" text-anchor="middle" class="t" font-size="12.5">critical files, path-ordered</text>
<text x="124" y="270" text-anchor="middle" class="s">1·core  2·w_mem  3·top  4·h_c  5·k_c</text>
<text x="124" y="287" text-anchor="middle" class="tiny">= the campaign cursor (worst first)</text>
<line x1="232" y1="264" x2="262" y2="264" stroke="#1a3a6b" stroke-width="2" marker-end="url(#ar)"/>

<!-- ── STAGE LOOP (center) ─────────────────────────────────────── -->
<rect x="264" y="10" width="612" height="500" fill="none" stroke="#1a3a6b" stroke-width="1.8" stroke-dasharray="7 4" rx="12"/>
<rect x="284" y="0" width="572" height="22" fill="#fff"/>
<text x="570" y="16" text-anchor="middle" class="t">STAGE i — repeat down the cursor · budget = 20 proposal turns (k=6, then 4)</text>

<rect x="286" y="36" width="568" height="46" class="box"/>
<text x="570" y="54" text-anchor="middle" class="t" font-size="12.5">context: file[i] EDITABLE · other critical files READ-ONLY (≤6) · rules · PPA · budget</text>
<text x="570" y="71" text-anchor="middle" class="tiny">parent = best-so-far design (locked wins carried forward)</text>
<line x1="570" y1="82" x2="570" y2="98" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#ar)"/>

<g>
<rect x="318" y="100" width="76" height="34" class="box"/><text x="356" y="121" text-anchor="middle" class="tiny">balanced-tree</text>
<rect x="402" y="100" width="76" height="34" class="box"/><text x="440" y="121" text-anchor="middle" class="tiny">carry-save</text>
<rect x="486" y="100" width="76" height="34" class="box"/><text x="524" y="121" text-anchor="middle" class="tiny">arith-arch</text>
<rect x="570" y="100" width="76" height="34" class="box"/><text x="608" y="121" text-anchor="middle" class="tiny">restructure</text>
<rect x="654" y="100" width="76" height="34" class="box"/><text x="692" y="121" text-anchor="middle" class="tiny">micro-opt</text>
<rect x="738" y="100" width="76" height="34" class="box"/><text x="776" y="121" text-anchor="middle" class="tiny">share-res</text>
<text x="847" y="113" class="tiny" text-anchor="middle">k Gemini</text>
<text x="847" y="127" class="tiny" text-anchor="middle">calls</text>
</g>
<line x1="570" y1="134" x2="570" y2="150" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#ar)"/>

<rect x="316" y="152" width="508" height="34" class="abox"/>
<text x="570" y="173" text-anchor="middle" class="s">strict scope filter: out-of-scope / hallucinated edits <tspan font-weight="600">dropped</tspan> · S-box fence</text>
<line x1="570" y1="186" x2="570" y2="202" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#ar)"/>

<g>
<rect x="296" y="204" width="66" height="34" class="box"/><text x="329" y="225" text-anchor="middle" class="tiny">lint</text>
<line x1="362" y1="221" x2="376" y2="221" stroke="#1a3a6b" stroke-width="1.4" marker-end="url(#ar)"/>
<rect x="378" y="204" width="76" height="34" class="box"/><text x="416" y="225" text-anchor="middle" class="tiny">compile</text>
<line x1="454" y1="221" x2="468" y2="221" stroke="#1a3a6b" stroke-width="1.4" marker-end="url(#ar)"/>
<rect x="470" y="204" width="76" height="34" class="box"/><text x="508" y="225" text-anchor="middle" class="tiny">TB gate</text>
<line x1="546" y1="221" x2="560" y2="221" stroke="#1a3a6b" stroke-width="1.4" marker-end="url(#ar)"/>
<rect x="562" y="204" width="96" height="34" class="box"/><text x="610" y="220" text-anchor="middle" class="tiny">synth + STA</text><text x="610" y="232" text-anchor="middle" class="tiny">(isolated wkspaces)</text>
<line x1="658" y1="221" x2="672" y2="221" stroke="#1a3a6b" stroke-width="1.4" marker-end="url(#ar)"/>
<rect x="674" y="204" width="106" height="34" class="box"/><text x="727" y="220" text-anchor="middle" class="tiny">yosys LEC</text><text x="727" y="232" text-anchor="middle" class="tiny">+ dual-inst diff sim</text>

</g>
<line x1="570" y1="238" x2="570" y2="256" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#ar)"/>

<polygon points="570,258 660,290 570,322 480,290" fill="#eef3fa" stroke="#1a3a6b" stroke-width="1.6"/>
<text x="570" y="286" text-anchor="middle" class="t" font-size="12.5">proven &amp;</text>
<text x="570" y="302" text-anchor="middle" class="t" font-size="12.5">better?</text>

<!-- YES branch -->
<line x1="660" y1="290" x2="700" y2="290" stroke="#1a7a2a" stroke-width="2" marker-end="url(#arg)"/>
<text x="678" y="282" class="tiny" fill="#1a7a2a">yes</text>
<rect x="702" y="262" width="152" height="56" class="gbox"/>
<text x="778" y="283" text-anchor="middle" class="t" font-size="12.5" fill="#1a7a2a">ACCEPT best</text>
<text x="778" y="301" text-anchor="middle" class="tiny">LOCK file[i] (read-only from now)</text>
<path d="M 830 262 L 830 90 L 856 90" fill="none" stroke="#1a7a2a" stroke-width="2" stroke-dasharray="5 3"/>
<text x="838" y="245" class="tiny" fill="#1a7a2a" text-anchor="end">next file</text>



<!-- NO branch: repair -->
<line x1="480" y1="290" x2="440" y2="290" stroke="#b07a1a" stroke-width="2" marker-end="url(#ara)"/>
<text x="462" y="282" class="tiny" fill="#b07a1a">no win</text>
<rect x="286" y="336" width="360" height="62" class="abox"/>
<text x="466" y="356" text-anchor="middle" class="t" font-size="12.5" fill="#b07a1a">PPA-ranked gate-fail repair (off-budget)</text>
<text x="466" y="373" text-anchor="middle" class="tiny">synth broken candidates in parallel → keep PPA-improvers →</text>
<text x="466" y="387" text-anchor="middle" class="tiny">repair top-2 (1 attempt, TB failures fed back) → re-verify</text>
<line x1="440" y1="290" x2="440" y2="334" stroke="#b07a1a" stroke-width="2" marker-end="url(#ara)"/>
<path d="M 646 367 L 700 367 L 700 322" fill="none" stroke="#b07a1a" stroke-width="1.8" marker-end="url(#ara)"/>
<text x="570" y="425" text-anchor="middle" class="tiny">either way: cursor advances (no retry — k is the diversity) · plateau stop if frontier is flat</text>

<!-- ── OUTPUTS (right column) ──────────────────────────────────── -->
<rect x="892" y="10" width="260" height="30" class="hdr"/>
<text x="1022" y="30" text-anchor="middle" class="w">OUTPUTS · LEARNING</text>
<rect x="900" y="52" width="244" height="52" class="box"/>
<text x="1022" y="72" text-anchor="middle" class="t" font-size="12.5">design pool + Pareto frontier</text>
<text x="1022" y="90" text-anchor="middle" class="tiny">every accept banked, RTL persisted</text>
<rect x="900" y="118" width="244" height="52" class="box"/>
<text x="1022" y="138" text-anchor="middle" class="t" font-size="12.5">reflector → playbook</text>
<text x="1022" y="156" text-anchor="middle" class="tiny">rules voted per round, injected next stage</text>
<path d="M 900 144 L 866 144 L 866 59 L 858 59" fill="none" stroke="#666" stroke-width="1.5" stroke-dasharray="4 3" marker-end="url(#ar)"/>
<rect x="900" y="184" width="244" height="66" class="gbox"/>
<text x="1022" y="205" text-anchor="middle" class="t" font-size="12.5" fill="#1a7a2a">--emit-best artifact</text>
<text x="1022" y="222" text-anchor="middle" class="tiny">repo-layout files + manifest.json</text>
<text x="1022" y="237" text-anchor="middle" class="tiny">(PPA Δ, verification, calls, tokens)</text>

<path d="M 854 290 L 1022 290 L 1022 252" fill="none" stroke="#1a7a2a" stroke-width="2" marker-end="url(#arg)"/>

</svg>

<span style="font-size:16px;color:#555">Banked: sha512 <b>ADP 0.7266</b> full 5-layer · prim <b>ADP 0.5824</b> LEC-PROVEN + dualsim (power −70%) · async_fifo ships <b>baseline</b> by design.</span>

---

# B2 · NXP — the full flow

<svg viewBox="0 0 1160 480" style="width:100%;height:auto" xmlns="http://www.w3.org/2000/svg">
<defs>
<marker id="nar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#1a3a6b"/></marker>
<marker id="nara" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#b07a1a"/></marker>
<marker id="narg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#1a7a2a"/></marker>
</defs>
<style>
.t{font:600 14px sans-serif;fill:#1a3a6b}.s{font:12px sans-serif;fill:#333}
.tiny{font:10.5px sans-serif;fill:#555}.w{font:600 12.5px sans-serif;fill:#fff}
.box{fill:#eef3fa;stroke:#1a3a6b;stroke-width:1.4;rx:8}
.mbox{fill:#1a3a6b;rx:8}
.gbox{fill:#e8f5e9;stroke:#1a7a2a;stroke-width:1.6;rx:8}
.abox{fill:#fdf3e0;stroke:#b07a1a;stroke-width:1.4;rx:8}
.hdr{fill:#1a3a6b;rx:8}
</style>

<!-- ── EXTRACT (left) ──────────────────────────────────────────── -->
<rect x="8" y="10" width="236" height="30" class="hdr"/>
<text x="126" y="30" text-anchor="middle" class="w">0 · EXTRACT — zero tokens</text>
<rect x="16" y="52" width="220" height="44" class="box"/>
<text x="126" y="70" text-anchor="middle" class="t" font-size="12.5">tb_skeleton → port contract</text>
<text x="126" y="87" text-anchor="middle" class="tiny">exact top ports, directions, widths</text>
<rect x="16" y="104" width="220" height="44" class="box"/>
<text x="126" y="122" text-anchor="middle" class="t" font-size="12.5">generator source → schema</text>
<text x="126" y="139" text-anchor="middle" class="tiny">every required() param, per ip_type</text>
<rect x="16" y="156" width="220" height="44" class="box"/>
<text x="126" y="174" text-anchor="middle" class="t" font-size="12.5">library demos → exemplars</text>
<text x="126" y="191" text-anchor="middle" class="tiny">known-good values (e.g. baud dividers)</text>
<rect x="16" y="208" width="220" height="44" class="box"/>
<text x="126" y="226" text-anchor="middle" class="t" font-size="12.5">architecture doc → doc facts</text>
<text x="126" y="243" text-anchor="middle" class="tiny">IRQ source map, instance hints</text>
<line x1="126" y1="252" x2="126" y2="266" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#nar)"/>
<rect x="16" y="268" width="220" height="40" class="gbox"/>
<text x="126" y="286" text-anchor="middle" class="t" font-size="12.5" fill="#1a7a2a">constraint bundle</text>
<text x="126" y="301" text-anchor="middle" class="tiny">ground truth in every prompt</text>
<line x1="236" y1="288" x2="262" y2="288" stroke="#1a3a6b" stroke-width="2" marker-end="url(#nar)"/>

<!-- ── GENERATE (center) ───────────────────────────────────────── -->
<rect x="264" y="10" width="600" height="460" fill="none" stroke="#1a3a6b" stroke-width="1.8" stroke-dasharray="7 4" rx="12"/>
<rect x="300" y="0" width="528" height="22" fill="#fff"/>
<text x="564" y="16" text-anchor="middle" class="t">GENERATE — every model boundary gated · typed errors → bounded repairs</text>

<rect x="300" y="34" width="528" height="38" class="mbox"/>
<text x="564" y="51" text-anchor="middle" class="w">MODEL CALL 1 — infer YAML spec per IP (diagram + constraint bundle)</text>
<text x="564" y="65" text-anchor="middle" class="w" font-size="10.5" opacity="0.8">multi-doc split · fenced-block fallback parsing</text>
<line x1="564" y1="72" x2="564" y2="86" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#nar)"/>
<rect x="316" y="88" width="496" height="32" class="abox"/>
<text x="564" y="108" text-anchor="middle" class="s">YAML validator — schema + required params · typed errors, ≤2 re-prompts ⟲</text>
<line x1="564" y1="120" x2="564" y2="134" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#nar)"/>
<rect x="316" y="136" width="496" height="34" class="box"/>
<text x="564" y="157" text-anchor="middle" class="t" font-size="12.5">rtl_gen_lib: YAML → Verilog per IP (+ auto-patch known library bugs)</text>
<line x1="564" y1="170" x2="564" y2="184" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#nar)"/>
<rect x="316" y="186" width="496" height="32" class="abox"/>
<text x="564" y="206" text-anchor="middle" class="s">generator errors fed back verbatim · ≤2 repairs ⟲</text>
<line x1="564" y1="218" x2="564" y2="232" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#nar)"/>
<rect x="316" y="234" width="496" height="32" class="box"/>
<text x="564" y="254" text-anchor="middle" class="t" font-size="12.5">module-interface index — exact headers parsed from generated RTL</text>
<line x1="564" y1="266" x2="564" y2="280" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#nar)"/>
<rect x="300" y="282" width="528" height="36" class="mbox"/>
<text x="564" y="304" text-anchor="middle" class="w">MODEL CALL 2 — stitch secure_periph_soc (interfaces given, not guessed)</text>
<line x1="564" y1="318" x2="564" y2="332" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#nar)"/>
<rect x="316" y="334" width="496" height="36" class="abox"/>
<text x="564" y="349" text-anchor="middle" class="s">port contract · reset lint · structural diff (census, IRQ reachability,</text>
<text x="564" y="363" text-anchor="middle" class="s">dangling ports) — typed errors, ≤3 repairs ⟲ · sabotage-validated 8/8</text>
<line x1="564" y1="370" x2="564" y2="384" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#nar)"/>
<rect x="316" y="386" width="496" height="36" class="gbox"/>
<text x="564" y="401" text-anchor="middle" class="t" font-size="12.5" fill="#1a7a2a">top accepted — best-effort RTL ALWAYS ships</text>
<text x="564" y="416" text-anchor="middle" class="tiny">a partial score beats the guaranteed 0 of a missing module</text>
<path d="M 812 404 L 876 404 L 876 72 L 894 72" fill="none" stroke="#1a7a2a" stroke-width="2" marker-end="url(#narg)"/>

<!-- ── VERIFY (right) ──────────────────────────────────────────── -->
<rect x="890" y="10" width="262" height="30" class="hdr"/>
<text x="1021" y="30" text-anchor="middle" class="w">VERIFY — deterministic, 0 tokens</text>
<rect x="898" y="52" width="246" height="40" class="box"/>
<text x="1021" y="70" text-anchor="middle" class="t" font-size="12.5">30-check staged self-test TB</text>
<text x="1021" y="86" text-anchor="middle" class="tiny">reset → r/w → function → irq → wdt → priv</text>
<line x1="1021" y1="92" x2="1021" y2="106" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#nar)"/>
<rect x="898" y="108" width="246" height="64" class="box"/>
<text x="1021" y="126" text-anchor="middle" class="t" font-size="12.5">KAT: 79 checks, dual oracle</text>
<text x="1021" y="143" text-anchor="middle" class="tiny">golden-calibrated models + predictions from</text>
<text x="1021" y="157" text-anchor="middle" class="tiny">the agent's OWN inferred YAML — no golden needed</text>
<line x1="1021" y1="172" x2="1021" y2="186" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#nar)"/>
<rect x="898" y="188" width="246" height="40" class="box"/>
<text x="1021" y="206" text-anchor="middle" class="t" font-size="12.5">STG differential</text>
<text x="1021" y="222" text-anchor="middle" class="tiny">dual-SoC random stimulus, cycle-by-cycle</text>
<line x1="1021" y1="228" x2="1021" y2="242" stroke="#1a3a6b" stroke-width="1.6" marker-end="url(#nar)"/>
<rect x="898" y="244" width="246" height="40" class="gbox"/>
<text x="1021" y="262" text-anchor="middle" class="t" font-size="12.5" fill="#1a7a2a">emit → output_dir + usage.json</text>
<text x="1021" y="278" text-anchor="middle" class="tiny">runner contract e2e: 6/6</text>
<text x="1021" y="310" text-anchor="middle" class="tiny">any layer fails → typed evidence</text>
<text x="1021" y="324" text-anchor="middle" class="tiny">→ back into the repair loops</text>
</svg>

<span style="font-size:16px;color:#555">Live: <b>2 model calls, 42 s</b> → 30/30 · KAT 79/79 (both oracles) · STG 3662 cycles, <b>0 differing</b> vs hand-built reference.</span>

---

# B3 · ASU — the full flow

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
<text x="475" y="78" text-anchor="middle" class="tiny">deterministic: via-bar (multi-cut array -> continuous bar), grid-snap</text>
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

# B4 · Verified number sheet

**NVIDIA** (ADP, baseline = 1.0, lower better)
prim **0.5824** LEC-PROVEN+dualsim, power −70% · sha512 **0.7266** full 5-layer, WNS −97 → +335 ps
ascon **0.97918** PROVEN · aes **1.0001** differential-only · kmac **1.0** bounded negative
async_fifo **1.0** deliberate revert · NVDLA formal **381,209/381,209**, release packet **6/6**
Refused: ascon INEQUIVALENT counterexample; sha512 **0.6546** unproven → refused

**NXP** easy: **2** calls / ~42 s · GATE **30/30** · KAT **79/79** golden + **79/79** model ·
STG differential **3,662** cycles · medium (`noc_aes_soc`) and hard (`crypto_soc`) elaborate,
contract-clean at attempts 3 and 2

**ASU v2 Rev3** 7/7 eligible · FVR **0.374–0.582** (mean **0.477**; v1 was 0.729) ·
electrical partition preserved on all 7 (layer-aware proof) · Block4/5 scored blind: **0.3741 / 0.4853**

**Reproduction, 2026-07-24/25:** fresh GitHub clone → NXP stub 30/30 + KAT 79/79×2; ASU output
**byte-identical** (`fdae65dd…`) under `python:3.10-slim --read-only`; NVIDIA prim re-run
improved to **0.5762** LEC-PROVEN.

---

# B5 · What we deliberately do NOT claim

- **Not claimed:** an NVDLA optimization result. Whole-design formal proves; the campaign
  plumbing is unfinished and the contract stays `PENDING` — every real model campaign is refused.
- **Not claimed:** an official NXP hidden-testbench score. **No golden testbench ships for any
  tier.** medium/hard "elaborate and conform" ≠ "functionally correct".
- **Not claimed:** ASU "can never be worse" — it was a net win on all five public blocks; some
  individual violation classes appear while the total falls.
- **Not claimed:** full 5-layer assurance on prim or aes — their manifests record
  `gate: SKIP-preexisting` and label the result **equivalence+differential**.
- **Not claimed:** "no model can improve kmac" — bounded probes found nothing; that is a
  bounded negative, not a universal.
- **Not claimed:** run-to-run identity of the NVIDIA search. A shallower run legitimately
  produced sha512 0.7814 where a deeper one produced 0.7266. The *artifact* reproduces; the
  *search* is stochastic.

**Every one of these was, at some point, stated too strongly in our own documents — and
corrected.** We audit our own claims.
