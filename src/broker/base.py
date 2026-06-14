"""DEPLOY-1 Phase 7 — Broker adapter interface.

A minimal, broker-agnostic contract the core can call without knowing the
venue. Concrete adapters translate to their broker. DEPLOY-1 connects only the
paper adapter; live adapters are interface-only stubs (no real money).
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Optional


class NotConnectedError(RuntimeError):
    """Raised when a stub/unconfigured adapter is asked to execute."""


@dataclass
class BrokerCapability:
    name: str
    supports_orders: bool = False     # can it place orders in DEPLOY-1?
    paper_only: bool = True
    connected: bool = False
    notes: str = ""


class BrokerAdapter(abc.ABC):
    """Broker-agnostic execution surface. Concrete subclasses implement it."""

    def __init__(self, config=None):
        self.config = config
        self.account_id = getattr(config, "account_id", "") if config else ""

    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @abc.abstractmethod
    def capability(self) -> BrokerCapability: ...

    @abc.abstractmethod
    def is_connected(self) -> bool: ...

    @abc.abstractmethod
    def get_account(self) -> dict: ...

    @abc.abstractmethod
    def get_position(self, symbol: str) -> dict: ...

    @abc.abstractmethod
    def submit_order(self, order: dict) -> dict: ...

    def describe(self) -> dict:
        cap = self.capability()
        return {"name": self.name, "account_id": self.account_id,
                "connected": self.is_connected(),
                "supports_orders": cap.supports_orders,
                "paper_only": cap.paper_only, "notes": cap.notes}
