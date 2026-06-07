"""
Paper Broker — Phase 2A/2B.

PAPER TRADING ONLY. Wraps the Alpaca TradingClient with hard safety guards.
Will raise RuntimeError if any indication of a live endpoint is detected.

Never imports live endpoint. Never allows execution on real money.
All submit functions validate the paper endpoint before every call.
"""
import os


_REQUIRED_PAPER_MARKER = "paper-api.alpaca.markets"


def _validate_paper_endpoint() -> str:
    """
    Read ALPACA_BASE_URL and reject anything that is not the paper endpoint.
    Returns the validated URL.
    Raises RuntimeError if the URL is unsafe or missing.
    """
    url = os.getenv("ALPACA_BASE_URL", "").strip()
    if not url:
        raise RuntimeError("ALPACA_BASE_URL is not set.")
    if _REQUIRED_PAPER_MARKER not in url:
        raise RuntimeError(
            f"Unsafe Alpaca endpoint detected: '{url}'. "
            f"Must contain '{_REQUIRED_PAPER_MARKER}'. Refusing to connect."
        )
    return url


def _build_client():
    """Create and return an Alpaca TradingClient for the paper endpoint only."""
    from alpaca.trading.client import TradingClient  # deferred: only loaded when broker is used

    _validate_paper_endpoint()
    api_key    = os.getenv("ALPACA_API_KEY", "")
    secret_key = os.getenv("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        raise RuntimeError("ALPACA_API_KEY or ALPACA_SECRET_KEY is not set.")

    # paper=True forces the paper-api endpoint within alpaca-py
    return TradingClient(api_key, secret_key, paper=True)


def is_paper_account_safe() -> tuple[bool, str]:
    """
    Lightweight check — confirms the configured endpoint is the paper endpoint.
    Returns (safe: bool, reason: str).
    Does NOT make a network call — pure config check.
    """
    try:
        _validate_paper_endpoint()
        paper_only = os.getenv("PAPER_TRADING_ONLY", "false").lower().strip()
        if paper_only != "true":
            return False, "PAPER_TRADING_ONLY is not 'true'"
        return True, "paper endpoint confirmed"
    except RuntimeError as exc:
        return False, str(exc)


def get_account() -> dict:
    """
    Return a dict summary of the paper account.
    Returns empty dict on failure (non-fatal — callers must handle gracefully).
    """
    try:
        client  = _build_client()
        account = client.get_account()
        return {
            "equity":         float(account.equity or 0),
            "cash":           float(account.cash or 0),
            "buying_power":   float(account.buying_power or 0),
            "status":         str(account.status),
            "account_number": str(account.account_number),
        }
    except Exception as exc:
        return {"error": str(exc)}


def get_open_positions() -> list:
    """
    Return list of open positions. Returns empty list on failure.
    Each item is a dict with symbol, qty, side.
    """
    try:
        client    = _build_client()
        positions = client.get_all_positions()
        return [
            {
                "symbol": str(p.symbol),
                "qty":    str(p.qty),
                "side":   str(p.side),
            }
            for p in (positions or [])
        ]
    except Exception as exc:
        return [{"error": str(exc)}]


def get_orders(status: str = "open") -> list:
    """
    Return a list of orders filtered by status ('open', 'closed', 'all').
    Returns empty list on failure.
    """
    try:
        from alpaca.trading.requests import GetOrdersRequest
        client  = _build_client()
        request = GetOrdersRequest(status=status)
        orders  = client.get_orders(filter=request)
        return [
            {
                "id":           str(o.id),
                "symbol":       str(o.symbol),
                "side":         str(o.side),
                "qty":          str(o.qty),
                "status":       str(o.status),
                "limit_price":  str(o.limit_price),
                "submitted_at": str(o.submitted_at),
            }
            for o in (orders or [])
        ]
    except Exception as exc:
        return [{"error": str(exc)}]


def get_position(symbol: str) -> dict | None:
    """
    Return open position details for symbol, or None if no position exists.
    Returns {"error": ...} on unexpected failure.
    """
    try:
        client   = _build_client()
        position = client.get_open_position(symbol)
        # PositionSide is a str enum — extract "long" or "short" safely
        side_raw = str(position.side).lower()
        side     = "long" if "long" in side_raw else "short"
        return {
            "symbol":          str(position.symbol),
            "qty":             str(position.qty),
            "side":            side,
            "avg_entry_price": str(position.avg_entry_price or "0"),
            "current_price":   str(position.current_price)  if position.current_price  is not None else None,
            "unrealized_pl":   str(position.unrealized_pl)  if position.unrealized_pl  is not None else None,
            "market_value":    str(position.market_value)   if position.market_value   is not None else None,
        }
    except Exception as exc:
        exc_str = str(exc)
        # 404 / "position does not exist" means no open position — not an error
        if "404" in exc_str or "position does not exist" in exc_str.lower() or "no position" in exc_str.lower():
            return None
        return {"error": exc_str}


def get_order(order_id: str) -> dict:
    """
    Return order details for a given order ID.
    Returns {"error": ...} on failure.
    """
    try:
        client = _build_client()
        order  = client.get_order_by_id(order_id)
        # OrderStatus enum → string value
        try:
            status = order.status.value
        except AttributeError:
            raw = str(order.status).lower()
            status = raw.split(".")[-1] if "." in raw else raw
        return {
            "id":               str(order.id),
            "symbol":           str(order.symbol),
            "status":           status,
            "side":             str(order.side),
            "qty":              str(order.qty),
            "filled_qty":       str(order.filled_qty)       if order.filled_qty       is not None else None,
            "filled_avg_price": str(order.filled_avg_price) if order.filled_avg_price is not None else None,
            "submitted_at":     str(order.submitted_at),
        }
    except Exception as exc:
        return {"error": str(exc)}


def submit_paper_exit_order(symbol: str, qty: int, side: str) -> dict:
    """
    Submit a paper MARKET exit order to close a position.
    side must be "sell" (to close long) or "buy" (to close short).
    Raises RuntimeError on safety failure.
    """
    safe, reason = is_paper_account_safe()
    if not safe:
        raise RuntimeError(f"Paper safety check failed: {reason}")

    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums    import OrderSide, TimeInForce

    order_side = OrderSide.SELL if side.lower() == "sell" else OrderSide.BUY
    order_request = MarketOrderRequest(
        symbol        = symbol,
        qty           = qty,
        side          = order_side,
        time_in_force = TimeInForce.DAY,
    )
    try:
        client = _build_client()
        order  = client.submit_order(order_data=order_request)
        return {
            "alpaca_order_id": str(order.id),
            "status":          str(order.status),
            "symbol":          str(order.symbol),
            "side":            str(order.side),
            "qty":             str(order.qty),
            "submitted_at":    str(order.submitted_at),
        }
    except Exception as exc:
        raise RuntimeError(f"Exit order submission failed: {exc}") from exc


def close_position_market(symbol: str) -> dict:
    """
    Close the entire open position for symbol at market.
    Validates paper endpoint before every call.
    Raises RuntimeError on safety failure.
    """
    safe, reason = is_paper_account_safe()
    if not safe:
        raise RuntimeError(f"Paper safety check failed: {reason}")

    try:
        client = _build_client()
        order  = client.close_position(symbol)
        return {
            "alpaca_order_id": str(order.id),
            "status":          str(order.status),
            "symbol":          str(order.symbol),
            "submitted_at":    str(order.submitted_at),
        }
    except Exception as exc:
        raise RuntimeError(f"close_position_market failed: {exc}") from exc


def get_recent_closed_orders_for_symbol(symbol: str, limit: int = 10) -> list:
    """
    Return recent closed/filled orders for symbol (most recent first).
    Used by trade_reconciliation to detect externally-closed positions.
    Returns empty list on failure.
    """
    try:
        from alpaca.trading.requests import GetOrdersRequest
        client = _build_client()
        try:
            request = GetOrdersRequest(status="closed", symbols=[symbol], limit=limit)
        except TypeError:
            request = GetOrdersRequest(status="closed", limit=limit)
        orders = client.get_orders(filter=request) or []
        result = []
        for o in orders:
            if str(o.symbol) != symbol:
                continue
            try:
                status = o.status.value
            except AttributeError:
                raw    = str(o.status).lower()
                status = raw.split(".")[-1] if "." in raw else raw
            filled_avg = str(o.filled_avg_price) if o.filled_avg_price is not None else None
            filled_qty = str(o.filled_qty)       if o.filled_qty       is not None else None
            result.append({
                "id":               str(o.id),
                "symbol":           str(o.symbol),
                "status":           status,
                "side":             str(o.side).lower(),
                "qty":              str(o.qty),
                "filled_qty":       filled_qty,
                "filled_avg_price": filled_avg,
                "submitted_at":     str(o.submitted_at),
            })
            if len(result) >= limit:
                break
        return result
    except Exception as exc:
        return [{"error": str(exc)}]


def submit_protective_stop_order(
    symbol: str, qty: int, side: str, stop_price: float
) -> dict:
    """
    Submit a paper STOP order to protect an open position.
    side must be "sell" (to protect a long) or "buy" (to protect a short).
    Returns {"alpaca_order_id": ..., "status": ..., ...} or {"error": ...}.
    """
    safe, reason = is_paper_account_safe()
    if not safe:
        return {"error": f"paper safety check failed: {reason}"}

    if qty <= 0:
        return {"error": f"qty must be > 0 (got {qty})"}
    if stop_price <= 0:
        return {"error": f"invalid stop_price {stop_price}"}
    if side not in ("buy", "sell"):
        return {"error": f"invalid side '{side}'"}

    from alpaca.trading.requests import StopOrderRequest
    from alpaca.trading.enums    import OrderSide, TimeInForce

    order_side = OrderSide.SELL if side.lower() == "sell" else OrderSide.BUY
    try:
        order_request = StopOrderRequest(
            symbol        = symbol,
            qty           = qty,
            side          = order_side,
            time_in_force = TimeInForce.GTC,   # GTC — stop persists until triggered
            stop_price    = round(float(stop_price), 2),
        )
        client = _build_client()
        order  = client.submit_order(order_data=order_request)
        return {
            "alpaca_order_id": str(order.id),
            "status":          str(order.status),
            "symbol":          str(order.symbol),
            "side":            str(order.side),
            "qty":             str(order.qty),
            "stop_price":      str(order.stop_price) if order.stop_price is not None else None,
            "submitted_at":    str(order.submitted_at),
        }
    except Exception as exc:
        return {"error": f"stop order submission failed: {exc}"}


def get_open_orders(symbol: str | None = None) -> list:
    """
    Return list of open orders, optionally filtered by symbol.
    Each item includes: id, symbol, side, type, qty, status, stop_price, limit_price.
    Returns empty list on failure.
    """
    try:
        from alpaca.trading.requests import GetOrdersRequest
        client = _build_client()
        try:
            req = GetOrdersRequest(status="open", symbols=[symbol]) if symbol else GetOrdersRequest(status="open")
        except TypeError:
            req = GetOrdersRequest(status="open")
        orders = client.get_orders(filter=req) or []
        result = []
        for o in orders:
            if symbol and str(o.symbol) != symbol:
                continue
            try:
                order_type = o.type.value if hasattr(o.type, "value") else str(o.type).lower()
                order_type = order_type.split(".")[-1] if "." in order_type else order_type
            except Exception:
                order_type = "unknown"
            try:
                status = o.status.value
            except AttributeError:
                raw    = str(o.status).lower()
                status = raw.split(".")[-1] if "." in raw else raw
            result.append({
                "id":          str(o.id),
                "symbol":      str(o.symbol),
                "side":        str(o.side).lower().split(".")[-1],
                "type":        order_type,
                "qty":         str(o.qty),
                "status":      status,
                "stop_price":  str(o.stop_price)  if o.stop_price  is not None else None,
                "limit_price": str(o.limit_price) if o.limit_price is not None else None,
                "submitted_at": str(o.submitted_at),
            })
        return result
    except Exception as exc:
        return [{"error": str(exc)}]


def find_open_stop_order(
    symbol: str,
    side: str,
    stop_price: float,
    tolerance: float = 0.02,
) -> dict | None:
    """
    Find an open stop order for symbol matching side and stop_price (within tolerance).
    Returns the first matching order dict or None.
    """
    try:
        orders = get_open_orders(symbol)
        for o in orders:
            if "error" in o:
                continue
            if str(o.get("symbol", "")) != symbol:
                continue
            o_side = o.get("side", "").lower().split(".")[-1]
            if o_side != side.lower():
                continue
            o_type = o.get("type", "")
            if o_type not in ("stop", "stop_limit"):
                continue
            raw_sp = o.get("stop_price")
            if raw_sp is None:
                continue
            try:
                if abs(float(raw_sp) - float(stop_price)) <= tolerance:
                    return o
            except (ValueError, TypeError):
                continue
        return None
    except Exception:
        return None


def cancel_order(order_id: str) -> dict:
    """
    Cancel an open order by ID.
    Returns {"canceled": True} or {"canceled": False, "reason": str}.
    Non-cancelable (already filled/expired) is treated as non-fatal.
    """
    safe, reason = is_paper_account_safe()
    if not safe:
        return {"canceled": False, "reason": f"paper safety check failed: {reason}"}

    try:
        client = _build_client()
        client.cancel_order_by_id(order_id)
        return {"canceled": True}
    except Exception as exc:
        exc_str = str(exc)
        if any(k in exc_str for k in ("422", "not cancelable", "not found", "404")):
            return {"canceled": False, "reason": f"order not cancelable (may be filled/expired): {exc_str}"}
        return {"canceled": False, "reason": str(exc)}


def submit_paper_order(order_request) -> dict:
    """
    Submit a paper limit order to Alpaca.
    Returns a dict with alpaca_order_id and status.
    Raises RuntimeError on safety or validation failure.
    """
    safe, reason = is_paper_account_safe()
    if not safe:
        raise RuntimeError(f"Paper safety check failed: {reason}")

    try:
        client = _build_client()
        order  = client.submit_order(order_data=order_request)
        return {
            "alpaca_order_id": str(order.id),
            "status":          str(order.status),
            "symbol":          str(order.symbol),
            "side":            str(order.side),
            "qty":             str(order.qty),
            "limit_price":     str(order.limit_price),
            "submitted_at":    str(order.submitted_at),
        }
    except Exception as exc:
        raise RuntimeError(f"Order submission failed: {exc}") from exc
