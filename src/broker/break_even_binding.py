"""Identity evidence for break-even. No proposals, order writes or AI.

The mission owner selects a trade; its actual durable path selects the file.
Neither slot arithmetic nor an armed boolean can grant management authority.
Old/incomplete records remain readable elsewhere, but cannot authorize BE.
"""
from __future__ import annotations

import json
import os

from broker import break_even_baseline as BB
from broker import protection_state as PS
from broker import topstepx_submission_record as SUB


class BindingRefused(ValueError):
    pass


def same(actual, expected, field):
    if (actual is None or expected is None or isinstance(actual, bool)
            or isinstance(expected, bool) or not str(actual).strip()
            or not str(expected).strip() or str(actual) != str(expected)):
        raise BindingRefused(f"identity mismatch or missing: {field}")


def number(actual, expected, field):
    a, e = PS.price(actual), PS.price(expected)
    if a is None or e is None or abs(a - e) > 1e-8:
        raise BindingRefused(f"geometry mismatch or missing: {field}")


def identity(owner, mission, session):
    auth = owner.authorization
    same(auth.authorization_fingerprint, auth.fingerprint(), "signed authorization")
    expected = dict(session_id=auth.session_id, mission_id=mission.mission_id,
                    order_id=mission.order_id, token_id=mission.token_id,
                    account_fingerprint=auth.account_fingerprint,
                    contract_id=auth.contract_id,
                    authorization_fingerprint=auth.fingerprint())
    for field, value in expected.items():
        same(getattr(mission, field, None), value, field)
    same(session.account_fingerprint, auth.account_fingerprint, "lane account")
    same(session.contract.id, auth.contract_id, "lane contract")
    same(session.session_id, auth.session_id, "lane session")
    path = os.path.realpath(mission.path)
    if os.path.normcase(os.path.dirname(path)) != os.path.normcase(
            os.path.realpath(owner.store_dir)):
        raise BindingRefused("mission path outside owned store")
    disk = BB.load_mission(path)
    if not isinstance(disk, dict):
        raise BindingRefused("mission record unreadable")
    for field, value in expected.items():
        same(disk.get(field), value, f"durable {field}")
    same(disk.get("state"), mission.state, "durable state")
    return expected, disk


def recover(owner, mission, session):
    """Strict live binding, wrapping the historical pure baseline reader."""
    expected, disk = identity(owner, mission, session)
    for field in ("fill_price", "filled_quantity"):
        number(disk.get(field), getattr(mission, field, None), field)
    ledger = SUB.ledger_path(owner.store_dir, expected["session_id"])
    geometry, submission_id, acknowledged = None, None, False
    with open(ledger, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)  # corrupt evidence is unavailable, not skipped
            if not isinstance(row, dict):
                raise BindingRefused("invalid submission row")
            if row.get("mission_id") != expected["mission_id"]:
                continue
            if row.get("operation") != SUB.OPERATION_ORDER_PLACE:
                continue  # emergency/cancel records are not entry geometry
            for field, value in expected.items():
                if field != "order_id":
                    same(row.get(field), value, f"submission {field}")
            same(row.get("submission_id"), row.get("submission_id"), "submission id")
            if submission_id is not None:
                same(row.get("submission_id"), submission_id, "one entry submission")
            submission_id = row["submission_id"]
            geo = row.get("geometry")
            if not isinstance(geo, dict) or not geo or (geometry is not None and geo != geometry):
                raise BindingRefused("missing or contradictory submission geometry")
            geometry = geo
            number(row.get("quantity"), disk.get("filled_quantity"), "submission quantity")
            number(row.get("side"), 0 if BB._side(geo.get("direction")) == "long" else 1,
                   "submission side")
            if row.get("venue_order_id") is not None:
                same(row["venue_order_id"], expected["order_id"], "submission entry order")
                acknowledged |= row.get("success") is True
    if not acknowledged or geometry is None:
        raise BindingRefused("no bound entry acknowledgement/geometry")
    baseline = BB.recover(mission_path=mission.path, submissions_path=ledger)
    if baseline.get("status") != BB.RECOVERED:
        raise BindingRefused(f"baseline unavailable: {baseline.get('reason')}")
    number(baseline.get("original_initial_stop"), geometry.get("stop_price"), "original stop")
    same(baseline.get("direction"), BB._side(geometry.get("direction")), "direction")
    target = PS.price(geometry.get("target_price"))
    if target is None:
        raise BindingRefused("missing original target")
    return dict(baseline, session_id=expected["session_id"],
                authorization_fingerprint=expected["authorization_fingerprint"],
                original_target_price=target)


