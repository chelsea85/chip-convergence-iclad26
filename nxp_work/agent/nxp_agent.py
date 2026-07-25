#!/usr/bin/env python3
"""
NXP SoC-Generation Agent — model-pluggable (Chip Convergence).

Two invocation modes:

  RUNNER (contest contract, AGENT_GUIDE.md — how hidden testcases run at DAC):
      python3 nxp_agent.py <info_json_path> --model <model_name>
    Paths come from info.json; ALL model calls go to its `model_endpoint`
    (POST /generate, exponential backoff on retryable errors); all generated
    .v files land in `output_dir`. Exits 0 once best-effort RTL is written —
    internal gates are quality control, not the contest verdict, so a soft
    gate failure must never zero out a run via a non-zero exit.

  DEV (local, this repo):
      python3 nxp_agent.py --model stub [--deep]     # offline e2e, expect 30/30
      python3 nxp_agent.py --model vertex [--deep]   # needs EXPRESS_MODE_KEY
    Exit code = internal gate verdict.

Pipeline: architecture doc -> [model] YAML per IP (validated BEFORE any
generation; error-fed re-prompts) -> rtl_gen_lib generates Verilog ->
[model] stitch top (port contract + reset lint + structural diff,
non-bypassable, <=3 re-prompts) -> self-check gate (fractional score,
first-fail stage) -> optional STG differential (--deep, dev easy-tier only).

Stdlib-only by design: the guaranteed eval environment is python3 + iverilog.
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, time
from pathlib import Path

import validators as V

HERE = Path(__file__).resolve().parent              # .../nxp_work/agent
NXP  = HERE.parent                                   # .../nxp_work
SELFCHECK_TB = NXP/"tb/tb_selfcheck.v"               # ships with the agent
REF_SPECS    = NXP/"specs"                           # stub's reference YAML
REF_TOP      = NXP/"rtl/secure_periph_soc.v"         # stub's reference top


# ── Paths (dev repo layout vs runner info.json) ───────────────────────────────
class Paths:
    def __init__(self, arch, tb_skeleton, rtl_gen, out_dir, tmp_dir,
                 ledger, problem="easy"):
        self.arch, self.tb_skeleton, self.rtl_gen = arch, tb_skeleton, rtl_gen
        self.out_dir, self.tmp_dir = out_dir, tmp_dir
        self.ledger, self.problem = ledger, problem

    @staticmethod
    def _resolve_arch(doc: Path) -> Path | None:
        """Runner/docs name architecture.md but only .html ships — accept
        whichever exists."""
        cands = [doc, doc.with_suffix(".html"), doc.with_suffix(".md")]
        return next((p for p in cands if p.is_file()), None)

    @classmethod
    def dev(cls) -> "Paths":
        repo = (HERE.parents[1] / "ICLAD-Hackathon-2026" /
                "problem-categories" / "ICLAD26-NXP-Problems")
        assert repo.is_dir(), f"contest repo not found: {repo}"
        return cls(
            arch=cls._resolve_arch(repo/"problems/easy/docs/architecture.html"),
            tb_skeleton=repo/"problems/easy/tb/tb_top_skeleton.v",
            rtl_gen=repo/"rtl_gen_lib/rtl_gen_main.py",
            out_dir=NXP/"agent_out/rtl", tmp_dir=NXP/"agent_out/tmp",
            ledger=HERE/"ledger.jsonl", problem="easy")

    @classmethod
    def from_info(cls, info: dict) -> "Paths":
        tmp = Path(info["temp_dir"])
        return cls(
            arch=cls._resolve_arch(Path(info["architecture_doc"])),
            tb_skeleton=Path(info["tb_skeleton"]),
            rtl_gen=Path(info["rtl_gen_lib"])/"rtl_gen_main.py",
            out_dir=Path(info["output_dir"]), tmp_dir=tmp,
            ledger=tmp/"ledger.jsonl", problem=info.get("problem", "easy"))


# ── Model interface ───────────────────────────────────────────────────────────
class Model:
    calls = 0
    def generate(self, prompt: str) -> str: raise NotImplementedError

class StubModel(Model):
    """No-network. Returns our hand-derived reference (keys off a TASK marker)."""
    def generate(self, prompt: str) -> str:
        if "TASK: YAML" in prompt:
            return "\n\n".join("```yaml\n" + y.read_text().strip() + "\n```"
                               for y in sorted(REF_SPECS.glob("*.yaml")))
        if "TASK: TOP" in prompt:
            return "```verilog\n" + REF_TOP.read_text() + "```"
        return "STUB: unrecognized task"

class VertexModel(Model):
    """Direct Gemini via google-genai (dev only; the contest runner routes
    model traffic through its own endpoint instead). Keys auto-detected:
    EXPRESS_MODE_KEY (Vertex Express, AgentSetup.md) or GEMINI_API_KEY
    (AI Studio personal key)."""
    def __init__(self, model_name="gemini-3-flash-preview"):
        try:
            from google import genai
        except ImportError as e:
            raise SystemExit("google-genai is not installed — "
                             "`pip install google-genai`") from e
        if os.environ.get("EXPRESS_MODE_KEY"):
            self.client = genai.Client(
                vertexai=True, api_key=os.environ["EXPRESS_MODE_KEY"],
                http_options={"headers": {"X-Goog-User-Project": ""}})
        elif os.environ.get("GEMINI_API_KEY"):
            self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        else:
            raise SystemExit("no API key: set EXPRESS_MODE_KEY or "
                             "GEMINI_API_KEY")
        self.model_name = model_name
    # LIVE FINDING 2026-07-12: gemini-3-flash-preview thinks by default and
    # can burn the whole token cap on thoughts (empty text, MAX_TOKENS) —
    # explicit output budget + bounded thinking is mandatory.
    GEN_CFG = {"max_output_tokens": 65536,
               "thinking_config": {"thinking_budget": 8192}}

    def generate(self, prompt: str, max_retries=5) -> str:
        from google.genai.errors import APIError
        delay = 2
        for attempt in range(max_retries):
            try:
                self.calls += 1
                text = self.client.models.generate_content(
                    model=self.model_name, contents=prompt,
                    config=self.GEN_CFG).text or ""
                if not text.strip() and attempt < max_retries - 1:
                    time.sleep(delay); continue
                return text
            except APIError as e:
                if getattr(e, "code", None) in (429, 500, 502, 503, 504) \
                        and attempt < max_retries-1:
                    time.sleep(delay); delay = min(delay*2, 60); continue
                raise
        raise RuntimeError("max retries exceeded")

class EndpointModel(Model):
    """Contest model service (AGENT_GUIDE.md): POST {endpoint}/generate with
    {model, prompt, max_output_tokens}; success -> {"text": ...}; on
    retryable errors / 429/5xx back off exponentially. Token usage is logged
    by the service itself to usage_path — we only count calls."""
    def __init__(self, endpoint: str, model_name: str, max_output_tokens=8192,
                 total_deadline_s=900, per_attempt_timeout_s=600, _sleep=None):
        self.endpoint = endpoint.rstrip("/")
        self.model_name = model_name
        self.max_output_tokens = max_output_tokens
        self.total_deadline_s = total_deadline_s      # monotonic budget/call
        self.per_attempt_timeout_s = per_attempt_timeout_s
        self._sleep = _sleep or time.sleep            # injectable for tests

    def generate(self, prompt: str, max_retries=6) -> str:
        """Typed, deadline-bounded. MALFORMED RESPONSES (truncated/invalid-JSON,
        bad UTF-8, non-mapping body, missing/empty/non-string text) are typed
        transient failures that retry within budget — never uncaught
        exceptions (Codex hardening §4.3). Retries obey one monotonic total
        deadline; the last attempt caps its socket timeout to the remaining
        budget. Failure reasons never include response content or secrets."""
        import urllib.request, urllib.error
        payload = json.dumps({"model": self.model_name, "prompt": prompt,
                              "max_output_tokens": self.max_output_tokens}
                             ).encode()
        start = time.monotonic()
        delay, last = 2, "no attempt made"
        for attempt in range(max_retries):
            remaining = self.total_deadline_s - (time.monotonic() - start)
            if remaining <= 0:
                last = f"total deadline {self.total_deadline_s}s exhausted"
                break
            self.calls += 1
            retryable = False
            try:
                req = urllib.request.Request(
                    self.endpoint + "/generate", data=payload,
                    headers={"Content-Type": "application/json"})
                timeout = min(self.per_attempt_timeout_s, remaining)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                # ── typed response-shape validation (was uncaught) ──────────
                try:
                    body = json.loads(raw.decode("utf-8"))
                except UnicodeDecodeError:
                    last, retryable = "invalid UTF-8 in response", True
                    body = None
                except json.JSONDecodeError:
                    last, retryable = "malformed/truncated JSON response", True
                    body = None
                if body is not None:
                    if not isinstance(body, dict):
                        last, retryable = \
                            f"response not a JSON object ({type(body).__name__})", True
                    else:
                        txt = body.get("text")
                        if isinstance(txt, str) and txt != "":
                            return txt
                        if txt is not None and not isinstance(txt, str):
                            last, retryable = "response 'text' not a string", True
                        else:  # missing/null/empty text: default transient,
                               # honor an explicit retryable=false
                            last = body.get("error", "empty/missing text in response")
                            rt = body.get("retryable")
                            retryable = (rt if isinstance(rt, bool) else True) \
                                or body.get("provider_status") in (429, 500, 502, 503, 504)
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
                retryable = e.code in (429, 500, 502, 503, 504)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last, retryable = f"{type(e).__name__}", True
            if retryable and attempt < max_retries - 1 and \
                    (time.monotonic() - start) + delay < self.total_deadline_s:
                self._sleep(delay); delay = min(delay * 2, 60); continue
            break
        raise RuntimeError(f"model endpoint failed ({last})")

def make_model(kind): return VertexModel() if kind == "vertex" else StubModel()

# ── Pipeline steps ────────────────────────────────────────────────────────────
SUPPORTED = ("sync_fifo async_fifo sram_sp sram_dp reset_sync cdc_sync apb_uart apb_gpio "
             "apb_timer apb_watchdog irq_aggregator ahb_to_apb_bridge apb_fabric "
             "axi_lite_crossbar axi_lite_sram dma_engine perf_counter tilelink_router "
             "tilelink_ni aes128")

def read_spec(P: Paths) -> str:
    if P.arch is None: sys.exit("architecture doc not found")
    txt = P.arch.read_text(errors="replace")
    if P.arch.suffix == ".html":                    # strip tags to readable text for the model
        txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", txt, flags=re.S|re.I)
        txt = re.sub(r"<[^>]+>", " ", txt)
        txt = re.sub(r"[ \t]+", " ", txt)
    return txt

def demo_exemplars(P: Paths) -> str:
    """Scrape the library's own demo specs (rtl_gen_main.py --demo) — the
    authoritative param defaults when the diagram is silent (LIVE FINDING
    2026-07-12: uart default_div=26 exists NOWHERE in the architecture doc;
    only the library demo's 115200 @ 50 MHz implies it)."""
    src = Path(P.rtl_gen).read_text()
    out = []
    for typ, body in re.findall(r'\("([a-z_0-9]+)",\s*"(ip_type:[^"]+)"', src):
        out.append(body.replace("\\n", "; "))
    hint = ("NOTE: apb_uart default_div must be a NUMBER; if you know baud "
            "and clock: default_div = clk_freq_hz // (16*baud_rate) - 1 "
            "(e.g. 115200 baud @ 50 MHz -> 26).")
    return ("\n".join(out) + "\n" + hint) if out else hint


def doc_irq_map(spec_text: str) -> str:
    """Extract the architecture's explicit IRQ source map (doc-fact; the
    stitch prompt's truncated slice can miss it)."""
    m = re.search(r"src\[0\].{0,400}", spec_text)
    return m.group(0) if m else ""


def required_params_table(P: Paths) -> str:
    """Auto-extract each generator's required() calls — the ground-truth
    YAML schema, straight from the library source (LIVE FINDING 2026-07-12:
    the model omits required params unless told exactly which are needed)."""
    tbl = {}
    for f in Path(P.rtl_gen).parent.glob("gen_*.py"):
        for key, typ in re.findall(
                r"required\(spec,\s*\"(\w+)\",\s*\"(\w+)\"\)", f.read_text()):
            tbl.setdefault(typ, []).append(key)
    return "; ".join(f"{t}: {', '.join(ks)}" for t, ks in sorted(tbl.items()))


def prompt_yaml(spec, skel, req_tbl="", exemplars=""):
    return (f"TASK: YAML\nYou are an RTL architect for the NXP ICLAD 2026 EASY SoC.\n"
            f"From the architecture description, infer a YAML spec for EACH IP block.\n"
            f"ip_type must be one of: {SUPPORTED}.\n"
            + (f"REQUIRED params per ip_type — the generator REJECTS any spec "
               f"missing one (every spec also needs ip_type and name):\n"
               f"{req_tbl}\n" if req_tbl else "")
            + (f"## Library demo exemplars — prefer these values when the "
               f"diagram does not determine a param\n{exemplars}\n"
               if exemplars else "")
            + f"Emit each spec as its own separate ```yaml``` block (flat "
              f"key: value lines only, no nesting, no '---' separators) with "
              f"ip_type, name, ALL required params, and any inferred params.\n\n"
              f"## Architecture\n{spec[:8000]}\n\n## Top port contract\n{skel[:3000]}\n")

def module_interfaces(gen_files) -> str:
    """Port-contract index (DeepCode / spec 3.4): the EXACT module headers of
    the generated IPs, so the stitcher never guesses port names (LIVE FINDING
    2026-07-12: model invented 'irq_sources' for the actual 'irq_src')."""
    out = []
    for f in gen_files:
        text = Path(f).read_text()
        m = re.search(r"\bmodule\s+\w+.*?\);", text, re.S)
        if m:
            hdr = re.sub(r"[ \t]+", " ", m.group(0))
            out.append(hdr)
    return "\n\n".join(out)


def prompt_top(spec, skel, gen_files):
    irq_map = doc_irq_map(spec)
    return (f"TASK: TOP\nWrite secure_periph_soc.v stitching these generated IPs: "
            f"{', '.join(Path(f).name for f in gen_files)}.\nThe top module MUST be named "
            f"secure_periph_soc with EXACTLY the skeleton ports. Verilog-2001 (iverilog -g2005). "
            f"Wire CPU AHB -> bridge -> APB fabric -> slaves; the reset synchronizer drives the "
            f"system reset (por_n feeds ONLY it); aggregate all peripheral IRQs into the "
            f"aggregator's irq_src. Use the EXACT module and port names from the interfaces "
            f"below — do not invent or rename ports. Emit one ```verilog``` block.\n\n"
            f"## Generated IP interfaces (authoritative)\n{module_interfaces(gen_files)[:6000]}\n\n"
            + (f"## IRQ source map (from the architecture — wire irq_src "
               f"EXACTLY this way)\n{irq_map}\n\n" if irq_map else "")
            + f"## Architecture\n{spec[:4000]}\n\n## Port contract\n{skel[:4000]}\n")

def extract_blocks(text, kind):
    blocks = re.findall(rf"```(?:{kind})?\s*\n(.*?)```", text, re.DOTALL|re.IGNORECASE)
    if kind.startswith("yaml"):
        # models sometimes pack all specs into one fence with '---' separators
        blocks = [d for b in blocks for d in re.split(r"^---\s*$", b, flags=re.M)
                  if d.strip()]
    return blocks

def _rtl_gen_env() -> dict:
    """Env for the rtl_gen subprocess. The organizer's generator crashes
    (UnboundLocalError) when PyYAML is absent because its `_load_yaml_minimal`
    fallback is broken and PyYAML is documented as OPTIONAL. PREFER installed
    PyYAML; only when it is absent, prepend our subprocess-local, fail-closed
    `_yaml_compat` shim to PYTHONPATH so the generator's `import yaml` resolves
    to it. Organizer sources are never modified. (Codex-approved, 2026-07-23.)"""
    env = dict(os.environ)
    try:
        import yaml  # noqa: F401  (same interpreter as the subprocess)
        return env
    except ImportError:
        shim = str(HERE / "_yaml_compat")
        prev = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = shim + (os.pathsep + prev if prev else "")
        return env


def generate_ip(yaml_text, idx, P: Paths) -> tuple[list, str]:
    """Run the library generator; returns (files, error). The generator IS
    the ground-truth spec validator — its MissingParameter errors are typed
    AND written to be model-readable ('Read the architecture docs
    carefully...'), i.e. purpose-built repair-prompt material."""
    P.tmp_dir.mkdir(parents=True, exist_ok=True)
    P.out_dir.mkdir(parents=True, exist_ok=True)
    yp = P.tmp_dir/f"spec_{idx}.yaml"; yp.write_text(yaml_text)
    r = subprocess.run([sys.executable, str(P.rtl_gen), "--spec", str(yp),
                        "--outdir", str(P.out_dir)], capture_output=True,
                       text=True, env=_rtl_gen_env())
    files = [l.split("]")[1].strip().split()[0] for l in r.stdout.splitlines()
             if l.startswith("[GEN]")]
    for f in files:                    # known library-bug fixups (see validators)
        text, notes = V.patch_library_rtl(Path(f).read_text())
        if notes:
            Path(f).write_text(text)
            print(f"    [fixup] {Path(f).name}: {'; '.join(notes)}")
    err = ""
    if not files:
        blob = (r.stderr or "") + (r.stdout or "")
        m = re.search(r"MissingParameter: (\[.*?\] Required parameter '\w+' "
                      r"is missing[^\n]*)", blob)
        if m:
            err = m.group(1)
        else:
            m = re.search(r"ERROR:[^\n]*", blob)
            lines = [l for l in blob.strip().splitlines() if l.strip()]
            err = m.group(0) if m else \
                (lines[-1] if lines else "generator produced no files")
    return files, err

def run_gate(P: Paths) -> dict:
    """Easy tier: compile generated RTL + our self-check TB, simulate, return
    a FRACTIONAL result (first failing test + stage = repair router signal).
    Unknown tiers (no tier-specific TB yet): elaboration gate against the
    skeleton TB only."""
    sim = P.tmp_dir/"sim_agent"
    vfiles = sorted(str(p) for p in P.out_dir.glob("*.v"))
    tb = SELFCHECK_TB if P.problem == "easy" else P.tb_skeleton
    c = subprocess.run(["iverilog","-g2005","-o",str(sim),*vfiles,str(tb)],
                       capture_output=True, text=True)
    if c.returncode != 0:
        return dict(ok=False, score=0.0, passed=0, total=0, stage="compile",
                    first_fail="compile", detail="COMPILE FAIL:\n"+c.stderr[-800:])
    if P.problem != "easy":
        return dict(ok=True, score=1.0, passed=0, total=0, stage=None,
                    first_fail=None, detail="skeleton elaboration OK "
                    f"(no self-check TB for tier '{P.problem}')")
    s = subprocess.run(["vvp",str(sim)], capture_output=True, text=True, timeout=300)
    stage, first_fail, fail_stage = "?", None, None
    for line in s.stdout.splitlines():
        sm = re.match(r"STAGE:\s*(\w+)", line)
        if sm: stage = sm.group(1)
        fm = re.match(r"\[FAIL\]\s*(\S+)", line)
        if fm and first_fail is None:
            first_fail, fail_stage = fm.group(1), stage
    m = re.search(r"TOTAL:\s*(\d+)\s*PASS,\s*(\d+)\s*FAIL", s.stdout)
    if not m:
        return dict(ok=False, score=0.0, passed=0, total=0, stage="sim",
                    first_fail="no-summary", detail=s.stdout[-500:])
    p, f = int(m[1]), int(m[2])
    total = p + f
    return dict(ok=(f == 0 and p > 0), score=(p/total if total else 0.0),
                passed=p, total=total, first_fail=first_fail,
                stage=fail_stage, detail=f"{p}/{total} PASS")


def params_from_yamls(yamls: list[str]) -> dict:
    """Inferred-YAML params -> ref_models.SoCModel overrides, so the KAT
    model path predicts against what the agent BELIEVES it built (a
    consistent misread is caught by the K-vote/doc-fact layers, not here)."""
    p = {}
    for y in yamls:
        s = V.parse_flat_yaml(y)
        t = s.get("ip_type")
        if t == "apb_uart":
            p["uart"] = {k: s[k] for k in ("fifo_depth", "default_div") if k in s}
        elif t == "apb_gpio":
            g = {}
            if "gpio_width" in s: g["width"] = s["gpio_width"]
            if "debounce_sync" in s: g["dbs"] = s["debounce_sync"]
            p["gpio"] = g
    return p


def ledger_append(P: Paths, rec: dict):
    P.ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(P.ledger, "a") as fh:
        fh.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}) + "\n")

