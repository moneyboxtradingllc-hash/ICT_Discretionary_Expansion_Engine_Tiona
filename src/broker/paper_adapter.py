"""DEPLOY-1 Phase 7 — Paper broker adapter.

Wraps the existing Alpaca PAPER broker (`paper_execution.paper_broker`) behind
the broker-agnostic interface. Paper-only by construction: paper_broker itself
refuses any non-paper endpoint. The bot core talks to this adapter, not to
Alpaca directly.
"""
from __future__ import annotations

from broker.base import BrokerAdapter, BrokerCapability


class PaperBrokerAdapter(BrokerAdapter):
    @property
    def name(self) -> str:
        return "paper"

    def capability(self) -> BrokerCapability:
        return BrokerCapability(
            name="paper", supports_orders=True, paper_only=True,
            connected=self.is_connected(),
            notes="Alpaca paper endpoint (paper-only; refuses live URLs)")

    def is_connected(self) -> bool:
        try:
            from paper_execution import paper_broker
            paper_broker._validate_paper_endpoint()   # raises if unsafe/missing
            return True
        except Exception:  # noqa: BLE001
            return False

    def get_account(self) -> dict:
        from paper_execution import paper_broker
        fn = getattr(paper_broker, "get_account", None)
        return fn() if callable(fn) else {"broker": "paper", "account_id": self.account_id}

    def get_position(self, symbol: str) -> dict:
        from paper_execution import paper_broker
        fn = getattr(paper_broker, "get_position", None)
        return fn(symbol) if callable(fn) else {"symbol": symbol, "qty": 0}

    def submit_order(self, order: dict) -> dict:
        from paper_execution import paper_broker
        for cand in ("submit_order", "submit_bracket_order", "place_order"):
            fn = getattr(paper_broker, cand, None)
            if callable(fn):
                return fn(order)
        raise RuntimeError("paper_broker exposes no submit function")
