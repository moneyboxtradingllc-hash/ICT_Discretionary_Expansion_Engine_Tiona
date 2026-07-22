"""Deterministic session authority (session-scoped, NOT per-trade human tokens).

Holds the live risk-and-state envelope for one trading session and persists it so
a restart can RECONSTRUCT trade count, realized P&L, position, working orders,
and risk before permitting another entry. Fail-closed: if reconciliation is
unknown, the session refuses new entries.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict, field
from typing import Optional

from integrations.ninjatrader.deterministic import (
    MODE, AUTHOR, ACCOUNT, INSTRUMENT, MAX_RISK_DOLLARS, TARGET_POINTS, MAX_STOP_POINTS,
    MAX_TRADES_PER_DAY, DAILY_LOSS_CEILING, DECISION_WINDOW, EVIDENCE_ERA,
)

SESSION_PATH = os.path.join("data", "integration", "ninjatrader", "deterministic",
                            "session_state.json")

# Session lifecycle states.
ACTIVE = "ACTIVE"
STOPPED_TRADE_LIMIT = "STOPPED_TRADE_LIMIT"
STOPPED_LOSS_CEILING = "STOPPED_LOSS_CEILING"
STOPPED_EOD = "STOPPED_EOD"
STOPPED_MANUAL = "STOPPED_MANUAL"
STOPPED_SAFETY = "STOPPED_SAFETY"


@dataclass
class SessionAuthority:
    session_id: str = field(default_factory=lambda: "DET-" + uuid.uuid4().hex[:12])
    mode: str = MODE
    author: str = AUTHOR
    account: str = ACCOUNT
    instrument: str = INSTRUMENT
    max_risk_usd: float = MAX_RISK_DOLLARS
    target_points: float = TARGET_POINTS
    max_stop_points: float = MAX_STOP_POINTS
    session_start: float = field(default_factory=time.time)
    decision_window: tuple = DECISION_WINDOW
    max_trades: int = MAX_TRADES_PER_DAY
    daily_loss_ceiling: float = DAILY_LOSS_CEILING
    evidence_era: str = EVIDENCE_ERA

    trade_count: int = 0
    realized_pnl: float = 0.0          # session realized P&L ($); losses negative
    open_realized_baseline: float = 0.0  # broker realized P&L captured at trade open
    active_position_qty: int = 0
    active_order_ids: list = field(default_factory=list)
    used_intent_ids: list = field(default_factory=list)
    used_client_order_ids: list = field(default_factory=list)
    state: str = ACTIVE
    last_reconcile_ok: bool = False

    def is_duplicate(self, intent_id: str, client_order_id: str) -> tuple:
        if intent_id in self.used_intent_ids:
            return True, f"duplicate intent_id {intent_id}"
        if client_order_id in self.used_client_order_ids:
            return True, f"duplicate client_order_id {client_order_id}"
        return False, ""

    def register_ids(self, intent_id: str, client_order_id: str):
        self.used_intent_ids.append(intent_id)
        self.used_client_order_ids.append(client_order_id)
        self.save()

    # ── realized loss helper ────────────────────────────────────────────────
    def realized_loss(self) -> float:
        """Positive number = dollars lost so far this session (0 if net positive)."""
        return max(0.0, -self.realized_pnl)

    # ── admission gates ─────────────────────────────────────────────────────
    def can_enter(self) -> tuple:
        """May a NEW entry be authorized right now? Fail-closed."""
        if self.state != ACTIVE:
            return False, f"session state {self.state}"
        if not self.last_reconcile_ok:
            return False, "reconciliation not known-clean — fail closed"
        if self.trade_count >= self.max_trades:
            return False, f"daily trade limit reached ({self.trade_count}/{self.max_trades})"
        if self.realized_loss() >= self.daily_loss_ceiling:
            return False, f"daily-loss ceiling reached ({self.realized_loss()})"
        if self.active_position_qty != 0:
            return False, "already positioned (max 1 simultaneous position)"
        if self.active_order_ids:
            return False, "working entry/exit orders exist"
        return True, "entry admissible"

    def record_trade_opened(self, order_ids: list, quantity: int = 0,
                            realized_baseline: float = 0.0):
        self.trade_count += 1
        self.active_position_qty = int(quantity)   # actual risk-sized fill qty
        self.active_order_ids = list(order_ids)
        self.open_realized_baseline = float(realized_baseline)  # for close-delta P&L
        self.save()

    def record_trade_closed(self, realized_delta: float):
        self.realized_pnl = round(self.realized_pnl + float(realized_delta), 2)
        self.active_position_qty = 0
        self.active_order_ids = []
        if self.trade_count >= self.max_trades:
            self.state = STOPPED_TRADE_LIMIT
        elif self.realized_loss() >= self.daily_loss_ceiling:
            self.state = STOPPED_LOSS_CEILING
        self.save()

    def apply_reconciliation(self, position: dict, orders: dict):
        """Update live position/order state from a bridge reconcile. Sets
        last_reconcile_ok only when both are KNOWN."""
        pos_known = bool((position or {}).get("known"))
        ord_known = bool((orders or {}).get("known"))
        if pos_known and ord_known:
            self.active_position_qty = int(position.get("qty", 0))
            cnt = int(orders.get("working_order_count", 0))
            if self.active_position_qty == 0 and cnt == 0:
                self.active_order_ids = []
            self.last_reconcile_ok = True
        else:
            # Unknown reconcile blocks NEW entries this scan (can_enter fails on
            # last_reconcile_ok) but does NOT permanently kill the session — the
            # next scan retries. A persistent failure keeps entries blocked.
            self.last_reconcile_ok = False
        self.save()

    def stop_new_entries(self, reason_state: str = STOPPED_MANUAL):
        self.state = reason_state
        self.save()

    # ── persistence / restart reconstruction ────────────────────────────────
    def to_dict(self) -> dict:
        d = asdict(self)
        d["decision_window"] = list(self.decision_window)
        return d

    def save(self, path: str = SESSION_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load(cls, path: str = SESSION_PATH) -> Optional["SessionAuthority"]:
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return None
        d["decision_window"] = tuple(d.get("decision_window", DECISION_WINDOW))
        known = set(cls.__dataclass_fields__.keys())
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def resume_or_new(cls, path: str = SESSION_PATH) -> "SessionAuthority":
        """Restart reconstruction: resume today's session if present, else new.
        The caller MUST apply_reconciliation() from the bridge before entries."""
        existing = cls.load(path)
        if existing is not None:
            # Reconstructed state must be re-reconciled against the bridge before
            # any new entry, so force last_reconcile_ok False on resume.
            existing.last_reconcile_ok = False
            return existing
        s = cls()
        s.save(path)
        return s
