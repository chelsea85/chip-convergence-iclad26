#!/usr/bin/env bash
# Regression for the PRODUCTION metric helpers in _metrics.sh (sourced, not copied),
# guarding the P0-A hierarchical-area bug and the fail-closed metric validators.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/_metrics.sh"          # the real production functions under test
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok(){ if [ "$2" = "$3" ]; then echo "[PASS] $1"; pass=$((pass+1)); else echo "[FAIL] $1: got '$2' want '$3'"; fail=$((fail+1)); fi; }
okrc(){ # name  actual_rc  want_rc
  if [ "$2" = "$3" ]; then echo "[PASS] $1"; pass=$((pass+1)); else echo "[FAIL] $1: rc=$2 want $3"; fail=$((fail+1)); fi; }

# ── extract_top_area ──────────────────────────────────────────────────────────
cat > "$TMP/h_stat.txt" <<'EOF'
   Chip area for module '\NV_NVDLA_SDP_brdma': 0.758160
   Chip area for module '\NV_NVDLA_SDP_RDMA_reg': 412.307820
   Chip area for top module '\NV_nvdla': 78346.606860
EOF
echo "Total Area:              78346.607 (liberty units)" > "$TMP/h_final.txt"
ok "hierarchical -> TOP not first submodule" "$(extract_top_area "$TMP/h_stat.txt" "$TMP/h_final.txt" NV_nvdla)" "78346.606860"

echo "   Chip area for module '\\sha512': 3903.649200" > "$TMP/f_stat.txt"
echo "Total Area:              3903.649 (liberty units)" > "$TMP/f_final.txt"
ok "flat -> Total Area top total" "$(extract_top_area "$TMP/f_stat.txt" "$TMP/f_final.txt" sha512)" "3903.649"

printf "   Chip area for module '\\\\prim_ascon_duplex': 757.474740\n   Chip area for module '\\\\ascon': 1789.767900\n" > "$TMP/o_stat.txt"
: > "$TMP/o_final.txt"
ok "opentitan by-name -> named top over submodule" "$(extract_top_area "$TMP/o_stat.txt" "$TMP/o_final.txt" ascon)" "1789.767900"

: > "$TMP/e.txt"
ok "no metric -> EMPTY (fail closed)" "$(extract_top_area "$TMP/e.txt" "$TMP/e.txt" foo)" ""

# ── is_pos_number (area/cells/ff/power) ───────────────────────────────────────
is_pos_number "78346.60686"; okrc "is_pos_number accepts 78346.60686" "$?" "0"
is_pos_number "1.04e-02";    okrc "is_pos_number accepts 1.04e-02"    "$?" "0"
is_pos_number "?";           okrc "is_pos_number rejects ?"           "$?" "1"
is_pos_number "";            okrc "is_pos_number rejects empty"       "$?" "1"
is_pos_number "0";           okrc "is_pos_number rejects 0"           "$?" "1"
is_pos_number "-5.0";        okrc "is_pos_number rejects negative"    "$?" "1"
is_pos_number "inf";         okrc "is_pos_number rejects inf"         "$?" "1"
is_pos_number "nan";         okrc "is_pos_number rejects nan"         "$?" "1"

# ── is_number (setup/hold, may be <= 0) ───────────────────────────────────────
is_number "-5788.40"; okrc "is_number accepts -5788.40" "$?" "0"
is_number "0.00";     okrc "is_number accepts 0.00"     "$?" "0"
is_number "?";        okrc "is_number rejects ?"        "$?" "1"
is_number "inf";      okrc "is_number rejects inf"      "$?" "1"

echo "test_measure_area: $pass/$((pass+fail)) PASS"
[ "$fail" -eq 0 ]
