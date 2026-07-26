#!/bin/bash
# Refresh the submission repo from the working directory. Re-runnable.
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DST="$(cd "$(dirname "$0")" && pwd)"

# NVIDIA track
mkdir -p "$DST/nvidia_work/agent"
cp -R "$SRC/nvidia_work/agent/ppa" "$DST/nvidia_work/agent/"
cp "$SRC/nvidia_work/agent"/{nvidia_agent.py,playbook.json,README.md} "$DST/nvidia_work/agent/"
# Ship the WHOLE test battery, not a hardcoded subset. The earlier fixed list
# (4 of 15 suites) silently omitted the suites that are the merge evidence for
# the contract/buildout code -- test_contract, test_nvdla_buildout,
# test_migration3, test_timing_rungs, test_cone_templates -- so a fresh clone
# carried the machinery but could not reproduce its verification.
cp "$SRC/nvidia_work/agent"/test_*.py "$DST/nvidia_work/agent/"
mkdir -p "$DST/nvidia_work/agent/ledger"
cp "$SRC/nvidia_work/agent/ledger"/*.json "$DST/nvidia_work/agent/ledger/" 2>/dev/null || true
cp "$SRC/nvidia_work/agent/ledger"/*.jsonl "$DST/nvidia_work/agent/ledger/" 2>/dev/null || true
cp -R "$SRC/nvidia_work/agent/ledger/raw" "$DST/nvidia_work/agent/ledger/" 2>/dev/null || true
cp -R "$SRC/nvidia_work/agent/variants" "$DST/nvidia_work/agent/" 2>/dev/null || true
for d in exp1_graycomb exp2_sha512_balanced exp3_sha512_wsched exp4_ascon_muxfold submission; do
  # rm before cp: cp -R MERGES (never deletes), which silently kept stale/renamed
  # artifact files in the mirror (2026-07-15 sha512 canonical-dir incident). Mirror
  # these trees as clean copies so a deletion in SRC propagates.
  [ -d "$SRC/nvidia_work/$d" ] && { rm -rf "$DST/nvidia_work/$d"; cp -R "$SRC/nvidia_work/$d" "$DST/nvidia_work/"; }
done
cp "$SRC/nvidia_work/AGENT_UPGRADE_SPEC.md" "$SRC/nvidia_work/OPTIMIZATION_CATALOG.md" "$DST/nvidia_work/" 2>/dev/null || true
cp "$SRC/NVIDIA_DAILY_RUN_LOG.md" "$DST/nvidia_work/"
cp -R "$SRC/nvidia_work/harness" "$DST/nvidia_work/"   # TB gate + measure scripts (fresh-clone fix 2026-07-14)

# NXP track
mkdir -p "$DST/nxp_work"
for d in agent tb specs rtl; do cp -R "$SRC/nxp_work/$d" "$DST/nxp_work/"; done
cp "$SRC/nxp_work/AGENT_UPGRADE_SPEC.md" "$DST/nxp_work/"
cp "$SRC/NXP_DAILY_RUN_LOG.md" "$DST/nxp_work/"


# ASU track (block-repair agent)
mkdir -p "$DST/asu_work/agent" "$DST/asu_work/docker"
cp "$SRC/asu_work/agent"/*.py "$SRC/asu_work/agent"/*.json "$SRC/asu_work/agent/README.md" "$DST/asu_work/agent/" 2>/dev/null || true
cp "$SRC/asu_work/docker/Dockerfile" "$DST/asu_work/docker/"
cp "$SRC/ASU_DAILY_RUN_LOG.md" "$DST/asu_work/"
# clean mirror, but validate the source exists FIRST so a missing/misnamed source
# can never delete the destination and silently ship nothing (do NOT suppress the
# copy failure for these required submission trees).
for d in submission official_submission; do
  if [ -d "$SRC/asu_work/$d" ]; then
    rm -rf "$DST/asu_work/$d"; cp -R "$SRC/asu_work/$d" "$DST/asu_work/"
  else
    echo "sync ERROR: required source asu_work/$d missing" >&2; exit 1
  fi
done
cp -R "$SRC/asu_work/baselines" "$DST/asu_work/" 2>/dev/null || true
cp "$SRC/asu_work/ASU_IMPROVEMENT_PLAN.md" "$SRC/asu_work/ASU_PHASE0_FINDINGS.md" "$DST/asu_work/" 2>/dev/null || true

cp "$SRC/PROJECT_SUMMARY.md" "$DST/" 2>/dev/null || true

# Docs
mkdir -p "$DST/docs"
for f in SLIDE_MATERIAL.md SLIDES_OUTLINE.md DAC_DAY_RUNBOOK.md GEMINI_SETUP.md RESEARCH_NOTES.md; do
  cp "$SRC/$f" "$DST/docs/"
done

# prune caches/outputs
find "$DST" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
find "$DST/nxp_work" -name agent_out -type d -exec rm -rf {} + 2>/dev/null || true
echo "synced from $SRC"

# Slides
mkdir -p "$DST/docs/slides"
cp "$SRC/slides"/*.md "$SRC/slides"/*.pdf "$SRC/slides"/build.sh "$DST/docs/slides/" 2>/dev/null || true

# ── ASU v2 (Rev3 resubmission package, 2026-07-26) ──────────────────────────
# The organizers' entry point asu_work/official_submission/agent.py is the
# GENERATED Rev3 agent; asu_v2/ carries its sources, tests, and evidence.
for d in agent tools tests results submission official_submission; do
  if [ -d "$SRC/asu_v2/$d" ]; then
    rm -rf "$DST/asu_v2/$d"; mkdir -p "$DST/asu_v2"; cp -R "$SRC/asu_v2/$d" "$DST/asu_v2/"
  else
    echo "sync ERROR: required source asu_v2/$d missing" >&2; exit 1
  fi
done
cp "$SRC/asu_v2/README.md" "$DST/asu_v2/"
cp "$SRC/asu_v2/run_docker.sh" "$DST/asu_v2/"
mkdir -p "$DST/asu_v2/reviews"
cp "$SRC"/ASU_V2_*CODEX_REVIEW*.md "$SRC"/COPY_TO_CODEX_ASU_V2_*.md "$DST/asu_v2/reviews/"
# Rev3 agent replaces the v1 agent at the documented organizer entry point
cp "$SRC/asu_v2/official_submission/agent.py" "$DST/asu_work/official_submission/agent.py"
