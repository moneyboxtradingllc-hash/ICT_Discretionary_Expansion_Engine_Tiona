"""S4G -- SAME-DIRECTION SUCCESSOR PROOF: TIMEFRAME TYPE/DOMAIN BOUNDARY.

`_same_direction_successor_proof` checked the load-bearing timeframe with a set
lookup. A list or dict there is unhashable, so a malformed published timeframe
raised TypeError out of `build_narrative_continuity` instead of withholding the
proof (Codex S4F audit, reproduced on 7a9ef80, both directions). The same
helper accepted ANY truthy invalidation or origin timeframe, and any latest
confirmation timeframe that also appeared in `supporting_timeframes`.

Boundary rule: every timeframe the proof reads -- last_invalidated.source_tf,
origin.source_tf, progression.supporting_timeframes and
latest_supporting_event.source_tf, load_bearing_structure.timeframe -- must be
one of the producer's four timeframe strings. Anything else withholds the
proof without raising; nothing is coerced into a supported timeframe.

The accepted successor is the existing ActivePath/extractor unit producer path:
`test_active_path_state`'s successor test, captured as it runs. Each case is
then published as its own scan through the same fixture ownership that test
uses at every scan, so the baseline and every variant read the same authentic
UNBOUND campaign scope and differ only in the evidence under test. Every
injected value below is DEFENSE-ONLY: it exercises the consumer boundary, it is
not a claim that a natural market tape publishes it, and it is not natural
P2/P3 proof.
"""
from __future__ import annotations

import copy

import pytest

import ai_brain.narrative_continuity as NC
import test_active_path_state as A
from ai_brain.narrative_continuity import (build_narrative_continuity,
                                           candidate_direction_authorized,
                                           output_direction_hold,
                                           recheck_narrative_continuity)
from test_campaign_scope_binding import authenticate_unbound_fixture

DIRECTIONS = (("bullish", "low", "below_low"), ("bearish", "high", "above_high"))
#: The Draw/campaign session the successor test authors every scan under.
SESSION = "causal-successor-session"
CUSTODY_SURFACES = ("campaign_scope_custody", "campaign_scope_custody_shadow",
                    "campaign_premise_catalog", "campaign_premise_shadow")
_CAPTURED = {}


def _capture(direction, side, raid):
    """Inputs and result of the first successor the producer path accepts."""
    if direction not in _CAPTURED:
        captured = []
        original = NC.build_narrative_continuity

        def observe(snapshot, history):
            continuity = original(snapshot, history)
            if continuity.get("same_direction_successor_proof") and not captured:
                captured.append(copy.deepcopy((snapshot, history, continuity)))
            return continuity

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(NC, "build_narrative_continuity", observe)
            A.test_real_continuity_accepts_fresh_same_direction_successor_then_rechecks(
                direction, side, raid, "continuation", "ACTIVE_DELIVERY")
        assert captured, "the producer successor must actually be accepted"
        _CAPTURED[direction] = captured[0]
    return copy.deepcopy(_CAPTURED[direction])


@pytest.fixture(params=DIRECTIONS, ids=[d[0] for d in DIRECTIONS])
def successor(request):
    direction, side, raid = request.param
    snapshot, history, accepted = _capture(direction, side, raid)
    return direction, snapshot, history, accepted


def _path(snapshot):
    return snapshot["active_path_state"]


def _with(snapshot, mutate):
    """This scan as published with `mutate` applied to its ActivePath state."""
    scan = {key: copy.deepcopy(value) for key, value in snapshot.items()
            if key not in CUSTODY_SURFACES}
    mutate(_path(scan))
    authenticate_unbound_fixture(scan, session_id=SESSION)
    return scan


def _authority(continuity):
    keys = ("control_state", "dominant_direction", "transfer_confirmed",
            "transfer_proof", "same_direction_successor_proof", "confirmed_from",
            "confirmed_to", "campaign_premise", "current_thesis_falsifier",
            "thesis_falsifier_status", "prior_thesis_falsifier_status",
            "current_thesis_falsifier_status", "active_leg_failure_status",
            "prior_active_leg_failure_status")
    return {k: copy.deepcopy(continuity.get(k)) for k in keys}


def _entry(direction):
    return {"narrative_direction": direction, "current_action": "propose_entry"}


def _assert_accepted(direction, snapshot, history):
    continuity = build_narrative_continuity(snapshot, history)
    proof = continuity["same_direction_successor_proof"]
    assert proof is not None and proof["status"] == "verified"
    assert proof["direction"] == direction
    assert continuity["control_state"] == "campaign_established"
    assert continuity["dominant_direction"] == direction
    assert continuity["active_leg_failure_status"] == "not_occurred"
    assert candidate_direction_authorized(direction, snapshot, continuity) == (
        True, "narrative_direction_authorized")
    held, guard = output_direction_hold(_entry(direction), continuity)
    assert held["current_action"] == "propose_entry"
    assert guard is None
    return continuity


