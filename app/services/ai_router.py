"""AZ-FF2: Multi-model AI router.

Intelligent fallback routing across LLM providers for AI chat, quiz
generation and grading assistance, with strict budget capping and a
semantic cache layer. Provider calls are injected so the router stays
testable and provider-agnostic.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.cache import get as cache_get
from app.core.cache import set as cache_set


class LLMProvider(Protocol):
    name: str

    def complete(self, prompt: str, **kwargs: Any) -> str: ...


@dataclass
class RouterConfig:
    budget_cap_usd: float = 10.0
    cache_ttl: int = 300
    max_retries: int = 2


@dataclass
class RouterResult:
    text: str
    provider: str
    cached: bool
    latency_ms: float
    cost_usd: float = 0.0


@dataclass
class BudgetTracker:
    spent_usd: float = 0.0
    cap_usd: float = 10.0

    def can_spend(self, amount: float) -> bool:
        return (self.spent_usd + amount) <= self.cap_usd

    def record(self, amount: float) -> None:
        self.spent_usd += amount


def _cache_key(prompt: str, provider_hint: str) -> str:
    h = hashlib.sha256((provider_hint + "::" + prompt).encode()).hexdigest()
    return f"ai:semantic:{h}"


class AIRouter:
    def __init__(
        self,
        providers: list[LLMProvider],
        config: RouterConfig | None = None,
        budget: BudgetTracker | None = None,
        cost_estimator: Callable[[str, str], float] | None = None,
    ) -> None:
        if not providers:
            raise ValueError("at least one provider required")
        self.providers = providers
        self.config = config or RouterConfig()
        self.budget = budget or BudgetTracker(cap_usd=self.config.budget_cap_usd)
        self.cost_estimator = cost_estimator or (lambda p, t: 0.0)
        self._fallback_index = 0

    def _try_cache(self, prompt: str) -> str | None:
        for p in self.providers:
            cached = cache_get(_cache_key(prompt, p.name))
            if cached is not None:
                return cached
        return None

    def complete(self, prompt: str, **kwargs: Any) -> RouterResult:
        # Semantic cache check.
        cached_text = self._try_cache(prompt)
        if cached_text is not None:
            return RouterResult(text=cached_text, provider="cache", cached=True, latency_ms=0.0, cost_usd=0.0)

        last_err: Exception | None = None
        for _attempt in range(self.config.max_retries + 1):
            for provider in self.providers:
                est = self.cost_estimator(provider.name, prompt)
                if not self.budget.can_spend(est):
                    continue
                start = time.monotonic()
                try:
                    text = provider.complete(prompt, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    continue
                latency = (time.monotonic() - start) * 1000.0
                self.budget.record(est)
                # Cache the result under the first provider's key.
                cache_set(_cache_key(prompt, self.providers[0].name), text, ttl=self.config.cache_ttl)
                return RouterResult(text=text, provider=provider.name, cached=False, latency_ms=latency, cost_usd=est)
            # all providers failed this attempt
        if last_err is not None:
            raise last_err
        raise RuntimeError("no provider available (budget exhausted or all failed)")

    @property
    def spent(self) -> float:
        return self.budget.spent_usd
