#!/usr/bin/env python3
"""Mock contest model service (AGENT_GUIDE.md protocol) for offline testing
of the runner-mode agent. Serves POST /generate (answers with our reference
YAML/top, keyed off the TASK marker — same behavior as StubModel) and
GET /health. Stdlib only.

  python3 mock_endpoint.py [port]      # prints the bound port on stdout
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

NXP = Path(__file__).resolve().parents[1]
REF_SPECS = NXP / "specs"
REF_TOP = NXP / "rtl/secure_periph_soc.v"


def answer(prompt: str) -> str:
    if "TASK: YAML" in prompt:
        return "\n\n".join("```yaml\n" + y.read_text().strip() + "\n```"
                           for y in sorted(REF_SPECS.glob("*.yaml")))
    if "TASK: TOP" in prompt:
        return "```verilog\n" + REF_TOP.read_text() + "```"
    return "MOCK: unrecognized task"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):                      # keep stdout parseable
        pass

    def _send(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/generate":
            self._send(404, {"error": "not found"})
            return
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n).decode())
            self._send(200, {"text": answer(req.get("prompt", "")),
                             "diagnostics": {"mock": True,
                                             "model": req.get("model")}})
        except Exception as e:
            self._send(500, {"error": str(e), "retryable": False,
                             "provider": "mock", "provider_status": 500})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    srv = HTTPServer(("127.0.0.1", port), Handler)
    print(srv.server_address[1], flush=True)        # actual bound port
    srv.serve_forever()


if __name__ == "__main__":
    main()
