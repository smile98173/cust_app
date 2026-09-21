from __future__ import annotations

import threading
import time
from contextvars import ContextVar, Token
from typing import Any, Dict, List, Optional

from langchain_core.runnables import RunnableLambda

from app.config.settings import (
    LLM_ENABLE_FALLBACK,
    LLM_FALLBACK_PROVIDER,
    LLM_PROVIDER,
    LLM_RAG_SUMMARY_BASE_URL,
    LLM_RAG_SUMMARY_MODEL,
    LLM_RAG_SUMMARY_ENABLE_FALLBACK,
    LLM_RAG_SUMMARY_PROVIDER,
    LLM_RAG_SUMMARY_TEMPERATURE,
    LLM_RAG_SUMMARY_TIMEOUT_SECONDS,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TEMPERATURE,
    OPENAI_BASE_URL,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_TEMPERATURE,
)


SUPPORTED_PROVIDERS = {"ollama", "openai"}


class ModelConfigurationError(RuntimeError):
    """Raised when the selected provider cannot be constructed from configuration."""


TASK_LLM_CONFIGS = {
    "rag_summary": {
        "provider": LLM_RAG_SUMMARY_PROVIDER,
        "model": LLM_RAG_SUMMARY_MODEL,
        "base_url": LLM_RAG_SUMMARY_BASE_URL,
        "temperature": LLM_RAG_SUMMARY_TEMPERATURE,
        "timeout": LLM_RAG_SUMMARY_TIMEOUT_SECONDS,
        "enable_fallback": LLM_RAG_SUMMARY_ENABLE_FALLBACK,
    },
}
_LLM_TRACE_EVENTS: ContextVar[Optional[List[Dict[str, Any]]]] = ContextVar(
    "llm_trace_events",
    default=None,
)


def start_llm_trace() -> Token:
    return _LLM_TRACE_EVENTS.set([])


def finish_llm_trace(token: Token) -> List[Dict[str, Any]]:
    events = _LLM_TRACE_EVENTS.get() or []
    _LLM_TRACE_EVENTS.reset(token)
    return events


def record_llm_trace_event(event: Dict[str, Any]) -> None:
    events = _LLM_TRACE_EVENTS.get()
    if events is not None:
        events.append(event)


