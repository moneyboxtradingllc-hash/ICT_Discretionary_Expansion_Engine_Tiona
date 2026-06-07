"""
Phase 4B — Bracket / OTO Order Builder.

Attempts to build an Alpaca paper OTO (one-triggers-other) order:
  entry LIMIT → auto-submits a STOP leg when filled.
No take-profit required. Paper trading only. Pure request construction.

If the installed alpaca-py version does not expose OrderClass.OTO or
StopLossRequest, returns supported=False so the caller falls back to
the after_fill separate-stop strategy.
"""


def build_bracket_order(
    symbol: str,
    side: str,
    qty: int,
    limit_price: float,
    stop_price: float,
) -> dict:
    """
    Attempt to build a paper OTO order (limit entry + stop-loss leg).

    Returns:
      {"supported": True,  "order_request": ..., "method": "oto", "warnings": []}
    or:
      {"supported": False, "reason": "...",       "warnings": [...]}
    """
    warnings: list[str] = []

    # ── Input validation ───────────────────────────────────────────────────────
    if qty <= 0:
        return {"supported": False, "reason": f"qty must be > 0 (got {qty})", "warnings": []}
    if side not in ("buy", "sell"):
        return {"supported": False, "reason": f"invalid side '{side}' — expected buy/sell", "warnings": []}
    if stop_price is None or float(stop_price) <= 0:
        return {"supported": False, "reason": f"invalid stop_price {stop_price}", "warnings": []}
    if limit_price is None or float(limit_price) <= 0:
        return {"supported": False, "reason": f"invalid limit_price {limit_price}", "warnings": []}

    # ── Stop-price sanity vs entry ─────────────────────────────────────────────
    lp = float(limit_price)
    sp = float(stop_price)
    if side == "buy" and sp >= lp:
        warnings.append(
            f"stop_price {sp} >= limit_price {lp} for long entry — stop may be invalid"
        )
    elif side == "sell" and sp <= lp:
        warnings.append(
            f"stop_price {sp} <= limit_price {lp} for short entry — stop may be invalid"
        )

    # ── Attempt OTO construction ───────────────────────────────────────────────
    try:
        from alpaca.trading.requests import LimitOrderRequest, StopLossRequest
        from alpaca.trading.enums    import OrderSide, TimeInForce, OrderClass

        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        stop_loss  = StopLossRequest(stop_price=round(sp, 2))
        order_req  = LimitOrderRequest(
            symbol        = symbol,
            qty           = qty,
            side          = order_side,
            time_in_force = TimeInForce.DAY,
            limit_price   = round(lp, 2),
            order_class   = OrderClass.OTO,
            stop_loss     = stop_loss,
        )
        return {
            "supported":     True,
            "order_request": order_req,
            "method":        "oto",
            "warnings":      warnings,
        }

    except ImportError as exc:
        return {
            "supported": False,
            "reason":    f"OTO requires alpaca-py imports not available: {exc}",
            "warnings":  warnings,
        }
    except AttributeError as exc:
        # OrderClass.OTO or StopLossRequest not available in this alpaca-py version
        return {
            "supported": False,
            "reason":    f"OTO order class not supported in this alpaca-py version: {exc}",
            "warnings":  warnings,
        }
    except TypeError as exc:
        # Unexpected constructor signature change
        return {
            "supported": False,
            "reason":    f"bracket order construction failed (API signature mismatch): {exc}",
            "warnings":  warnings,
        }
    except Exception as exc:
        return {
            "supported": False,
            "reason":    f"bracket order build failed: {exc}",
            "warnings":  warnings,
        }
