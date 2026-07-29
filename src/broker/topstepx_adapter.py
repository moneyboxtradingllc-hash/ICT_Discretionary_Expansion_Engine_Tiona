"""TopstepX broker adapter — the execution surface for Topstep's own platform.

TopstepX has no NinjaTrader bridge, so an operator on Topstep cannot use the
deterministic lane's usual transport at all. This adapter implements the
broker-agnostic contract in `broker/base.py` against the ProjectX Gateway API.

SAFETY POSTURE

The NinjaTrader integration keeps a hardcoded account allowlist because NT does
not reliably tell us whether an account is real money — the allowlist is the only
way to be certain. TopstepX does tell us: `TradingAccountModel.simulated` is a
fact from the venue. So the gate here is that fact, checked at connect time, and
routing to a non-simulated account requires TOPSTEPX_ALLOW_LIVE=true set
deliberately. Nothing defaults toward real money.

WHAT THIS ADAPTER DOES NOT KNOW

Topstep enforces a TRAILING maximum drawdown that follows peak equity. This bot
models a static daily loss ceiling and has no trailing-drawdown concept at all,
so it can believe it is well inside its limits while the account is one trade
from being closed. That gap is real, it is not fixed here, and it is not
something an execution adapter can fix — it belongs in the risk model. Until it
exists, `capability().notes` says so, and the preflight prints it.
"""
from __future__ import annotations

import os
from typing import Optional

from broker.base import BrokerAdapter, BrokerCapability, NotConnectedError
from broker.topstepx_client import (
    TopstepXAccount, TopstepXClient, TopstepXContract, TopstepXError,
)

__all__ = ["TopstepXBrokerAdapter", "TopstepXConfigError", "load_topstepx_config"]


class TopstepXConfigError(RuntimeError):
    """Configuration is absent or incomplete. Never guessed around."""


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def load_topstepx_config() -> dict:
    """Read per-operator TopstepX settings from the environment (.env).

    Every value is required and none has a default. A default account name would
    mean one operator's bot could address another operator's account, and a
    default contract would mean trading an instrument nobody chose.
    """
    cfg = {
        "username": os.getenv("TOPSTEPX_USERNAME", "").strip(),
        "api_key": os.getenv("TOPSTEPX_API_KEY", "").strip(),
        "account_name": os.getenv("TOPSTEPX_ACCOUNT_NAME", "").strip(),
        "contract": os.getenv("TOPSTEPX_CONTRACT", "").strip(),
        "allow_live": _flag("TOPSTEPX_ALLOW_LIVE", False),
    }
    missing = [k.upper() for k in ("username", "api_key", "account_name", "contract")
               if not cfg[k]]
    if missing:
        raise TopstepXConfigError(
            "TopstepX is not configured. Missing: "
            + ", ".join(f"TOPSTEPX_{m}" for m in missing)
            + ".\nCopy .env.template to .env and fill them in. The API key comes "
              "from TopstepX -> Settings -> API (API access is a paid add-on)."
        )
    return cfg


