#!/usr/bin/env python3
"""
Ollama native-API proxy for OpenCode.

OpenCode speaks OpenAI-compatible /v1/chat/completions. Ollama exposes an
OpenAI-compatible endpoint too, but some local models (notably mistral-nemo)
return tool calls as JSON inside the message content instead of the proper
tool_calls field, so OpenCode never executes them.

This proxy sits between OpenCode and Ollama and forwards chat requests to
Ollama's native /api/chat endpoint. Ollama's native tool handling correctly
produces structured tool_calls for mistral-nemo, so the proxy can translate
those back into a standard OpenAI-compatible response that OpenCode understands.

The proxy also injects tool definitions for the tools OpenCode exposes to the
agent (bash, edit, write). OpenCode's `@ai-sdk/openai-compatible` provider does
not send these definitions to a custom baseURL by default, which prevents local
models from knowing they can call tools.
"""

import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


OLLAMA_HOST = os.getenv("OLLAMA_PROXY_TARGET_HOST", "host.docker.internal")
OLLAMA_PORT = int(os.getenv("OLLAMA_PROXY_TARGET_PORT", "11434"))
OLLAMA_CHAT_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/chat"
LOG_PATH = "/var/log/ollama_proxy_requests.log"


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a bash command in the agent's shell.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute.",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": "Edit an existing file by replacing a string with another string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file."},
                    "oldString": {"type": "string", "description": "Text to replace."},
                    "newString": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "oldString", "newString"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": "Write content to a file (create or overwrite).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file."},
                    "content": {"type": "string", "description": "Content to write."},
                },
                "required": ["path", "content"],
            },
        },
    },
]


def _log(label: str, payload: str):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"[{_now()}] {label}: {payload[:4000]}\n")
    except Exception:
        pass


def _now() -> int:
    return int(time.time())


