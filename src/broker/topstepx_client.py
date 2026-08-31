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
    """A call reached the venue and the venue refused it.

    `venue_body` carries the venue's own response dict when there was one.
    PROD-20260810 lost a rejection because the only copy of `errorCode` and
    `errorMessage` was formatted into this exception's string and then dropped;
    the flight recorder reads the structured body from here instead.
    """

    def __init__(self, *args, venue_body: dict = None) -> None:
        super().__init__(*args)
        self.venue_body = dict(venue_body) if venue_body else None


class TopstepXAuthError(TopstepXError):
    """Credentials rejected, or the session could not be established."""


class TopstepXRateLimited(TopstepXError):
    """HTTP 429. Carries the venue's Retry-After when it supplied one."""

    def __init__(self, message: str, retry_after: "float | None" = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TopstepXPinError(TopstepXError):
    """Account pinning refused to resolve a single, tradable, visible account.

    Its own type because the operator response differs from an ordinary venue
    error: a pin failure means the configuration names the wrong account, and
    routing anywhere else would be worse than not trading.
    """


@dataclass(frozen=True)
class TopstepXAccount:
    id: int
    name: str
    balance: float
    can_trade: bool
    simulated: bool
    # TOPSTEPX-INTEGRATION — `isVisible` is part of the documented
    # /api/Account/search response (ProjectX Gateway API, Search for Account).
    # It defaults True when the key is absent so recorded fixtures and the
    # existing deterministic lane keep their behavior; the strict pinning path
    # (`pin_account`) requires the field to be present and true.
    is_visible: bool = True

    @classmethod
    def from_api(cls, d: dict) -> "TopstepXAccount":
        return cls(id=int(d["id"]), name=str(d.get("name") or ""),
                   balance=float(d.get("balance") or 0.0),
                   can_trade=bool(d.get("canTrade")),
                   simulated=bool(d.get("simulated")),
                   is_visible=bool(d.get("isVisible", True)))


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
        # Error bodies echo request context; redact before the text can reach a
        # log line or an exception chain an artifact might capture.
        from broker.topstepx_redaction import redact
        detail = redact(detail)
        if exc.code == 429:
            raw = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
            try:
                wait = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                wait = None      # Retry-After may be an HTTP-date; fall back to backoff
            raise TopstepXRateLimited(f"HTTP 429 from {url}: {detail}", wait) from exc
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
                 clock: Optional[Callable[[], datetime]] = None,
                 max_retries: int = 3, backoff_base: float = 0.5,
                 backoff_max: float = 8.0,
                 sleep: Optional[Callable[[float], None]] = None) -> None:
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
        # Bounded retry knobs. Injectable `sleep` keeps backoff tests instant —
        # a test that really slept would be a test nobody runs.
        self.max_retries = int(max_retries)
        self.backoff_base = float(backoff_base)
        self.backoff_max = float(backoff_max)
        self._sleep = sleep or time.sleep
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
            out = self._request_with_backoff(f"{self.base_url}{path}", payload, headers)
        except TopstepXError as exc:
            if _retry and "HTTP 401" in str(exc):
                self._token = None                    # expired early; re-auth once
                return self._post(path, payload, _retry=False)
            raise
        if not out.get("success", True):
            # The body travels WITH the exception. Formatting it into a string
            # and discarding the structure is exactly how PROD-20260810 lost
            # its rejection reason.
            raise TopstepXError(
                f"{path} failed: errorCode={out.get('errorCode')} "
                f"{out.get('errorMessage') or ''}".strip(), venue_body=out)
        return out

    def _request_with_backoff(self, url: str, payload: dict, headers: dict) -> dict:
        """One request, retried only for throttling — never for a refusal.

        HTTP 429 is the only status retried here. A 4xx that is not 429 is the
        venue saying no, and repeating a rejected call neither changes the
        answer nor is polite; a 5xx is retried once because it is usually
        transient. Attempts are hard-bounded (`max_retries`) so a throttled
        venue can never turn into an unbounded loop inside a trading session.

        Retry-After is honored when the venue supplies it; otherwise the wait
        doubles per attempt from `backoff_base`.
        """
        delay = self.backoff_base
        last: "TopstepXError | None" = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._transport(url, payload, headers, self.timeout)
            except TopstepXRateLimited as exc:
                last = exc
                if attempt >= self.max_retries:
                    break
                self._sleep(exc.retry_after if exc.retry_after is not None else delay)
                delay = min(delay * 2, self.backoff_max)
            except TopstepXError as exc:
                if "HTTP 5" in str(exc) and attempt < self.max_retries:
                    last = exc
                    self._sleep(delay)
                    delay = min(delay * 2, self.backoff_max)
                    continue
                raise
        raise TopstepXError(
            f"gave up after {self.max_retries + 1} attempts against {url}: {last}")

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

    def pin_account(self, *, account_id: "int | None" = None,
                    account_name: str = "",
                    expected_fingerprint: str = "") -> TopstepXAccount:
        """Resolve THE one configured account, or fail closed. Never guesses.

        ACCOUNT-PINNING LAW (TOPSTEPX-INTEGRATION, 2026-08-04). A prop trader
        holds several linked accounts — an evaluation, a funded one, a reset,
        a practice account. Every one of them authenticates with the same key,
        so the venue will happily route an order to the wrong one. The list
        order is not a preference and must never be read as one.

        Refuses, rather than choosing, when:
          - neither an id nor an exact name is configured
          - zero accounts match
          - more than one account matches
          - the matched account has canTrade false
          - the matched account has isVisible false
          - `expected_fingerprint` is supplied and the resolved identity
            differs from it (the configured account CHANGED between runs)

        `account_id` wins when both are given: an integer id cannot be made
        ambiguous by a rename.
        """
        from broker.topstepx_redaction import account_fingerprint, redacted_account_label

        wanted_id = None if account_id in (None, "") else int(account_id)
        wanted_name = (account_name or "").strip()
        if wanted_id is None and not wanted_name:
            raise TopstepXPinError(
                "no account pinned: set TOPSTEPX_ACCOUNT_ID (preferred) or "
                "TOPSTEPX_ACCOUNT_NAME. The adapter will not choose an account "
                "for you — an unpinned adapter could route to any linked account."
            )

        active = self.accounts(only_active=True)
        if wanted_id is not None:
            matches = [a for a in active if a.id == wanted_id]
            # The configured account NUMBER never enters an error string. A pin
            # failure is the one moment this message is guaranteed to be copied
            # into a terminal, a screenshot or a bug report, and the account
            # number is exactly what must not travel with it. The operator knows
            # what they configured; naming the variable is enough to act on.
            criterion = "the configured TOPSTEPX_ACCOUNT_ID"
        else:
            matches = [a for a in active if a.name.strip() == wanted_name]
            criterion = f"the configured TOPSTEPX_ACCOUNT_NAME ({redacted_account_label(wanted_name)})"

        if not matches:
            raise TopstepXPinError(
                f"{criterion} is not among the {len(active)} active account(s) "
                f"this key can see. Refusing to fall back to any other account. "
                f"(The available accounts are deliberately not listed here.)"
            )
        if len(matches) > 1:
            raise TopstepXPinError(
                f"{criterion} matched {len(matches)} accounts. "
                f"Ambiguity is not resolved by ordering — pin TOPSTEPX_ACCOUNT_ID "
                f"instead."
            )

        acct = matches[0]
        if not acct.can_trade:
            raise TopstepXPinError(
                f"pinned account {redacted_account_label(acct.name)} reports "
                f"canTrade=false. Topstep has disabled trading on it."
            )
        if not acct.is_visible:
            raise TopstepXPinError(
                f"pinned account {redacted_account_label(acct.name)} reports "
                f"isVisible=false. A hidden account is not a routing target."
            )

        actual = account_fingerprint(acct.id, acct.name)
        if expected_fingerprint and actual != expected_fingerprint:
            raise TopstepXPinError(
                "pinned account IDENTITY CHANGED since the recorded run "
                f"(expected {expected_fingerprint}, resolved {actual}). Refusing "
                f"to continue against a different account."
            )
        return acct

    def search_contracts(self, text: str, live: bool = False) -> list[TopstepXContract]:
        out = self._post("/api/Contract/search", {"searchText": text, "live": bool(live)})
        return [TopstepXContract.from_api(c) for c in (out.get("contracts") or [])]

    def available_contracts(self, live: bool = False) -> list[TopstepXContract]:
        """POST /api/Contract/available — the documented catalogue call.

        Kept beside `search_contracts` because the two answer different
        questions: search filters by text, available enumerates. Preflight uses
        search (MNQ is a text lookup); this exists so contract resolution can be
        cross-checked without a search term.
        """
        out = self._post("/api/Contract/available", {"live": bool(live)})
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
        # Round the window down to the last COMPLETED interval. Asking for
        # bars up to 14:13:04.421975Z while includePartialBar=false requests a
        # closed view of a minute that has not closed — an ambiguity the server
        # should not have to resolve, and one that makes every request unique
        # so nothing upstream can cache it. (Found 2026-08-05 during the
        # retrieveBars debug; it is NOT the cause of that hang, which reproduces
        # with a rounded window through four independent clients, but a request
        # that straddles a developing bar is wrong on its own terms.)
        end = self._clock().replace(second=0, microsecond=0)
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

    def open_orders(self, account_id: int, contract_id: Optional[str] = None) -> list[dict]:
        """Working orders. After a bracket entry fills, the stop and target are
        the two that remain — which is how the lane proves a position is
        protected rather than assuming the bracket attached."""
        out = self._post("/api/Order/searchOpen", {"accountId": int(account_id)})
        rows = []
        for o in (out.get("orders") or []):
            if contract_id and o.get("contractId") != contract_id:
                continue
            rows.append({"id": o.get("id"), "contract_id": o.get("contractId"),
                         "status": int(o.get("status") or 0),
                         "type": int(o.get("type") or 0),
                         "side": int(o.get("side") or 0),
                         "size": int(o.get("size") or 0),
                         "limit_price": o.get("limitPrice"),
                         "stop_price": o.get("stopPrice"),
                         "parent_order_id": o.get("parentOrderId")})
        return rows

    #: The venue's own order lifecycle, per the official Gateway contract.
    #: Pinned here because the safety layer's behaviour is defined in terms of
    #: these exact values, and a silent drift would re-interpret every
    #: terminality decision without failing a single test.
    ORDER_STATUS = {0: "None", 1: "Open", 2: "Filled", 3: "Cancelled",
                    4: "Expired", 5: "Rejected", 6: "Pending",
                    7: "PendingCancellation", 8: "Suspended"}

    #: PROVEN NON-EXECUTABLE. Note that a terminal ORDER does not imply an
    #: unchanged POSITION -- `Filled`, and `Cancelled` with a non-zero
    #: fillVolume, both mean exposure may have moved.
    TERMINAL_ORDER_STATUSES = frozenset({2, 3, 4, 5})

    #: STILL CAPABLE OF CHANGING EXPOSURE, or unresolved.
    #: `PendingCancellation` is NOT cancelled. `Suspended` is NOT harmless --
    #: it is a bracket child staged at the venue, and it is precisely the class
    #: `searchOpen` omits.
    ACTIVE_ORDER_STATUSES = frozenset({1, 6, 7, 8})

    #: `/api/Order/v2/query` paging. The venue caps a response at 100 rows and
    #: reports the true size in `totalCount`; asking for more per round trip
    #: reduces the number of windows in which the book can change underneath a
    #: discovery that is supposed to be a single coherent view.
    QUERY_PAGE_SIZE = 500
    #: A bound, not a budget. Exhausting it means the venue is not converging
    #: and completeness cannot be claimed.
    QUERY_MAX_PAGES = 50

    def order_by_id(self, account_id: int, order_id: int) -> "dict | None":
        """POST /api/Order/searchById -- the EXACT lifecycle of ONE order.

        THE TERMINALITY ORACLE. `searchOpen` answers "is it working right now",
        which cannot distinguish cancelled from filled from not-yet-visible; a
        negative observation there is not evidence of anything. This asks the
        venue about one known order and gets its status back.

        Returns None when the venue reports no such order -- which is itself
        UNKNOWN, never terminality.
        """
        out = self._post("/api/Order/searchById",
                         {"accountId": int(account_id), "orderId": int(order_id)})
        o = out.get("order") or (out.get("orders") or [None])[0]
        if not o:
            return None
        return {"id": o.get("id"), "contract_id": o.get("contractId"),
                "status": int(o.get("status") or 0),
                "status_name": self.ORDER_STATUS.get(int(o.get("status") or 0),
                                                     "UNRECOGNISED"),
                "type": int(o.get("type") or 0), "side": int(o.get("side") or 0),
                "size": int(o.get("size") or 0),
                "fill_volume": o.get("fillVolume"),
                "filled_price": o.get("filledPrice"),
                "limit_price": o.get("limitPrice"),
                "stop_price": o.get("stopPrice"),
                "custom_tag": o.get("customTag"),
                "parent_order_id": o.get("parentOrderId"),
                "linked_order_id": o.get("linkedOrderId"),
                "raw": o}

    def query_orders(self, account_id: int, *, statuses=None,
                     contract_id: Optional[str] = None) -> list[dict]:
        """POST /api/Order/v2/query -- DISCOVERY across order statuses.

        WHY THIS EXISTS AND `searchOpen` DOES NOT SUFFICE. The official Gateway
        documentation states that `searchOpen` does NOT include Suspended
        bracket children. Every discovery path in the safety stack read
        `searchOpen` and concluded "no owned protective order" from its silence
        -- a partial view consumed as complete truth.

        A caller cannot ask `searchById` about an order whose id it never
        learned, so discovery has to come first and identity second.

        THE WIRE CONTRACT, MEASURED AGAINST THE LIVE VENUE (2026-08-27).
        This method previously posted the filter fields at the ROOT:

            {"accountId": N, "contractId": "..."}          -> HTTP 400
            "SearchOrdersQueryRequest was missing required properties
             including: 'filter'"

        So canonical discovery had NEVER succeeded against the real Gateway.
        Every live call raised, fell back to `searchOpen`, and was labelled
        INCOMPLETE -- which meant the Suspended-child repair was inert in
        production, and after the completeness law landed, emergency
        convergence would have refused to act at all. No fixture could catch
        it: every fixture implements `query_orders` and returns rows. The
        contract was wrong at the wire, not in the logic.

        The accepted body:

            {"filter": {"accountId": N, ...}, "pageSize": K, "pageOffset": R}

        `pageOffset` IS A ROW OFFSET, NOT A PAGE INDEX. Measured: with
        pageSize=5, pageOffset=1 returns rows[1:6], not rows[5:10]. Advancing
        it by one per "page" would re-read almost the same window forever while
        looking like progress.

        PAGINATION IS MANDATORY, NOT AN OPTIMISATION. The venue caps a response
        at 100 rows and reports the real size in `totalCount` -- the live
        Combine returned 100 of 193. A first-page read is a PARTIAL view, and
        this method exists precisely so partial views stop being consumed as
        complete truth. It therefore raises rather than returning a short list:
        a caller that cannot see every order must fall back to INCOMPLETE, not
        receive a confident-looking prefix.

        SERVER-SIDE `contractId` DOES NOT FILTER. Measured: `totalCount` is
        identical with and without it. The client-side filter below is the one
        that actually scopes the result, and it stays.
        """
        flt = {"accountId": int(account_id)}
        if statuses:
            flt["statuses"] = [int(x) for x in statuses]
        if contract_id:
            flt["contractId"] = contract_id

        raw, offset, total, guard = [], 0, None, 0
        while True:
            guard += 1
            if guard > self.QUERY_MAX_PAGES:
                raise TopstepXError(
                    f"/api/Order/v2/query did not terminate within "
                    f"{self.QUERY_MAX_PAGES} pages (offset {offset}, "
                    f"totalCount {total}); discovery cannot be proven complete")
            out = self._post("/api/Order/v2/query",
                             {"filter": flt, "pageSize": self.QUERY_PAGE_SIZE,
                              "pageOffset": offset})
            if out.get("success") is False:
                raise TopstepXError(
                    f"/api/Order/v2/query refused: errorCode="
                    f"{out.get('errorCode')} {out.get('errorMessage')!r}")
            page = out.get("orders") or out.get("items") or []
            if total is None:
                total = out.get("totalCount")
            raw.extend(page)
            if not page:
                break
            offset += len(page)
            if total is not None and offset >= int(total):
                break
            if total is None and len(page) < self.QUERY_PAGE_SIZE:
                # ONLY WHEN THE VENUE WITHHELD `totalCount`. A short page is
                # NOT proof of the last page: the server may cap below the size
                # we asked for -- measured at 100 rows by default -- so
                # "len(page) < requested" would stop at row 100 of 193 and call
                # it the whole book. Exactly the partial-view error this method
                # exists to prevent, reintroduced one layer down.
                break
        if total is not None and len(raw) < int(total):
            # POSITIVE PROOF OR NOTHING. A short read is exactly the partial
            # view this endpoint exists to replace.
            raise TopstepXError(
                f"/api/Order/v2/query returned {len(raw)} of {total} orders; "
                f"discovery cannot be proven complete")

        rows = []
        for o in raw:
            if contract_id and o.get("contractId") != contract_id:
                continue
            status = int(o.get("status") or 0)
            rows.append({"id": o.get("id"), "contract_id": o.get("contractId"),
                         "status": status,
                         "status_name": self.ORDER_STATUS.get(status, "UNRECOGNISED"),
                         "type": int(o.get("type") or 0),
                         "side": int(o.get("side") or 0),
                         "size": int(o.get("size") or 0),
                         "fill_volume": o.get("fillVolume"),
                         "limit_price": o.get("limitPrice"),
                         "stop_price": o.get("stopPrice"),
                         "custom_tag": o.get("customTag"),
                         "parent_order_id": o.get("parentOrderId"),
                         "linked_order_id": o.get("linkedOrderId")})
        return rows

    def order_history(self, account_id: int, start_iso: str,
                      end_iso: str) -> list[dict]:
        """Every order the venue recorded in a window, ours or not.

        Read-only. This is how bot activity is separated from manual activity
        after the fact: the bot tags what it submits, so an untagged order in
        our window came from somewhere else.
        """
        out = self._post("/api/Order/search",
                         {"accountId": int(account_id),
                          "startTimestamp": start_iso, "endTimestamp": end_iso})
        return [{"id": o.get("id"), "contract_id": o.get("contractId"),
                 "created": o.get("creationTimestamp"),
                 "updated": o.get("updateTimestamp"),
                 "status": int(o.get("status") or 0),
                 "type": int(o.get("type") or 0),
                 "side": int(o.get("side") or 0),
                 "size": int(o.get("size") or 0),
                 "fill_volume": o.get("fillVolume"),
                 "filled_price": o.get("filledPrice"),
                 "custom_tag": o.get("customTag")}
                for o in (out.get("orders") or [])]

    def trade_history(self, account_id: int, start_iso: str,
                      end_iso: str) -> list[dict]:
        """Executed trades in a window, with realised P&L and fees."""
        out = self._post("/api/Trade/search",
                         {"accountId": int(account_id),
                          "startTimestamp": start_iso, "endTimestamp": end_iso})
        return [{"id": t.get("id"), "order_id": t.get("orderId"),
                 "contract_id": t.get("contractId"),
                 "created": t.get("creationTimestamp"),
                 "price": t.get("price"), "size": int(t.get("size") or 0),
                 "side": int(t.get("side") or 0),
                 "voided": bool(t.get("voided")),
                 "pnl": t.get("profitAndLoss"), "fees": t.get("fees")}
                for t in (out.get("trades") or [])]

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
        # SMOKE-SIGN-REPAIR (2026-08-10). This harness sent UNSIGNED ticks and
        # Topstep refused it: errorCode 2, "Invalid stop loss ticks (40). Ticks
        # should be less than zero when longing." The production geometry had
        # always signed them correctly, so the two paths disagreed about the
        # venue's contract. Rather than write the convention out a second time
        # here, both now read the same helper. Imported inside the function
        # because `topstepx_combine_risk` imports this module at load time.
        from broker.topstepx_combine_risk import (sign_stop_ticks,
                                                  sign_target_ticks)
        direction = "bullish" if side == "buy" else "bearish"
        payload = {
            "accountId": int(account_id),
            "contractId": contract.id,
            "type": ORDER_TYPE["market"],
            "side": ORDER_SIDE[side],
            "size": int(size),
            "limitPrice": None, "stopPrice": None, "trailPrice": None,
            "customTag": custom_tag,
            "stopLossBracket": {
                "ticks": sign_stop_ticks(direction,
                                         contract.points_to_ticks(stop_points)),
                "type": ORDER_TYPE["stop"]},
            "takeProfitBracket": {
                "ticks": sign_target_ticks(direction,
                                           contract.points_to_ticks(target_points)),
                "type": ORDER_TYPE["limit"]},
        }
        try:
            out = self._post("/api/Order/place", payload)
        except TopstepXError as exc:
            raise TopstepXError(f"order rejected: {exc}",
                                venue_body=getattr(exc, "venue_body", None)) from exc
        return {"order_id": out.get("orderId"), "accepted": True,
                "submitted": payload, "raw": out}

    def place_order_raw(self, payload: dict) -> dict:
        """POST /api/Order/place with a body the caller already built.

        The bracket geometry is constructed and validated by
        `topstepx_combine_risk.BracketGeometry.as_order_payload`, immediately
        before submission, on the current price. This method exists so that the
        EXACT validated body is what reaches the venue — rebuilding it here
        would reintroduce the gap between what was checked and what was sent.
        """
        out = self._post("/api/Order/place", payload)
        return {"order_id": out.get("orderId"), "accepted": True, "raw": out}

    def cancel_order(self, account_id: int, order_id: int) -> dict:
        return self._post("/api/Order/cancel",
                          {"accountId": int(account_id), "orderId": int(order_id)})

    def modify_order(self, account_id: int, order_id: int, *,
                     size: Optional[int] = None, limit_price=None,
                     stop_price=None, trail_price=None) -> dict:
        """POST /api/Order/modify — official schema verified 2026-08-04.

        All price fields are optional and nullable; omitted values are sent as
        null, which is what the documented example does. Used by the smoke only
        to move a protective stop, never to widen it — the caller owns that
        rule, because a client that silently permits a wider stop is a client
        that permits a bigger loss than the risk model approved.
        """
        return self._post("/api/Order/modify", {
            "accountId": int(account_id), "orderId": int(order_id),
            "size": None if size is None else int(size),
            "limitPrice": limit_price, "stopPrice": stop_price,
            "trailPrice": trail_price,
        })

    def close_position(self, account_id: int, contract_id: str) -> dict:
        return self._post("/api/Position/closeContract",
                          {"accountId": int(account_id), "contractId": contract_id})

    def close_position_partial(self, account_id: int, contract_id: str, size: int) -> dict:
        """POST /api/Position/closeContractPartial — official path verified 2026-08-04.

        NOTE the endpoint name. The mission brief listed this as
        `/api/Position/partialCloseContract`, which does not exist; the official
        documentation names it `closeContractPartial`. Guessed endpoint names
        are exactly the class of error that only shows up live, mid-position.
        """
        if int(size) < 1:
            raise TopstepXError(f"partial close size must be >= 1, got {size!r}")
        return self._post("/api/Position/closeContractPartial",
                          {"accountId": int(account_id), "contractId": contract_id,
                           "size": int(size)})

    def ping(self) -> bool:
        try:
            self._session_token()
            return True
        except TopstepXError:
            return False
