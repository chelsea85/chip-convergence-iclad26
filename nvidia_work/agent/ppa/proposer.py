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
from .cone_templates import catalog_text as _cone_catalog_text

# audited template catalog for the small-cone-arrival-template rung (each
# entry exhaustively verified by ppa/cone_templates.verify_all)
_cone_catalog = _cone_catalog_text()

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
                   "redundant +/-1 or shifted values from one computation. "
                   "Keep every register and FSM encoding exactly as-is."),
    dict(key="arith-arch", axis="perf",
         directive="Swap the architecture of ONE critical-path arithmetic "
                   "operator (adder tree style: Kogge-Stone / Brent-Kung / "
                   "Sklansky; or compressor-tree multiplier). One operator "
                   "only, keep everything else untouched."),
    dict(key="activity-reduce", axis="power",
         directive="Reduce switching activity: operand isolation for unused "
                   "units, enable-gated registers, replace physically "
                   "shifting register banks with pointer-addressed buffers."),
    # ── timing-targeted rungs v2 (2026-07-23, Codex expanded literature
    #    review `NVIDIA_TIMING_STRATEGY_EXPANDED_LITERATURE_REVIEW.md` §5/§14:
    #    the approved DAC-ready five). All cycle-exact, register-preserving,
    #    combinational-only — the LEC-provable class. v1's fanout-duplicate
    #    and arrival-aware-restructure were REJECTED by the review (generic
    #    duplication needs load evidence; freehand arrival reordering is a
    #    synthesis algorithm, not a prompt) and are removed. ──
    dict(key="sum-cluster-expose", axis="perf",
         directive="Find exactly ONE critical chain of two or more additions "
                   "separated only by a one-use combinational intermediate. "
                   "Inline that intermediate so synthesis sees one "
                   "fixed-width multi-operand sum (letting it build a "
                   "carry-save tree with a single final carry-propagate "
                   "adder). Preserve signedness and modulo width; list every "
                   "original and resulting width. Do NOT flatten across an "
                   "observable truncation, carry, comparison, selector, "
                   "address, saturation point, or a second consumer, and do "
                   "NOT manually implement full-adder sum/carry bits."),
    dict(key="xor-depth-resynthesize", axis="perf",
         directive="Optimize exactly ONE strictly linear GF(2) cone "
                   "(XOR/XNOR/NOT/constants only — no AND, OR, carry, mux, "
                   "compare, or control). BEFORE changing RTL, list each "
                   "output bit as the exact XOR-support set of input bits "
                   "plus affine constant; the rewritten cone must have "
                   "IDENTICAL support sets. Use arrival-aware XOR trees and "
                   "share partial XORs only where sharing does not increase "
                   "the critical output's depth. Bit order and widths "
                   "untouched."),
    dict(key="late-input-cofactor", axis="perf",
         directive="Apply cofactor expansion to exactly ONE bounded "
                   "combinational cone with ONE identified late-arriving "
                   "1-bit control (from the timing-path report). Derive the "
                   "control=0 and control=1 functions from the original "
                   "expression, compute both early, and use the late control "
                   "only at the cone output. Keep the duplicated cone small; "
                   "preserve priority, defaults, X behavior, and widths. Do "
                   "not convert if/case/?: into a different semantic form."),
    dict(key="priority-prefix-select", axis="perf",
         directive="Rewrite ONE wide priority chain using an exact "
                   "prefix-priority form: each grant = its own condition AND "
                   "no earlier condition. Preserve the original winner for "
                   "EVERY simultaneous-condition combination and the "
                   "no-match default. Do NOT assume one-hotness, full "
                   "coverage, or two-state inputs."),
    dict(key="compare-decode-prefix", axis="perf",
         directive="Optimize ONE critical wide comparison, range check, or "
                   "address decode. State the relation, signedness, width, "
                   "constants and inclusive/exclusive boundaries, then use "
                   "an exact prefix comparison or high-bit aligned-range "
                   "form. Remove lower bits ONLY when the constants prove "
                   "they cannot affect the result. Preserve == versus === "
                   "and all defaults."),
    dict(key="small-cone-arrival-template", axis="perf",
         directive="Select exactly ONE combinational Boolean cone with at "
                   "most five scalar inputs on the critical path. Reproduce "
                   "its complete truth behavior from the source, identify "
                   "the LATE input from the timing-path report, then apply "
                   "ONE template from the verified set below — mapping your "
                   "cone's signals onto it. Do NOT invent a new network "
                   "shape; if no template matches, make no edit.\n"
                   + _cone_catalog),
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
- Do NOT re-encode FSM state or merge/split/rename registers: equivalence is
  certified register-to-register, so register-structure changes can never be
  proven and will never ship, no matter how good their PPA looks.
