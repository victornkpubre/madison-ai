"""
resilience.py
═════════════════════
Single resilient choke point for every direct LLM call across the backend.

Modelled on the production error-handling pattern: retry with exponential
backoff, a circuit breaker, a fallback chain across models, and a response
cache — combined the same way as a RobustLLMClient. The one adaptation
needed for this codebase: every real call site here is either a plain
prompt, a tool-bound call (.bind_tools(...)), or a structured-output call
(.with_structured_output(...)) — never just a bare model.invoke(messages).
So instead of a fallback chain of ready-made clients, this holds a chain of
*base* chat models and applies a `bind` function (supplied by the caller)
to each one in turn — same fallback/breaker/retry/cache behavior, just
generalised to whatever shape the caller actually needs.

Usage
─────
    # plain completion
    text = (await invoke_llm(prompt)).content

    # tool-bound agent turn
    response = await invoke_llm(messages, bind=lambda m: m.bind_tools(TOOLS))

    # structured output
    result = await invoke_llm(prompt, bind=lambda m: m.with_structured_output(Schema),
                              cache_tag="idea_score")
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Optional

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from config import settings

try:
    from langchain_anthropic import ChatAnthropic
except ImportError:  # langchain-anthropic not installed — Claude fallback just won't be in the chain
    ChatAnthropic = None


# ── Circuit breaker ──────────────────────────────────────────────────────────

class CircuitBreaker:
    """Stops hammering a model that's already failing. Opens after
    `failure_threshold` consecutive failures; once `recovery_timeout`
    seconds have passed, the NEXT check (is_open or call()) moves it to
    half-open and lets one attempt through to test recovery; that attempt
    closes it again on success or re-opens it on failure.

    `is_open` performs that time-based transition itself (not just a flat
    state check) — callers that skip straight to the next fallback model
    whenever is_open is true would otherwise never give a long-open breaker
    a chance to heal, since the recovery check would never run.
    """

    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0.0
        self.state = "closed"

    @property
    def is_open(self) -> bool:
        if self.state == "open" and time.time() - self.last_failure_time > self.recovery_timeout:
            self.state = "half-open"
        return self.state == "open"

    async def call(self, coro_func, *args, **kwargs):
        if self.is_open:
            raise RuntimeError("circuit breaker open — failing fast")
        try:
            result = await coro_func(*args, **kwargs)
            if self.state == "half-open":
                self.state = "closed"
                self.failures = 0
            return result
        except Exception:
            self.failures += 1
            self.last_failure_time = time.time()
            if self.failures >= self.failure_threshold:
                self.state = "open"
            raise


def with_async_retry(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 10.0,
                     exceptions: tuple = (Exception,)):
    """Exponential backoff with jitter around a single async call."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc: Optional[Exception] = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        delay *= 0.5 + random.random()
                        await asyncio.sleep(delay)
            raise last_exc
        return wrapper
    return decorator


# ── Fallback chain ────────────────────────────────────────────────────────────

@dataclass
class _ModelSpec:
    name: str
    model: BaseChatModel
    breaker: CircuitBreaker = field(
        default_factory=lambda: CircuitBreaker(failure_threshold=3, recovery_timeout=30.0))


def _build_chain() -> list[_ModelSpec]:
    """Primary model first (whatever OPENAI_MODEL is configured to — gpt-4o-mini
    by default), then a stronger same-provider fallback, then a cross-provider
    fallback. Claude is only included if ANTHROPIC_API_KEY is set, so this
    degrades gracefully on setups with only an OpenAI key configured."""
    chain = [
        _ModelSpec(
            settings.openai_model,
            ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, timeout=30),
        ),
        _ModelSpec(
            "gpt-4o",
            ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key, timeout=30),
            breaker=CircuitBreaker(failure_threshold=3, recovery_timeout=60.0),
        ),
    ]
    if settings.anthropic_api_key and ChatAnthropic is not None:
        chain.append(_ModelSpec(
            "claude-sonnet",
            ChatAnthropic(model="claude-sonnet-4-5", api_key=settings.anthropic_api_key, timeout=30),
            breaker=CircuitBreaker(failure_threshold=3, recovery_timeout=60.0),
        ))
    return chain


class RobustLLMClient:
    """
    Production LLM client combining:
    - Fallback chain (primary → stronger same-provider → cross-provider)
    - Circuit breaker per model
    - Retry with exponential backoff per attempt
    - Response cache (opt-in per call, keyed by caller-supplied tag)
    """

    def __init__(self, models: list[_ModelSpec] | None = None):
        self.models = models if models is not None else _build_chain()
        self.cache: dict[str, Any] = {}

    @with_async_retry(max_retries=3, base_delay=1.0, max_delay=10.0)
    async def _call_model(self, spec: _ModelSpec, runnable, prompt_or_messages):
        return await spec.breaker.call(runnable.ainvoke, prompt_or_messages)

    async def invoke(self, prompt_or_messages, *,
                     bind: Optional[Callable[[BaseChatModel], Any]] = None,
                     cache_tag: str = "", use_cache: bool = True):
        """
        Invoke with the full protection stack.

        bind:       applied to each candidate model to produce the runnable
                    actually called (e.g. lambda m: m.bind_tools([...]), or
                    lambda m: m.with_structured_output(Schema)). Omit for a
                    plain completion.
        cache_tag:  short, stable label identifying this call site (e.g.
                    "idea_score"). Required for a cache hit to be safe —
                    without it, two call sites that happen to send the same
                    prompt text but expect different response shapes could
                    collide. Calls made without a tag are never cached.
        """
        cache_key = f"{cache_tag}:{prompt_or_messages}" if (use_cache and cache_tag) else None
        if cache_key and cache_key in self.cache:
            return self.cache[cache_key]

        errors = []
        for spec in self.models:
            if spec.breaker.is_open:
                errors.append(f"{spec.name}: circuit open")
                continue
            try:
                runnable = bind(spec.model) if bind else spec.model
                result = await self._call_model(spec, runnable, prompt_or_messages)
                if cache_key:
                    self.cache[cache_key] = result
                return result
            except Exception as e:
                errors.append(f"{spec.name}: {e}")
                continue

        raise RuntimeError("All models failed:\n" + "\n".join(errors))

    def status(self) -> dict:
        """Check the state of every circuit breaker."""
        return {spec.name: spec.breaker.state for spec in self.models}


# Process-wide singleton — every direct LLM call in the backend goes through this.
llm_client = RobustLLMClient()


async def invoke_llm(prompt_or_messages, *,
                     bind: Optional[Callable[[BaseChatModel], Any]] = None,
                     cache_tag: str = "", use_cache: bool = True):
    """Module-level convenience wrapper around the shared llm_client."""
    return await llm_client.invoke(prompt_or_messages, bind=bind,
                                   cache_tag=cache_tag, use_cache=use_cache)
