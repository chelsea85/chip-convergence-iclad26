#!/bin/bash
# Refresh the submission repo from the working directory. Re-runnable.
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DST="$(cd "$(dirname "$0")" && pwd)"

# NVIDIA track
mkdir -p "$DST/nvidia_work/agent"
cp -R "$SRC/nvidia_work/agent/ppa" "$DST/nvidia_work/agent/"
cp "$SRC/nvidia_work/agent"/{nvidia_agent.py,playbook.json,README.md,test_cold_start.py,test_model_iface.py} "$DST/nvidia_work/agent/"
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
rm -rf "$DST/asu_work/submission" "$DST/asu_work/official_submission"   # clean mirror (see NVIDIA note)
cp -R "$SRC/asu_work/submission" "$DST/asu_work/" 2>/dev/null || true
cp -R "$SRC/asu_work/official_submission" "$DST/asu_work/" 2>/dev/null || true
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
cp "$SRC/slides"/*.md "$SRC/slides"/*.pdf "$DST/docs/slides/" 2>/dev/null || true
