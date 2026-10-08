"""Campaign continuity and transfer evidence shared by Brain and mechanics.

This module does not infer direction from tools. It carries the prior Brain
campaign and recognizes a transfer only from an explicit deterministic proof
family in the active-path ledger. The current producer supports a reclaimed
opposing-raid origin followed by structural progression; that is one supported
proof family, not the definition of every possible market reversal.
"""
from __future__ import annotations

import copy
import math


DIRECTIONS = ("bullish", "bearish")
OPPOSITE = {"bullish": "bearish", "bearish": "bullish"}
STATE_VERSION = 1
#: Stance-custody metadata a prior thesis carries exactly as it was recorded.
AUTHORING_METADATA = ("stance_schema_version", "recorded_at_cutoff",
                      "history_lineage", "contract_id", "market_session",
                      "process_session_id")


def _direction(value):
    value = str(value or "").strip().lower()
    return value if value in DIRECTIONS else None


def _session_key(timestamp):
    try:
        from market_state.active_path import production_session_key
        return production_session_key(timestamp)
    except Exception:  # noqa: BLE001
        return None


def _timestamp_after(left, right):
    """Compare causal event times; unparseable timestamps fail closed."""
    try:
        from datetime import datetime, timezone

        def parse(value):
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result

        return parse(left) > parse(right)
    except (TypeError, ValueError):
        return False


def _aware_datetime(value):
    """Parse an explicitly zoned timestamp; naive times are not causal proof."""
    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            return None
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _finite_price(value):
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _load_bearing(path):
    value = (path or {}).get("load_bearing_structure")
    if not isinstance(value, dict):
        return None
    level = value.get("level")
    if level is None:
        return None
    return {key: value.get(key) for key in
            ("level", "side", "timeframe", "basis", "swing_id", "registered_at",
             "occurrence_id", "source_bar_time", "settled_edge_time", "at", "intact",
             "producer_backed")}


def _owner_has_live_structure(path, direction):
    bearing = _load_bearing(path)
    expected_side = "low" if direction == "bullish" else "high"
    return bool(bearing and bearing.get("side") == expected_side
                and bearing.get("intact") is True)


def _authoritative_opposing_origin(origin, to_direction):
    """Validate a typed deterministic origin family without defining reversal.

    A new family must be separately derived from existing deterministic facts
    and registered here. Unknown or merely model-authored origins fail closed.
    """
    if not isinstance(origin, dict):
        return False
    family = origin.get("proof_family")
    expected_event = ("sell_side_raid_rejected" if to_direction == "bullish"
                      else "buy_side_raid_rejected")
    if family == "rejected_raid_reclaim":
        return (origin.get("event") == expected_event
                and origin.get("direction") == to_direction)
    return False


