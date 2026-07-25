#!/usr/bin/env bash
# run_gate.sh — run an IP's functional gate (the correctness check the optimizer MUST keep passing).
# Runs INSIDE iclad-dev:v1, CWD = NVIDIA repo root. Looks the IP up in registry.tsv.
#
#   ./run_gate.sh <ip> [gate_dir gate_cmd]
# Prints: "<ip> GATE: PASS" or "<ip> GATE: FAIL" + the raw pass/fail tally.
# gate_dir/gate_cmd override the registry lookup (auto-discovered hidden IPs).
set -uo pipefail
IP=$1
if [ $# -ge 3 ]; then
    gdir=$2; gcmd=$3
else
    HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    row=$(grep -P "^${IP}\t" "$HERE/registry.tsv") || { echo "$IP: not in registry"; exit 2; }
    gdir=$(echo "$row" | cut -f3); gcmd=$(echo "$row" | cut -f4)
fi

out=$(cd "$gdir" && eval "$gcmd" 2>&1)
rc=$?
echo "$IP GATE-RC: $rc"
# FAIL-CLOSED (migration review SS4.9): a nonzero underlying command rc is a
# gate FAILURE regardless of any PASS text in the output. tmake IPs use the
# structural ppa/gate.py adapter instead of this script.
if [ "$rc" -ne 0 ]; then
    echo "$IP GATE: FAIL (underlying rc=$rc)"
    echo "$out" | tail -5
    exit "$rc"
fi
clean=$(echo "$out" | sed -E 's/\x1b\[[0-9;]*m//g')   # strip ANSI colors

# FAIL-CLOSED parser (corrective review SS4.8):
#   - ALL "N PASS, M FAIL" summaries must AGREE (contradiction => FAIL);
#   - any FAIL marker overrides any all-pass banner;
#   - a PASS banner with ZERO counted evidence (no summary, no per-test pass
#     markers) is NOT sufficient => FAIL (uncounted);
#   - functional failure exits NONZERO (not just underlying-command failure).
summaries=$(echo "$clean" | grep -oiE '[0-9]+ +PASS, *[0-9]+ +FAIL' | sort -u)
nsummaries=$(echo "$summaries" | grep -c . || true)
# FAIL evidence is scanned over the COMPLETE output with only zero-count and
# summary PATTERN text removed (never whole lines) - a line carrying both a
# summary and a real FAIL marker keeps its failure evidence (corrective2 SS4.6).
# Zero-count strip (2026-07-23): the OpenTitan Verilator TBs print a benign
# counter "Failed: 0" (aes/prim), which `\bFAILED\b` wrongly matched -> pristine
# gate FAIL. A zero count is definitionally NOT a failure, so stripping it can
# never mask a real one (mirrors the "N PASS, M FAIL" summary strip).
nofmt=$(echo "$clean" \
  | sed -E 's/[0-9]+ +PASS, *[0-9]+ +FAIL//Ig' \
  | sed -E 's/(fail(ed|ures)?|errors?)[[:space:]]*[:=]?[[:space:]]*0+\b//Ig' \
  | sed -E 's/\b0+[[:space:]]+(fail(ed|ures)?|errors?)\b//Ig')
nf_marks=$(echo "$nofmt" | grep -ciE '\[FAIL\]|::.*FAIL|\bFAILED\b')
body=$(echo "$clean" | grep -viE 'TOTAL|SUMMARY|ALL TESTS PASSED|TEST PASSED|SIMULATION PASSED')
np_marks=$(echo "$body" | grep -ciE '\[PASS\]|::.*PASS|\bPASSED\b')

if [ "$nsummaries" -gt 1 ]; then
    echo "$IP GATE: FAIL (contradictory summaries: $(echo $summaries))"; exit 3
fi
if [ "$nsummaries" -eq 1 ]; then
    np=$(echo "$summaries" | grep -oiE '[0-9]+ +PASS' | grep -oE '[0-9]+')
    nf=$(echo "$summaries" | grep -oiE '[0-9]+ +FAIL' | grep -oE '[0-9]+')
    if [ "$nf" != "0" ] || [ "${np:-0}" -eq 0 ]; then
        echo "$IP GATE: FAIL ($summaries)"; exit 3
    fi
    if [ "$nf_marks" -gt 0 ]; then
        echo "$IP GATE: FAIL (summary PASS but $nf_marks FAIL markers)"; exit 3
    fi
    echo "$IP GATE: PASS"; exit 0
fi
# banner path: a recognized SIMULATION-SUCCESS banner (single-verdict TBs) +
# rc 0 (already checked above) + ZERO failure markers is valid pass evidence.
# The OpenTitan Verilator TBs print only "Simulation passed!" — no per-test
# count — so a "require a positive count" rule over-REJECTED that real format
# (2026-07-23 release-control catch: pristine aes/prim/ascon gate wrongly
# FAILed). A failing sim prints "Simulation failed!" -> caught by nf_marks.
# gate_cmd is FIXED per-IP (not agent-injected), so an uncounted banner is not
# a production-reachable gaming vector under the agreed threat model; rc,
# fail-markers, and contradictory summaries still gate.
if echo "$clean" | grep -qiE 'ALL TESTS PASSED|TEST PASSED|SIMULATION PASSED|SIMULATION FINISHED'; then
    if [ "$nf_marks" -gt 0 ]; then
        echo "$IP GATE: FAIL (banner + $nf_marks FAIL markers)"; exit 3
    fi
    echo "$IP GATE: PASS"; exit 0
fi
if [ "$nf_marks" -eq 0 ] && [ "$np_marks" -gt 0 ]; then
    echo "$IP GATE: PASS"; exit 0
fi
echo "$IP GATE: FAIL (pass=$np_marks fail=$nf_marks)"
echo "$clean" | grep -iE 'TOTAL|FAIL' | tail -3
exit 3
