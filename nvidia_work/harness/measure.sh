#!/usr/bin/env bash
# measure.sh — synthesize one NVIDIA IP (Yosys) + STA (OpenSTA) and print a one-line PPA summary.
# Runs INSIDE the iclad-dev:v1 container, CWD = NVIDIA repo root (mounted at /workspace).
#
#   ./measure.sh <syn_path> <label> [VT] [CORNER] [ABC_AREA] [SKIP_SV2V] [TOP]
# e.g.
#   ./measure.sh sha512/yosys_syn sha512-base RVT TT 0 0
#   ./measure.sh opentitan/hw/ip/aes/yosys_syn aes-base RVT TT 0 1 aes
#   ./measure.sh opentitan/hw/ip/prim/yosys_syn prim-base RVT TT 0 1 prim_crc32
#
# Output: label | VT/C/ABC | area cells ff | setup hold (+TIMING-MET flag) | power
set -uo pipefail
SYN=$1; LABEL=${2:-run}; VT=${3:-RVT}; CORNER=${4:-TT}; ABC=${5:-0}; SKIP=${6:-0}; TOP=${7:-}

LOG=/tmp/syn_$(echo "$LABEL" | tr -c 'A-Za-z0-9' _).log
# DESIGN_NAME= (empty) is safe: every env.sh/syn.tcl defaults via ${DESIGN_NAME:-...}
run_flow() {
    SKIP_SV2V=$SKIP VT=$VT CORNER=$CORNER ABC_AREA=$ABC DESIGN_NAME=$TOP \
        bash -c "cd $SYN && ./run_syn.sh $1" >"$LOG" 2>&1
}
# CLI differs per IP: most take `all`; multi-design dirs (prim) take no arg
if ! run_flow all; then
    if grep -q "Unknown command: all" "$LOG"; then
        run_flow "" || { echo "$LABEL | SYNTH/STA FAILED -> $LOG"; tail -4 "$LOG"; exit 1; }
    else
        echo "$LABEL | SYNTH/STA FAILED -> $LOG"; tail -4 "$LOG"; exit 1
    fi
fi

R="$SYN/reports"; S="$SYN/syn_results"
# Report filenames differ: async_fifo/sha512 use synth_stat.txt; OpenTitan uses
# <design>_synth_stat.txt; multi-design dirs (prim) prefix EVERY report — prefer
# the TOP-prefixed file when given, else unprefixed, else first glob match.
pick() {  # pick <dir> <suffix>
    if [ -n "$TOP" ] && [ -f "$1/${TOP}_$2" ]; then echo "$1/${TOP}_$2";
    elif [ -f "$1/$2" ]; then echo "$1/$2";
    else ls "$1"/*"$2" 2>/dev/null | head -1; fi
}
STAT=$(pick "$S" synth_stat.txt)
FINAL=$(pick "$S" synth_final_report.txt)
STA_T=$(pick "$R" sta_timing_report.txt)
STA_P=$(pick "$R" sta_power_report.txt)
area=$(grep -m1 "Chip area for module" "$STAT" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
cells=$(grep -m1 "Total Cell Count" "$FINAL" 2>/dev/null | grep -oE '[0-9]+' | head -1)
ff=$(grep -m1 "Flip-Flops" "$FINAL" 2>/dev/null | grep -oE '[0-9]+' | head -1)
sslk=$(grep -m1 "Worst Slack" "$STA_T" 2>/dev/null | grep -oE '[-0-9]+\.[0-9]+' | head -1)
hslk=$(grep -m1 "Worst Slack" "$STA_T" 2>/dev/null | grep -oE '[-0-9]+\.[0-9]+' | sed -n '2p')
pwr=$(grep -m1 "^Total" "$STA_P" 2>/dev/null | grep -oE '[0-9]\.[0-9]+e-[0-9]+' | sed -n '4p')

met="MET"; case "$sslk" in -*) met="VIOLATED";; esac
printf "%-20s | VT=%-4s C=%-2s ABC=%s | area=%-10s cells=%-6s ff=%-5s | setup=%-9s hold=%-9s [%s] | pwr=%s\n" \
    "$LABEL" "$VT" "$CORNER" "$ABC" "${area:-?}" "${cells:-?}" "${ff:-?}" "${sslk:-?}ps" "${hslk:-?}ps" "$met" "${pwr:-?}W"
