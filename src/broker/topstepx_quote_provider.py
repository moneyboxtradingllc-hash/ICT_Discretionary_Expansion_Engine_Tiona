"""Live executable-quote provider for the final submit boundary.

Attaches to an ALREADY-RUNNING TopstepX market hub and keeps the newest
`GatewayQuote` in memory. At submit time the provider hands back that snapshot
synchronously — no HTTP request, no poll, no sleep, no second market-data
connection. The submit boundary is the one place where a blocking call would
delay an authorized order reaching its protection.

Freshness is REPORTED, never repaired. A stale quote still returns, carrying its
age, so the measurement can be marked unreliable and the candidate rejected at
submit — rather than the provider silently waiting for a better one while the
authorization ages.
"""
from __future__ import annotations

from datetime import datetime, timezone

from broker.topstepx_slippage import QuoteCapture, capture_quote


class QuoteProviderError(RuntimeError):
    """The provider is not usable for this contract."""


class LiveQuoteProvider:
    """Newest GatewayQuote for one contract, read straight from memory."""

    def __init__(self, hub, contract, *, clock=None) -> None:
        if hub is None:
            raise QuoteProviderError("no market hub; refusing to fabricate a provider")
        self.hub = hub
        self.contract = contract
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._last: dict = {}
        self._last_at: "datetime | None" = None
        self.volatility_state = ""
        hub.on("GatewayQuote", self._on_quote)

    # ── stream ────────────────────────────────────────────────────────────────
    def _on_quote(self, args) -> None:
        """GatewayQuote -> [contractId, {bestBid, bestAsk, lastPrice, ...}]."""
        if not args or len(args) < 2 or not isinstance(args[1], dict):
            return
        if args[0] and args[0] != self.contract.id:
            return                      # never mix contracts into one provider
        q = args[1]
        for key in ("bestBid", "bestAsk", "lastPrice", "timestamp"):
            if q.get(key) is not None:
                self._last[key] = q[key]
        self._last_at = self._clock()

    # ── read ──────────────────────────────────────────────────────────────────
    def age_seconds(self, now: datetime = None) -> "float | None":
        if self._last_at is None:
            return None
        return ((now or self._clock()) - self._last_at).total_seconds()

    def has_quote(self) -> bool:
        return self._last.get("bestBid") is not None or self._last.get("bestAsk") is not None

    def capture(self, volatility_state: str = None) -> QuoteCapture:
        """Snapshot for the submit boundary. Synchronous, allocation only."""
        age = self.age_seconds()
        return capture_quote(
            market_hub_quote=dict(self._last), contract_id=self.contract.id,
            # No quote at all is reported as an enormous age rather than zero,
            # so it is classified stale instead of passing as fresh.
            market_data_age_seconds=(age if age is not None else 1e9),
            volatility_state=(volatility_state if volatility_state is not None
                              else self.volatility_state),
            now=self._clock())

    def __call__(self) -> QuoteCapture:
        return self.capture()

    def describe(self) -> dict:
        return {"provider": type(self).__name__,
                "contract_id": self.contract.id,
                "source": "Topstep realtime in-memory quote stream",
                "has_quote": self.has_quote(),
                "age_seconds": self.age_seconds(),
                "best_bid": self._last.get("bestBid"),
                "best_ask": self._last.get("bestAsk")}
