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
        from broker.topstep_adapter import TopstepBrokerAdapter
        from broker.tradestation_adapter import TradeStationBrokerAdapter
        _REGISTRY.update({
            "paper": PaperBrokerAdapter,
            "topstep": TopstepBrokerAdapter,
            "tradestation": TradeStationBrokerAdapter,
        })
    return _REGISTRY


def available_brokers() -> list:
    return sorted(_registry().keys())


def get_adapter(config=None, broker: str = None) -> BrokerAdapter:
    """Return the adapter for `broker` (or config.broker). Unknown → paper."""
    name = (broker or getattr(config, "broker", None) or "paper").lower().strip()
    cls = _registry().get(name, _registry()["paper"])
    return cls(config)
