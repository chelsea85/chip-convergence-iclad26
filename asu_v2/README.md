# ASU v2 — build on top of the shipped via-bar repair

**STATUS (2026-07-26 REV3, post 2nd Codex review): all Rev3 checklist items
done, awaiting re-review GO.** Stack = **via-bar-safe + track-shift + v1-patch**
(run `runs/rev3b`, driver exit 0 under `--require beat`): 142/35/35/102/444
violations = FVR **0.39–0.58** (v1 shipped 0.68–0.76). Layer-aware everywhere:
per-side two-sided bar guard; per-move track acceptance (same-layer + stationary
adjacent-via + riding-cut host contact sets; NO flat-projection path); immutable-
anchor partition gate (full SHA-256, fail-closed coverage, all 5 blocks equal);
driver credibility = anti-deletion area + partition gate (v1 2D count recorded as
info only). **12/12 permanent keyless controls** (`tests/run_controls.sh`) incl.
both Codex counterexamples + a drop control that caught a real guard bug.
Composer byte-identity ×5, read-only slim emission ×5, full-hash
RELEASE_MANIFEST. Packet: `../COPY_TO_CODEX_ASU_V2_REV3_2026-07-26.md`.
Remaining: Codex GO + P1-5 official runner (EXPRESS_MODE_KEY) + Hari's push.

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
