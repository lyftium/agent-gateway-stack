"""Per-tenant request and token quotas (token buckets, in process memory).

Tokens are charged after the response, from the upstream's reported usage, so a
tenant can overdraw by at most one request. Limits are per replica: with N
gateway replicas a tenant gets up to N times its quota. A shared store
(Redis, or Limitador when running under Kuadrant) removes that; see docs/design.md.
"""

from __future__ import annotations

import time
from collections.abc import Callable

Clock = Callable[[], float]


class TokenBucket:
    def __init__(self, capacity: float, refill_per_s: float, clock: Clock) -> None:
        self._capacity = capacity
        self._rate = refill_per_s
        self._clock = clock
        self._level = capacity
        self._updated = clock()

    def _refill(self) -> None:
        now = self._clock()
        self._level = min(self._capacity, self._level + (now - self._updated) * self._rate)
        self._updated = now

    def wait_for(self, amount: float) -> float:
        """Seconds until `amount` is available; 0 if it is available now."""
        self._refill()
        if self._level >= amount:
            return 0.0
        return (amount - self._level) / self._rate

    def take(self, amount: float) -> None:
        self._refill()
        self._level -= amount


class Quotas:
    def __init__(self, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._requests: dict[str, TokenBucket] = {}
        self._tokens: dict[str, TokenBucket] = {}

    def _buckets(self, tenant: str, rpm: int, tpm: int) -> tuple[TokenBucket, TokenBucket]:
        if tenant not in self._requests:
            self._requests[tenant] = TokenBucket(rpm, rpm / 60, self._clock)
            self._tokens[tenant] = TokenBucket(tpm, tpm / 60, self._clock)
        return self._requests[tenant], self._tokens[tenant]

    def admit(self, tenant: str, rpm: int, tpm: int) -> float:
        """Consume one request slot. Returns 0 if admitted, else a Retry-After in seconds."""
        requests, tokens = self._buckets(tenant, rpm, tpm)
        wait = max(requests.wait_for(1), tokens.wait_for(1))
        if wait == 0:
            requests.take(1)
        return wait

    def charge_tokens(self, tenant: str, rpm: int, tpm: int, used: int) -> None:
        _, tokens = self._buckets(tenant, rpm, tpm)
        tokens.take(used)
