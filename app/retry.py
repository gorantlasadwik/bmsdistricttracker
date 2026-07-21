"""
ShowPulser Retry Decorator
Exponential backoff retry wrapper for scraping functions.
"""
from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable, TypeVar

from loguru import logger

F = TypeVar("F", bound=Callable[..., Any])


def with_retry(max_attempts: int = 3, base_delay: float = 2.0, backoff: float = 2.0):
    """
    Decorator that retries an async function on exception.
    Delay: base_delay * (backoff ** attempt)
    """
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    delay = base_delay * (backoff ** attempt)
                    logger.warning(
                        f"[Retry {attempt + 1}/{max_attempts}] {fn.__name__} failed: {exc}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(delay)
            logger.error(f"{fn.__name__} failed after {max_attempts} attempts: {last_exc}")
            raise last_exc  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator
