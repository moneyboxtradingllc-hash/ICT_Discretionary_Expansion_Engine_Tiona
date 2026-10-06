"""Campaign phase projection and participation gate.

This is a stateless projection of the current Brain/Narrative, ActivePath,
Campaign Draw, and derived-history authorities. It owns no direction, objective,
transfer detector, persistence, target policy, or position management.
"""
from __future__ import annotations

import math

UNESTABLISHED = "UNESTABLISHED"
ESTABLISHING = "ESTABLISHING"
ACTIVE_DELIVERY = "ACTIVE_DELIVERY"
RETRACING = "RETRACING"
DESTINATION_SUBSTANTIALLY_DELIVERED = "DESTINATION_SUBSTANTIALLY_DELIVERED"
TRANSFER_UNRESOLVED = "TRANSFER_UNRESOLVED"
AUTHORITY_UNKNOWN = "AUTHORITY_UNKNOWN"

_PERMITTED_STATES = frozenset((ACTIVE_DELIVERY, RETRACING))
_DIRECTIONS = frozenset(("bullish", "bearish"))


def _finite(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _instant(value):
    try:
        from market_data.object_identity import canonical_instant
        return canonical_instant(value, strict=True)
    except Exception:  # noqa: BLE001 -- malformed authority fails closed
        return None


def _result(state, reason, *, direction=None, draw=None, control_state=None,
            phase=None):
    draw = draw if isinstance(draw, dict) else {}
    return {
        "schema_version": 1,
        "state": state,
        "reason": str(reason),
        "participation_permitted": state in _PERMITTED_STATES,
        "authorized_direction": direction if state in _PERMITTED_STATES else None,
        "campaign_episode_id": draw.get("campaign_episode_id"),
        "objective_identity": draw.get("objective_identity"),
        "campaign_draw_status": draw.get("authority_status"),
        "narrative_control_state": control_state,
        "narrative_phase": phase,
    }


def _forming(path: dict) -> bool:
    """Recognize ActivePath's descriptive causal hypothesis, never an owner."""
    origin = path.get("origin") or {}
    return bool(
        path.get("owner") in (None, "none")
        and path.get("status") == "forming"
        and path.get("forming_direction") in _DIRECTIONS
        and isinstance(origin, dict)
        and origin.get("direction") == path.get("forming_direction")
        and origin.get("proof_family") == "rejected_raid_reclaim"
        and origin.get("occurrence_id")
        and origin.get("at"))


def _no_campaign_draw(draw: dict) -> bool:
    return (draw.get("authority_status") == "UNKNOWN"
            and draw.get("process_authority") == "CURRENT_PROCESS_ONLY"
            and draw.get("authority_reason") == "no_accepted_campaign_draw"
            and not draw.get("campaign_episode_id"))


def _valid_draw(draw, *, snapshot, direction, session_id, contract_id,
                history_revision):
    """Validate public Draw authority without consulting audit history."""
    if not isinstance(draw, dict):
        return False, "campaign_draw_unavailable"
    if draw.get("authority_status") not in ("PROVEN_NOT_DELIVERED",
                                               "PROVEN_DELIVERED"):
        return False, "campaign_draw_authority_unknown"
    if draw.get("process_authority") != "CURRENT_PROCESS_ONLY":
        return False, "campaign_draw_process_authority_invalid"
    if not str(draw.get("campaign_episode_id") or "").strip():
        return False, "campaign_draw_episode_missing"
    if draw.get("superseded") is not False:
        return False, "campaign_draw_superseded_or_unverified"
    if (not session_id or draw.get("session_id") != session_id
            or not contract_id or draw.get("contract_id") != contract_id
            or draw.get("campaign_direction") != direction):
        return False, "campaign_draw_identity_mismatch"

    cutoff = _instant(draw.get("settled_cutoff"))
    anchor = _instant(draw.get("anchor_bar_time"))
    if (cutoff is None or anchor is None or anchor > cutoff
            or draw.get("anchor_price_basis") != "settled_1m_source_bar_close"):
        return False, "campaign_draw_anchor_or_cutoff_invalid"
    try:
        from market_state.active_path import production_session_key
        expected_market_session = production_session_key(cutoff)
    except Exception:  # noqa: BLE001
        expected_market_session = None
    if (not expected_market_session
            or draw.get("market_session") != expected_market_session):
        return False, "campaign_draw_market_session_mismatch"
    path = snapshot.get("active_path_state") or {}
    if path.get("session") != expected_market_session:
        return False, "active_path_market_session_mismatch"

    anchor_close = _finite(draw.get("anchor_bar_close"))
    objective_price = _finite(draw.get("objective_price"))
    objective_identity = str(draw.get("objective_identity") or "").strip()
    if anchor_close is None or objective_price is None or not objective_identity:
        return False, "campaign_draw_objective_or_anchor_invalid"
    if ((direction == "bullish" and objective_price <= anchor_close)
            or (direction == "bearish" and objective_price >= anchor_close)):
        return False, "campaign_draw_objective_side_invalid"

    revision = draw.get("history_revision")
    if (isinstance(revision, bool) or not isinstance(revision, int)
            or revision != history_revision):
        return False, "campaign_draw_history_revision_mismatch"
    derived = snapshot.get("derived_state") or {}
    if (derived.get("current") is not True
            or derived.get("history_revision") != history_revision
            or derived.get("derived_revision") != history_revision):
        return False, "derived_history_not_current"

    if draw["authority_status"] == "PROVEN_NOT_DELIVERED":
        if (draw.get("history_complete") is not True
                or draw.get("coverage_status") != "COMPLETE"
                or draw.get("progress_authoritative") is not True):
            return False, "campaign_draw_negative_or_progress_coverage_incomplete"
    else:
        evidence_at = _instant(draw.get("delivery_evidence_bar"))
        evidence_price = _finite(draw.get("delivery_evidence_price"))
        if (evidence_at is None or evidence_price is None
                or not anchor < evidence_at <= cutoff
                or (direction == "bullish" and evidence_price < objective_price)
                or (direction == "bearish" and evidence_price > objective_price)):
            return False, "campaign_draw_delivery_evidence_invalid"
    return True, None


def evaluate_campaign_lifecycle(*, snapshot, brain_output,
                                narrative_continuity, campaign_draw,
                                session_id, contract_id,
                                brain_authority_available=True) -> dict:
    """Project current authorities into one mutually exclusive lifecycle state."""
    snap = snapshot if isinstance(snapshot, dict) else {}
    output = brain_output if isinstance(brain_output, dict) else {}
    authored = (narrative_continuity
                if isinstance(narrative_continuity, dict) else {})
    draw = campaign_draw if isinstance(campaign_draw, dict) else {}
    phase = str(output.get("narrative_phase") or "").strip().lower()

    derived = snap.get("derived_state") or {}
    history_revision = derived.get("history_revision")
    if (derived.get("current") is not True
            or isinstance(history_revision, bool)
            or not isinstance(history_revision, int)
            or isinstance(derived.get("derived_revision"), bool)
            or not isinstance(derived.get("derived_revision"), int)
            or derived.get("derived_revision") != history_revision):
        return _result(AUTHORITY_UNKNOWN, "derived_history_not_current",
                       draw=draw, phase=phase or None)

    path = snap.get("active_path_state")
    if not isinstance(path, dict) or path.get("state_available") is not True:
        return _result(AUTHORITY_UNKNOWN, "active_path_unavailable",
                       draw=draw, phase=phase or None)

    try:
        from ai_brain.narrative_continuity import (
            candidate_direction_authorized, recheck_narrative_continuity)
        current = recheck_narrative_continuity(snap, authored)
    except Exception as exc:  # noqa: BLE001 -- authority failure is explicit
        return _result(AUTHORITY_UNKNOWN,
                       f"narrative_continuity_unavailable:{type(exc).__name__}",
                       draw=draw, phase=phase or None)
    if (not isinstance(current, dict)
            or not isinstance(current.get("active_path"), dict)
            or current["active_path"].get("available") is not True):
        return _result(AUTHORITY_UNKNOWN, "current_narrative_continuity_unavailable",
                       draw=draw, phase=phase or None)
    control = current.get("control_state")

    if control in ("developing_transfer", "unresolved"):
        return _result(TRANSFER_UNRESOLVED,
                       "narrative_control_transfer_not_yet_confirmed",
                       draw=draw, control_state=control, phase=phase or None)

    if control == "unestablished":
        # Forming is descriptive only. Recheck Narrative Continuity first so a
        # new hypothesis cannot hide a failed incumbent. It is lawful only when
        # current available authorities also report no accepted Draw.
        if _forming(path):
            if _no_campaign_draw(draw):
                return _result(ESTABLISHING,
                               "active_path_causal_hypothesis_only",
                               draw=draw, control_state=control,
                               phase=phase or None)
            return _result(AUTHORITY_UNKNOWN,
                           "forming_hypothesis_conflicts_with_campaign_draw",
                           draw=draw, control_state=control, phase=phase or None)
        if (path.get("owner") in (None, "none") and path.get("status") == "none"
                and _no_campaign_draw(draw)):
            return _result(UNESTABLISHED, "current_authorities_report_no_campaign",
                           draw=draw, control_state=control, phase=phase or None)
        return _result(AUTHORITY_UNKNOWN,
                       "unestablished_control_conflicts_with_current_facts",
                       draw=draw, control_state=control, phase=phase or None)

    if _forming(path):
        return _result(AUTHORITY_UNKNOWN,
                       "forming_hypothesis_conflicts_with_narrative_control",
                       draw=draw, control_state=control, phase=phase or None)

    # Narrative Continuity supplies the already-authorized current owner.
    # Brain must agree with it for ACTIVE_DELIVERY / RETRACING, but Lifecycle
    # never obtains or changes direction from local tools or a missing response.
    direction = (current.get("confirmed_to") if control == "confirmed_transfer"
                 else current.get("dominant_direction"))
    direction = str(direction or "").strip().lower()
    if direction not in _DIRECTIONS:
        return _result(AUTHORITY_UNKNOWN, "narrative_direction_unavailable",
                       draw=draw, control_state=control, phase=phase or None)

    transfer_proof = current.get("transfer_proof")
    if control == "confirmed_transfer":
        if (not isinstance(transfer_proof, dict)
                or transfer_proof.get("status") != "verified"
                or current.get("confirmed_to") != direction
                or path.get("owner") != direction):
            return _result(AUTHORITY_UNKNOWN,
                           "confirmed_transfer_proof_or_direction_mismatch",
                           direction=direction, draw=draw, control_state=control,
                           phase=phase or None)
    elif control not in ("campaign_established", "incumbent_intact"):
        return _result(AUTHORITY_UNKNOWN, "narrative_control_state_unrecognized",
                       direction=direction, draw=draw, control_state=control,
                       phase=phase or None)

    expected_side = "low" if direction == "bullish" else "high"
    bearing = path.get("load_bearing_structure")
    if (path.get("owner") != direction or path.get("status") != "active"
            or not isinstance(bearing, dict)
            or bearing.get("side") != expected_side
            or bearing.get("intact") is not True
            or _finite(bearing.get("level")) is None):
        return _result(AUTHORITY_UNKNOWN,
                       "active_path_owner_or_falsifier_not_intact",
                       direction=direction, draw=draw, control_state=control,
                       phase=phase or None)

    try:
        permitted, refusal = candidate_direction_authorized(
            direction, snap, authored, current_continuity=current)
    except Exception as exc:  # noqa: BLE001
        permitted, refusal = False, f"narrative_authority_error:{type(exc).__name__}"
    if not permitted:
        return _result(AUTHORITY_UNKNOWN,
                       f"narrative_direction_not_authorized:{refusal}",
                       direction=direction, draw=draw, control_state=control,
                       phase=phase or None)

    valid, invalid_reason = _valid_draw(
        draw, snapshot=snap, direction=direction, session_id=session_id,
        contract_id=contract_id, history_revision=history_revision)
    if not valid:
        return _result(AUTHORITY_UNKNOWN, invalid_reason, direction=direction,
                       draw=draw, control_state=control, phase=phase or None)

    if draw.get("authority_status") == "PROVEN_DELIVERED":
        return _result(DESTINATION_SUBSTANTIALLY_DELIVERED,
                       "settled_campaign_objective_touch_proven",
                       direction=direction, draw=draw, control_state=control,
                       phase=phase or None)

    if brain_authority_available is not True:
        return _result(AUTHORITY_UNKNOWN, "current_brain_authority_unavailable",
                       direction=direction, draw=draw, control_state=control,
                       phase=phase or None)

    brain_direction = str(output.get("narrative_direction") or "").strip().lower()
    if brain_direction != direction:
        return _result(AUTHORITY_UNKNOWN,
                       "current_brain_direction_does_not_match_authorized_owner",
                       direction=direction, draw=draw, control_state=control,
                       phase=phase or None)
    if phase == "retracement":
        return _result(RETRACING, "validated_brain_retracement_with_intact_owner",
                       direction=direction, draw=draw, control_state=control,
                       phase=phase)
    if phase in ("continuation", "distribution"):
        return _result(ACTIVE_DELIVERY,
                       "validated_brain_delivery_with_intact_owner",
                       direction=direction, draw=draw, control_state=control,
                       phase=phase)
    if phase == "reversal" and control == "confirmed_transfer":
        # A reversal phase can establish delivery only for the already verified
        # new owner after Narrative Continuity proves transfer. All current
        # ActivePath, Draw, direction and history checks above still apply.
        return _result(ACTIVE_DELIVERY,
                       "validated_brain_reversal_after_verified_transfer",
                       direction=direction, draw=draw, control_state=control,
                       phase=phase)
    return _result(AUTHORITY_UNKNOWN,
                   "narrative_phase_does_not_establish_delivery_or_retracement",
                   direction=direction, draw=draw, control_state=control,
                   phase=phase or None)


def participation_permission(assessment: dict, direction: str) -> tuple[bool, str]:
    """Additional gate only; it can never grant an unrepresented direction."""
    result = assessment if isinstance(assessment, dict) else {}
    requested = str(direction or "").strip().lower()
    state = result.get("state")
    if (result.get("participation_permitted") is True
            and state in _PERMITTED_STATES
            and requested in _DIRECTIONS
            and result.get("authorized_direction") == requested):
        return True, "campaign_lifecycle_permitted"
    if state in _PERMITTED_STATES:
        return False, "campaign_lifecycle_direction_mismatch"
    return False, f"campaign_lifecycle_refused:{state or AUTHORITY_UNKNOWN}"