def _make_id(prefix: str = "chatcmpl") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _convert_ollama_to_openai(ollama_resp: dict, model: str) -> dict:
    """Turn an Ollama native /api/chat response into an OpenAI-compatible one."""
    message = ollama_resp.get("message") or {}
    content = message.get("content", "") or ""
    tool_calls = message.get("tool_calls") or []

    openai_tool_calls = []
    for idx, tc in enumerate(tool_calls):
        func = tc.get("function") or {}
        name = func.get("name", "")
        arguments = func.get("arguments", {})
        if isinstance(arguments, dict):
            # OpenCode's bash tool requires a "description" field that
            # mistral-nemo never includes. Inject a default so OpenCode's
            # schema validation passes and the tool call is executed.
            if name == "bash" and "description" not in arguments:
                arguments["description"] = "Execute a bash command"
            arguments = json.dumps(arguments)
        openai_tool_calls.append({
            "id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "index": idx,
            "function": {
                "name": name,
                "arguments": arguments,
            },
        })

    finish_reason = "tool_calls" if openai_tool_calls else "stop"

    choice_message = {
        "role": "assistant",
        "content": content,
    }
    if openai_tool_calls:
        choice_message["tool_calls"] = openai_tool_calls

    return {
        "id": _make_id(),
        "object": "chat.completion",
        "created": _now(),
        "model": model,
        "system_fingerprint": "fp_ollama_proxy",
        "choices": [
            {
                "index": 0,
                "message": choice_message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": ollama_resp.get("prompt_eval_count", 0),
            "completion_tokens": ollama_resp.get("eval_count", 0),
            "total_tokens": (
                ollama_resp.get("prompt_eval_count", 0)
                + ollama_resp.get("eval_count", 0)
            ),
        },
    }


def _prepare_tools(tools: list) -> list:
    """Filter the tool list to only the tools mistral-nemo can reliably call.

    mistral-nemo (12B) returns plain text instead of structured tool_calls when
    presented with more than a few tools. OpenCode sends 10 tools (bash, edit,
    glob, grep, read, skill, task, todowrite, webfetch, write); the complex
    schemas (especially task/todowrite with nested array/object params) overwhelm
    the model's tool-calling ability. Filtering to bash/edit/write — the only
    tools the db_admin agent actually needs (everything else is done via bash) —
    makes the model emit proper tool_calls consistently.

    If OLLAMA_PROXY_TOOL_FILTER is set to "false", the original merge behaviour
    is used instead (forward all caller tools + inject any missing defaults).
    """
    filter_enabled = os.getenv("OLLAMA_PROXY_TOOL_FILTER", "true").lower() == "true"
    tool_def_names = {t["function"]["name"] for t in TOOL_DEFINITIONS}

    if filter_enabled:
        # Always use the simplified TOOL_DEFINITIONS, not OpenCode's original
        # schemas. OpenCode's bash tool requires a "description" field that
        # mistral-nemo never includes, causing SchemaError on every tool call.
        # The proxy injects "description" into the response before returning
        # to OpenCode (see _convert_ollama_to_openai).
        return TOOL_DEFINITIONS

    # Legacy merge behaviour: keep caller tools, add any missing defaults.
    if not tools:
        return TOOL_DEFINITIONS
    existing_names = {t.get("function", {}).get("name") for t in tools}
    for t in TOOL_DEFINITIONS:
        if t["function"]["name"] not in existing_names:
            tools.append(t)
    return tools


def _convert_messages_for_ollama(messages: list) -> list:
    """Convert OpenAI-format messages to Ollama native /api/chat format.

    OpenCode sends messages in OpenAI format where tool_call.arguments is a
    JSON string (e.g. "{\"command\": \"ls\"}"). Ollama's native /api/chat
    endpoint expects arguments as an object (e.g. {"command": "ls"}).
    Without this conversion, Ollama returns HTTP 400:
    "Value looks like object, but can't find closing '}' symbol".
    """
    converted = []
    for msg in messages:
        m = dict(msg)
        role = m.get("role", "")

        # Convert tool_calls in assistant messages: string args -> object args
        if role == "assistant" and m.get("tool_calls"):
            new_tcs = []
            for tc in m["tool_calls"]:
                tc = dict(tc)
                fn = dict(tc.get("function", {}))
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        fn["arguments"] = json.loads(args)
                    except (json.JSONDecodeError, ValueError):
                        fn["arguments"] = {"raw": args}
                tc["function"] = fn
                new_tcs.append(tc)
            m["tool_calls"] = new_tcs

        # Convert tool-role messages to Ollama format.
        # OpenAI: {"role": "tool", "tool_call_id": "...", "content": "output"}
        # Ollama expects the tool result inside the assistant message that
        # made the call, but also accepts a separate message with role "tool".
        # Keep as-is; Ollama handles role="tool" natively.
        converted.append(m)

    return converted


def _forward_chat(body: dict) -> dict:
    """Send the request to Ollama's native /api/chat and return OpenAI format."""
    model = body.get("model", "mistral-nemo")

    # OpenCode sends internal permission flags at the top level; Ollama doesn't
    # understand them, so strip them before forwarding.
    messages = _convert_messages_for_ollama(body.get("messages", []))
    tools = _prepare_tools(body.get("tools") or [])

    ollama_body = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
        "options": {},
    }

    for key in ("temperature", "top_p", "top_k", "num_predict"):
        if key in body:
            ollama_body["options"][key] = body[key]

    # Ollama defaults num_ctx to 4096, which truncates large system prompts
    # (e.g. the db_admin agent prompt is ~6k tokens). A truncated prompt drops
    # the behavioral rules and breaks tool calling. OpenCode's Ollama docs
    # recommend 16k-32k; default to 32768 unless the caller overrides it.
    num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "32768"))
    ollama_body["options"].setdefault("num_ctx", num_ctx)

    req = Request(
        OLLAMA_CHAT_URL,
        data=json.dumps(ollama_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(req, timeout=300) as resp:
        ollama_resp = json.loads(resp.read().decode("utf-8"))

    return _convert_ollama_to_openai(ollama_resp, model)


def _forward_native_chat(body: dict) -> dict:
    """Forward a native Ollama /api/chat request, injecting tools + num_ctx.

    Unlike _forward_chat (which converts OpenAI format), this accepts and
    returns the native Ollama format as-is. It only injects the bash/edit/
    write tool definitions and sets num_ctx, then forwards to the real
    Ollama's /api/chat endpoint.
    """
    body["tools"] = _prepare_tools(body.get("tools") or [])
    body.setdefault("stream", False)

    # Ensure num_ctx is large enough (Ollama defaults to 4096).
    options = body.setdefault("options", {})
    options.setdefault("num_ctx", int(os.getenv("OLLAMA_NUM_CTX", "32768")))

    req = Request(
        OLLAMA_CHAT_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status: int, data: dict):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_sse_stream(self, result: dict):
        """Send a complete OpenAI chat completion as SSE streaming chunks.

        OpenCode's @ai-sdk/openai-compatible adapter sends stream=true and
        expects Server-Sent Events (SSE) format. When the proxy returns a
        non-streaming JSON response to a streaming request, the adapter
        extracts text content but silently drops tool_calls. This method
        converts the complete response into valid SSE chunks so tool_calls
        are correctly parsed by the adapter.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        choice = (result.get("choices") or [{}])[0]
        msg = choice.get("message", {})
        content = msg.get("content", "") or ""
        tool_calls = msg.get("tool_calls") or []
        finish_reason = choice.get("finish_reason", "stop")
        chunk_id = result.get("id", _make_id())
        model = result.get("model", "mistral-nemo")
        created = result.get("created", _now())

        def _send_chunk(delta: dict, finish=None):
            chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
            self.wfile.flush()

        # First chunk: role only (per OpenAI spec)
        _send_chunk({"role": "assistant"})

        # Stream text content if present
        if content:
            _send_chunk({"content": content})

        # Stream tool calls
        for tc in tool_calls:
            fn = tc.get("function", {})
            # First chunk for this tool call: id + name
            _send_chunk({
                "tool_calls": [{
                    "index": tc.get("index", 0),
                    "id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                    "type": "function",
                    "function": {"name": fn.get("name", ""), "arguments": ""},
                }]
            })
            # Second chunk: arguments (complete)
            _send_chunk({
                "tool_calls": [{
                    "index": tc.get("index", 0),
                    "function": {"arguments": fn.get("arguments", "{}")},
                }]
            })

        # Final chunk: finish_reason
        _send_chunk({}, finish=finish_reason)

        # End of stream
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def do_GET(self):
        if self.path in ("/", "/health"):
            self._send_json(200, {"status": "ok", "proxy": "ollama-native"})
        elif self.path == "/v1/models":
            self._send_json(200, {
                "object": "list",
                "data": [
                    {
                        "id": os.getenv("OLLAMA_MODEL", "mistral-nemo"),
                        "object": "model",
                        "created": _now(),
                        "owned_by": "ollama",
                    }
                ],
            })
        elif self.path == "/api/tags":
            # Native Ollama model discovery – proxy through to the real
            # Ollama so the built-in provider sees the same model list.
            try:
                req = Request(
                    f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/tags",
                    headers={"Content-Type": "application/json"},
                    method="GET",
                )
                with urlopen(req, timeout=30) as resp:
                    self._send_json(200, json.loads(resp.read().decode("utf-8")))
            except Exception as exc:
                _log("ERR", f"api/tags proxy: {exc}")
                self._send_json(502, {"error": str(exc)})
        else:
            _log("GET404", f"path={self.path}")
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self._send_json(400, {"error": "Empty body"})
            return

        raw_body = self.rfile.read(length).decode("utf-8")
        has_tools = '"tools"' in raw_body
        _log("REQ", f"path={self.path} len={len(raw_body)} has_tools={has_tools} head={raw_body[:300]}")

        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": f"Invalid JSON: {exc}"})
            return

        if self.path == "/api/chat":
            # Native Ollama /api/chat – inject tools + num_ctx, forward to
            # the real Ollama, and return the native response as-is (no
            # OpenAI format conversion needed).
            try:
                result = _forward_native_chat(body)
                has_tool_calls = bool(
                    (result.get("message") or {}).get("tool_calls")
                )
                _log("RESP", f"native has_tool_calls={has_tool_calls} {json.dumps(result)[:500]}")
                self._send_json(200, result)
            except HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                _log("ERR", f"Ollama HTTP {exc.code}: {error_body}")
                self._send_json(502, {"error": f"Ollama returned {exc.code}: {error_body}"})
            except URLError as exc:
                _log("ERR", f"Cannot reach Ollama: {exc}")
                self._send_json(502, {"error": f"Cannot reach Ollama: {exc}"})
            except Exception as exc:
                _log("ERR", str(exc))
                self._send_json(502, {"error": str(exc)})
            return

        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": "Not found", "path": self.path})
            return

        stream_mode = body.get("stream", False)
        try:
            result = _forward_chat(body)
            has_tool_calls = bool(result.get("choices", [{}])[0].get("message", {}).get("tool_calls"))
            _log("RESP", f"stream={stream_mode} has_tool_calls={has_tool_calls} {json.dumps(result)[:500]}")
            if stream_mode:
                self._send_sse_stream(result)
            else:
                self._send_json(200, result)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            _log("ERR", f"Ollama HTTP {exc.code}: {error_body}")
            self._send_json(502, {"error": f"Ollama returned {exc.code}: {error_body}"})
        except URLError as exc:
            _log("ERR", f"Cannot reach Ollama: {exc}")
            self._send_json(502, {"error": f"Cannot reach Ollama: {exc}"})
        except Exception as exc:
            _log("ERR", str(exc))
            self._send_json(502, {"error": str(exc)})


def main():
    port = int(os.getenv("OLLAMA_PROXY_PORT", "11435"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[ollama_proxy] Listening on http://0.0.0.0:{port}")
    print(f"[ollama_proxy] Forwarding to {OLLAMA_CHAT_URL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