- ONE cone / ONE named transform per proposal. Begin your answer with a short
  ledger: which transform you applied, the exact cone touched, and every
  changed signal's original->new width and signedness (for XOR cones: the
  per-output-bit XOR support sets, which must be identical before and after).
- If the strategy's preconditions are NOT present in the provided files, say
  so and make NO edit rather than forcing an inapplicable transform.
- Synthesizable Verilog-2001/2005 only; no initial blocks, no latches.
- Return COMPLETE file contents for every file you modify (and only those).{fence}"""

# Per-IP scope fences (prompt text + tooling-enforced forbidden substrings in
# any changed file). aes: keep the security S-box as-is — a masked->unmasked
# swap would "win" PPA by DELETING a side-channel countermeasure, which is not
# an RTL optimization. Optimize the datapath instead.
FENCE = {
    "aes": {
        "prompt": ("\n- SCOPE FENCE (aes): Do NOT change the S-box security "
                   "implementation. Do NOT modify SecSBoxImpl, the "
                   "SBoxImpl/masking selection, or any aes_sbox_*.v file. "
                   "Optimize the cipher datapath, key expansion, MixColumns, "
                   "and GF(2^8) arithmetic ONLY."),
        "forbid_files": ("aes_sbox_canright", "aes_sbox_lut", "aes_sbox_dom",
                         "aes_sbox_canright_masked"),
        "forbid_substr": ("SecSBoxImpl =", "SecSBoxImpl=", "SecSBoxImpl  ="),
    },
    # kmac (2026-07-24): the Keccak core is the DOM-MASKED (side-channel
    # protected) implementation. XOR re-sharing there can be LOGICALLY
    # equivalent yet merge the two shares and destroy the countermeasure —
    # LEC proves logic, not masking. Same principle as the aes S-box fence:
    # deleting a security property is not an RTL optimization.
    "kmac": {
        "prompt": ("\n- SCOPE FENCE (kmac): Do NOT modify the masked Keccak "
                   "core: keccak_2share.v, keccak_round.v, or any prim_dom_* "
                   "file. Their share-separation structure is a side-channel "
                   "countermeasure; re-sharing XORs across shares breaks it "
                   "even when logically equivalent. Optimize the application "
                   "interface, TL-UL logic, padding, and FIFOs ONLY."),
        "forbid_files": ("keccak_2share", "keccak_round", "prim_dom_and"),
        "forbid_substr": (),
    },
    # NVDLA (2026-07-24 buildout): mandatory first-campaign fence. The
    # measured worst paths are reset-distribution artifacts, and the first
    # campaign is deliberately restricted to one ordinary datapath leaf.
    # Path checks are tooling-enforced even when a caller omits --fence.
    "nvdla": {
        "mandatory": True,
        "prompt": (
            "\n- SCOPE FENCE (nvdla, mandatory): Edit exactly the selected "
            "ordinary datapath leaf. Do NOT modify reset/synchronizer/CDC or "
            "clock-and-reset (car) logic; RAM/vlibs/include/build sources; "
            "partition tops; or APB/CSB/NOCIF/MCIF/CVIF bus interfaces. "
            "Do not chase reset-distribution timing paths."),
        "forbid_files": (),
        "forbid_substr": (),
        "forbid_path_regex": (
            r"(?i)(?:^|/)(?:car|vlibs|rams|include)(?:/|$)",
            r"(?i)(?:^|/)(?:apb2csb|csb_master|nocif)(?:/|$)",
            r"(?i)(?:^|/)[^/]*(?:reset|cdc|ssync|sync\d*)[^/]*\.v$",
            r"(?i)(?:^|/)top/NV_NVDLA_partition_[acmop]\.v$",
            r"(?i)(?:^|/)[^/]*(?:mcif|cvif|dmaif|csb|apb2csb)[^/]*\.v$",
        ),
    },
}


def fence_violation(ip: str, files: dict) -> str | None:
    """Return a reason string if a candidate breaches the IP's scope fence,
    else None. Tooling enforcement of the prompt fence above.

    PRESENCE of a fenced token is not a breach: pristine files legitimately
    carry pass-through lines (aes_core.v declares/forwards SecSBoxImpl), and
    candidates return COMPLETE files. Flag only if the token-bearing lines
    actually DIFFER from pristine (2026-07-14: presence-check falsely wiped
    an entire aes_core stage)."""
    f = FENCE.get(ip)
    if not f:
        return None
    for rel, text in files.items():
        stem = rel.rsplit("/", 1)[-1]
        for pat in f.get("forbid_path_regex", ()):
            if re.search(pat, rel):
                return f"fence: forbidden path {rel}"
        if any(bad in stem for bad in f.get("forbid_files", ())):
            return f"fence: modified protected implementation file {stem}"
        for sub in f.get("forbid_substr", ()):
            if sub not in text:
                continue
            token = sub.strip().rstrip("=").strip()
            try:
                from .workspace import pristine_source
                pris = pristine_source(ip, rel)
            except Exception:
                return f"fence: changed {token}"   # can't verify → conservative
            norm = lambda t: sorted(" ".join(l.split()) for l in t.splitlines()
                                    if token in l)
            if norm(text) != norm(pris):
                return f"fence: changed {token}"
            break   # token lines identical to pristine — pass-through, fine
    return None

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
    readonly_files: dict = None       # {rel: content} shown but NOT editable
                                      # (already-locked / dependency files)
    scope_note: str = ""              # staged mode: warns that out-of-scope
                                      # edits are discarded
    iface_block: str = ""             # config C: interface stubs of the
                                      # modules the batch file instantiates
    fence: bool = False               # scope fence (e.g. aes S-box). Default
                                      # OFF (2026-07-14, Hari): the contest
                                      # scores tests-pass + PPA only — no
                                      # self-imposed restrictions. "on" kept
                                      # as a DAC-day option.


def build_prompt(ctx: PromptContext, strategy: dict) -> str:
    spec = IPS[ctx.ip]
    latency_note = (" (this IP's TB is handshake-based; latency changes are "
                    "allowed ONLY if strategy says so)"
                    if spec.compare_mode == "transaction" else "")
    rtl = "\n\n".join(f"// FILE: {Path(rel).name}\n{text}"
                      for rel, text in sorted(ctx.files.items()))
    # read-only context: already-optimised/dependency files the model must
    # understand but NOT edit (coordinate descent — locked wins carried forward)
    if ctx.readonly_files:
        ro = "\n\n".join(f"// READ-ONLY (do not edit): {Path(rel).name}\n{text}"
                         for rel, text in sorted(ctx.readonly_files.items()))
        rtl = ("// ── READ-ONLY CONTEXT (already optimised / dependencies — "
               "understand these, do NOT return them) ──\n" + ro +
               "\n\n// ── FILES TO OPTIMISE (return complete, only these) ──\n"
               + rtl)
    if ctx.iface_block:
        rtl = ("// ── SUBMODULE INTERFACES (read-only reference: port "
               "contracts of modules instantiated by the file(s) below; "
               "bodies omitted, do NOT return these) ──\n" + ctx.iface_block +
               "\n\n// ── FILES TO OPTIMISE (return complete, only these) ──\n"
               + rtl)
    if ctx.scope_note:
        rtl = ctx.scope_note + "\n\n" + rtl
    period = ""
    m = re.search(r"period=([\d.]+)ps", ctx.sta_block)
    if m:
        period = m.group(1)
    return _TEMPLATE.format(
        weights=ctx.weights,
        hard_rules=_HARD_RULES.format(
            latency_note=latency_note,
            fence=(FENCE.get(ctx.ip, {}).get("prompt", "")
                   if (ctx.fence
                       or FENCE.get(ctx.ip, {}).get("mandatory", False))
                   else "")),
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


_GATEFAIL_REPAIR_TMPL = """Your Verilog rewrite is CLOSE: it compiles and — good news — synthesis
shows it IMPROVES timing/PPA ({ppa_note}). But it is FUNCTIONALLY INCORRECT:
functional verification fails (testbench cases and/or differential simulation
mismatches vs the original design), so it cannot be accepted yet.

