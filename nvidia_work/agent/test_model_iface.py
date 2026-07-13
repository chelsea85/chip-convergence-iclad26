#!/usr/bin/env python3
"""Mocked smoke test of the model interface — exercises the EXACT VertexModel
code path (client init modes, generate, usage accounting, retry ladder)
without network or the google-genai package, plus EndpointModel against a
live local stdlib HTTP server. This is the closest we can get to the Vertex
seam before a real key exists.

Run: python3 test_model_iface.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail and not ok else ''}")
    PASS += ok
    FAIL += not ok


# ── fake google-genai SDK ─────────────────────────────────────────────────────
class _FakeAPIError(Exception):
    def __init__(self, code):
        self.code = code


class _FakeUsage:
    prompt_token_count = 100
    candidates_token_count = 50
    total_token_count = 150      # includes thought tokens on real responses


class _FakeResponse:
    text = "// FILE: fake.v\nmodule fake; endmodule"
    usage_metadata = _FakeUsage()


class _FakeModels:
    def __init__(self, fail_codes):
        self.fail_codes = list(fail_codes)
        self.call_log = []

    def generate_content(self, model, contents, config):
        self.call_log.append(dict(model=model, config=config))
        if self.fail_codes:
            raise _FakeAPIError(self.fail_codes.pop(0))
        return _FakeResponse()


class _FakeClient:
    last_init = None

    def __init__(self, **kw):
        _FakeClient.last_init = kw
        self.models = _FakeModels(fail_codes=_FakeClient.next_fail_codes)
        _FakeClient.next_fail_codes = []

    next_fail_codes = []


def install_fake_genai():
    genai = types.ModuleType("google.genai")
    genai.Client = _FakeClient
    errors = types.ModuleType("google.genai.errors")
    errors.APIError = _FakeAPIError
    google = types.ModuleType("google")
    google.genai = genai
    genai.errors = errors
    sys.modules["google"] = google
    sys.modules["google.genai"] = genai
    sys.modules["google.genai.errors"] = errors


def test_vertex_model():
    import time as _time
    install_fake_genai()
    from ppa import proposer
    proposer.time.sleep = lambda s: None          # no real backoff waits

    # express mode init
    os.environ["EXPRESS_MODE_KEY"] = "test-express-key"
    os.environ.pop("GEMINI_API_KEY", None)
    m = proposer.VertexModel(model_name="gemini-test", temperature=0.3,
                             top_p=0.7)
    check("express: vertexai=True client init",
          _FakeClient.last_init.get("vertexai") is True and
          _FakeClient.last_init.get("api_key") == "test-express-key",
          str(_FakeClient.last_init))
    check("express: mode label", m.mode == "vertex-express")
    r = m.generate("optimize this RTL")
    check("generate returns text", r.startswith("// FILE: fake.v"))
    check("usage-metadata token accounting", m.tokens == 150 and m.calls == 1,
          f"tokens={m.tokens} calls={m.calls}")
    cfg = m.client.models.call_log[0]["config"]
    check("model name + decoding config passed through",
          m.client.models.call_log[0]["model"] == "gemini-test" and
          cfg["temperature"] == 0.3 and cfg["top_p"] == 0.7 and
          cfg["max_output_tokens"] == 65536 and
          cfg["thinking_config"] == {"thinking_budget": 8192},
          str(cfg))

    # ai-studio mode init
    os.environ.pop("EXPRESS_MODE_KEY")
    os.environ["GEMINI_API_KEY"] = "test-studio-key"
    m2 = proposer.VertexModel()
    check("ai-studio: plain api_key client init",
          "vertexai" not in _FakeClient.last_init and
          _FakeClient.last_init.get("api_key") == "test-studio-key",
          str(_FakeClient.last_init))
    check("ai-studio: mode label", m2.mode == "ai-studio")

    # retry ladder: two retryable errors then success
    _FakeClient.next_fail_codes = [429, 503]
    m3 = proposer.VertexModel()
    r = m3.generate("prompt")
    check("retries through 429+503 then succeeds",
          r.startswith("// FILE:") and len(m3.client.models.call_log) == 3)

    # non-retryable error raises
    _FakeClient.next_fail_codes = [400]
    m4 = proposer.VertexModel()
    try:
        m4.generate("prompt")
        check("non-retryable 400 raises", False)
    except _FakeAPIError:
        check("non-retryable 400 raises", True)

    # no key -> clear SystemExit
    os.environ.pop("GEMINI_API_KEY")
    try:
        proposer.VertexModel()
        check("missing key -> SystemExit", False)
    except SystemExit as e:
        check("missing key -> SystemExit", "API key" in str(e))


# ── endpoint model against a live local server ────────────────────────────────
class _EpHandler(BaseHTTPRequestHandler):
    fail_first = 0

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n).decode())
        if _EpHandler.fail_first > 0:
            _EpHandler.fail_first -= 1
            body = {"error": "overloaded", "retryable": True,
                    "provider_status": 429}
        else:
            body = {"text": f"// FILE: ep.v\n// model={req['model']}\n"
                            f"module ep; endmodule",
                    "diagnostics": {}}
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_endpoint_model():
    from ppa import proposer
    srv = HTTPServer(("127.0.0.1", 0), _EpHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        m = proposer.EndpointModel(url, model_name="gemini-ep-test")
        r = m.generate("optimize")
        check("endpoint: returns text with model passthrough",
              "model=gemini-ep-test" in r)
        check("endpoint: call/token accounting",
              m.calls == 1 and m.tokens > 0)
        _EpHandler.fail_first = 2
        r = m.generate("optimize again")
        check("endpoint: retries retryable errors then succeeds",
              r.startswith("// FILE: ep.v"))
    finally:
        srv.shutdown()


def main():
    test_vertex_model()
    test_endpoint_model()
    print(f"model interface: {PASS}/{PASS+FAIL} PASS")
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
