#!/usr/bin/env python3
"""ASU block-repair agent — OFFICIAL SUBMISSION entry point.

Contest runner contract (official_eval/run_official_eval.py):
    python3 agent.py <info_json> --model <model_name>
The agent container runs from `python:3.10-slim` (only `google-genai` + `shapely`
on top), `--read-only`, with NO KLayout binary on PATH. The organizer's evaluator
renders and scores the emitted script AFTERWARD, on the host, in KLayout 0.30.1.

DESIGN DECISION (why this agent does not render/DRC internally):
  Our development agent (asu_work/agent/asu_agent.py) measures every candidate
  with the official evaluator's render+DRC to keep-best. That REQUIRES KLayout at
  agent runtime, which the official image does not provide — there the dev agent
  can measure nothing and falls back to the untouched original (no-op FVR is the
  evaluator's fresh-DRC ratio, ~1.25-1.32 on the public blocks — NOT 1.0; see
  SAFETY below).

  The winning repair, however, is DETERMINISTIC and needs no measurement to APPLY:
  replace each flagged multi-cut via array with one continuous via BAR. We proved
  on all 5 public blocks (independently re-scored with the published evaluator)
  that `strip_write(original) + via_bar_snippet` yields FVR 0.68-0.76, eligible,
  connectivity-preserved. This agent emits exactly that artifact — byte-identical
  to asu_work/submission/Block*_repaired.py — using only the Python stdlib. The
  KLayout code in the appended snippet runs later, inside the organizer's
  evaluator, exactly as it does for the dev agent's kept candidate.

SAFETY (hidden cases) — stated precisely (per Codex review 2026-07-23):
  `_asu_bar_pair` only reshapes vias whose perpendicular dimension is smaller than
  the interacting metal's; a block with no such landing selects 0 bars and leaves
  the rendered geometry unchanged (the per-layer `flatten` still runs, so it is a
  geometric no-op, not a literal structural no-op). On a valid benchmark case
  whose original script renders and whose original connectivity matches its
  reference, emitting the original is an ELIGIBLE FALLBACK — eligibility requires
  render + DRC + connectivity_preserved, NOT improvement — but its numerical FVR
  is the evaluator's fresh-DRC total over the supplied reference-report total and
  is NOT assumed to be 1.0 (public no-op FVR is ~1.25-1.32). The transform was a
  net scoring WIN on all five public blocks; it is not a "cannot make anything
  worse" transform (manifests show some V4.AUX.1/V5.AUX.1 appear while the total
  falls). If the layout script does not look like a KLayout `pya` layout builder,
  we emit it untouched (a false-negative here is safe — original is emitted).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ── the proven via-bar repair, emitted as pya code appended to the original ──
# (Kept byte-identical to asu_work/agent/repairs.py so this agent reproduces the
#  committed, independently-scored Block*_repaired.py artifacts exactly.)
_VIA_BAR_HELPER = '''
# ===== ASU via-bar repair pass (2026-07-15) =====
# The seeded errors split each via-in-wide-metal landing into a multi-cut array;
# every min-via then fails the via-width-match rule (V.M.AUX.2/.3). Replace each
# flagged array with ONE continuous via BAR spanning the metal's length (keeping
# the min via thickness → NO lower-metal widening → no enclosure/spacing cascade).
# Upper routing layers only (V2/M3, V4/M5, V5/M6); V0/M1 is the device layer and
# must NOT be barred (it explodes enclosure/spacing + breaks connectivity).
def _asu_bar_pair(layout, via_ln, m_ln):
    top = layout.top_cell()
    vli = layout.layer(pya.LayerInfo(via_ln, 0))
    mli = layout.layer(pya.LayerInfo(m_ln, 0))
    V = pya.Region(top.begin_shapes_rec(vli))
    M = pya.Region(top.begin_shapes_rec(mli)); M.merge()
    top.flatten(-1, True)
    vsh = top.shapes(vli)
    landings = {}
    for v in V.each():
        vb = v.bbox(); mp = None
        for p in M.interacting(pya.Region(vb)).each(): mp = p; break
        if not mp: continue
        mb = mp.bbox(); horiz = mb.width() >= mb.height()
        vperp = vb.height() if horiz else vb.width()
        mperp = mb.height() if horiz else mb.width()
        if vperp >= mperp: continue                 # already matched (not flagged)
        landings.setdefault((mb.left, mb.bottom, mb.right, mb.top, horiz), []).append(vb)
    todel = []
    for s in vsh.each():
        b = s.polygon.bbox() if s.is_polygon() else (s.box if s.is_box() else None)
        if b is None: continue
        for (ml, mbo, mr, mt, h) in landings:
            if b.left >= ml and b.right <= mr and b.bottom >= mbo and b.top <= mt:
                todel.append(s); break
    for s in todel: s.delete()
    n = 0
    for (ml, mbo, mr, mt, h), cuts in landings.items():
        if h:                                        # M horizontal: bar spans x
            th = cuts[0].height(); cy = (mbo + mt) // 2
            vsh.insert(pya.Box(ml, cy - th // 2, mr, cy - th // 2 + th))
        else:                                        # M vertical: bar spans y
            tw = cuts[0].width(); cx = (ml + mr) // 2
            vsh.insert(pya.Box(cx - tw // 2, mbo, cx - tw // 2 + tw, mt))
        n += 1
    return n
'''

# (via_layer, metal_layer) pairs safe to bar — upper routing only, NOT V0/M1
_BAR_PAIRS = [(25, 30), (45, 50), (55, 60)]   # V2/M3, V4/M5, V5/M6

_WRITE_RE = re.compile(r"layout\.write\(\s*(['\"]).*?\1\s*\)")


def _strip_write(script: str) -> str:
    return _WRITE_RE.sub("", script)


def via_bar_snippet(pairs=None) -> str:
    """Byte-identical to asu_work/agent/repairs.via_bar_pass()."""
    pairs = pairs or _BAR_PAIRS
    lines = [_VIA_BAR_HELPER, "_asu_bars = 0"]
    for vln, mln in pairs:
        lines.append(f"_asu_bars += _asu_bar_pair(layout, {vln}, {mln})")
    lines.append("print('[asu-repair] via-bars placed:', _asu_bars)")
    return "\n".join(lines) + "\n"


def _looks_like_pya_layout(script: str) -> bool:
    """Fail-closed guard: only transform scripts that build a `layout` with pya."""
    return "layout" in script and ("pya" in script or "klayout" in script)


def _log(msg: str):
    print(f"[asu-official] {msg}", file=sys.stderr, flush=True)


def repair(original: str) -> tuple[str, str]:
    """Return (emitted_script, note). Deterministic; no KLayout at runtime."""
    if not _looks_like_pya_layout(original):
        return original, "not a pya layout script — emitted original (eligible floor)"
    emitted = _strip_write(original) + "\n" + via_bar_snippet()
    return emitted, "via-bar repair applied (V2/M3, V4/M5, V5/M6)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ASU block-repair agent (official)")
    ap.add_argument("info_json")
    # The runner always passes --model <name>; this deterministic agent ignores it
    # (the proven repair needs no model call, which also removes token cost and the
    # model-candidate credibility-gate risk entirely).
    ap.add_argument("--model", default="none")
    a = ap.parse_args(argv)

    info = json.loads(Path(a.info_json).read_text(encoding="utf-8"))
    case = info.get("case_name", "?")
    layout_path = Path(info["path_to_layout_script"])
    output_path = Path(info["output_path"])
    original = layout_path.read_text(encoding="utf-8", errors="replace")

    emitted, note = repair(original)
    _log(f"{case}: {note}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(emitted, encoding="utf-8")
    _log(f"{case}: wrote {output_path} ({len(emitted):,} chars)")

    # Usage is recorded by the benchmark model-service wrapper, not the agent, and
    # the official runner mounts the agent read-only. Best-effort only; never crash.
    usage_path = info.get("usage_path")
    if usage_path:
        try:
            up = Path(usage_path)
            up.parent.mkdir(parents=True, exist_ok=True)
            up.write_text(json.dumps({"input_tokens": 0, "output_tokens": 0,
                                      "calls": 0}, indent=1))
        except OSError as e:
            _log(f"usage write skipped (read-only, expected under official runner): "
                 f"{type(e).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
