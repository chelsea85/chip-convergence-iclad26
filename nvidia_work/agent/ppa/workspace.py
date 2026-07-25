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

from . import config, contract
from .config import IPS, REPO, WORK, IPSpec, docker_run

_COPY_EXCLUDES = ("syn_results*", "reports")


def _clone_tree(src: Path, dst: Path) -> str:
    """Portable full-tree copy (Rev2.1 SSD.1): APFS clone fast path on darwin,
    GNU reflink fast path on Linux, safe recursive fallback preserving
    modes/symlinks. Returns an explicit method label (per-subtree provenance;
    excluded from logical design-input hashes). Post-copy, escaping symlinks
    are rejected (Rev2.1a SSH.4d): a link resolving outside the copied tree
    fails validation rather than being silently preserved."""
    import shutil as _sh
    import sys as _sys
    if _sys.platform == "darwin":
        fast, label = ["cp", "-Rc", str(src), str(dst)], "apfs-clone"
    else:
        fast, label = ["cp", "-a", "--reflink=auto", str(src), str(dst)], \
            "gnu-reflink"
    r = subprocess.run(fast, capture_output=True)
    if r.returncode != 0:
        _sh.rmtree(dst, ignore_errors=True)  # never keep a partial fast copy
        _sh.copytree(src, dst, symlinks=True)
        label = "copytree"
    try:
        _scan_dest_aliases(src, dst)
    except contract.ContractError:
        _sh.rmtree(dst, ignore_errors=True)   # never keep an unsafe copy
        raise
    return label


def _scan_dest_aliases(src: Path, dst: Path):
    """Post-copy alias scan, factored so the rejection branch is unit-testable
    independent of any copy method's hardlink semantics (re-review3 SS5): a
    method that DE-LINKS a source hardlink pair produced a safe tree and
    passes; a method that PRESERVES the pair is rejected here.

    ONE path domain (re-review2 SS4.1): children from dst.rglob() keep the
    LEXICAL spelling, so relative paths are computed against lexical `dst`
    itself - never against dst.resolve(), which breaks under a symlink-aliased
    ancestor (macOS /var -> /private/var). Resolved paths are used only for
    the escape check, where both sides are resolved."""
    droot = dst.resolve()
    seen_inodes: dict[tuple[int, int], str] = {}
    for p in dst.rglob("*"):
        rel = p.relative_to(dst)               # lexical vs lexical - safe
        if p.is_symlink():
            tgt = p.resolve()                  # resolved vs resolved - safe
            if not str(tgt).startswith(str(droot) + "/"):
                raise contract.ContractError(
                    f"workspace copy: escaping symlink {rel} -> {tgt}")
        elif p.is_file():
            st_p = p.stat()
            key = (st_p.st_dev, st_p.st_ino)
            # (a) alias back into the source tree: a workspace mutation would
            # reach the pristine repo (Rev2.1a SSH.4d)
            s = src / rel
            if s.exists():
                st_s = s.stat()
                if key == (st_s.st_dev, st_s.st_ino):
                    raise contract.ContractError(
                        f"workspace copy: {rel} is a hardlink alias of the "
                        f"source tree")
            # (b) two destination paths sharing one inode (cp -a can preserve
            # internal hardlinks): a write through one path would silently
            # mutate the other class (re-review2 SS5.2)
            if key in seen_inodes:
                raise contract.ContractError(
                    f"workspace copy: {rel} and {seen_inodes[key]} are "
                    f"internal hardlink aliases")
            seen_inodes[key] = str(rel)


def _validate_copy(ws: "Workspace"):
    """Contract-aware post-copy validation (re-review2 SS5.1): every declared
    editable/immutable-dependency root must exist in the workspace after
    cloning, be UNALIASED (no symlink in any component), and be a real regular
    file or directory - an internal symlink standing in for a required root is
    rejected before any tool can consume it."""
    ctr = contract.get_contract(ws.spec)
    classes = ctr.path_classes()
    for cls_name in ("editable", "immutable_deps"):
        for rel in classes.get(cls_name, ()):
            p = ws.root / rel
            if not p.exists():
                raise contract.ContractError(
                    f"workspace copy incomplete: required {cls_name} root "
                    f"{rel} missing")
            contract._assert_unaliased(ws.root, rel,
                                       f"required {cls_name} root")
            if not (p.is_file() or p.is_dir()):
                raise contract.ContractError(
                    f"required {cls_name} root {rel} is not a regular "
                    f"file/directory")


