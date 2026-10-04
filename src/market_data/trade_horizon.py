"""Current-candidate destination and published protected-structure facts.

This projection describes where an already authorized candidate points. It
does not select geometry, grant participation, or manage an open position.
"""
from __future__ import annotations

import math


LOCAL_PARTICIPATION = "LOCAL_PARTICIPATION"
CAMPAIGN_HOLD = "CAMPAIGN_HOLD"
AUTHORITY_UNKNOWN = "AUTHORITY_UNKNOWN"

_DIRECTIONS = frozenset(("bullish", "bearish"))


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _unknown(reason, *, base=None):
    out = dict(base or {})
    out.update({"schema_version": 1,
                "classification": AUTHORITY_UNKNOWN,
                "classification_reason": str(reason)})
    return out


def _campaign_context(*, campaign_draw, campaign_lifecycle, snapshot,
                      direction, narrative_phase, session_id, contract_id):
    """Validate public, same-current-projection campaign lineage."""
    draw = campaign_draw if isinstance(campaign_draw, dict) else None
    lifecycle = campaign_lifecycle if isinstance(campaign_lifecycle, dict) else None
    derived = (snapshot or {}).get("derived_state") or {}
    revision = derived.get("history_revision")
    if (draw is None or lifecycle is None
            or derived.get("current") is not True
            or isinstance(revision, bool) or not isinstance(revision, int)
            or isinstance(derived.get("derived_revision"), bool)
            or isinstance(draw.get("history_revision"), bool)
            or not isinstance(draw.get("history_revision"), int)
            or derived.get("derived_revision") != revision):
        return None, "current_campaign_or_history_authority_unavailable"

    if (lifecycle.get("state") not in ("ACTIVE_DELIVERY", "RETRACING")
            or lifecycle.get("participation_permitted") is not True
            or lifecycle.get("authorized_direction") != direction
            or lifecycle.get("narrative_phase") != narrative_phase
            or lifecycle.get("campaign_draw_status") != "PROVEN_NOT_DELIVERED"):
        return None, "current_lifecycle_does_not_authorize_campaign_projection"

    try:
        from market_state.active_path import production_session_key
        from market_data.object_identity import canonical_instant
        cutoff = canonical_instant(draw.get("settled_cutoff"), strict=True)
        anchor = canonical_instant(draw.get("anchor_bar_time"), strict=True)
        expected_market_session = production_session_key(cutoff)
    except Exception:  # noqa: BLE001 -- descriptive evidence fails closed
        return None, "campaign_draw_time_or_market_session_invalid"

    episode = str(draw.get("campaign_episode_id") or "").strip()
    identity = str(draw.get("objective_identity") or "").strip()
    kind = str(draw.get("objective_kind") or "").strip()
    objective_price = _finite(draw.get("objective_price"))
    anchor_close = _finite(draw.get("anchor_bar_close"))
    if (draw.get("authority_status") != "PROVEN_NOT_DELIVERED"
            or draw.get("process_authority") != "CURRENT_PROCESS_ONLY"
            or draw.get("superseded") is not False
            or not episode or not identity or not kind
            or not session_id or draw.get("session_id") != session_id
            or draw.get("contract_id") != contract_id
            or draw.get("campaign_direction") != direction
            or draw.get("history_revision") != revision
            or not expected_market_session
            or draw.get("market_session") != expected_market_session
            or anchor is None or cutoff is None or anchor > cutoff
            or draw.get("anchor_price_basis") != "settled_1m_source_bar_close"
            or anchor_close is None or objective_price is None
            or draw.get("history_complete") is not True
            or draw.get("coverage_status") != "COMPLETE"
            or draw.get("progress_authoritative") is not True
            or lifecycle.get("campaign_episode_id") != episode
            or lifecycle.get("objective_identity") != identity):
        return None, "current_campaign_draw_lineage_invalid"
    path = (snapshot or {}).get("active_path_state") or {}
    if (path.get("state_available") is not True
            or path.get("owner") != direction or path.get("status") != "active"
            or path.get("session") != expected_market_session):
        return None, "active_path_market_session_mismatch"
    if direction == "bullish" and objective_price <= anchor_close:
        return None, "campaign_objective_side_invalid"
    if direction == "bearish" and objective_price >= anchor_close:
        return None, "campaign_objective_side_invalid"
    return {"draw": draw, "revision": revision,
            "objective_price": objective_price,
            "objective_identity": identity,
            "objective_kind": kind,
            "episode": episode}, None


