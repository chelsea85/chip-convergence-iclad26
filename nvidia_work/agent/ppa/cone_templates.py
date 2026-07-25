"""Verified arrival-aware cone templates (Codex expanded review §5.2).

`small-cone-arrival-template` requires "a finite audited template set": the
model IDENTIFIES a small (<=5-input) critical Boolean cone and its late input,
then SELECTS one of these templates — it never invents a replacement network.

The audit is honest and machine-checked: every template's `impl` is verified
EXHAUSTIVELY equivalent to its `spec` over all 2^n input assignments (n<=5 ->
<=32 rows) by `verify_all()`, which `test_cone_templates.py` runs. Each
template's structural promise is that the LATE input touches only the FINAL
gate/mux of the implementation.

These are prompt-side search artifacts. LEC-v2 + dualsim remain the only
acceptance authority; a template merely raises the prior that the rewrite is
provable.
"""
from __future__ import annotations

from itertools import product

# Each template: id, inputs (last-listed input is the LATE one), spec/impl as
# python lambdas over bools, verilog pattern (documentation for the prompt),
# note. spec = the natural/source form; impl = the arrival-aware form.
TEMPLATES = [
    dict(id="T1-and3-late",
         inputs=("a", "b", "c_late"),
         spec=lambda a, b, c: a and b and c,
         impl=lambda a, b, c: (a and b) and c,
         verilog="assign f = (a & b) & c_late;",
         note="chain ANDs so the late input feeds only the final AND"),
    dict(id="T2-or3-late",
         inputs=("a", "b", "c_late"),
         spec=lambda a, b, c: a or b or c,
         impl=lambda a, b, c: (a or b) or c,
         verilog="assign f = (a | b) | c_late;",
         note="chain ORs so the late input feeds only the final OR"),
    dict(id="T3-and4-late",
         inputs=("a", "b", "c", "d_late"),
         spec=lambda a, b, c, d: a and b and c and d,
         impl=lambda a, b, c, d: ((a and b) and c) and d,
         verilog="assign f = ((a & b) & c) & d_late;",
         note="skew the AND tree: early inputs deep, late input at the root"),
    dict(id="T4-xor3-late",
         inputs=("a", "b", "c_late"),
         spec=lambda a, b, c: a ^ b ^ c,
         impl=lambda a, b, c: (a ^ b) ^ c,
         verilog="assign f = (a ^ b) ^ c_late;",
         note="XOR chain skewed so the late input meets one final XOR"),
    dict(id="T5-aoi-late",
         inputs=("a", "b", "c_late"),
         spec=lambda a, b, c: (a and b) or c,
         impl=lambda a, b, c: (a and b) or c,
         verilog="assign f = (a & b) | c_late;",
         note="keep the late input on the OR side (single-gate depth); do "
              "NOT factor it into the AND term"),
    dict(id="T6-mux-late-select",
         inputs=("a", "b", "s_late"),
         spec=lambda a, b, s: a if s else b,
         impl=lambda a, b, s: a if s else b,
         verilog="assign f = s_late ? a : b;",
         note="late SELECT is already optimal: both data cofactors compute "
              "early, the late select drives one mux — this is the "
              "late-input-cofactor canonical form"),
    dict(id="T7-maj3-late-cofactor",
         inputs=("a", "b", "c_late"),
         spec=lambda a, b, c: (a and b) or (a and c) or (b and c),
         impl=lambda a, b, c: (a or b) if c else (a and b),
         verilog="assign f = c_late ? (a | b) : (a & b);",
         note="majority-of-3 cofactored on the late input: late bit drives "
              "only the final mux instead of two AND terms"),
    dict(id="T8-mux2-late-inner-select",
         inputs=("a", "b", "c", "s1", "s2_late"),
         spec=lambda a, b, c, s1, s2: a if s1 else (b if s2 else c),
         impl=lambda a, b, c, s1, s2: (a if s1 else b) if s2 else (a if s1 else c),
         verilog="assign f = s2_late ? (s1 ? a : b) : (s1 ? a : c);",
         note="pull a late INNER select to the root mux: precompute both "
              "s2-cofactors of the whole chain, select last"),
    dict(id="T9-and-of-or-late",
         inputs=("a", "b", "c", "d_late"),
         spec=lambda a, b, c, d: (a or b) and (c or d),
         impl=lambda a, b, c, d: ((a or b) and c) or ((a or b) and d),
         verilog="assign f = ((a | b) & c) | ((a | b) & d_late);",
         note="distribute so the late input reaches f through AND->OR (2 "
              "gates) without first waiting on its own OR term"),
]


def verify_template(t: dict) -> bool:
    """Exhaustive equivalence check of spec vs impl over all 2^n inputs."""
    n = len(t["inputs"])
    return all(bool(t["spec"](*v)) == bool(t["impl"](*v))
               for v in product([False, True], repeat=n))


def verify_all() -> list[str]:
    """Return ids of any template failing its exhaustive audit (must be [])."""
    return [t["id"] for t in TEMPLATES if not verify_template(t)]


def catalog_text() -> str:
    """Compact, prompt-injectable catalog of the verified templates."""
    lines = ["VERIFIED ARRIVAL-AWARE TEMPLATES (late input listed last; each "
             "is exhaustively proven equivalent to its spec — choose one, "
             "map your cone's signals onto it, do not invent new networks):"]
    for t in TEMPLATES:
        lines.append(f"  {t['id']}: {t['verilog']}  // {t['note']}")
    return "\n".join(lines)
