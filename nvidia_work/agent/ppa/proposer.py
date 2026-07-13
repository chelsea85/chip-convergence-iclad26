"""Proposal generation: strategy ladder, prompt builder, model interface.

Prompt structure (Alpha-RTL template + our blocks, ordered stable-first for
prompt-cache friendliness):
  role + hard constraints
  design dossier (per-IP, static)
  playbook bullets (retrieved by STA tag + objective axis)
  current design RTL + measured PPA (the state being mutated)
  STA-localized feedback block
  strategy directive (the ladder rung this candidate explores)
  budget block (BATS)
  output format

Diversity across a best-of-k batch comes from DISTINCT LADDER RUNGS, not
temperature (Agent Factories / Diversity Collapse findings).
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .config import IPS

# ── strategy ladder (v0..v6, axis-tagged) ─────────────────────────────────────
LADDER = [
    dict(key="micro-opt", axis="area",
         directive="Conservative micro-optimizations only: common "
                   "subexpression elimination, constant folding, strength "
                   "reduction, dead logic removal. No structural changes."),
    dict(key="balanced-tree", axis="perf",
         directive="Re-associate serial arithmetic/logic chains on the "
                   "critical path into balanced trees (provably equivalent "
                   "reorderings only, e.g. mod-2^w addition)."),
    dict(key="carry-save", axis="perf",
         directive="Rewrite 3+ operand additions on the critical path using "
                   "carry-save (3:2 compressor) form with one final "
                   "carry-propagate adder."),
    dict(key="restructure-select", axis="perf",
         directive="Restructure selection/decode logic: priority chains to "
                   "parallel one-hot, hierarchical group-then-encode for "
                   "wide encoders, rebalanced mux trees."),
    dict(key="share-resources", axis="area",
         directive="Share mutually-exclusive arithmetic resources; derive "
                   "redundant +/-1 or shifted values from one computation; "
                   "re-encode FSMs appropriately for their state count."),
    dict(key="arith-arch", axis="perf",
         directive="Swap the architecture of ONE critical-path arithmetic "
                   "operator (adder tree style: Kogge-Stone / Brent-Kung / "
                   "Sklansky; or compressor-tree multiplier). One operator "
                   "only, keep everything else untouched."),
    dict(key="activity-reduce", axis="power",
         directive="Reduce switching activity: operand isolation for unused "
                   "units, enable-gated registers, replace physically "
                   "shifting register banks with pointer-addressed buffers."),
]


def pick_strategies(k: int, weights: dict, exclude: set[str] = frozenset(),
                    boost_axis: str | None = None) -> list[dict]:
    """k distinct rungs, ordered by objective-axis weight (boost_axis first)."""
    def score(r):
        w = weights.get(r["axis"] if r["axis"] != "perf" else "perf", 0.1)
        return (2.0 if r["axis"] == boost_axis else 1.0) * (w + 0.05)
    ranked = sorted((r for r in LADDER if r["key"] not in exclude),
                    key=score, reverse=True)
    return ranked[:k]


# ── prompt ────────────────────────────────────────────────────────────────────
_HARD_RULES = """HARD CONSTRAINTS (violations are auto-rejected by tooling):
- Functional behavior must be EXACTLY preserved; the provided testbench, a
  formal equivalence check, and a random differential simulation all gate
  acceptance.
- Do NOT change any module's port list, name, or parameters.
- Do NOT add or remove pipeline stages / change cycle-level latency{latency_note}.
- Synthesizable Verilog-2001/2005 only; no initial blocks, no latches.
- Return COMPLETE file contents for every file you modify (and only those)."""

_TEMPLATE = """You are an expert RTL engineer optimizing Verilog PPA on the ASAP7 7nm library
(Yosys synthesis + OpenSTA timing). Optimization goal weights: {weights}.

{hard_rules}

{dossier}

{playbook}

## Current design ({ip}, measured on our flow)
area={area} um2, cells={cells}, worst setup slack={setup} ps (clock {period} ps),
power={power} W (ratio-only reliability). This design PASSES all gates.
{ref_note}

{sta_block}

## Your strategy for THIS attempt: {strategy_key}
{directive}

{budget}

## RTL (files you may rewrite)
{rtl}