def context(baseline, ctx, runner):
    if ctx is None:
        raise BindingRefused("no bound execution context")
    for field in ("session_id", "mission_id", "entry_order_id", "token_id",
                  "account_fingerprint", "contract_id", "authorization_fingerprint"):
        same(getattr(ctx, field, None), baseline.get(field), f"context {field}")
    same(runner.order_id, baseline["entry_order_id"], "runner entry order")
    same(runner.account_fingerprint, baseline["account_fingerprint"], "runner account")
    same(runner.contract.id, baseline["contract_id"], "runner contract")
    same(PS.normalized_direction(ctx.direction), baseline["direction"], "context direction")
    for field, key in (("quantity", "quantity"), ("entry_fill_price", "entry_fill_price"),
                       ("structural_stop_price", "original_initial_stop"),
                       ("original_thesis_invalidation", "original_initial_stop"),
                       ("liquidity_target_price", "original_target_price")):
        number(getattr(ctx, field, None), baseline[key], f"context {field}")
    same(ctx.position_id, ctx.position_id, "position id")
    same(ctx.stop_order_id, ctx.stop_order_id, "stop id")
    same(ctx.target_order_id, ctx.target_order_id, "target id")
    if ctx.protection_baseline_armed is not True or PS.price(ctx.active_protective_stop) is None:
        raise BindingRefused("structural baseline not armed")


def position(positions, *, contract_id, direction, quantity, fill, position_id=None):
    """Single pinned position AND fill geometry; contract alone is insufficient.

    The durable position id originates only after order-linked full fills and
    verified children. Replacement ids, scale-ins, partials and flips refuse BE.
    The venue still exposes net positions, not an entry-order/position join.
    """
    if not isinstance(positions, list) or len(positions) != 1:
        raise BindingRefused("one attributable account position required")
    pos = positions[0]
    same(pos.get("contract_id"), contract_id, "position contract")
    same(pos.get("id"), position_id if position_id is not None else pos.get("id"), "position id")
    same(PS.normalized_direction(pos.get("side")), direction, "position direction")
    number(pos.get("size"), quantity, "position size")
    number(pos.get("avg_price"), fill, "position fill")
    return pos


def venue_position(session, baseline, ctx):
    return position(session.open_positions(), contract_id=baseline["contract_id"],
                    direction=baseline["direction"], quantity=baseline["quantity"],
                    fill=baseline["entry_fill_price"], position_id=ctx.position_id)


def protection(probe, ctx, *, target_price):
    """Recovery requires a complete, identity-bound bracket; never reanchors."""
    if not probe.get("known") or not probe.get("complete"):
        raise BindingRefused("complete protection evidence unavailable")
    for name, oid, price_field in (("stop", ctx.stop_order_id, "stop_price"),
                                    ("target", ctx.target_order_id, "limit_price")):
        order = probe.get(name) or {}
        same(order.get("id"), oid, f"{name} child id")
        number(order.get("size"), ctx.quantity, f"{name} child size")
        number(order.get("side"), 1 if BB._side(ctx.direction) == "long" else 0,
               f"{name} child side")
        if PS.price(order.get(price_field)) is None:
            raise BindingRefused(f"missing {name} price")
    number(probe["target"].get("limit_price"), target_price, "working target")


def aligned_target(ctx, contract):
    # Reuse the structural alignment authority, without authorizing an entry.
    from types import SimpleNamespace
    from broker.topstepx_execution_runner import ExecutionRunner
    runner = ExecutionRunner(session=None, account_fingerprint=ctx.account_fingerprint,
                             contract=contract)
    runner.geometry = SimpleNamespace(direction="bullish" if BB._side(ctx.direction) == "long" else "bearish",
                                      stop_price=ctx.structural_stop_price,
                                      target_price=ctx.liquidity_target_price)
    return runner._aligned_structural_prices(ctx.entry_fill_price)["target_price"]
