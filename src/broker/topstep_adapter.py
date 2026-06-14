"""DEPLOY-1 Phase 7 — Topstep broker adapter (STUB).

Interface-only. DEPLOY-1 does NOT connect live money or real accounts. This
adapter declares the Topstep surface and refuses to execute until a real
integration is added in a later, explicitly-authorized phase.
"""
from __future__ import annotations

from broker.base import BrokerAdapter, BrokerCapability, NotConnectedError


class TopstepBrokerAdapter(BrokerAdapter):
    @property
    def name(self) -> str:
        return "topstep"

    def capability(self) -> BrokerCapability:
        return BrokerCapability(
            name="topstep", supports_orders=False, paper_only=False,
            connected=False,
            notes="STUB — not connected in DEPLOY-1 (no live money)")

    def is_connected(self) -> bool:
        return False

    def get_account(self) -> dict:
        return {"broker": "topstep", "account_id": self.account_id,
                "connected": False, "stub": True}

    def get_position(self, symbol: str) -> dict:
        return {"symbol": symbol, "qty": 0, "stub": True}

    def submit_order(self, order: dict) -> dict:
        raise NotConnectedError(
            "Topstep adapter is a DEPLOY-1 stub — live execution not authorized.")