Think briefly about which file/expression is on the critical path given the
STA profile, then output every modified file as:
// FILE: <basename>.v
<complete file content>
"""


@dataclass
class PromptContext:
    ip: str
    files: dict[str, str]
    ppa: dict
    sta_block: str
    playbook_block: str
    dossier: str
    weights: dict
    budget_line: str
    ref_note: str = ""


def build_prompt(ctx: PromptContext, strategy: dict) -> str:
    spec = IPS[ctx.ip]
    latency_note = (" (this IP's TB is handshake-based; latency changes are "
                    "allowed ONLY if strategy says so)"
                    if spec.compare_mode == "transaction" else "")
    rtl = "\n\n".join(f"// FILE: {Path(rel).name}\n{text}"
                      for rel, text in sorted(ctx.files.items()))
    period = ""
    m = re.search(r"period=([\d.]+)ps", ctx.sta_block)
    if m:
        period = m.group(1)
    return _TEMPLATE.format(
        weights=ctx.weights, hard_rules=_HARD_RULES.format(latency_note=latency_note),
        dossier=ctx.dossier, playbook=ctx.playbook_block, ip=ctx.ip,
        area=ctx.ppa.get("area"), cells=ctx.ppa.get("cells"),
        setup=ctx.ppa.get("setup"), period=period or "?",
        power=ctx.ppa.get("power"), ref_note=ctx.ref_note,
        sta_block=ctx.sta_block, strategy_key=strategy["key"],
        directive=strategy["directive"], budget=ctx.budget_line, rtl=rtl)


def parse_response(ip: str, text: str) -> dict[str, str]:
    """'// FILE: name.v' blocks -> {repo-relative path: content}.

    Fallback (real-model finding, 2026-07-12: Gemini often emits plain
    fenced code blocks despite the FILE-block instruction): map each
    ``` fence to a source file by its declared module name."""
    spec = IPS[ip]
    out = {}
    for name, code in re.findall(
            r"//\s*FILE:\s*(\S+\.s?v)\s*\n(.*?)(?=//\s*FILE:|\Z)",
            text, re.DOTALL):
        code = re.sub(r"^```\w*\s*$", "", code, flags=re.M).strip()
        if code:
            out[f"{spec.rtl_dir}/{Path(name).name}"] = code + "\n"
    if out:
        return out
    stems = {Path(s).stem: s for s in spec.sources}
    for block in re.findall(r"```(?:\w+)?\s*\n(.*?)```", text, re.DOTALL):
        block = block.strip()
        m = re.search(r"\bmodule\s+([A-Za-z_]\w*)\b", block)
        if m and m.group(1) in stems and "endmodule" in block:
            out[stems[m.group(1)]] = block + "\n"
    return out


# ── repair + reflection prompts ───────────────────────────────────────────────
_REPAIR_TMPL = """Your previous Verilog rewrite FAILED to compile/elaborate. Fix ONLY the
errors below; preserve the optimization intent and all interface contracts
(ports, parameters, latency). Synthesizable Verilog-2001/2005.

## Tool errors
{errors}

## The files you produced (broken)
{rtl}

Return every corrected file as:
// FILE: <basename>.v
<complete file content>
"""


def build_repair_prompt(files: dict[str, str], errors: str) -> str:
    rtl = "\n\n".join(f"// FILE: {Path(rel).name}\n{text}"
                      for rel, text in sorted(files.items()))
    return _REPAIR_TMPL.format(errors=errors[:3000], rtl=rtl)


_REFLECT_TMPL = """You are the reflector for an RTL PPA-optimization agent. Below are this
round's candidate outcomes on `{ip}` and the playbook bullets that were in
context. Extract durable lessons.

## Outcomes
{outcomes}

## Playbook bullets that were in context
{bullets}

Respond ONLY with lines in these exact formats (0-3 lines each; nothing else):
VOTE <bullet-id> helpful|harmful
ADD <section:timing|area|power|pitfall|avoid> <tag> <one-sentence lesson>
"""


def build_reflect_prompt(ip: str, outcomes: list[str], bullets: list[dict]) -> str:
    return _REFLECT_TMPL.format(
        ip=ip, outcomes="\n".join(outcomes) or "(none)",
        bullets="\n".join(f"[{b['id']}] {b['content'][:120]}" for b in bullets))


def parse_reflection(text: str) -> tuple[list[tuple[str, bool]], list[tuple[str, str, str]]]:
    votes, adds = [], []
    for line in text.splitlines():
        m = re.match(r"VOTE\s+(\S+)\s+(helpful|harmful)", line.strip())
        if m:
            votes.append((m.group(1), m.group(2) == "helpful"))
            continue
        m = re.match(r"ADD\s+(timing|area|power|pitfall|avoid)\s+(\S+)\s+(.+)",
                     line.strip())
        if m:
            adds.append((m.group(1), m.group(2), m.group(3).strip()))
    return votes, adds


# ── models ────────────────────────────────────────────────────────────────────
class Model:
    calls = 0
    tokens = 0

    def generate(self, prompt: str) -> str:
        raise NotImplementedError

    def _count(self, prompt: str, resp: str):
        self.calls += 1
        self.tokens += (len(prompt) + len(resp)) // 4   # rough chars/4


class StubModel(Model):
    """Offline loop testing. Replays queued variant dirs (each dir of .v files
    becomes one response); echoes 'no change' when the queue is empty."""

    def __init__(self, replay_dirs: list[Path] | None = None):
        self.queue = list(replay_dirs or [])

    def generate(self, prompt: str) -> str:
        if not self.queue:
            resp = "STUB: no further variants queued — no change proposed."
        else:
            d = Path(self.queue.pop(0))
            blocks = [f"// FILE: {f.name}\n{f.read_text()}"
                      for f in sorted(d.glob("*.v"))]
            resp = "\n".join(blocks) if blocks else "STUB: empty variant dir."
        self._count(prompt, resp)
        return resp


