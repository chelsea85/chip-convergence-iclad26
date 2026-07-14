---
marp: true
theme: default
paginate: true
size: "16:9"
html: true
style: |
  section { font-size: 23px; padding: 48px 60px; }
  h1 { font-size: 38px; color: #1a3a6b; }
  h2 { font-size: 30px; color: #1a3a6b; }
  table { font-size: 19px; }
  code { font-size: 17px; }
  pre { font-size: 15px; line-height: 1.25; }
  section.lead h1 { font-size: 46px; }
  section.lead { text-align: center; }
  .ok { color: #1a7a2a; font-weight: 600; }
  .bad { color: #b03030; font-weight: 600; }
  footer { font-size: 14px; color: #888; }
footer: "Chip Convergence — ICLAD-DAC 2026 — Engineering Learnings (companion deck)"
---

<!-- _class: lead -->
<!-- _footer: "" -->

# Engineering Learnings

## What building a verified RTL-optimization agent taught us

Companion to the **NVIDIA problem** deck — the discoveries behind the design decisions.
Every lesson below was found by *running*, fixed same-day, and locked in with a regression.

Harikrishnan KC · Team **Chip Convergence** · greatharikrishnan@gmail.com

---

# 1 · Depth ≠ delay: don't guess where the timing is

We compared two ways to find timing-critical files on aes **before** spending model tokens:

- **Method A** — per-module logic-*depth* ranking (cheap, popular): pointed at the
  **GHASH datapath**
- **Method B** — hierarchy-preserved synth+STA (`FLATTEN=0`), worst path attributed to
  source files: pointed at **register integrity + control FSM files**

They **disagree**. Depth ignores cell drive/load and path composition — a campaign steered
by Method A would have optimized the wrong files entirely.

**Lesson:** attribution must come from real STA, not proxies. Our zero-token diagnosis is
built on Method B; Method A survives only as a pre-filter heuristic.

---

# 2 · Context is a correctness feature, not a token knob

Trimming aes prompts from 174k tokens was necessary — but our first cut (send *only* the
file being edited) collapsed reliability: **0/6 accepts, twice**. Two failure modes:

1. The model **invented sibling files from training memory** (it knows `sha512_w_mem`
   exists — it's instantiated in the file it sees) and returned edits to its imagined copy
2. Even single-file edits went functionally wrong without the neighbours' contracts
   (signature: testbench completes **zero** tests — the design hangs)

**Fixes, both mechanical:** a **strict scope filter** (edits outside the stage's file list are
dropped by tooling — the model cannot merge an imagined file), and **read-only grounding**
(the other critical files ride along, marked non-editable). Result: 0/6 → 3/6 functionally
correct, and the next two campaigns each landed verified wins.

---

# 3 · Your guardrails need verification too

We fenced aes's DPA-masked S-box (security posture). The fence checked for **presence** of
`SecSBoxImpl =` in returned files. But pristine `aes_core.v` *legitimately contains* that
parameter pass-through — so **every complete rewrite of aes_core tripped the fence**, and
our most promising stage was wiped without a single candidate evaluated.

Second, subtler bug: the fence ran **before** scope filtering — killing candidates for
out-of-scope S-box edits that the scope filter would have dropped harmlessly anyway.

**Fixes:** fence flags only lines that **differ from pristine** (whitespace-normalized), and
runs **after** scoping. Verified against four cases: pristine pass, benign rewrite pass,
value-change reject, S-box-file reject.

**Lesson:** an unverified guardrail is a silent results-destroyer. Test the police.

---

# 4 · "Improves everything" can mean "broke everything"

A candidate rewrite of one aes primitive measured: **perf ✓ area ✓ power ✓ — better on
every axis.** It had synthesized to **3,903 cells vs the parent's 74,234** — the edit broke
hierarchy elaboration and most of the design was pruned away. A fragment of aes trivially
"beats" aes.

It reached the **fifth** verification layer before dying (differential sim ERROR) — the TB
gate was legitimately skipped (pre-existing pristine-flow issue) and LEC was inconclusive
at that size.

**Fix:** a **netlist-collapse guard** — any candidate below 50% of its parent's cell count is
rejected as elaboration failure *before* any PPA comparison. Defense-in-depth means the
last layer should never be the only one standing.

---

# 5 · LLM API realities (plan for all of them)

| Reality | Symptom we hit | Mitigation now in the agent |
|---|---|---|
| Thinking models burn output caps | 63k thought-tokens, **0 output**, per call | explicit `max_output_tokens` + bounded `thinking_config`; thoughts are billed — account `total_token_count` |
| Sockets hang without error | campaign stalled **47 min**, no exception | per-attempt HTTP timeout (5 min) |
| Transient 429/503 | one failed call killed a k=6 round | resilient fan-out: a failed call drops **one** candidate; failed calls don't spend proposal turns |
| Quotas are request-shaped | free tier = **20 requests/day**, not tokens | request budgeting; key failover |
| Format compliance ~2/3 | plain fenced blocks instead of FILE headers | module-name fallback parser; raw responses archived |

---

# 6 · The contest toolkit is part of the problem

- **aes flow shipped broken**: the generated all-modules file duplicates every per-module
  source; yosys re-definition errors were **masked by the run script's success banner** —
  the recorded baseline was invalid. We re-derive every baseline from a pristine clone.
- **sv2v artifacts** break testbench compiles on kmac/prim — pristine fails identically, so
  we added **differential gating**: a layer that fails the same way on pristine can't indict
  a candidate; equivalence checks take over as the correctness gate.
- **ADP under-reporting**: our clock-period map lacked prim/aes → slack couldn't convert to
  delay → prim's real **0.605** printed as 1.0. Now periods parse from each IP's own SDC.

**Lesson:** measure the measurement system. Three toolkit bugs found; all reported in our logs.

---

# 7 · Validation moments worth keeping

- **The duplicate moment:** the model independently proposed our hand-derived balanced-tree
  rewrite; fingerprint dedup recognized it instantly (zero wasted synthesis). The playbook
  and the model converge on the same transformations — the approach generalizes.
- **The overtake:** two days later the agent's live `arith-arch` rewrite **beat** the
  hand-derived winner (ADP 0.727 vs 0.787, LEC-proven) — on a fresh pool, in one stage.
- **The flip:** prim, our one "no-improvement" IP, went to **ADP 0.605 in 6 calls** once
  diagnosis scoped its 147 library files down to the 1 file actually in the design.
- **Layer-5 catches:** dualsim caught a TB-passing functional bug (151 mismatches) and the
  netlist-collapse fragment — the expensive layers earn their cost.

---

# 8 · The meta-lesson

**Run everything before trusting it — including your own machinery.**

Every improvement in the main deck exists because a real run exposed a weakness the same
day: the fence bugs cost one campaign, the hung socket cost 47 minutes, naive context
trimming cost two campaigns, the missing SDC period nearly cost us our best result's
headline number.

The discipline that made it safe to move fast:
- **cold-start drill (6/6) re-run after every harness change**
- raw responses + full ledgers archived for every campaign (postmortems are cheap)
- honest statuses everywhere: SKIP-preexisting, INCONCLUSIVE, no-improvement — never
  silently upgraded to PASS

**Harikrishnan KC · Chip Convergence · greatharikrishnan@gmail.com**
