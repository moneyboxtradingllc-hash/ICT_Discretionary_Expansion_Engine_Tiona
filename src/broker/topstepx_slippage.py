"""Quote-to-fill slippage measurement for the live MNQ execution path.

Slippage is the distance between the price that was EXECUTABLE when the request
left and the price that was actually filled. It is not profit, not loss, and not
the trade's excursion. So it is measured one way only:

    BUY   entry_slippage = fill_price - captured_best_ask
    SELL  entry_slippage = captured_best_bid - fill_price

Positive is adverse. Favorable fills stay NEGATIVE in the record — clamping
price improvement to zero would bias every future reserve upward and quietly
make the bot trade smaller than the evidence warrants.

WHAT THIS MODULE REFUSES TO DO. It never derives slippage from gross P&L, net
P&L, balance movement, stop distance, target distance, or entry-to-exit
movement. Those all confound execution quality with market direction, and that
confusion is exactly why the current reserve is provisional rather than
measured. Raw observations are stored before any summary is computed, so a
later reviewer can recompute from the source rather than trust an aggregate.

THE RESERVE DOES NOT MOVE ON ITS OWN. Reaching the minimum sample only makes a
recommendation available; changing production sizing remains a reviewed
doctrine change.
"""
from __future__ import annotations

import json
import os
import statistics
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ── measurement quality ───────────────────────────────────────────────────────
RELIABLE = "RELIABLE"
UNRELIABLE_STALE_QUOTE = "UNRELIABLE_STALE_QUOTE"
UNRELIABLE_MISSING_QUOTE = "UNRELIABLE_MISSING_QUOTE"
UNRELIABLE_QUOTE_AFTER_REQUEST = "UNRELIABLE_QUOTE_AFTER_REQUEST"
UNRELIABLE_CONTRACT_MISMATCH = "UNRELIABLE_CONTRACT_MISMATCH"
UNRELIABLE_UNLINKED_FILL = "UNRELIABLE_UNLINKED_FILL"
UNRELIABLE_DIRECTION_UNRESOLVED = "UNRELIABLE_DIRECTION_UNRESOLVED"
UNRELIABLE_UNKNOWN_ATTRIBUTION = "UNRELIABLE_UNKNOWN_ATTRIBUTION"

# exit kinds, kept separate because their execution characteristics differ
EXIT_TARGET = "TARGET"
EXIT_STOP = "STOP"
EXIT_EMERGENCY_FLATTEN = "EMERGENCY_FLATTEN"
EXIT_MANUAL_FLATTEN = "MANUAL_FLATTEN"
EXIT_OTHER = "OTHER"

MAX_QUOTE_AGE_SECONDS = 5.0

# Reserve may only be revisited once BOTH thresholds are met. Round trips and
# individual fills measure different things: a round trip proves the whole
# lifecycle, a fill proves one execution.
MIN_ROUND_TRIPS = 10
MIN_RELIABLE_OBSERVATIONS = 20