def _protected_evidence(brain_input, *, direction, entry, target,
                        risk_points, contract_id, session_id, history_revision):
    protected = (brain_input or {}).get("protected_swings")
    registry = protected.get("by_timeframe") if isinstance(protected, dict) else None
    if (not isinstance(registry, dict)
            or not isinstance(registry.get("highs"), dict)
            or not isinstance(registry.get("lows"), dict)):
        return {"status": "UNKNOWN", "reason": "protected_swing_registry_unavailable",
                "witnesses": [], "nearest": None}

    sign = 1.0 if direction == "bullish" else -1.0
    target_distance = (target - entry) * sign
    witnesses = []
    for side in ("highs", "lows"):
        for timeframe, row in registry[side].items():
            if (not isinstance(timeframe, str) or not timeframe.strip()
                    or not isinstance(row, dict)):
                return {"status": "UNKNOWN",
                        "reason": "protected_swing_registry_row_invalid",
                        "witnesses": [], "nearest": None}
            level = _finite(row.get("level"))
            registered_at = row.get("registered_at")
            swing_id = row.get("swing_id")
            basis = row.get("basis")
            if (level is None or not isinstance(registered_at, str)
                    or not registered_at.strip()
                    or not isinstance(swing_id, str) or not swing_id.strip()
                    or not isinstance(basis, str) or not basis.strip()):
                return {"status": "UNKNOWN",
                        "reason": "protected_swing_registry_row_invalid",
                        "witnesses": [], "nearest": None}
            distance = (level - entry) * sign
            if distance < 0:
                relation = "BEHIND_ENTRY"
            elif distance == 0:
                relation = "AT_ENTRY"
            elif distance < target_distance:
                relation = "BETWEEN_ENTRY_AND_TARGET"
            elif distance == target_distance:
                relation = "AT_SELECTED_TARGET"
            else:
                relation = "BEYOND_SELECTED_TARGET"
            if relation in ("BEHIND_ENTRY", "AT_ENTRY",
                            "BETWEEN_ENTRY_AND_TARGET", "AT_SELECTED_TARGET"):
                witnesses.append({
                    "side": "high" if side == "highs" else "low",
                    "timeframe": timeframe,
                    "level": level,
                    "swing_id": swing_id,
                    "registered_at": registered_at,
                    "basis": basis,
                    "role": row.get("role"),
                    "relation": relation,
                    "distance_from_entry": distance,
                    "reward_to_risk": (distance / risk_points
                                       if risk_points > 0 and distance >= 0
                                       else None),
                    "lineage": {"contract_id": contract_id,
                                "session_id": session_id,
                                "history_revision": history_revision,
                                "side": "high" if side == "highs" else "low",
                                "timeframe": timeframe, "level": level,
                                "registered_at": registered_at,
                                "swing_id": swing_id},
                })

    between = [w for w in witnesses
               if w["relation"] == "BETWEEN_ENTRY_AND_TARGET"]
    nearest_distance = min((w["distance_from_entry"] for w in between),
                           default=None)
    nearest = ([w for w in between
                if w["distance_from_entry"] == nearest_distance]
               if nearest_distance is not None else [])
    witnesses.sort(key=lambda w: (w["distance_from_entry"], w["side"],
                                 w["timeframe"], w["registered_at"],
                                 w["swing_id"]))
    return {"status": ("NEAREST_PUBLISHED_PROTECTED_LEVEL"
                       if nearest else "NO_PUBLISHED_INTERVENING_PROTECTED_LEVEL"),
            "reason": None if nearest else "registry_has_no_level_between_entry_and_target",
            "witnesses": witnesses,
            "nearest": nearest}