class TopstepXBrokerAdapter(BrokerAdapter):
    """Execution against one named, verified TopstepX account."""

    def __init__(self, config=None, *, client: Optional[TopstepXClient] = None) -> None:
        super().__init__(config)
        self._cfg = load_topstepx_config()
        self._client = client or TopstepXClient(self._cfg["username"], self._cfg["api_key"])
        self._account: Optional[TopstepXAccount] = None
        self._contract: Optional[TopstepXContract] = None
        self._connect_error: Optional[str] = None

    # ── identity ──────────────────────────────────────────────────────────────
    @property
    def name(self) -> str:
        return "topstepx"

    def capability(self) -> BrokerCapability:
        acct = self._account
        return BrokerCapability(
            name=self.name,
            supports_orders=bool(acct and acct.can_trade),
            paper_only=bool(acct.simulated) if acct else True,
            connected=self.is_connected(),
            notes=("Trailing max drawdown is NOT modelled by this bot; Topstep "
                   "enforces one that follows peak equity."),
        )

    # ── connection ────────────────────────────────────────────────────────────
    def connect(self) -> TopstepXAccount:
        """Authenticate, resolve the account and contract, and verify the account
        is one this bot is permitted to trade. Raises rather than degrading."""
        account = self._client.account_by_name(self._cfg["account_name"])

        if not account.simulated and not self._cfg["allow_live"]:
            raise NotConnectedError(
                f"account {account.name!r} is NOT simulated — this is real money.\n"
                f"The bot refuses by default. If that is genuinely intended, set "
                f"TOPSTEPX_ALLOW_LIVE=true, and understand first that this bot does "
                f"not model Topstep's trailing drawdown."
            )
        if not account.can_trade:
            raise NotConnectedError(
                f"account {account.name!r} reports canTrade=false. Topstep has "
                f"disabled trading on it — commonly a breached rule or an "
                f"evaluation that has ended."
            )

        self._contract = self._client.resolve_contract(self._cfg["contract"])
        self._account = account
        self.account_id = str(account.id)
        self._connect_error = None
        return account

    def is_connected(self) -> bool:
        return self._account is not None and self._contract is not None

    def _require(self) -> tuple[TopstepXAccount, TopstepXContract]:
        if not self.is_connected():
            raise NotConnectedError(
                "TopstepX adapter is not connected; call connect() first"
                + (f" (last error: {self._connect_error})" if self._connect_error else "")
            )
        return self._account, self._contract  # type: ignore[return-value]

    # ── reads ─────────────────────────────────────────────────────────────────
    def get_account(self) -> dict:
        account, contract = self._require()
        # Re-read rather than serve the cached copy: balance moves, and sizing
        # that compounds off equity must not compound off a stale number.
        fresh = self._client.account_by_name(self._cfg["account_name"])
        self._account = fresh
        return {
            "account": fresh.name, "account_id": fresh.id,
            "cash_value": fresh.balance, "balance": fresh.balance,
            "can_trade": fresh.can_trade, "simulated": fresh.simulated,
            "contract_id": contract.id, "instrument": contract.name,
            "tick_size": contract.tick_size, "tick_value": contract.tick_value,
        }

    def get_position(self, symbol: str = "") -> dict:
        account, contract = self._require()
        wanted = symbol or contract.id
        for pos in self._client.open_positions(account.id):
            if pos["contract_id"] == wanted:
                return {"known": True, "flat": False, **pos}
        return {"known": True, "flat": True, "contract_id": wanted, "size": 0,
                "side": "flat", "avg_price": 0.0}

    def bars_1m(self, minutes_back: int = 1500) -> list[dict]:
        """Closed 1-minute bars — the lane's market data, since there is no NT feed."""
        _, contract = self._require()
        return self._client.bars(contract.id, minutes_back=minutes_back,
                                 unit="minute", unit_number=1)

    # ── writes ────────────────────────────────────────────────────────────────
    def submit_order(self, order: dict) -> dict:
        """Place a bracketed market order.

        Expects the lane's intent shape: direction (long/short), quantity, and
        stop/target expressed as POINT distances. Prices are not accepted — the
        venue takes ticks, and converting from a price here would need a fill
        price the order does not have yet.
        """
        account, contract = self._require()
        direction = str(order.get("direction") or order.get("side") or "").lower()
        side = {"long": "buy", "buy": "buy", "short": "sell", "sell": "sell"}.get(direction)
        if side is None:
            raise TopstepXError(f"unrecognised direction {direction!r}")

        qty = int(order.get("quantity") or order.get("size") or 0)
        stop_points = float(order.get("stop_points") or 0.0)
        target_points = float(order.get("target_points") or 0.0)

        result = self._client.place_bracket_market_order(
            account_id=account.id, contract=contract, side=side, size=qty,
            stop_points=stop_points, target_points=target_points,
            custom_tag=order.get("tag"),
        )
        return {"accepted": True, "order_id": result["order_id"],
                "broker": self.name, "account": account.name,
                "contract_id": contract.id, "side": side, "quantity": qty,
                "stop_points": stop_points, "target_points": target_points,
                "stop_ticks": result["submitted"]["stopLossBracket"]["ticks"],
                "target_ticks": result["submitted"]["takeProfitBracket"]["ticks"]}

    def flatten(self) -> dict:
        account, contract = self._require()
        self._client.close_position(account.id, contract.id)
        return {"flattened": True, "contract_id": contract.id}
