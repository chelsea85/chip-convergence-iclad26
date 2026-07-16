"""Submission-artifact writer — filesystem-only, no contest/config dependency so
it stays unit-testable on its own (see test_emit_replace.py)."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path


def staged_replace(out_dir: Path, files: dict, manifest: dict):
    """Replace out_dir with EXACTLY {files + manifest.json} via a staged dir and a
    backup/rollback swap. Two guarantees:
      1. never MERGES into an existing dir — a re-emit touching fewer files can't
         leave stale files behind (the 2026-07-15 sha512 canonical-mismatch class);
      2. RECOVERABLE — the prior artifact is moved aside first and restored if the
         swap fails, so a failed emit never destroys the last known-good package.
    This is a clean staged replacement with rollback, NOT a single atomic op on a
    non-empty dir (POSIX has none); recoverability is the property that matters."""
    out_dir = Path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=out_dir.parent,
                                    prefix=f".{out_dir.name}.emit-"))
    uniq = staging.name.rsplit("-", 1)[-1]   # unique suffix, no ".emit-" substring
    backup = None
    try:
        for rel, text in files.items():
            dst = staging / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text)
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=1))
        staging.chmod(0o755)                 # mkdtemp is 0700; ship normal perms
        if out_dir.exists() or out_dir.is_symlink():
            backup = out_dir.with_name(f".{out_dir.name}.bak-{uniq}")
            out_dir.rename(backup)           # move known-good aside (atomic)
        try:
            staging.rename(out_dir)          # move new artifact into place (atomic)
        except Exception:
            if backup is not None and not (out_dir.exists() or out_dir.is_symlink()):
                backup.rename(out_dir)       # ROLLBACK: restore known-good
            raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        # drop the backup only once a good artifact is in place; otherwise KEEP it
        if backup is not None and backup.exists() and out_dir.exists():
            shutil.rmtree(backup, ignore_errors=True)
