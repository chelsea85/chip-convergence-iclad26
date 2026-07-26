#!/bin/bash
# ASU v2 — run the v2 driver inside the version-exact KLayout 0.30.1 container.
# The repo is mounted at its HOST path (all absolute paths resolve unchanged);
# asu_work/ is overlay-mounted READ-ONLY as a hard no-regression guarantee.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
docker run --rm --platform linux/amd64 \
  -v "$ROOT":"$ROOT" \
  -v "$ROOT/asu_work":"$ROOT/asu_work":ro \
  asu-klayout:0.30.1 \
  python3 "$ROOT/asu_v2/agent/v2_run.py" "$@"
