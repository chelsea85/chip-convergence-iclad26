"""ASU v2 driver — builds ON TOP of the shipped via-bar repair without touching
asu_work/ (the submitted artifact).

Isolation contract:
  * asu_work/agent modules (verify, repairs, asu_agent) are IMPORTED read-only —
    never copied, never edited — so "verify == official scorer" stays a single
    source of truth.
  * Before every run we assert the frozen SHA-256 hashes recorded in
    asu_work/baselines/baseline_table.json (rule deck, evaluator, block
    scripts). Any drift aborts the run.
  * All outputs land under asu_v2/runs/. Nothing writes into asu_work/ or the
    contest tree.
  * Keep-best floor = the SHIPPED via-bar result (asu_work/submission/
    SUMMARY.json): a v2 candidate is only reported as a win if it is eligible,
    rendered-connectivity credible AND strictly better than the shipped FVR.

Run inside the version-exact container (klayout 0.30.1 on PATH); the repo is
mounted at its HOST path so all recorded absolute paths resolve unchanged:

  python3 asu_v2/agent/v2_run.py --blocks Block1,... --passes via-bar --tag parity
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

V2 = Path(__file__).resolve().parent.parent          # asu_v2/
ROOT = V2.parent                                     # DAC_2026_hackathon/
LEGACY = ROOT / "asu_work" / "agent"
ASU = (ROOT / "ICLAD-Hackathon-2026" / "problem-categories"
       / "ICLAD26-ASU-Problems")
TC = ASU / "testcase" / "asap7"

sys.path.insert(0, str(LEGACY))
sys.path.insert(0, str(V2 / "agent"))
import repairs                                       # noqa: E402  (v1, read-only)
import verify                                        # noqa: E402  (v1, read-only)
from asu_agent import _strip_write                   # noqa: E402  (v1, read-only)
import v2_repairs                                    # noqa: E402  (v2 passes)

BLOCKS = ["Block1", "Block2", "Block3", "Block6", "Block7"]


def _sha16(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def load_frozen():
    return json.loads(
        (ROOT / "asu_work" / "baselines" / "baseline_table.json").read_text())


def load_shipped():
    rows = json.loads(
        (ROOT / "asu_work" / "submission" / "SUMMARY.json").read_text())
    return {r["block"]: r for r in rows}


def assert_frozen(block: str, table: dict) -> dict:
    """Abort unless rule deck / evaluator / block script match the hashes
    frozen at submission time — guards against silent input drift."""
    checks = [
        ("rule deck", TC / "asap7.lydrc", table["rule_deck_sha256_16"]),
        ("evaluator", ASU / "evaluator" / "evaluate_repair.py",
         table["evaluator_sha256_16"]),
    ]
    entry = next(b for b in table["blocks"] if b["block"] == block)
    checks.append((f"{block} script",
                   TC / "block" / "layout_script" / f"{block}.py",
                   entry["script_sha256_16"]))
    for name, path, want in checks:
        got = _sha16(path)
        if got != want:
            raise SystemExit(
                f"FROZEN-HASH MISMATCH: {name} {path} = {got}, expected {want}")
    return entry


# ── pass registry ────────────────────────────────────────────────────────────
# Each pass returns a pya snippet appended after the previous ones, so every
# candidate is original + pass1 + pass2 + ... (build-on-top composition).
# v2 passes will be added here; 'via-bar' is the shipped v1 primary.
PASSES = {
    "via-bar": lambda: repairs.via_bar_pass(),
    "via-bar-safe": lambda: v2_repairs.via_bar_safe_pass(),
    "track-shift": lambda: v2_repairs.track_shift_pass(),
    "v1-patch": lambda: v2_repairs.v1_patch_pass(),
    "v0-finger": lambda: v2_repairs.v0_finger_pass(),
}


def laconn_compare(base_gds: Path, cand_gds: Path, out_json: Path) -> dict:
    """Layer-aware electrical partition equality (Rev3 gate): every baseline
    metal polygon is an anchor mapped into the candidate partition; the
    complete anchor partition must match exactly (full SHA-256)."""
    env = os.environ.copy()
    env["CHAR_BASE_GDS"] = str(base_gds)
    env["CHAR_CAND_GDS"] = str(cand_gds)
    env["CHAR_OUT"] = str(out_json)
    subprocess.run(["klayout", "-b", "-r",
                    str(V2 / "agent" / "compare_laconn.py")],
                   env=env, check=True, timeout=3600,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    return json.loads(out_json.read_text())


def vctx(block: str, runs_dir: Path) -> verify.VContext:
    return verify.VContext(
        eval_dir=ASU / "evaluator",
        rule_path=TC / "asap7.lydrc",
        drc_report_json=TC / "block" / "drc_report" / f"{block}.drc.json",
        conn_path=TC / "block" / "connectivity" / f"{block}.json",
        workdir=runs_dir / block,
        case=block)


def run_block(block: str, pass_names: list[str], runs_dir: Path,
              table: dict, shipped: dict) -> dict:
    assert_frozen(block, table)
    ctx = vctx(block, runs_dir)
    original = (TC / "block" / "layout_script" / f"{block}.py").read_text(
        encoding="utf-8")
    orig_nw = _strip_write(original)

    base = verify.measure(original, ctx, tag="baseline", want_conn_sig=True)
    print(f"[v2] {block} baseline: total={base.total} "
          f"fvr={base.final_violation_rate} eligible={base.eligible}",
          flush=True)

    script = orig_nw
    for name in pass_names:
        script = script + "\n" + PASSES[name]()
    cand = verify.measure(script, ctx, tag="+".join(pass_names),
                          want_conn_sig=True)
    # v1's 2D projected net-count is a proxy proven both under-sensitive
    # (missed the 49 shorts) and over-sensitive (flags electrically-safe
    # moves). v2 keeps its ANTI-DELETION area criterion and replaces the
    # count criterion with the layer-aware partition gate (la_equal below).
    sb, sc = base.conn_sig, cand.conn_sig
    if sb and sc and sb.get("conducting_area"):
        drop = (sb["conducting_area"] - sc["conducting_area"]) / sb["conducting_area"]
        credible = drop <= 0.02
        why = f"conducting-area drop {100*drop:.2f}% (anti-deletion)"
        proxy_delta = sc["components"] - sb["components"]
    else:
        credible, why, proxy_delta = False, "signature unavailable", None

    # layer-aware connectivity gate (Rev3): the COMPLETE anchor partition
    # (every baseline metal polygon mapped into the candidate) must be equal
    wd = runs_dir / block
    la = laconn_compare(wd / "baseline" / "out.gds",
                        wd / ("+".join(pass_names)) / "out.gds",
                        wd / "laconn_compare.json")
    la_equal = la["partition_equal"]

    ship = shipped.get(block, {})
    row = {
        "block": block,
        "passes": pass_names,
        "baseline_total": base.total,
        "total": cand.total,
        "fvr": cand.final_violation_rate,
        "repair_rate": cand.repair_rate,
        "eligible": cand.eligible,
        "credible": credible,
        "credible_why": why,
        "conn_proxy_component_delta": proxy_delta,
        "la_components_orig": la["base_components"],
        "la_components_cand": la["cand_components"],
        "la_anchors": la["anchors"],
        "la_uncovered": [la["base_uncovered_components"],
                         la["cand_uncovered_components"]],
        "la_partition_sha256_base": la["base_partition_sha256"],
        "la_partition_sha256_cand": la["cand_partition_sha256"],
        "la_equal": la_equal,
        "per_rule": cand.per_rule,
        "shipped_total": ship.get("final"),
        "shipped_fvr": ship.get("fvr"),
        "parity": cand.total == ship.get("final"),
        "beats_shipped": (cand.eligible and credible
                          and cand.total is not None
                          and ship.get("final") is not None
                          and cand.total < ship["final"]),
    }
    print(f"[v2] {block} {'+'.join(pass_names)}: total={cand.total} "
          f"fvr={cand.final_violation_rate} eligible={cand.eligible} "
          f"credible={credible} la_equal={la_equal} "
          f"({la['base_components']}->{la['cand_components']}) "
          f"shipped={ship.get('final')} parity={row['parity']}", flush=True)
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description="ASU v2 build-on-top driver")
    ap.add_argument("--blocks", default=",".join(BLOCKS))
    ap.add_argument("--passes", default="via-bar",
                    help="comma-separated pass stack, applied in order")
    ap.add_argument("--tag", default="run", help="runs/<tag>/ output dir")
    ap.add_argument("--require", choices=["parity", "beat"], default=None,
                    help="release condition: exit nonzero unless every block "
                         "matches shipped (parity) or strictly beats it (beat)")
    a = ap.parse_args(argv)

    runs_dir = V2 / "runs" / a.tag
    runs_dir.mkdir(parents=True, exist_ok=True)
    table, shipped = load_frozen(), load_shipped()
    pass_names = [p.strip() for p in a.passes.split(",") if p.strip()]
    unknown = [p for p in pass_names if p not in PASSES]
    if unknown:
        raise SystemExit(f"unknown pass(es): {unknown}; have {list(PASSES)}")

    blocks = [b.strip() for b in a.blocks.split(",") if b.strip()]
    if not blocks:
        print("[v2] FAIL: empty block selection", flush=True)
        return 2
    rows = [run_block(b, pass_names, runs_dir, table, shipped) for b in blocks]
    out = runs_dir / "summary.json"
    out.write_text(json.dumps(rows, indent=1))
    print(f"[v2] wrote {out}", flush=True)

    ok = all(r["eligible"] and r["credible"] and r["la_equal"] for r in rows)
    parity = all(r["parity"] for r in rows)
    beat = all(r["beats_shipped"] for r in rows)
    print(f"[v2] all eligible+credible+la_equal: {ok}; parity: {parity}; "
          f"beats shipped: {beat}", flush=True)
    if not ok:
        return 1                       # fail closed on any gate failure
    if a.require == "parity" and not parity:
        return 1
    if a.require == "beat" and not beat:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