def _assert_refused(direction, snapshot, history, sealed):
    """Withheld proof and the existing held/refused behaviour, never an error."""
    continuity = build_narrative_continuity(snapshot, history)
    assert continuity["same_direction_successor_proof"] is None
    assert continuity["control_state"] == "developing_transfer"
    assert continuity["dominant_direction"] is None
    assert continuity["transfer_confirmed"] is False
    assert continuity["active_leg_failure_status"] == "occurred"
    assert continuity["campaign_premise"]["status"] == "UNKNOWN"
    assert continuity["current_thesis_falsifier"] is None
    for requested in ("bullish", "bearish"):
        assert candidate_direction_authorized(requested, snapshot, continuity) == (
            False, "narrative_transfer_unresolved")
    held, guard = output_direction_hold(_entry(direction), continuity)
    assert held["current_action"] == "stand_down"
    assert held["narrative_direction"] == "conflicted"
    assert guard["status"] == "entry_held_for_control_state"
    # A plan sealed on the accepted successor rechecks to the same refusal.
    rechecked = recheck_narrative_continuity(snapshot, sealed)
    assert rechecked["same_direction_successor_proof"] is None
    assert rechecked["control_state"] == "developing_transfer"
    assert candidate_direction_authorized(direction, snapshot, sealed) == (
        False, "narrative_transfer_unresolved")
    return continuity, held, guard


def _reference_refusal(direction, snapshot, history, sealed):
    """An existing non-timeframe negative: the producer did not back the leg."""
    reference = _with(snapshot, lambda p: p["load_bearing_structure"].update(
        producer_backed=False))
    return _assert_refused(direction, reference, history, sealed)


def _set(*keys):
    def assign(value):
        def mutate(path):
            target = path
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = value
        return mutate
    return assign


def _drop(*keys):
    def mutate(path):
        target = path
        for key in keys[:-1]:
            target = target[key]
        target.pop(keys[-1])
    return mutate


def _paired_latest(value):
    """The latest confirmation and its supporting list both carry `value`."""
    def mutate(path):
        progression = path["progression"]
        progression["latest_supporting_event"]["source_tf"] = value
        progression["supporting_timeframes"] = [copy.deepcopy(value)]
    return mutate


def _extra_supporting(value):
    def mutate(path):
        path["progression"]["supporting_timeframes"].append(value)
    return mutate


_BEARING = _set("load_bearing_structure", "timeframe")
_INVALIDATION = _set("last_invalidated", "source_tf")
_ORIGIN = _set("origin", "source_tf")

# DEFENSE-ONLY malformed timeframe evidence. Codex's reproduced cases first.
MALFORMED = {
    "bearing_list": _BEARING(["5m"]),
    "bearing_dict": _BEARING({"timeframe": "5m"}),
    "bearing_tuple_holding_list": _BEARING(("5m", ["5m"])),
    "bearing_unknown_string": _BEARING("4h"),
    "bearing_case_variant": _BEARING("5M"),
    "bearing_padded": _BEARING(" 5m"),
    "bearing_empty": _BEARING(""),
    "bearing_null": _BEARING(None),
    "bearing_missing": _drop("load_bearing_structure", "timeframe"),
    "bearing_bool": _BEARING(True),
    "bearing_int": _BEARING(5),
    "bearing_float": _BEARING(5.0),
    "invalidation_list": _INVALIDATION(["5m"]),
    "invalidation_dict": _INVALIDATION({"timeframe": "5m"}),
    "invalidation_unknown_string": _INVALIDATION("4h"),
    "invalidation_bool": _INVALIDATION(True),
    "invalidation_int": _INVALIDATION(5),
    "invalidation_null": _INVALIDATION(None),
    "origin_list": _ORIGIN(["1m"]),
    "origin_dict": _ORIGIN({"timeframe": "1m"}),
    "origin_unknown_string": _ORIGIN("4h"),
    "origin_bool": _ORIGIN(True),
    "origin_int": _ORIGIN(1),
    "origin_null": _ORIGIN(None),
    "latest_list_alone": _set("progression", "latest_supporting_event",
                              "source_tf")(["1m"]),
    "latest_and_supporting_list": _paired_latest(["1m"]),
    "latest_and_supporting_dict": _paired_latest({"timeframe": "1m"}),
    "latest_and_supporting_unknown_string": _paired_latest("4h"),
    "latest_and_supporting_null": _paired_latest(None),
    "latest_and_supporting_bool": _paired_latest(True),
    "latest_and_supporting_int": _paired_latest(1),
    "supporting_extra_list": _extra_supporting(["5m"]),
    "supporting_extra_unknown_string": _extra_supporting("4h"),
}

