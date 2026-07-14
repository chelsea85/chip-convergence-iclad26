"""Auto-onboarding: construct an IPSpec for an UNSEEN design from the contest
repo's own conventions — no hand registry entry required.

Hidden testcases at DAC follow the same layout as the released IPs, so
discovery keys off those invariants:
  <ip>/.../yosys_syn/run_syn.sh          synthesis entry (anchors everything)
  yosys_syn/env.sh                       DESIGN_NAME, VERILOG_FILES|FILELIST
  yosys_syn/*_yosys.f                    -I dirs + .sv/.v sources (OT style)
  yosys_syn/generated/*.v + .sv filelist -> dual-representation (skip_sv2v=1)
  yosys_syn/constraint.sdc               create_clock -> clock ports + period
  run_*tb*.sh / run_*test*.sh            functional gate runner
  top-module input ports                 clk*/rst* classification for dualsim

The hand entries in config.IPS act as validation fixtures: `--validate`
diffs discovery output against them. `get_spec()` prefers hand entries and
falls back to discovery, so the rest of the package needs no changes.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .config import IPS, REPO, ClockSpec, IPSpec

_SIM_PERIODS = (10.0, 14.0, 7.0, 11.0)   # distinct sim periods per clock


# ── helpers ───────────────────────────────────────────────────────────────────
def _parse_env_sh(text: str) -> dict[str, str]:
    """export VAR=val and export VAR=${VAR:-val} forms, quoted or not
    (prim's env.sh uses export DESIGN_NAME="${DESIGN_NAME:-prim_crc32}")."""
    out = {}
    for m in re.finditer(
            r"^\s*export\s+(\w+)=[\"']?(?:\$\{\1:-)?([^}\n\"']*?)\}?[\"']?\s*$",
            text, re.M):
        val = m.group(2).strip()
        if val and not val.startswith("$"):
            out[m.group(1)] = val
    return out


def _parse_filelist(fl_path: Path) -> tuple[list[Path], list[Path]]:
    """Returns (source files, include dirs), resolved relative to the list."""
    srcs, incs = [], []
    base = fl_path.parent
    for line in fl_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(("-D", "-W", "--top")):
            continue
        if line.startswith("-I"):
            incs.append((base / line[2:].strip()).resolve())
            continue
        if line.startswith("-v"):
            line = line[2:].strip()
        if line.endswith((".v", ".sv")):
            srcs.append((base / line).resolve())
    return srcs, incs


def _repo_rel(p: Path) -> str:
    return str(p.resolve().relative_to(REPO))


def _input_ports(text: str) -> list[str]:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return re.findall(
        r"\binput\s+(?:wire\s+|logic\s+|reg\s+)?(?:\[[^\]]*\]\s*)?"
        r"([A-Za-z_]\w*)", text)


def _classify_clk_rst(ports: list[str]) -> tuple[list[str], list[tuple[str, int]]]:
    clocks, resets = [], []
    for p in ports:
        pl = p.lower()
        if re.search(r"(^|_)(clk|clock)", pl) and not \
                re.search(r"(ovr|gating|disable|enable|_en$|_on$)", pl):
            clocks.append(p)
        # [a-z]?rst catches wrst/arst/hrst prefixed forms without matching
        # e.g. "burst" (rst too deep into the word)
        elif re.search(r"(^|_)[a-z]?rst|(^|_)reset", pl):
            # active-low markers: _n/_ni/_b/_l suffixes, NVDLA's 'rstn' and
            # trailing-underscore conventions
            active = 0 if re.search(r"(_n|_ni|_b|_l|rstn|_)$", pl) else 1
            resets.append((p, active))
    return clocks, resets


# ── discovery ─────────────────────────────────────────────────────────────────
def find_syn_dirs() -> list[Path]:
    hits = []
    for p in REPO.glob("**/yosys_syn/run_syn.sh"):
        s = str(p)
        if "/BUILD/" in s or "/obj_fusesoc/" in s or "/yosys_syn/syn/" in s:
            continue
        hits.append(p.parent)
    return sorted(hits)


def discover(syn_dir: Path) -> IPSpec:
    env = _parse_env_sh((syn_dir / "env.sh").read_text()
                        if (syn_dir / "env.sh").exists() else "")
    # top = synthesis top module (env.sh DESIGN_NAME is authoritative).
    # The REGISTRY/cache key is location-derived instead (`name`, set below
    # once ip_root is known): a hidden testcase whose DESIGN_NAME collides
    # with a known IP must NOT alias onto that IP's cached baseline/ledger.
    top = env.get("DESIGN_NAME") or syn_dir.parent.name

    # ── sources ──────────────────────────────────────────────────────────────
    sources: list[str] = []
    sv_sources: list[str] = []
    skip_sv2v = 0
    filelist_rel = ""
    generated = syn_dir / "generated"

    if env.get("VERILOG_FILES"):
        for f in env["VERILOG_FILES"].split():
            sources.append(_repo_rel(syn_dir / f))
    else:
        fl = None
        if env.get("VERILOG_FILELIST"):
            cand = env["VERILOG_FILELIST"].replace("${SCRIPT_DIR}/", "")
            if (syn_dir / cand).exists():
                fl = syn_dir / cand
        if fl is None:
            fls = sorted(syn_dir.glob("*_yosys.f")) or sorted(syn_dir.glob("*.f"))
            fl = fls[0] if fls else None
        if fl is not None:
            srcs, _ = _parse_filelist(fl)
            filelist_rel = _repo_rel(fl)
            has_sv = any(s.suffix == ".sv" for s in srcs)
            if has_sv and generated.is_dir() and any(generated.glob("*.v")):
                # OpenTitan dual representation
                skip_sv2v = 1
                sources = sorted(_repo_rel(p) for p in generated.glob("*.v")
                                 if p.name != "all_modules.v")
                for s in srcs:
                    if s.suffix == ".sv" and not s.name.endswith("_pkg.sv") and \
                            (top in s.name or
                             _repo_rel(s).startswith(_repo_rel(syn_dir.parent))):
                        sv_sources.append(_repo_rel(s))
                sv_sources.sort()
            else:
                sources = [_repo_rel(s) for s in srcs]
        else:
            # last resort: syn.tcl default file block
            tcl = syn_dir / "syn.tcl"
            if tcl.exists():
                for m in re.finditer(r"\[file join \$rtl_dir (\S+?\.s?v)\]",
                                     tcl.read_text()):
                    rtl_dir = env.get("RTL_DIR", "../rtl")
                    sources.append(_repo_rel(syn_dir / rtl_dir / m.group(1)))

    assert sources, f"{top}: no synthesis sources discovered"
    rtl_dir = str(Path(sources[0]).parent)

    # ── clocks from SDC ──────────────────────────────────────────────────────
    sdc_clocks: list[str] = []
    sdc = syn_dir / "constraint.sdc"
    if sdc.exists():
        sdc_clocks = re.findall(r"create_clock[^\n]*\[get_ports\s+\{?(\w+)\}?\]",
                                sdc.read_text())

    # ── port classification (top source file) ────────────────────────────────
    top_file = next((s for s in sources
                     if Path(s).stem == top), sources[0])
    ports = _input_ports((REPO / top_file).read_text())
    clocks, resets = _classify_clk_rst(ports)
    for c in sdc_clocks:               # SDC is authoritative, keep order
        if c in clocks:
            clocks.remove(c)
    clocks = (sdc_clocks + clocks) or ["clk"]
    clock_specs = tuple(ClockSpec(c, _SIM_PERIODS[i % len(_SIM_PERIODS)])
                        for i, c in enumerate(clocks))

    # ── gate runner ──────────────────────────────────────────────────────────
    ip_root = syn_dir.parent
    if ip_root.name == "syn":          # NVDLA/syn/yosys_syn quirk
        ip_root = ip_root.parent

    # registry/cache key: location-derived, never DESIGN_NAME (collision =
    # wrong cached baseline). Hash-suffix if even the dir name collides with
    # a DIFFERENT already-registered location.
    name = ip_root.name
    if name in IPS and IPS[name].syn_dir != _repo_rel(syn_dir):
        import hashlib
        name = f"{name}_{hashlib.md5(_repo_rel(syn_dir).encode()).hexdigest()[:6]}"
    gate_dir, gate_cmd = "", ""
    runners = sorted(
        (p for pat in ("run_*tb*.sh", "run_*test*.sh")
         for p in ip_root.glob(f"**/{pat}")
         if "BUILD" not in str(p) and "obj_fusesoc" not in str(p)),
        key=lambda p: len(p.parts))
    if runners:
        r = runners[0]
        gate_dir = _repo_rel(r.parent)
        gate_cmd = f"./{r.name}" + (" all" if "tb" in r.name else "")

    # ── workspace shape ──────────────────────────────────────────────────────
    subtree = Path(_repo_rel(syn_dir)).parts[0]
    clean = tuple(_repo_rel(p) for pat in ("obj_fusesoc", "BUILD")
                  for p in ip_root.glob(f"**/{pat}") if p.is_dir())

    return IPSpec(
        name=name, top=top, rtl_dir=rtl_dir, sources=tuple(sources),
        syn_dir=_repo_rel(syn_dir), gate_dir=gate_dir, gate_cmd=gate_cmd,
        subtrees=(subtree,), skip_sv2v=skip_sv2v, clocks=clock_specs,
        resets=tuple(resets), sv_sources=tuple(sv_sources),
        filelist=filelist_rel, clean_dirs=clean)


def get_spec(name_or_path: str) -> IPSpec:
    """Hand registry first (validated fixtures), discovery for unseen IPs —
    by repo-relative path or by DESIGN_NAME."""
    if name_or_path in IPS:
        return IPS[name_or_path]
    p = (REPO / name_or_path)
    if p.exists():
        syn = p if p.name == "yosys_syn" else next(
            (d for d in find_syn_dirs() if str(d).startswith(str(p))), None)
        assert syn, f"no yosys_syn/run_syn.sh found under {name_or_path}"
        return discover(Path(syn))
    for syn in find_syn_dirs():        # lookup by location key or DESIGN_NAME
        env = _parse_env_sh((syn / "env.sh").read_text()
                            if (syn / "env.sh").exists() else "")
        root = syn.parent.parent if syn.parent.name == "syn" else syn.parent
        if name_or_path in (root.name, env.get("DESIGN_NAME"),
                            syn.parent.name):
            return discover(syn)
    raise AssertionError(f"no IP named or at '{name_or_path}' found")


def register(spec: IPSpec):
    """Make a discovered spec visible to the rest of the package."""
    IPS[spec.name] = spec


# ── validation CLI ────────────────────────────────────────────────────────────
_CHECK_FIELDS = ("top", "rtl_dir", "sources", "syn_dir", "gate_dir",
                 "gate_cmd", "skip_sv2v", "sv_sources")


def main(argv=None):
    ap = argparse.ArgumentParser(description="IP auto-discovery")
    ap.add_argument("--validate", action="store_true",
                    help="diff discovery vs hand registry entries")
    ap.add_argument("--ip", help="discover one IP (name or repo-relative path)")
    a = ap.parse_args(argv)

    if a.validate:
        ok = True
        by_name = {}
        for syn in find_syn_dirs():
            try:
                spec = discover(syn)
                by_name[spec.name] = spec
            except Exception as e:
                print(f"  {syn}: DISCOVERY FAILED: {e}")
        for name, hand in IPS.items():
            got = by_name.get(name)
            if not got:
                print(f"{name}: NOT DISCOVERED")
                ok = False
                continue
            diffs = [f for f in _CHECK_FIELDS
                     if getattr(got, f) != getattr(hand, f)]
            if diffs:
                ok = False
                print(f"{name}: MISMATCH in {diffs}")
                for f in diffs:
                    print(f"   hand {f}: {getattr(hand, f)}")
                    print(f"   disc {f}: {getattr(got, f)}")
            else:
                print(f"{name}: MATCH (clocks={[c.name for c in got.clocks]}, "
                      f"resets={list(got.resets)})")
        new = sorted(set(by_name) - set(IPS))
        print(f"\nnewly onboarded (no hand entry): {new}")
        for n in new:
            s = by_name[n]
            print(f"  {n}: top={s.top} srcs={len(s.sources)} "
                  f"gate={s.gate_dir}:{s.gate_cmd} skip_sv2v={s.skip_sv2v} "
                  f"clocks={[c.name for c in s.clocks]} resets={list(s.resets)}")
        return 0 if ok else 1

    assert a.ip
    s = get_spec(a.ip)
    for f in ("name", *_CHECK_FIELDS, "subtrees", "clean_dirs"):
        v = getattr(s, f)
        print(f"{f}: {v if not isinstance(v, tuple) or len(v) < 8 else f'({len(v)} items)'}")
    print("clocks:", [(c.name, c.period_ns) for c in s.clocks],
          "resets:", list(s.resets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