class RegenError(RuntimeError):
    """Source-to-generated regeneration of an edited source failed."""


class Workspace:
    def __init__(self, spec: IPSpec, root: Path, tag: str,
                 scope: "contract.CampaignScope | None" = None):
        self.spec = spec
        self.root = root
        self.tag = tag
        self.scope = scope   # campaign narrowing enforced on every overlay

    # ── lifecycle ────────────────────────────────────────────────────────────
    @classmethod
    def create(cls, ip: str, cand_files: dict[str, str] | None = None,
               tag: str = "",
               scope: "contract.CampaignScope | None" = None) -> "Workspace":
        """cand_files maps repo-relative paths (must be inside the IP's
        contract-editable set, and inside `scope` when given) to full file
        contents. None/empty -> pristine baseline workspace."""
        spec = IPS[ip]
        tag = tag or uuid.uuid4().hex[:8]
        # ALWAYS-UNIQUE root (2026-07-23, host-run fix): a fixed per-IP/tag dir
        # that gets rmtree'd on reuse crashed on macOS when TCC denied deleting
        # the bind-mounted techlib subdir (only a com.apple.provenance xattr) —
        # this killed the aes release packet on its second run. A unique suffix
        # means we never delete a prior run's tree; if a same-named dir somehow
        # exists, fall back to a fresh unique name rather than rmtree-crash.
        base = WORK / ip / f"{time.strftime('%m%d_%H%M%S')}_{tag}"
        root = base
        if root.exists():
            try:
                shutil.rmtree(root)
            except OSError:
                root = WORK / ip / f"{base.name}_{uuid.uuid4().hex[:6]}"
        root.mkdir(parents=True)

        config.require_repo()
        copy_methods: dict[str, str] = {}
        for sub in spec.subtrees:
            dst = root / sub
            dst.parent.mkdir(parents=True, exist_ok=True)
            # fast path is a copy-on-write clone (~2s even for the 700M
            # opentitan tree on APFS); falls back portably (Rev2.1 SSD.1)
            copy_methods[sub] = _clone_tree(REPO / sub, dst)
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

        ws = cls(spec, root, tag, scope=scope)
        ws.copy_methods = copy_methods  # per-subtree provenance, never hashed
        _validate_copy(ws)              # required contract roots present
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
        # two-layer validation (P0-4): contract editable universe + campaign
        # scope, with canonical-path/symlink-escape rejection. The scope fixed
        # at create() is the sole authority - no per-overlay override
        # (review SS3.3). Direct/sv2v semantics match the prior inline asserts.
        ctr = contract.get_contract(self.spec)
        contract.validate_candidate(ctr, self.root, cand_files, self.scope)
        touched_sv = []
        for rel, text in cand_files.items():
            rel_path = Path(rel)
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


def candidate_from_dir(ip: str, variant_dir: Path,
                       scope: "contract.CampaignScope | None" = None
                       ) -> dict[str, str]:
    """Build a cand_files dict from a directory of replacement files. .v
    basenames map into the IP's rtl_dir; .sv basenames map to their entry in
    spec.sv_sources (OpenTitan dual-representation IPs). Tmake/NVDLA requires
    an explicit scope so a repeated basename can never be guessed into the
    wrong nested vmod partition."""
    spec = IPS[ip]
    ctr = contract.get_contract(spec)
    sv_by_name = {Path(s).name: s for s in spec.sv_sources}
    scoped_v = {}
    if ctr.name == "tmake":
        contract.check_scope_compat(ctr, scope)
        for rel in scope.editable_targets:
            name = Path(rel).name
            if name in scoped_v:
                raise contract.ContractError(
                    f"ambiguous scoped tmake basename {name!r}")
            scoped_v[name] = rel
    out: dict[str, str] = {}
    for f in sorted(Path(variant_dir).glob("*.*v")):
        if f.suffix == ".sv":
            rel = sv_by_name.get(f.name)
            assert rel, f"{f.name} not in {ip} sv_sources"
        elif ctr.name == "tmake":
            rel = scoped_v.get(f.name)
            if rel is None:
                raise contract.ContractError(
                    f"{f.name} is not the exact scoped tmake target")
        else:
            rel = f"{spec.rtl_dir}/{f.name}"
            assert (REPO / rel).exists(), \
                f"{f.name} does not exist in {spec.rtl_dir}"
        out[rel] = f.read_text()
    assert out, f"no .v/.sv files in {variant_dir}"
    return out
