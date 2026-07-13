"""ACE-style playbook: the machine-readable optimization catalog.

Bullets with IDs and helpful/harmful counters; deterministic curator (append /
vote / near-dup merge) — the playbook is NEVER rewritten wholesale (context
collapse). Retrieval is by STA root-cause tag + objective axis, so the
proposer only sees bullets relevant to the current bottleneck.

Seeded from OPTIMIZATION_CATALOG.md (P1-P5, L1-L5) + the deep-read paper
harvest (Dr. RTL patterns/AVOIDs, RTLScout lessons, Alpha-RTL LZA case,
Pluto per-axis strategies). JSON storage — one file per repo, human-editable.
"""
from __future__ import annotations

import difflib
import json
import time
from pathlib import Path

from .config import AGENT

PLAYBOOK = AGENT / "playbook.json"

# sections: timing | area | power | pitfall | avoid | tool
# tags: sta root-cause tags + generic keys the proposer queries with
_SEED = [
    # ── our measured patterns ────────────────────────────────────────────────
    dict(id="p2-balanced-tree", section="timing", tags=["arith-carry-chain"],
         content="P2 (MEASURED, sha512): rewrite serial N-operand add chains "
                 "as balanced binary adder trees (mod-2^w addition is "
                 "associative -> provably equivalent). sha512: WNS -97->+235ps,"
                 " area -0.6%, gate 24/24. Expose sub-terms as wires."),
    dict(id="p2b-carry-save", section="timing", tags=["arith-carry-chain"],
         content="P2b: for 3+ operand adds, use carry-save (3:2 compressor) "
                 "tree -> single final carry-propagate adder; shorter than "
                 "balanced CPA tree. Higher rewrite risk; keep operand order "
                 "documented and let the gate catch errors."),
    dict(id="p1-gray-deregister", section="timing", tags=["cdc", "mixed-comb-depth"],
         content="P1 (MEASURED, async_fifo): registered gray pointer equals "
                 "gray(registered binary); replace duplicate gray register "
                 "with combinational bin>>1 ^ bin. +13ps slack but +0.86% "
                 "area (FF removal added comb cells). CDC-safe (single-bit "
                 "change property preserved)."),
    dict(id="p4-share-lookahead", section="area", tags=["arith-carry-chain"],
         content="P4: share redundant +/-1 lookahead incrementers (e.g. "
                 "async_fifo computes gray(next) AND gray(next+1) with two "
                 "adders; derive the second from the first)."),
    dict(id="p5-syn-knobs", section="tool", tags=["tool"],
         content="P5: VT/CORNER/ABC_AREA knobs exist but env.sh clobbers CLI "
                 "values during synth while STA uses caller values -> "
                 "inconsistent libs. Only use knobs via workspace-patched "
                 "env; keep RVT/TT/speed for scored runs until organizer "
                 "clarifies legality."),
    # ── Dr. RTL pattern->strategy library (validated on 20 designs) ─────────
    dict(id="drrtl-fanout", section="timing", tags=["control-boolean-network",
                                                    "wide-gate-decode"],
         content="High-fanout control signal on critical path -> replicate "
                 "the driver register/logic per consumer group (signal "
                 "replication / fanout management)."),
    dict(id="drrtl-precompute", section="timing", tags=["control-boolean-network",
                                                        "mux-select"],
         content="Deep FSM/decode condition feeding datapath -> pre-compute "
                 "the condition one cycle earlier into a register when a "
                 "spare cycle exists (condition pre-computation). CHECK TB "
                 "latency tolerance first."),
    dict(id="drrtl-wide-compare", section="timing", tags=["wide-gate-decode"],
         content="Wide equality/magnitude compare on critical path -> "
                 "restructure: split into ranges, early-out constant bits, "
                 "or one-hot re-encode the compared state."),
    dict(id="drrtl-mux-restructure", section="timing", tags=["mux-select"],
         content="Mux-heavy selection tree -> re-balance select logic, "
                 "convert priority chains to parallel one-hot selects, or "
                 "insert a register on the select path (selective register "
                 "insertion; latency check needed)."),
    dict(id="alpha-lza-hierarchical", section="timing", tags=["wide-gate-decode",
                                                              "mux-select"],
         content="Wide flat casez/priority encoder -> two-level hierarchy: "
                 "4-bit group valid bits + per-group encode (log depth). "
                 "C910 LZA case: -40% delay, -32% area."),
    # ── RTLScout lessons + arithmetic architecture menu ──────────────────────
    dict(id="rtlscout-cutpoints", section="timing", tags=["arith-carry-chain",
                                                          "mixed-comb-depth"],
         content="Declare named intermediate wires with explicit widths at "
                 "logical boundaries — helps Yosys/ABC partition and "
                 "optimize independently (RTLScout lesson)."),
    dict(id="rtlscout-mux-vs-shift", section="area", tags=["mux-select"],
         content="Barrel shifters have overhead; for small index ranges "
                 "(<=~11) an explicit mux chain is cheaper (RTLScout)."),
    dict(id="arith-menu", section="timing", tags=["arith-carry-chain"],
         content="Arithmetic architecture menu for critical-path * and +: "
                 "partial products via carry-save/Wallace/Dadda/4:2-compressor"
                 " tree; final adder Kogge-Stone / Brent-Kung / Sklansky / "
                 "sparse-KS. Propose ONE alternative per candidate."),
    # ── Pluto per-axis strategy lists ────────────────────────────────────────
    dict(id="pluto-area", section="area", tags=["area"],
         content="Area levers: logic simplification/CSE, FSM re-encoding "
                 "(binary vs one-hot by state count), resource sharing of "
                 "mutually-exclusive adders/multipliers, operator strength "
                 "reduction (x*2^k -> shift)."),
    dict(id="pluto-power", section="power", tags=["power"],
         content="Power levers: operand isolation (gate inputs of unused "
                 "units), clock gating via enable registers, minimize "
                 "shifting register banks (pointer-addressed window instead "
                 "of physical shift). Power numbers are noisy without "
                 "activity data — trust only large deltas."),
    dict(id="shift-to-pointer", section="power", tags=["power", "area"],
         content="Large physically-shifting register file (e.g. sha512 w_mem "
                 "16x64 shifts 1024 FF/cycle) -> circular buffer with "
                 "pointer-addressed reads; cuts FF clock activity and mux "
                 "area. Medium risk: index arithmetic must be exact."),
    # ── AVOID entries ─────────────────────────────────────────────────────────
    dict(id="avoid-rebalance-optimal", section="avoid", tags=["avoid"],
         content="AVOID re-balancing logic ABC already optimizes well "
                 "(absorbed by synthesis, adds churn/risk for ~0 gain) — "
                 "e.g. simple 2-3 operand expressions (Dr. RTL AVOID)."),
    dict(id="avoid-move-control-regs", section="avoid", tags=["avoid"],
         content="AVOID moving control-signal updates across register "
                 "boundaries — top equivalence-breaker class in Dr. RTL "
                 "(SEC failures)."),
    dict(id="avoid-ff-count-chasing", section="avoid", tags=["avoid"],
         content="AVOID chasing FF count: in ASAP7 FFs are cheap; removing "
                 "FFs by adding comb+buffers can INCREASE area (L1, measured "
                 "in exp1)."),
    dict(id="avoid-cdc-restructure", section="avoid", tags=["avoid", "cdc"],
         content="AVOID restructuring 2-FF synchronizers or gray-code CDC "
                 "pointer logic beyond proven P1; every published method "
                 "scored ZERO on async_fifo by breaking this (Alpha-RTL "
                 "Table 4)."),
]


