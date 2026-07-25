#!/usr/bin/env bash
# _metrics.sh — the single production metric-extraction helpers, sourced by
# measure.sh AND exercised directly by test_measure_area.sh (so the test covers
# the real code, not a copy). No side effects on source.

# extract_top_area <STAT> <FINAL> <TOP>  -> echoes the TOP-module area or "" (empty).
# Order: explicit "Chip area for top module" (STAT, hierarchical, full precision)
#        -> "Total Area" (FINAL, universal top total)
#        -> by-name "Chip area for module '\<TOP>'" (STAT)
#        -> empty (caller must fail closed; NEVER substitute a submodule value).
extract_top_area() {
    local STAT="$1" FINAL="$2" TOP="$3" a
    a=$(grep -m1 "Chip area for top module" "$STAT" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
    [ -z "$a" ] && a=$(grep -m1 "Total Area" "$FINAL" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
    if [ -z "$a" ] && [ -n "$TOP" ]; then
        a=$(grep -E "Chip area for module '\\\\?${TOP}'" "$STAT" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | tail -1)
    fi
    printf '%s' "$a"
}

# is_number <token> -> exit 0 iff token is a finite number. The char-class guard
# rejects "?", "", "inf", "nan" (they contain letters outside [0-9.eE+-]); the awk
# check confirms it is numerically parseable.
is_number() {
    case "$1" in
        ''|'?'|*[!0-9.eE+-]*) return 1 ;;
    esac
    awk -v v="$1" 'BEGIN{ exit !(v+0==v) }'
}

# is_pos_number <token> -> exit 0 iff finite AND strictly > 0
# (area/cells/ff/power must be positive; 0 or negative is a measurement failure).
is_pos_number() {
    is_number "$1" || return 1
    awk -v v="$1" 'BEGIN{ exit !(v>0) }'
}
