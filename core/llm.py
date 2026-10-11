"""Model factory.

Every LLM call in the system goes through `chat()` or `structured()`, which
adds retries, an optional fallback model and fault injection. Tests replace
these two functions with scripted stubs, so no test needs an API key.

Model choice: the large model handles the steps where reasoning quality
decides the outcome (routing, research planning, the final answer). The small
model handles steps that run many times per question (batch analysis,
classification, memory extraction), where cost and latency multiply.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, TypeVar

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from core.config import get_settings
from core.resilience import check_fault

Size = Literal["large", "small"]
S = TypeVar("S", bound=BaseModel)


@lru_cache(maxsize=8)
def _model(spec: str, streaming: bool = False) -> BaseChatModel:
    settings = get_settings()
    kwargs: dict = {}
    if spec.startswith("anthropic:") and settings.anthropic_workspace_id:
        kwargs["default_headers"] = {"anthropic-workspace-id": settings.anthropic_workspace_id}
    return init_chat_model(spec, timeout=settings.llm_timeout_s, max_retries=0, streaming=streaming, **kwargs)


def _guarded(runnable: Runnable) -> Runnable:
    def gate(value):
        check_fault("llm")
        return value
    return RunnableLambda(gate, name="llm_fault_gate") | runnable


def _with_resilience(primary: Runnable, fallback: Runnable | None) -> Runnable:
    settings = get_settings()
    wrapped = _guarded(primary).with_retry(stop_after_attempt=settings.llm_max_retries + 1,
                                            wait_exponential_jitter=True)
    if fallback is not None:
        wrapped = wrapped.with_fallbacks([fallback])
    return wrapped


def chat(size: Size = "large", *, tools: list | None = None, tags: list[str] | None = None) -> Runnable:
    """A chat model runnable, optionally with tools bound."""
    settings = get_settings()
    spec = settings.llm_large if size == "large" else settings.llm_small
    primary: Runnable = _model(spec, streaming=True)
    fallback: Runnable | None = _model(settings.llm_fallback, streaming=True) if settings.llm_fallback else None
    if tools:
        primary = primary.bind_tools(tools)
        fallback = fallback.bind_tools(tools) if fallback is not None else None
    runnable = _with_resilience(primary, fallback)
    return runnable.with_config(tags=tags or [], run_name=f"chat_{size}")


def structured(schema: type[S], size: Size = "large") -> Runnable:
    """A runnable returning an instance of `schema`."""
    settings = get_settings()
    spec = settings.llm_large if size == "large" else settings.llm_small
    primary = _model(spec).with_structured_output(schema)
    fallback = _model(settings.llm_fallback).with_structured_output(schema) if settings.llm_fallback else None
    return _with_resilience(primary, fallback).with_config(run_name=f"{schema.__name__}_{size}")