def _same_direction_successor_proof(path, snapshot, direction):
    """Prove a fresh same-direction ActivePath generation after a real failure.

    This is not a transfer. It requires the current public ActivePath state to
    carry a new typed raid origin, a current-generation structural confirmation,
    the exact invalidated swing identity, and intact supporting structure.
    """
    if not isinstance(path, dict) or path.get("state_available") is not True:
        return None
    if (_direction(direction) is None or path.get("owner") != direction
            or path.get("status") != "active"):
        return None

    snapshot_contract = str((snapshot or {}).get("contract_id") or "").strip()
    path_contract = str(path.get("contract_id") or "").strip()
    current_session = _session_key((snapshot or {}).get("timestamp"))
    if (not snapshot_contract or path_contract != snapshot_contract
            or not current_session or path.get("session") != current_session):
        return None

    invalidated = path.get("last_invalidated")
    if not isinstance(invalidated, dict) or invalidated.get("owner") != direction:
        return None
    expected_side = "low" if direction == "bullish" else "high"
    if (invalidated.get("side") != expected_side
            or not _finite_price(invalidated.get("level"))
            or not invalidated.get("source_tf")
            or not invalidated.get("swing_id")
            or not invalidated.get("registered_at")
            or not invalidated.get("occurrence_id")):
        return None

    origin = path.get("origin")
    if not isinstance(origin, dict):
        return None
    expected_event = ("sell_side_raid_rejected" if direction == "bullish"
                      else "buy_side_raid_rejected")
    if not (origin.get("proof_family") == "rejected_raid_reclaim"
            and origin.get("event") == expected_event
            and origin.get("direction") == direction
            and origin.get("source_tf")
            and origin.get("occurrence_id")):
        return None

    # Use the settled bar that authored each fact for causal ordering. Scan
    # observation time is checked too, but cannot substitute for source time.
    invalidated_source = _aware_datetime(invalidated.get("source_bar_time"))
    origin_source = _aware_datetime(origin.get("source_bar_time"))
    invalidated_observed = _aware_datetime(invalidated.get("at"))
    origin_observed = _aware_datetime(origin.get("at"))
    if not (invalidated_source and origin_source and origin_source > invalidated_source
            and invalidated_observed and origin_observed
            and origin_observed > invalidated_observed):
        return None

    progression = path.get("progression")
    supporting = (progression.get("supporting_timeframes")
                  if isinstance(progression, dict) else None)
    latest = (progression.get("latest_supporting_event")
              if isinstance(progression, dict) else None)
    if (not isinstance(supporting, list) or not supporting
            or not isinstance(latest, dict)
            or latest.get("direction") != direction
            or latest.get("source_tf") not in supporting
            or not latest.get("occurrence_id")
            or latest.get("occurrence_id") == origin.get("occurrence_id")
            or not _aware_datetime(latest.get("at"))):
        return None
    latest_source = _aware_datetime(latest.get("source_bar_time"))
    if not (latest_source and latest_source > origin_source
            and _aware_datetime(latest.get("at")) > origin_observed):
        return None

    bearing = _load_bearing(path)
    valid_timeframes = {"1m", "3m", "5m", "15m"}
    bearing_source = _aware_datetime((bearing or {}).get("source_bar_time"))
    if not (bearing and _finite_price(bearing.get("level"))
            and bearing.get("side") == expected_side
            and bearing.get("timeframe") in valid_timeframes
            and bearing.get("basis")
            and bearing.get("swing_id")
            and bearing.get("registered_at")
            and bearing.get("occurrence_id")
            and bearing.get("intact") is True
            and bearing.get("producer_backed") is True
            and bearing_source and bearing_source > origin_source):
        return None

    evidence = path.get("transfer_evidence")
    if not isinstance(evidence, dict):
        return None
    required_flags = ("opposing_structure_break", "load_bearing_failure",
                      "load_bearing_replaced_against_path",
                      "ambiguous_load_bearing_invalidation")
    if any(not isinstance(evidence.get(name), bool) for name in required_flags):
        return None
    if any(evidence.get(name) is True for name in required_flags):
        return None

    return {
        "status": "verified",
        "direction": direction,
        "prior_invalidation": dict(invalidated),
        "successor_origin": dict(origin),
        "current_generation_progression": dict(latest),
        "supporting_structure": bearing,
        "contract_id": snapshot_contract,
        "session": current_session,
    }


