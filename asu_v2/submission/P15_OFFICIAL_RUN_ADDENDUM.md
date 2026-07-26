# P1-5 official-runner rehearsal — PASSED (2026-07-26, run `rev3p15`)

Release control required by `ASU_V2_REV3_CODEX_REVIEW_2026-07-26.md` §8.2/§9.
Target: the GENERATED official agent (`asu_v2/official_submission/agent.py`,
sha256 in `RELEASE_MANIFEST.json`), not the development driver.

## Procedure

1. `EXPRESS_MODE_KEY` exported from `.env` without printing.
2. Agent phase: `official_eval/run_official_eval.py --run-id rev3p15
   --submission-dir <abs>/asu_v2/official_submission --agent-entrypoint
   agent.py --model gemini-3.5-flash --skip-eval` — full Docker isolation
   (per-case network, model-service wrapper container, `--read-only` agent
   container from `iclad26-asu-official:latest`), all five blocks.
   Log: `asu_v2/runs/p15/official_agent_phase.log`.
3. Evaluator phase: the runner's own eval command
   (`python3 evaluator/evaluate_repair.py --case <B> --run-id rev3p15`)
   executed INSIDE the pinned `asu-klayout:0.30.1` image.
   **Documented deviation from §9.5 ("do not use --skip-eval"):** this host
   has NO KLayout binary and the evaluator hard-rejects any version other
   than 0.30.1, so the wrapper's host-side eval step cannot run natively
   anywhere but an organizer host. The identical command in the version-exact
   container is the same environment-equivalence used for the accepted v1
   rehearsal. Log: `asu_v2/runs/p15/official_eval_phase.log`.

## Acceptance conditions (review §8.2) — all met

1. **All five cases complete:** agent phase exit 0; evaluator exit 0.
2. **Valid + connectivity-eligible:** every factor report has
   `valid_repair=true` and `connectivity_preserved=true`
   (`factors/rev3p15/block/repair/Block*_factors.json`).
3. **Totals exactly 142 / 35 / 35 / 102 / 444**, with official FVRs matching
   the rev3b measurements to full precision:
   0.5819672131147541 / 0.5147058823529411 / 0.39325842696629215 /
   0.41295546558704455 / 0.5803921568627451
   (repair rates 0.4303 / 0.5147 / 0.6292 / 0.6032 / 0.4209).
4. **Emitted-script hashes equal the release manifest:** SHA-256 of all five
   `result/rev3p15/block/repair/Block*/Block*_repaired.py` == the
   `emitted_script_sha256` values in `RELEASE_MANIFEST.json`.
5. **No model-generation request occurred:** the wrapper usage ledger
   directory (`/tmp/iclad26_asu_official/rev3p15/usage/`) is EMPTY and the
   preserved wrapper/agent logs contain zero generation-request lines. Per
   the review's evidence nuance: the wrapper writes usage JSON only when a
   model request occurs and the read-only agent cannot write `/secure/usage`
   (the expected `usage write skipped ... OSError` line appears once per
   block) — the absent ledger is therefore consistent with, and here
   corroborated by the logs as, zero calls. This is stated as evidence
   posture, not as a positive ledger record.
6. **Submission directory contents:** `agent.py` only (generated,
   `compose_official_agent.py`, do-not-edit header).

## Verdict

All six conditions met → per the review's release condition, **Rev3 is GO for
resubmission**. The final push/email is the team decision.