# ── storage + curator (deterministic — no LLM here) ──────────────────────────
def load() -> list[dict]:
    if PLAYBOOK.exists():
        return json.loads(PLAYBOOK.read_text())
    entries = [dict(e, helpful=0, harmful=0,
                    created=time.strftime("%Y-%m-%d")) for e in _SEED]
    save(entries)
    return entries


def save(entries: list[dict]):
    PLAYBOOK.write_text(json.dumps(entries, indent=1))


def retrieve(tags: list[str], sections: list[str] | None = None,
             k: int = 5) -> list[dict]:
    """Bullets matching any tag (or section), best helpful-harmful first."""
    entries = load()
    hits = []
    for e in entries:
        tag_hit = any(t in e["tags"] for t in tags)
        sec_hit = sections and e["section"] in sections
        if tag_hit or sec_hit:
            hits.append(e)
    hits.sort(key=lambda e: -(e["helpful"] - 2 * e["harmful"]))
    avoid = [e for e in entries if e["section"] == "avoid"]
    return hits[:k] + [a for a in avoid if a not in hits][:3]


def vote(entry_id: str, helpful: bool):
    entries = load()
    for e in entries:
        if e["id"] == entry_id:
            e["helpful" if helpful else "harmful"] += 1
    save(entries)


def add_bullet(section: str, tags: list[str], content: str,
               bid: str | None = None) -> str:
    """Curator ADD: append unless a near-duplicate exists (then vote it up)."""
    entries = load()
    for e in entries:
        if difflib.SequenceMatcher(
                None, e["content"], content).ratio() > 0.85:
            e["helpful"] += 1
            save(entries)
            return e["id"]
    bid = bid or f"learned-{len(entries)}-{int(time.time()) % 100000}"
    entries.append(dict(id=bid, section=section, tags=tags, content=content,
                        helpful=1, harmful=0,
                        created=time.strftime("%Y-%m-%d")))
    save(entries)
    return bid


def render(bullets: list[dict]) -> str:
    lines = ["PLAYBOOK (cite bullet ids you rely on):"]
    for e in bullets:
        lines.append(f"  [{e['id']}] ({e['section']}) {e['content']}")
    return "\n".join(lines)