def _transfer_proof(path, from_direction, to_direction):
    """Return a verified state proof, or None when the chain is incomplete.

    `confirmed_transfer` names the market state. `proof_family` names the
    deterministic causal route currently supporting that state.
    """
    if not isinstance(path, dict) or path.get("state_available") is not True:
        return None
    if (_direction(from_direction) is None or _direction(to_direction) is None
            or from_direction == to_direction):
        return None
    if path.get("owner") != to_direction or path.get("status") != "active":
        return None
    died = path.get("last_invalidated") or {}
    origin = path.get("origin") or {}
    progression = path.get("progression") or {}
    died_at, origin_at = str(died.get("at") or ""), str(origin.get("at") or "")
    bearing = _load_bearing(path)
    expected_side = "low" if to_direction == "bullish" else "high"
    if not (
        died.get("owner") == from_direction
        and died_at and origin_at and _timestamp_after(origin_at, died_at)
        and _authoritative_opposing_origin(origin, to_direction)
        and (progression.get("supporting_timeframes")
             or progression.get("highest_confirmed"))
        and bearing and bearing.get("side") == expected_side
        and bearing.get("intact") is True
    ):
        return None
    return {
        "status": "verified",
        "from_direction": from_direction,
        "to_direction": to_direction,
        "incumbent_invalidation": died,
        "authoritative_opposing_origin": {
            "proof_family": origin.get("proof_family"),
            "event": origin.get("event"),
            "direction": origin.get("direction"),
            "at": origin.get("at"),
            "source_tf": origin.get("source_tf"),
            "occurrence_id": origin.get("occurrence_id"),
        },
        "structural_progression": progression,
        "opposing_owner": path.get("owner"),
        "load_bearing_structure": bearing,
    }


def _same_session(last, snapshot, path):
    last_key = _session_key((last or {}).get("timestamp"))
    current_key = (path or {}).get("session") or _session_key(
        (snapshot or {}).get("timestamp"))
    return bool(last_key and current_key and last_key == current_key)


