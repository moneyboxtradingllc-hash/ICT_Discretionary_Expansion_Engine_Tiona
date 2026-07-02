"""DEPLOY-1 Phase 7 — Broker Adapter Layer.

Abstracts execution so the bot core does not care which broker is active; the
instance config selects the adapter. DEPLOY-1 ships:
  • paper       — wraps the existing Alpaca PAPER broker (real, paper-only)
  • tradestation— stub (interface only; not connected — no live money)
"""
from broker.factory import get_adapter   # noqa: F401
from broker.base import BrokerAdapter, BrokerCapability, NotConnectedError  # noqa: F401
