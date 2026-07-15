"""DRC report -> structured, actionable diagnosis. Zero model tokens.

The ASU DRC report (BlockN.drc.json) already carries everything a repair needs:
per-rule violation counts, the rule DESCRIPTION (which usually encodes the fix,
e.g. "M4 horizontal edges must be at a grid of 24 nm"), and exact violation
geometry (bbox + vertices in DBU). We parse it into a Digest that classifies
each rule by fix-strategy so deterministic passes can handle what they can and
the model only sees what genuinely needs judgement.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# ASAP7 layer-datatype -> friendly name (from asap7.lyp / the rule vocabulary).
# Only the routing/via layers that appear in violations matter here.
_GRID_RE = re.compile(r"grid of\s+([\d.]+)\s*nm", re.I)
_SPACING_RE = re.compile(r"(?:space|spacing|apart|separation).*?([\d.]+)\s*nm", re.I)
_WIDTH_RE = re.compile(r"width.*?([\d.]+)\s*nm", re.I)
_ENCLOSE_RE = re.compile(r"enclos", re.I)


@dataclass
class RuleFinding:
    rule: str
    description: str
    count: int
    violations: list          # raw geometry dicts (type/bbox/vertices, DBU)
    fix_kind: str = "unknown"  # grid | spacing | width | enclosure | area | unknown
    param_nm: float | None = None    # the numeric bound in the description, if any
    layer_hint: str = ""       # e.g. "M4", "V0", parsed from the rule name

    @property
    def bboxes(self):
        return [v.get("bbox") for v in self.violations if v.get("bbox")]


@dataclass
class Digest:
    case: str
    total_violations: int
    findings: list = field(default_factory=list)   # RuleFinding, worst-count first

    def by_kind(self, kind: str):
        return [f for f in self.findings if f.fix_kind == kind]

    def deterministic_share(self) -> float:
        det = sum(f.count for f in self.findings
                  if f.fix_kind in ("grid",))
        return det / self.total_violations if self.total_violations else 0.0

    def bundle_text(self, top_n: int = 20) -> str:
        L = [f"## DRC diagnosis for {self.case}",
             f"{self.total_violations} violations across {len(self.findings)} rules.",
             ""]
        for f in self.findings[:top_n]:
            tag = f"[{f.fix_kind}" + (f" {f.param_nm}nm" if f.param_nm else "") + "]"
            L.append(f"- {f.rule} x{f.count} {tag}: {f.description}")
        return "\n".join(L)


def _classify(rule: str, desc: str) -> tuple[str, float | None, str]:
    """(fix_kind, param_nm, layer_hint) from the rule name + description."""
    layer = ""
    m = re.match(r"([A-Z]+\d*)", rule)
    if m:
        layer = m.group(1)
    g = _GRID_RE.search(desc)
    if g:
        return "grid", float(g.group(1)), layer
    if _ENCLOSE_RE.search(desc):
        return "enclosure", None, layer
    if re.search(r"\barea\b", desc, re.I):
        return "area", None, layer
    w = _WIDTH_RE.search(desc)
    if w:
        return "width", float(w.group(1)), layer
    s = _SPACING_RE.search(desc)
    if s:
        return "spacing", float(s.group(1)), layer
    return "unknown", None, layer


_RULES_CACHE = None


def rule_library() -> dict:
    global _RULES_CACHE
    if _RULES_CACHE is None:
        _RULES_CACHE = json.loads(
            (Path(__file__).with_name("drc_rules.json")).read_text())
    return _RULES_CACHE


def match_rule(rule_name: str) -> dict | None:
    """Return the repair-rule-library entry whose `match` regex hits this DRC
    rule name (highest-priority match wins)."""
    hits = [r for r in rule_library()["rules"]
            if re.search(r["match"], rule_name)]
    hits.sort(key=lambda r: r.get("priority", 99))
    return hits[0] if hits else None


def load(report_path: str | Path, case: str | None = None) -> Digest:
    d = json.loads(Path(report_path).read_text())
    case = case or d.get("case_name", "block")
    findings = []
    for rule, info in d.get("rules", {}).items():
        desc = str(info.get("description", "")).strip()
        kind, param, layer = _classify(rule, desc)
        findings.append(RuleFinding(
            rule=rule, description=desc,
            count=int(info.get("violation_count", 0) or 0),
            violations=info.get("violations", []),
            fix_kind=kind, param_nm=param, layer_hint=layer))
    findings.sort(key=lambda f: -f.count)
    total = int(d.get("total_violations",
                      sum(f.count for f in findings)))
    return Digest(case=case, total_violations=total, findings=findings)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="DRC report -> diagnosis (0 tokens)")
    ap.add_argument("report")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    dg = load(a.report)
    if a.json:
        print(json.dumps({"case": dg.case, "total": dg.total_violations,
                          "deterministic_share": round(dg.deterministic_share(), 3),
                          "rules": [{"rule": f.rule, "count": f.count,
                                     "kind": f.fix_kind, "param_nm": f.param_nm,
                                     "layer": f.layer_hint} for f in dg.findings]},
                         indent=1))
    else:
        print(dg.bundle_text())
        print(f"\ndeterministic (grid) share: {dg.deterministic_share():.1%}")
