"""DEPLOY-1 Phase 7 — TradeStation broker adapter (STUB).

Interface-only. DEPLOY-1 does NOT connect live money or real accounts. Refuses
to execute until a real integration is added in a later authorized phase.
"""
from __future__ import annotations

from broker.base import BrokerAdapter, BrokerCapability, NotConnectedError


class TradeStationBrokerAdapter(BrokerAdapter):
    @property
    def name(self) -> str:
        return "tradestation"

    def capability(self) -> BrokerCapability:
        return BrokerCapability(
            name="tradestation", supports_orders=False, paper_only=False,
            connected=False,
            notes="STUB — not connected in DEPLOY-1 (no live money)")

    def is_connected(self) -> bool:
        return False

    def get_account(self) -> dict:
        return {"broker": "tradestation", "account_id": self.account_id,
                "connected": False, "stub": True}

    def get_position(self, symbol: str) -> dict:
        return {"symbol": symbol, "qty": 0, "stub": True}

    def submit_order(self, order: dict) -> dict:
        raise NotConnectedError(
            "TradeStation adapter is a DEPLOY-1 stub — live execution not authorized.")
