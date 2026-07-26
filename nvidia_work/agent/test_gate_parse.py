#!/usr/bin/env python3.12
"""Regression for ppa.gate.parse_test_results.

Origin (2026-07-25): the NVDLA release packet sat at 5/6 with
`gate_positive = FAIL` for a run the trace runner itself reported as
`rc=0 ... Done: 1 passed, 0 failed`. Root cause was in the PARSER, not the
design:

  1. `_RE_SUMMARY` required a comma immediately after PASS ("3 PASS, 1 FAIL"),
     so the NVDLA runner's "1 passed, 0 failed" never matched and the
     authoritative summary was discarded.
  2. The fallback then counted the word "failed" inside the runner's banner
     `TEST_TIMEOUT_SEC=4500 (per test; exceeded => failed)` as a real failure.
  3. ...and counted PASS twice (the `[PASS]` marker plus "passed" in the
     summary line).

The tests below lock in the fix AND — more importantly — lock in that the fix
cannot manufacture a false PASS. A parser that under-reports failures is far
more dangerous than one that over-reports them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ppa.gate import parse_test_results          # noqa: E402

PASSED = FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"[PASS] {name}")
    else:
        FAILED += 1
        print(f"[FAIL] {name} {detail}")


# ── the exact shape of the NVDLA trace runner's output ──────────────────────
NVDLA_PASS = """\
TEST_PREFIXES=pdp_1x3x8_8x8_ave_int8_0 (name must start with one of these)
EXCLUDE_TESTS: 4 test(s) excluded
TEST_TIMEOUT_SEC=4500 (per test; exceeded => failed)
========== TEST: pdp_1x3x8_8x8_ave_int8_0 ==========
done at 17446 ticks
*** PASS
[PASS] pdp_1x3x8_8x8_ave_int8_0
TEST                      RESULT    DETAIL
------------------------------------------
pdp_1x3x8_8x8_ave_int8_0  PASS

Done: 1 passed, 0 failed
      PROJECT=nv_small  skipped=0
"""

NVDLA_REALFAIL = NVDLA_PASS.replace(
    "*** PASS\n[PASS] pdp_1x3x8_8x8_ave_int8_0",
    "*** FAIL\n[FAIL] pdp_1x3x8_8x8_ave_int8_0").replace(
    "pdp_1x3x8_8x8_ave_int8_0  PASS", "pdp_1x3x8_8x8_ave_int8_0  FAIL").replace(
    "Done: 1 passed, 0 failed", "Done: 0 passed, 1 failed")

# ── 1. the original defect ──────────────────────────────────────────────────
tp, tf, note = parse_test_results(NVDLA_PASS)
check("NVDLA all-pass parses as (1,0)", (tp, tf) == (1, 0), f"got ({tp},{tf})")
check("NVDLA all-pass has no parse note", note == "", f"note={note!r}")

# ── 2. THE IMPORTANT ONE: a real failure must still fail ────────────────────
tp, tf, note = parse_test_results(NVDLA_REALFAIL)
check("real NVDLA failure still counted", tf >= 1, f"got ({tp},{tf}) note={note!r}")
check("real NVDLA failure not rescued to zero-pass-only", tp == 0,
      f"got tp={tp}")

# ── 3. the timeout banner alone must never invent a failure ─────────────────
BANNER_ONLY = ("TEST_TIMEOUT_SEC=4500 (per test; exceeded => failed)\n"
               "[PASS] some_test\nDone: 1 passed, 0 failed\n")
tp, tf, note = parse_test_results(BANNER_ONLY)
check("timeout banner does not invent a failure", tf == 0, f"got tf={tf}")

# ── 4. a genuine FAIL sharing the banner's presence is still caught ─────────
BANNER_PLUS_FAIL = ("TEST_TIMEOUT_SEC=4500 (per test; exceeded => failed)\n"
                    "[FAIL] some_test\nDone: 0 passed, 1 failed\n")
tp, tf, note = parse_test_results(BANNER_PLUS_FAIL)
check("banner present AND real fail -> failure reported", tf >= 1,
      f"got ({tp},{tf})")

# ── 5. legacy "N PASS, M FAIL" summaries must be unchanged ──────────────────
LEGACY_PASS = "running tb\n24 PASS, 0 FAIL\n"
tp, tf, note = parse_test_results(LEGACY_PASS)
check("legacy '24 PASS, 0 FAIL' still (24,0)", (tp, tf) == (24, 0),
      f"got ({tp},{tf})")
LEGACY_FAIL = "running tb\n20 PASS, 4 FAIL\n"
tp, tf, note = parse_test_results(LEGACY_FAIL)
check("legacy '20 PASS, 4 FAIL' still (20,4)", (tp, tf) == (20, 4),
      f"got ({tp},{tf})")

# ── 6. the contradiction guard must survive ─────────────────────────────────
CONTRADICT = "[FAIL] something_broke\n5 PASS, 0 FAIL\n"
tp, tf, note = parse_test_results(CONTRADICT)
check("summary-says-pass + FAIL marker -> flagged", tf > 0 and note != "",
      f"got ({tp},{tf}) note={note!r}")

# ── 7. contradictory summaries still refuse ────────────────────────────────
TWO_SUMS = "3 PASS, 0 FAIL\n1 passed, 2 failed\n"
tp, tf, note = parse_test_results(TWO_SUMS)
check("contradictory summaries -> (0,0)+note", (tp, tf) == (0, 0) and note,
      f"got ({tp},{tf}) note={note!r}")

# ── 8. zero-count text still not a failure (2026-07-23 OpenTitan behavior) ──
ZERO = "Failed: 0\n[PASS] t1\n"
tp, tf, note = parse_test_results(ZERO)
check("'Failed: 0' is not a failure", tf == 0, f"got tf={tf}")

# ── 9. the real archived log parses correctly ──────────────────────────────
ARCHIVE = (Path(__file__).resolve().parents[2] / "nvdla_release_evidence" /
           "gate_parser_falsefail_2026-07-25" /
           "release_nvdla_0724_144931_03_positive_phases_2__raw_log.log")
if ARCHIVE.exists():
    tp, tf, note = parse_test_results(ARCHIVE.read_text())
    check("archived NVDLA positive log parses (1,0)", (tp, tf) == (1, 0),
          f"got ({tp},{tf}) note={note!r}")
else:
    print(f"[SKIP] archived log not present at {ARCHIVE}")

print(f"\ntest_gate_parse: {PASSED}/{PASSED + FAILED} PASS")
sys.exit(1 if FAILED else 0)
