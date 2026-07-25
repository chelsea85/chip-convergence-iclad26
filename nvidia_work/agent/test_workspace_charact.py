#!/usr/bin/env python3
"""P0-4 checkpoint-1c: PERMANENT Direct/Sv2v workspace characterizations
(re-review SS5.5) - the disposable review-time probes, now owned by the repo.

Covers, against the REAL contest tree:
  1. Direct (async_fifo): pristine same-content overlay is byte-identical; a
     real edit lands only in the workspace; repository bytes unchanged.
  2. Sv2v authoritative-generated mode (ascon_core.v): provided .v is
     authoritative, byte-identical when same-content; no regeneration runs.
  3. Sv2v source-edit mode (prim_ascon_round.sv): same-content .sv overlay
     regenerates the mapped generated .v byte-identically via HOST sv2v.
     Requires the host `sv2v` binary - when absent this leg reports
     PREREQ-MISSING and the suite exits 3 (distinct non-green outcome, never
     silent success).
Exit: 0 all legs pass; 1 failures; 3 prerequisite missing (leg skipped).
"""
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ppa.config import IPS, REPO                                  # noqa: E402
from ppa.workspace import Workspace, pristine_source              # noqa: E402

PASS = FAIL = 0
PREREQ_MISSING = False


def check(name, ok):
    global PASS, FAIL
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    PASS, FAIL = PASS + int(bool(ok)), FAIL + int(not ok)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def repo_hashes(rels) -> dict:
    return {r: sha(REPO / r) for r in rels}


def direct_characterization():
    spec = IPS["async_fifo"]
    watch = list(spec.sources)
    before = repo_hashes(watch)
    rel = "async_fifo/rtl/fifomem.v"
    same = pristine_source("async_fifo", rel)

    ws = Workspace.create("async_fifo", {rel: same}, tag="charact_same")
    try:
        check("direct: same-content overlay byte-identical in workspace",
              (ws.root / rel).read_text() == same)
    finally:
        ws.destroy()

    edited = same + "// charact edit\n"
    ws = Workspace.create("async_fifo", {rel: edited}, tag="charact_edit")
    try:
        check("direct: real edit lands in workspace only",
              (ws.root / rel).read_text() == edited
              and sha(REPO / rel) == before[rel])
    finally:
        ws.destroy()
    check("direct: repository bytes unchanged", repo_hashes(watch) == before)


def sv2v_authoritative_characterization():
    spec = IPS["ascon"]
    rel = f"{spec.rtl_dir}/ascon_core.v"
    watch = [rel, "opentitan/hw/ip/ascon/rtl/ascon_core.sv"]
    before = repo_hashes(watch)
    same = pristine_source("ascon", rel)

    ws = Workspace.create("ascon", {rel: same}, tag="charact_auth")
    try:
        check("sv2v mode (b): authoritative generated .v byte-identical, "
              "no regeneration",
              (ws.root / rel).read_text() == same)
    finally:
        ws.destroy()
    check("sv2v mode (b): repository bytes unchanged",
          repo_hashes(watch) == before)


def sv2v_source_edit_characterization():
    global PREREQ_MISSING
    if shutil.which("sv2v") is None:
        print("PREREQ-MISSING: host `sv2v` binary not found - sv2v "
              "source-edit regeneration leg NOT characterized (run on the "
              "macOS host)")
        PREREQ_MISSING = True
        return
    spec = IPS["ascon"]
    sv = "opentitan/hw/ip/prim/rtl/prim_ascon_round.sv"
    gen = f"{spec.rtl_dir}/prim_ascon_round.v"
    before = repo_hashes([sv, gen])
    same = pristine_source("ascon", sv)

    ws = Workspace.create("ascon", {sv: same}, tag="charact_svedit")
    try:
        check("sv2v mode (a): same-content .sv regenerates mapped .v "
              "byte-identically",
              sha(ws.root / gen) == before[gen])
    finally:
        ws.destroy()
    check("sv2v mode (a): repository bytes unchanged",
          repo_hashes([sv, gen]) == before)


def main():
    if not REPO.is_dir():
        print("PREREQ-MISSING: contest repo not present at", REPO)
        return 3
    direct_characterization()
    sv2v_authoritative_characterization()
    sv2v_source_edit_characterization()
    print(f"\ntest_workspace_charact: {PASS}/{PASS + FAIL} PASS"
          + (" (PREREQ-MISSING: sv2v leg skipped)" if PREREQ_MISSING else ""))
    if FAIL:
        return 1
    return 3 if PREREQ_MISSING else 0


if __name__ == "__main__":
    sys.exit(main())
