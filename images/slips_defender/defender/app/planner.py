from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv

# LangChain core + OpenAI-compatible chat model
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import BaseMessage


load_dotenv()  # Load .env if present; intentionally early to set env for model


def _is_truthy(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class PlannerConfig:
    model: str = os.getenv("LLM_MODEL", "gpt-oss-120b")
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "1200"))
    # OpenAI-compatible endpoint values
    openai_base_url: Optional[str] = os.getenv("OPENAI_BASE_URL")
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
    # Optional Langfuse tracing
    langfuse_enabled: bool = _is_truthy(os.getenv("LANGFUSE_ENABLED"), default=True)
    langfuse_public_key: Optional[str] = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: Optional[str] = os.getenv("LANGFUSE_SECRET_KEY")
    langfuse_host: Optional[str] = os.getenv("LANGFUSE_HOST")
    langfuse_trace_name: str = os.getenv("LANGFUSE_TRACE_NAME", "incident_planner")


import yaml


class IncidentPlanner:
    """
    LangChain-based planner that takes an IDS alert and returns a
    concrete English remediation plan using an OpenAI-compatible endpoint.
    """

    def __init__(self, config: Optional[PlannerConfig] = None, prompts_path: Optional[str] = None):
        self.config = config or PlannerConfig()
        self.prompts_path = prompts_path or os.getenv("PROMPTS_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts.yaml"))

        # Ensure environment variables are set for OpenAI-compatible clients
        if self.config.openai_base_url:
            os.environ.setdefault("OPENAI_BASE_URL", self.config.openai_base_url)
        if self.config.openai_api_key:
            os.environ.setdefault("OPENAI_API_KEY", self.config.openai_api_key)

        # Build the model
        self.llm = ChatOpenAI(
            model=self.config.model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            # ChatOpenAI reads OPENAI_BASE_URL and OPENAI_API_KEY from env; base_url can also be passed explicitly
            base_url=self.config.openai_base_url,
            api_key=self.config.openai_api_key,
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
        # Log the exact alert being sent to planner
        import sys
        import os
        
        # Log file path
        log_file = f"/outputs/{os.getenv('RUN_ID', 'run')}/logs/planner_llm_detailed.log"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        # Helper to log to both stderr and file
        def log_msg(msg):
            print(msg, file=sys.stderr, flush=True)
            with open(log_file, 'a') as f:
                f.write(msg + "\n")

        request_id = str(uuid.uuid4())
        invoke_config: Dict[str, Any] = {
            "metadata": {
                "request_id": request_id,
                "component": "incident_planner",
            },
            "run_name": self.config.langfuse_trace_name,
        }
        if self.langfuse_callback is not None:
            invoke_config["callbacks"] = [self.langfuse_callback]
         
        log_msg(f"[PLANNER_LLM_INPUT_START]")
        log_msg(f"Alert length: {len(alert)}")
        log_msg(f"Alert contains base64 marker: {'VUc5' in alert or 'base64' in alert.lower()}")
        log_msg(f"[ALERT_TEXT]")
        log_msg(alert)
        log_msg(f"[ALERT_TEXT_END]")
         
        # Build formatted prompt messages (always, for logging purposes)
        formatted_messages = self.prompt.format_messages(alert=alert)
        formatted_prompt_text = self._serialize_prompt_messages(formatted_messages)
        log_msg(f"[LLM_FULL_FORMATTED_PROMPT_START]")
        log_msg(formatted_prompt_text)
        log_msg(f"[LLM_FULL_FORMATTED_PROMPT_END]")
        
        # Explicit Langfuse generation capture to guarantee full planner input/output payloads
        langfuse_generation = self._start_langfuse_generation(
            request_id=request_id,
            alert=alert,
            formatted_prompt_text=formatted_prompt_text,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            # Allow per-request overrides
            if temperature is not None or max_tokens is not None:
                llm = ChatOpenAI(
                    model=self.config.model,
                    temperature=temperature if temperature is not None else self.config.temperature,
                    max_tokens=max_tokens if max_tokens is not None else self.config.max_tokens,
                    base_url=self.config.openai_base_url,
                    api_key=self.config.openai_api_key,
                                )
                result_message = llm.invoke(formatted_messages, config=invoke_config)
                result_text = self._extract_result_text(result_message)
            else:
                result_text = self.chain.invoke({"alert": alert}, config=invoke_config)
            
            if langfuse_generation is not None:
                langfuse_generation.update(output=result_text)
            
            log_msg(f"[LLM_OUTPUT_START]")
            log_msg(result_text)
            log_msg(f"[LLM_OUTPUT_END]")
            log_msg(f"[PLANNER_LLM_INPUT_END]")
        finally:
            if langfuse_generation is not None:
                langfuse_generation.end()
            self._flush_langfuse()

        # Parse strict JSON: {"executor_host_ip": "...", "plan": "..."}
        executor_host_ip: str = ""
        plan_text: str = ""
        try:
            import json
            # be resilient to any leading/trailing text
            start = result_text.find("{")
            end = result_text.rfind("}")
            obj = json.loads(result_text[start:end + 1] if start != -1 and end != -1 and end > start else result_text)
            executor_host_ip = str(obj.get("executor_host_ip", "") or "")
            plan_text = str(obj.get("plan", "") or "")
        except Exception:
            # Fallback: return whole text as plan
            plan_text = result_text

        return {
            "executor_host_ip": executor_host_ip,
            "plan": plan_text,
            "model": self.config.model,
            "request_id": request_id,
            "created": datetime.now(timezone.utc).isoformat(),
        }

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
        if self.langfuse_client is not None:
            client_flush_fn = getattr(self.langfuse_client, "flush", None)
            if callable(client_flush_fn):
                client_flush_fn()
        if self.langfuse_callback is None:
            return
        flush_fn = getattr(self.langfuse_callback, "flush", None)
        if callable(flush_fn):
            flush_fn()
            return
        langfuse_client = getattr(self.langfuse_callback, "langfuse", None)
        if langfuse_client is None:
            return
        client_flush_fn = getattr(langfuse_client, "flush", None)
        if callable(client_flush_fn):
            client_flush_fn()
