"""Process-local authority for one Brain-authored conditional plan.

The original Brain phase is authoring evidence. This object never represents a
current Brain response; it binds a watching judgment to current causal facts
which must survive until its exact quote trigger.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
import json


AUTHORITY_BASIS = "PREAUTHORIZED_PLAN_JUDGMENT"
PHASE_UNAVAILABLE_REASON = "current_brain_authority_unavailable"
_SEAL = object()


@dataclass(frozen=True, init=False)
class ConditionalPlanAuthority:
    _payload_json: str
    _scope: object
    _seal: object

    def __init__(self, payload_json, scope, seal):
        if seal is not _SEAL:
            raise ValueError("conditional plan authority is process-minted only")
        object.__setattr__(self, "_payload_json", payload_json)
        object.__setattr__(self, "_scope", scope)
        object.__setattr__(self, "_seal", seal)

    def payload(self) -> dict:
        return json.loads(self._payload_json)


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def matches_authoring_output(*, authority, scope, parsed) -> bool:
    """Check detached convenience fields against the sealed Brain output."""
    if (not isinstance(authority, ConditionalPlanAuthority)
            or authority._seal is not _SEAL or authority._scope is not scope):
        return False
    try:
        return _json(authority.payload().get("parsed")) == _json(parsed)
    except Exception:  # noqa: BLE001
        return False


def matches_authoring_result(*, authority, scope, brain_result) -> bool:
    """Validate the plan's converted result while ignoring mutable side facts.

    The sealed result supplies the authored Narrative Continuity at trigger.
    The shallow audit copy may share mutable continuity details with later
    snapshots, so only its typed judgment and conversion identity are matched.
    """
    if (not isinstance(authority, ConditionalPlanAuthority)
            or authority._seal is not _SEAL or authority._scope is not scope):
        return False
    try:
        from live_scan.production_scan_cycle import ProductionScanCycle
        bound = authority.payload()
        expected = bound.get("brain_result") or {}
        actual = brain_result if isinstance(brain_result, dict) else {}
        return (
            ProductionScanCycle.is_validated_brain_result(expected)
            and ProductionScanCycle.is_validated_brain_result(actual)
            and _json(actual.get("parsed")) == _json(bound.get("parsed"))
            and all(actual.get(key) == expected.get(key)
                    for key in ("ok", "source", "model", "fallback_reason"))
        )
    except Exception:  # noqa: BLE001
        return False


def _finite(value):
    try:
        if isinstance(value, bool):
            return None
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _public_path(snapshot):
    path = (snapshot or {}).get("active_path_state")
    if not isinstance(path, dict) or path.get("state_available") is not True:
        return None
    origin = path.get("origin")
    bearing = path.get("load_bearing_structure")
    if not isinstance(origin, dict) or not isinstance(bearing, dict):
        return None
    fields = ("direction", "proof_family", "occurrence_id", "at", "source_tf")
    bearing_fields = ("side", "level", "timeframe", "basis", "swing_id", "at")
    if any(not origin.get(key) for key in fields):
        return None
    if any(not bearing.get(key) for key in bearing_fields):
        return None
    if bearing.get("intact") is not True or _finite(bearing.get("level")) is None:
        return None
    return {
        "owner": path.get("owner"), "status": path.get("status"),
        "session": path.get("session"),
        "origin": {key: origin.get(key) for key in fields},
        "load_bearing": {**{key: bearing.get(key) for key in bearing_fields},
                         "intact": True},
        "last_invalidated": _invalidation(path.get("last_invalidated")),
        "transfer_evidence": path.get("transfer_evidence"),
    }


def _invalidation(value):
    if not isinstance(value, dict):
        return None
    return {key: value.get(key) for key in ("owner", "at", "level")}


def _draw_identity(draw):
    if not isinstance(draw, dict):
        return None
    keys = ("process_authority", "superseded", "authority_status",
            "campaign_episode_id", "session_id", "market_session", "contract_id",
            "campaign_direction", "objective_identity", "objective_kind",
            "objective_price", "anchor_bar_time", "anchor_bar_close",
            "anchor_price_basis", "history_revision", "history_complete",
            "coverage_status", "progress_authoritative",
            "active_path_last_invalidated")
    result = {key: draw.get(key) for key in keys}
    if (draw.get("process_authority") != "CURRENT_PROCESS_ONLY"
            or draw.get("superseded") is not False
            or draw.get("authority_status") != "PROVEN_NOT_DELIVERED"
            or not draw.get("campaign_episode_id")
            or not draw.get("objective_identity")
            or not draw.get("objective_kind")
            or _finite(draw.get("objective_price")) is None
            or not draw.get("anchor_bar_time")
            or _finite(draw.get("anchor_bar_close")) is None
            or draw.get("anchor_price_basis") != "settled_1m_source_bar_close"
            or draw.get("history_complete") is not True
            or draw.get("coverage_status") != "COMPLETE"
            or draw.get("progress_authoritative") is not True):
        return None
    return result


def _transfer_binding(proof, *, contract_id=None, session=None):
    """Stable causal identity for the existing verified transfer proof."""
    if not isinstance(proof, dict) or proof.get("status") != "verified":
        return None
    invalidation = proof.get("incumbent_invalidation") or {}
    origin = proof.get("authoritative_opposing_origin") or {}
    # ActivePath publishes the invalidated anchor's timeframe as `source_tf`.
    # Bind that producer field verbatim; a parallel `timeframe` alias would be
    # synthetic and would reject every real transfer record.
    required_invalidation = ("owner", "at", "level", "source_tf", "swing_id",
                            "registered_at", "occurrence_id")
    required_origin = ("proof_family", "event", "direction", "at", "source_tf",
                       "occurrence_id")
    if (any(invalidation.get(key) is None for key in required_invalidation)
            or any(origin.get(key) is None for key in required_origin)
            or proof.get("from_direction") not in ("bullish", "bearish")
            or proof.get("to_direction") not in ("bullish", "bearish")
            or proof.get("from_direction") == proof.get("to_direction")
            or not contract_id or not session):
        return None
    return {
        "from_direction": proof.get("from_direction"),
        "to_direction": proof.get("to_direction"),
        # Narrative's proof is a compact causal tuple. Contract/session are
        # public ActivePath lineage, so bind them from that same current path
        # rather than pretending they are fields emitted by the proof.
        "contract_id": contract_id,
        "session": session,
        "incumbent_invalidation": {key: invalidation.get(key)
                                   for key in required_invalidation},
        "authoritative_opposing_origin": {key: origin.get(key)
                                          for key in required_origin},
    }


def _session_date(now):
    from broker import topstepx_session_authorization as SA
    return now.astimezone(ZoneInfo(SA.PRODUCTION_WINDOW_TZ)).strftime("%Y%m%d")


def _aware_datetime(value):
    return (isinstance(value, datetime) and value.tzinfo is not None
            and value.utcoffset() is not None)


def _verify_authorization(authorization, *, account_fingerprint, contract_id, now):
    if authorization is None:
        return False, "session_authorization_unavailable"
    try:
        authorization.verify(account_fingerprint=account_fingerprint,
                             contract_id=contract_id,
                             session_date=_session_date(now), now=now)
        return True, None
    except Exception as exc:  # noqa: BLE001 -- authorization fails closed
        return False, f"session_authorization_invalid:{type(exc).__name__}"


def capture(*, scope, candidate, scan, brain_block, brain_result,
            authorization, process_session_id, now):
    """Mint only from the real, validated plan-publication boundary."""
    from ai_brain.production_model import brain_contract_fingerprint
    from live_scan.production_scan_cycle import ProductionScanCycle
    from market_data.campaign_lifecycle import evaluate_campaign_lifecycle

    snapshot = (scan or {}).get("snapshot") or {}
    output = (brain_block or {}).get("output")
    parsed = (brain_result or {}).get("parsed")
    lifecycle = snapshot.get("campaign_lifecycle")
    draw = scan.get("campaign_draw_authority",
                    scan.get("campaign_draw_truth"))
    extras = candidate.extras or {}
    phase = str((parsed or {}).get("narrative_phase") or "").strip().lower()
    direction = str((parsed or {}).get("narrative_direction") or "").strip().lower()
    authored_continuity = ((brain_result or {}).get("narrative_continuity")
                           or (brain_block or {}).get("narrative_continuity") or {})
    transfer_proof = authored_continuity.get("transfer_proof")
    path_id = _public_path(snapshot)
    transfer_binding = _transfer_binding(
        transfer_proof, contract_id=candidate.contract_id,
        session=(path_id or {}).get("session"))
    reversal_transfer = bool(
        phase == "reversal"
        and authored_continuity.get("control_state") == "confirmed_transfer"
        and authored_continuity.get("confirmed_from") == (transfer_proof or {}).get(
            "from_direction")
        and authored_continuity.get("confirmed_to") == direction
        and (transfer_proof or {}).get("to_direction") == direction
        and transfer_binding is not None)
    if (not _aware_datetime(now)
            or not ProductionScanCycle.is_sovereign(brain_block)
            or not ProductionScanCycle.is_validated_brain_result(brain_result)
            or _json(output) != _json(parsed)
            or (parsed or {}).get("current_action") != "watching"
            or direction not in ("bullish", "bearish")
            or phase not in ("continuation", "distribution", "retracement", "reversal")
            or (phase == "reversal" and not reversal_transfer)
            or not isinstance(lifecycle, dict)
            or lifecycle.get("state") not in ("ACTIVE_DELIVERY", "RETRACING")
            or lifecycle.get("participation_permitted") is not True
            or lifecycle.get("authorized_direction") != direction
            or lifecycle.get("narrative_phase") != phase
            or lifecycle.get("campaign_draw_status") != "PROVEN_NOT_DELIVERED"):
        raise ValueError("conditional_plan_authoring_authority_invalid")
    draw_id = _draw_identity(draw)
    reproduced_lifecycle = evaluate_campaign_lifecycle(
        snapshot=snapshot, brain_output=parsed,
        narrative_continuity=authored_continuity, campaign_draw=draw,
        session_id=process_session_id, contract_id=candidate.contract_id,
        brain_authority_available=True)
    if _json(lifecycle) != _json(reproduced_lifecycle):
        raise ValueError("conditional_plan_lifecycle_not_reproduced")
    derived = snapshot.get("derived_state") or {}
    revision = derived.get("history_revision")
    if (draw_id is None or path_id is None or derived.get("current") is not True
            or isinstance(revision, bool) or not isinstance(revision, int)
            or derived.get("derived_revision") != revision
            or draw_id.get("history_revision") != revision
            or path_id.get("owner") != direction or path_id.get("status") != "active"
            or draw_id.get("session_id") != process_session_id
            or draw_id.get("contract_id") != candidate.contract_id
            or draw_id.get("campaign_direction") != direction
            or path_id.get("session") != draw_id.get("market_session")
            or (reversal_transfer and _transfer_binding({
                "status": "verified",
                "from_direction": transfer_binding.get("from_direction"),
                "to_direction": transfer_binding.get("to_direction"),
                "incumbent_invalidation": draw_id.get("active_path_last_invalidated"),
                "authoritative_opposing_origin": transfer_binding.get(
                    "authoritative_opposing_origin"),
            }, contract_id=draw_id.get("contract_id"),
                session=path_id.get("session")) != transfer_binding)
            or lifecycle.get("campaign_episode_id") != draw_id.get("campaign_episode_id")
            or lifecycle.get("objective_identity") != draw_id.get("objective_identity")
            or candidate.direction != direction
            or candidate.snapshot_id != scan.get("snapshot_id")
            or candidate.extras.get("brain_response_digest") is None
            or not extras.get("activation_zone")
            or not extras.get("structural_invalidation")
            or not candidate.objective.identity):
        raise ValueError("conditional_plan_lineage_incomplete")
    auth_ok, auth_reason = _verify_authorization(
        authorization, account_fingerprint=candidate.account_fingerprint,
        contract_id=candidate.contract_id, now=now)
    if not auth_ok:
        raise ValueError(auth_reason)
    from broker.luna_candidate_producer import _digest
    if candidate.extras.get("brain_response_digest") != _digest(parsed):
        raise ValueError("conditional_plan_brain_response_digest_mismatch")
    auth_session = getattr(authorization, "session_id", None)
    auth_fingerprint = getattr(authorization, "authorization_fingerprint", None)
    if (not auth_session or auth_session != process_session_id
            or not auth_fingerprint):
        raise ValueError("conditional_plan_session_authorization_lineage_invalid")
    expires = extras.get("plan_expires_at")
    expiry = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
    if expiry.tzinfo is None or now >= expiry.astimezone(now.tzinfo):
        raise ValueError("conditional_plan_expiry_invalid")
    zone = extras.get("activation_zone") or {}
    invalidation = extras.get("structural_invalidation") or {}
    objective = candidate.objective.evidence()
    if (zone.get("direction") != direction
            or not zone.get("occurrence_id")
            or _finite(zone.get("low")) is None
            or _finite(zone.get("high")) is None
            or _finite(zone.get("low")) > _finite(zone.get("high"))
            or extras.get("selected_tool_occurrence_id") != zone.get("occurrence_id")
            or not invalidation.get("structure_identity")
            or _finite(candidate.invalidation_price) is None
            or not objective.get("identity") or not objective.get("kind")
            or _finite(objective.get("price")) is None):
        raise ValueError("conditional_plan_selected_geometry_incomplete")
    payload = {
        "schema_version": 1, "authority_basis": AUTHORITY_BASIS,
        "plan_id": candidate.candidate_id,
        "candidate_fingerprint": candidate.fingerprint(),
        "brain_response_digest": extras.get("brain_response_digest"),
        "parsed": parsed, "brain_result": brain_result,
        "authoring_snapshot_id": scan.get("snapshot_id"),
        "authoring_phase": phase, "direction": direction,
        "authoring_lifecycle": lifecycle,
        "created_at": now.isoformat(), "expires_at": expiry.isoformat(),
        "contract_id": candidate.contract_id,
        "account_fingerprint": candidate.account_fingerprint,
        "process_session_id": process_session_id,
        "authorization_session_id": auth_session,
        "authorization_fingerprint": auth_fingerprint,
        "brain_fingerprint": brain_contract_fingerprint(),
        "draw": draw_id, "active_path": path_id,
        "authoring_transfer_proof": transfer_binding,
        "history_revision": revision,
        "activation_zone": extras.get("activation_zone"),
        "tool_family": extras.get("tool_family"),
        "occurrence_id": extras.get("selected_tool_occurrence_id"),
        "playbook": extras.get("playbook"),
        "invalidation": invalidation,
        "invalidation_price": candidate.invalidation_price,
        "objective": objective,
        "transfer_evidence": extras.get("conditional_plan_transfer_evidence"),
    }
    return ConditionalPlanAuthority(_json(payload), scope, _SEAL)


def validate(*, authority, scope, candidate, candidate_at_trigger,
             brain_result, snapshot, brain_input, draw, lifecycle,
             authorization, process_session_id, contract_id, session_id,
             trigger_event, trigger_snapshot_id=None, now):
    """Revalidate exact plan premises. Return (allowed, reason, evidence)."""
    from ai_brain.narrative_continuity import (
        candidate_direction_authorized, recheck_narrative_continuity)
    from ai_brain.production_model import brain_contract_fingerprint
    from broker.topstepx_candidate_freshness import CandidateSnapshot
    from live_scan.production_scan_cycle import ProductionScanCycle
    from market_data.campaign_lifecycle import evaluate_campaign_lifecycle

    def refuse(reason):
        return False, reason, {"authority_basis": AUTHORITY_BASIS,
                                "state": "REFUSED", "reason": reason}
    if (not isinstance(authority, ConditionalPlanAuthority)
            or authority._seal is not _SEAL or authority._scope is not scope):
        return refuse("conditional_plan_authority_missing_or_unbound")
    try:
        bound = authority.payload()
    except Exception:  # noqa: BLE001
        return refuse("conditional_plan_authority_malformed")
    if not isinstance(candidate, CandidateSnapshot):
        return refuse("conditional_plan_candidate_invalid")
    event = trigger_event if isinstance(trigger_event, dict) else {}
    if (event.get("plan_id") != bound.get("plan_id")
            or event.get("occurrence_id") != bound.get("occurrence_id")
            or event.get("reason") not in {
                "conditional_plan_zone_reached",
                "conditional_plan_armed_inside"}):
        return refuse("conditional_plan_trigger_event_invalid")
    if (not _aware_datetime(now)
            or bound.get("authority_basis") != AUTHORITY_BASIS
            or bound.get("plan_id") != candidate.candidate_id
            or bound.get("candidate_fingerprint") != candidate.fingerprint()
            or bound.get("contract_id") != candidate.contract_id
            or bound.get("contract_id") != contract_id
            or bound.get("account_fingerprint") != candidate.account_fingerprint
            or bound.get("account_fingerprint") != getattr(authorization, "account_fingerprint", None)
            or bound.get("process_session_id") != process_session_id
            or bound.get("process_session_id") != session_id
            or bound.get("authorization_session_id") != getattr(authorization, "session_id", None)
            or bound.get("authorization_fingerprint") != getattr(authorization, "authorization_fingerprint", None)
            or bound.get("brain_fingerprint") != brain_contract_fingerprint()):
        return refuse("conditional_plan_environment_lineage_changed")
    try:
        expiry = datetime.fromisoformat(str(bound.get("expires_at")).replace("Z", "+00:00"))
        if expiry.tzinfo is None or now >= expiry.astimezone(now.tzinfo):
            return refuse("conditional_plan_expired")
    except Exception:  # noqa: BLE001
        return refuse("conditional_plan_expiry_invalid")
    if (not ProductionScanCycle.is_validated_brain_result(brain_result)
            or _json((brain_result or {}).get("parsed")) != _json(bound.get("parsed"))
            or _json(brain_result) != _json(bound.get("brain_result"))
            or (bound.get("parsed") or {}).get("current_action") != "watching"
            or (brain_result or {}).get("parsed", {}).get("narrative_direction") != bound.get("direction")
            or (brain_result or {}).get("parsed", {}).get("narrative_phase") != bound.get("authoring_phase")):
        return refuse("conditional_plan_brain_judgment_changed")
    auth_ok, auth_reason = _verify_authorization(
        authorization, account_fingerprint=bound.get("account_fingerprint"),
        contract_id=contract_id, now=now)
    if not auth_ok:
        return refuse(auth_reason)
    snap = snapshot if isinstance(snapshot, dict) else {}
    derived = snap.get("derived_state") or {}
    revision = derived.get("history_revision")
    if (derived.get("current") is not True
            or isinstance(revision, bool) or not isinstance(revision, int)
            or revision != bound.get("history_revision")
            or derived.get("derived_revision") != revision):
        return refuse("conditional_plan_history_changed_or_unavailable")
    draw_id = _draw_identity(draw)
    if draw_id is None or draw_id != bound.get("draw"):
        return refuse("conditional_plan_campaign_draw_changed_or_unavailable")
    current_path = _public_path(snap)
    if current_path is None or current_path != bound.get("active_path"):
        return refuse("conditional_plan_active_path_lineage_changed")
    direction = bound.get("direction")
    if current_path.get("owner") != direction or current_path.get("status") != "active":
        return refuse("conditional_plan_owner_not_intact")
    from broker.topstepx_execution_price import executable_price
    market = (brain_input or {}).get("market") or {}
    executable = executable_price(market.get("execution_price") or {}, direction)
    zone = bound.get("activation_zone") or {}
    low, high = _finite(zone.get("low")), _finite(zone.get("high"))
    if (executable is None or low is None or high is None
            or not low <= float(executable) <= high):
        return refuse("conditional_plan_fresh_quote_outside_authorized_zone")
    authored_continuity = ((bound.get("brain_result") or {}).get(
        "narrative_continuity") or {})
    reproduced_lifecycle = evaluate_campaign_lifecycle(
        snapshot=snap, brain_output={},
        narrative_continuity=authored_continuity, campaign_draw=draw,
        session_id=session_id, contract_id=contract_id,
        brain_authority_available=False)
    if _json(reproduced_lifecycle) != _json(lifecycle):
        return refuse("conditional_plan_lifecycle_not_reproduced")
    if (not isinstance(lifecycle, dict)
            or lifecycle.get("state") != "AUTHORITY_UNKNOWN"
            or lifecycle.get("reason") != PHASE_UNAVAILABLE_REASON
            or lifecycle.get("narrative_phase") is not None
            or lifecycle.get("campaign_episode_id") != draw_id.get("campaign_episode_id")
            or lifecycle.get("campaign_draw_status") != "PROVEN_NOT_DELIVERED"):
        return refuse("conditional_plan_lifecycle_refusal_not_phase_only")
    try:
        continuity = recheck_narrative_continuity(snap, authored_continuity)
        permitted, reason = candidate_direction_authorized(
            direction, snap, authored_continuity,
            current_continuity=continuity)
    except Exception as exc:  # noqa: BLE001
        return refuse(f"conditional_plan_narrative_recheck_failed:{type(exc).__name__}")
    if not permitted:
        return refuse(f"conditional_plan_narrative_not_authorized:{reason}")
    if bound.get("authoring_phase") == "reversal":
        from ai_brain.narrative_continuity import _transfer_proof
        bound_transfer = bound.get("authoring_transfer_proof")
        if (not isinstance(bound_transfer, dict)
                or continuity.get("control_state") not in (
                    "confirmed_transfer", "campaign_established", "incumbent_intact")
                or (continuity.get("confirmed_to") if continuity.get("control_state")
                    == "confirmed_transfer" else continuity.get("dominant_direction"))
                    != direction):
            return refuse("conditional_plan_transfer_context_not_current")
        current_proof = _transfer_proof(
            snap.get("active_path_state") or {},
            bound_transfer.get("from_direction"),
            bound_transfer.get("to_direction"))
        current_binding = _transfer_binding(
            current_proof, contract_id=contract_id,
            session=current_path.get("session"))
        if current_binding is None or current_binding != bound_transfer:
            return refuse("conditional_plan_verified_transfer_lineage_changed")
        if _transfer_binding({
                "status": "verified",
                "from_direction": bound_transfer.get("from_direction"),
                "to_direction": bound_transfer.get("to_direction"),
                "incumbent_invalidation": (draw_id or {}).get(
                    "active_path_last_invalidated"),
                "authoritative_opposing_origin": bound_transfer.get(
                    "authoritative_opposing_origin"),
            }, contract_id=(draw_id or {}).get("contract_id"),
                session=current_path.get("session")) != bound_transfer:
            return refuse("conditional_plan_draw_not_bound_to_transfer")
    elif continuity.get("control_state") not in (
            "campaign_established", "incumbent_intact"):
        return refuse(f"conditional_plan_narrative_not_authorized:{reason}")
    extras = candidate.extras or {}
    if (_json(extras.get("activation_zone")) != _json(bound.get("activation_zone"))
            or _json(extras.get("tool_family")) != _json(bound.get("tool_family"))
            or extras.get("selected_tool_occurrence_id") != bound.get("occurrence_id")
            or extras.get("playbook") != bound.get("playbook")
            or extras.get("brain_response_digest") != bound.get("brain_response_digest")
            or candidate.invalidation_price != bound.get("invalidation_price")
            or _json((extras.get("structural_invalidation") or {}).get("structure_identity"))
                != _json((bound.get("invalidation") or {}).get("structure_identity"))
            or _json(candidate.objective.evidence()) != _json(bound.get("objective"))):
        return refuse("conditional_plan_selected_geometry_changed")
    if candidate_at_trigger is not None:
        fresh = candidate_at_trigger
        fresh_extras = fresh.extras or {}
        if (not trigger_snapshot_id
                or fresh.snapshot_id != trigger_snapshot_id
                or fresh.contract_id != candidate.contract_id
                or fresh.account_fingerprint != candidate.account_fingerprint
                or fresh.direction != candidate.direction
                or fresh_extras.get("playbook") != bound.get("playbook")
                or _json(fresh_extras.get("tool_family")) != _json(bound.get("tool_family"))
                or fresh_extras.get("selected_tool_occurrence_id") != bound.get("occurrence_id")
                or _json(fresh_extras.get("selected_tool_zone")) != _json({
                    "low": (bound.get("activation_zone") or {}).get("low"),
                    "high": (bound.get("activation_zone") or {}).get("high")})
                or fresh.invalidation_price != bound.get("invalidation_price")
                or fresh.objective.identity != (bound.get("objective") or {}).get("identity")
                or fresh.objective.kind != (bound.get("objective") or {}).get("kind")
                or fresh.objective.price != (bound.get("objective") or {}).get("price")):
            return refuse("conditional_plan_fresh_candidate_changed")
    evidence = {"authority_basis": AUTHORITY_BASIS, "state": "VERIFIED",
                "reason": "preauthorized_judgment_survives_current_causal_checks",
                "authoring_snapshot_id": bound.get("authoring_snapshot_id"),
                "authoring_phase": bound.get("authoring_phase"),
                "authoring_lifecycle": {
                    "state": (bound.get("authoring_lifecycle") or {}).get("state"),
                    "reason": (bound.get("authoring_lifecycle") or {}).get("reason"),
                },
                "trigger_snapshot_id": (candidate_at_trigger.snapshot_id
                                         if candidate_at_trigger is not None else None),
                "campaign_episode_id": draw_id.get("campaign_episode_id"),
                "history_revision": revision,
                "current_lifecycle": {
                    "state": lifecycle.get("state"),
                    "reason": lifecycle.get("reason"),
                    "narrative_phase": lifecycle.get("narrative_phase"),
                },
                "authoring_transfer_proof": bound.get("authoring_transfer_proof")}
    return True, None, evidence


def validate_final_quote(*, authority, scope, candidate, contract_id,
                        executable_price, now):
    """Bind the final priced entry to the original conditional plan zone.

    This is called after the production quote has passed freshness and venue
    quality checks, immediately before the final candidate freshness/economics
    checks and token minting. Candidate evidence is checked against the sealed
    authoring record; it cannot supply or widen the zone.
    """
    def refuse(reason):
        return False, reason

    from broker.topstepx_candidate_freshness import CandidateSnapshot

    if (not isinstance(authority, ConditionalPlanAuthority)
            or authority._seal is not _SEAL or authority._scope is not scope):
        return refuse("conditional_plan_final_quote_authority_missing_or_unbound")
    try:
        bound = authority.payload()
    except Exception:  # noqa: BLE001
        return refuse("conditional_plan_final_quote_authority_malformed")
    if not isinstance(candidate, CandidateSnapshot):
        return refuse("conditional_plan_final_quote_candidate_invalid")
    if not _aware_datetime(now):
        return refuse("conditional_plan_final_quote_time_invalid")
    try:
        expiry = datetime.fromisoformat(str(bound.get("expires_at")).replace(
            "Z", "+00:00"))
        if expiry.tzinfo is None or now >= expiry.astimezone(now.tzinfo):
            return refuse("conditional_plan_expired_before_final_quote")
    except Exception:  # noqa: BLE001
        return refuse("conditional_plan_final_quote_expiry_invalid")

    zone = bound.get("activation_zone")
    low = _finite(zone.get("low")) if isinstance(zone, dict) else None
    high = _finite(zone.get("high")) if isinstance(zone, dict) else None
    price = _finite(executable_price)
    extras = candidate.extras if isinstance(candidate.extras, dict) else {}
    authority_evidence = extras.get("conditional_plan_authority")
    current_lifecycle = extras.get("current_lifecycle_assessment")
    invalidation = extras.get("structural_invalidation")
    objective = candidate.objective.evidence()
    expected_zone = {"low": (zone or {}).get("low"),
                     "high": (zone or {}).get("high")} if isinstance(zone, dict) else None
    if (not bound.get("plan_id") or candidate.direction != bound.get("direction")
            or candidate.contract_id != contract_id
            or extras.get("conditional_plan_id") != bound.get("plan_id")
            or extras.get("selected_tool_occurrence_id") != bound.get("occurrence_id")
            or not isinstance(zone, dict)
            or zone.get("direction") != bound.get("direction")
            or zone.get("occurrence_id") != bound.get("occurrence_id")
            or _json(extras.get("selected_tool_zone")) != _json(expected_zone)
            or _json(extras.get("tool_family")) != _json(bound.get("tool_family"))
            or extras.get("playbook") != bound.get("playbook")
            or candidate.invalidation_price != bound.get("invalidation_price")
            or not isinstance(invalidation, dict)
            or _json(invalidation.get("structure_identity"))
                != _json((bound.get("invalidation") or {}).get("structure_identity"))
            or objective.get("identity")
                != (bound.get("objective") or {}).get("identity")
            or objective.get("kind") != (bound.get("objective") or {}).get("kind")
            or objective.get("price") != (bound.get("objective") or {}).get("price")
            or not isinstance(authority_evidence, dict)
            or authority_evidence.get("authority_basis") != AUTHORITY_BASIS
            or authority_evidence.get("state") != "VERIFIED"
            or authority_evidence.get("authoring_snapshot_id")
                != bound.get("authoring_snapshot_id")
            or authority_evidence.get("authoring_phase") != bound.get("authoring_phase")
            or authority_evidence.get("campaign_episode_id")
                != (bound.get("draw") or {}).get("campaign_episode_id")
            or authority_evidence.get("history_revision") != bound.get("history_revision")
            or authority_evidence.get("trigger_snapshot_id") != candidate.snapshot_id
            or not isinstance(authority_evidence.get("current_lifecycle"), dict)
            or authority_evidence["current_lifecycle"].get("state") != "AUTHORITY_UNKNOWN"
            or authority_evidence["current_lifecycle"].get("reason")
                != PHASE_UNAVAILABLE_REASON
            or authority_evidence["current_lifecycle"].get("narrative_phase") is not None
            or not isinstance(current_lifecycle, dict)
            or current_lifecycle.get("state") != "AUTHORITY_UNKNOWN"
            or current_lifecycle.get("reason") != PHASE_UNAVAILABLE_REASON
            or low is None or high is None or low > high or price is None):
        return refuse("conditional_plan_final_quote_lineage_invalid")
    if not low <= price <= high:
        return refuse("conditional_plan_final_quote_outside_authorized_zone")
    if not isinstance(bound.get("brain_fingerprint"), str) \
            or not bound.get("brain_fingerprint"):
        return refuse("conditional_plan_brain_fingerprint_missing")
    try:
        from ai_brain.production_model import brain_contract_fingerprint
        if brain_contract_fingerprint() != bound.get("brain_fingerprint"):
            return refuse("conditional_plan_brain_fingerprint_changed")
    except Exception:  # noqa: BLE001
        return refuse("conditional_plan_brain_fingerprint_unavailable")
    return True, None