class VertexModel(Model):
    """Gemini via google-genai. Two key modes, auto-detected:
      EXPRESS_MODE_KEY -> Vertex AI Express Mode (AgentSetup.md; how the
                          organizers evaluate at DAC)
      GEMINI_API_KEY   -> AI Studio key (personal-subscription dev fallback)
    """

    def __init__(self, model_name: str = "gemini-3-flash-preview",
                 temperature: float = 0.2, top_p: float = 0.6,
                 thinking_budget: int = 8192):
        try:
            from google import genai
        except ImportError as e:
            raise SystemExit(
                "google-genai is not installed — run `pip install "
                "google-genai` (AgentSetup.md step 1)") from e
        if os.environ.get("EXPRESS_MODE_KEY"):
            self.client = genai.Client(
                vertexai=True, api_key=os.environ["EXPRESS_MODE_KEY"])
            self.mode = "vertex-express"
        elif os.environ.get("GEMINI_API_KEY"):
            self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            self.mode = "ai-studio"
        else:
            raise SystemExit(
                "no API key: set EXPRESS_MODE_KEY (Vertex Express Mode, "
                "AgentSetup.md) or GEMINI_API_KEY (AI Studio)")
        self.model_name = model_name
        # LIVE FINDING 2026-07-12: gemini-3-flash-preview is a thinking
        # model; with default config it burned 63k thought tokens into the
        # default cap and returned EMPTY text (finish=MAX_TOKENS, 0 parts).
        # Explicit output budget + bounded thinking is mandatory.
        self.gen_cfg = {"temperature": temperature, "top_p": top_p,
                        "max_output_tokens": 65536,
                        "thinking_config": {"thinking_budget": thinking_budget}}

    _RETRYABLE = (429, 500, 502, 503, 504)

    def generate(self, prompt: str, max_retries: int = 6) -> str:
        from google.genai.errors import APIError
        delay = 2
        for attempt in range(max_retries):
            try:
                r = self.client.models.generate_content(
                    model=self.model_name, contents=prompt,
                    config=self.gen_cfg)
                self.calls += 1
                usage = getattr(r, "usage_metadata", None)
                if usage:
                    # total includes THOUGHT tokens — what billing/eval sees
                    self.tokens += (usage.total_token_count or
                                    (usage.prompt_token_count or 0) +
                                    (usage.candidates_token_count or 0))
                else:
                    self.tokens += (len(prompt) + len(r.text or "")) // 4
                text = r.text or ""
                if not text.strip() and attempt < max_retries - 1:
                    # thinking model returned no visible text (MAX_TOKENS
                    # mid-thought) — one more try is usually enough
                    time.sleep(delay)
                    continue
                return text
            except APIError as e:
                if (getattr(e, "code", None) in self._RETRYABLE
                        and attempt < max_retries - 1):
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                raise
        raise RuntimeError("max retries exceeded")


class EndpointModel(Model):
    """NXP-runner-style local model service: POST {endpoint}/generate with
    {model, prompt, max_output_tokens} -> {"text": ...}. Kept in case the
    NVIDIA eval harness fronts Vertex with an endpoint the way the NXP
    runner does; also lets the NXP mock endpoint smoke this agent offline."""

    def __init__(self, endpoint: str,
                 model_name: str = "gemini-3-flash-preview",
                 max_output_tokens: int = 8192):
        self.endpoint = endpoint.rstrip("/")
        self.model_name = model_name
        self.max_output_tokens = max_output_tokens

    _RETRYABLE = (429, 500, 502, 503, 504)

    def generate(self, prompt: str, max_retries: int = 6) -> str:
        import json as _json
        import urllib.error
        import urllib.request
        payload = _json.dumps({
            "model": self.model_name, "prompt": prompt,
            "max_output_tokens": self.max_output_tokens}).encode()
        delay, last = 2, "no attempt"
        for attempt in range(max_retries):
            retryable = False
            try:
                req = urllib.request.Request(
                    self.endpoint + "/generate", data=payload,
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=600) as resp:
                    body = _json.loads(resp.read().decode())
                if body.get("text") is not None:
                    self._count(prompt, body["text"])
                    return body["text"]
                last = body.get("error", "no text in response")
                retryable = bool(body.get("retryable")) or \
                    body.get("provider_status") in self._RETRYABLE
            except urllib.error.HTTPError as e:
                last, retryable = f"HTTP {e.code}", e.code in self._RETRYABLE
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last, retryable = f"{type(e).__name__}: {e}", True
            if retryable and attempt < max_retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            break
        raise RuntimeError(f"endpoint model failed ({last})")


def make_model(kind: str, **kw) -> Model:
    if kind == "vertex":
        return VertexModel(**kw)
    if kind == "endpoint":
        return EndpointModel(**kw)
    return StubModel(**kw)
