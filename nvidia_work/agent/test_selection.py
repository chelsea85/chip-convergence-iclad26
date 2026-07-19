#!/usr/bin/env python3
"""Regression for assurance-aware canonical selection (ppa.controller._canonical_best).

Locks the 2026-07-19 ascon findings AND the re-review integration bug:
  - an LEC-INCONCLUSIVE candidate must NEVER be canonical over an LEC-PROVEN one;
  - the selector must search the FULL POOL, not the Pareto frontier — a PROVEN
    candidate can be PPA-dominated and EVICTED from the frontier by an unproven one
    (the real-frontier test below reproduces exactly that eviction);
  - if no proven improvement exists, the selector returns None (caller ships baseline).

Run: python3 test_selection.py   (exit 0 = pass)
"""
from ppa import controller as C
from ppa.objective import Objective, ParetoFrontier

# The exact ascon shape: the INVALID candidate dominates the PROVEN one on all three
# Pareto dims (lower area, better setup, lower power) — so a frontier-only search
# loses the proven candidate.
BASE   = {"area": 1789.77, "setup": -430.14, "power": 0.0184, "cells": 12295}
PROVEN = {"area": 1801.05, "setup": -415.85, "power": 0.0183, "cells": 12386}
BROKEN = {"area": 1794.26, "setup": -411.18, "power": 0.0182, "cells": 12031}


class _S:                                    # DesignState-like
    def __init__(self, cid, ppa): self.cid, self.ppa = cid, ppa


class _Pool:                                 # DesignPool-like (.states)
    def __init__(self, states): self.states = {s.cid: s for s in states}


def _obj(): return Objective(mode="pareto", clk_period_ps=1000.0)


def _patch(lecs):
    orig = C._verify_status
    C._verify_status = lambda ip, cid: {"lec": lecs.get(cid)}
    return orig


def test_pool_selector_prefers_proven_over_lower_adp_inconclusive():
    pool = _Pool([_S("baseline", BASE), _S("proven", PROVEN), _S("broken", BROKEN)])
    orig = _patch({"proven": "PROVEN", "broken": "INCONCLUSIVE"})
    try:
        best = C._canonical_best("x", pool, _obj(), BASE)
    finally:
        C._verify_status = orig
    assert best and best["cid"] == "proven", best


def test_real_frontier_evicts_but_pool_selector_recovers():
    # INTEGRATION: exercise the real ParetoFrontier so dominance eviction actually
    # happens (the bug the synthetic-frontier test missed).
    fr = ParetoFrontier()
    fr.offer("proven", PROVEN, {})
    fr.offer("broken", BROKEN, {})
    in_fr = [e["cid"] for e in fr.entries]
    assert "proven" not in in_fr, f"expected proven to be Pareto-evicted; frontier={in_fr}"
    pool = _Pool([_S("baseline", BASE), _S("proven", PROVEN), _S("broken", BROKEN)])
    orig = _patch({"proven": "PROVEN", "broken": "INCONCLUSIVE"})
    try:
        best = C._canonical_best("x", pool, _obj(), BASE)
    finally:
        C._verify_status = orig
    assert best and best["cid"] == "proven", f"pool selector must recover the evicted proven cand: {best}"


def test_no_proven_improvement_returns_none():
    pool = _Pool([_S("baseline", BASE), _S("u", {"area": 100, "setup": 500, "power": 0.001})])
    orig = _patch({"u": "INCONCLUSIVE"})
    try:
        assert C._canonical_best("x", pool, _obj(), BASE) is None
    finally:
        C._verify_status = orig


def test_experimental_best_excludes_baseline_and_nonimprovement():
    # Codex 2026-07-19 P1: a baseline-only campaign must NOT record baseline (or any
    # non-improvement) as experimental_best.
    obj = _obj()
    orig = _patch({"broken": "INCONCLUSIVE", "proven": "PROVEN"})
    try:
        # baseline-only campaign -> None
        assert C._experimental_best("x", {"cid": "baseline", "ppa": BASE}, None, obj, BASE) is None
        # a non-improvement (adp >= 1.0) -> None
        worse = {"cid": "worse", "ppa": {"area": 9999, "setup": -9999, "power": 9.0}}
        assert C._experimental_best("x", worse, None, obj, BASE) is None
        # a genuine improving unproven candidate (no proven) -> recorded
        exp = C._experimental_best("x", {"cid": "broken", "ppa": BROKEN}, None, obj, BASE)
        assert exp and exp["cid"] == "broken" and exp["lec"] == "INCONCLUSIVE", exp
        # demoted in favour of a proven winner -> recorded
        exp2 = C._experimental_best("x", {"cid": "broken", "ppa": BROKEN},
                                    {"cid": "proven", "ppa": PROVEN}, obj, BASE)
        assert exp2 and exp2["cid"] == "broken", exp2
        # ppa_best IS the canonical winner -> None
        assert C._experimental_best("x", {"cid": "proven", "ppa": PROVEN},
                                    {"cid": "proven", "ppa": PROVEN}, obj, BASE) is None
    finally:
        C._verify_status = orig


if __name__ == "__main__":
    test_pool_selector_prefers_proven_over_lower_adp_inconclusive()
    test_real_frontier_evicts_but_pool_selector_recovers()
    test_no_proven_improvement_returns_none()
    test_experimental_best_excludes_baseline_and_nonimprovement()
    print("test_selection: 4/4 PASS")
