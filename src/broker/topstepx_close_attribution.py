"""Prove which venue trade belongs to one bot-authored position close.

The POSITION/closeContract endpoint may acknowledge a close without returning
the venue-minted order id.  This module joins that durable intent/response to
the venue trade ledger only when the complete identity, side, quantity, time
window, and flat-reconciliation evidence agree.  Missing or conflicting facts
remain UNKNOWN; flatness alone never attributes a trade.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math

from broker import topstepx_submission_record as SUBREC


SCHEMA = "emergency_close_flat_confirmation.v1"
PROVEN = "PROVEN"
UNKNOWN = "UNKNOWN"


def _same(a, b) -> bool:
    return a is not None and b is not None and str(a) == str(b)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(value):
    try:
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def _timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _field(row, *keys):
    if not isinstance(row, dict):
        return None
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


def _side(value):
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"buy", "long"}:
            return 0
        if lowered in {"sell", "short"}:
            return 1
    parsed = _int(value)
    return parsed if parsed in (0, 1) else None


def mission_close_submissions(mission) -> list:
    """Return latest durable close rows for the exact mission/session only."""
    path = getattr(mission, "path", None)
    session_id = getattr(mission, "session_id", None)
    mission_id = getattr(mission, "mission_id", None)
    if not path or not session_id or not mission_id:
        return []
    import os
    rows = SUBREC.latest_by_submission(
        os.path.dirname(path), str(session_id), str(mission_id)).values()
    return [row for row in rows
            if row.get("operation") == SUBREC.OPERATION_POSITION_CLOSE]


def has_unresolved_bot_close(*, submissions, mission, contract_id) -> bool:
    """Whether this mission has a venue-reachable close lacking a refusal.

    Reconciliation must not terminalize an unattributed flat mission while a
    bot-authored close could still be resolved from the venue trade ledger.
    """
    for row in submissions or []:
        if not _identity_matches(row, mission, contract_id):
            continue
        if row.get("state") not in SUBREC.VENUE_MAY_HAVE_SEEN:
            continue
        if (row.get("raw_response") or {}).get("success") is False:
            continue
        if row.get("venue_order_id") is not None:
            return True
        if row.get("transport_exception") or row.get("success") is True:
            return True
        if row.get("state") == SUBREC.SUBMISSION_STARTED:
            return True
    return False


def _identity_matches(row, mission, contract_id) -> bool:
    return (
        row.get("operation") == SUBREC.OPERATION_POSITION_CLOSE
        and _same(row.get("mission_id"), getattr(mission, "mission_id", None))
        and _same(row.get("session_id"), getattr(mission, "session_id", None))
        and _same(row.get("account_fingerprint"),
                  getattr(mission, "account_fingerprint", None))
        and _same(row.get("contract_id"), contract_id)
        and _same(getattr(mission, "contract_id", None), contract_id)
        and _same(((row.get("geometry") or {}).get("emergency_close") or {}).get(
            "entry_order_id"), getattr(mission, "order_id", None))
    )


def _flat_evidence(row, current_flat_observation):
    recorded = (row.get("reconciliation") or {}).get("close_flat_confirmation")
    for evidence in (recorded, current_flat_observation):
        if not isinstance(evidence, dict):
            continue
        if (evidence.get("schema") == SCHEMA
                and evidence.get("flat_confirmed") is True
                and evidence.get("safe_terminal") is True
                and evidence.get("orders_complete") is True
                and evidence.get("all_positions_flat") is True
                and evidence.get("contract_position_size") == 0
                and evidence.get("mission_working_orders") == []
                and evidence.get("unaccounted_same_contract") == []
                and _same(evidence.get("mission_id"), row.get("mission_id"))
                and _same(evidence.get("session_id"), row.get("session_id"))
                and _same(evidence.get("account_fingerprint"),
                          row.get("account_fingerprint"))
                and _same(evidence.get("contract_id"), row.get("contract_id"))
                and _same(evidence.get("close_submission_id"),
                          row.get("submission_id"))):
            return evidence
    return None


def _trade_identity(trade):
    return {
        "order_id": _field(trade, "order_id", "orderId"),
        "contract_id": _field(trade, "contract_id", "contractId"),
        "created": _field(trade, "created", "creationTimestamp"),
        "side": _side(_field(trade, "side")),
        "size": _int(_field(trade, "size")),
        "price": _number(_field(trade, "price", "fill_price")),
    }


def _order_conflicts(order_id, orders, *, contract_id, expected_side,
                     expected_quantity):
    matches = [row for row in (orders or [])
               if _same(_field(row, "id", "order_id", "orderId"), order_id)]
    for row in matches:
        contract = _field(row, "contract_id", "contractId")
        side = _side(_field(row, "side"))
        size = _int(_field(row, "size"))
        if (not _same(contract, contract_id)
                or (side is not None and side != expected_side)
                or (size is not None and abs(size) != expected_quantity)):
            return True
    return False


def prove_emergency_close_attribution(*, submissions, trades, mission,
                                      contract_id, orders=None,
                                      current_flat_observation=None) -> dict:
    """Return PROVEN only for a uniquely attributable venue close fill.

    For the no-order-id case, proof requires the exact successful close request,
    its measured pre-close position and requested offset, a complete safe-flat
    observation, and a unique venue trade set in the close's bounded time
    interval. Any second close attempt or conflicting trade keeps attribution
    UNKNOWN.
    """
    def unknown(reason):
        return {"status": UNKNOWN, "reason": reason}

    mission_rows = [row for row in (submissions or [])
                    if row.get("operation") == SUBREC.OPERATION_POSITION_CLOSE
                    and _identity_matches(row, mission, contract_id)]
    if len(mission_rows) != 1:
        return unknown("close_submission_not_unique")
    row = mission_rows[0]
    raw = row.get("raw_response") or {}
    if raw.get("success") is not True or row.get("transport_exception"):
        return unknown("close_response_not_positive")

    geometry = row.get("geometry") or {}
    intent = geometry.get("emergency_close") or {}
    signed_before = _int(intent.get("pre_close_signed_position"))
    quantity = _int(intent.get("requested_quantity"))
    side = _side(intent.get("requested_side"))
    prepared_at = _timestamp(row.get("prepared_at_utc"))
    if (signed_before in (None, 0) or quantity is None
            or quantity != abs(signed_before)
            or side != (0 if signed_before < 0 else 1)
            or not _same(intent.get("entry_order_id"),
                         getattr(mission, "order_id", None))
            or prepared_at is None):
        return unknown("close_intent_geometry_incomplete")

    flat = _flat_evidence(row, current_flat_observation)
    if flat is None:
        return unknown("safe_flat_confirmation_missing")
    observed_at = _timestamp(flat.get("observed_at_utc"))
    response_at = _timestamp(row.get("response_at_utc"))
    end_at = observed_at
    if response_at is None or end_at is None or end_at < response_at:
        return unknown("close_timestamps_unusable")

    # Entry fills are expected to precede this close and can share a timestamp
    # at venue resolution. They are already owned through the mission's entry
    # identity, so exclude only that exact order; any other same-contract fill
    # in the close interval is potentially conflicting activity.
    entry_id = getattr(mission, "order_id", None)
    in_window = []
    for trade in trades or []:
        if bool(_field(trade, "voided")):
            continue
        identity = _trade_identity(trade)
        if not _same(identity["contract_id"], contract_id):
            continue
        created = _timestamp(identity["created"])
        if created is None or created < prepared_at or created > end_at:
            continue
        if _same(identity["order_id"], entry_id):
            continue
        in_window.append(identity)

    if not in_window or any(row.get("order_id") is None
                            or row.get("side") is None
                            or row.get("size") is None for row in in_window):
        return unknown("close_fill_missing_or_unidentified")
    order_ids = {str(row["order_id"]) for row in in_window}
    if len(order_ids) != 1:
        return unknown("conflicting_close_interval_trades")
    order_id = in_window[0]["order_id"]
    response_order_id = row.get("venue_order_id")
    if (response_order_id is not None
            and not _same(response_order_id, order_id)):
        return unknown("response_and_trade_order_identity_mismatch")
    if (any(row["side"] != side for row in in_window)
            or sum(abs(row["size"]) for row in in_window) != quantity):
        return unknown("close_fill_side_or_quantity_mismatch")
    if _order_conflicts(order_id, orders, contract_id=contract_id,
                        expected_side=side, expected_quantity=quantity):
        return unknown("discovered_order_conflicts_with_close_fill")

    prices = [row["price"] for row in in_window]
    exit_price = None
    if all(price is not None for price in prices):
        exit_price = sum(abs(row["size"]) * price
                         for row, price in zip(in_window, prices)) / quantity
    return {
        "status": PROVEN,
        "order_id": order_id,
        "exit_price": exit_price,
        "quantity": quantity,
        "close_submission_id": row["submission_id"],
        "proof": "bot_close_intent+positive_venue_response+unique_trade_fill+safe_flat",
        "trade_fill_count": len(in_window),
    }
