# Chip Convergence — NXP SoC-Generation Agent

> **2026-07-26 library sync:** the contest `rtl_gen_lib` was updated by the
> organizers on 2026-07-25 (commit `8c68299`): `tilelink_router` is now a
> 5-port XY design with NODE_X/NODE_Y parameters, and a new `apb_fabric6` IP
> was added. `ip_models.TlRouter` has been synchronized (12/12 lockstep
> restored). `apb_fabric6` has no reference model yet — a KNOWN coverage gap
> in the dev differential vocabulary only; the agent emits all IP RTL via the
> contest's own generator, so emitted RTL always tracks the current library.

Generates the `secure_periph_soc` from the architecture diagram: infers YAML specs per IP,
drives `rtl_gen_lib`, stitches the top, and gates everything through a deterministic
correctness firewall. Stdlib-only Python + iverilog (the guaranteed eval environment).

## Layout

```
agent/
  nxp_agent.py        the agent (runner-contract + dev modes)
  validators.py       port contract, YAML validator, reset lint, structural diff,
                      library-bug fixups
  kat_engine.py       KAT vector-replay engine (79 checks, dual oracle)
  ref_models.py       cycle-stepped reference models (easy-8, calibrated 0-mismatch)
  ip_models.py        reference models for the other 12 library ip_types
  stg_diff.py         dual-SoC random-stimulus differential
  mock_endpoint.py    contest model-service protocol mock (offline testing)
  kat/                vector program + golden expected + calibration
  test_*.py           regression suites (see below)
tb/tb_selfcheck.v     30-check staged self-test TB
specs/, rtl/          hand-derived reference (stub model answers; STG reference)
```

## Run — organizer path (contest runner)

Organizers drive the agent through the contest runner, which creates `info.json`,
starts a Vertex-backed model service, and invokes the agent:

```bash
# from the NXP problem dir (ICLAD26-NXP-Problems); needs EXPRESS_MODE_KEY exported
python3 runner/run_benchmark.py --problem easy \
    --agent <this_repo>/nxp_work/agent/nxp_agent.py --model <model_name> --run-id r1
#   -> 8 IP .v + secure_periph_soc.v in result/<run-id>/; GATE 30/30 + KAT 79/79 ×2
```

Note: the public NXP checkout omits `scripts/model_service.py` (organizer-supplied
Vertex wrapper). To run it yourself, either drop in a Vertex-backed `/generate`
service (the ICLAD26-ASU-Problems `scripts/model_service.py` is the same wrapper)
and pass `--model-endpoint http://127.0.0.1:<port>`, or use `--model stub` below.
Verified live 2026-07-15: `run_benchmark.py … --model gemini-3-flash-preview
--model-endpoint <live-vertex>` → 30/30 + KAT 79/79 ×2 in 2 model calls.

### Agent contract (what the runner invokes)

```bash
python3 nxp_agent.py <info_json_path> --model <model_name>
```

Reads all paths from info.json, sends every model call to its `model_endpoint`
(POST /generate, exponential backoff), writes all .v to `output_dir`, exit 0 iff RTL
delivered.

## Run — development

```bash
python3 nxp_agent.py --model stub           # offline, full pipeline, expect all green
python3 nxp_agent.py --model vertex --deep  # real Gemini (EXPRESS_MODE_KEY or
                                            # GEMINI_API_KEY) + STG differential
```

Expected (stub and, as of 2026-07-12, live vertex):
```
[3] wrote secure_periph_soc.v (contract clean, attempt 1)
[4] GATE: PASS — 30/30 PASS
[4b] KAT(golden): PASS — 79/79
[4b] KAT(model):  PASS — 79/79
[5] STG-DIFF: MATCH — 3662 cycles, 0 differing   (--deep / live runs only;
                                                  not printed by default stub)
```

## Regression suites

```bash
python3 test_structural.py    # structural-diff sabotage: 8/8
python3 test_runner_mode.py   # runner contract e2e vs mock endpoint: 6/6
python3 test_ip_models.py     # 12 IP models lockstep vs library RTL: 12/12
python3 kat_engine.py --gen-smoke --record --calibrate   # rebuild KAT assets
```

## Design notes (why it scores)

- Constraints enforced by tooling, not prompting: non-bypassable gates convert model
  mistakes into typed re-prompts (≤2 spec / ≤3 stitch); best-effort RTL always ships
  (partial score > compile-fail 0).
- The library is the oracle: required-param schema, demo exemplars, and module interfaces
  are auto-extracted from rtl_gen_lib at runtime; reference models mirror actual library
  behavior (bugs included) — the KAT model oracle works on unseen problems with no golden.
- Known library bugs auto-patched (dma_engine cfg_rdata wire/reg — does not compile
  otherwise); watchdog kick-no-reload behavior asserted as-is.
- Token discipline: 2 calls / 42 s, **perfect against our full verification stack** (30/30
  self-test + KAT 79/79 on both oracles + 3,662-cycle reference match), 2026-07-12. The organizer
  hidden testbench is not in the public checkout, so the official score is organizer-confirmed only.
