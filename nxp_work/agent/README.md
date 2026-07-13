# Chip Convergence — NXP SoC-Generation Agent

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

## Run — contest runner contract (AGENT_GUIDE.md)

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
[5] STG-DIFF: MATCH — 3662 cycles, 0 differing
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
- Token discipline: perfect easy-tier solve measured at 2 calls / 42 s (2026-07-12).
