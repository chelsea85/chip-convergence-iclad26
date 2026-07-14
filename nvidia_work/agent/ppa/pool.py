"""Design-state pool with Thompson-sampling parent selection (AB-MCTS-A Beta).

Alpha-RTL's single biggest ablation: branching from a sampled pool member
(-45.3% ADP) vs always from the incumbent best (-13.3%). Every gate-passing
measured variant joins the pool; each iteration Thompson-samples which state
to mutate next. Each state keeps a Beta(1+wins, 1+losses) posterior fed by
the rewards of ITS CHILDREN — states whose offspring improve get exploited,
stale ones decay toward exploration. A virtual GEN arm with a wide prior
keeps fresh-strategy generation competitive (wider-vs-deeper).

Variants' RTL is persisted under agent/variants/<ip>/<cid>/ so the pool
survives restarts.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from .config import AGENT, IPS

VARIANTS = AGENT / "variants"


@dataclass
class DesignState:
    cid: str
    ppa: dict
    parent: str | None = None
    strategy: str = ""
    wins: float = 0.0      # sum of child rewards r in [0,1]
    losses: float = 0.0    # sum of (1 - r)

    def sample(self, rng: random.Random) -> float:
        return rng.betavariate(1 + self.wins, 1 + self.losses)


class DesignPool:
    def __init__(self, ip: str, seed: int = 0, fresh: bool = False):
        self.ip = ip
        self.rng = random.Random(seed)
        self.states: dict[str, DesignState] = {}
        self._dir = VARIANTS / ip
        self._meta = self._dir / "pool.json"
        # fresh=True: start from baseline only (ignore prior banked wins) — for
        # clean coordinate-descent demos where pre-banked wins would dominate
        # parent selection.
        if not fresh:
            self._load()

    # ── persistence ──────────────────────────────────────────────────────────
    def _load(self):
        if self._meta.exists():
            for d in json.loads(self._meta.read_text()):
                self.states[d["cid"]] = DesignState(**d)

    def _save(self):
        self._dir.mkdir(parents=True, exist_ok=True)
        self._meta.write_text(json.dumps(
            [vars(s) for s in self.states.values()], indent=1))

    def files_of(self, cid: str) -> dict[str, str]:
        """Reload a pool member's RTL (repo-relative path -> content)."""
        spec = IPS[self.ip]
        d = self._dir / cid
        manifest = d / "files.json"
        if manifest.exists():
            return {rel: (d / name).read_text()
                    for name, rel in json.loads(manifest.read_text()).items()}
        return {f"{spec.rtl_dir}/{f.name}": f.read_text()
                for f in sorted(d.glob("*.v"))}

    # ── pool ops ─────────────────────────────────────────────────────────────
    def add(self, cid: str, ppa: dict, files: dict[str, str],
            parent: str | None, strategy: str = ""):
        if cid in self.states:
            return
        self.states[cid] = DesignState(cid=cid, ppa=ppa, parent=parent,
                                       strategy=strategy)
        d = self._dir / cid
        d.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            (d / Path(rel).name).write_text(text)
        (d / "files.json").write_text(json.dumps(
            {Path(rel).name: rel for rel in files}, indent=1))
        self._save()

    def backup(self, parent_cid: str | None, reward: float):
        """Credit a child's reward to its parent (and half to grandparent)."""
        depth = 0
        cid = parent_cid
        while cid and cid in self.states and depth < 2:
            s = self.states[cid]
            w = reward * (0.5 ** depth)
            s.wins += w
            s.losses += (1 - reward) * (0.5 ** depth)
            cid = s.parent
            depth += 1
        self._save()

    def select_parent(self) -> tuple[str, str]:
        """Thompson sample over states + a virtual GEN arm.

        Returns (cid, mode): mode 'deepen' = mutate the sampled state further
        along its own strategy line; 'generate' = fresh strategy from the
        sampled state (GEN arm won)."""
        assert self.states, "pool empty — add baseline first"
        best_cid, best_theta = None, -1.0
        for s in self.states.values():
            th = s.sample(self.rng)
            if th > best_theta:
                best_cid, best_theta = s.cid, th
        gen_theta = self.rng.betavariate(1, 1)     # wide uninformed prior
        if gen_theta > best_theta:
            return best_cid, "generate"
        return best_cid, "deepen"

    def reward_from_eval(self, status: str, adp_ratio: float | None) -> float:
        """Map an evaluation outcome to r in [0,1] for backup (0.5 = neutral,
        >0.5 = improved ADP, gate failures land low)."""
        if status in ("lint-fail", "compile-fail"):
            return 0.05
        if status in ("gate-fail", "dualsim-fail"):
            return 0.10
        if status in ("proxy-reject", "duplicate", "synth-fail"):
            return 0.30
        if adp_ratio is None:
            return 0.5
        return max(0.0, min(1.0, 0.5 + 0.5 * (1.0 - adp_ratio) / 0.25))

    def best(self, key=None) -> DesignState:
        key = key or (lambda s: (s.ppa.get("setup") or -1e9))
        return max(self.states.values(), key=key)
