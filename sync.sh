#!/bin/bash
# Refresh the submission repo from the working directory. Re-runnable.
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DST="$(cd "$(dirname "$0")" && pwd)"

# NVIDIA track
mkdir -p "$DST/nvidia_work/agent"
cp -R "$SRC/nvidia_work/agent/ppa" "$DST/nvidia_work/agent/"
cp "$SRC/nvidia_work/agent"/{playbook.json,README.md,test_cold_start.py,test_model_iface.py} "$DST/nvidia_work/agent/"
mkdir -p "$DST/nvidia_work/agent/ledger"
cp "$SRC/nvidia_work/agent/ledger"/*.json "$DST/nvidia_work/agent/ledger/" 2>/dev/null || true
cp "$SRC/nvidia_work/agent/ledger"/*.jsonl "$DST/nvidia_work/agent/ledger/" 2>/dev/null || true
cp -R "$SRC/nvidia_work/agent/ledger/raw" "$DST/nvidia_work/agent/ledger/" 2>/dev/null || true
cp -R "$SRC/nvidia_work/agent/variants" "$DST/nvidia_work/agent/" 2>/dev/null || true
for d in exp1_graycomb exp2_sha512_balanced exp3_sha512_wsched exp4_ascon_muxfold submission; do
  [ -d "$SRC/nvidia_work/$d" ] && cp -R "$SRC/nvidia_work/$d" "$DST/nvidia_work/"
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
