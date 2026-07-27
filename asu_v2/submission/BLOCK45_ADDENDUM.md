# Block4/Block5 addendum (2026-07-26, post-audit)

The organizers released the two previously-missing blocks on **2026-07-25**
(contest repo commit `11643cd "Add missing ASU block benchmarks"`) — after the
v1 submission and after the Rev3 review evidence was frozen. The Rev3
`RELEASE_MANIFEST.json` therefore remains the audited FIVE-block record; this
addendum extends coverage to all seven with the same instruments.

The rev3p15 official-runner rehearsal (agent phase, no --case filter) had
already processed all seven available blocks; Block4/5 outputs were scored
afterwards with the official evaluator in the pinned KLayout 0.30.1 image,
plus baselines (original scripts through the same evaluator) and the
layer-aware electrical comparison:

| Block | baseline | Rev3 | official FVR | valid | conn | electrical partition |
|---|---|---|---|---|---|---|
| Block4 | 189 | **55** | **0.374** | ✓ | ✓ | equal (170 comps, 568 anchors, 0 uncovered) |
| Block5 | 87  | **33** | **0.485** | ✓ | ✓ | equal (58 comps, 175 anchors, 0 uncovered) |

These are **blind** results: the agent was frozen (hash in RELEASE_MANIFEST)
before these blocks existed locally, and no code or parameter changed. For
comparison, the v1 agent scored 0.6939 / 0.7941 on the same blocks (Jul 25
run recorded in the talk deck).

All-seven Rev3 FVRs: 0.582 / 0.515 / 0.393 / 0.374 / 0.485 / 0.413 / 0.580
(mean 0.477). Evidence: `Block4/`, `Block5/`, `evidence/p15_Block{4,5}_factors.json`,
`evidence/base_Block{4,5}_factors.json`, `evidence/laconn_compare_Block{4,5}.json`.
