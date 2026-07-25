"""Fail-closed regression for the PRODUCTION evaluate.measure() (P0-1).

Proves measure() returns None (never a partial dict) when measure.sh exits
nonzero or emits a missing/nonnumeric/nonfinite mandatory metric — so a bogus
baseline/candidate can never be cached or compared. Exercises the real function
with a stub Workspace (no Docker/synth needed)."""
import sys, types
from dataclasses import dataclass
sys.path.insert(0, ".")
from ppa import evaluate


@dataclass
class _Spec:
    syn_dir: str = "x/yosys_syn"
    skip_sv2v: int = 0
    top: str = "top"


class _Run:
    def __init__(self, rc, out):
        self.returncode, self.stdout, self.stderr = rc, out, ""


class _WS:
    """Minimal Workspace stub: canned measure.sh result."""
    def __init__(self, rc, out):
        self.spec = _Spec()
        self._r = _Run(rc, out)

    def run(self, cmd, timeout=0):
        return self._r


def _line(area="78346.60686", cells="952591", ff="42457",
          setup="-5788.40", hold="42.40", flag="VIOLATED", pwr="1.04e-02"):
    return (f"top-base | VT=RVT C=TT ABC=0 | area={area} cells={cells} ff={ff} "
            f"| setup={setup}ps hold={hold}ps [{flag}] | pwr={pwr}W")


CASES = [
    ("valid full line -> dict",        _WS(0, _line()),                      True),
    ("nonzero returncode -> None",     _WS(3, _line()),                      False),
    ("area=? -> None",                 _WS(0, _line(area="?")),              False),
    ("area empty-ish '-' -> None",     _WS(0, _line(area="-")),              False),
    ("cells=0 -> None",                _WS(0, _line(cells="0")),             False),
    ("power=? -> None",                _WS(0, _line(pwr="?")),               False),
    ("nan area -> None",               _WS(0, _line(area="nan")),            False),
    ("inf power -> None",              _WS(0, _line(pwr="inf")),             False),
    ("negative area -> None",          _WS(0, _line(area="-5.0")),           False),
    ("unparseable line -> None",       _WS(0, "garbage no metrics here"),    False),
    ("empty stdout -> None",           _WS(0, ""),                           False),
    ("setup<=0 is allowed",            _WS(0, _line(setup="-100.0")),        True),
    ("hold=0 allowed",                 _WS(0, _line(hold="0.00")),           True),
]

p = f = 0
for name, ws, want_ppa in CASES:
    got = evaluate.measure(ws, "top-base")
    ok = (got is not None) == want_ppa
    # when a dict is returned, every mandatory metric must be a finite number
    if ok and want_ppa:
        req = evaluate._REQ_POSITIVE + evaluate._REQ_FINITE
        ok = all(isinstance(got[k], float) for k in req)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    p += ok; f += not ok

print(f"test_measure_failclosed: {p}/{p+f} PASS")
sys.exit(0 if f == 0 else 1)
