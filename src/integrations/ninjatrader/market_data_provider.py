"""Phase 7 — NinjaTrader MNQ market-data provider.

Implements the organism's BaseDataProvider contract (1-minute candles; higher
timeframes are built by the existing deterministic timeframe_builder so there is
ONE canonical source of truth). Bars are sourced from the NinjaScript bridge
(BAR_CLOSED / HISTORICAL_BARS_RESPONSE) and pass through the BarGatekeeper
invariants before the organism ever sees them.

A `BarSource` is any object exposing `historical_1m(instrument, lookback)` and
`buffered_bars()`. In production this is the bridge client; in tests it is a
deterministic mock. This keeps NinjaTrader out of the organism core.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

# BaseDataProvider lives in data_feed; import defensively so this module can be
# unit-tested even if the wider package import graph is heavy.
try:
    from data_feed.provider_interface import BaseDataProvider, DataFeedError
except Exception:  # pragma: no cover - fallback for isolated tests
    class DataFeedError(Exception):
        pass

    class BaseDataProvider:  # minimal shim
        pass

from integrations.ninjatrader.bar_gatekeeper import BarGatekeeper
from integrations.ninjatrader.instrument_spec import InstrumentSpec, CANONICAL_SYMBOL, DENIED_ROOTS

VOLUME_PROVENANCE_LABEL = "ninjatrader_futures_feed"


@runtime_checkable
class BarSource(Protocol):
    def historical_1m(self, instrument: str, lookback: int) -> list: ...
    def buffered_bars(self) -> list: ...


class NinjaTraderMNQProvider(BaseDataProvider):
    """1m MNQ candle provider gated by BarGatekeeper. Refuses non-MNQ symbols and
    never labels QQQ/continuous data as the tradable expiry."""

    def __init__(self, spec: InstrumentSpec, source: BarSource):
        self.spec = spec
        self.source = source
        self.gatekeeper = BarGatekeeper(
            expected_instrument=spec.ninjatrader_name,
            expected_expiry=spec.expiry,
        )

    # ── symbol guard ─────────────────────────────────────────────────────────
    def _assert_symbol(self, symbol: str):
        s = str(symbol).strip().upper()
        root = s.split(" ")[0]
        if root in DENIED_ROOTS:
            raise DataFeedError(f"symbol root {root!r} (NQ) is DENIED for MNQ provider")
        if root != CANONICAL_SYMBOL:
            raise DataFeedError(f"symbol {symbol!r} is not {CANONICAL_SYMBOL} — refusing "
                                f"(this provider never serves non-MNQ data)")

    def _filter(self, bars: list) -> list:
        """Run every candidate bar through the gatekeeper; return only accepted,
        stamping the volume provenance label."""
        out = []
        for b in bars or []:
            acc = self.gatekeeper.accept_bar(b)
            if acc.accepted:
                rec = dict(b)
                rec.setdefault("instrument", self.spec.ninjatrader_name)
                rec.setdefault("expiry", self.spec.expiry)
                rec["volume_provenance"] = VOLUME_PROVENANCE_LABEL
                out.append(rec)
        return out

    def fetch_1m_candles(self, symbol: str, lookback_bars: int) -> list:
        self._assert_symbol(symbol)
        raw = self.source.historical_1m(self.spec.ninjatrader_name, lookback_bars)
        candles = self._filter(raw)
        if not candles:
            raise DataFeedError(
                f"no valid MNQ 1m candles available (health={self.gatekeeper.health}, "
                f"reason={self.gatekeeper.last_reason})")
        return candles

    def health(self) -> str:
        return self.gatekeeper.health

    def fresh_entry_ready(self) -> bool:
        return self.gatekeeper.fresh_entry_ready()
