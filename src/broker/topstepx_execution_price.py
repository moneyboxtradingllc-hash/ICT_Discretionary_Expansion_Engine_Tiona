"""Fresh executable price for candidate economics. EXEC-PRICE-FRESHNESS-1.

2026-08-20. `brain_input._current_price()` published the newest SETTLED candle
close as `market.current_price`, and `luna_candidate_producer._reference_price()`
made that number the candidate's ENTRY PRICE -- the value every stop distance,
reward ratio and side-check is measured from.

At 11:02:10 ET Luna held a bearish thesis with bearish tools eligible and the
29240.25 sell-side objective authorized, and was handed 29404.25. The
contemporaneous 1m candle was:

    open 29440.75   high 29457.25   low 29423.25   close 29429.50

The market did not trade 29404.25 anywhere in that minute. Against the 29470.25
protected high the stale field produced a 66.00-point stop -- a ceiling veto --
while every price actually traded in that candle implied 13.00 to 47.00.

    A SETTLED CLOSE IS MARKET TRUTH.
    IT IS NOT AN EXECUTABLE PRICE.

They are different questions and no longer share one field. Settled evidence
keeps answering "what has the market done"; anything answering "what does this
trade cost me right now" reads the live quote through here.

NOTHING NEW IS MEASURED. `LiveQuoteProvider` already streams GatewayQuote into
memory and `topstepx_slippage` already owns the freshness standard the submit
boundary trusts. This module carries that same authority to a second consumer --
it does not open a second market-data connection and does not invent a
threshold.

Freshness is REPORTED and then ENFORCED. A stale or absent quote never falls
back to the settled close, because that fallback IS the defect.
"""
from __future__ import annotations

from broker.topstepx_slippage import (MAX_QUOTE_AGE_SECONDS,
                                      UNRELIABLE_STALE_QUOTE, QuoteCapture)

SCHEMA = "execution_price.v1"
SOURCE = "topstepx_realtime_quote"

#: Why no executable price is available. Each is a distinct operational fact,
#: because "the lane has no quote stream" and "the stream went quiet" need
#: different answers from whoever reads the evidence.
NO_QUOTE_PROVIDER = "NO_QUOTE_PROVIDER"
NO_QUOTE_RECEIVED = "NO_QUOTE_RECEIVED"
#: The provider existed and raised. Distinct from having no provider at all --
#: a lane wired for live quotes whose stream is broken is not the same fact as
#: a replay lane that never had one, and the evidence must not blur them.
QUOTE_PROVIDER_FAILED = "QUOTE_PROVIDER_FAILED"
STALE_QUOTE = UNRELIABLE_STALE_QUOTE
SIDE_NOT_QUOTED = "SIDE_NOT_QUOTED"

#: The refusal a caller gets for trying to price exposure off settled evidence.
SETTLED_CLOSE_REFUSED = "SETTLED_CLOSE_IS_NOT_AN_EXECUTABLE_PRICE"

_BULLISH = ("buy", "bullish", "long")
_BEARISH = ("sell", "bearish", "short")


def unavailable(reason: str) -> dict:
    """A block that states, positively, that there is no executable price."""
    return {"schema": SCHEMA, "available": False, "fresh": False,
            "source": None, "unavailable_reason": reason,
            "best_bid": None, "best_ask": None, "last_trade": None,
            "captured_at": None, "age_seconds": None,
            "max_age_seconds": MAX_QUOTE_AGE_SECONDS}


def from_capture(capture: QuoteCapture, *,
                 max_age_seconds: float = MAX_QUOTE_AGE_SECONDS) -> dict:
    """Turn a `QuoteCapture` into the payload block. Never raises.

    A stale capture is still published in full -- age, both sides, timestamp --
    and merely marked `fresh: False`. Evidence is never discarded for being
    inconvenient; it is labelled so the refusal downstream can name a number.
    """
    if capture is None:
        return unavailable(NO_QUOTE_PROVIDER)

    age = getattr(capture, "market_data_age_seconds", None)
    bid = getattr(capture, "best_bid", None)
    ask = getattr(capture, "best_ask", None)
    last = getattr(capture, "last_trade", None)

    if bid is None and ask is None:
        block = unavailable(NO_QUOTE_RECEIVED)
        block["age_seconds"] = age
        block["last_trade"] = last
        return block

    try:
        age_f = float(age)
    except (TypeError, ValueError):
        age_f = None
    fresh = age_f is not None and age_f <= float(max_age_seconds)

    captured_at = getattr(capture, "captured_at", None)
    return {
        "schema": SCHEMA,
        "available": True,
        "fresh": fresh,
        "source": SOURCE,
        "unavailable_reason": None if fresh else STALE_QUOTE,
        "best_bid": bid,
        "best_ask": ask,
        "last_trade": last,
        "captured_at": captured_at.isoformat() if captured_at is not None else None,
        "age_seconds": age_f,
        "max_age_seconds": float(max_age_seconds),
        # Stated per side so the payload never requires the reader to know
        # which side a direction executes against.
        "bullish_executable": ask,
        "bearish_executable": bid,
    }


def refusal(block: dict, direction: str) -> "str | None":
    """Why this block cannot price `direction`, or None if it can."""
    b = block or {}
    if not b.get("available"):
        return b.get("unavailable_reason") or NO_QUOTE_PROVIDER
    if not b.get("fresh"):
        return STALE_QUOTE
    return None if _side(b, direction) is not None else SIDE_NOT_QUOTED


def executable_price(block: dict, direction: str) -> "float | None":
    """Ask to buy, bid to sell -- and only when the quote is fresh.

    Returns None rather than a substitute. There is deliberately no argument
    that permits a settled close to stand in: a caller holding None must refuse
    the trade, not reach for the number that caused this module to exist.
    """
    if refusal(block, direction) is not None:
        return None
    return _side(block or {}, direction)


def _side(block: dict, direction: str) -> "float | None":
    d = (direction or "").lower()
    if d in _BULLISH:
        return block.get("best_ask")
    if d in _BEARISH:
        return block.get("best_bid")
    return None


def describe(block: dict) -> str:
    """One line for a refusal message. Names the age, never just 'stale'."""
    b = block or {}
    if not b.get("available"):
        return f"no executable price ({b.get('unavailable_reason')})"
    age = b.get("age_seconds")
    age_s = f"{age:.2f}s" if isinstance(age, (int, float)) else "unknown age"
    state = "fresh" if b.get("fresh") else f"STALE (> {b.get('max_age_seconds')}s)"
    return (f"bid {b.get('best_bid')} / ask {b.get('best_ask')} "
            f"at {age_s} — {state}")