class ModelManager:
    def __init__(
        self,
        provider: str = LLM_PROVIDER,
        fallback_provider: str = LLM_FALLBACK_PROVIDER,
        enable_fallback: bool = LLM_ENABLE_FALLBACK,
    ):
        self.provider = self._normalize_provider(provider)
        self.fallback_provider = self._normalize_provider(fallback_provider)
        self.enable_fallback = enable_fallback
        self._models: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self.last_provider: Optional[str] = None
        self.last_error: Optional[str] = None
        self.llm = RunnableLambda(self.invoke)

    def _normalize_provider(self, provider: str) -> str:
        value = (provider or "ollama").lower().strip()
        if value not in SUPPORTED_PROVIDERS:
            return "ollama"
        return value

    def get_llm(self, task: str | None = None):
        if not task:
            return self.llm

        return RunnableLambda(
            lambda input_value, config=None, **kwargs: self.invoke(
                input_value,
                config=config,
                task=task,
                **kwargs,
            )
        )

    def set_provider(self, provider: str) -> Dict[str, Any]:
        normalized = self._normalize_provider(provider)
        with self._lock:
            self.provider = normalized
            self.last_error = None
        return self.status()

    def set_fallback_provider(self, provider: str) -> Dict[str, Any]:
        normalized = self._normalize_provider(provider)
        with self._lock:
            self.fallback_provider = normalized
            self.last_error = None
        return self.status()

    def _build_model(self, provider: str, model_config: Optional[Dict[str, Any]] = None):
        model_config = model_config or {}
        if provider == "openai":
            if not OPENAI_API_KEY:
                raise ModelConfigurationError(
                    "OpenAI provider is selected, but OPENAI_API_KEY is not configured."
                )
            try:
                from langchain_openai import ChatOpenAI
            except Exception as exc:
                raise RuntimeError(
                    "OpenAI provider requires langchain-openai. "
                    "Please install requirements.txt in the cust_app environment."
                ) from exc

            kwargs: Dict[str, Any] = {
                "model": model_config.get("model") or OPENAI_MODEL,
                "temperature": model_config.get("temperature", OPENAI_TEMPERATURE),
            }
            base_url = model_config.get("base_url") or OPENAI_BASE_URL
            if base_url:
                kwargs["base_url"] = base_url
            timeout = model_config.get("timeout")
            if timeout:
                kwargs["timeout"] = timeout
            kwargs["api_key"] = OPENAI_API_KEY
            return ChatOpenAI(**kwargs)

        from langchain_ollama import ChatOllama

        kwargs = {
            "model": model_config.get("model") or OLLAMA_MODEL,
            "temperature": model_config.get("temperature", OLLAMA_TEMPERATURE),
        }
        base_url = model_config.get("base_url") or OLLAMA_BASE_URL
        if base_url:
            kwargs["base_url"] = base_url
        timeout = model_config.get("timeout")
        if timeout:
            kwargs["timeout"] = timeout
        return ChatOllama(**kwargs)

    def _get_model(self, provider: str, task: str = "default", model_config: Optional[Dict[str, Any]] = None):
        model_config = model_config or {}
        model_key = "|".join([
            task,
            provider,
            str(model_config.get("model") or ""),
            str(model_config.get("base_url") or ""),
            str(model_config.get("temperature") or ""),
            str(model_config.get("timeout") or ""),
        ])
        with self._lock:
            if model_key not in self._models:
                self._models[model_key] = self._build_model(provider, model_config)
            return self._models[model_key]

    def _model_label(self, provider: str, model_config: Optional[Dict[str, Any]] = None) -> str:
        model_config = model_config or {}
        if model_config.get("model"):
            return model_config["model"]
        if provider == "openai":
            return OPENAI_MODEL
        return OLLAMA_MODEL

    def _task_config(self, task: str) -> Dict[str, Any]:
        if task not in TASK_LLM_CONFIGS:
            return {}

        raw = TASK_LLM_CONFIGS[task]
        provider = self._normalize_provider(raw.get("provider", self.provider))
        return {
            "provider": provider,
            "model": raw.get("model") or (OPENAI_MODEL if provider == "openai" else OLLAMA_MODEL),
            "base_url": raw.get("base_url") or (OPENAI_BASE_URL if provider == "openai" else OLLAMA_BASE_URL),
            "temperature": raw.get(
                "temperature",
                OPENAI_TEMPERATURE if provider == "openai" else OLLAMA_TEMPERATURE,
            ),
            "timeout": raw.get("timeout"),
            "enable_fallback": raw.get("enable_fallback", self.enable_fallback),
        }

    def invoke(
        self,
        input_value: Any,
        config: Optional[Dict[str, Any]] = None,
        task: str | None = None,
        **kwargs,
    ):
        task_name = task or "primary"
        task_config = self._task_config(task_name)
        provider = task_config.pop("provider", self.provider) if task_config else self.provider
        enable_fallback = task_config.pop("enable_fallback", self.enable_fallback) if task_config else self.enable_fallback
        started = time.perf_counter()
        try:
            model = self._get_model(provider, task=task_name, model_config=task_config)
            result = model.invoke(input_value, config=config, **kwargs)
            duration_sec = time.perf_counter() - started
            self.last_provider = provider
            self.last_error = None
            record_llm_trace_event({
                "task": task_name,
                "provider": provider,
                "model": self._model_label(provider, task_config),
                "success": True,
                "fallback": False,
                "duration_sec": round(duration_sec, 3),
            })
            return result
        except Exception as exc:
            failed_duration_sec = time.perf_counter() - started
            self.last_error = f"{provider}: {exc}"
            record_llm_trace_event({
                "task": task_name,
                "provider": provider,
                "model": self._model_label(provider, task_config),
                "success": False,
                "fallback": False,
                "duration_sec": round(failed_duration_sec, 3),
                "error": str(exc),
            })

            # A missing or invalid local provider configuration is not a
            # transient model outage. Falling back here hides a broken launch
            # environment and can unexpectedly send requests to another model.
            if isinstance(exc, ModelConfigurationError):
                raise

            fallback_provider = self.fallback_provider
            if task_name != "primary" and self.provider != provider:
                fallback_provider = self.provider

            if not enable_fallback or fallback_provider == provider:
                raise

            fallback_started = time.perf_counter()
            try:
                fallback_model = self._get_model(fallback_provider, task=f"{task_name}:fallback")
                result = fallback_model.invoke(input_value, config=config, **kwargs)
                fallback_duration_sec = time.perf_counter() - fallback_started
                self.last_provider = fallback_provider
                record_llm_trace_event({
                    "task": task_name,
                    "provider": fallback_provider,
                    "model": self._model_label(fallback_provider),
                    "success": True,
                    "fallback": True,
                    "duration_sec": round(fallback_duration_sec, 3),
                })
                return result
            except Exception as fallback_exc:
                fallback_duration_sec = time.perf_counter() - fallback_started
                record_llm_trace_event({
                    "task": task_name,
                    "provider": fallback_provider,
                    "model": self._model_label(fallback_provider),
                    "success": False,
                    "fallback": True,
                    "duration_sec": round(fallback_duration_sec, 3),
                    "error": str(fallback_exc),
                })
                raise

    def status(self) -> Dict[str, Any]:
        rag_summary_provider = self._normalize_provider(LLM_RAG_SUMMARY_PROVIDER)
        rag_summary_base_url = (
            LLM_RAG_SUMMARY_BASE_URL
            or (OPENAI_BASE_URL if rag_summary_provider == "openai" else OLLAMA_BASE_URL)
            or None
        )
        return {
            "provider": self.provider,
            "fallback_provider": self.fallback_provider,
            "fallback_enabled": self.enable_fallback,
            "last_provider": self.last_provider,
            "last_error": self.last_error,
            "models": {
                "ollama": {
                    "model": OLLAMA_MODEL,
                    "base_url": OLLAMA_BASE_URL or None,
                    "temperature": OLLAMA_TEMPERATURE,
                },
                "openai": {
                    "model": OPENAI_MODEL,
                    "base_url": OPENAI_BASE_URL or None,
                    "temperature": OPENAI_TEMPERATURE,
                    "api_key_configured": bool(OPENAI_API_KEY),
                },
            },
            "task_models": {
                "rag_summary": {
                    "provider": rag_summary_provider,
                    "model": LLM_RAG_SUMMARY_MODEL,
                    "base_url": rag_summary_base_url,
                    "temperature": LLM_RAG_SUMMARY_TEMPERATURE,
                    "timeout": LLM_RAG_SUMMARY_TIMEOUT_SECONDS,
                    "fallback_enabled": LLM_RAG_SUMMARY_ENABLE_FALLBACK,
                },
            },
        }
