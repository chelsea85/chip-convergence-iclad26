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

out=$(cd "$gdir" && eval "$gcmd" 2>&1) || true
clean=$(echo "$out" | sed -E 's/\x1b\[[0-9;]*m//g')   # strip ANSI colors

# 1) Preferred: a summary line "N PASS, M FAIL" (SVUT / many TBs).
summary=$(echo "$clean" | grep -oiE '[0-9]+ +PASS, *[0-9]+ +FAIL' | tail -1)
if [ -n "$summary" ]; then
    np=$(echo "$summary" | grep -oiE '[0-9]+ +PASS' | grep -oE '[0-9]+')
    nf=$(echo "$summary" | grep -oiE '[0-9]+ +FAIL' | grep -oE '[0-9]+')
    if [ "$nf" = "0" ] && [ "${np:-0}" -gt 0 ]; then echo "$IP GATE: PASS"; else echo "$IP GATE: FAIL ($summary)"; fi
    exit 0
fi

# 2) Explicit all-pass banners.
if echo "$clean" | grep -qiE 'ALL TESTS PASSED|TEST PASSED|SIMULATION PASSED'; then
    echo "$IP GATE: PASS"; exit 0
fi

# 3) Fallback: per-test markers, excluding any summary/total lines.
body=$(echo "$clean" | grep -viE 'TOTAL|SUMMARY')
nf=$(echo "$body" | grep -ciE '\[FAIL\]|::.*FAIL|\bFAILED\b')
np=$(echo "$body" | grep -ciE '\[PASS\]|::.*PASS|\bPASSED\b')
if [ "$nf" -eq 0 ] && [ "$np" -gt 0 ]; then
    echo "$IP GATE: PASS"
else
    echo "$IP GATE: FAIL (pass=$np fail=$nf)"; echo "$clean" | grep -iE 'TOTAL|FAIL' | tail -3
fi
