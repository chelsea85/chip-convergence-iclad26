# SLIDE DECK OUTLINES (draft for review with Hari) — ~15 slides each

Format assumption: PDF, dense-but-readable, one claim per slide, evidence bottom-right.
Both decks share slides 1 & 15 styling. Numbers: see SLIDE_MATERIAL.md.

═══════════════════════════════════════════════════════════════════
## DECK 1 — NXP: "The Library Is the Oracle"
Story: verification-first agent; every model failure becomes a typed signal;
perfect solve in 2 calls.

1. Title — Chip Convergence / NXP SoC Generation / one-line result:
   **"Diagram → verified SoC: 2 model calls, 42 seconds, cycle-identical to reference."**
2. Problem & scoring — diagram-only spec, YAML→rtl_gen_lib→stitch, hidden golden TB,
   compile-fail=0, tokens tiebreak. Agent IS the submission (runner contract).
3. Thesis — constraints enforced by TOOLING, not prompting (SLDB/SpecAssess evidence:
   models alter ports despite instructions; reset = #1 silent killer). Architecture diagram:
   pipeline with gates at every model boundary.
4. Correctness firewall — port_contract / reset_lint / structural_diff; sabotage-validated
   8/8; typed errors = repair prompts. (Show one real typed error.)
5. Verification depth — 30-check staged TB + KAT engine (replay TB, 79 checks) + STG
   differential. Venn: what each layer alone catches (FIFO-depth example: selfcheck 30/30
   PASS but KAT catches tx_full bit).
6. The oracle insight — hidden golden TB is built on the SAME library ⇒ model the library,
   bugs included (watchdog kick bug as proof). Reference models: all 20 ip_types, easy-8
   calibrated 0-mismatch, 12/12 lockstep (AES bit-exact).
7. Hidden-testcase path — KAT-model oracle needs NO golden; params plumb from inferred YAML
   (depth-8 demo: model(16) fails it, model(8) passes). Runner contract 6/6 vs mock endpoint.
8. LIVE: the 5-attempt debug arc (the money slide) — table: attempt → failure class →
   deterministic fix → result. 0% → perfect in ~1 day, no hand-tuning of the SoC.
9. LIVE: perfect solve — the actual run transcript screenshot: 8/8, contract clean attempt 1,
   30/30, 79/79, 79/79, STG MATCH 3662 cycles. 2 calls / 42 s.
10. Auto-extraction principle — required-params schema, demo exemplars, module-interface
    index, doc IRQ-map: ALL mined from provided materials at runtime ⇒ generalizes to
    medium/hard (nothing easy-tier hardcoded; gates activate by role).
11. Medium/hard readiness — 12 additional IP models validated; MissingParameter intel;
    known library quirks (aes encrypt-only; router no-mesh); structural gates role-activated.
12. Contest contributions — 3 library bugs found (show dma_engine non-compiling snippet +
    our auto-patch); reported to organizers.
13. Token economics — 2-call solve; bounded re-prompts (≤2/≤3); generator-error repair
    converges by prevention (schema in first prompt).
14. What's next by DAC — K-vote inference, best-of-M with KAT-score selection, live-testcase
    runbook (agents updatable through Jul 26).
15. Summary + repro — one command per claim (`--model stub` regressions green table),
    repo/contact.

═══════════════════════════════════════════════════════════════════
## DECK 2 — NVIDIA: "Verify Everything, Learn From Every Round"
Story: measured-not-vibed optimization; formal equivalence gates; the loop that
composes wins and learns from failures.

1. Title — **"LEC-proven ADP 0.787 on sha512 — and an agent that found the same trick
   itself."**
2. Problem & scoring — PPA after yosys, functional gates, tokens/calls tracked; hidden
   testcases at DAC via Vertex.
3. Thesis — every candidate: 5-layer verification incl. yosys LEC + differential sim;
   accept only measured strict improvement. (Alpha-RTL Table-4 context: published methods
   score 0 on async_fifo without this discipline.)
4. Architecture — controller loop diagram: propose (ladder) → verify (5 layers) → measure
   (Docker synth+STA, parallel APFS workspaces) → objective (Pareto/ADP) → pool (Thompson)
   → playbook (ACE) → reflector.
5. Headline result — sha512: WNS −97→+235 ps MET, ADP 0.787, LEC-proven. Waterfall chart
   baseline→exp2. (+ async_fifo differentiator note.)
6. Honest measurement — corrected aes baseline story (bug #1): our workspaces drop the
   duplicate all_modules.v; recorded baseline invalid by 235 ps. Rigor as a feature.
7. LIVE: first real-model rounds — timeline of Jul 12: handshake → empty-response mystery →
   63k thought tokens finding → fix → 3/3 parsed.
8. LIVE: the accept — arith-arch ADP 0.898 verified end-to-end; THEN restructure-select
   composes on top (0.884). Round ledger excerpt.
9. LIVE: the dedup moment — Gemini reinvents our hand-derived balanced-tree; fingerprint
   dedup rejects DUPLICATE, zero wasted synthesis. (Validates strategy + efficiency.)
10. Learning loop — playbook AVOID rules from measured no-ops (ABC absorbs local
    restructuring); reflector's live lesson (carry-save gate-fails). Before/after bullets.
11. Hidden-testcase readiness — discovery (fixtures MATCH, NVDLA/OT onboard zero-config);
    cold-start drill 6/6; the DESIGN_NAME-collision bug we caught (wrong-baseline scoring
    hazard) — found by drilling, not luck.
12. Submission artifact — --emit-best: drop-in repo-layout RTL + manifest (PPA, ADP,
    verification statement, calls/tokens). Show sha512 manifest.
13. Token economics — budgets/plateau/proxy pre-filter/dedup; measured round costs
    (~112k tokens incl. thinking; thinking-budget finding).
14. What's next by DAC — config sweep + model mixing on Jul-19 unlimited accounts;
    aes GF/tower-field + kmac Keccak-θ targets (ABC-resistant headroom); NVDLA baseline.
15. Summary + repro — regression table (13/13 iface, 6/6 cold-start, fixtures 3/3),
    run commands, repo/contact.

═══════════════════════════════════════════════════════════════════
## Open decisions for Hari
- Tooling: Marp/reveal.js (markdown→PDF, I generate directly) vs PowerPoint/Slides (Hari
  polishes)? Recommend Marp for speed + versionable in repo.
- Screenshots: re-run the NXP perfect solve + an NVIDIA round with clean terminal for
  captures (5 min, ~4 calls) or use saved transcripts?
- Slide 12/6 bug slides: confirm organizer bug email SENT before decks go out (timestamped
  credit).
- Team/title slide details (affiliation, email, repo URL once GitHub is set up).
