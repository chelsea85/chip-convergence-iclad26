#!/usr/bin/env python3
"""Regression for ppa.staged_replace (the emit-best artifact writer).

Locks in the two properties the 2026-07-15 reviews required:
  1. CLEAN — a re-emit that touches fewer files leaves NO stale files behind
     (the sha512 canonical-mismatch failure class).
  2. RECOVERABLE — if the swap fails mid-way, the prior known-good artifact is
     restored, never destroyed (the "clean but not atomic" follow-up finding).

Run: python3 test_emit_replace.py   (exit 0 = pass)
"""
import json
import shutil
import tempfile
from pathlib import Path

from ppa.emit import staged_replace


def test_clean_removes_stale():
    base = Path(tempfile.mkdtemp())
    try:
        out = base / "sha512"
        out.mkdir()
        (out / "OLD_STALE.v").write_text("stale")
        (out / "manifest.json").write_text('{"old": 1}')
        staged_replace(out, {"src/rtl/core.v": "newcore"}, {"result": "ok"})
        assert not (out / "OLD_STALE.v").exists(), "stale file survived"
        assert (out / "src/rtl/core.v").read_text() == "newcore"
        assert json.loads((out / "manifest.json").read_text())["result"] == "ok"
        # mkdtemp is 0700; the shipped artifact must have normal perms
        assert (out.stat().st_mode & 0o755) == 0o755, "artifact dir not world-readable"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_failed_swap_preserves_known_good():
    base = Path(tempfile.mkdtemp())
    try:
        out = base / "sha512"
        out.mkdir()
        (out / "KNOWN_GOOD.v").write_text("v2")
        (out / "manifest.json").write_text('{"v": 2}')

        orig = Path.rename

        def flaky(self, target):                 # fail ONLY the staging->out swap
            if ".emit-" in self.name and ".bak-" not in self.name:
                raise OSError("injected rename failure")
            return orig(self, target)

        Path.rename = flaky
        try:
            staged_replace(out, {"src/rtl/core.v": "v3"}, {"v": 3})
            raise AssertionError("expected the injected failure to propagate")
        except OSError:
            pass
        finally:
            Path.rename = orig

        assert out.exists(), "destination lost after a failed swap"
        assert (out / "KNOWN_GOOD.v").read_text() == "v2", "known-good content lost"
        leftovers = [p.name for p in base.iterdir() if p.name != "sha512"]
        assert not leftovers, f"temp/backup dirs left behind: {leftovers}"
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    test_clean_removes_stale()
    test_failed_swap_preserves_known_good()
    print("test_emit_replace: 2/2 PASS")
