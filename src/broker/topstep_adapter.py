"""DEPLOY/TOPSTEP-1 — Topstep broker adapter (ProjectX Gateway API).

Real adapter for Tiona's Topstep PRACTICE account via the ProjectX Gateway API
(api.topstepx.com). Verified against official docs (June 2026):
  • Auth (API key): POST /api/Auth/loginKey {userName, apiKey} -> {token, success}
    JWT valid ~24h, sent as `Authorization: Bearer <token>`.
  • Accounts:  POST /api/Account/search      {onlyActiveAccounts} -> [{id,name,balance,canTrade,...}]
  • Positions: POST /api/Position/searchOpen  {accountId}
  • Orders:    POST /api/Order/searchOpen     {accountId}
  • Place:     POST /api/Order/place          {accountId,contractId,type,side,size,...}
  • Cancel:    POST /api/Order/cancel          {accountId,orderId}
  • Close:     POST /api/Position/closeContract{accountId,contractId}

SAFETY (TOPSTEP-1 scope):
  • PRACTICE/SIM ONLY. `_practice_guard()` refuses any write (place/cancel/close)
    unless TOPSTEP_ENV in {practice,sim,demo}. The adapter will not touch a
    funded/live account.
  • submit_order additionally requires TOPSTEP_EXECUTION_ENABLED=true (default
    off) — so reading account state never risks an order; trades stay blocked
    until explicitly enabled.
  • Credentials are read from env (Tiona enters them privately); never logged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from broker.base import BrokerAdapter, BrokerCapability, NotConnectedError

DEFAULT_BASE_URL = "https://api.topstepx.com/api"
_PRACTICE_ENVS = {"practice", "sim", "demo"}
# ProjectX enums
_SIDE = {"buy": 0, "long": 0, "bid": 0, "sell": 1, "short": 1, "ask": 1}
_OTYPE = {"limit": 1, "market": 2, "stop": 4, "trailing_stop": 5}


def _env(name, default=""):
    return (os.getenv(name, default) or "").strip()


@dataclass
class TopstepConfig:
    api_key: str
    username: str
    account_id: str
    env: str
    base_url: str

    @classmethod
    def from_env(cls) -> "TopstepConfig":
        return cls(
            api_key=_env("TOPSTEP_API_KEY"),
            username=_env("TOPSTEP_USERNAME"),
            account_id=_env("TOPSTEP_ACCOUNT_ID"),
            env=_env("TOPSTEP_ENV", "practice").lower(),
            base_url=_env("TOPSTEP_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        )

    def masked_key(self) -> str:
        k = self.api_key
        if not k:
            return "(not set)"
        return f"{k[:3]}…{k[-3:]} (len {len(k)})" if len(k) > 8 else "***"

    def credentials_present(self) -> bool:
        return bool(self.api_key and self.username)


class TopstepClient:
    """Thin REST client for the ProjectX Gateway. Never logs credentials."""

    def __init__(self, cfg: TopstepConfig, timeout: float = 15.0):
        self.cfg = cfg
        self.timeout = timeout
        self._token = None

    def _post(self, path: str, body: dict, auth: bool = True) -> dict:
        import requests  # deferred
        headers = {"Content-Type": "application/json", "accept": "text/plain"}
        if auth:
            if not self._token:
                raise NotConnectedError("not authenticated — call authenticate() first")
            headers["Authorization"] = f"Bearer {self._token}"
        resp = requests.post(f"{self.cfg.base_url}{path}", json=body,
                             headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:  # noqa: BLE001
            return {"success": False, "errorMessage": "non-json response"}

    def authenticate(self) -> dict:
        """POST /Auth/loginKey. Returns {ok, error}. Caches the JWT. Never raises
        on bad creds — returns ok=False."""
        if not self.cfg.credentials_present():
            return {"ok": False, "error": "credentials_not_configured"}
        try:
            data = self._post("/Auth/loginKey",
                              {"userName": self.cfg.username, "apiKey": self.cfg.api_key},
                              auth=False)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"auth_request_failed:{type(exc).__name__}"}
        if data.get("success") and data.get("token"):
            self._token = data["token"]
            return {"ok": True}
        return {"ok": False, "error": data.get("errorMessage") or f"errorCode={data.get('errorCode')}"}

    def accounts(self, only_active: bool = True) -> list:
        d = self._post("/Account/search", {"onlyActiveAccounts": only_active})
        return d.get("accounts") or d.get("data") or (d if isinstance(d, list) else [])

    def positions(self, account_id) -> list:
        d = self._post("/Position/searchOpen", {"accountId": account_id})
        return d.get("positions") or d.get("data") or []

    def open_orders(self, account_id) -> list:
        d = self._post("/Order/searchOpen", {"accountId": account_id})
        return d.get("orders") or d.get("data") or []

    # ── market data (read-only; DEPLOY-2B) ────────────────────────────────────
    # ProjectX Gateway market-data endpoints. Read-only: no order side effects.
    #   POST /api/Contract/search   {searchText, live} -> [{id, name, ...}]
    #   POST /api/History/retrieveBars {contractId, live, unit, unitNumber,
    #        limit, startTime, endTime, includePartialBar} -> {bars:[{t,o,h,l,c,v}]}
    def search_contract(self, symbol: str, live: bool = False) -> list:
        d = self._post("/Contract/search", {"searchText": symbol, "live": live})
        return d.get("contracts") or d.get("data") or (d if isinstance(d, list) else [])

    def retrieve_bars(self, contract_id, *, unit: int = 2, unit_number: int = 1,
                      limit: int = 300, live: bool = False,
                      start: str = None, end: str = None) -> list:
        # ProjectX unit enum: 1=Second 2=Minute 3=Hour 4=Day. (2,1) => 1-minute.
        body = {"contractId": contract_id, "live": live, "unit": unit,
                "unitNumber": unit_number, "limit": limit, "includePartialBar": False}
        if start:
            body["startTime"] = start
        if end:
            body["endTime"] = end
        d = self._post("/History/retrieveBars", body)
        return d.get("bars") or d.get("data") or []

    # ── execution history (read-only; DEPLOY-2D reconciliation) ───────────────
    #   POST /api/Trade/search {accountId, startTimestamp, endTimestamp?}
    #        -> trades [{id, accountId, contractId, creationTimestamp, price,
    #                    profitAndLoss(nullable=half-turn), fees, side, size,
    #                    voided, orderId}]
    #   POST /api/Order/search {accountId, startTimestamp, endTimestamp?}
    #        -> orders [{id, ..., status, type, side, size, limitPrice, stopPrice,
    #                    fillVolume, filledPrice, creationTimestamp, ...}]
    def search_trades(self, account_id, start: str, end: str = None) -> list:
        body = {"accountId": account_id, "startTimestamp": start}
        if end:
            body["endTimestamp"] = end
        d = self._post("/Trade/search", body)
        return d.get("trades") or d.get("data") or []

    def search_orders(self, account_id, start: str, end: str = None) -> list:
        body = {"accountId": account_id, "startTimestamp": start}
        if end:
            body["endTimestamp"] = end
        d = self._post("/Order/search", body)
        return d.get("orders") or d.get("data") or []

    def place_order(self, body: dict) -> dict:
        return self._post("/Order/place", body)

    def cancel(self, account_id, order_id) -> dict:
        return self._post("/Order/cancel", {"accountId": account_id, "orderId": order_id})

    def close_contract(self, account_id, contract_id) -> dict:
        return self._post("/Position/closeContract",
                          {"accountId": account_id, "contractId": contract_id})


class TopstepBrokerAdapter(BrokerAdapter):
    """ProjectX/Topstep practice adapter behind the broker-agnostic interface."""

    def __init__(self, config=None):
        super().__init__(config)
        self.cfg = TopstepConfig.from_env()
        self.client = TopstepClient(self.cfg)
        self._authed = False
        self._resolved_account = None
        # prefer the instance-config account_id if env didn't set one
        if not self.cfg.account_id and getattr(config, "account_id", ""):
            self.cfg.account_id = str(config.account_id)

    # ── identity / capability ──────────────────────────────────────────────────
    @property
    def name(self) -> str:
        return "topstep"

    def _execution_enabled(self) -> bool:
        return _env("TOPSTEP_EXECUTION_ENABLED", "false").lower() == "true"

    def _is_practice(self) -> bool:
        return self.cfg.env in _PRACTICE_ENVS

    def capability(self) -> BrokerCapability:
        return BrokerCapability(
            name="topstep",
            supports_orders=self._is_practice() and self._execution_enabled(),
            paper_only=self._is_practice(),
            connected=self._authed,
            notes=("ProjectX practice account; orders gated by "
                   "TOPSTEP_ENV=practice + TOPSTEP_EXECUTION_ENABLED"))

    # ── guards ──────────────────────────────────────────────────────────────────
    def _practice_guard(self):
        if not self._is_practice():
            raise NotConnectedError(
                f"refusing broker write: TOPSTEP_ENV='{self.cfg.env}' is not "
                f"practice/sim/demo (no live-money execution in TOPSTEP-1)")

    # ── connection ──────────────────────────────────────────────────────────────
    def authenticate(self) -> dict:
        res = self.client.authenticate()
        self._authed = bool(res.get("ok"))
        return res

    def validate_connection(self) -> dict:
        if not self._authed:
            res = self.authenticate()
            if not res.get("ok"):
                return {"connected": False, "reason": res.get("error")}
        accts = self._safe(lambda: self.client.accounts(True), [])
        return {"connected": True, "accounts_visible": len(accts)}

    def is_connected(self) -> bool:
        return bool(self.validate_connection().get("connected"))

    # ── reads ───────────────────────────────────────────────────────────────────
    def _safe(self, fn, default):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            return default

    def _resolve_account(self) -> dict:
        accts = self._safe(lambda: self.client.accounts(True), [])
        if self.cfg.account_id:
            for a in accts:
                if str(a.get("id")) == str(self.cfg.account_id):
                    self._resolved_account = a
                    return a
        self._resolved_account = accts[0] if accts else {}
        return self._resolved_account

    def get_account(self) -> dict:
        if not self._authed and not self.authenticate().get("ok"):
            return {"broker": "topstep", "connected": False,
                    "reason": "not_authenticated"}
        a = self._resolve_account()
        return {"broker": "topstep", "connected": True, "env": self.cfg.env,
                "account_id": a.get("id"), "name": a.get("name"),
                "balance": a.get("balance"), "can_trade": a.get("canTrade"),
                "simulated": a.get("simulated", self._is_practice())}

    def get_buying_power(self) -> dict:
        a = self.get_account()
        return {"balance": a.get("balance"), "can_trade": a.get("can_trade"),
                "account_id": a.get("account_id")}

    def get_positions(self) -> list:
        if not self._authed and not self.authenticate().get("ok"):
            return []
        acct = self._resolve_account()
        return self._safe(lambda: self.client.positions(acct.get("id")), [])

    def get_position(self, symbol: str) -> dict:
        for p in self.get_positions():
            cid = str(p.get("contractId") or p.get("contract") or "")
            if symbol and symbol.upper() in cid.upper():
                return p
        return {"symbol": symbol, "qty": 0}

    def get_open_orders(self) -> list:
        if not self._authed and not self.authenticate().get("ok"):
            return []
        acct = self._resolve_account()
        return self._safe(lambda: self.client.open_orders(acct.get("id")), [])

    def health_check(self) -> dict:
        conn = self.validate_connection()
        if not conn.get("connected"):
            return {"healthy": False, "reason": conn.get("reason"),
                    "credentials_present": self.cfg.credentials_present()}
        a = self.get_account()
        return {"healthy": True, "env": self.cfg.env,
                "account_id": a.get("account_id"), "balance": a.get("balance"),
                "can_trade": a.get("can_trade"), "simulated": a.get("simulated"),
                "open_positions": len(self.get_positions()),
                "open_orders": len(self.get_open_orders())}

    # ── writes (guarded) ─────────────────────────────────────────────────────────
    def submit_order(self, order: dict) -> dict:
        self._practice_guard()
        if not self._execution_enabled():
            raise NotConnectedError(
                "order submission disabled: set TOPSTEP_EXECUTION_ENABLED=true "
                "to allow practice orders (trades blocked by default)")
        if not self._authed and not self.authenticate().get("ok"):
            raise NotConnectedError("not authenticated")
        acct = self._resolve_account()
        side = _SIDE.get(str(order.get("side", "")).lower())
        otype = _OTYPE.get(str(order.get("type", "market")).lower(), 2)
        body = {"accountId": acct.get("id"),
                "contractId": order.get("contractId") or order.get("symbol"),
                "type": otype, "side": side,
                "size": int(order.get("size") or order.get("qty") or 0)}
        for k_src, k_dst in (("limitPrice", "limitPrice"), ("limit_price", "limitPrice"),
                             ("stopPrice", "stopPrice"), ("stop_price", "stopPrice"),
                             ("trailPrice", "trailPrice")):
            if order.get(k_src) is not None:
                body[k_dst] = order[k_src]
        # DEPLOY-2D — native ProjectX bracket legs (stop loss + take profit).
        # Forwarded verbatim from the caller's trade plan; no synthetic brackets.
        for bk in ("stopLossBracket", "takeProfitBracket"):
            if isinstance(order.get(bk), dict):
                body[bk] = order[bk]
        return self.client.place_order(body)

    def cancel_order(self, order_id) -> dict:
        self._practice_guard()
        if not self._authed and not self.authenticate().get("ok"):
            raise NotConnectedError("not authenticated")
        return self.client.cancel(self._resolve_account().get("id"), order_id)

    def flatten_position(self, contract_id: str) -> dict:
        self._practice_guard()
        if not self._authed and not self.authenticate().get("ok"):
            raise NotConnectedError("not authenticated")
        return self.client.close_contract(self._resolve_account().get("id"), contract_id)