def build_narrative_continuity(snapshot: dict, stance_history: dict) -> dict:
    """Describe the previous campaign against this scan's deterministic state.

    Legacy stance rows and prior-session rows are visible in stance history but
    are not treated as an authoritative incumbent because they lack the causal
    state contract or belong to a different production session.
    """
    snap = snapshot if isinstance(snapshot, dict) else {}
    hist = stance_history if isinstance(stance_history, dict) else {}
    path = snap.get("active_path_state") or {}
    last = hist.get("last") if hist.get("available") else None
    last = last if isinstance(last, dict) else None
    same_session = bool(last and last.get("narrative_state_version") == STATE_VERSION
                        and _same_session(last, snap, path))
    prior_direction = (_direction((last or {}).get("campaign_direction")
                                 or (last or {}).get("direction"))
                       if same_session else None)
    prior_falsifier_status = ((last or {}).get("thesis_falsifier_status")
                              if same_session else None)
    prior_established = bool(same_session and last.get("campaign_established") is True
                             and prior_direction)

    owner = _direction(path.get("owner"))
    path_available = path.get("state_available") is True
    status = path.get("status")
    snapshot_contract = str(snap.get("contract_id") or "").strip()
    path_contract = str(path.get("contract_id") or "").strip()
    current_session = _session_key(snap.get("timestamp"))
    path_session = str(path.get("session") or "").strip()
    path_identity_conflict = bool(
        path_available and (
            (snapshot_contract and path_contract != snapshot_contract)
            or (current_session and path_session != current_session)))
    current_falsifier = _load_bearing(path)
    last_invalidated = path.get("last_invalidated") or {}
    last_invalidated_at = str(last_invalidated.get("at") or "")
    prior_at = str((last or {}).get("timestamp") or "") if same_session else ""
    incumbent_failed = bool(
        prior_direction and last_invalidated.get("owner") == prior_direction
        and ((last_invalidated_at and prior_at
              and _timestamp_after(last_invalidated_at, prior_at))
             or prior_falsifier_status == "occurred")
    )
    proof = (_transfer_proof(path, prior_direction, owner)
             if (not path_identity_conflict
                 and (prior_established or incumbent_failed)
                 and owner and incumbent_failed) else None)
    confirmed = proof is not None

    successor = (_same_direction_successor_proof(path, snap, prior_direction)
                 if (not path_identity_conflict and incumbent_failed
                     and owner == prior_direction) else None)

    transfer_flags = ((path.get("transfer_evidence") or {})
                      if isinstance(path.get("transfer_evidence"), dict) else {})
    required_transfer_flags = ("opposing_structure_break", "load_bearing_failure",
                               "load_bearing_replaced_against_path",
                               "ambiguous_load_bearing_invalidation")
    transfer_flags_known = all(
        isinstance(transfer_flags.get(name), bool) for name in required_transfer_flags)
    substantive_challenge = any(
        transfer_flags.get(name) is True for name in required_transfer_flags)
    if path_identity_conflict:
        control_state = "unresolved"
        dominant_direction = None
    elif confirmed:
        control_state = "confirmed_transfer"
        dominant_direction = owner
    elif successor:
        # The old campaign's falsifier remains historical evidence. A new
        # causal generation in the same direction starts with its own intact
        # falsifier and does not constitute a directional transfer.
        control_state = "campaign_established"
        dominant_direction = owner
    elif prior_established:
        dominant_direction = None if incumbent_failed else prior_direction
        if not path_available:
            control_state = "unresolved"
        elif incumbent_failed or status in ("none", "invalidated") or (
                owner and owner != prior_direction):
            control_state = "developing_transfer"
        elif status == "contested" or substantive_challenge:
            control_state = "developing_transfer"
        elif not transfer_flags_known:
            control_state = "unresolved"
        elif (owner == prior_direction and status == "active"
              and _owner_has_live_structure(path, owner)):
            control_state = "incumbent_intact"
        else:
            control_state = "unresolved"
    elif prior_direction and (incumbent_failed or prior_falsifier_status == "occurred"):
        # Keep the falsified campaign as prior thesis until mechanics confirms
        # the new owner; it is no longer the current dominant direction.
        control_state = "developing_transfer"
        dominant_direction = None
    elif (path_available and owner and status == "active"
          and _owner_has_live_structure(path, owner)):
        # A mechanically established campaign can anchor a new process or a
        # legacy stance whose schema did not preserve causal continuity.
        if substantive_challenge:
            control_state = "developing_transfer"
            dominant_direction = owner
        elif not transfer_flags_known:
            control_state = "unresolved"
            dominant_direction = None
        else:
            control_state = "campaign_established"
            dominant_direction = owner
    elif (path_available and owner and status == "contested"
          and _owner_has_live_structure(path, owner)):
        control_state = "developing_transfer"
        dominant_direction = owner
    else:
        control_state = "unestablished"
        dominant_direction = None

    prior_thesis = None
    if same_session:
        prior_thesis = {
            "direction": prior_direction,
            "campaign_established": prior_established,
            "timestamp": last.get("timestamp"),
            "phase": last.get("phase"),
            "market_story": last.get("market_story"),
            "causal_reason": last.get("dominant_reasoning"),
            "invalidation_level": last.get("invalidation_level"),
            "thesis_falsifier": last.get("thesis_falsifier"),
            "active_draw": last.get("active_draw"),
            "objective_id": last.get("objective_id"),
            "falsifier_status": prior_falsifier_status,
        }
        # STAGE-3B-1A: the authoring row's own custody metadata, copied as
        # recorded. A legacy row carries None; nothing is inferred from the
        # current snapshot, so a plan recheck keeps truthful authoring lineage.
        prior_thesis.update({key: copy.deepcopy(last.get(key))
                             for key in AUTHORING_METADATA})

    falsifier_status = "unknown"
    if successor:
        falsifier_status = "not_occurred"
    elif prior_direction:
        if incumbent_failed or prior_falsifier_status == "occurred":
            falsifier_status = "occurred"
        elif prior_established and control_state in (
                "incumbent_intact", "developing_transfer", "confirmed_transfer"):
            falsifier_status = "not_occurred"

    prior_falsifier = _load_bearing((last or {}).get("thesis_falsifier") or {})
    active_falsifier = current_falsifier or prior_falsifier

    return {
        "state_version": STATE_VERSION,
        "control_state": control_state,
        "dominant_direction": dominant_direction,
        "prior_thesis": prior_thesis,
        "thesis_falsifier_status": falsifier_status,
        "prior_thesis_falsifier_status": prior_falsifier_status,
        "current_thesis_falsifier_status": falsifier_status,
        "current_thesis_falsifier": active_falsifier,
        "active_path": {
            "available": path_available,
            "record_present": isinstance(snap.get("active_path_state"), dict),
            "owner": owner,
            "status": status,
            "origin": path.get("origin"),
            "load_bearing_structure": current_falsifier,
            "progression": path.get("progression"),
            "transfer_evidence": transfer_flags,
            "last_invalidated": last_invalidated or None,
            "contract_id": path.get("contract_id"),
            "session": path.get("session"),
            "identity_conflict": path_identity_conflict,
        },
        "transfer_confirmed": confirmed,
        "transfer_proof": proof,
        "same_direction_successor_proof": successor,
        "confirmed_from": prior_direction if confirmed else None,
        "confirmed_to": owner if confirmed else None,
        "same_production_session": same_session,
        "legacy_or_prior_session_stance_ignored": bool(last and not same_session),
    }