def project_trade_horizon(*, snapshot, brain_input, campaign_draw,
                          campaign_lifecycle, direction, entry_price,
                          stop_price, objective_identity, objective_kind,
                          objective_price, snapshot_id, session_id,
                          contract_id, narrative_phase):
    """Describe candidate horizon and mapped structure without gating entry."""
    direction = str(direction or "").strip().lower()
    entry = _finite(entry_price)
    stop = _finite(stop_price)
    target = _finite(objective_price)
    identity = str(objective_identity or "").strip()
    kind = str(objective_kind or "").strip()
    market = (brain_input or {}).get("market") or {}
    quote = market.get("execution_price")
    quote = quote if isinstance(quote, dict) else {}
    base = {"snapshot_id": str(snapshot_id or ""),
            "contract_id": str(contract_id or ""),
            "session_id": str(session_id or ""),
            "direction": direction or None,
            "entry_price": entry,
            "entry_price_basis": "fresh_executable_directional_quote",
            "entry_price_field": ("bullish_executable" if direction == "bullish"
                                   else "bearish_executable" if direction == "bearish"
                                   else None),
            "quote_source": quote.get("source"),
            "quote_captured_at": quote.get("captured_at"),
            "quote_age_seconds": quote.get("age_seconds"),
            "settled_price_at_authorship": market.get("current_price"),
            "settled_price_basis": market.get("settled_price_basis"),
            "structural_stop": stop,
            "selected_objective": {"identity": identity or None,
                                   "kind": kind or None,
                                   "price": target}}
    if (direction not in _DIRECTIONS or entry is None or stop is None
            or target is None or not identity or not kind):
        return _unknown("candidate_geometry_unavailable", base=base)
    sign = 1.0 if direction == "bullish" else -1.0
    risk_points = abs(entry - stop)
    target_distance = (target - entry) * sign
    stop_distance = (entry - stop) * sign
    if risk_points <= 0 or target_distance <= 0 or stop_distance <= 0:
        return _unknown("candidate_geometry_invalid", base=base)
    base["risk_points"] = risk_points
    base["selected_target_distance"] = target_distance
    base["selected_target_reward_to_risk"] = target_distance / risk_points
    structure = _protected_evidence(
        brain_input, direction=direction, entry=entry, target=target,
        risk_points=risk_points, contract_id=contract_id,
        session_id=session_id,
        history_revision=((snapshot or {}).get("derived_state") or {}).get(
            "history_revision"))
    base["protected_structure"] = structure

    context, reason = _campaign_context(
        campaign_draw=campaign_draw,
        campaign_lifecycle=campaign_lifecycle,
        snapshot=snapshot, direction=direction,
        narrative_phase=str(narrative_phase or "").strip().lower(),
        session_id=session_id, contract_id=contract_id)
    if context is None:
        base["campaign"] = {"episode_id": None, "objective": None}
        return _unknown(reason, base=base)

    campaign_distance = (context["objective_price"] - entry) * sign
    if campaign_distance <= 0:
        return _unknown("campaign_objective_not_ahead_of_entry", base=base)
    base["campaign"] = {
        "episode_id": context["episode"],
        "process_authority": context["draw"].get("process_authority"),
        "session_id": context["draw"].get("session_id"),
        "market_session": context["draw"].get("market_session"),
        "history_revision": context["revision"],
        "settled_cutoff": context["draw"].get("settled_cutoff"),
        "objective": {"identity": context["objective_identity"],
                      "kind": context["objective_kind"],
                      "price": context["objective_price"]},
        "distance_from_entry": campaign_distance,
    }
    if (identity == context["objective_identity"]
            and kind == context["objective_kind"]
            and target == context["objective_price"]):
        base.update({"schema_version": 1, "classification": CAMPAIGN_HOLD,
                     "classification_reason": "selected_objective_matches_current_campaign_destination"})
        return base
    if identity == context["objective_identity"]:
        return _unknown("campaign_objective_identity_has_conflicting_kind_or_price",
                        base=base)
    if 0 < target_distance < campaign_distance:
        base.update({"schema_version": 1, "classification": LOCAL_PARTICIPATION,
                     "classification_reason": "selected_objective_is_between_entry_and_campaign_destination"})
        return base
    return _unknown("selected_objective_is_not_a_local_or_exact_campaign_destination",
                    base=base)
