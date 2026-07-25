"""Regression for the timing-rung upgrade v2+v3 (2026-07-23, search-side only).

v1 -> v2: Codex expanded literature review approved the DAC-ready five and
rejected v1's fanout-duplicate / arrival-aware-restructure. v3 adds the three
follow-ups: rho-normalized risk gating (§8.3), the xor-linear-network
classifier split (§3.6), and the audited small-cone template rung (§5.2,
rank #2). Gates/acceptance untouched throughout."""
import sys
sys.path.insert(0, ".")
from ppa.proposer import LADDER, pick_strategies, _HARD_RULES
from ppa.controller import (_timing_biased, _risk_gated, _TIMING_RUNGS,
                            _TAG_TO_RUNGS, _HIGH_DELTA)
from ppa import skills
from ppa import sta_feedback as S

p = f = 0
def ok(name, cond):
    global p, f
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    p += cond; f += not cond

keys = {r["key"] for r in LADDER}
V2 = {"sum-cluster-expose", "xor-depth-resynthesize", "late-input-cofactor",
      "priority-prefix-select", "compare-decode-prefix",
      "small-cone-arrival-template"}
REJECTED = {"fanout-duplicate", "arrival-aware-restructure",
            "late-arrival-shannon"}

# 1. approved rungs in, rejected out
ok("approved six present in LADDER", V2 <= keys)
ok("rejected v1 rungs absent", not (REJECTED & keys))
ok("v2 rungs are axis=perf",
   all(r["axis"] == "perf" for r in LADDER if r["key"] in V2))

# 2. prompt discipline
sr = next(r for r in LADDER if r["key"] == "share-resources")
ok("share-resources FSM re-encode clause removed",
   "re-encode" not in sr["directive"].lower())
ok("register-to-register hard rule present",
   "register-to-register" in _HARD_RULES)
ok("one-cone + ledger + refusal rules present",
   "ONE cone" in _HARD_RULES and "NO edit" in _HARD_RULES)

# 3. tag map (v2+v3)
ok("arith-carry-chain leads with sum-cluster-expose",
   _TAG_TO_RUNGS["arith-carry-chain"][0] == "sum-cluster-expose")
ok("xor-linear-network tag mapped, xor rung first",
   _TAG_TO_RUNGS.get("xor-linear-network", [None])[0]
   == "xor-depth-resynthesize")
ok("balanced-tree/carry-save demoted from every preferred list",
   all(x not in v for v in _TAG_TO_RUNGS.values()
       for x in ("balanced-tree", "carry-save")))
ok("all preferred rungs exist in LADDER",
   all(x in keys for v in _TAG_TO_RUNGS.values() for x in v))

# 4. classifier split (synthetic replay of the RECORDED mixes)
_orig = S._family
S._family = lambda t: t
kmac_cells = [("xor", 1)] * 40 + [("aoi", 1)] * 38 + [("gate", 1)] * 22
sha_cells = ([("aoi", 1)] * 45 + [("gate", 1)] * 29 + [("xor", 1)] * 24
             + [("carry", 1)] * 2)
ok("kmac-style mix (xor .40 top, carry 0) -> xor-linear-network",
   S.classify(kmac_cells)[0] == "xor-linear-network")
ok("sha512-style mix (aoi .45 top, real adders) stays arith-carry-chain",
   S.classify(sha_cells)[0] == "arith-carry-chain")
S._family = _orig

# 5. rho-normalized risk gate (§8.3)
ac = _TAG_TO_RUNGS["arith-carry-chain"]
met = _risk_gated(ac, 22.2, 1500.0)            # rho=0 -> met band
ok("timing met (rho<0.05): duplication rung dropped, clustering kept",
   "late-input-cofactor" not in met and met[0] == "sum-cluster-expose")
near = _risk_gated(ac, -50.0, 1500.0)          # rho=0.033 < 0.05
ok("near-met (rho<0.05): duplication rung dropped",
   "late-input-cofactor" not in near and "sum-cluster-expose" in near)
mid = _risk_gated(ac, -97.3, 1500.0)           # rho=0.065 mid band
ok("mid band: full interleaved set incl. cofactor",
   "late-input-cofactor" in mid and set(_TIMING_RUNGS) <= set(mid))
severe = _risk_gated(["restructure-select", "micro-opt"], -430.0, 100.0)  # rho=4.3
ok("severe (rho>1): only high-delta rungs survive",
   severe and all(r in _HIGH_DELTA for r in severe))
ok("no-period fallback: rho=0 path safe",
   _risk_gated(ac, -500.0, None) is not None)
ok("_HIGH_DELTA is exactly the approved template rungs", _HIGH_DELTA == V2)

# 6. templates power the rung (full audit lives in test_cone_templates.py)
from ppa.cone_templates import verify_all
ok("cone-template audit clean", verify_all() == [])

# 7. retrieval
def _texts(entries):
    return " ".join(e["content"] if isinstance(e, dict) else str(e)
                    for e in entries)
b = _texts(skills.retrieve(["arith-carry-chain"], sections=None, k=14))
ok("ABC-rebalance caution retrievable", "RE-BALANCED AWAY" in b)
bx = _texts(skills.retrieve(["xor-linear-network"], sections=None, k=8))
ok("xor + template recipes retrievable for the new tag",
   "XOR" in bx or "template" in bx.lower())

got = pick_strategies(4, {"perf": 0.6, "area": 0.3, "power": 0.1})
ok("pick_strategies returns 4 distinct", len({r['key'] for r in got}) == 4)

print(f"test_timing_rungs: {p}/{p+f} PASS")
sys.exit(0 if f == 0 else 1)
