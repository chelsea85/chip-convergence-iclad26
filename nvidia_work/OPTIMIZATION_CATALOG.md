# NVIDIA RTL Optimization — Pattern Catalog & Learnings (transferable)

Reusable, measured knowledge for the PPA-optimization agent. Each pattern: what it does, when it
helps, risk, and measured effect. Feeds the agent's prompt library once Vertex/Gemini access lands.

---

## Ground rules (apply to every rewrite)
1. **Never break the functional gate.** Every candidate must keep `run_gate.sh <ip>` = PASS. This
   is a hard gate before any PPA is counted.
2. **Don't change the module's port list / latency-visible behavior** unless the TB tolerates it
   (most don't). Pipelining that adds latency usually breaks the TB → avoid unless verified.
3. **Measure, don't assume.** Always re-run `measure.sh`; PPA is non-obvious (see Lesson L1).
4. **Keep edits minimal & equivalence-preserving** where possible — easier to verify, easier to
   keep the gate green, fewer tokens to justify.

## Key lessons (measured)
- **L1 — FF count ≠ area (ASAP7).** Removing flip-flops can *increase* area if it adds
  combinational logic + buffering. (exp1: −8 FF but +0.86% area.) Optimize the metric that's
  scored, not a proxy.
- **L2 — Several IPs ship FAILING timing.** sha512 WNS −97 ps @1500 ps; aes WNS −1083 ps @100 ps
  (10 GHz, physically unmeetable for AES). → Strongly implies the metric is **relative improvement
  vs baseline** (shrink WNS / area / power), not absolute timing closure. (Confirm w/ organizers.)
- **L3 — Spend slack, don't waste it.** If a design already meets timing (async_fifo +22 ps),
  extra slack is only valuable if (a) metric rewards perf, or (b) you trade it for smaller/
  lower-power cells. Recovering area at still-positive slack is usually the better play.
- **L4 — Synthesis recipe is a lever** (`ABC_AREA`, `VT`, `CORNER`) — but suspect `env.sh`
  hard-sets these and clobbers CLI overrides. Verify the knob actually changes output before
  relying on it. (Pending organizer Q: are knobs in scope, or is eval recipe fixed?)
- **L5 — Critical path lives in the submodules.** Top files are mostly structural; PPA is decided
  inside the datapath modules (e.g., sha512 round adders, aes sbox/mixcolumns).

---

## Patterns

### P1 — Gray pointer de-registration (CDC counters)   [exp1, MEASURED]
- **Where:** async-FIFO / Gray-coded CDC pointers that register BOTH binary and gray.
- **Do:** register only the binary counter; derive gray combinationally `g=(b>>1)^b`. Equivalent
  because registered-gray == gray(registered-binary). CDC-safe (value stable between launch edges).
- **Effect (async_fifo):** −8 FF, **+13 ps setup slack (timing↑)**, **+0.86% area (slight loss)**,
  power flat. Gate 16/16.
- **Verdict:** timing win / area-neutral-to-slightly-worse. Use when timing-bound, not area-bound.

### P2 — Balanced adder-tree reassociation for datapaths   [exp2, MEASURED — ⭐ BIG WIN]
- **Where:** long left-associative multi-operand add chains on the critical path. SHA-512 round:
  `a_new = h+Σ1+Ch+K+W+Σ0+Maj` (7 operands) and `e_new = d+h+Σ1+Ch+K+W` (6) were written as a
  serial `t1=h+Σ1+Ch+K+W; a_new=t1+t2; e_new=d+t1` chain (depth ~6).
- **Do:** regroup into **balanced binary trees** (depth ~3), e.g.
  `a_new = ((h+Σ1)+(Ch+K)) + ((W+Σ0)+Maj)`. Modular (mod 2^64) addition is associative →
  **value-identical**, zero functional risk. Expose Σ0/Σ1/Ch/Maj as module wires so the trees can
  be written directly (bypassing the serial t1/t2).
- **Effect (sha512, MEASURED):** setup slack **−97.30 ps (VIOLATED) → +235.36 ps (MET)** = **+332.7
  ps**; area **3984.20 → 3960.29 (−0.6%)**; cells 29307 → 28955 (−352); FF & power unchanged.
  Gate **24/24 PASS**. → **Win on every axis** (timing, area) with no regression. Closes the
  timing violation with margin.
- **Verdict:** highest-value pattern so far. Apply wherever RTL has serial multi-operand `+` chains
  on the critical path. (Next level: explicit CSA / 3:2-compressor tree — see P2b.)

### P2b — Carry-save (CSA / 3:2 compressor) tree   [CANDIDATE — beyond P2]
- For even shorter paths than balanced CPAs: reduce N operands → 2 (sum+carry) with 3:2
  compressors (no carry propagation), one final CPA. Same value mod 2^N (top carry dropped).
  More complex/bug-prone to hand-write → ideal task for the LLM agent; gate catches errors.

### P3 — Constant folding / specialization for fixed params   [CANDIDATE]
- **Where:** generic-width logic instantiated at fixed sizes; constant K/H tables.
- **Do:** propagate constants, prune unreachable width/logic. (Yosys already does much of this;
  RTL-level help mainly when structure hides it.)

### P4 — Operator strength reduction / expression rewrite   [CANDIDATE]
- **Where:** comparators, mux trees, redundant recomputation (e.g., sha512 W-schedule recompute).
- **Do:** share common subexpressions, precompute, replace expensive compares with cheaper forms.

### P5 — Synthesis-recipe tuning (RTL-free)   [CANDIDATE — pending L4/organizer Q]
- **Do:** if knobs are in scope, sweep `ABC_AREA`/`VT` per IP to trade area↔speed. Zero functional
  risk (RTL untouched). Confirm `env.sh` isn't clobbering first.

---

## Per-IP optimization notes
- **sha512** ⭐ — failing timing (−97 ps). Target the round-compression adder path (P2). Best
  near-term ROI: turning a violated design into a met/closer one is a win under any metric.
- **aes** — failing timing (−1083 ps @10 GHz). Critical path likely sbox (canright) / mix-columns.
  P2/P4 on the datapath. Large (74k cells) → slower synth iterations.
- **async_fifo** — already lean & meets timing; limited headroom. Good for flow validation; not the
  place to chase big wins.
- **ascon / kmac / prim** — baselines pending; characterize critical path before optimizing.
- **nvdla** — large, blackbox RAM; treat as stretch.