# Valid producer evidence that must still prove the successor.
VALID = {
    "baseline": lambda path: None,
    "bearing_1m": _BEARING("1m"),
    "bearing_3m": _BEARING("3m"),
    "bearing_15m": _BEARING("15m"),
    "bearing_integer_level": lambda path: path["load_bearing_structure"].update(
        level=int(path["load_bearing_structure"]["level"])),
    "invalidation_15m": _INVALIDATION("15m"),
    "origin_5m": _ORIGIN("5m"),
    "supporting_all_four": _set("progression", "supporting_timeframes")(
        ["1m", "3m", "5m", "15m"]),
    "latest_3m_supported": lambda path: (
        path["progression"]["latest_supporting_event"].update(source_tf="3m"),
        path["progression"].update(supporting_timeframes=["1m", "3m"])),
}

# Existing non-timeframe negatives, unchanged by S4G.
UNCHANGED_NEGATIVES = {
    "wrong_contract": lambda path: path.update(contract_id="CON.OTHER"),
    "wrong_session": lambda path: path.update(session="other-session"),
    "origin_not_after_invalidation": lambda path: path["origin"].update(
        source_bar_time=path["last_invalidated"]["source_bar_time"]),
    "bearing_oversized_integer_level": lambda path: path[
        "load_bearing_structure"].update(level=10 ** 1000),
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_malformed_successor_timeframe_is_withheld_without_raising(successor, case):
    direction, snapshot, history, sealed = successor
    _assert_accepted(direction, _with(snapshot, VALID["baseline"]), history)
    malformed = _with(snapshot, MALFORMED[case])
    continuity, held, guard = _assert_refused(direction, malformed, history, sealed)
    reference, reference_held, reference_guard = _reference_refusal(
        direction, snapshot, history, sealed)
    assert _authority(continuity) == _authority(reference)
    assert held == reference_held
    assert guard == reference_guard


@pytest.mark.parametrize("case", sorted(VALID))
def test_valid_producer_timeframes_still_prove_the_successor(successor, case):
    direction, snapshot, history, _ = successor
    valid = _with(snapshot, VALID[case])
    continuity = _assert_accepted(direction, valid, history)
    proof = continuity["same_direction_successor_proof"]
    path = _path(valid)
    assert proof["supporting_structure"]["timeframe"] == path[
        "load_bearing_structure"]["timeframe"]
    assert proof["prior_invalidation"] == path["last_invalidated"]
    assert proof["successor_origin"] == path["origin"]
    assert proof["current_generation_progression"] == path["progression"][
        "latest_supporting_event"]


@pytest.mark.parametrize("case", sorted(UNCHANGED_NEGATIVES))
def test_existing_successor_negatives_still_refuse(successor, case):
    direction, snapshot, history, _ = successor
    negative = _with(snapshot, UNCHANGED_NEGATIVES[case])
    continuity = build_narrative_continuity(negative, history)
    assert continuity["same_direction_successor_proof"] is None
    assert continuity["control_state"] in ("developing_transfer", "unresolved")
    assert candidate_direction_authorized(direction, negative, continuity)[0] is False


def test_legacy_stance_row_is_not_a_successor_incumbent(successor):
    direction, snapshot, history, _ = successor
    legacy = copy.deepcopy(history)
    legacy["last"].pop("narrative_state_version")
    continuity = build_narrative_continuity(_with(snapshot, VALID["baseline"]), legacy)
    assert continuity["same_direction_successor_proof"] is None
    assert continuity["legacy_or_prior_session_stance_ignored"] is True
    malformed = _with(snapshot, MALFORMED["bearing_dict"])
    assert build_narrative_continuity(malformed, legacy)[
        "same_direction_successor_proof"] is None


@pytest.mark.parametrize("value", [{"5m"}, frozenset({"5m"})], ids=["set", "frozenset"])
def test_unpublishable_timeframe_containers_are_withheld_by_the_helper(successor, value):
    """A set cannot be published (the custody fact seal is JSON), so this
    DEFENSE-ONLY in-memory value is checked at the proof helper itself."""
    direction, snapshot, _, _ = successor
    scan = _with(snapshot, VALID["baseline"])
    assert NC._same_direction_successor_proof(
        _path(scan), scan, direction)["status"] == "verified"
    path = copy.deepcopy(_path(scan))
    path["load_bearing_structure"]["timeframe"] = value
    assert NC._same_direction_successor_proof(path, scan, direction) is None