def recheck_narrative_continuity(snapshot: dict, authored_continuity: dict) -> dict:
    """Recheck an authored decision against the latest mechanics snapshot.

    Conditional plans carry their authoring continuity. This reuses that prior
    thesis while re-evaluating current active-path truth at the trigger scan.
    """
    context = authored_continuity if isinstance(authored_continuity, dict) else {}
    prior = context.get("prior_thesis")
    if not isinstance(prior, dict) or not prior.get("direction"):
        return build_narrative_continuity(snapshot, {"available": False})
    last = {
        **prior,
        "direction": prior.get("direction"),
        "campaign_direction": prior.get("direction"),
        "campaign_established": prior.get("campaign_established") is True,
        "thesis_falsifier_status": prior.get("falsifier_status"),
        "narrative_state_version": STATE_VERSION,
    }
    return build_narrative_continuity(snapshot, {"available": True, "last": last})


def output_direction_hold(output: dict, continuity: dict) -> tuple[dict, dict | None]:
    """Keep an unconfirmed model flip from replacing the dominant campaign.

    It also converts an unestablished or developing transfer proposal to a
    stand-down. This guard cannot establish a new direction; mechanics must
    confirm a causal transfer before the Brain may propose the new owner.
    """
    out = dict(output or {})
    context = continuity if isinstance(continuity, dict) else {}
    proposed = _direction(out.get("narrative_direction"))
    dominant = _direction(context.get("dominant_direction"))
    state = context.get("control_state") or "unresolved"
    prior = context.get("prior_thesis") or {}
    action = str(out.get("current_action") or "").strip().lower()
    if (state == "unestablished" and not prior.get("direction")
            and action not in ("propose_entry", "watching")):
        # A directional read with no entry is still the Brain's market
        # judgment. Missing campaign mechanics may prevent exposure, but must
        # not erase the Brain's observational narrative.
        return out, None
    if (dominant and state == "confirmed_transfer"
            and context.get("confirmed_to") == proposed == dominant):
        return out, None

    unresolved = state in ("developing_transfer", "unresolved")
    if dominant and proposed == dominant and not unresolved:
        return out, None
    if not dominant and state not in ("developing_transfer", "unresolved",
                                      "unestablished"):
        return out, None

    falsifier = context.get("current_thesis_falsifier") or {}
    opposing = OPPOSITE[dominant] if dominant else proposed
    reason = (prior.get("causal_reason") or prior.get("market_story") or
              "prior campaign")
    held = dict(out)
    held.update({
        "narrative_direction": dominant or "conflicted",
        "narrative_phase": ("transition" if unresolved or not dominant
                            else "retracement"),
        "current_action": "stand_down",
        "allowed_direction": dominant or "none",
        "forbidden_direction": opposing if dominant else None,
        "recommended_playbook_family": "none",
        "recommended_tool_family": ["none"],
        "preferred_trade_family": "none",
        "preferred_playbooks": [],
        "preferred_tools": [],
        "active_draw": (prior.get("active_draw") or "") if dominant else "",
        "objective_id": None,
        "invalidation_id": None,
        "invalidation_level": (falsifier.get("level")
                               if falsifier.get("level") is not None
                               else prior.get("invalidation_level")),
        "market_story": ((f"The {dominant} campaign remains the dominant narrative. "
                          f"Opposing {opposing} evidence is {state.replace('_', ' ')}; "
                          "it has not established a confirmed control transfer, so "
                          "no opposing entry is authorized.") if dominant else
                         ("Directional control is developing but no new dominant "
                          "campaign is confirmed; stand down." if state in
                          ("developing_transfer", "unresolved") else
                          "No dominant campaign is established; local geometry "
                          "cannot supply direction, so stand down.")),
        "dominant_reasoning": ((f"Carry the prior {dominant} campaign: {reason}. "
                                f"Current control state is {state}; a local "
                                f"{opposing} tool or move cannot change the "
                                "dominant direction without confirmed active-path transfer.")
                               if dominant else
                               (f"Prior thesis: {reason}. Its falsifier has occurred "
                                "or control is unavailable, but a new owner is not "
                                "confirmed." if state in ("developing_transfer", "unresolved")
                                else "No established causal campaign owner is available.")),
        "thesis_health": (f"{state}; prior {dominant} campaign retained" if dominant
                          else ("developing transfer; no current owner confirmed"
                                if state in ("developing_transfer", "unresolved")
                                else "campaign unestablished")),
        "reason": ("opposing direction lacks confirmed causal control transfer"
                   if dominant else ("directional control is unresolved" if state in
                                     ("developing_transfer", "unresolved") else
                                     "dominant campaign is unestablished")),
        "warnings": list(out.get("warnings") or []) + [
            (f"narrative_direction_flip_refused:{proposed}->{dominant}"
             if dominant and proposed != dominant else
             f"narrative_entry_refused_control_state:{state}")],
        "contradiction_flags": list(out.get("contradiction_flags") or []) + [
            (f"unconfirmed_control_transfer:{proposed}"
             if dominant and proposed != dominant else
             f"control_state_not_entry_authorized:{state}")],
    })
    out_direction_source = out.get("direction_provenance")
    held["direction_provenance"] = {
        **(out_direction_source if isinstance(out_direction_source, dict) else {}),
        "source": "narrative_continuity_guard",
        "structure_derived": False,
        "retrieval_used": bool((out_direction_source or {}).get("retrieval_used")),
    }
    return held, {
        "status": ("unconfirmed_flip_held" if dominant and proposed != dominant
                   else ("entry_held_for_control_state" if state in
                         ("developing_transfer", "unresolved") else
                         "unestablished_campaign_held")),
        "proposed_direction": proposed,
        "retained_direction": dominant,
        "control_state": state,
    }


def candidate_direction_authorized(direction: str, snapshot: dict,
                                   authored_continuity: dict,
                                   current_continuity: dict = None) -> tuple[bool, str]:
    """Hard candidate boundary: only an established dominant campaign trades."""
    requested = _direction(direction)
    if requested is None:
        return False, "narrative_direction_invalid"
    current = (current_continuity if isinstance(current_continuity, dict)
               else recheck_narrative_continuity(snapshot, authored_continuity))
    state = current.get("control_state")
    if state in ("developing_transfer", "unresolved"):
        return False, "narrative_transfer_unresolved"
    if state == "confirmed_transfer":
        return (requested == current.get("confirmed_to"),
                "narrative_transfer_confirmed" if requested == current.get("confirmed_to")
                else "narrative_direction_not_current_owner")
    if state in ("incumbent_intact", "campaign_established"):
        owner = current.get("dominant_direction")
        return (requested == owner,
                "narrative_direction_authorized" if requested == owner
                else "narrative_counterflow_not_authorized")
    return False, "narrative_campaign_unestablished"
