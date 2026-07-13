#!/usr/bin/env python3
"""End-to-end test of the RUNNER contract (AGENT_GUIDE.md): start the mock
model endpoint, write an info.json exactly as the contest runner would,
invoke `nxp_agent.py <info.json> --model <name>`, and check the contract
outcomes: exit 0, all .v files in output_dir, agent used the endpoint.

  python3 test_runner_mode.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
NXP = HERE.parent
REPO = (HERE.parents[1] / "ICLAD-Hackathon-2026" /
        "problem-categories" / "ICLAD26-NXP-Problems")
WORK = NXP / "agent_out/tmp/runner_test"

EXPECTED_V = 9        # 8 IPs + secure_periph_soc.v


def main() -> int:
    if WORK.exists():
        shutil.rmtree(WORK)
    out_dir, tmp_dir = WORK / "result", WORK / "temp"
    out_dir.mkdir(parents=True), tmp_dir.mkdir(parents=True)

    ep = subprocess.Popen([sys.executable, str(HERE / "mock_endpoint.py")],
                          stdout=subprocess.PIPE, text=True)
    failures = 0
    try:
        port = ep.stdout.readline().strip()
        endpoint = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(endpoint + "/health", timeout=10) as r:
            ok = r.status == 200
        print(f"[{'PASS' if ok else 'FAIL'}] mock endpoint /health")
        failures += 0 if ok else 1

        info = {
            "run_id": "chip_convergence_test",
            "model": "gemini-2.0-flash-exp",
            "model_endpoint": endpoint,
            "problem": "easy",
            # runner-doc quirk under test: names .md, only .html ships
            "architecture_doc": str(REPO / "problems/easy/docs/architecture.md"),
            "tb_skeleton": str(REPO / "problems/easy/tb/tb_top_skeleton.v"),
            "rtl_gen_lib": str(REPO / "rtl_gen_lib"),
            "output_dir": str(out_dir),
            "temp_dir": str(tmp_dir),
            "usage_path": str(WORK / "usage.json"),
        }
        info_path = WORK / "info.json"
        info_path.write_text(json.dumps(info, indent=2))

        t0 = time.time()
        r = subprocess.run(
            [sys.executable, str(HERE / "nxp_agent.py"), str(info_path),
             "--model", "gemini-2.0-flash-exp"],
            capture_output=True, text=True, timeout=600)
        dt = time.time() - t0

        checks = [
            ("agent exit code 0", r.returncode == 0),
            (f"{EXPECTED_V} .v files in output_dir",
             len(list(out_dir.glob("*.v"))) == EXPECTED_V),
            ("gate 30/30 in agent output", "30/30 PASS" in r.stdout),
            ("model calls went to endpoint", "model calls:" in r.stdout),
            ("ledger written to temp_dir", (tmp_dir / "ledger.jsonl").is_file()),
        ]
        for name, ok in checks:
            print(f"[{'PASS' if ok else 'FAIL'}] {name}")
            failures += 0 if ok else 1
        if failures:
            print("--- agent stdout tail ---")
            print(r.stdout[-1200:])
            print(r.stderr[-800:])
        print(f"runner-mode e2e: {6-failures}/6 PASS ({dt:.1f}s)")
    finally:
        ep.terminate()
    return failures


if __name__ == "__main__":
    sys.exit(main())
