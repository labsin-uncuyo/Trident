# Trident — Agent & Local-Model Notes

This file contains agent-focused context for working on Trident, including the
local Ollama integration and known model/behavior considerations.

---

## Supported agent back-ends

Trident agents are driven by [OpenCode](https://opencode.ai). OpenCode is
configured inside the lab containers by `/root/.config/opencode/opencode.json`,
which is generated at container start from `images/compromised/opencode.json.template`
(and the server-side equivalent in `images/server/opencode.json`).

Two back-end modes can coexist:

1. **API provider** (default): uses any OpenAI-compatible endpoint (OpenAI,
   e-INFRA, OpenRouter, Gemini proxy, etc.). Configure with the usual
   `LLM_API_KEY`, `LLM_BASE_URL`, `PROVIDER_NAME`, `LLM_MODEL` variables.
2. **Local Ollama** (optional): runs a local model inside the Ollama container.
   Configure with the `OLLAMA_*` variables described below.

---

## Local Ollama support

### Goal

Allow the **benign agent (`db_admin`)** to run against a local model
(`mistral-nemo`) served by a containerized Ollama instance, without breaking the
API-provider path used by the other agents.

### Files involved

| File | Purpose |
|------|---------|
| `.env` / `.env.example` | Switches and URLs for Ollama |
| `docker-compose.yml` | Passes `OLLAMA_*` env vars into `lab_compromised` |
| `images/compromised/entrypoint.sh` | Generates `opencode.json` with both providers; routes `db_admin` to Ollama when requested |
| `images/compromised/ollama_proxy.py` | Translates OpenCode's OpenAI-compatible requests into Ollama's native `/api/chat` API and back |

### Configuration

```bash
# Add or enable in .env
OLLAMA_ENABLED=true
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1   # host-side Ollama
OLLAMA_MODEL=mistral-nemo
OLLAMA_API_KEY=ollama                                   # dummy value, required by OpenCode
BENIGN_USE_OLLAMA=true                                  # only db_admin uses Ollama
```

After changing these variables, rebuild and restart the lab:

```bash
make build && make up
```

### Why a proxy is needed

OpenCode talks to Ollama through an OpenAI-compatible provider. Ollama exposes
`/v1/chat/completions`, but with `mistral-nemo` that endpoint does **not**
reliably return structured `tool_calls`; instead the model emits bash commands as
plain markdown or JSON inside `content`. OpenCode therefore never executes them.

Ollama's **native** `/api/chat` endpoint handles tool calling correctly for
`mistral-nemo` and returns proper `tool_calls`. `ollama_proxy.py` sits between
OpenCode and Ollama:

- Receives OpenAI-compatible requests from OpenCode on `127.0.0.1:11434`.
- Filters the tool list to bash/edit/write only (mistral-nemo cannot reliably
  call tools when presented with more than a few).
- Converts OpenAI-format messages to Ollama native format (string tool_call
  arguments → object arguments).
- Forwards to Ollama's native `/api/chat`.
- Translates the native response back to OpenAI-compatible SSE streaming format
  so OpenCode executes the tool calls.

The proxy runs inside `lab_compromised` and is started by `entrypoint.sh`.

### Verifying Ollama reachability

The Ollama container must be started with `--gpus all` and `-p 11435:11434`:

```bash
docker run -d --gpus all --name ollama -v ollama:/root/.ollama -p 11435:11434 ollama/ollama
```

Verify GPU access:
```bash
docker exec ollama nvidia-smi   # should show the GPU
nvidia-smi                       # host: should show an 'ollama' process during inference
```

From the compromised container (through the proxy):
```bash
docker exec lab_compromised curl -s http://127.0.0.1:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{"model":"mistral-nemo","messages":[{"role":"user","content":"Run ls /tmp"}],"stream":false}' \
  | python3 -m json.tool
```

A working setup returns a `tool_calls` entry with `name: "bash"`.

### Running the benign agent

```bash
make benign TIME_LIMIT=120
```

Logs are written to `outputs/<RUN_ID>/benign_agent/`.

### Switching back to the API provider

```bash
BENIGN_USE_OLLAMA=false
```

Then `make build && make up`. The Ollama provider remains in `opencode.json` but
`db_admin` will use the API provider again.

---

## Benign agent tool-calling: diagnosis and resolution (RESOLVED)

As of 2026-06-20 the benign agent (`db_admin`) running against the local
`mistral-nemo` model **successfully invokes the `bash` tool** — verified with
21 tool calls in a 120-second session, 0 errors, GPU-accelerated inference.

### Previous diagnosis was WRONG

The earlier investigation concluded that "OpenCode bypasses the Ollama proxy"
and that the built-in `ollama` provider ignores all config/env overrides and
connects directly to `172.17.0.1:11434`. **This was incorrect.** The
in-container proxy (`ollama_proxy.py` on `127.0.0.1:11434`) IS reached by
OpenCode — the proxy request log showed `has_tools=True` requests with the full
db_admin system prompt arriving at `/v1/chat/completions`. The real problems
were five separate issues, each of which had to be fixed:

### Root causes and fixes

#### 1. Ollama container had no GPU access (FIXED)

The `ollama` container was running with `Runtime: runc` and
`DeviceRequests: null` — **no GPU**. Inference took 107s on CPU (vs 7s on GPU).
Recreated with `--gpus all`:

```bash
docker rm -f ollama
docker run -d --gpus all --name ollama -v ollama:/root/.ollama -p 11435:11434 ollama/ollama
```

Verify: `docker exec ollama nvidia-smi` should show the GPU, and
`nvidia-smi` on the host should show an `ollama` process using ~12 GB VRAM
during inference.

#### 2. mistral-nemo returns text instead of tool_calls with 10 tools (FIXED)

OpenCode sends 10 tool definitions (bash, edit, glob, grep, read, skill, task,
todowrite, webfetch, write). mistral-nemo (12B) **cannot reliably produce
structured `tool_calls` when presented with more than a few tools** — it emits
commands as plain text or markdown instead. With only 3 tools (bash, edit,
write), the model consistently returns proper `tool_calls`.

Fix: added `_prepare_tools()` in `ollama_proxy.py` that filters the tool list
to bash/edit/write only (controlled by `OLLAMA_PROXY_TOOL_FILTER=true`, the
default). The db_admin agent does everything via bash (psql, curl, ssh), so
the other 7 tools are unnecessary.

#### 3. Proxy returned non-streaming JSON to stream=true requests (FIXED)

OpenCode's `@ai-sdk/openai-compatible` adapter sends `stream: true` and expects
SSE (Server-Sent Events) format. The proxy was returning a single JSON object
(non-streaming). The adapter parsed text `content` from it but **silently
dropped `tool_calls`** — OpenCode reported `tool calls: 0` even though the
proxy log showed `has_tool_calls=True`.

Fix: added `_send_sse_stream()` method that converts the complete response into
valid SSE chunks (`data: {...}\n\n` + `data: [DONE]\n\n`) with proper
`tool_calls` delta chunks. The `Connection: close` header ensures the stream
terminates cleanly.

#### 4. Tool_call arguments not converted for Ollama native API (FIXED)

When OpenCode sends conversation history (multi-turn), assistant messages
contain `tool_calls` with `arguments` as a **JSON string** (OpenAI format,
e.g. `"{\"command\": \"ls\"}"`). Ollama's native `/api/chat` expects
`arguments` as an **object** (e.g. `{"command": "ls"}`). Without conversion,
Ollama returns `HTTP 400: "Value looks like object, but can't find closing '}'
symbol"` on every request after the first tool call.

Fix: added `_convert_messages_for_ollama()` in `ollama_proxy.py` that parses
string `arguments` into objects before forwarding to Ollama.

#### 5. db_admin client flooded with "keep going" messages (FIXED)

When the model returned text instead of a tool_call, OpenCode completed the
turn in <1s. The `db_admin_opencode_client.py` inner loop immediately sent a
"Good, keep going..." nudge, creating a tight loop of **hundreds of messages
per second**.

Fix: added a 5-second delay when a turn completes in under 3s (likely no tool
call executed), preventing the flood.

### `num_ctx` truncation (previously FIXED, still required)

Ollama's default `num_ctx` is 4096. The db_admin system prompt is ~6000 tokens,
so Ollama silently truncated it. Fixed by creating the model with
`PARAMETER num_ctx 32768`:

```bash
docker exec ollama bash -c 'printf "FROM mistral-nemo:latest\nPARAMETER num_ctx 32768\n" > /tmp/Modelfile && ollama create mistral-nemo -f /tmp/Modelfile'
```

This setting is preserved in the `ollama` Docker volume across container
recreations.

### Files modified

| File | Change |
|------|--------|
| `images/compromised/ollama_proxy.py` | Added `_prepare_tools()` (tool filtering), `_send_sse_stream()` (SSE streaming), `_convert_messages_for_ollama()` (message format conversion) |
| `images/compromised/db_admin_opencode_client.py` | Added 5s anti-flood delay on fast (<3s) turn completions |

### Verification (2026-06-20)

```
[db_admin] ✓ Session 1: 21 turns, 60 messages, 92s
[db_admin]   LLM calls: 40, tool calls: 21, cost: $0.0000
```

- Proxy: 42 requests, 20 with `has_tool_calls=True`, 0 HTTP 400 errors
- OpenCode: 22 steps past step 1 (tool execution confirmed)
- GPU: 12.5 GB VRAM, 144W power draw during inference
- No flooding: turns 3–92s apart

### Previous failed attempts (historical record)

The following attempts were made during the earlier investigation, under the
incorrect assumption that OpenCode was bypassing the proxy. They are preserved
here for reference but were **not the cause** of the failure:

| Attempt | Result |
|---------|--------|
| Custom provider named `ollama` with `baseURL` → proxy | Built-in provider shadows it; connects directly to Ollama. |
| Custom provider named `ollama_local` with `baseURL` → proxy | OpenCode uses it but the `@ai-sdk/openai-compatible` adapter in 1.17.8 is broken: `Z.responses is not a function`; no HTTP request. |
| `disabled_providers: ["ollama"]` + custom `ollama_local` | Same broken-adapter error; no HTTP request. |
| Override `OLLAMA_BASE_URL`/`OLLAMA_HOST` env vars | Built-in provider ignores them; connects to real Ollama directly. |
| Repoint `host.docker.internal` → `127.0.0.1` in `/etc/hosts` | OpenCode still connects to the real Ollama IP `172.17.0.1` directly. |
| Set `provider.ollama.npm: "@ai-sdk/openai-compatible"` | Built-in provider ignores the `npm` override. |

### OpenCode version note

OpenCode 1.17.8 (Jun 17 2026) is the latest release as of this date. The
changelog shows no fix for the `@ai-sdk/openai-compatible` adapter bug
(`Z.responses is not a function`), but the built-in `ollama` provider with the
in-container proxy works correctly once the five issues above are fixed. No
upgrade is needed.

### Quick verification commands

```bash
# Is the proxy up inside the compromised container?
docker exec lab_compromised curl -sf http://127.0.0.1:11434/health

# Does the proxy inject tools and return tool_calls?
docker exec lab_compromised curl -s http://127.0.0.1:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{"model":"mistral-nemo","messages":[{"role":"user","content":"Run ls /tmp"}],"stream":false}' \
  | python3 -m json.tool
# A working proxy returns message.tool_calls with name "bash".

# Did OpenCode actually hit the proxy during a benign run?
docker exec lab_compromised wc -l /var/log/ollama_proxy_requests.log
# > 0 means the proxy was reached; 0 means OpenCode bypassed it again.

# What did OpenCode's built-in ollama provider actually do?
docker exec lab_compromised tail -50 /root/.local/share/opencode/log/opencode.log | grep -iE 'ollama|error|stream'

# Is Ollama truncating the prompt? (num_ctx too small)
docker logs ollama 2>&1 | grep truncating
# No output = good (num_ctx is large enough).
```

---

## Known limitations

- Tool calling with local models is provider/model-specific. `mistral-nemo` works
  through the proxy with tool filtering (bash/edit/write only); other models may
  behave differently.
- The benign agent prompt instructs extensive web research before database
  operations. With a 120-second test run the agent often stays in the research
  phase and may not reach SQL execution. Longer runs are needed to observe
  database activity.
- The proxy converts non-streaming Ollama responses into SSE streaming format
  for OpenCode (which sends `stream: true`). The `Connection: close` header
  terminates the stream cleanly.
- mistral-nemo (12B) cannot reliably produce structured `tool_calls` when
  presented with more than a few tools. The proxy filters to bash/edit/write
  by default (`OLLAMA_PROXY_TOOL_FILTER=true`).
- The `ollama` Docker container must be started with `--gpus all` for
  GPU-accelerated inference (107s CPU vs 7s GPU per request).

---

## Dashboard tests

The dashboard test suite can be run in a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install docker httpx==0.27.0 pytest-asyncio
.venv/bin/pytest tests/dashboard/ -v
```

As of the current codebase some tests fail due to pre-existing test/code
mismatches (missing `OpenCodeClient`/`get_client` symbols and an `aracne`
topology node that does not exist in the backend). These failures are unrelated
to the Ollama integration.
