"""STA-localized feedback — Dr. RTL's highest-leverage lever.

Parses the harness's OpenSTA reports (sta_timing_report.txt summary +
sta_timing_paths.txt detailed paths) into structured path records with a
root-cause tag, and renders a compact, non-redundant feedback block for the
proposer prompt.

The synthesized netlist has anonymized cell names (yosys renames everything),
so RTL-name recovery is impossible; localization instead uses the path's
*cell-family profile* — e.g. a path dominated by XNOR/XOR + MAJ cells is a
ripple-carry/adder chain, MUX-heavy is a selection tree, AOI/OAI-heavy is a
boolean control network. The tag doubles as the retrieval key into the skill
library.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .config import IPS, REPO

# ── cell families (ASAP7 base-name prefixes, order matters) ──────────────────
_FAMILIES = (
    ("XNOR", "xor"), ("XOR", "xor"),
    ("MAJ", "carry"), ("FA", "carry"), ("HA", "carry"),
    ("MUX", "mux"),
    ("AOI", "aoi"), ("OAI", "aoi"), ("AO", "aoi"), ("OA", "aoi"),
    ("NAND", "gate"), ("NOR", "gate"), ("AND", "gate"), ("OR", "gate"),
    ("BUF", "buf"), ("INV", "buf"), ("HB", "buf"),
    ("DFF", "seq"), ("SDF", "seq"), ("ICG", "seq"), ("DLL", "seq"),
)


def _base_type(cell: str) -> str:
    """XNOR2x2_ASAP7_75t_R -> XNOR2"""
    m = re.match(r"([A-Za-z0-9]+?)x(?:p)?\d", cell)
    return m.group(1) if m else cell


def _family(base: str) -> str:
    for pre, fam in _FAMILIES:
        if base.startswith(pre):
            return fam
    return "other"


# ── path records ──────────────────────────────────────────────────────────────
@dataclass
class PathInfo:
    start: str
    end: str
    start_kind: str
    end_kind: str
    slack: float | None = None
    cells: list = field(default_factory=list)     # (base_type, delay_ps)
    tag: str = ""
    mix: dict = field(default_factory=dict)       # family -> fraction

    @property
    def depth(self) -> int:                       # comb cells only
        return sum(1 for t, _ in self.cells if _family(t) not in ("seq",))

    def worst_cells(self, k: int = 3) -> list:
        return sorted(self.cells, key=lambda c: -c[1])[:k]


def classify(cells: list) -> tuple[str, dict]:
    comb = [(t, d) for t, d in cells if _family(t) not in ("seq", "buf")]
    if not comb:
        return "sequential-only", {}
    n = len(comb)
    mix = {}
    for t, _ in comb:
        f = _family(t)
        mix[f] = mix.get(f, 0) + 1
    mix = {k: v / n for k, v in sorted(mix.items(), key=lambda kv: -kv[1])}

    # ABC maps adder carry logic to AOI/OA/MAJ mixes, so the XOR fraction is
    # the reliable arithmetic signature (control logic is rarely >10% XOR)
    if mix.get("xor", 0) + mix.get("carry", 0) >= 0.20:
        tag = "arith-carry-chain"
    elif mix.get("mux", 0) >= 0.25:
        tag = "mux-select"
    elif mix.get("aoi", 0) >= 0.50:
        tag = "control-boolean-network"
    elif mix.get("gate", 0) >= 0.35:
        tag = "wide-gate-decode"
    else:
        tag = "mixed-comb-depth"
    return tag, mix


# ── parsers ───────────────────────────────────────────────────────────────────
def parse_summary(text: str) -> dict:
    out = {}
    for key, name in (("wns", "WNS"), ("tns", "TNS")):
        m = re.search(rf"\|\s*{name}\s*\|\s*(-?[\d.]+)\s*ps\s*\|\s*(-?[\d.]+)\s*ps",
                      text)
        if m:
            out[key] = float(m.group(1))
            out[f"hold_{key}"] = float(m.group(2))
    m = re.search(r"\|\s*(\w+)\s*\|\s*([\d.]+)\s*\|\s*[\d.]+\s*\|\s*[\d.]+\s*\|",
                  text)
    if m:
        out["clock"], out["period"] = m.group(1), float(m.group(2))
    return out


_START_RE = re.compile(r"Startpoint:\s+(\S+)\s+\(([^)]*)\)")
_END_RE = re.compile(r"Endpoint:\s+(\S+)\s+\(([^)]*)\)")
_CELL_RE = re.compile(
    r"^\s+([\d.]+)\s+[\d.]+\s+[\^v]\s+(\S+)/\w+\s+\(([^)]+)\)\s*$")
_SLACK_RE = re.compile(r"^\s+(-?[\d.]+)\s+slack \((VIOLATED|MET)\)")


def parse_paths(text: str, section: str = "SETUP") -> list[PathInfo]:
    if "HOLD TIMING PATHS" in text and section == "SETUP":
        text = text.split("HOLD TIMING PATHS")[0]
    paths: list[PathInfo] = []
    cur: PathInfo | None = None
    seen_inst: set[str] = set()
    for line in text.splitlines():
        sm = _START_RE.search(line)
        if sm:
            cur = PathInfo(start=sm.group(1), end="?",
                           start_kind=sm.group(2), end_kind="?")
            seen_inst = set()
            continue
        if cur is None:
            continue
        em = _END_RE.search(line)
        if em:
            cur.end, cur.end_kind = em.group(1), em.group(2)
            continue
        cm = _CELL_RE.match(line)
        if cm:
            inst = cm.group(2)
            if inst not in seen_inst:      # clock-network lines repeat insts
                seen_inst.add(inst)
                cur.cells.append((_base_type(cm.group(3)), float(cm.group(1))))
            continue
        km = _SLACK_RE.match(line)
        if km:
            cur.slack = float(km.group(1)) * (1 if km.group(2) == "MET" else 1)
            cur.tag, cur.mix = classify(cur.cells)
            paths.append(cur)
            cur = None
    return paths


# ── feedback rendering (compact, for the proposer prompt) ────────────────────
def _kind_short(kind: str) -> str:
    if "flip-flop" in kind:
        return "REG"
    if "input" in kind:
        return "IN"
    if "output" in kind:
        return "OUT"
    return kind[:12]


def feedback(reports_dir: Path, top_k: int = 3) -> str:
    summary_f = reports_dir / "sta_timing_report.txt"
    paths_f = reports_dir / "sta_timing_paths.txt"
    if not summary_f.exists() or not paths_f.exists():
        return "STA: no reports available"
    s = parse_summary(summary_f.read_text())
    paths = parse_paths(paths_f.read_text())

    lines = [f"STA: WNS={s.get('wns', '?')}ps TNS={s.get('tns', '?')}ps "
             f"clock={s.get('clock', '?')} period={s.get('period', '?')}ps "
             f"({'VIOLATED' if (s.get('wns') or 0) < 0 else 'MET'})"]

    # deduplicate by endpoint, keep worst per endpoint, preserve order
    by_end: dict[str, PathInfo] = {}
    for p in paths:
        if p.end not in by_end:
            by_end[p.end] = p
    tags: dict[str, int] = {}
    for i, p in enumerate(list(by_end.values())[:top_k], 1):
        mix = ", ".join(f"{k} {v:.0%}" for k, v in list(p.mix.items())[:3])
        worst = ", ".join(f"{t} {d:.0f}ps" for t, d in p.worst_cells(2))
        lines.append(
            f" {i}. slack={p.slack}ps {_kind_short(p.start_kind)}->"
            f"{_kind_short(p.end_kind)} depth={p.depth} tag={p.tag} "
            f"[{mix}] worst: {worst}")
        tags[p.tag] = tags.get(p.tag, 0) + 1
    if tags:
        dom = max(tags, key=tags.get)
        lines.append(f"Diagnosis: dominant bottleneck = {dom} "
                     f"({tags[dom]}/{min(len(by_end), top_k)} top paths). "
                     "Cell names are post-synth anonymized; reason from the "
                     "structural profile.")
    return "\n".join(lines)


def dominant_tag(reports_dir: Path, top_k: int = 3) -> str | None:
    paths_f = reports_dir / "sta_timing_paths.txt"
    if not paths_f.exists():
        return None
    paths = parse_paths(paths_f.read_text())
    tags: dict[str, int] = {}
    for p in paths[:top_k]:
        tags[p.tag] = tags.get(p.tag, 0) + 1
    return max(tags, key=tags.get) if tags else None


# ── CLI ───────────────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description="render STA feedback block")
    ap.add_argument("--ip", help="IP name (auto-discovered if unknown)")
    ap.add_argument("--reports", help="explicit reports dir")
    ap.add_argument("--top", type=int, default=3)
    a = ap.parse_args(argv)
    if a.ip and a.ip not in IPS:
        from .discover import get_spec, register
        spec = get_spec(a.ip)
        register(spec)
        a.ip = spec.name
    d = Path(a.reports) if a.reports else REPO / IPS[a.ip].syn_dir / "reports"
    print(feedback(d, a.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
