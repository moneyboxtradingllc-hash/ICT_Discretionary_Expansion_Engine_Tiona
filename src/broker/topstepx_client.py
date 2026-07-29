"""TopstepX (ProjectX Gateway) REST client.

Topstep's own web platform has no NinjaTrader bridge, so the deterministic lane's
usual transport does not exist there. This speaks the ProjectX Gateway API that
TopstepX is built on, which supplies BOTH execution and market data — the bot
needs both, and losing the NT bridge loses both at once.

Contract source: https://api.topstepx.com/swagger/v1/swagger.json (Swagger 2.0),
read directly rather than inferred. Every enum below is from that document.

Three things in the API map onto defects this project has already paid for:

  * `includePartialBar` — the forming-bar class. A bar that has not closed yet
    reports a high/low/close that will still change, and every downstream
    measurement built on it silently describes a moment that has not happened.
    This client pins it False and does not expose it.

  * `TradingAccountModel.simulated` — the venue itself tells us whether an
    account is real money. The NinjaTrader lane could only enforce that with a
    hardcoded account allowlist; here it is a fact we can check, so we do, and
    routing to a non-simulated account requires an explicit opt-in.

  * Brackets are expressed in TICKS, not prices. `ContractModel.tickSize` is the
    only correct conversion and it is per-contract — hardcoding 0.25 for MNQ
    would silently misprice a stop the day the bot trades anything else.

No SignalR/WebSocket here. The deterministic lane polls bars and account state,
so REST is sufficient; a streaming layer can be added without touching this.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

__all__ = [
    "TopstepXClient", "TopstepXError", "TopstepXAuthError", "TopstepXAccount",
    "TopstepXContract", "ORDER_TYPE", "ORDER_SIDE", "BAR_UNIT", "POSITION_TYPE",
]

BASE_URL = "https://api.topstepx.com"

# ── enums, verbatim from the swagger definitions ──────────────────────────────
ORDER_TYPE = {"unknown": 0, "limit": 1, "market": 2, "stop_limit": 3, "stop": 4,
              "trailing_stop": 5, "join_bid": 6, "join_ask": 7}
ORDER_SIDE = {"buy": 0, "sell": 1}            # Bid = 0, Ask = 1
BAR_UNIT = {"second": 1, "minute": 2, "hour": 3, "day": 4, "week": 5, "month": 6,
            "tick": 7}
POSITION_TYPE = {0: "undefined", 1: "long", 2: "short"}

# PlaceOrderErrorCode — 4 is the one that matters most on a prop account.
PLACE_ORDER_ERRORS = {
    0: "Success", 1: "AccountNotFound", 2: "OrderRejected", 3: "InsufficientFunds",
    4: "AccountViolation", 5: "OutsideTradingHours", 6: "OrderPending",
    7: "UnknownError", 8: "ContractNotFound", 9: "ContractNotActive",
    10: "AccountRejected",
}


class TopstepXError(RuntimeError):
    """A call reached the venue and the venue refused it."""


class TopstepXAuthError(TopstepXError):
    """Credentials rejected, or the session could not be established."""


@dataclass(frozen=True)
class TopstepXAccount:
    id: int
    name: str
    balance: float
    can_trade: bool
    simulated: bool

    @classmethod
    def from_api(cls, d: dict) -> "TopstepXAccount":
        return cls(id=int(d["id"]), name=str(d.get("name") or ""),
                   balance=float(d.get("balance") or 0.0),
                   can_trade=bool(d.get("canTrade")),
                   simulated=bool(d.get("simulated")))


@dataclass(frozen=True)
class TopstepXContract:
    id: str
    name: str
    description: str
    tick_size: float
    tick_value: float
    active: bool

    @classmethod
    def from_api(cls, d: dict) -> "TopstepXContract":
        return cls(id=str(d["id"]), name=str(d.get("name") or ""),
                   description=str(d.get("description") or ""),
                   tick_size=float(d.get("tickSize") or 0.0),
                   tick_value=float(d.get("tickValue") or 0.0),
                   active=bool(d.get("activeContract")))

    def points_to_ticks(self, points: float) -> int:
        """Convert a price distance to the tick count brackets require.

        Rounds DOWN so a converted stop is never wider than the one the risk
        model approved — the cap is a cap, and a rounding that widens it is the
        same defect as widening it deliberately.
        """
        if self.tick_size <= 0:
            raise TopstepXError(f"contract {self.id} reports tickSize={self.tick_size}; "
                                f"cannot convert {points} points to ticks")
        return max(1, int(points / self.tick_size))


def _default_transport(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:400]
        except Exception:  # noqa: BLE001 — the status code is the signal
            pass
        raise TopstepXError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise TopstepXError(f"cannot reach {url}: {exc.reason}") from exc
    return json.loads(raw) if raw else {}


class TopstepXClient:
    """Authenticated REST access to one TopstepX account.

    `transport` exists so the whole client is testable without a network or a
    paid API subscription: it is called as transport(url, payload, headers,
    timeout) and returns the decoded JSON body.
    """

    def __init__(self, username: str, api_key: str, *, base_url: str = BASE_URL,
                 timeout: float = 15.0,
                 transport: Optional[Callable[..., dict]] = None,
                 clock: Optional[Callable[[], datetime]] = None) -> None:
        if not username or not api_key:
            raise TopstepXAuthError(
                "TopstepX needs both a username and an API key. Set "
                "TOPSTEPX_USERNAME and TOPSTEPX_API_KEY in .env — see .env.template. "
                "The key is generated in TopstepX under Settings -> API."
            )
        self.username = username
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport or _default_transport
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        self._contract_cache: dict[str, TopstepXContract] = {}

    # ── session ───────────────────────────────────────────────────────────────
    def _authenticate(self) -> None:
        out = self._transport(f"{self.base_url}/api/Auth/loginKey",
                              {"userName": self.username, "apiKey": self._api_key},
                              {"Content-Type": "application/json", "accept": "text/plain"},
                              self.timeout)
        if not out.get("success") or not out.get("token"):
            code = out.get("errorCode")
            msg = out.get("errorMessage") or ""
            hint = ""
            if code == 9:      # ApiSubscriptionNotFound
                hint = (" — TopstepX API access is a paid add-on; it must be active "
                        "on the account before the key works.")
            elif code == 10:   # ApiKeyAuthenticationDisabled
                hint = " — API key authentication is disabled for this account."
            raise TopstepXAuthError(f"TopstepX login rejected (errorCode={code}) {msg}{hint}")
        self._token = out["token"]
        # Documented as 24h. Refresh at 20h so a long session never trades on a
        # token that expires mid-order.
        self._token_expires = self._clock() + timedelta(hours=20)

    def _session_token(self) -> str:
        if self._token is None or (self._token_expires and self._clock() >= self._token_expires):
            self._authenticate()
        return self._token  # type: ignore[return-value]

    def _post(self, path: str, payload: dict, *, _retry: bool = True) -> dict:
        headers = {"Content-Type": "application/json", "accept": "text/plain",
                   "Authorization": f"Bearer {self._session_token()}"}
        try:
            out = self._transport(f"{self.base_url}{path}", payload, headers, self.timeout)
        except TopstepXError as exc:
            if _retry and "HTTP 401" in str(exc):
                self._token = None                    # expired early; re-auth once
                return self._post(path, payload, _retry=False)
            raise
        if not out.get("success", True):
            raise TopstepXError(
                f"{path} failed: errorCode={out.get('errorCode')} "
                f"{out.get('errorMessage') or ''}".strip())
        return out

    # ── reads ─────────────────────────────────────────────────────────────────
    def accounts(self, only_active: bool = True) -> list[TopstepXAccount]:
        out = self._post("/api/Account/search", {"onlyActiveAccounts": bool(only_active)})
        return [TopstepXAccount.from_api(a) for a in (out.get("accounts") or [])]

    def account_by_name(self, name: str) -> TopstepXAccount:
        """Resolve one account by EXACT name. Never guesses.

        A prop trader can hold several accounts — an evaluation, a funded one, a
        reset. Picking 'the first active account' would silently trade the wrong
        one, so the name must match exactly and ambiguity is an error.
        """
        wanted = (name or "").strip()
        if not wanted:
            raise TopstepXError("no account name configured; set TOPSTEPX_ACCOUNT_NAME")
        found = [a for a in self.accounts() if a.name.strip() == wanted]
        if not found:
            available = ", ".join(sorted(a.name for a in self.accounts())) or "(none active)"
            raise TopstepXError(f"account {wanted!r} not found. Active accounts: {available}")
        if len(found) > 1:
            raise TopstepXError(f"account name {wanted!r} matched {len(found)} accounts; "
                                f"names must be unique to route safely")
        return found[0]

    def search_contracts(self, text: str, live: bool = False) -> list[TopstepXContract]:
        out = self._post("/api/Contract/search", {"searchText": text, "live": bool(live)})
        return [TopstepXContract.from_api(c) for c in (out.get("contracts") or [])]

    def resolve_contract(self, text: str, live: bool = False) -> TopstepXContract:
        """The single ACTIVE contract matching `text`, cached.

        Ambiguity is refused rather than resolved by picking one: 'MNQ' can match
        several expiries, and quietly choosing among them is how a bot ends up
        trading a contract nobody selected.
        """
        key = f"{text}|{live}"
        if key in self._contract_cache:
            return self._contract_cache[key]
        matches = [c for c in self.search_contracts(text, live) if c.active]
        if not matches:
            raise TopstepXError(f"no active contract matches {text!r}")
        if len(matches) > 1:
            names = ", ".join(f"{c.id} ({c.name})" for c in matches[:6])
            raise TopstepXError(
                f"{text!r} matched {len(matches)} active contracts: {names}. "
                f"Set TOPSTEPX_CONTRACT to the exact contract id.")
        self._contract_cache[key] = matches[0]
        return matches[0]

    def bars(self, contract_id: str, *, minutes_back: int = 1500, unit: str = "minute",
             unit_number: int = 1, limit: int = 2000, live: bool = False) -> list[dict]:
        """CLOSED bars only, oldest-first, normalised to the core's bar shape.

        includePartialBar is pinned False. The forming bar is the single most
        expensive measurement error this project has hit — a leg terminating on a
        bar that had not finished printing — and here it is simply declinable.
        """
        end = self._clock()
        start = end - timedelta(minutes=max(1, minutes_back))
        out = self._post("/api/History/retrieveBars", {
            "contractId": contract_id,
            "live": bool(live),
            "startTime": start.isoformat().replace("+00:00", "Z"),
            "endTime": end.isoformat().replace("+00:00", "Z"),
            "unit": BAR_UNIT[unit],
            "unitNumber": int(unit_number),
            "limit": int(limit),
            "includePartialBar": False,
        })
        rows = [{"timestamp": b["t"], "open": float(b["o"]), "high": float(b["h"]),
                 "low": float(b["l"]), "close": float(b["c"]),
                 "volume": int(b.get("v") or 0)}
                for b in (out.get("bars") or [])]
        rows.sort(key=lambda r: r["timestamp"])
        return rows

    def open_positions(self, account_id: int) -> list[dict]:
        out = self._post("/api/Position/searchOpen", {"accountId": int(account_id)})
        return [{"id": p.get("id"), "contract_id": p.get("contractId"),
                 "side": POSITION_TYPE.get(int(p.get("type") or 0), "undefined"),
                 "size": int(p.get("size") or 0),
                 "avg_price": float(p.get("averagePrice") or 0.0),
                 "opened_at": p.get("creationTimestamp")}
                for p in (out.get("positions") or [])]

    # ── writes ────────────────────────────────────────────────────────────────
    def place_bracket_market_order(self, *, account_id: int, contract: TopstepXContract,
                                   side: str, size: int, stop_points: float,
                                   target_points: float,
                                   custom_tag: Optional[str] = None) -> dict:
        """Market entry with attached stop and target, sized in ticks.

        The stop is submitted WITH the entry rather than after it. An entry that
        fills while a follow-up stop request is still in flight is an unprotected
        position, and on a prop account an unprotected position is how a trailing
        drawdown gets breached in one move.
        """
        if side not in ORDER_SIDE:
            raise TopstepXError(f"side must be 'buy' or 'sell', got {side!r}")
        if int(size) < 1:
            raise TopstepXError(f"size must be a positive whole number, got {size!r}")
        if stop_points <= 0 or target_points <= 0:
            raise TopstepXError(
                f"bracket distances must be positive (stop={stop_points}, "
                f"target={target_points}); an order without a stop is never placed")
        payload = {
            "accountId": int(account_id),
            "contractId": contract.id,
            "type": ORDER_TYPE["market"],
            "side": ORDER_SIDE[side],
            "size": int(size),
            "limitPrice": None, "stopPrice": None, "trailPrice": None,
            "customTag": custom_tag,
            "stopLossBracket": {"ticks": contract.points_to_ticks(stop_points),
                                "type": ORDER_TYPE["stop"]},
            "takeProfitBracket": {"ticks": contract.points_to_ticks(target_points),
                                  "type": ORDER_TYPE["limit"]},
        }
        try:
            out = self._post("/api/Order/place", payload)
        except TopstepXError as exc:
            raise TopstepXError(f"order rejected: {exc}") from exc
        return {"order_id": out.get("orderId"), "accepted": True,
                "submitted": payload, "raw": out}

    def cancel_order(self, account_id: int, order_id: int) -> dict:
        return self._post("/api/Order/cancel",
                          {"accountId": int(account_id), "orderId": int(order_id)})

    def close_position(self, account_id: int, contract_id: str) -> dict:
        return self._post("/api/Position/closeContract",
                          {"accountId": int(account_id), "contractId": contract_id})

    def ping(self) -> bool:
        try:
            self._session_token()
            return True
        except TopstepXError:
            return False
