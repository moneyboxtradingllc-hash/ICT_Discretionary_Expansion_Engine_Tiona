"""Origin attribution — manual operator vs Expansion Bot vs unknown.

Maurice traded this Combine manually on 2026-08-05 (+$33.90 realized, 5 MNQ
short, no customTag) while the bot was collecting candles. That result belongs
to him, not to the bot, and nothing in the system may quietly absorb it as
automated performance.

ATTRIBUTION RULE. The bot stamps every order it sends with a `customTag`
carrying its authorization token id. So:

    tag matches a token this session issued -> EXPANSION_BOT
    no tag at all                           -> MANUAL_OPERATOR
    tag present but unrecognized            -> UNKNOWN_EXTERNAL

The default is deliberately NOT "bot". An order that cannot be positively
attributed to the bot is never counted as one, because the direction of that
error matters: mistaking a manual trade for a bot trade would let the bot
believe it had already spent its one-trade allowance, or credit it with a
result it did not earn.

UNKNOWN_EXTERNAL is the dangerous class — something is trading this account and
the bot cannot say what. It pauses rather than adding exposure alongside it.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

MANUAL_OPERATOR = "MANUAL_OPERATOR"
EXPANSION_BOT = "EXPANSION_BOT"
UNKNOWN_EXTERNAL = "UNKNOWN_EXTERNAL"

BOT_TAG_PREFIX = "EXPBOT-"
# Suffixes the VENUE appends when it derives a protective leg from the entry
# order. Kept in step with topstepx_slippage.candidate_from_order_tag.
PROTECTIVE_TAG_SUFFIXES = ("-SL", "-TP")


def bot_tag(token_id: str) -> str:
    """The customTag the bot stamps on its orders. Carries no secret."""
    return f"{BOT_TAG_PREFIX}{token_id}"


def classify(row: dict, known_token_ids: "set | None" = None,
             order_index: "dict | None" = None) -> str:
    """Attribute one order/trade/position row to an origin.

    TRADE RECORDS CARRY NO customTag on this venue — measured 2026-08-05:
    order 3367891717 was submitted with tag 'EXPBOT-execsmoke-171100' and the
    resulting trade 2953374559 reported customTag=None. Reading the tag off the
    trade therefore attributed the bot's OWN fill to the operator.

    The tag survives on the ORDER, and every trade carries `orderId`, so
    attribution joins Trade.orderId -> Order.id and reads the tag there.
    `order_index` maps order id -> order row.
    """
    known = known_token_ids or set()
    row = row or {}
    tag = row.get("customTag") or row.get("custom_tag") or ""
    tag = str(tag).strip()
    if not tag and row.get("orderId") is not None and order_index:
        parent = order_index.get(row["orderId"]) or order_index.get(str(row["orderId"]))
        if parent:
            tag = str(parent.get("customTag") or "").strip()
    if not tag:
        return MANUAL_OPERATOR
    if tag.startswith(BOT_TAG_PREFIX):
        token_id = tag[len(BOT_TAG_PREFIX):]
        if token_id in known:
            return EXPANSION_BOT
        # Mission F proved the venue DERIVES the protective legs by suffixing
        # the entry tag: EXPBOT-<token>-SL / -TP. Those orders are the bot's own
        # bracket. Without stripping the suffix they read as UNKNOWN_EXTERNAL —
        # which both marks every stop/target exit unreliable (so no round trip
        # could ever accumulate) and trips the pause law on the bot's own stop.
        for suffix in PROTECTIVE_TAG_SUFFIXES:
            if token_id.endswith(suffix) and token_id[: -len(suffix)] in known:
                return EXPANSION_BOT
        return UNKNOWN_EXTERNAL
    return UNKNOWN_EXTERNAL


@dataclass
class SessionLedger:
    """Persistent per-session record of who did what on this account."""

    account_fingerprint: str
    session_date: str
    path: str
    known_token_ids: set = field(default_factory=set)
    entries: list = field(default_factory=list)

    # ── recording ─────────────────────────────────────────────────────────────
    def record_token(self, token_id: str) -> None:
        self.known_token_ids.add(token_id)

    def record(self, kind: str, row: dict, *, note: str = "",
               order_index: "dict | None" = None) -> dict:
        origin = classify(row, self.known_token_ids, order_index)
        entry = {"kind": kind, "origin": origin,
                 "at": datetime.now(timezone.utc).isoformat(),
                 "contract_id": row.get("contractId") or row.get("contract_id"),
                 "size": row.get("size"), "side": row.get("side"),
                 "price": row.get("price"), "pnl": row.get("profitAndLoss"),
                 "fees": row.get("fees"),
                 # `commissions` is billed SEPARATELY from `fees`. Omitting it
                 # left an unexplained gap between computed net and the balance
                 # ($2.50 manual, $0.50 bot). gross - fees - commissions
                 # reconciles to the cent.
                 "commissions": row.get("commissions"),
                 "order_id": row.get("orderId"), "venue_id": row.get("id"),
                 "note": note}
        self.entries.append(entry)
        return entry

    def reconcile_trades(self, trades: list, orders: list = None) -> dict:
        """Attribute trades, joining to their parent orders for the tag."""
        index = {}
        for o in orders or []:
            if o.get("id") is not None:
                index[o["id"]] = o
                index[str(o["id"])] = o
        for t in trades or []:
            self.record("trade", t, order_index=index)
        return self.summary()

    # ── queries ───────────────────────────────────────────────────────────────
    def bot_filled_trade_count(self) -> int:
        return sum(1 for e in self.entries
                   if e["kind"] == "trade" and e["origin"] == EXPANSION_BOT)

    def manual_trade_count(self) -> int:
        return sum(1 for e in self.entries
                   if e["kind"] == "trade" and e["origin"] == MANUAL_OPERATOR)

    def unknown_count(self) -> int:
        return sum(1 for e in self.entries if e["origin"] == UNKNOWN_EXTERNAL)

    def realized_by_origin(self) -> dict:
        out = {}
        for e in self.entries:
            if e["kind"] != "trade":
                continue
            pnl = (float(e.get("pnl") or 0) - float(e.get("fees") or 0)
                   - float(e.get("commissions") or 0))
            out[e["origin"]] = round(out.get(e["origin"], 0.0) + pnl, 2)
        return out

    def requires_pause(self) -> "str | None":
        """Unknown activity means stop and reconcile before adding exposure."""
        if self.unknown_count():
            return (f"{self.unknown_count()} order/trade row(s) could not be attributed. "
                    f"Refusing to add exposure alongside unidentified activity.")
        return None

    def summary(self) -> dict:
        return {"account_fingerprint": self.account_fingerprint,
                "session_date": self.session_date,
                "bot_filled_trade_count": self.bot_filled_trade_count(),
                "manual_trade_count": self.manual_trade_count(),
                "unknown_count": self.unknown_count(),
                "realized_by_origin": self.realized_by_origin(),
                "requires_pause": self.requires_pause(),
                # Persisted so a RESTART can still recognise the bot's own work.
                # Without this the token set resets to empty, every order still
                # carries the bot tag prefix, and `classify` downgrades our own
                # fills to UNKNOWN_EXTERNAL — which reads as an intruder on the
                # account and trips the pause law during recovery.
                "known_token_ids": sorted(self.known_token_ids),
                "entries": list(self.entries)}

    # ── persistence ───────────────────────────────────────────────────────────
    def save(self) -> str:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.summary(), fh, indent=2, default=str)
        return self.path

    @classmethod
    def load_or_new(cls, account_fingerprint: str, session_date: str,
                    store_dir: str) -> "SessionLedger":
        path = os.path.join(store_dir, f"session_{session_date}.json")
        led = cls(account_fingerprint, session_date, path)
        if os.path.exists(path):
            try:
                data = json.load(open(path, encoding="utf-8"))
                led.entries = data.get("entries") or []
                led.known_token_ids = set(data.get("known_token_ids") or [])
            except Exception:  # noqa: BLE001 — a damaged ledger must not block startup
                led.entries = []
                led.known_token_ids = set()
        return led


def account_state_digest(*, balance: float, positions: int, orders: int,
                         realized: float) -> str:
    """A short digest of everything a candidate assumed about the account.

    Bound into the candidate so that a manual fill, a new working order or a
    balance change between approval and submit is detected as drift rather than
    discovered afterwards.
    """
    import hashlib
    raw = f"{round(float(balance), 2)}|{int(positions)}|{int(orders)}|{round(float(realized), 2)}"
    return "acctstate:" + hashlib.sha256(raw.encode()).hexdigest()[:16]
