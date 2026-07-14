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
  section.lead h1 { font-size: 52px; }
  section.lead { text-align: center; }
  .ok { color: #1a7a2a; font-weight: 600; }
  .bad { color: #b03030; font-weight: 600; }
  footer { font-size: 14px; color: #888; }
footer: "Chip Convergence — ICLAD-DAC 2026 — NXP SoC Generation"
---

<!-- _class: lead -->
<!-- _footer: "" -->

# The Library Is the Oracle

## Verification-first SoC generation from diagrams

**Diagram → verified SoC: 2 model calls, 42 seconds —
30/30 self-test · KAT 79/79 (both oracles) · cycle-identical to reference**

Harikrishnan KC · Team **Chip Convergence** · greatharikrishnan@gmail.com
NXP Problem · ICLAD-DAC 2026 GenAI Chip Hackathon

---

# 1 · The problem, and what actually scores

**Given:** one architecture HTML (diagrams + minimal spec), a TB skeleton fixing the top
port contract, and `rtl_gen_lib` (YAML → Verilog generators). No YAML, no RTL, no text spec.

**The agent must:** read diagrams → infer YAML per IP → generate → stitch
`secure_periph_soc` → verify.

**Scoring reality:**

| Dimension | Rule | Consequence for agent design |
|---|---|---|
| Correctness | hidden golden TB, `passed/total` | **compile fail = 0** → never ship a broken top |
| Efficiency | total tokens, tiebreak | every re-prompt must earn its cost |
| Evaluation | runner invokes agent via `info.json` + HTTP model endpoint | contract compliance is table stakes |

---

<!-- _footer: "" -->

# 2 · What we do — one picture

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

# 3 · Principles

1. **Tools before tokens** — the port contract, the YAML schema, the known-good exemplars
   and the doc facts are *extracted deterministically* from the provided materials and
   injected as ground truth; the model reads diagrams, not tea leaves.
2. **Constraints enforced by tooling, not prompting** — published evidence (SLDB,
   SpecAssess): frontier models alter ports they were told not to touch; reset semantics is
   the #1 silently-misspecified element. Every model boundary gets a deterministic gate.
3. **Every failure is a typed error** — and typed errors are repair fuel: bounded,
   targeted re-prompts with the exact violation, never "try again".
4. **Verify without a golden** — the oracle predicts from the agent's *own declared design*,
   so it works on hidden testcases where no reference exists.
5. **Always ship** — best-effort RTL beats the guaranteed zero of a missing module.

---

# 4 · Tools before tokens: what's extracted, zero-token

| Extracted (deterministically, at runtime) | From | Feeds |
|---|---|---|
| Exact top-port contract (names, dirs, widths) | `tb_skeleton` | stitch prompt + hard gate |
| Required-params schema, per ip_type | generator *source* (`required()` calls) | spec prompt + YAML validator |
| Known-good exemplar values | library demo specs | spec prompt (e.g. baud divider) |
| IRQ source map, instance hints | architecture doc text | spec + stitch prompts |
| Module-interface index (exact headers) | the just-generated RTL | stitch prompt — ports *given*, not guessed |

All of it re-derives itself on **any** testcase — nothing is hardcoded to the easy SoC.
The live proof: `default_div = 26` appears **nowhere in the doc**; it was recovered from
library demo exemplars (115200 baud @ 50 MHz) — the library's implicit knowledge, mined.

---

# 5 · The correctness firewall (all sabotage-validated)

| Gate | Catches | Validated |
|---|---|---|
| `port_contract` | renamed / missing / wrong-width top ports vs skeleton | typed errors on all fault classes |
| `reset_lint` | por_n feeding anything but the synchronizer; split reset nets | reset = the known killer |
| `structural_diff` | instance census, dangling ports, IRQ reachability, fabric hang-off, bridge bus | **8/8** sabotage suite |
| library fixups | known non-compiling generator output (auto-patch) | behavior-neutral |

Example typed error, verbatim from a live run — this text *is* the repair prompt:

```
struct-irq: i_uart.irq net 'uart_irq' never reaches u_irq_aggregator.irq_src
```

---

# 6 · Verification depth: three independent layers

**1. 30-check staged self-test TB** — reset → r/w → function → irq → watchdog → privilege;
first-failing stage localizes bugs for repair.

**2. KAT engine** — 125-command vector program, **79 known-answer checks**, replay-TB +
Python comparison, two oracles.

**3. STG differential** — dual-SoC random-stimulus trace diff (LCG + burst schedules),
cycle-by-cycle.

The layers are complementary — measured example: a FIFO_DEPTH 16→8 sabotage **passes the
30-check TB (30/30)** but the KAT status read catches it in 5 trace lines:
`0x89 vs 0x88` — literally the `tx_full` bit.

---

# 7 · The earned asset: 20 library IPs, modeled bugs-included

The hidden golden TB is built on the **same generator library** — so our reference models
are transcribed from the generated RTL, statement-for-statement, **quirks preserved**
(a "first-principles correct" model would *fail* the golden TB — the library watchdog's
kick genuinely never reloads, and our model asserts that actual behavior):

- cycle-stepped Python models for **all 20 library ip_types**
- easy-8 calibrated against golden-recorded traces: **0 mismatches**
- other 12 (AXI, TileLink, AES-128, FIFOs/SRAMs): **12/12 lockstep** vs library RTL,
  2000 cycles each; AES bit-exact over ~150 encryptions

This suite is the NXP counterpart of a rule library: **earned by measurement, versioned,
and reused by every layer of verification.**

---

# 8 · Hidden testcases: an oracle that needs no golden

**KAT model path:** replay vectors on the candidate → predict expected values from the
reference models **parameterized by the agent's own inferred YAML** → compare.
No golden RTL, no golden TB required.

Proof the oracle follows the declared design (not a hardcoded answer):

| Candidate SoC | Model believes | Result |
|---|---|---|
| UART FIFO depth 8 | `fifo_depth: 16` | <span class="bad">FAIL 76/79</span> — catches the divergence |
| UART FIFO depth 8 | `fifo_depth: 8` (plumbed) | <span class="ok">PASS 79/79</span> — consistent design accepted |

Structural gates activate **by role present in the design** (fabric checks only if a fabric
exists…). Runner contract: `python3 nxp_agent.py <info.json> --model <name>` — **6/6**
end-to-end against a mock endpoint. Stdlib-only Python + iverilog.

---

# 9 · The result: perfect solve, 2 calls, 42 seconds

```
[1] model returned 8 YAML spec block(s)
[2] generated 8 IP file(s): ['sys_rst_sync.v', 'ahb_brg0.v', 'apb_fab0.v', 'uart0.v',
    'gpio0.v', 'timer0.v', 'wdt0.v', 'irq_agg0.v']
[3] wrote secure_periph_soc.v (contract clean, attempt 1)
[4] GATE: PASS — 30/30 PASS
[4b] KAT(golden): PASS — 79/79
[4b] KAT(model):  PASS — 79/79
[5] STG-DIFF: MATCH — 3662 cycles, 0 differing
    model calls: 2
```

The generated SoC is **cycle-identical** to our hand-built reference over 3662 random
cycles — and the whole solve cost **2 model calls / ~40k tokens**.

---

# 10 · Medium/hard readiness

The library ships **20 generators; easy uses 8**. The other 12 are the likely
medium/hard vocabulary — already modeled and validated:

- AXI-Lite: crossbar (2M×3S), SRAM, DMA engine — 12/12 lockstep
- TileLink: router, network interface
- AES-128 (bit-exact), FIFOs (sync/async gray-code), SRAMs, CDC, perf counter

Known library quirks catalogued (golden-TB-relevant): AES core **ignores its `encrypt`
input**; TL router implements **no mesh routing** (all→local). Generator `MissingParameter`
errors are typed and model-directed — purpose-built repair material.

---

# 11 · Economics & contest contributions

| Item | Cost |
|---|---|
| Perfect easy-tier solve | **2 calls / ~40k tokens** |
| Repair bounds | ≤2 spec re-prompts, ≤2 generator-repair, ≤3 stitch |
| Prevention > repair | schema in the *first* prompt ended the omission loop |
| Every verification gate | free — deterministic, local, zero tokens |

**3 toolkit bugs found & reported** (details in the Learnings deck): `dma_engine` generates
non-compiling RTL (hits *every* team; we auto-patch, behavior-neutral) · `apb_watchdog`
kick never reloads (modeled as-is — oracle correctness) · NVIDIA aes flow masked failure.

---

# 12 · Next: what we build before DAC (agents updatable to Jul 26)

- **Testcase digest (designed)** — deterministic parse of the architecture doc's address-map
  tables + instance inventory, cross-checked against the model's specs; mismatches feed the
  existing repair loops. The per-testcase analog of our zero-token extraction — insurance
  for medium/hard doc complexity.
- **K-vote spec inference** — field-level majority across independent diagram reads;
  disagreement → targeted re-look (defense vs consistent misreads)
- **Best-of-M stitches** — KAT-model score as the selector
- **Model mixing on unlimited Vertex (Jul 19+)** — strong model for diagram reading,
  cheap model for repairs
- Medium/hard fixtures composed from the 12 modeled IPs; live-testcase runbook in repo

---

# 13 · Summary — every claim, one command

| Claim | Reproduce with |
|---|---|
| Full pipeline offline | `python3 nxp_agent.py --model stub` → 30/30, KAT 79/79 ×2 |
| Real-model solve | `python3 nxp_agent.py --model vertex --deep` |
| Gate sabotage suite | `python3 test_structural.py` → 8/8 |
| Runner contract | `python3 test_runner_mode.py` → 6/6 |
| 12 IP models vs RTL | `python3 test_ip_models.py` → 12/12 |

**Repo:** github.com/chelsea85/chip-convergence-iclad26 (fresh-clone verified)
Companion deck: **Engineering Learnings** (attached) — what building this taught us.

**Harikrishnan KC · Chip Convergence · greatharikrishnan@gmail.com**
