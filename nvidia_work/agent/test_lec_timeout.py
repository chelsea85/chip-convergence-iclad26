#!/usr/bin/env python3
"""Regression tests for the LEC watchdog/reaping boundary.

No Docker or EDA tools are invoked. A real local sleeping subprocess proves
that the verdict returns promptly; Docker lifecycle behavior is exercised
with a mocked subprocess boundary.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ppa import config as CFG                                      # noqa: E402
from ppa import controller as CTRL                                 # noqa: E402
from ppa import evaluate as E                                      # noqa: E402
from ppa import lec_diagnostic as LD                               # noqa: E402
from ppa import verify as V                                        # noqa: E402
from ppa.config import IPS, IPSpec                                  # noqa: E402

PASS = FAIL = 0


def check(name, ok):
    global PASS, FAIL
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    PASS, FAIL = PASS + int(bool(ok)), FAIL + int(not ok)


class TmpWs:
    def __init__(self, root: Path, spec=None, runner=None):
        self.root = root
        self.spec = spec
        self._runner = runner

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def run(self, cmd, timeout):
        return self._runner(cmd, timeout)


def sleeping_runner(cmd, timeout):
    return subprocess.run(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        capture_output=True, text=True, timeout=timeout)


def main():
    with tempfile.TemporaryDirectory(prefix="lec_timeout_") as td:
        root = Path(td)

        # Central/tmake/release adapter: a genuinely sleeping child must be
        # killed by subprocess timeout and become an ineligible timeout proof.
        t0 = time.monotonic()
        pr, log = V.run_lec_v2_script(
            TmpWs(root), "read_verilog -sv x.v\n",
            runner=sleeping_runner, timeout=0.08)
        elapsed = time.monotonic() - t0
        check("mocked hanging LEC is killed promptly",
              elapsed < 2.0)
        check("central LEC timeout -> INCONCLUSIVE(timeout)",
              pr.verdict == "INCONCLUSIVE" and pr.reason == "timeout"
              and pr.rc is None and "TIMEOUT after 0.08s" == log)

        # Legacy campaign adapter must use the same process boundary and the
        # per-IP timeout value. Keep script construction real; mock only the
        # source reader and timeout policy.
        spec = IPSpec(
            name="timeout_legacy", top="top", rtl_dir="rtl",
            sources=("rtl/top.v",), syn_dir="syn", gate_dir=".",
            gate_cmd="true", subtrees=("rtl",))
        seen = {}

        def legacy_runner(cmd, timeout):
            seen["timeout"] = timeout
            raise subprocess.TimeoutExpired(cmd, timeout)

        orig_source, orig_timeout = V.pristine_source, V._lec_timeout
        try:
            V.pristine_source = lambda ip, rel: \
                "module top(input a, output y); assign y=a; endmodule\n"
            V._lec_timeout = lambda s: 37
            status, note = V.lec(TmpWs(root, spec, legacy_runner))
        finally:
            V.pristine_source, V._lec_timeout = orig_source, orig_timeout
        check("legacy campaign LEC applies configured timeout",
              seen.get("timeout") == 37)
        check("legacy campaign timeout is ineligible, never ERROR/PROVEN",
              status == "INCONCLUSIVE"
              and "exceeded budget (37s)" in note)

        # The diagnostic ladder also routes through the shared boundary.
        def diag_runner(cmd, timeout):
            raise subprocess.TimeoutExpired(cmd, timeout)

        rc, out = LD._run(
            TmpWs(root, runner=diag_runner),
            "read_verilog -sv x.v\n", "hang", 19)
        check("diagnostic LEC applies timeout and records it",
              rc is None and out == "TIMEOUT after 19s")

    # LEC memory is serialized even when candidate evaluation has multiple
    # worker threads; other pipeline stages are unaffected.
    active = maximum = 0
    guard = threading.Lock()

    def bounded_runner(cmd, timeout):
        nonlocal active, maximum
        with guard:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.05)
        with guard:
            active -= 1
        return subprocess.CompletedProcess(cmd, 0, "", "")

    threads = [
        threading.Thread(
            target=V.run_lec_command,
            args=(bounded_runner, f"yosys job{i}.ys", 2))
        for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("parallel candidates cannot run overlapping LEC processes",
          maximum == 1)

    # Docker lifecycle: the command contains an independent inner watchdog,
    # a marker is normalized to TimeoutExpired, and the named container is
    # reaped. No real docker call is made.
    calls = []
    orig_run = CFG.subprocess.run

    def inner_timeout_run(args, **kw):
        calls.append((args, kw))
        if args[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(
                args, 124, "", "__ICLAD_CONTAINER_TIMEOUT__ 7s\n")
        return subprocess.CompletedProcess(args, 0, "killed\n", "")

    try:
        CFG.subprocess.run = inner_timeout_run
        try:
            CFG.docker_run("yosys .lec/lec.ys", root=CFG.REPO, timeout=7)
            inner_raised = False
        except subprocess.TimeoutExpired as e:
            inner_raised = e.timeout == 7
    finally:
        CFG.subprocess.run = orig_run
    docker_args, docker_kw = calls[0]
    check("container payload has an independent 7s watchdog",
          "timeout --signal=TERM --kill-after=30s" in docker_args[-4]
          and docker_args[-2] == "7s"
          and docker_kw["timeout"] == 52)
    check("inner watchdog marker raises configured TimeoutExpired",
          inner_raised)
    check("inner timeout reaps the named container",
          len(calls) == 2 and calls[1][0][:2] == ["docker", "kill"]
          and calls[1][0][2] == docker_args[4])

    # Host-client backstop follows the same normalized/reaped behavior.
    calls = []

    def host_timeout_run(args, **kw):
        calls.append((args, kw))
        if args[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(args, kw["timeout"])
        return subprocess.CompletedProcess(args, 0, "killed\n", "")

    try:
        CFG.subprocess.run = host_timeout_run
        try:
            CFG.docker_run("yosys .lec/lec.ys", root=CFG.REPO, timeout=11)
            host_raised = False
        except subprocess.TimeoutExpired as e:
            host_raised = e.timeout == 11
    finally:
        CFG.subprocess.run = orig_run
    check("host watchdog timeout is normalized to configured budget",
          host_raised)
    check("host watchdog also reaps the named container",
          len(calls) == 2 and calls[1][0][:2] == ["docker", "kill"])

    # Current production policies remain explicit.
    check("small legacy LEC budget remains 900s",
          V._lec_timeout(IPS["async_fifo"]) == 900)
    large_spec = IPSpec(
        name="large", top="top", rtl_dir="rtl",
        sources=tuple(f"rtl/m{i}.v" for i in range(40)),
        syn_dir="syn", gate_dir=".", gate_cmd="true", subtrees=("rtl",))
    check("large legacy LEC budget remains capped at 2400s",
          V._lec_timeout(large_spec) == 2400)

    # Future banking manifests must retain the normalized LEC counts rather
    # than only the word PROVEN.
    with tempfile.TemporaryDirectory(prefix="lec_ledger_") as td:
        old_e, old_c = E.LEDGER_DIR, CTRL.LEDGER_DIR
        try:
            E.LEDGER_DIR = CTRL.LEDGER_DIR = Path(td)
            cand = E.Candidate("proofip", {"rtl/top.v": "module top; endmodule"})
            result = E.EvalResult(cand.cid, "measured")
            vr = V.VerifyResult()
            proof_note = ("recipe=nvdla-lec-contract-v2 rc=0 total=17 "
                          "proven=17 unproven=0 reason=fully_proven")
            vr.record("lec", "PROVEN", proof_note)
            E._finish(cand, result, vr, time.time())
            row = json.loads(
                (Path(td) / "proofip.jsonl").read_text().splitlines()[-1])
            retained = CTRL._verify_evidence("proofip", cand.cid)
        finally:
            E.LEDGER_DIR, CTRL.LEDGER_DIR = old_e, old_c
    check("ledger retains normalized LEC recipe/rc/count evidence",
          row["verify_evidence"]["lec"] == proof_note)
    check("emitter evidence lookup recovers retained LEC counts",
          retained.get("lec") == proof_note)

    if "--host" in sys.argv:
        before = subprocess.run(
            ["docker", "ps", "--filter", "name=iclad_",
             "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=30).stdout.splitlines()
        t0 = time.monotonic()
        try:
            CFG.docker_run("sleep 30", root=CFG.REPO, timeout=1)
            host_timed_out = False
        except subprocess.TimeoutExpired as e:
            host_timed_out = e.timeout == 1
        elapsed = time.monotonic() - t0
        after = subprocess.run(
            ["docker", "ps", "--filter", "name=iclad_",
             "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=30).stdout.splitlines()
        check("HOST: real container watchdog expires and reaps",
              host_timed_out and elapsed < 50 and after == before)

    print(f"\ntest_lec_timeout: {PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
