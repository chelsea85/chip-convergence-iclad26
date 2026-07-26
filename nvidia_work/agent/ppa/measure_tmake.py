"""measure_fn for the tmake/orchestrate path (2026-07-25).

`orchestrate.evaluate_tmake_candidate(..., measure_fn=...)` has always accepted
a measurement callable but NOTHING in the package ever supplied one, so policy
conditions #11 `measurement_valid` and #12 `objective_improves` could never
reach PASS for a tmake IP. This module supplies it.

It deliberately does NOT invent a measurement path: `evaluate.measure()`
already runs the real `harness/measure.sh` synth+STA flow and is already
fail-closed (returns None on nonzero rc or any missing/non-finite metric). All
this module adds is the ADP arithmetic and the MeasurementEvidence wrapper,
using the SAME delay proxy as `objective.Objective` (period - worst setup
slack) so a tmake number is comparable to every other IP's.

FAIL-CLOSED CONTRACT: any doubt -> ok=False. `MeasurementEvidence(ok=True)`
rejects non-finite / non-positive adp or base_adp at construction, so a
degenerate measurement cannot be reported as an improvement.

⚠️ INTERPRETING NVDLA's ADP. NVDLA's worst setup slack (-5788 ps on a 30 ns
clock) is dominated by RESET-DISTRIBUTION paths that the SDC intends to
false-path (Codex preflight review, 2026-07-20: "do NOT optimize this WNS").
The delay half of ADP is therefore partly a constraint artifact, not a
datapath opportunity. AREA is the trustworthy half. Callers should report
area and ADP separately and not treat an ADP delta alone as a real win.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

from . import contract as C
from . import evaluate as E
from . import policy as P


_MEASURE_PROVIDERS: dict[str, object] = {}


def register_measure_provider(ip: str, provider):
    """Bind one canonical tmake measurement provider per IP.

    Dispatch remains fail-closed until both this provider and a canonical gate
    plan are registered.  Duplicate registration is rejected so a later
    import cannot silently replace the scoring recipe.
    """
    if not ip or not callable(provider):
        raise C.ContractError(
            "measure provider requires a nonempty IP and callable")
    if ip in _MEASURE_PROVIDERS:
        raise C.ContractError(
            f"tmake measure provider for {ip!r} already registered")
    _MEASURE_PROVIDERS[ip] = provider
    return provider


def get_measure_provider(ip: str):
    return _MEASURE_PROVIDERS.get(ip)


def _reset_measure_providers():
    """TEST-ONLY."""
    _MEASURE_PROVIDERS.clear()


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")
                   ).encode()).hexdigest()


def _finite_pos(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and v > 0)


def absolute_adp(ppa: dict, period_ps: float) -> float | None:
    """area x (period - worst setup slack). Same delay proxy as
    objective.Objective.delay_ps, so tmake ADP is comparable to every other
    IP's. None if inputs are unusable."""
    if not ppa or not _finite_pos(period_ps):
        return None
    area, setup = ppa.get("area"), ppa.get("setup")
    if not _finite_pos(area):
        return None
    if not (isinstance(setup, (int, float)) and not isinstance(setup, bool)
            and math.isfinite(setup)):
        return None
    delay = period_ps - setup          # slack may be negative -> larger delay
    if not _finite_pos(delay):
        return None
    return area * delay


def make_measure_fn(base_ppa: dict, period_ps: float, *, label: str = "tmk",
                    record: list | None = None):
    """Build a measure_fn(ws, design_inputs) -> P.MeasurementEvidence.

    `base_ppa` is the PRISTINE baseline measurement (evaluate.baseline(ip)
    ["ppa"]); `period_ps` the IP's SDC clock period. If `record` is given, the
    raw candidate ppa dict is appended to it so the caller can report area and
    delay separately from the ADP scalar (see the module docstring warning).
    """
    if not isinstance(label, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", label):
        raise C.ContractError(
            "tmake measurement label must be a bounded safe token")
    base_adp = absolute_adp(base_ppa, period_ps)

    def measure_fn(ws, design_inputs):
        # design_inputs is the contract-revalidated DesignInputs; measure.sh
        # reads the workspace the receipt was frozen against, so we do not
        # re-derive paths from it -- we only note its digest for the evidence
        # ref so a measurement is bound to the inputs it measured.
        try:
            # Bind the complete DesignInputs identity (top, ordered sources,
            # includes/defines/filelist and manifest), not only the leaf-file
            # manifest root.
            di_digest = design_inputs.digest()
        except (AttributeError, C.ContractError):
            di_digest = ""
        ppa = E.measure(ws, label=label)          # already fail-closed -> None
        measure_fn.last_ppa = ppa
        if record is not None:
            record.append(ppa)
        cand_adp = absolute_adp(ppa, period_ps) if ppa else None
        ok = (C._is_sha256(di_digest)
              and _finite_pos(cand_adp) and _finite_pos(base_adp))
        ref = _digest({"schema": "tmake-measurement-v1",
                       "inputs": di_digest, "label": label,
                       "period_ps": period_ps,
                       "baseline_ppa": base_ppa if ok else None,
                       "ppa": ppa if ok else None,
                       "adp": cand_adp if ok else None,
                       "base_adp": base_adp if ok else None})
        if not ok:
            # never report partial numbers: policy sees ok=False and
            # measurement_valid / objective_improves stay FAIL.
            return P.MeasurementEvidence(ok=False, adp=None, base_adp=None,
                                         ref=ref)
        return P.MeasurementEvidence(ok=True, adp=cand_adp,
                                     base_adp=base_adp, ref=ref)

    measure_fn.last_ppa = None
    return measure_fn
