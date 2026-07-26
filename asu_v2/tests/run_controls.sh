#!/bin/bash
# Keyless Rev3 release tests: geometric safety controls (in the pinned KLayout
# image) + fail-closed CLI checks (host python). Exits nonzero on any failure.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
fail=0

echo "== geometric controls (KLayout $(docker run --rm --platform linux/amd64 asu-klayout:0.30.1 klayout -v 2>/dev/null | head -1)) =="
docker run --rm --platform linux/amd64 -v "$ROOT":"$ROOT" asu-klayout:0.30.1 \
  klayout -b -r "$ROOT/asu_v2/tests/test_controls.py" || fail=1

echo "== CLI fail-closed checks =="
python3 "$ROOT/asu_v2/agent/v2_run.py" --blocks '' --passes via-bar-safe --tag _cli_test >/dev/null 2>&1
[ $? -ne 0 ] && echo "[control] cli/empty-blocks nonzero            PASS" || { echo "[control] cli/empty-blocks nonzero            FAIL"; fail=1; }
python3 "$ROOT/asu_v2/agent/v2_run.py" --blocks Block1 --passes no-such-pass --tag _cli_test >/dev/null 2>&1
[ $? -ne 0 ] && echo "[control] cli/unknown-pass nonzero            PASS" || { echo "[control] cli/unknown-pass nonzero            FAIL"; fail=1; }

echo "== composer equality =="
python3 "$ROOT/asu_v2/tools/compose_official_agent.py" >/dev/null || fail=1
echo "[control] composer builder equality            $([ $fail -eq 0 ] && echo PASS || echo '(see above)')"

exit $fail
