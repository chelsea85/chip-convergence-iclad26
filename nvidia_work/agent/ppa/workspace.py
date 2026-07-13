"""Per-candidate scratch workspaces.

Each candidate gets a private copy of the IP's subtree(s), overlaid with the
candidate's rewritten files, so N candidates can gate/synth/measure in parallel
without touching the cloned contest repo. Heavy synthesis outputs are excluded
from the copy and recreated empty.
"""
from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from pathlib import Path

from .config import IPS, REPO, WORK, IPSpec, docker_run

_COPY_EXCLUDES = ("syn_results*", "reports")


class RegenError(RuntimeError):
    """sv2v regeneration of an edited .sv failed."""


class Workspace:
    def __init__(self, spec: IPSpec, root: Path, tag: str):
        self.spec = spec
        self.root = root
        self.tag = tag

    # ── lifecycle ────────────────────────────────────────────────────────────
    @classmethod
    def create(cls, ip: str, cand_files: dict[str, str] | None = None,
               tag: str = "") -> "Workspace":
        """cand_files maps repo-relative paths (must be inside spec.rtl_dir)
        to full file contents. None/empty -> pristine baseline workspace."""
        spec = IPS[ip]
        tag = tag or uuid.uuid4().hex[:8]
        root = WORK / ip / f"{time.strftime('%m%d')}_{tag}"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)

        for sub in spec.subtrees:
            dst = root / sub
            dst.parent.mkdir(parents=True, exist_ok=True)
            # APFS copy-on-write clone: ~2s even for the 700M opentitan tree
            subprocess.run(["cp", "-Rc", str(REPO / sub), str(dst)],
                           check=True, capture_output=True)
        # purge stale synth outputs + build dirs (clones are ours to mutate)
        for pat in _COPY_EXCLUDES:
            for p in (root / spec.syn_dir).glob(pat):
                shutil.rmtree(p, ignore_errors=True)
        for rel in spec.clean_dirs:
            shutil.rmtree(root / rel, ignore_errors=True)
        (root / spec.syn_dir / "syn_results").mkdir(parents=True, exist_ok=True)
        (root / spec.syn_dir / "reports").mkdir(parents=True, exist_ok=True)

        # workspace-local harness fixes (repo copy stays pristine):
        # run_sta.tcl uses -endpoint_count N, which OpenSTA treats as N paths
        # through ONE worst endpoint; -group_path_count N gives the top-N
        # distinct endpoints that STA-localized feedback needs.
        sta_tcl = root / spec.syn_dir / "run_sta.tcl"
        if sta_tcl.exists():
            sta_tcl.write_text(sta_tcl.read_text().replace(
                "-endpoint_count ", "-group_path_count "))
        # aes ships a fully-redundant generated/all_modules.v aggregate that
        # re-defines every per-module file -> yosys ERROR under SKIP_SV2V=1
        # (masked by run_syn.sh's success banner). Verified 84/84 duplicated,
        # none unique; syn.tcl globs generated/*.v so drop it in the clone.
        agg = root / spec.syn_dir / "generated" / "all_modules.v"
        if agg.exists() and len(list(agg.parent.glob("*.v"))) > 1:
            agg.unlink()

        ws = cls(spec, root, tag)
        if cand_files:
            ws.overlay(cand_files)
        return ws

    def overlay(self, cand_files: dict[str, str]):
        # modules whose generated .v is supplied directly (hand-authored) skip
        # sv2v regen — the provided .v is authoritative for synth/LEC while the
        # matching .sv still drives the Verilator gate. Sidesteps sv2v-version
        # name mangling of parameterized submodules.
        provided_v = {Path(rel).stem for rel in cand_files
                      if str(Path(rel).parent) == self.spec.rtl_dir
                      and rel.endswith(".v")}
        touched_sv = []
        for rel, text in cand_files.items():
            rel_path = Path(rel)
            assert not rel_path.is_absolute() and ".." not in rel_path.parts, \
                f"bad candidate path {rel}"
            assert (str(rel_path.parent) == self.spec.rtl_dir or
                    rel in self.spec.sv_sources), \
                f"candidate file {rel} outside editable set"
            (self.root / rel_path).write_text(
                text if text.endswith("\n") else text + "\n")
            if rel in self.spec.sv_sources and Path(rel).stem not in provided_v:
                touched_sv.append(rel)
        if touched_sv:
            self._regen_sv2v(touched_sv)

    def _regen_sv2v(self, touched_sv: list[str]):
        """Regenerate generated/<module>.v for edited .sv modules with HOST
        sv2v, using the -I dirs + package files from the IP's filelist —
        byte-identical to the repo flow (validated on prim_ascon_round)."""
        spec = self.spec
        syn_dir = self.root / spec.syn_dir
        incs, pkgs = [], []
        for line in (self.root / spec.filelist).read_text().splitlines():
            line = line.strip()
            if line.startswith("-I"):
                incs.append(line[2:].strip())
            elif line.endswith("_pkg.sv") and not line.startswith("#"):
                pkgs.append(line)
        for rel in touched_sv:
            module = Path(rel).stem
            src = None
            for line in (self.root / spec.filelist).read_text().splitlines():
                line = line.strip()
                if line.endswith(f"/{module}.sv") or line == f"{module}.sv":
                    src = line
                    break
            if src is None:
                raise RegenError(f"{module}.sv not in {spec.filelist}")
            out = syn_dir / "generated" / f"{module}.v"
            r = subprocess.run(
                ["sv2v", "--define=SYNTHESIS", "--define=YOSYS",
                 *[f"-I{i}" for i in incs], *pkgs, src],
                cwd=syn_dir, capture_output=True, text=True, timeout=300)
            if r.returncode != 0 or not r.stdout.strip():
                raise RegenError(f"sv2v {module}: {r.stderr[:800]}")
            out.write_text(r.stdout)

    def destroy(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # ── execution ────────────────────────────────────────────────────────────
    def run(self, cmd: str, timeout: int = 3600) -> subprocess.CompletedProcess:
        return docker_run(cmd, root=self.root, timeout=timeout)

    # ── file access ──────────────────────────────────────────────────────────
    def read(self, rel: str) -> str:
        return (self.root / rel).read_text()

    def write(self, rel: str, text: str):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def pristine_source(ip: str, rel: str) -> str:
    """Read a source file from the (assumed clean) contest repo."""
    return (REPO / rel).read_text()


def candidate_from_dir(ip: str, variant_dir: Path) -> dict[str, str]:
    """Build a cand_files dict from a directory of replacement files. .v
    basenames map into the IP's rtl_dir; .sv basenames map to their entry in
    spec.sv_sources (OpenTitan dual-representation IPs)."""
    spec = IPS[ip]
    sv_by_name = {Path(s).name: s for s in spec.sv_sources}
    out: dict[str, str] = {}
    for f in sorted(Path(variant_dir).glob("*.*v")):
        if f.suffix == ".sv":
            rel = sv_by_name.get(f.name)
            assert rel, f"{f.name} not in {ip} sv_sources"
        else:
            rel = f"{spec.rtl_dir}/{f.name}"
            assert (REPO / rel).exists(), \
                f"{f.name} does not exist in {spec.rtl_dir}"
        out[rel] = f.read_text()
    assert out, f"no .v/.sv files in {variant_dir}"
    return out
