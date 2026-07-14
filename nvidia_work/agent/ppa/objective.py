"""Pluggable optimization objective — the product-facing PPA dial.

Three modes (see AGENT_UPGRADE_SPEC.md "Internal metric"):
  weighted       Dr. RTL candidate score: 0.5*WNS_n + 0.35*TNS_n + 0.15*Area_n
                 (normalized deltas vs baseline, lower better) + 0.5 penalty
                 when area grows >10%. Weights configurable per axis.
  lexicographic  signoff-style: meet timing first, then area, then power.
  pareto         accept only if no axis regresses beyond epsilon and at least
                 one improves — the safe mode under an unknown contest metric.

Also provides:
  adp_ratio      headline metric (organizer signal): area-delay-product vs
                 baseline, gated on functional pass. delay proxy = clk_period
                 - setup_slack (critical path), so it works for designs that
                 violate timing.
  staged_reward  Alpha-RTL partial-credit score for ranking FAILED candidates
                 (which one is least broken / most worth iterating on).
  ParetoFrontier per-IP archive of non-dominated variants for submission-time
                 selection once the real metric is published.

Axis conventions: `setup` = worst setup slack in ps (higher better); `area`,
`power` lower better. Power is only ever compared as a ratio under our own
flow (OpenSTA absolute power is unreliable cross-flow).
"""
from __future__ import annotations

from dataclasses import dataclass, field


AXES = ("perf", "area", "power")


@dataclass
class Objective:
    mode: str = "pareto"                    # weighted | lexicographic | pareto
    weights: dict = field(default_factory=lambda: {
        "perf": 0.5, "tns": 0.35, "area": 0.15, "power": 0.0})
    # hard constraints
    max_area_growth: float = 0.10           # candidates above this are penalized
    area_penalty: float = 0.5               # Dr. RTL blowup penalty
    epsilon: dict = field(default_factory=lambda: {
        "perf": 1.0,                        # ps of setup slack we treat as noise
        "area": 0.005, "power": 0.02})      # relative noise floors
    lex_order: tuple = ("perf", "area", "power")
    clk_period_ps: float | None = None      # for delay/ADP; per-IP (SDC clock)

    # ── normalized deltas (lower = better on every axis) ─────────────────────
    def _norms(self, cand: dict, base: dict) -> dict:
        n = {}
        # perf: improvement in setup slack, normalized by clock period if
        # known else by 100ps; NEGATIVE when slack improves (lower=better).
        scale = self.clk_period_ps or 100.0
        n["perf"] = -(cand["setup"] - base["setup"]) / scale
        n["tns"] = n["perf"]                # TNS not parsed yet; mirror WNS
        n["area"] = (cand["area"] - base["area"]) / base["area"]
        if base.get("power") and cand.get("power"):
            n["power"] = (cand["power"] - base["power"]) / base["power"]
        else:
            n["power"] = 0.0
        return n

    # ── scores ────────────────────────────────────────────────────────────────
    def score(self, cand: dict, base: dict) -> float:
        """Weighted candidate score, lower is better (Dr. RTL form)."""
        n = self._norms(cand, base)
        s = sum(self.weights.get(k, 0.0) * v for k, v in n.items())
        if n["area"] > self.max_area_growth:
            s += self.area_penalty
        return s

    def delay_ps(self, ppa: dict) -> float:
        """Critical-path proxy: clock period minus worst slack."""
        period = self.clk_period_ps or 0.0
        return period - ppa["setup"]

    def adp_ratio(self, cand: dict, base: dict) -> float | None:
        """Area-delay-product vs baseline (<1 is an improvement)."""
        if not self.clk_period_ps:
            return None
        return ((cand["area"] * self.delay_ps(cand)) /
                (base["area"] * self.delay_ps(base)))

    # ── acceptance ────────────────────────────────────────────────────────────
    def better(self, cand: dict, base: dict) -> tuple[bool, str]:
        """Is `cand` an acceptable improvement over `base`? Both must already
        be gate-passing. Returns (verdict, reason)."""
        n = self._norms(cand, base)
        eps = self.epsilon
        improves = {
            "perf": cand["setup"] > base["setup"] + eps["perf"],
            "area": n["area"] < -eps["area"],
            "power": n["power"] < -eps["power"],
        }
        regresses = {
            "perf": cand["setup"] < base["setup"] - eps["perf"],
            "area": n["area"] > eps["area"],
            "power": n["power"] > eps["power"],
        }

        if self.mode == "pareto":
            # Headline-metric override (2026-07-13, exp6 lesson): the contest
            # metric is ADP-shaped, so a strict ADP win is accepted even when
            # a single axis regresses slightly (exp6: +0.23% area for +73 ps
            # → ADP 0.787→0.743 was being VETOED by pure epsilon-dominance).
            # Power guard: ADP ignores power, so cap its regression.
            adp = self.adp_ratio(cand, base)
            if (adp is not None and adp < 0.995
                    and n["power"] <= eps["power"] * 5):
                return True, f"ADP {adp:.3f} vs parent (headline override)"
            if any(regresses.values()):
                bad = [k for k, v in regresses.items() if v]
                return False, f"regresses {','.join(bad)}"
            if any(improves.values()):
                good = [k for k, v in improves.items() if v]
                return True, f"improves {','.join(good)}, regresses none"
            return False, "no meaningful change"

        if self.mode == "lexicographic":
            # timing gate first: never accept a slack regression while the
            # design violates timing; then walk the priority order.
            for axis in self.lex_order:
                if improves[axis] and not any(
                        regresses[a] for a in self.lex_order[
                            :self.lex_order.index(axis)]):
                    return True, f"lex: improves {axis}"
                if regresses[axis]:
                    return False, f"lex: regresses {axis}"
            return False, "lex: no change"

        # weighted
        s = self.score(cand, base)
        if s < 0:
            return True, f"weighted score {s:.4f} < 0"
        return False, f"weighted score {s:.4f} >= 0"


