"""DEPLOY-1 Phase 7 — Broker adapter factory.

Maps an instance config's `broker` field to the concrete adapter. The core asks
the factory; it never imports a specific broker. Defaults to the paper adapter.
"""
from __future__ import annotations

from broker.base import BrokerAdapter

_REGISTRY = {}


def _registry():
    if not _REGISTRY:
        from broker.paper_adapter import PaperBrokerAdapter
        from broker.tradestation_adapter import TradeStationBrokerAdapter
        _REGISTRY.update({
            "paper": PaperBrokerAdapter,
            "tradestation": TradeStationBrokerAdapter,
        })
        # NINJATRADER-MNQ-INTEGRATION-FOUNDATION — DEMO8458533 MNQ adapter, DISARMED.
        # Registered so it is reachable by explicit `broker: ninjatrader`, but the
        # default stays `paper`. Imported lazily so its integration deps never
        # load for QQQ/paper runs.
        try:
            from integrations.ninjatrader.execution_adapter import NinjaTraderBrokerAdapter
            _REGISTRY["ninjatrader"] = NinjaTraderBrokerAdapter
        except Exception:  # noqa: BLE001 — integration package optional
            pass
        # TOPSTEPX — Topstep's own platform has no NinjaTrader bridge, so this
        # adapter is the entire transport for an operator there: execution AND
        # market data. Registered for explicit `broker: topstepx`; the default
        # stays paper. It refuses a non-simulated account unless the operator
        # sets TOPSTEPX_ALLOW_LIVE, so registering it arms nothing by itself.
        try:
            from broker.topstepx_adapter import TopstepXBrokerAdapter
            _REGISTRY["topstepx"] = TopstepXBrokerAdapter
        except Exception:  # noqa: BLE001 — optional like the others
            pass
    return _REGISTRY


def available_brokers() -> list:
    return sorted(_registry().keys())


def get_adapter(config=None, broker: str = None) -> BrokerAdapter:
    """Return the adapter for `broker` (or config.broker). Unknown → paper."""
    name = (broker or getattr(config, "broker", None) or "paper").lower().strip()
    cls = _registry().get(name, _registry()["paper"])
    return cls(config)
