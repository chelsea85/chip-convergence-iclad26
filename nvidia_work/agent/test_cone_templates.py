"""Machine audit for the verified cone-template library (Codex §5.2: the
small-cone-arrival-template rung is only legitimate "if backed by a finite
AUDITED template set"). Every template is exhaustively checked spec==impl
over all 2^n assignments — this test IS the audit."""
import sys
sys.path.insert(0, ".")
from itertools import product
from ppa.cone_templates import TEMPLATES, verify_all, verify_template, catalog_text

p = f = 0
def ok(name, cond):
    global p, f
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    p += cond; f += not cond

# 1. the audit itself: every template exhaustively equivalent
fails = verify_all()
ok(f"all {len(TEMPLATES)} templates exhaustively PROVEN spec==impl (2^n rows)",
   fails == [])
if fails:
    print("   FAILING:", fails)

# 2. audit sensitivity: a deliberately WRONG template must be caught
bad = dict(id="neg", inputs=("a", "b"),
           spec=lambda a, b: a and b,
           impl=lambda a, b: a or b)
ok("audit catches an inequivalent template (negative control)",
   verify_template(bad) is False)

# 3. structural constraints
ok("every template has <=5 inputs (exhaustive audit stays trivial)",
   all(len(t["inputs"]) <= 5 for t in TEMPLATES))
ok("every template names its LATE input last",
   all(t["inputs"][-1].endswith("_late") or "late" in t["inputs"][-1]
       for t in TEMPLATES))
ok("every template ships verilog + note",
   all(t.get("verilog") and t.get("note") for t in TEMPLATES))
ok("template ids unique", len({t["id"] for t in TEMPLATES}) == len(TEMPLATES))

# 4. catalog is prompt-ready and complete
cat = catalog_text()
ok("catalog lists every template id", all(t["id"] in cat for t in TEMPLATES))
ok("catalog forbids inventing networks", "do not invent" in cat.lower())

# 5. the rung carries the catalog into its prompt directive
from ppa.proposer import LADDER
rung = next((r for r in LADDER if r["key"] == "small-cone-arrival-template"), None)
ok("small-cone-arrival-template rung exists", rung is not None)
ok("rung directive embeds the verified catalog",
   rung is not None and all(t["id"] in rung["directive"] for t in TEMPLATES))

print(f"test_cone_templates: {p}/{p+f} PASS")
sys.exit(0 if f == 0 else 1)
