from __future__ import annotations

import os
import sys
import time
import uuid
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv

# LangChain core + OpenAI-compatible chat model
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import BaseMessage

# Local timing trace utilities
from .timing_trace import get_tracer, trace_span


load_dotenv()  # Load .env if present; intentionally early to set env for model


def _is_truthy(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class PlannerConfig:
    model: str = os.getenv("LLM_MODEL", "")
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "1200"))
    # OpenAI-compatible endpoint values
    openai_base_url: Optional[str] = os.getenv("LLM_URL")
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
    # Optional Langfuse tracing
    langfuse_enabled: bool = _is_truthy(os.getenv("LANGFUSE_ENABLED"), default=False)
    langfuse_public_key: Optional[str] = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: Optional[str] = os.getenv("LANGFUSE_SECRET_KEY")
    langfuse_host: Optional[str] = os.getenv("LANGFUSE_HOST")
    langfuse_trace_name: str = os.getenv("LANGFUSE_TRACE_NAME", "incident_planner")
    # Async Langfuse flush (non-blocking) - default enabled for performance
    langfuse_async_flush: bool = _is_truthy(os.getenv("LANGFUSE_ASYNC_FLUSH"), default=True)


import yaml


class IncidentPlanner:
    """
    LangChain-based planner that takes an IDS alert and returns a
    concrete English remediation plan using an OpenAI-compatible endpoint.
    """

    def __init__(self, config: Optional[PlannerConfig] = None, prompts_path: Optional[str] = None):
        self.config = config or PlannerConfig()
        self.prompts_path = prompts_path or os.getenv("PROMPTS_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts.yaml"))

        # Initialize timing tracer
        self.tracer = get_tracer("planner")
        self._init_start = time.time()

        # Log configuration for debugging
        print(f"\n[PLANNER_INIT] Initializing IncidentPlanner with config:", file=sys.stderr, flush=True)
        print(f"  model: {self.config.model}", file=sys.stderr, flush=True)
        print(f"  temperature: {self.config.temperature}", file=sys.stderr, flush=True)
        print(f"  max_tokens: {self.config.max_tokens}", file=sys.stderr, flush=True)
        print(f"  openai_base_url: {self.config.openai_base_url}", file=sys.stderr, flush=True)
        print(f"  openai_api_key: {self.config.openai_api_key[:10]}..." if self.config.openai_api_key else "  openai_api_key: None", file=sys.stderr, flush=True)
        print(f"  prompts_path: {self.prompts_path}", file=sys.stderr, flush=True)
        print(f"  langfuse_enabled: {self.config.langfuse_enabled}", file=sys.stderr, flush=True)
        print(f"[PLANNER_INIT] End of config\n", file=sys.stderr, flush=True)

        # Ensure environment variables are set for OpenAI-compatible clients
        if self.config.openai_base_url:
            os.environ.setdefault("LLM_URL", self.config.openai_base_url)
        if self.config.openai_api_key:
            os.environ.setdefault("OPENAI_API_KEY", self.config.openai_api_key)

        # Verify env vars are set
        print(f"[PLANNER_INIT] Environment check:", file=sys.stderr, flush=True)
        print(f"  LLM_URL: {os.getenv('LLM_URL')}", file=sys.stderr, flush=True)
        print(f"  OPENAI_API_KEY: {os.getenv('OPENAI_API_KEY', 'None')[:10]}..." if os.getenv('OPENAI_API_KEY') else "  OPENAI_API_KEY: None", file=sys.stderr, flush=True)
        print(f"[PLANNER_INIT] End of env check\n", file=sys.stderr, flush=True)

        # Build the model
        # NOTE: timeout is set to 30s to accommodate gpt-oss-120b cold starts (4-5s) and network conditions
        # LangChain's default timeout is 10s which can cause empty responses on slow LLM responses
        self.llm = ChatOpenAI(
            model=self.config.model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            # ChatOpenAI reads LLM_URL and OPENAI_API_KEY from env; base_url can also be passed explicitly
            base_url=self.config.openai_base_url,
            api_key=self.config.openai_api_key,
            timeout=30.0,
            # Enable verbose mode for debugging LangChain internals
            verbose=False,
        )

        # Load prompts from YAML (one-shot prompt)
        sys_tmpl, human_tmpl = self._load_prompts(self.prompts_path)

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", sys_tmpl),
            ("human", human_tmpl),
        ])
        self.langfuse_client: Optional[Any] = None
        self.langfuse_callback = self._build_langfuse_callback()

        self.chain = self.prompt | self.llm | StrOutputParser()

    def plan(self, alert: str, *, temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> Dict[str, Any]:
        """Generate a remediation plan from an IDS alert with fine-grained timing traces."""
        # Overall plan timing
        plan_start = time.time()

        # Log file path
        log_file = f"/outputs/{os.getenv('RUN_ID', 'run')}/logs/planner_llm_detailed.log"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        # Helper to log to both stderr and file
        def log_msg(msg):
            print(msg, file=sys.stderr, flush=True)
            with open(log_file, 'a') as f:
                f.write(msg + "\n")

        request_id = str(uuid.uuid4())
        alert_len = len(alert)
        has_base64 = 'VUc5' in alert or 'base64' in alert.lower()

        # Phase 1: Initialization and config setup
        with self.tracer.span("plan_request_setup", "planner",
                              request_id=request_id[:8],
                              alert_length=alert_len,
                              has_base64=has_base64):
            invoke_config: Dict[str, Any] = {
                "metadata": {
                    "request_id": request_id,
                    "component": "incident_planner",
                },
                "run_name": self.config.langfuse_trace_name,
            }
            if self.langfuse_callback is not None:
                invoke_config["callbacks"] = [self.langfuse_callback]

            log_msg(f"[PLANNER_LLM_INPUT_START] request_id={request_id[:8]}")
            log_msg(f"Alert length: {alert_len}")
            log_msg(f"Alert contains base64 marker: {has_base64}")
            log_msg(f"[ALERT_TEXT]")
            log_msg(alert)
            log_msg(f"[ALERT_TEXT_END]")

        # Phase 2: Prompt formatting
        formatted_messages = None
        formatted_prompt_text = None
        with self.tracer.span("prompt_formatting", "planner",
                              request_id=request_id[:8]) as fmt_span:
            formatted_messages = self.prompt.format_messages(alert=alert)
            formatted_prompt_text = self._serialize_prompt_messages(formatted_messages)

            log_msg(f"[LLM_FULL_FORMATTED_PROMPT_START]")
            log_msg(formatted_prompt_text)
            log_msg(f"[LLM_FULL_FORMATTED_PROMPT_END]")

            # Record prompt size metrics
            fmt_span.args.update({
                "prompt_length": len(formatted_prompt_text),
                "num_messages": len(formatted_messages),
            })

        # Phase 3: Langfuse generation start
        langfuse_generation = None
        with self.tracer.span("langfuse_start", "planner",
                              request_id=request_id[:8]):
            langfuse_generation = self._start_langfuse_generation(
                request_id=request_id,
                alert=alert,
                formatted_prompt_text=formatted_prompt_text,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        # Phase 4: LLM invocation (the critical path)
        result_text = ""
        llm_error = None
        llm_start = time.time()

        try:
            # Allow per-request overrides
            with self.tracer.span("llm_invoke", "planner",
                                  request_id=request_id[:8],
                                  model=self.config.model,
                                  has_temp_override=temperature is not None,
                                  has_max_tokens_override=max_tokens is not None):
                if temperature is not None or max_tokens is not None:
                    with self.tracer.span("llm_model_creation", "planner"):
                        llm = ChatOpenAI(
                            model=self.config.model,
                            temperature=temperature if temperature is not None else self.config.temperature,
                            max_tokens=max_tokens if max_tokens is not None else self.config.max_tokens,
                            base_url=self.config.openai_base_url,
                            api_key=self.config.openai_api_key,
                            timeout=30.0,
                        )

                    with self.tracer.span("llm_invoke_call", "planner"):
                        result_message = llm.invoke(formatted_messages, config=invoke_config)
                    result_text = self._extract_result_text(result_message)
                else:
                    with self.tracer.span("llm_chain_invoke", "planner"):
                        result_text = self.chain.invoke({"alert": alert}, config=invoke_config)

            llm_duration = (time.time() - llm_start) * 1000

            if langfuse_generation is not None:
                with self.tracer.span("langfuse_update", "planner"):
                    langfuse_generation.update(output=result_text)

            log_msg(f"[LLM_OUTPUT_START]")
            log_msg(f"Raw result type: {type(result_text)}")
            log_msg(f"Raw result length: {len(result_text)}")
            log_msg(f"Raw result (first 1000 chars): {result_text[:1000]}")
            log_msg(result_text)
            log_msg(f"[LLM_OUTPUT_END]")
            log_msg(f"[PLANNER_LLM_INPUT_END]")

        except Exception as e:
            llm_duration = (time.time() - llm_start) * 1000
            llm_error = f"{type(e).__name__}: {e}"

            # Log any exception that occurs during LLM invocation
            import traceback
            log_msg(f"[LLM_INVOCATION_EXCEPTION]")
            log_msg(f"Exception type: {type(e).__name__}")
            log_msg(f"Exception message: {e}")
            log_msg(f"Traceback: {traceback.format_exc()}")
            log_msg(f"[LLM_INVOCATION_EXCEPTION_END]")

            # Record error in trace
            self.tracer.add_span(
                "llm_invoke_error",
                (llm_start - self._init_start) * 1000,
                llm_duration,
                "planner",
                error_type=type(e).__name__,
                error_message=str(e)[:200],
                request_id=request_id[:8],
            )

            # Re-raise to be handled by caller
            raise
        finally:
            # Phase 5: Langfuse flush
            with self.tracer.span("langfuse_flush", "planner",
                                  request_id=request_id[:8]):
                if langfuse_generation is not None:
                    langfuse_generation.end()
                self._flush_langfuse()

        # Phase 6: Response parsing
        executor_host_ip: str = ""
        plan_text: str = ""
        parse_error = None
        parse_details: Dict[str, Any] = {}

        with self.tracer.span("response_parsing", "planner",
                              request_id=request_id[:8],
                              result_length=len(result_text)):

            # Sub-phase: Markdown cleanup
            with self.tracer.span("parse_markdown_cleanup", "planner"):
                def _best_effort_unescape(raw: str) -> str:
                    try:
                        return json.loads(f'"{raw}"')
                    except Exception:
                        return (
                            raw.replace(r"\\", "\\")
                            .replace(r"\"", '"')
                            .replace(r"\n", "\n")
                            .replace(r"\r", "\r")
                            .replace(r"\t", "\t")
                        )

                def _extract_json_string_value(text: str, key: str, *, allow_unterminated: bool = False) -> Optional[str]:
                    key_token = f'"{key}"'
                    key_pos = text.find(key_token)
                    if key_pos == -1:
                        return None
                    colon_pos = text.find(":", key_pos + len(key_token))
                    if colon_pos == -1:
                        return None
                    i = colon_pos + 1
                    while i < len(text) and text[i].isspace():
                        i += 1
                    if i >= len(text) or text[i] != '"':
                        return None
                    i += 1

                    raw_chars = []
                    escaped = False
                    while i < len(text):
                        ch = text[i]
                        if escaped:
                            raw_chars.append("\\" + ch)
                            escaped = False
                        else:
                            if ch == "\\":
                                escaped = True
                            elif ch == '"':
                                return _best_effort_unescape("".join(raw_chars))
                            else:
                                raw_chars.append(ch)
                        i += 1

                    if allow_unterminated:
                        return _best_effort_unescape("".join(raw_chars))
                    return None

                import re

                cleaned_text = str(result_text or "")

                # 1) Clean up markdown code blocks that LLMs sometimes add
                # Pattern: ```json ... ``` or ``` ... ``` (prefer blocks that look like JSON)
                code_block_pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
                fenced_blocks = re.findall(code_block_pattern, cleaned_text, re.DOTALL)
                if fenced_blocks:
                    preferred_block = next((block for block in fenced_blocks if "{" in block and "}" in block), fenced_blocks[0])
                    cleaned_text = preferred_block.strip()
                    parse_details["markdown_code_block_removed"] = True
                else:
                    # Handle cases where the fence is present but not properly closed
                    if re.match(r"^```(?:json)?\s*", cleaned_text):
                        cleaned_text = re.sub(r"^```(?:json)?\s*", "", cleaned_text)
                        parse_details["markdown_code_block_removed"] = True
                    if cleaned_text.rstrip().endswith("```"):
                        cleaned_text = re.sub(r"\n?```\s*$", "", cleaned_text).rstrip()
                        parse_details["markdown_code_block_removed"] = True

            # Sub-phase: JSON extraction
            with self.tracer.span("parse_json_extraction", "planner"):
                # 2) Extract the first balanced JSON object if any extra text remains
                start = cleaned_text.find("{")
                if start != -1:
                    # Find the matching closing brace by counting
                    brace_count = 0
                    in_string = False
                    escape_next = False
                    for i in range(start, len(cleaned_text)):
                        char = cleaned_text[i]
                        if escape_next:
                            escape_next = False
                            continue
                        if char == "\\":
                            escape_next = True
                            continue
                        if char == '"' and not escape_next:
                            in_string = not in_string
                            continue
                        if not in_string:
                            if char == "{":
                                brace_count += 1
                            elif char == "}":
                                brace_count -= 1
                                if brace_count == 0:
                                    # Found matching closing brace
                                    cleaned_text = cleaned_text[start:i + 1]
                                    parse_details["balanced_braces_extracted"] = True
                                    parse_details["extracted_start_pos"] = start
                                    parse_details["extracted_end_pos"] = i + 1
                                    break

                parse_details.update({
                    "result_length": len(result_text),
                    "cleaned_length": len(cleaned_text),
                    "first_bracket_pos": cleaned_text.find("{"),
                    "last_bracket_pos": cleaned_text.rfind("}"),
                    "has_opening_brace": cleaned_text.startswith("{"),
                    "has_closing_brace": cleaned_text.endswith("}"),
                })

                json_str_to_parse = cleaned_text
                parse_details["json_extracted_preview"] = json_str_to_parse[:200] if json_str_to_parse else ""

            # Sub-phase: JSON parsing
            with self.tracer.span("parse_json_decode", "planner"):
                try:
                    obj = json.loads(json_str_to_parse)
                    parse_details["json_keys"] = list(obj.keys())
                    parse_details["has_executor_host_ip"] = "executor_host_ip" in obj
                    parse_details["has_plan"] = "plan" in obj

                    raw_executor_ip = obj.get("executor_host_ip", "")
                    raw_plan = obj.get("plan", "")

                    parse_details["raw_executor_host_ip"] = str(raw_executor_ip) if raw_executor_ip else ""
                    parse_details["raw_plan_length"] = len(str(raw_plan)) if raw_plan else 0
                    parse_details["raw_plan_preview"] = str(raw_plan)[:100] if raw_plan else ""

                    executor_host_ip = str(raw_executor_ip or "")
                    plan_text = str(raw_plan or "")

                    parse_details["final_executor_host_ip"] = executor_host_ip
                    parse_details["final_plan_length"] = len(plan_text)

                except json.JSONDecodeError as e:
                    parse_error = f"JSON decode error: {e}"
                    parse_details["json_error"] = str(e)
                    parse_details["json_error_pos"] = e.pos if hasattr(e, 'pos') else None

                    with self.tracer.span("parse_json_recovery", "planner"):
                        recovered_executor = _extract_json_string_value(cleaned_text, "executor_host_ip")
                        recovered_plan = _extract_json_string_value(cleaned_text, "plan", allow_unterminated=True)
                        if recovered_executor or recovered_plan:
                            if recovered_executor:
                                executor_host_ip = recovered_executor
                            if recovered_plan is not None:
                                plan_text = recovered_plan
                            parse_details["recovered_partial_json"] = True
                            parse_details["recovered_executor_host_ip"] = executor_host_ip
                            parse_details["recovered_plan_length"] = len(plan_text)
                            parse_error = None
                        else:
                            # Fallback: return whole text as plan
                            plan_text = result_text
                except Exception as e:
                    parse_error = f"Parse error: {type(e).__name__}: {e}"
                    parse_details["exception_type"] = type(e).__name__
                    parse_details["exception_msg"] = str(e)
                    # Fallback: return whole text as plan
                    plan_text = result_text

            # Log parse results
            log_msg(f"[PLAN_PARSE_START]")
            if parse_error:
                log_msg(f"Parse error occurred: {parse_error}")
            log_msg(f"Parse details: {parse_details}")
            log_msg(f"Final executor_host_ip: '{executor_host_ip}'")
            log_msg(f"Final plan length: {len(plan_text)}")
            log_msg(f"Final plan preview: {plan_text[:200]}")
            log_msg(f"[PLAN_PARSE_END]")

        # Phase 7: Response building
        with self.tracer.span("response_building", "planner",
                              request_id=request_id[:8],
                              parse_error=parse_error is not None):
            response = {
                "executor_host_ip": executor_host_ip,
                "plan": plan_text,
                "model": self.config.model,
                "request_id": request_id,
                "created": datetime.now(timezone.utc).isoformat(),
            }

            # Add debug info if parsing failed
            if parse_error or (not executor_host_ip and not plan_text):
                response["_debug"] = {
                    "parse_error": parse_error,
                    "parse_details": parse_details,
                    "original_result_length": len(result_text),
                    "original_result_preview": result_text[:500],
                }

        # Phase 8: Trace write
        total_duration = (time.time() - plan_start) * 1000
        with self.tracer.span("trace_write", "planner",
                              request_id=request_id[:8],
                              total_duration_ms=total_duration):
            self.tracer.write()

        # Add overall plan span
        self.tracer.add_span(
            "plan_total",
            (plan_start - self._init_start) * 1000,
            total_duration,
            "planner",
            request_id=request_id[:8],
            alert_length=alert_len,
            result_length=len(result_text),
            plan_length=len(plan_text),
            has_parse_error=parse_error is not None,
        )

        return response

    @staticmethod
    def _load_prompts(path: str) -> tuple[str, str]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            system = str(data.get("system", "")).strip()
            human = str(data.get("human", "")).strip()
            if not system or not human:
                raise ValueError("Prompts missing 'system' or 'human' keys")
            return system, human
        except Exception as e:
            # Provide a minimal fallback that mirrors our constraints
            fallback_system = (
                "Return JSON with executor_host_ip and plan only. No code. Stop attack and prevent recurrence."
            )
            fallback_human = "IDS alert:\n{alert}"
            return fallback_system, fallback_human

    @staticmethod
    def _extract_result_text(result: Any) -> str:
        content = getattr(result, "content", None)
        return str(content) if content is not None else str(result)

    @staticmethod
    def _serialize_prompt_messages(messages: List[BaseMessage]) -> str:
        return "\n\n".join(
            f"[{message.type.upper()}]\n{message.content}" for message in messages
        )

    def _build_langfuse_callback(self) -> Optional[Any]:
        if not self.config.langfuse_enabled:
            return None
        if not self.config.langfuse_public_key or not self.config.langfuse_secret_key:
            return None
        try:
            # langfuse>=4 exposes the LangChain callback in langfuse.langchain
            from langfuse import Langfuse
            from langfuse.langchain import CallbackHandler

            client_kwargs: Dict[str, Any] = {
                "public_key": self.config.langfuse_public_key,
                "secret_key": self.config.langfuse_secret_key,
            }
            if self.config.langfuse_host:
                client_kwargs["host"] = self.config.langfuse_host
            self.langfuse_client = Langfuse(**client_kwargs)
            return CallbackHandler(public_key=self.config.langfuse_public_key)
        except ImportError:
            try:
                # Backward compatibility for older Langfuse versions
                from langfuse.callback import CallbackHandler
            except ImportError:
                # langfuse not installed or not available - gracefully degrade
                return None

        callback_kwargs: Dict[str, Any] = {
            "public_key": self.config.langfuse_public_key,
            "secret_key": self.config.langfuse_secret_key,
        }
        if self.config.langfuse_host:
            callback_kwargs["host"] = self.config.langfuse_host
        try:
            return CallbackHandler(**callback_kwargs)
        except Exception:
            # Any error creating callback - degrade gracefully
            return None

    def _start_langfuse_generation(
        self,
        *,
        request_id: str,
        alert: str,
        formatted_prompt_text: str,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> Optional[Any]:
        if self.langfuse_client is None:
            return None
        return self.langfuse_client.start_observation(
            name=self.config.langfuse_trace_name,
            as_type="generation",
            input={
                "request_id": request_id,
                "run_id": os.getenv("RUN_ID", "run"),
                "alert": alert,
                "formatted_prompt": formatted_prompt_text,
            },
            model=self.config.model,
            model_parameters={
                "temperature": temperature if temperature is not None else self.config.temperature,
                "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
            },
            metadata={
                "component": "incident_planner",
            },
        )

    def _flush_langfuse(self) -> None:
        """Flush Langfuse telemetry.

        If langfuse_async_flush is enabled (default), uses a background daemon
        thread to avoid blocking the response. Errors during background flush are
        logged but do not affect the response.
        """
        def _do_flush():
            """Internal flush function that runs in background thread."""
            try:
                if self.langfuse_client is not None:
                    client_flush_fn = getattr(self.langfuse_client, "flush", None)
                    if callable(client_flush_fn):
                        client_flush_fn()
                if self.langfuse_callback is not None:
                    flush_fn = getattr(self.langfuse_callback, "flush", None)
                    if callable(flush_fn):
                        flush_fn()
                        return
                    langfuse_client = getattr(self.langfuse_callback, "langfuse", None)
                    if langfuse_client is not None:
                        client_flush_fn = getattr(langfuse_client, "flush", None)
                        if callable(client_flush_fn):
                            client_flush_fn()
            except Exception as e:
                # Log but don't fail - telemetry is non-critical
                # Using stderr to avoid disrupting any structured logging
                import sys
                print(f"[LANGFUSE] Background flush error (non-critical): {e}",
                      file=sys.stderr, flush=True)

        # Check if async flush is enabled (default)
        if self.config.langfuse_async_flush:
            # Start background flush - daemon=True allows thread to be killed on exit
            flush_thread = threading.Thread(target=_do_flush, daemon=True)
            flush_thread.start()
            # Return immediately without waiting
        else:
            # Synchronous flush (legacy behavior)
            _do_flush()
