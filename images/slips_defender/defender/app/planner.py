from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from dotenv import load_dotenv

# LangChain core + OpenAI-compatible chat model
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain.schema import SystemMessage, HumanMessage


load_dotenv()  # Load .env if present; intentionally early to set env for model


@dataclass
class PlannerConfig:
    model: str = os.getenv("LLM_MODEL", "gpt-oss-120b")
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "1200"))
    # OpenAI-compatible endpoint values
    openai_base_url: Optional[str] = os.getenv("OPENAI_BASE_URL")
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")


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

        self.chain = self.prompt | self.llm | StrOutputParser()

    def plan(self, alert: str, *, temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> Dict[str, Any]:
        # Allow per-request overrides
        if temperature is not None or max_tokens is not None:
            llm = ChatOpenAI(
                model=self.config.model,
                temperature=temperature if temperature is not None else self.config.temperature,
                max_tokens=max_tokens if max_tokens is not None else self.config.max_tokens,
                base_url=self.config.openai_base_url,
                api_key=self.config.openai_api_key,
                            )
            result_text = llm.invoke(self.prompt.format(alert=alert))
        else:
            result_text = self.chain.invoke({"alert": alert})

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
            "request_id": str(uuid.uuid4()),
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
