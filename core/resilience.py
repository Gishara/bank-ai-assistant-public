"""Fault injection, circuit breakers and timeouts shared by all backends."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from core.config import get_settings

T = TypeVar("T")


class Faults:
    """Runtime-toggleable fault injection for demonstrating degradation.

    Seeded from the FAULTS environment variable and changeable by an
    administrator through the API.
    """

    KNOWN = frozenset({"llm", "pinecone", "mcp"})

    def __init__(self) -> None:
        self._active: set[str] = {f.strip() for f in get_settings().faults.split(",") if f.strip()} & self.KNOWN

    def active(self, name: str) -> bool:
        return name in self._active

    def set(self, name: str, on: bool) -> None:
        if name not in self.KNOWN:
            raise ValueError(f"Unknown fault {name!r}; expected one of {sorted(self.KNOWN)}")
        (self._active.add if on else self._active.discard)(name)

    def snapshot(self) -> dict[str, bool]:
        return {name: name in self._active for name in sorted(self.KNOWN)}


faults = Faults()


class InjectedFault(RuntimeError):
    pass


def check_fault(name: str) -> None:
    if faults.active(name):
        raise InjectedFault(f"Injected fault: {name} unavailable")


class CircuitOpen(RuntimeError):
    pass


class CircuitBreaker:
    """Opens after `threshold` consecutive failures; half-opens after `reset_s`."""

    def __init__(self, name: str, threshold: int = 3, reset_s: float = 30.0) -> None:
        self.name = name
        self.threshold = threshold
        self.reset_s = reset_s
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if time.monotonic() - self.opened_at >= self.reset_s:
            return "half_open"
        return "open"

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        if self.state == "open":
            raise CircuitOpen(f"{self.name} circuit is open")
        try:
            result = await fn()
        except Exception:
            self.failures += 1
            if self.failures >= self.threshold or self.state == "half_open":
                self.opened_at = time.monotonic()
            raise
        self.failures = 0
        self.opened_at = None
        return result


breakers = {
    "pinecone": CircuitBreaker("pinecone"),
    "mcp": CircuitBreaker("mcp"),
}


async def with_timeout(coro: Awaitable[T], seconds: float | None = None) -> T:
    return await asyncio.wait_for(coro, timeout=seconds or get_settings().tool_timeout_s)