# ── Main ──────────────────────────────────────────────────────────────────────
def run(model: Model, P: Paths, deep: bool = False):
    print(f"=== NXP agent (model={type(model).__name__}, problem={P.problem}) "
          f"— arch={P.arch.name if P.arch else '?'} ===")
    spec = read_spec(P); skel = P.tb_skeleton.read_text()
    # clean output dir
    P.out_dir.mkdir(parents=True, exist_ok=True)
    for p in P.out_dir.glob("*.v"): p.unlink()

    # Step 1: infer YAML specs, validated BEFORE any generation
    #         (deterministic AutoHarness-style legality gate; typed errors are
    #         cheap repair-prompt material)
    req_tbl = required_params_table(P)
    exemplars = demo_exemplars(P)
    resp = model.generate(prompt_yaml(spec, skel, req_tbl, exemplars))
    yamls = extract_blocks(resp, "yaml|yml")
    print(f"[1] model returned {len(yamls)} YAML spec block(s)")
    for attempt in range(2):
        ok_y, errs = V.yaml_validator(yamls)
        if ok_y:
            break
        print(f"[1v] YAML validator: {len(errs)} error(s): {errs[:4]}")
        if isinstance(model, StubModel):
            break
        resp = model.generate(prompt_yaml(spec, skel, req_tbl, exemplars) +
                              "\n\nYour previous specs had these errors — fix "
                              "ONLY these and re-emit ALL specs:\n- " +
                              "\n- ".join(errs))
        yamls = extract_blocks(resp, "yaml|yml")

    # Step 2: generate IP RTL — the deterministic library doubles as the
    # ground-truth spec validator (LIVE FINDING 2026-07-12: real model
    # omitted required params on 5/8 specs; failures were silent). Typed
    # generator errors are fed back for spec repair, ≤2 re-prompts.
    for gattempt in range(3):
        for p in P.out_dir.glob("*.v"):
            p.unlink()                       # no stale partials across retries
        gen, gerrs = [], []
        for i, y in enumerate(yamls):
            files, err = generate_ip(y, i, P)
            gen += files
            if err:
                tag = V.parse_flat_yaml(y).get("name") or f"spec#{i}"
                gerrs.append(f"{tag}: {err}")
        print(f"[2] generated {len(gen)} IP file(s): "
              f"{[Path(f).name for f in gen]}"
              + (f" | {len(gerrs)} spec(s) REJECTED by generator" if gerrs
                 else ""))
        if not gerrs or isinstance(model, StubModel):
            break
        print(f"[2v] generator rejections: {[e[:110] for e in gerrs[:4]]}")
        resp = model.generate(
            prompt_yaml(spec, skel, req_tbl, exemplars) +
            "\n\nThe RTL generator REJECTED some of your previous specs "
            "with these errors — fix ONLY these (add the missing required "
            "parameters, inferring values from the architecture) and "
            "re-emit ALL specs:\n- " + "\n- ".join(gerrs))
        yamls = extract_blocks(resp, "yaml|yml")

    # Step 3: write top — port contract + reset lint + structural diff are
    #         NON-BYPASSABLE (compile-fail=0 firewall; SLDB: models alter
    #         ports despite explicit instructions; structural diff catches
    #         stitch errors the TB can't localize)
    gen_mods = [Path(f).stem for f in gen]
    top_errs = []
    for attempt in range(3):
        top_resp = model.generate(
            prompt_top(spec, skel, gen) +
            ("" if not top_errs else
             "\n\nYour previous top violated the contract — fix ONLY these:\n- "
             + "\n- ".join(top_errs[:12])))
        tops = extract_blocks(top_resp, "verilog|v|systemverilog|sv")
        if not tops:
            print("[3] WARNING: model returned no top module"); break
        top_text = tops[0].strip() + "\n"
        ok_p, perrs = V.port_contract(top_text, skel)
        ok_r, rerrs = V.reset_lint(top_text)
        ok_s, serrs = V.structural_diff(top_text, gen_mods)
        top_errs = perrs + rerrs + serrs
        if ok_p and ok_r and ok_s:
            (P.out_dir/"secure_periph_soc.v").write_text(top_text)
            print(f"[3] wrote secure_periph_soc.v (contract clean, "
                  f"attempt {attempt+1})")
            break
        print(f"[3v] contract violations ({len(top_errs)}): {top_errs[:4]}")
        if isinstance(model, StubModel):
            (P.out_dir/"secure_periph_soc.v").write_text(top_text)
            print("[3] stub: wrote top DESPITE violations (fix reference!)")
            break
        if attempt == 2:
            # out of re-prompts: ship the best-effort top anyway — a partial
            # score beats the guaranteed 0 of a missing module
            (P.out_dir/"secure_periph_soc.v").write_text(top_text)
            print("[3] wrote top DESPITE violations (re-prompts exhausted)")

    # Step 4: fractional gate with stage-localized failure
    g = run_gate(P)
    print(f"[4] GATE: {'PASS' if g['ok'] else 'FAIL'} — {g['detail']}"
          + ("" if g["ok"] else f" | first fail: {g['first_fail']} "
             f"(stage: {g['stage']})"))

    # Step 4b: KAT gates — vector replay compared against (i) the shipped
    # golden-recorded expected values (easy tier) and (ii) ref_models
    # predictions anchored on the candidate's own trace (works on ANY
    # tier once params come from the inferred YAML — the hidden-testcase
    # oracle). Internal QC signals, never blockers.
    kat = katm = None
    if P.problem == "easy":
        import kat_engine
        try:
            kat = kat_engine.run_kat(P.out_dir, work=P.tmp_dir/"kat")
            print(f"[4b] KAT(golden): {'PASS' if kat['ok'] else 'FAIL'} — "
                  f"{kat['passed']}/{kat['total']}"
                  + (f" | first fail: {kat['first_fail']}"
                     if kat.get("first_fail") else ""))
            katm = kat_engine.run_kat(P.out_dir, work=P.tmp_dir/"kat",
                                      model_predict=True,
                                      params=params_from_yamls(yamls))
            print(f"[4b] KAT(model):  {'PASS' if katm['ok'] else 'FAIL'} — "
                  f"{katm['passed']}/{katm['total']}"
                  + (f" | first fail: {katm['first_fail']}"
                     if katm.get("first_fail") else ""))
        except Exception as e:
            kat = kat or dict(ok=False, error=str(e))
            print(f"[4b] KAT error: {e}")

    # Step 5 (--deep): dual-SoC random-stimulus differential vs the reference
    # RTL. Dev easy-tier only — hidden testcases have no golden RTL to diff
    # against, so this stays an optional deep gate, never a blocker.
    stg = None
    if deep:
        import stg_diff
        try:
            stg = stg_diff.run_diff(ref_dir=NXP/"rtl", gen_dir=P.out_dir,
                                    work=P.tmp_dir/"stg")
            print(f"[5] STG-DIFF: "
                  + ("MATCH" if stg["ok"] else "MISMATCH")
                  + f" — {stg['lines']} cycles, {stg['mismatches']} differing"
                  + (f" | first: {stg['first']}" if stg.get("first") else "")
                  + (f" | error: {stg['error']}" if stg.get("error") else ""))
        except Exception as e:
            stg = dict(ok=False, error=str(e))
            print(f"[5] STG-DIFF error: {e}")

    if model.calls:
        print(f"    model calls: {model.calls}")
    ledger_append(P, dict(model=type(model).__name__, problem=P.problem,
                          yamls=len(yamls), gen_files=len(gen),
                          score=g["score"], passed=g["passed"],
                          total=g["total"], first_fail=g.get("first_fail"),
                          fail_stage=g.get("stage"), calls=model.calls,
                          kat_ok=(kat or {}).get("ok"),
                          kat_score=(kat or {}).get("score"),
                          kat_first=(kat or {}).get("first_fail"),
                          kat_model_ok=(katm or {}).get("ok"),
                          kat_model_score=(katm or {}).get("score"),
                          stg_ok=(stg or {}).get("ok"),
                          stg_mismatches=(stg or {}).get("mismatches"),
                          stg_first=(stg or {}).get("first")))
    return g["ok"]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("info_json", nargs="?",
                    help="runner mode: path to the runner's info.json")
    ap.add_argument("--model", default="stub",
                    help="dev: stub|vertex; runner: model name for the endpoint")
    ap.add_argument("--deep", action="store_true",
                    help="dev only: also run the dual-SoC STG differential "
                         "vs the reference RTL (easy tier)")
    a = ap.parse_args()
    if a.info_json:                                   # RUNNER contract
        info = json.loads(Path(a.info_json).read_text())
        P = Paths.from_info(info)
        model = EndpointModel(info["model_endpoint"],
                              a.model if a.model not in ("stub", "vertex")
                              else info.get("model", a.model))
        try:
            run(model, P, deep=False)
        except Exception as e:
            print(f"AGENT ERROR: {e}", file=sys.stderr)
        # contest verdict comes from the evaluator; success here = we
        # delivered RTL for it to judge
        sys.exit(0 if any(P.out_dir.glob("*.v")) else 1)
    else:                                             # DEV
        sys.exit(0 if run(make_model(a.model), Paths.dev(), deep=a.deep) else 1)
