"""Model-proposed repair passes for the ASU agent.

The model is asked to write a small pya fix-pass (appended to the original
script, run before write) that reduces the reported DRC violations WITHOUT
moving metal edges that enclose vias / carry connectivity. Its output is
verified + kept-only-if-better by the agent, so a bad suggestion is harmless.

Models:
  stub      offline — returns a no-op pass (pipeline/runner-contract testing)
  vertex    google-genai (EXPRESS_MODE_KEY / GEMINI_API_KEY)
  endpoint  contest model-service HTTP (info.json model_endpoint)
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


def _extract_code(text: str) -> str:
    blocks = _FENCE.findall(text or "")
    code = "\n".join(b.strip() for b in blocks) if blocks else (text or "").strip()
    # safety: reject obviously non-pya or dangerous content
    if not code or "layout" not in code:
        return ""
    for bad in ("import os", "import sys", "subprocess", "open(", "__import__",
                "eval(", "exec("):
        if bad in code:
            return ""
    return code


def _rules_block(digest) -> str:
    """The matched repair-rule-library entries for the rules actually present —
    structure-matched knowledge injection (like the NVIDIA 45-rule playbook)."""
    import drc_digest
    seen, lines = set(), []
    lib = drc_digest.rule_library()
    lines.append(f"LAYER MAP (name->GDS layer): {lib['_meta']['layers']}")
    lines.append(f"DBU per nm = {lib['_meta']['dbu_per_nm']}")
    for f in digest.findings:
        r = drc_digest.match_rule(f.rule)
        if not r or r["id"] in seen:
            continue
        seen.add(r["id"])
        lines.append(
            f"\n[{r['id']}] fixes rules like {f.rule}:\n"
            f"  transform: {r['transform']}\n"
            f"  COUPLING HAZARD: {r['coupling']}")
    return "\n".join(lines)


def build_prompt(digest, orig_nw_script: str, cur, P) -> str:
    top = digest.bundle_text(top_n=16)
    rules = _rules_block(digest)
    head = "\n".join(orig_nw_script.splitlines()[:40])
    return f"""You are legalizing an ASAP7 block layout built by a `pya` Python
script. The script constructs `layout` (pya.Layout) with a top cell and inserts
shapes on metal layers (M1..M6) and via layers (V0..V5). DRC reports:

{top}

CRITICAL — the violations sit on VIA STACKS (M2-V2-M3-V3-M4...). Widths must be
mutually consistent AND grid-aligned AND mutually enclosing THROUGH the stack.
A single-layer edit just pushes the violation to an adjacent layer (measured:
growing a via to match M3 breaks the M2 enclosure below it; shrinking M3 breaks
the V3 enclosure above it). Fixes must be STACK-COORDINATED.

Repair-rule library (use these transforms; respect the coupling hazards):
{rules}

Write a SELF-CONTAINED pya fix-pass operating on the already-built `layout`
(all shapes inserted). It runs right before `layout.write(...)`. You MAY
`layout.top_cell().flatten(-1, True)` to edit flattened shapes by location. Use
pya.Region/pya.Box/pya.Polygon. Do NOT re-create the layout, do NOT import
anything, do NOT open files. Make MINIMAL, LOCAL, stack-coordinated edits that
reduce total violations without creating new ones.

Script header (layer/shape idioms):
```python
{head}
```

Current best: total DRC violations={cur.total}, final_violation_rate=\
{cur.final_violation_rate}. Return ONLY one Python code block."""


class StubModel:
    usage = {"num_calls": 0, "total_tokens": 0}

    def generate(self, prompt: str) -> str:
        self.usage["num_calls"] += 1
        return "```python\n# stub: no-op repair pass\n_asu_noop = len(str(layout))\n```"


class VertexModel:
    def __init__(self, model_name="gemini-3-flash-preview"):
        from google import genai
        name = next((k for k in ("EXPRESS_MODE_KEY", "GEMINI_API_KEY",
                                 "GEMINI_API_KEY_2") if os.environ.get(k)), None)
        if not name:
            raise SystemExit("no API key (EXPRESS_MODE_KEY / GEMINI_API_KEY)")
        key = os.environ[name]
        kw = {"api_key": key, "http_options": {"timeout": 300_000}}
        if "EXPRESS" in name.upper():
            kw["vertexai"] = True
        self.client = genai.Client(**kw)
        self.model_name = model_name
        self.usage = {"num_calls": 0, "total_tokens": 0}

    def generate(self, prompt: str) -> str:
        r = self.client.models.generate_content(
            model=self.model_name, contents=prompt,
            config={"max_output_tokens": 65536, "temperature": 0.3,
                    "thinking_config": {"thinking_budget": 8192}})
        u = getattr(r, "usage_metadata", None)
        self.usage["num_calls"] += 1
        if u:
            self.usage["total_tokens"] += getattr(u, "total_token_count", 0) or 0
        return r.text or ""


class EndpointModel:
    def __init__(self, url: str, model_name="gemini-3-flash-preview"):
        self.url, self.model_name = url.rstrip("/"), model_name
        self.usage = {"num_calls": 0, "total_tokens": 0}

    def generate(self, prompt: str) -> str:
        body = json.dumps({"model": self.model_name, "prompt": prompt}).encode()
        req = urllib.request.Request(self.url + "/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            d = json.loads(resp.read().decode())
        self.usage["num_calls"] += 1
        self.usage["total_tokens"] += d.get("total_tokens", 0)
        return d.get("text", "")


def make_model(kind: str, P):
    if kind == "stub":
        return StubModel()
    if kind == "vertex":
        return VertexModel(getattr(P, "model_name", "gemini-3-flash-preview"))
    if kind == "endpoint":
        # contest runner contract: ALL model calls go to info.json's
        # model_endpoint (F-01 fix). Fall back to env/localhost for dev only.
        ep = (getattr(P, "model_endpoint", "") or
              os.environ.get("ASU_MODEL_ENDPOINT", "") or "http://127.0.0.1:8080")
        return EndpointModel(ep, getattr(P, "model_name", "gemini-3-flash-preview"))
    raise SystemExit(f"unknown model kind: {kind}")


def _compiles(code: str) -> bool:
    try:
        compile(code, "<fixpass>", "exec")
        return True
    except SyntaxError:
        return False


def propose_fix_pass(model, prompt: str) -> str:
    code = _extract_code(model.generate(prompt))
    return code if (code and _compiles(code)) else ""


REPAIR_SUFFIX = """

Your previous fix-pass FAILED (render/DRC error below). Fix it — keep the intent,
correct the pya API usage. Return ONLY one Python code block.

## Error
{err}

## Your previous pass
```python
{code}
```
"""
