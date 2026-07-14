"""PPA diagnosis — run the tools FIRST, hand the model actionable findings.

Zero model tokens. For an IP, produces a structured bundle telling us (and the
model) WHERE the PPA problems are, at file granularity:

  timing  hierarchy-preserved OpenSTA critical paths (FLATTEN=0) -> instance
          paths -> attributed to source files, path-ordered. This is the
          accurate axis: depth-ranking (per-module ltp) was empirically shown
          to MISLEAD (aes: depth said GHASH datapath, real STA said register
          integrity + control FSM). See NVIDIA_DAILY_RUN_LOG 2026-07-13.
  area    per-module cell counts (yosys stat, hierarchy kept) -> biggest-area
          files. Accurate (ASAP7 area ~0.6% error).
  power   PROXY only (OpenSTA absolute power ~31% error): leakage tracks cell
          count, so the area ranking doubles as the leakage proxy; dynamic
          headroom flagged via always-on sequential mass. Used to INFORM the
          model, not to gate acceptance (ADP=area*delay stays the objective).

Output: DiagnoseResult with `critical_files` (path-ordered, the scope ladder's
spine) and a compact `bundle_text` for prompting.

  python3 -m ppa.diagnose --ip aes            # print the bundle
  python3 -m ppa.diagnose --ip aes --json     # machine-readable
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .config import IPS, REPO
from .workspace import Workspace


# ── module <-> file mapping ────────────────────────────────────────────────────
def _file_stems(ip: str) -> dict[str, str]:
    """{module/file stem -> repo-relative source} for attribution. OpenTitan &
    the NVIDIA IPs name a module after its file, so the stem is the key."""
    spec = IPS[ip]
    return {Path(s).stem: s for s in spec.sources}


def _norm_seg(seg: str) -> str:
    """Normalise an STA instance-path segment to a candidate module stem:
    strip u_/i_ prefixes, gen_*[N] generate labels, _i/_inst suffixes."""
    seg = re.sub(r"\\", "", seg)
    seg = re.sub(r"gen_\w+\[\d+\]\.?", "", seg)     # generate-block labels
    seg = re.sub(r"^(u_|i_|g_)", "", seg)
    seg = re.sub(r"(_i|_inst|_reg)$", "", seg)
    return seg


def _module_stem(mod: str) -> str:
    """yosys module name -> source-file stem. Handles parametrised forms:
    $paramod\aes_reg_status\Width=... and $paramod$<hash>\aes_..._p/_n."""
    m = re.search(r"\\([A-Za-z_]\w*?)(?:\\Width=.*)?$", mod)
    name = m.group(1) if m else mod.lstrip("\\")
    return re.sub(r"_[pn]$", "", name)


def _attribute_instance(inst_path: str, stems: dict[str, str]) -> str | None:
    """Map an OpenSTA instance path (a/b/c/_123_) to a source file by matching
    normalised segments (deepest first) against known file stems."""
    segs = [s for s in inst_path.split("/") if s and not re.match(r"_\d+_?$", s)]
    for seg in reversed(segs):                       # deepest instance wins
        n = _norm_seg(seg)
        if n in stems:
            return stems[n]
        # longest-prefix match (aes_control_fsm inside u_aes_control_fsm_...)
        hit = max((st for st in stems if st and (st in n or n in st)),
                  key=len, default=None)
        if hit:
            return stems[hit]
    return None


# ── result ─────────────────────────────────────────────────────────────────────
@dataclass
class DiagnoseResult:
    ip: str
    wns_ps: float | None = None
    timing_met: bool = False
    # file -> {crit_cells, area_cells, seq_cells, on_worst_path}
    files: dict = field(default_factory=dict)
    critical_files: list = field(default_factory=list)   # path-ordered
    worst_path_files: list = field(default_factory=list)
    structure: str = ""          # STA classifier tag: arith-carry-chain / mux-
                                 # select / control-boolean-network / wide-gate-
                                 # decode / mixed-comb-depth — drives rule match
    struct_mix: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def bundle_text(self, top_n: int = 6) -> str:
        L = [f"## PPA diagnosis for {self.ip}",
             f"Timing: WNS={self.wns_ps}ps "
             f"({'MET' if self.timing_met else 'VIOLATED'})."
             + (f" Critical-path structure: {self.structure}."
                if self.structure else ""),
             "",
             "Critical-path files (fix these first; the worst timing path "
             "flows through them, in order):"]
        for f in self.worst_path_files[:top_n]:
            d = self.files.get(f, {})
            L.append(f"  - {Path(f).name}: {d.get('crit_cells',0)} cells on "
                     f"the worst path, {d.get('area_cells','?')} cells total")
        area_sorted = sorted(self.files.items(),
                             key=lambda kv: -(kv[1].get("area_cells") or 0))
        L += ["", "Largest-area files (area/leakage headroom):"]
        for f, d in area_sorted[:top_n]:
            L.append(f"  - {Path(f).name}: {d.get('area_cells','?')} cells")
        if self.notes:
            L += ["", "Notes:"] + [f"  - {n}" for n in self.notes]
        return "\n".join(L)


# ── the three axes ──────────────────────────────────────────────────────────────
def _run_flatten0(ws: Workspace) -> str:
    """Hierarchy-preserved synth+STA (FLATTEN=0); return reports dir path."""
    spec = ws.spec
    ws.run(f"cd {spec.syn_dir} && SKIP_SV2V={spec.skip_sv2v} FLATTEN=0 "
           f"DESIGN_NAME={spec.top} ./run_syn.sh all", timeout=7200)
    return f"{ws.root}/{spec.syn_dir}/reports"


def _parse_timing(ws: Workspace, reports: str, stems: dict) -> tuple:
    """Attribute the worst timing path's cells to source files. Returns
    (wns, met, per_file_crit_counts, ordered_worst_path_files)."""
    # multi-design dirs (prim) prefix reports with the top name; prefer that
    top = ws.spec.top
    def _pick(suffix):
        p = Path(reports) / f"{top}_{suffix}"
        return p if p.is_file() else Path(reports) / suffix
    paths = _pick("sta_timing_paths.txt")
    rpt = _pick("sta_timing_report.txt")
    wns, met = None, False
    if rpt.is_file():
        m = re.search(r"WNS\s*\|\s*(-?[\d.]+)", rpt.read_text())
        if m:
            wns = float(m.group(1)); met = wns >= 0
    if not paths.is_file():
        return wns, met, {}, [], []
    text = paths.read_text()
    # the single worst path = first block with the min slack; simplest: take the
    # first path block (reports are sorted worst-first per group) on the WORST
    # group. Grab all instance paths from the first ~40 cell lines.
    crit, ordered = {}, []
    # find the worst-slack block across the file
    blocks = re.split(r"\nStartpoint:", text)
    worst_block, worst_slack = "", 0.0
    for b in blocks[1:]:
        sm = re.search(r"slack \(VIOLATED\)", b)
        vm = re.search(r"(-?\d+\.\d+)\s+slack", b)
        if vm and float(vm.group(1)) < worst_slack:
            worst_slack, worst_block = float(vm.group(1)), b
    src = worst_block or (blocks[1] if len(blocks) > 1 else "")
    cell_types = []
    for cm in re.finditer(r"([\w\\/\[\].]+)/\w+/Y \((\w+?)x", src):
        f = _attribute_instance(cm.group(1), stems)
        cell_types.append((cm.group(2), 0.0))
        if f:
            crit[f] = crit.get(f, 0) + 1
            if f not in ordered:
                ordered.append(f)
    return wns, met, crit, ordered, cell_types


def _parse_area(ws: Workspace, stems: dict) -> dict:
    """Per-module cell counts via yosys stat (hierarchy kept)."""
    spec = ws.spec
    files = " ".join(Path(s).name for s in spec.sources)
    gen = f"{spec.syn_dir}/generated" if spec.skip_sv2v else spec.rtl_dir
    r = ws.run(
        f"cd {gen} && yosys -p 'read_verilog -sv {files}; "
        f"hierarchy -check -top {spec.top}; proc; opt -fast; techmap; "
        f"opt -fast; stat' 2>&1", timeout=3600)
    out = r.stdout or ""
    area, seq = {}, {}
    # per-module: "=== <mod> ===" ... "<N> cells" then a $_TYPE_ breakdown
    for mod, body in re.findall(r"=== (\S+) ===(.*?)(?=\n=== |\Z)", out, re.S):
        f = stems.get(_module_stem(mod))
        if not f:
            continue
        cm = re.search(r"^\s*(\d+)\s+cells\s*$", body, re.M)
        if cm:
            area[f] = area.get(f, 0) + int(cm.group(1))
        for dm in re.finditer(r"^\s*(\d+)\s+\$?_?[A-Za-z]*DFF", body, re.M):
            seq[f] = seq.get(f, 0) + int(dm.group(1))   # sequential mass (power proxy)
    return area, seq


# ── entry point ─────────────────────────────────────────────────────────────────
def diagnose(ip: str, reuse_reports: str | None = None) -> DiagnoseResult:
    if ip not in IPS:
        from .discover import get_spec, register
        register(get_spec(ip));
    stems = _file_stems(ip)
    res = DiagnoseResult(ip=ip)
    ws = Workspace.create(ip, tag="diag")
    try:
        reports = reuse_reports or _run_flatten0(ws)
        wns, met, crit, ordered, cell_types = _parse_timing(ws, reports, stems)
        area, seq = _parse_area(ws, stems)
        res.wns_ps, res.timing_met = wns, met
        res.worst_path_files = ordered
        if cell_types:
            from .sta_feedback import classify, _base_type
            typed = [(_base_type(t), d) for t, d in cell_types]
            res.structure, res.struct_mix = classify(typed)
            res.notes.append(f"critical structure: {res.structure} "
                             f"(mix { {k: round(v,2) for k,v in res.struct_mix.items()} })")
        allf = set(crit) | set(area)
        for f in allf:
            res.files[f] = {"crit_cells": crit.get(f, 0),
                            "area_cells": area.get(f),
                            "seq_cells": seq.get(f, 0),
                            "on_worst_path": f in crit}
        if seq:
            hog = max(seq.items(), key=lambda kv: kv[1])
            res.notes.append(f"power(proxy): {Path(hog[0]).name} has the most "
                             f"sequential cells ({hog[1]}) — leakage/clock-gate "
                             f"candidate")
        # critical_files = worst-path files first (path order), then area hogs
        res.critical_files = ordered + [
            f for f, _ in sorted(area.items(), key=lambda kv: -(kv[1] or 0))
            if f not in ordered]
        if not ordered:
            res.notes.append("flat/shallow hierarchy — no per-file timing "
                             "attribution available; using area ranking (fine "
                             "for small IPs that send full context anyway)")
        res.notes.append("power: proxy only (leakage~=cells); ADP=area*delay "
                         "is the acceptance objective")
    finally:
        ws.destroy()
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="PPA diagnosis (zero model tokens)")
    ap.add_argument("--ip", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.ip not in IPS:
        from .discover import get_spec, register
        register(get_spec(a.ip)); a.ip = get_spec(a.ip).name
    r = diagnose(a.ip)
    if a.json:
        print(json.dumps({"ip": r.ip, "wns_ps": r.wns_ps,
                          "timing_met": r.timing_met,
                          "critical_files": [Path(f).name for f in r.critical_files],
                          "worst_path_files": [Path(f).name for f in r.worst_path_files],
                          "files": {Path(f).name: d for f, d in r.files.items()}},
                         indent=1))
    else:
        print(r.bundle_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