{errors}

Your transformation is on the right track. Find the FUNCTIONAL BUG (a wrong
index/bit-width, a mis-ordered operand, an off-by-one in a tree/pipeline, a
sign issue) WITHOUT undoing the optimization — keep the PPA gain, just make it
produce identical outputs to the original. Preserve all interface contracts
(ports, parameters, cycle latency). Synthesizable Verilog-2001/2005.

## The files you produced (functionally broken but PPA-improving)
{rtl}

Return every corrected file as:
// FILE: <basename>.v
<complete file content>
"""


def build_gatefail_repair_prompt(files: dict[str, str], tb_detail: str,
                                 ppa_note: str) -> str:
    rtl = "\n\n".join(f"// FILE: {Path(rel).name}\n{text}"
                      for rel, text in sorted(files.items()))
    return _GATEFAIL_REPAIR_TMPL.format(
        errors=(tb_detail or "the functional testbench reported mismatches")[:2000],
        ppa_note=ppa_note, rtl=rtl)


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
    calls = 0            # ALL model calls (proposals + reflector + repair)
    proposal_calls = 0   # candidate proposals only — the turn budget
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
                 thinking_budget: int = 8192, key_env: str | None = None):
        try:
            from google import genai
        except ImportError as e:
            raise SystemExit(
                "google-genai is not installed — run `pip install "
                "google-genai` (AgentSetup.md step 1)") from e
        # key_env pins a specific env var (multi-account parallelism); else
        # auto-detect. Express keys use the Vertex client; AI-Studio keys the
        # plain client. Express keys carry an 'AQ.'-style prefix but so can
        # some AI-Studio keys, so mode follows the ENV NAME, not the value:
        # *EXPRESS* -> vertex, anything else -> ai-studio.
        candidates = ([key_env] if key_env else
                      ["EXPRESS_MODE_KEY", "GEMINI_API_KEY", "GEMINI_API_KEY_2"])
        name = next((n for n in candidates if os.environ.get(n)), None)
        if not name:
            raise SystemExit(
                f"no API key in env {candidates}: set EXPRESS_MODE_KEY "
                f"(Vertex Express) or GEMINI_API_KEY* (AI Studio)")
        key = os.environ[name]
        # HTTP timeout (ms): without it a hung socket stalls a campaign
        # FOREVER inside generate() — no exception, nothing for the retry
        # ladder or the resilient fan-out to catch (2026-07-14: aes stage 5
        # hung 47 min). 5 min/attempt >> any real response incl. thinking.
        _http = {"timeout": 300_000}
        if "EXPRESS" in name.upper():
            # X-Goog-User-Project header per the contest AgentSetup.md — an
            # Express-Mode requirement in the organizers' eval environment.
            _http_ex = dict(_http, headers={"X-Goog-User-Project": ""})
            self.client = genai.Client(vertexai=True, api_key=key,
                                       http_options=_http_ex)
            self.mode = f"vertex-express[{name}]"
        else:
            self.client = genai.Client(api_key=key, http_options=_http)
            self.mode = f"ai-studio[{name}]"
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
