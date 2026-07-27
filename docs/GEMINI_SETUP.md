# Gemini API key — setup & first live-fire runbook

Both agents auto-detect either key. Prefer Express Mode (it is the exact
client mode the organizers use to evaluate at DAC).

## 1. Get a key (pick one)

- **Vertex AI Express Mode** (preferred): AgentSetup.md Step 1 —
  browser → Vertex AI Studio Express Mode → "Get API key".
  `export EXPRESS_MODE_KEY=...`
- **AI Studio** (personal Gemini subscription fallback):
  https://aistudio.google.com/apikey → create key.
  `export GEMINI_API_KEY=...`

## 2. Install the SDK (once)

```bash
pip install google-genai
```

## 3. Handshake test (AgentSetup.md step 3 equivalent)

```bash
cd ICLAD-Hackathon-2026/problem-categories/ICLAD26-NVIDIA-Problems
python3 - <<'EOF'
import os
from google import genai
if os.environ.get("EXPRESS_MODE_KEY"):
    c = genai.Client(vertexai=True, api_key=os.environ["EXPRESS_MODE_KEY"])
else:
    c = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
r = c.models.generate_content(model="gemini-3-flash-preview",
                              contents="Say READY.")
print(r.text)
EOF
```

If `gemini-3-flash-preview` 404s on an AI Studio key, retry with
`gemini-2.0-flash` and pass that via `--model-name` below.

## 4. First real rounds — HISTORICAL RUNBOOK (already executed)

> These campaigns were run during development and their results are banked in
> the submission manifests/ledgers. Re-running them consumes real tokens and
> is NOT needed to verify any claim — the keyless paths in the root README
> (NXP `--model stub`, NVIDIA `ppa.evaluate`, ASU placeholder key) reproduce
> everything. Kept for provenance. Current default model at evaluation time:
> `gemini-3.5-flash`.

```bash
# NVIDIA: one careful round on sha512 (bounded: ~4 calls)
cd nvidia_work/agent
python3 -m ppa.controller --ip sha512 --rounds 1 --k 3 --model vertex \
    --max-calls 8 --emit-best ../submission/sha512_live

# NVIDIA: async_fifo (the differentiator IP)
python3 -m ppa.controller --ip async_fifo --rounds 2 --k 3 --model vertex \
    --max-calls 12 --emit-best ../submission/async_fifo_live

# NXP: first real diagram inference (expect all gates + KAT lines green)
cd ../../nxp_work/agent
python3 nxp_agent.py --model vertex --deep
```

Then: decoding-config mini-sweep (temp 0–0.4 / top_p 0.4–0.7, ~25 calls) on
sha512, then aes/kmac agent targets (GF/tower-field + Keccak-θ headroom).
Watch `ledger/` on both sides for calls/tokens; results feed the slide decks.
