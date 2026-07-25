#!/usr/bin/env python3
"""EndpointModel adversarial hardening tests (Codex §6.2, 2026-07-23).

Deterministic: monkeypatches urllib.request.urlopen with a scripted sequence of
responses/errors, and injects a zero-duration backoff so retries run instantly.
Asserts typed, deadline-bounded behavior — malformed responses never raise
uncaught, retryable errors recover, terminal errors don't retry, and the total
deadline bounds runtime.
"""
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nxp_agent as A                                            # noqa: E402

PASS = FAIL = 0


def check(name, ok):
    global PASS, FAIL
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    PASS, FAIL = PASS + int(bool(ok)), FAIL + int(not ok)


class _Resp:
    def __init__(self, raw: bytes):
        self._raw = raw
    def read(self):
        return self._raw
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _script(seq):
    """seq: list of ('ok', body_bytes) | ('http', code) | ('neterr',) | raw bytes."""
    it = iter(seq)

    def fake_urlopen(req, timeout=None):
        try:
            item = next(it)
        except StopIteration:
            raise urllib.error.URLError("exhausted")
        if isinstance(item, bytes):
            return _Resp(item)
        kind = item[0]
        if kind == "ok":
            return _Resp(item[1])
        if kind == "http":
            raise urllib.error.HTTPError(req.full_url, item[1], "err", {}, None)
        if kind == "neterr":
            raise urllib.error.URLError("connection refused")
        raise AssertionError(item)
    return fake_urlopen


def run(seq, **kw):
    m = A.EndpointModel("http://x", "model", _sleep=lambda s: None, **kw)
    m.calls = 0
    orig = urllib.request.urlopen
    urllib.request.urlopen = _script(seq)
    try:
        return m, m.generate("prompt")
    finally:
        urllib.request.urlopen = orig


def run_expect_fail(seq, **kw):
    try:
        run(seq, **kw)
        return None
    except RuntimeError as e:
        return str(e)


OK = json.dumps({"text": "// FILE: x.v\nmodule x; endmodule"}).encode()


def main():
    # retryable transport -> success
    _, out = run([("http", 429), ("http", 503), ("ok", OK)])
    check("429 -> 503 -> success", out.startswith("// FILE:"))
    _, out = run([("neterr",), ("ok", OK)])
    check("network error -> success", out.startswith("// FILE:"))
    # retryable JSON body -> success
    _, out = run([("ok", json.dumps({"retryable": True, "error": "busy"}).encode()),
                  ("ok", OK)])
    check("retryable JSON body -> success", out.startswith("// FILE:"))

    # MALFORMED responses must be typed transient (retry), NOT uncaught
    _, out = run([("ok", b'{"text":'), ("ok", OK)])          # truncated JSON
    check("truncated JSON -> retried -> success (no uncaught JSONDecodeError)",
          out.startswith("// FILE:"))
    _, out = run([("ok", b'\xff\xfe not utf8'), ("ok", OK)])  # bad UTF-8
    check("invalid UTF-8 -> retried -> success", out.startswith("// FILE:"))
    _, out = run([("ok", json.dumps([]).encode()), ("ok", OK)])  # list body
    check("JSON list body -> retried -> success (no uncaught AttributeError)",
          out.startswith("// FILE:"))
    _, out = run([("ok", json.dumps({"text": 123}).encode()), ("ok", OK)])
    check("non-string text -> retried -> success", out.startswith("// FILE:"))
    _, out = run([("ok", json.dumps({"text": ""}).encode()),
                  ("ok", json.dumps({"retryable": True}).encode()), ("ok", OK)])
    check("empty text -> retried -> success", out.startswith("// FILE:"))

    # persistent malformed -> typed bounded FAIL (never uncaught)
    err = run_expect_fail([("ok", b'{"text":')] * 6)
    check("persistent truncated JSON -> typed RuntimeError, no leak",
          err is not None and "malformed" in err and "prompt" not in err)
    err = run_expect_fail([("ok", json.dumps([]).encode())] * 6)
    check("persistent list body -> typed RuntimeError",
          err is not None and "not a JSON object" in err)

    # terminal 4xx -> NO retry (one call)
    m = A.EndpointModel("http://x", "model", _sleep=lambda s: None)
    m.calls = 0
    urllib.request.urlopen = _script([("http", 400), ("ok", OK)])
    try:
        m.generate("p")
        check("terminal 400 -> no retry", False)
    except RuntimeError as e:
        check("terminal 400 -> no retry (1 call, no fallthrough to success)",
              m.calls == 1 and "HTTP 400" in str(e))
    finally:
        urllib.request.urlopen = urllib.request.urlopen

    # total deadline bounds retries (0s budget -> immediate typed fail)
    err = run_expect_fail([("http", 503)] * 6, total_deadline_s=0)
    check("total deadline exhausted -> bounded typed fail",
          err is not None and "deadline" in err)

    print(f"\ntest_endpoint: {PASS}/{PASS + FAIL} PASS")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
