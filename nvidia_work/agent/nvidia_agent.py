#!/usr/bin/env python3
"""Chip Convergence — NVIDIA RTL PPA-optimization agent (contest entry point).

The NVIDIA problem is open (no info.json runner): build an agent on Vertex AI
that rewrites an IP's RTL to improve PPA, verified functionally + by equivalence.
This is the clean, documented entry point over our staged coordinate-descent
optimizer (`ppa.controller`), preset with the defaults that produced our results.

Usage
-----
    # real campaign (Vertex Express; needs EXPRESS_MODE_KEY, Docker + ASAP7):
    python3 nvidia_agent.py --ip sha512
    #   -> runs the staged optimizer, writes the best VERIFIED RTL (delta only)
    #      + manifest.json to submission/sha512/

    # offline smoke (no model / no network, replays a proven variant):
    python3 nvidia_agent.py --ip async_fifo --model stub --stub-replay exp1_graycomb

Options mirror `python3 -m ppa.controller` (which remains available for full
control); this wrapper just fixes the contest-appropriate defaults:
staged diagnosis-driven descent, k=6 then 4, 20-proposal budget, fresh pool,
read-only-grounding context, emit best-verified delta.

Evaluation contract (README.md / AgentSetup.md): the organizers run the agent
with Vertex AI to meter LLM calls/tokens, then (1) check functional correctness
with the existing testbenches and (2) measure PPA after Yosys. Our agent only
emits candidates that passed verification at acceptance; see each manifest's
`verification_per_layer` + `assurance` for the exact level reached.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ppa.config import IPS
from ppa.proposer import make_model
from ppa import controller


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="NVIDIA RTL PPA-optimization agent (staged optimizer)")
    ap.add_argument("--ip", required=True,
                    help="IP name (sha512, async_fifo, aes, prim, kmac, "
                         "ascon, NVDLA) or a path to auto-discover")
    ap.add_argument("--model", default="vertex",
                    choices=["vertex", "endpoint", "stub"],
                    help="vertex (contest eval), endpoint (HTTP), stub (offline)")
    ap.add_argument("--emit-best", metavar="DIR", default=None,
                    help="output dir for the best verified RTL + manifest "
                         "(default: ../submission/<ip>)")
    # staged-optimizer knobs (contest defaults preset; override if needed)
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--k-first", type=int, default=6)
    ap.add_argument("--max-calls", type=int, default=20)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--model-name", default="gemini-3-flash-preview")
    ap.add_argument("--key-env", default=None,
                    help="env var holding the API key (auto-detected otherwise)")
    ap.add_argument("--endpoint", default="http://127.0.0.1:8080")
    ap.add_argument("--fence", choices=["on", "off"], default="off")
    ap.add_argument("--focus", default=None,
                    help="comma-separated file basenames to target")
    ap.add_argument("--stub-replay", action="append", default=[],
                    help="(stub) proven-variant dirs to replay")
    a = ap.parse_args(argv)

    # resolve / auto-discover the IP
    ip = a.ip
    if ip not in IPS:
        from ppa.discover import get_spec, register
        spec = get_spec(ip)
        register(spec)
        ip = spec.name
        print(f"[discover] onboarded '{ip}': {len(spec.sources)} sources")

    out = a.emit_best or str(Path(__file__).resolve().parent.parent /
                             "submission" / ip)

    # staged diagnosis-driven descent for the real model; the offline stub
    # REPLAYS a proven variant, which needs the full-context (non-staged) path.
    if a.model == "stub":
        model = make_model("stub",
                           replay_dirs=[Path(d) for d in a.stub_replay])
        diagnose, fresh = "off", False
    elif a.model == "endpoint":
        model = make_model("endpoint", endpoint=a.endpoint,
                           model_name=a.model_name)
        diagnose, fresh = "on", True
    else:
        model = make_model("vertex", model_name=a.model_name,
                           temperature=0.2, top_p=0.6, key_env=a.key_env)
        diagnose, fresh = "on", True

    controller.run(
        ip, a.rounds, a.k, model,
        mode="pareto", workers=a.workers, max_calls=a.max_calls,
        diagnose=diagnose, grounding="on", stage_batch=1, fresh_pool=fresh,
        k_first=a.k_first, fence=(a.fence == "on"),
        focus=[s.strip() for s in a.focus.split(",")] if a.focus else None,
        emit_best=out)
    print(f"[nvidia_agent] done — best verified RTL + manifest in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
