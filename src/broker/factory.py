"""DEPLOY-1 Phase 7 — Broker adapter factory.

Maps an instance config's `broker` field to the concrete adapter. The core asks
the factory; it never imports a specific broker. Defaults to the paper adapter.
"""
from __future__ import annotations

from broker.base import BrokerAdapter


class BrokerSelectionError(RuntimeError):
    """No broker was configured, or the named one is not registered."""


_REGISTRY = {}


def _registry():
    if not _REGISTRY:
        from broker.paper_adapter import PaperBrokerAdapter
        from broker.tradestation_adapter import TradeStationBrokerAdapter
        _REGISTRY.update({
            "paper": PaperBrokerAdapter,
            "tradestation": TradeStationBrokerAdapter,
        })
        # LUNA-TOPSTEPX-ONLY (2026-08-31). The NinjaTrader adapter was
        # registered here behind a lazy import. Both it and the venue
        # were removed: there is no bridge, no adapter and no account
        # configuration left to reach, so registering a name that can
        # never resolve would only make `broker: ninjatrader` fail
        # later and less clearly than not offering it at all.
        # TOPSTEPX — Topstep's own platform has no NinjaTrader bridge, so this
        # adapter is the entire transport for an operator there: execution AND
        # market data. Registered for explicit `broker: topstepx`; the default
        # stays paper. It refuses a non-simulated account unless the operator
        # sets TOPSTEPX_ALLOW_LIVE, so registering it arms nothing by itself.
        # READ-ONLY, DELIBERATELY. This registry used to hand out the fully
        # mutating adapter: `get_adapter(broker="topstepx")` returned place,
        # cancel, modify and close authority over an environment-selected
        # account, with no certified execution authority anywhere in the path.
        # The audit found no operational caller -- and "nothing calls it today"
        # is the same reasoning that left an ungated `close_position` alive in
        # the deterministic lane until a combined certification went looking.
        # The safety boundary is the ACCOUNT, not the entrypoint.
        #
        # Order authority belongs to the certified production organism, which
        # never resolves through this factory.
        try:
            from broker.topstepx_read_capability import (
                ReadOnlyTopstepXBrokerAdapter)
            _REGISTRY["topstepx"] = ReadOnlyTopstepXBrokerAdapter
        except Exception:  # noqa: BLE001 — optional like the others
            pass
    return _REGISTRY


def available_brokers() -> list:
    return sorted(_registry().keys())


def get_adapter(config=None, broker: str = None) -> BrokerAdapter:
    """Return the adapter for `broker` (or config.broker).

    DECON-3 (2026-08-05): an unknown or missing broker used to resolve to the
    paper adapter, which is an Alpaca client. Silently routing an unrecognised
    venue to a retired one is exactly the substitution this engine must never
    make, so an unknown name now raises.
    """
    name = (broker or getattr(config, "broker", None) or "").lower().strip()
    if not name:
        raise BrokerSelectionError(
            "no broker configured and there is no default; set broker: topstepx")
    cls = _registry().get(name)
    if cls is None:
        raise BrokerSelectionError(
            f"unknown broker {name!r}; available: {', '.join(available_brokers())}")
    return cls(config)