def staged_reward(status: str, ppa_ratio: float | None = None,
                  n_errors: int = 0, port_binding: bool = False) -> float:
    """Alpha-RTL partial-credit reward. Orders failures for parent selection:
    syntax-fail < gate-fail < measured; measured scales with PPA gain."""
    if status in ("lint-fail", "compile-fail"):
        r = 0.1 / (1 + max(n_errors, 1))
        return r * 0.3 if port_binding else r
    if status in ("gate-fail", "dualsim-fail"):
        return 0.1
    if status in ("proxy-reject", "duplicate", "synth-fail"):
        return 0.3
    if status == "measured" and ppa_ratio:
        return 1.0 + 10.0 * max(0.0, 1.0 / ppa_ratio - 1.0) + 1.0
    return 1.0


# ── Pareto frontier archive ───────────────────────────────────────────────────
def _dominates(a: dict, b: dict) -> bool:
    """a dominates b: no axis worse, at least one better (setup higher=better,
    area/power lower=better)."""
    ge = (a["setup"] >= b["setup"] and a["area"] <= b["area"] and
          (a.get("power") or 0) <= (b.get("power") or float("inf")))
    gt = (a["setup"] > b["setup"] or a["area"] < b["area"] or
          (a.get("power") or 0) < (b.get("power") or float("inf")))
    return ge and gt


class ParetoFrontier:
    def __init__(self):
        self.entries: list[dict] = []       # {cid, ppa, meta}

    def offer(self, cid: str, ppa: dict, meta: dict | None = None) -> bool:
        """Add if non-dominated; evict anything it dominates. Returns True if
        the candidate joined the frontier."""
        for e in self.entries:
            if _dominates(e["ppa"], ppa):
                return False
        self.entries = [e for e in self.entries
                        if not _dominates(ppa, e["ppa"])]
        self.entries.append({"cid": cid, "ppa": ppa, "meta": meta or {}})
        return True

    def best(self, objective: Objective, base: dict) -> dict | None:
        if not self.entries:
            return None
        return min(self.entries, key=lambda e: objective.score(e["ppa"], base))
