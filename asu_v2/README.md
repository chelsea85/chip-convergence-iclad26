# ASU v2 — build on top of the shipped via-bar repair

**STATUS (FINAL, 2026-07-26): RELEASED & INDEPENDENTLY REPRODUCED.** Codex Rev3 review =
ACCEPTED/GO; P1-5 official-runner rehearsal PASSED (zero model calls); resubmission pushed;
a cold public-clone reproduction re-executed everything green. **All SEVEN blocks** (organizers
added Block4/5 on 2026-07-25): FVR **0.374–0.582**, totals 142/35/35/55/33/102/444, all valid +
connectivity-preserved + layer-aware electrical partition equal. Blocks 4/5 were scored BLIND by
the hash-frozen agent and are its two best results. Release evidence: `submission/`
(RELEASE_INDEX.json = 7-block index → RELEASE_MANIFEST.json [audited 5-block record] +
Block4/5 manifests + BLOCK45_ADDENDUM.md + P15 addendum [historical 5-block rehearsal]).
Review trail: `reviews/` (3 rounds + full-repro review). Earlier text in this file describing
in-progress status is superseded by this block.

Goal: improve on the submitted ASU result (FVR 0.68–0.76, all 5 public blocks)
and **resubmit if better**. `asu_work/` is the submitted artifact and is never
modified — this folder holds all new work.

## Isolation contract (no-regression guarantees)

1. **Import, don't copy.** The proven v1 modules (`asu_work/agent/verify.py`,
   `repairs.py`, `asu_agent.py`) are imported read-only so
   "verify == official scorer" keeps a single source of truth.
2. **Frozen-hash guard.** Every run asserts the SHA-256 hashes recorded at
   submission time (`asu_work/baselines/baseline_table.json`) for the rule
   deck, evaluator, and block scripts. Drift aborts the run.
3. **Read-only mount.** `run_docker.sh` overlay-mounts `asu_work/` read-only in
   the container.
4. **Parity gate.** Step 0: the v2 driver with only the imported `via_bar_pass`
   must reproduce the shipped totals exactly (178/52/68/167/522, eligible,
   credible) before any new pass is enabled.
5. **Keep-best floor = shipped result.** A v2 candidate counts as a win only if
   eligible + rendered-connectivity credible + strictly better than the
   shipped FVR for that block. Worst case = resubmit what already shipped.

## Layout

```
agent/     v2 driver + NEW repair passes only (v1 code stays in asu_work/)
runs/      per-run outputs (runs/<tag>/summary.json + per-block workdirs)
results/   residual tables + per-phase findings
```

## Usage

```bash
# parity gate (reproduces the shipped v1 artifact exactly)
./run_docker.sh --tag parity --passes via-bar --require parity
# Rev3 release stack (layer-aware guards + full-anchor partition gate)
./run_docker.sh --tag rel --passes via-bar-safe,track-shift,v1-patch --require beat
# keyless safety controls (geometric negative controls + CLI fail-closed)
tests/run_controls.sh
# regenerate + verify the official agent
python3 tools/compose_official_agent.py --check-against runs/<tag>
```

## Plan

* Phase 0 — residual characterization from the parity run (per-rule table).
* Phase 1 — V0/M1 per-site via fix (dominant residual class).
* Phase 2 — per-edge grid snap, batch-apply + bisect acceptance.
* Phase 3 — enclosure/spacing cleanup + runner-contract hardening → resubmit.
