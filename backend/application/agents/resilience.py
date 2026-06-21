from __future__ import annotations

import asyncio
import random
import time
from functools import wraps


class CircuitBreaker:
    """Stops hammering a failing provider. Opens after `failure_threshold`
    consecutive failures, half-opens after `recovery_timeout` seconds to test
    recovery, and closes again on the first success."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0.0
        self.state = "closed"

    async def call(self, coro_func, *args, **kwargs):
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
            else:
                raise RuntimeError("LLM circuit breaker open — failing fast")

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


def with_async_retry(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 10.0):
    """Exponential backoff with jitter around a single async call."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        delay *= 0.5 + random.random()
                        await asyncio.sleep(delay)
            raise last_exc
        return wrapper
    return decorator


# one breaker shared by every call that wires through invoke_llm()
_llm_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)


@with_async_retry(max_retries=3, base_delay=1.0, max_delay=10.0)
async def _protected_call(coro_func, *args, **kwargs):
    return await _llm_breaker.call(coro_func, *args, **kwargs)


async def invoke_llm(runnable, prompt_or_messages):
    """Single choke point for direct LLM calls across the backend."""
    return await _protected_call(runnable.ainvoke, prompt_or_messages)