class SlippageError(RuntimeError):
    """A capture could not be formed at all."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts):
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class QuoteCapture:
    """The executable picture at the instant before the request left."""
    captured_at: datetime
    best_bid: float
    best_ask: float
    last_trade: float
    contract_id: str
    market_data_age_seconds: float
    volatility_state: str = ""

    def spread_ticks(self, tick_size: float) -> float:
        if tick_size <= 0 or self.best_ask is None or self.best_bid is None:
            return float("nan")
        return round((self.best_ask - self.best_bid) / tick_size, 3)

    def executable_reference(self, direction: str) -> float:
        """What the order could realistically have paid: ask to buy, bid to sell."""
        d = (direction or "").lower()
        if d in ("buy", "bullish", "long"):
            return self.best_ask
        if d in ("sell", "bearish", "short"):
            return self.best_bid
        raise SlippageError(f"unresolved direction {direction!r}")

    def evidence(self, tick_size: float = 0.25) -> dict:
        return {"captured_at": self.captured_at.isoformat(),
                "best_bid": self.best_bid, "best_ask": self.best_ask,
                "last_trade": self.last_trade, "contract_id": self.contract_id,
                "spread_ticks": self.spread_ticks(tick_size),
                "market_data_age_seconds": self.market_data_age_seconds,
                "volatility_state": self.volatility_state}


def capture_quote(*, market_hub_quote: dict, contract_id: str,
                  market_data_age_seconds: float, volatility_state: str = "",
                  now: datetime = None) -> QuoteCapture:
    """Snapshot the live GatewayQuote block. Missing sides are allowed through
    and flagged later — refusing to capture would lose the evidence entirely."""
    q = market_hub_quote or {}

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return QuoteCapture(captured_at=now or _now(),
                        best_bid=num(q.get("bestBid")), best_ask=num(q.get("bestAsk")),
                        last_trade=num(q.get("lastPrice")), contract_id=contract_id,
                        market_data_age_seconds=float(market_data_age_seconds),
                        volatility_state=volatility_state or "")


# ── the measurement ───────────────────────────────────────────────────────────
def classify_quality(capture: QuoteCapture, *, direction: str, contract_id: str,
                     request_at: datetime, fill_order_id=None,
                     expected_order_id=None, attribution: str = None) -> str:
    """Every reason a measurement cannot be trusted, checked before arithmetic."""
    if capture.contract_id != contract_id:
        return UNRELIABLE_CONTRACT_MISMATCH
    if (direction or "").lower() not in ("buy", "sell", "bullish", "bearish",
                                         "long", "short"):
        return UNRELIABLE_DIRECTION_UNRESOLVED
    ref_missing = (capture.best_ask is None
                   if (direction or "").lower() in ("buy", "bullish", "long")
                   else capture.best_bid is None)
    if ref_missing:
        return UNRELIABLE_MISSING_QUOTE
    if capture.market_data_age_seconds is None or \
            capture.market_data_age_seconds > MAX_QUOTE_AGE_SECONDS:
        return UNRELIABLE_STALE_QUOTE
    if request_at is not None and capture.captured_at > request_at:
        # A quote timestamped after the request cannot describe what was
        # executable when it left.
        return UNRELIABLE_QUOTE_AFTER_REQUEST
    if expected_order_id is not None and fill_order_id is not None \
            and str(fill_order_id) != str(expected_order_id):
        return UNRELIABLE_UNLINKED_FILL
    if attribution is not None and attribution != "EXPANSION_BOT":
        return UNRELIABLE_UNKNOWN_ATTRIBUTION
    return RELIABLE


def measure_entry(*, capture: QuoteCapture, direction: str, fill_price: float,
                  quantity: int, tick_size: float, tick_value: float,
                  contract_id: str, request_at: datetime, ack_at: datetime = None,
                  fill_at: datetime = None, fill_order_id=None,
                  expected_order_id=None, attribution: str = None,
                  candidate_id: str = "", snapshot_id: str = "",
                  account_fingerprint: str = "", trade_id=None) -> dict:
    """Entry slippage from the captured executable reference. Never from P&L."""
    quality = classify_quality(capture, direction=direction, contract_id=contract_id,
                               request_at=request_at, fill_order_id=fill_order_id,
                               expected_order_id=expected_order_id,
                               attribution=attribution)
    d = (direction or "").lower()
    is_buy = d in ("buy", "bullish", "long")
    try:
        reference = capture.executable_reference(direction)
    except SlippageError:
        reference = None

    if reference is None or fill_price is None:
        points = ticks = dollars = None
    else:
        # BUY: paid above the ask is adverse. SELL: sold below the bid is adverse.
        points = (float(fill_price) - reference) if is_buy else (reference - float(fill_price))
        points = round(points, 6)
        ticks = round(points / tick_size, 4) if tick_size else None
        dollars = round(ticks * tick_value, 4) if ticks is not None else None

    return {
        "kind": "ENTRY", "measured_at": _now().isoformat(),
        "candidate_id": candidate_id, "snapshot_id": snapshot_id,
        "account_fingerprint": account_fingerprint,
        "contract_id": contract_id, "direction": direction, "quantity": int(quantity or 0),
        "order_id": fill_order_id or expected_order_id, "trade_id": trade_id,
        "quote": capture.evidence(tick_size),
        "expected_price": reference, "actual_fill_price": fill_price,
        "slippage_points": points, "slippage_ticks": ticks,
        "slippage_dollars_per_contract": dollars,
        "slippage_dollars_total": (round(dollars * int(quantity or 0), 4)
                                   if dollars is not None else None),
        "request_at": request_at.isoformat() if request_at else None,
        "ack_at": ack_at.isoformat() if ack_at else None,
        "fill_at": fill_at.isoformat() if fill_at else None,
        "ack_latency_ms": _ms(request_at, ack_at),
        "fill_latency_ms": _ms(request_at, fill_at),
        "spread_ticks": capture.spread_ticks(tick_size),
        "volatility_state": capture.volatility_state,
        "quality": quality, "reliable": quality == RELIABLE,
        "favorable": (points is not None and points < 0),
        "derived_from_pnl": False,
    }


def measure_exit(*, capture: QuoteCapture, direction: str, exit_type: str,
                 requested_price: float, fill_price: float, quantity: int,
                 tick_size: float, tick_value: float, contract_id: str,
                 request_at: datetime = None, fill_at: datetime = None,
                 order_id=None, trade_id=None, attribution: str = None,
                 candidate_id: str = "", snapshot_id: str = "",
                 account_fingerprint: str = "") -> dict:
    """Exit slippage vs the REQUESTED protective price (or executable quote).

    The exit direction is the opposite of the position: a long exits by selling.
    Movement from entry to the stop or target is NOT slippage — only the gap
    between where the protective order was meant to execute and where it did.
    """
    d = (direction or "").lower()
    position_is_long = d in ("buy", "bullish", "long")
    exit_side = "sell" if position_is_long else "buy"
    quality = classify_quality(capture, direction=exit_side, contract_id=contract_id,
                               request_at=request_at or capture.captured_at,
                               attribution=attribution)

    reference = requested_price
    if reference is None:
        try:
            reference = capture.executable_reference(exit_side)
        except SlippageError:
            reference = None

    if reference is None or fill_price is None:
        points = ticks = dollars = None
    else:
        # Selling below the intended exit is adverse; buying above it is adverse.
        points = ((reference - float(fill_price)) if position_is_long
                  else (float(fill_price) - reference))
        points = round(points, 6)
        ticks = round(points / tick_size, 4) if tick_size else None
        dollars = round(ticks * tick_value, 4) if ticks is not None else None

    return {
        "kind": "EXIT", "exit_type": exit_type or EXIT_OTHER,
        "measured_at": _now().isoformat(),
        "candidate_id": candidate_id, "snapshot_id": snapshot_id,
        "account_fingerprint": account_fingerprint,
        "contract_id": contract_id, "direction": direction, "exit_side": exit_side,
        "quantity": int(quantity or 0), "order_id": order_id, "trade_id": trade_id,
        "quote": capture.evidence(tick_size),
        "requested_price": requested_price, "expected_price": reference,
        "actual_fill_price": fill_price,
        "slippage_points": points, "slippage_ticks": ticks,
        "slippage_dollars_per_contract": dollars,
        "slippage_dollars_total": (round(dollars * int(quantity or 0), 4)
                                   if dollars is not None else None),
        "request_at": request_at.isoformat() if request_at else None,
        "fill_at": fill_at.isoformat() if fill_at else None,
        "fill_latency_ms": _ms(request_at, fill_at),
        "spread_ticks": capture.spread_ticks(tick_size),
        "volatility_state": capture.volatility_state,
        "quality": quality, "reliable": quality == RELIABLE,
        "favorable": (points is not None and points < 0),
        "derived_from_pnl": False,
    }


def _ms(a, b):
    a, b = _parse(a), _parse(b)
    if a is None or b is None:
        return None
    return int((b - a).total_seconds() * 1000)


# ── partial fills ─────────────────────────────────────────────────────────────
def aggregate_fills(fills: list) -> dict:
    """Collapse the fill rows of ONE order into a quantity-weighted average.

    A 3-lot order that fills 1 + 2 is one execution, not two. Counting each row
    as its own observation would inflate the sample and let a single trade look
    like several round trips.
    """
    rows = [f for f in (fills or [])
            if f.get("price") is not None and int(f.get("size") or 0) > 0]
    if not rows:
        return {"quantity": 0, "vwap": None, "fill_count": 0, "raw_fills": list(fills or []),
                "aggregation_reliable": False}
    qty = sum(int(f["size"]) for f in rows)
    notional = sum(float(f["price"]) * int(f["size"]) for f in rows)
    order_ids = {str(f.get("orderId")) for f in rows if f.get("orderId") is not None}
    return {"quantity": qty, "vwap": round(notional / qty, 6),
            "fill_count": len(rows),
            "trade_ids": [f.get("id") for f in rows],
            "last_fill_at": max((str(f.get("creationTimestamp") or "") for f in rows),
                                default=None),
            "raw_fills": list(rows),
            # One order-level observation requires one order.
            "aggregation_reliable": len(order_ids) <= 1,
            "order_id": next(iter(order_ids), None)}


# ── active-position execution context ─────────────────────────────────────────
@dataclass
class ExecutionContext:
    """What the exit needs to know about the entry, carried across the position.

    Identity is threaded explicitly. It is never reconstructed from price
    similarity or timestamp proximity later — those guesses are exactly how a
    manual fill gets mislabelled as the bot's.
    """
    candidate_id: str
    candidate_fingerprint: str
    snapshot_id: str
    mission_id: str
    account_fingerprint: str
    contract_id: str
    direction: str
    quantity: int
    entry_order_id: object = None
    entry_trade_id: object = None
    entry_fill_price: float = None
    structural_stop_price: float = None
    liquidity_target_price: float = None
    # PROTECTION-STATE-AUTHORITY-1 — the two meanings `structural_stop_price`
    # used to carry at once. `original_thesis_invalidation` is frozen when the
    # post-fill structural protection is venue-proven and is never rewritten
    # afterwards; `active_protective_stop` is what is working at the venue now
    # and may only move toward less risk. `protection_baseline_armed` is the
    # gate: before it, the monotonic law does not exist, because the certified
    # re-anchor may legitimately widen the provisional bracket.
    original_thesis_invalidation: float = None
    active_protective_stop: float = None
    protection_baseline_armed: bool = False
    stop_order_id: object = None
    target_order_id: object = None
    entry_capture: dict = None
    path: str = ""

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "path"}

    def save(self) -> str:
        if not self.path:
            return ""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), prefix=".ctx-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.as_dict(), fh, indent=2, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        return self.path

    @classmethod
    def load(cls, path: str) -> "ExecutionContext | None":
        if not os.path.exists(path):
            return None
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        # `save()` writes `__dict__`, so new fields travel automatically -- but
        # THIS list is hand-maintained, and a field missing from it is written
        # to disk and then silently dropped on load. That is precisely how a
        # restart would forget an advanced protective stop and fall back to the
        # original invalidation, so protection fields belong here or nowhere.
        ctx = cls(**{k: d.get(k) for k in
                     ("candidate_id", "candidate_fingerprint", "snapshot_id",
                      "mission_id", "account_fingerprint", "contract_id",
                      "direction", "quantity", "entry_order_id", "entry_trade_id",
                      "entry_fill_price", "structural_stop_price",
                      "liquidity_target_price", "stop_order_id", "target_order_id",
                      "entry_capture", "original_thesis_invalidation",
                      "active_protective_stop", "protection_baseline_armed")})
        # A context written before this unit has no flag at all, and a missing
        # flag must never read as "armed".
        ctx.protection_baseline_armed = bool(ctx.protection_baseline_armed)
        ctx.path = path
        return ctx


def candidate_from_order_tag(tag: str) -> "str | None":
    """Map a venue order tag back to its parent lifecycle token.

    Mission F proved the venue derives protective legs by suffixing the entry
    tag: EXPBOT-<token>, EXPBOT-<token>-SL, EXPBOT-<token>-TP. The suffix is
    stripped so a protective fill resolves to the same parent as its entry.
    """
    t = str(tag or "").strip()
    if not t.startswith("EXPBOT-"):
        return None
    token = t[len("EXPBOT-"):]
    for suffix in ("-SL", "-TP"):
        if token.endswith(suffix):
            return token[: -len(suffix)]
    return token


# ── persistence + statistics ──────────────────────────────────────────────────
@dataclass
class SlippageLedger:
    """Append-only raw observations. Summaries are always recomputed."""

    path: str
    observations: list = field(default_factory=list)

    @classmethod
    def load(cls, path: str) -> "SlippageLedger":
        led = cls(path=path)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        led.observations.append(json.loads(line))
                    except Exception:  # noqa: BLE001 — one bad line is not a reason to lose the rest
                        continue
        return led

    def record(self, observation: dict) -> dict:
        """Append the RAW observation immediately, before any aggregation."""
        self.observations.append(observation)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(observation, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return observation

    # ── queries ───────────────────────────────────────────────────────────────
    def reliable(self, kind: str = None) -> list:
        return [o for o in self.observations
                if o.get("reliable") and (kind is None or o.get("kind") == kind)]

    def round_trips(self) -> int:
        """Complete round trips, paired ONLY by full lifecycle identity.

        Requires the same candidate_id, contract and direction on both a
        reliable entry and a reliable exit. Never paired by nearest timestamp,
        matching quantity, matching price, or mission date — each of those would
        happily pair two unrelated trades.
        """
        def keys(kind):
            out = set()
            for o in self.reliable(kind):
                cid = o.get("candidate_id")
                if not cid:
                    continue        # no identity -> cannot be part of a round trip
                out.add((str(cid), str(o.get("contract_id")), str(o.get("direction"))))
            return out
        return len(keys("ENTRY") & keys("EXIT"))

    def round_trip_details(self) -> list:
        def index(kind):
            d = {}
            for o in self.reliable(kind):
                cid = o.get("candidate_id")
                if cid:
                    d[(str(cid), str(o.get("contract_id")), str(o.get("direction")))] = o
            return d
        e, x = index("ENTRY"), index("EXIT")
        return [{"candidate_id": k[0], "contract_id": k[1], "direction": k[2],
                 "entry": e[k], "exit": x[k]} for k in sorted(e.keys() & x.keys())]

    def sample_status(self) -> dict:
        n_rel = len(self.reliable())
        rt = self.round_trips()
        return {"reliable_observations": n_rel,
                "required_observations": MIN_RELIABLE_OBSERVATIONS,
                "round_trips": rt, "required_round_trips": MIN_ROUND_TRIPS,
                "sufficient": n_rel >= MIN_RELIABLE_OBSERVATIONS and rt >= MIN_ROUND_TRIPS}

    def may_revisit_reserve(self) -> tuple:
        st = self.sample_status()
        if not st["sufficient"]:
            return False, (f"insufficient sample: {st['reliable_observations']}/"
                           f"{st['required_observations']} reliable observations, "
                           f"{st['round_trips']}/{st['required_round_trips']} round trips")
        return True, None

    def statistics(self) -> dict:
        """Full breakdown. Reporting only — it changes nothing by itself."""
        def stats(rows):
            vals = sorted(o["slippage_ticks"] for o in rows
                          if o.get("slippage_ticks") is not None)
            if not vals:
                return {"n": 0}
            def pct(p):
                if len(vals) == 1:
                    return vals[0]
                idx = min(int(round((p / 100.0) * (len(vals) - 1))), len(vals) - 1)
                return vals[idx]
            return {"n": len(vals), "mean": round(statistics.fmean(vals), 4),
                    "median": round(statistics.median(vals), 4),
                    "p90": pct(90), "p95": pct(95),
                    "worst": max(vals), "best": min(vals)}

        entries, exits = self.reliable("ENTRY"), self.reliable("EXIT")

        def group(rows, key):
            out = {}
            for o in rows:
                out.setdefault(str(o.get(key) or "unknown"), []).append(o)
            return {k: stats(v) for k, v in sorted(out.items())}

        def spread_bucket(o):
            s = o.get("spread_ticks")
            if s is None or s != s:
                return "unknown"
            return "<=1" if s <= 1 else ("<=2" if s <= 2 else ">2")

        by_spread = {}
        for o in entries + exits:
            by_spread.setdefault(spread_bucket(o), []).append(o)

        return {
            "sample": self.sample_status(),
            "entry": stats(entries), "exit": stats(exits),
            "entry_by_direction": group(entries, "direction"),
            "exit_by_type": group(exits, "exit_type"),
            "entry_by_volatility": group(entries, "volatility_state"),
            "exit_by_volatility": group(exits, "volatility_state"),
            "by_spread_bucket": {k: stats(v) for k, v in sorted(by_spread.items())},
            "unreliable_excluded": len([o for o in self.observations if not o.get("reliable")]),
            "note": ("statistics are reporting only; the production reserve changes "
                     "only through a reviewed doctrine change"),
        }
