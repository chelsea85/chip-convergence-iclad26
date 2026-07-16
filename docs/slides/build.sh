#!/usr/bin/env bash
# Rebuild all deck PDFs from the .md sources.
#
# IMPORTANT: --html is REQUIRED. The "What we do — one picture" slides use inline
# <svg> diagrams; without --html, marp-cli escapes them and the slide shows raw
# SVG markup instead of the diagram (regression seen 2026-07-15). The frontmatter
# `html: true` alone is NOT enough for marp-cli — the CLI flag must be passed.
set -e
cd "$(dirname "$0")"
# macOS system Chrome by default; override CHROME_PATH for other platforms.
export CHROME_PATH="${CHROME_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
for d in asu_deck asu_learnings nvidia_deck nvidia_learnings nxp_deck nxp_learnings; do
  npx --yes @marp-team/marp-cli@latest --html "$d.md" --pdf --allow-local-files -o "$d.pdf"
  echo "built $d.pdf"
done
echo "all decks rebuilt (with --html)"
