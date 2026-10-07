"""Composed production proofs for reaffirmed reversal formation custody.

All bars below are a synthetic, internally consistent test tape. They are not
October 1 provider history. The tests use real scan, liquidity, structure,
protected-swing, occurrence-ledger, formation-custody, catalog, Brain-input,
Campaign Draw, Lifecycle, and CandidateProducer code. Model transport is the
only cognition boundary replaced; account/order/venue endpoints are never used.
"""
from __future__ import annotations

import copy
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain import production_model as PM  # noqa: E402
from broker.luna_candidate_producer import (  # noqa: E402
    CandidateProducer, NoCandidate, authorized_tool_catalog)
from broker.topstepx_candidate_freshness import CandidateSnapshot  # noqa: E402
from broker.topstepx_client import TopstepXContract  # noqa: E402
from broker.topstepx_slippage import QuoteCapture  # noqa: E402
from live_scan.production_scan_cycle import ProductionScanCycle  # noqa: E402
from market_data.occurrence_ledger import HEALTHY, OccurrenceLedger  # noqa: E402


CONTRACT = "CON.F.US.MNQ.Z26"
SESSION_ID = "REVERSAL-FOUNDATION-SYNTHETIC"
MNQ = TopstepXContract(id=CONTRACT, name="MNQZ6", description="MNQ",
                       tick_size=0.25, tick_value=0.50, active=True)

# Five-minute bars are expanded into five one-minute constituents whose OHLC
# aggregate exactly to these values. The 01:15 low is first protected; the
# 01:35 sweep establishes that live life; the 02:15 sweep revisits it while a
# newer higher structural pivot exists; the 02:20 close validates the object;
# 02:25 is the later healthy return.
RAW_5M = [
    ("00:55", 29480.00, 29490.00, 29470.00, 29475.00),
    ("01:00", 29475.00, 29480.00, 29465.00, 29468.00),
    ("01:05", 29468.00, 29470.00, 29455.00, 29460.00),
    ("01:10", 29460.00, 29462.00, 29440.00, 29445.00),
    ("01:15", 29445.00, 29450.00, 29429.75, 29434.00),
    ("01:20", 29434.00, 29450.00, 29432.00, 29440.00),
    ("01:25", 29440.00, 29455.00, 29438.00, 29450.00),
    ("01:30", 29450.00, 29465.00, 29440.00, 29445.00),
    ("01:35", 29445.00, 29455.00, 29428.75, 29445.00),
    ("01:40", 29445.00, 29450.00, 29438.00, 29442.00),
    ("01:45", 29442.00, 29448.00, 29437.00, 29444.00),
    ("01:50", 29444.00, 29450.00, 29438.00, 29445.00),
    ("01:55", 29445.00, 29450.00, 29435.00, 29440.00),
    ("02:00", 29440.00, 29448.00, 29438.00, 29444.00),
    ("02:05", 29444.00, 29450.00, 29437.00, 29445.00),
    ("02:10", 29445.00, 29452.00, 29438.00, 29446.00),
    ("02:15", 29446.00, 29460.00, 29429.00, 29445.00),
    ("02:20", 29445.00, 29500.00, 29443.00, 29490.00),
    ("02:25", 29490.00, 29495.00, 29448.00, 29456.00),
    ("02:30", 29456.00, 29465.00, 29452.00, 29458.00),
    # Allow the transient expansion classification to cool while price stays
    # in a healthy return/consolidation around the retained block.
    ("02:35", 29458.00, 29462.00, 29454.00, 29459.00),
    ("02:40", 29459.00, 29463.00, 29455.00, 29460.00),
    ("02:45", 29460.00, 29464.00, 29456.00, 29461.00),
    ("02:50", 29461.00, 29464.00, 29457.00, 29460.00),
    ("02:55", 29460.00, 29463.00, 29456.00, 29459.00),
]


def _expand_5m(row):
    hhmm, open_, high, low, close = row
    start = datetime.fromisoformat(f"2026-08-19T{hhmm}:00+00:00")
    middle = (low + close) / 2
    values = [
        (open_, high, min(open_, close), open_),
        (open_, max(open_, close), low, low),
        (low, max(low, middle), min(low, middle), middle),
        (middle, max(middle, close), min(middle, close), close),
        (close, close, close, close),
    ]
    return [{"timestamp": (start + timedelta(minutes=i)).isoformat(),
             "open": o, "high": h, "low": lo, "close": c,
             "volume": 10, "contract": CONTRACT}
            for i, (o, h, lo, c) in enumerate(values)]


TAPE_1M = [bar for group in RAW_5M for bar in _expand_5m(group)]


def _now_for(rows):
    return datetime.fromisoformat(rows[-1]["timestamp"]) + timedelta(minutes=1)


def _quote():
    return QuoteCapture(
        captured_at=datetime.now(timezone.utc), best_bid=29456.00,
        best_ask=29456.25, last_trade=29456.00,
        contract_id=CONTRACT, market_data_age_seconds=0.25)


def _cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("OCCURRENCE_LEDGER_DIR", str(tmp_path / "occurrences"))
    monkeypatch.setenv("BRAIN_ECU_MODE", "false")
    monkeypatch.setenv("AI_BRAIN_ENABLED", "false")
    monkeypatch.setenv("AI_BRAIN_LLM", "false")
    cycle = ProductionScanCycle(
        symbol="MNQ", contract_id=CONTRACT, session_id=SESSION_ID,
        quote_provider=_quote)
    # ProductionScanCycle constructed its ledger from the scoped environment.
    assert cycle.occurrence_ledger is not None
    assert cycle.occurrence_ledger.health()["status"] == HEALTHY
    return cycle


def _scan_prefix(cycle, end_index):
    """Advance the real scan exactly once for each complete 5m occurrence."""
    last = None
    for end in range(5, end_index + 1, 5):
        rows = TAPE_1M[:end]
        last = cycle.scan(rows, now=_now_for(rows), invoke_brain=False)
    return last


def _valid_model_reply(brain_input, *, action="propose_entry", direction="bullish"):
    objectives = brain_input.get("authorized_objectives") or []
    invalidations = brain_input.get("authorized_invalidations") or []
    market = brain_input.get("market") or {}
    executable = market.get("execution_price") or {}
    entry = executable.get("best_ask") if direction == "bullish" else executable.get("best_bid")
    # In ECU, this mission's pre-cognition hook intentionally attaches the
    # current derived/path/catalog facts before the call. The executable quote
    # is assembled by the existing later snapshot stage; let the mock choose
    # catalog identities relative to the settled reference when that field is
    # not part of this pre-cognition payload. CandidateProducer will still
    # revalidate against the real executable quote after the response.
    if not isinstance(entry, (int, float)):
        entry = market.get("current_price")
    profitable = [row for row in objectives
                  if isinstance(row, dict) and row.get("objective_id")
                  and isinstance(row.get("price"), (int, float))
                  and ((row["price"] > entry) if direction == "bullish"
                       else (row["price"] < entry))]
    protective = [row for row in invalidations
                  if isinstance(row, dict) and row.get("invalidation_id")
                  and isinstance(row.get("price"), (int, float))
                  and ((row["price"] < entry) if direction == "bullish"
                       else (row["price"] > entry))]
    selected_objective = next((row for row in profitable
                               if row.get("kind") == "opposing_external_liquidity"),
                              profitable[0] if profitable else None)
    stop_type = "protected_low" if direction == "bullish" else "protected_high"
    selected_stop = next((row for row in protective
                          if row.get("type") == stop_type), None)
    if selected_objective is None or selected_stop is None:
        # A failed or unresolved authority case is still a successful mocked
        # provider response: the synthetic model stands down when the current
        # producer catalogs offer no lawful geometry.
        return {
            "market_story": "The protected structure failed and current evidence does not support participation.",
            "narrative_direction": "neutral", "narrative_phase": "transition",
            "phase_confidence": 0, "allowed_direction": "none",
            "forbidden_direction": None, "current_action": "stand_down",
            "reason": "Current target or protected invalidation authority is unavailable.",
            "dominant_reasoning": (
                "Price broke the protected low, liquidity remains uncertain, "
                "delivery has no current owner, and the unresolved phase does "
                "not establish a valid target or invalidation."),
            "objective_id": None, "invalidation_id": None,
            "invalidation_level": None, "active_draw": "none",
            "recommended_playbook_family": "none",
            "recommended_tool_family": ["none"],
        }
    return {
        "market_story": "A protected low was swept and reclaimed, delivery expanded through the bearish run, and price returned into the validated bullish block.",
        "narrative_direction": direction,
        "narrative_phase": "continuation",
        "phase_confidence": 80,
        "allowed_direction": direction,
        "forbidden_direction": "bearish" if direction == "bullish" else "bullish",
        "current_action": action,
        "reason": "Current settled structure, campaign ownership, and the exact selected objective support this judgment.",
        "dominant_reasoning": (
            "Price swept and reclaimed the protected low; bullish delivery and "
            "displacement followed the liquidity raid. The continuation phase "
            "remains valid while the protected structure below is not invalidated."),
        "active_draw": "buy side liquidity above",
        "objective_id": selected_objective["objective_id"],
        "invalidation_id": selected_stop["invalidation_id"],
        "invalidation_level": selected_stop["price"],
        "recommended_playbook_family": "manipulation_to_distribution",
        "recommended_tool_family": ["po3_reversal_order_block"],
    }


def _mock_current_brain(monkeypatch, calls):
    import ai_brain.ecu as ecu
    import ai_brain.narrative_brain as narrative_brain
    from ai_brain.stance_memory import StanceMemory

    monkeypatch.setenv("BRAIN_ECU_MODE", "true")
    monkeypatch.setenv("AI_BRAIN_ENABLED", "true")
    monkeypatch.setenv("AI_BRAIN_LLM", "true")
    memory = StanceMemory(persist=False)
    monkeypatch.setattr(ecu, "_stance", lambda: memory)
    monkeypatch.setattr(narrative_brain, "persist_brain_call", lambda *a, **k: {})

    def mocked_transport(payload, repair=None):
        calls.append(copy.deepcopy(payload))
        output = _valid_model_reply(payload)
        return {"parsed": output, "ok": True, "model": PM.PRODUCTION_MODEL,
                "prompt": "mocked current Brain transport",
                "user_content": "current production input",
                "raw_response": copy.deepcopy(output), "usage": {}}

    monkeypatch.setattr(narrative_brain, "_call_llm", mocked_transport)
    return memory


def _current_return_scan(tmp_path, monkeypatch):
    cycle = _cycle(tmp_path, monkeypatch)
    _scan_prefix(cycle, len(TAPE_1M) - 5)
    calls = []
    _mock_current_brain(monkeypatch, calls)
    scan = cycle.scan(TAPE_1M, now=_now_for(TAPE_1M), invoke_brain=True)
    assert len(calls) == 1
    return cycle, scan, calls


def _produce_candidate(scan, *, snapshot=None, brain_result=None, now=None):
    producer = CandidateProducer(account_fingerprint="acct:reversal-closure",
                                 contract=MNQ)
    current_snapshot = snapshot if snapshot is not None else scan["snapshot"]
    return producer.produce(
        brain_result=(brain_result if brain_result is not None
                      else scan["brain_result"]),
        brain_input=scan["brain_input"], snapshot=current_snapshot,
        qualification=scan["qualification"],
        engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
        snapshot_id="synthetic-retained-return",
        market_data_timestamp=current_snapshot["timestamp"],
        latest_closed_bar_timestamp=current_snapshot["timestamp"],
        now=now or datetime.now(timezone.utc),
        require_campaign_lifecycle=True,
        campaign_draw=scan["campaign_draw_truth"],
        campaign_session_id=SESSION_ID)


def test_real_ecu_input_contains_retained_object_on_later_return_and_consumes_one_response(
        monkeypatch, tmp_path):
    """The exact populated catalog row survives into the current ECU call."""
    cycle = _cycle(tmp_path, monkeypatch)
    # Advance through the validated close and later return scans without
    # cognition. At this point both the sweep and displacement flags have
    # expired, while the retained formation remains available.
    before_return = _scan_prefix(cycle, len(TAPE_1M) - 5)
    before_snapshot = before_return["snapshot"]
    prior_rows = [row for row in authorized_tool_catalog(before_snapshot)
                  if row.get("tool_family") == "po3_reversal_order_block"
                  and row.get("direction") == "bullish"]
    assert len(prior_rows) == 1, prior_rows
    prior = prior_rows[0]
    assert before_snapshot["liquidity"]["5m"]["sweep_detected"] is False
    assert before_snapshot["expansion"]["5m"].get("displacement_detected") is False
    assert before_snapshot["reversal_formation_view"]["bullish"]["5m"]
    assert prior["formation_authority"]["status"] == \
        "CURRENT_PROCESS_REVALIDATED"
    assert cycle.occurrence_ledger.is_durable(prior["sweep_occurrence_id"])
    assert cycle.occurrence_ledger.is_durable(
        prior["protected_swing_occurrence_id"])

    calls = []
    _mock_current_brain(monkeypatch, calls)
    current_rows = TAPE_1M[:len(TAPE_1M)]
    scan = cycle.scan(current_rows, now=_now_for(current_rows), invoke_brain=True)
    snapshot = scan["snapshot"]
    assert len(calls) == 1
    sent_rows = [row for row in calls[0].get("authorized_tool_catalog", [])
                 if row.get("tool_family") == "po3_reversal_order_block"
                 and row.get("direction") == "bullish"]
    assert sent_rows == [prior]
    assert scan["brain_block"]["source"] == "llm", (
        scan["brain_block"].get("fallback_reason"),
        (scan["brain_block"].get("output") or {}).get("warnings"),
        (scan["brain_block"].get("output") or {}).get("reason"),
        (calls[0].get("market") or {}).get("execution_price"))
    assert ProductionScanCycle.is_sovereign(scan["brain_block"])
    assert ProductionScanCycle.is_validated_brain_result(scan["brain_result"])
    assert scan["brain_result"]["parsed"] == scan["brain_block"]["output"]
    assert snapshot["ai_brain"] is scan["brain_block"]
    assert snapshot["candidate_thesis"]["brain_block"] is scan["brain_block"]
    assert calls[0]["timestamp"] == snapshot["timestamp"]
    for key in ("history_revision", "derived_revision", "current"):
        assert calls[0]["derived_state"][key] == snapshot["derived_state"][key]
    assert calls[0]["active_path_state"] == snapshot["active_path_state"]
    assert scan["campaign_draw_truth"]["authority_status"] == "PROVEN_NOT_DELIVERED"
    assert scan["campaign_lifecycle"]["state"] == "ACTIVE_DELIVERY"
    assert snapshot["active_path_state"]["owner"] == "bullish"
    assert snapshot["active_path_state"]["status"] == "active"
    assert scan["campaign_lifecycle"]["authorized_direction"] == "bullish"

    # The same current response and exact public object proceed through the
    # real candidate boundary. No runner, token, or venue endpoint is involved.
    candidate = _produce_candidate(scan)
    assert candidate.direction == "bullish"
    assert candidate.objective.price == 29500.0
    assert candidate.invalidation_price == 29429.75
    assert candidate.extras["tool_family"] == ["po3_reversal_order_block"]


def test_bootstrap_draw_is_unknown_then_prior_draw_is_measured_before_brain(
        tmp_path, monkeypatch):
    """The first call sees no invented Draw; a later call sees delivery."""
    cycle = _cycle(tmp_path, monkeypatch)
    _scan_prefix(cycle, len(TAPE_1M) - 5)
    calls = []
    _mock_current_brain(monkeypatch, calls)

    first = cycle.scan(TAPE_1M, now=_now_for(TAPE_1M), invoke_brain=True)
    assert len(calls) == 1
    bootstrap = calls[0].get("campaign_draw_context")
    assert bootstrap["authority_status"] == "UNKNOWN"
    assert bootstrap["authority_reason"] == "no_accepted_campaign_draw"
    accepted = first["campaign_draw_truth"]
    assert accepted["authority_status"] == "PROVEN_NOT_DELIVERED", accepted
    assert len(cycle.campaign_draw_truth.audit_records) == 1
    original = cycle.campaign_draw_truth.audit_records[0]
    original_id = original["record_id"]
    original_episode = original["campaign_episode_id"]
    original_anchor = original["anchor_bar_time"]

    # A later settled candle trades through the accepted objective. The next
    # cognition must see that delivery before its model request is made.
    future = TAPE_1M + _expand_5m(
        ("03:00", 29459.0, 29505.0, 29450.0, 29460.0))
    second = cycle.scan(future, now=_now_for(future), invoke_brain=True)
    assert len(calls) == 2
    delivered_context = calls[1].get("campaign_draw_context")
    assert delivered_context["authority_status"] == "PROVEN_DELIVERED"
    assert delivered_context["record_id"] == original_id
    assert delivered_context["campaign_episode_id"] == original_episode
    assert delivered_context["anchor_bar_time"] == original_anchor
    assert delivered_context["delivery_evidence_bar"] is not None
    assert delivered_context["delivery_evidence_bar"] <= future[-1]["timestamp"]
    assert "campaign_draw_truth" not in calls[1]
    assert calls[1]["active_path_state"]["owner"] == "bullish"
    assert second["brain_block"]["output"]["narrative_direction"] == "bullish"

    # The post-response pass may accept a new objective, but it cannot rewrite
    # what the current request saw or mutate the delivered record's identity.
    assert calls[1]["campaign_draw_context"] == delivered_context
    assert cycle.campaign_draw_truth.audit_records[0]["record_id"] == original_id
    assert cycle.campaign_draw_truth.audit_records[0]["campaign_episode_id"] == original_episode
    assert cycle.campaign_draw_truth.audit_records[0]["anchor_bar_time"] == original_anchor
    assert second["snapshot"]["campaign_draw_context"] == delivered_context
    assert second["snapshot"]["campaign_draw_truth"]["record_id"] == \
        second["campaign_draw_truth"]["record_id"]


def test_non_ecu_input_receives_pre_cognition_draw_and_rebuild_is_brainless(
        tmp_path, monkeypatch):
    """Non-ECU sees the same pre-measurement; no-Brain scans call no model."""
    cycle = _cycle(tmp_path, monkeypatch)
    _scan_prefix(cycle, len(TAPE_1M) - 5)
    calls = []
    _mock_current_brain(monkeypatch, calls)
    first = cycle.scan(TAPE_1M, now=_now_for(TAPE_1M), invoke_brain=True)
    assert len(calls) == 1

    monkeypatch.setenv("BRAIN_ECU_MODE", "false")
    future = TAPE_1M + _expand_5m(
        ("03:00", 29459.0, 29505.0, 29450.0, 29460.0))
    second = cycle.scan(future, now=_now_for(future), invoke_brain=True)
    assert len(calls) == 2
    assert calls[1]["campaign_draw_context"]["authority_status"] == \
        "PROVEN_DELIVERED"
    assert calls[1]["campaign_draw_context"]["record_id"] == \
        first["campaign_draw_truth"]["record_id"]
    assert "campaign_draw_truth" not in calls[1]
    assert second["brain_block"]["source"] == "llm"
    assert second["brain_input"]["campaign_draw_context"] == \
        calls[1]["campaign_draw_context"]
    assert second["brain_result"]["parsed"] == second["brain_block"]["output"]

    before_calls = len(calls)
    revision = cycle._history.revision
    cycle._rebuild_derived_state(future, revision)
    assert len(calls) == before_calls

    third = future + _expand_5m(
        ("03:05", 29460.0, 29470.0, 29455.0, 29465.0))
    no_brain = cycle.scan(third, now=_now_for(third), invoke_brain=False)
    assert len(calls) == before_calls
    assert no_brain["brain_block"]["source"] == "preauthorized_plan_trigger"


def test_history_revision_retires_old_draw_before_current_brain_request(
        tmp_path, monkeypatch):
    """A revised accepted anchor is unavailable to the next cognition."""
    cycle = _cycle(tmp_path, monkeypatch)
    _scan_prefix(cycle, len(TAPE_1M) - 5)
    calls = []
    _mock_current_brain(monkeypatch, calls)
    first = cycle.scan(TAPE_1M, now=_now_for(TAPE_1M), invoke_brain=True)
    old_draw = first["campaign_draw_truth"]
    assert old_draw["authority_status"] == "PROVEN_NOT_DELIVERED"
    assert len(calls) == 1

    revised = copy.deepcopy(TAPE_1M)
    revised[0]["close"] += 0.25
    revised[0]["high"] = max(revised[0]["high"], revised[0]["close"])
    revised[0]["low"] = min(revised[0]["low"], revised[0]["close"])
    scan = cycle.scan(revised, now=_now_for(revised), invoke_brain=True)

    assert len(calls) == 2
    assert scan["snapshot"]["derived_state"]["history_revision"] == 1
    context = calls[1]["campaign_draw_context"]
    assert context["authority_status"] == "UNKNOWN"
    assert context.get("record_id") != old_draw["record_id"]
    old_record = next(row for row in cycle.campaign_draw_truth.audit_records
                      if row["record_id"] == old_draw["record_id"])
    assert old_record["superseded"] is True
    assert old_record["superseded_reason"] == \
        "canonical_history_revision_changed"


def test_real_production_sweep_lifetime_and_catalog_survive_later_sweep(
        tmp_path, monkeypatch):
    """No manually minted IDs: production scan emitters build the row."""
    cycle = _cycle(tmp_path, monkeypatch)
    scan = _scan_prefix(cycle, len(TAPE_1M))
    snapshot = scan["snapshot"]
    row = next(row for row in authorized_tool_catalog(snapshot)
               if row.get("tool_family") == "po3_reversal_order_block"
               and row.get("direction") == "bullish")
    assert row["invalidation_level"] == 29429.75
    assert row["protected_swing_registered_at"] == \
        "2026-08-19T01:39:00+00:00"
    assert snapshot["liquidity"]["5m"].get("sweep_detected") is False
    assert snapshot["expansion"]["5m"].get("displacement_detected") is False
    live = cycle.swing_tracker.protected_lows["5m"]
    assert live["registered_at"] == "2026-08-19T01:39:00+00:00"
    assert live["level"] == 29429.75
    sweep_id = row["sweep_occurrence_id"]
    assert cycle.occurrence_ledger.is_durable(sweep_id)
    assert cycle.occurrence_ledger.get(sweep_id)["swept_level"] == 29429.75
    registration_id = row["protected_swing_occurrence_id"]
    assert cycle.occurrence_ledger.is_durable(registration_id)
    assert cycle.occurrence_ledger.get(registration_id)["event_type"] == \
        "PROTECTED_SWING_REGISTERED"
    assert row["formation_authority"]["anchor_identity"]["registered_at"] == \
        live["registered_at"]


@pytest.mark.parametrize("invalid_edge", [
    "older_event", "forming_event", "missing_fact", "malformed_fact",
    "contradictory_fact",
])
def test_real_lifetime_cannot_be_reaffirmed_without_current_settled_edge(
        tmp_path, monkeypatch, invalid_edge):
    """The producer's timeframe view rejects stale or absent sweep edges."""
    cycle, scan, _ = _current_return_scan(tmp_path, monkeypatch)
    tracker = copy.deepcopy(cycle.swing_tracker)
    snapshot = copy.deepcopy(scan["snapshot"])
    record = copy.deepcopy(tracker.protected_lows["5m"])
    candles = snapshot["timeframes"]["5m"]["recent_candles"]
    latest = candles[-1]
    fact = {
        "source_tf": "5m",
        "event_time": latest["timestamp"],
        "sweep_direction": "below_low",
        "swept_level": record["level"],
        "reclaimed": True,
        "source_bars": [latest["timestamp"]],
    }
    liq = {"sweep_detected": True, "reclaim_detected": True,
           "sweep_direction": "below_low", "sweep_fact": fact}
    if invalid_edge == "older_event":
        prior = candles[-2]
        fact["event_time"] = prior["timestamp"]
        fact["source_bars"] = [prior["timestamp"]]
    elif invalid_edge == "forming_event":
        latest["temporal_status"] = "forming"
    elif invalid_edge == "malformed_fact":
        fact["source_bars"] = "not-a-source-list"
    elif invalid_edge == "contradictory_fact":
        fact["source_tf"] = "1m"
    else:
        liq.pop("sweep_fact")
        snapshot["structure"]["5m"]["last_swing_low"] = record["level"]
    snapshot["liquidity"]["5m"] = liq

    prior_lineage_count = len(tracker.low_lineage["5m"])
    state = tracker.update(snapshot)
    current = state["by_timeframe"]["lows"]["5m"]
    assert current["registered_at"] == record["registered_at"]
    assert current["level"] == record["level"]
    assert len(tracker.low_lineage["5m"]) == prior_lineage_count


def _real_occupied_snapshot(tmp_path, monkeypatch, direction):
    cycle = _cycle(tmp_path, monkeypatch)
    history = list(TAPE_1M)
    if direction == "bearish":
        history = [{**bar,
                    "open": 60000.0 - bar["open"],
                    "high": 60000.0 - bar["low"],
                    "low": 60000.0 - bar["high"],
                    "close": 60000.0 - bar["close"]}
                   for bar in history]
    last = None
    for end in range(5, len(history) + 1, 5):
        rows = history[:end]
        last = cycle.scan(rows, now=_now_for(rows), invoke_brain=False)
    side = "low" if direction == "bullish" else "high"
    registry = (cycle.swing_tracker.protected_lows if side == "low"
                else cycle.swing_tracker.protected_highs)
    assert "5m" in registry
    return cycle, copy.deepcopy(last["snapshot"]), side


@pytest.mark.parametrize("direction", ["bullish", "bearish"])
def test_defense_only_unknown_lifetime_evidence_cannot_replace_occupied_slot(
        tmp_path, monkeypatch, direction):
    """Malformed injected evidence freezes registration, not close invalidation."""
    cycle, base_snapshot, side = _real_occupied_snapshot(
        tmp_path, monkeypatch, direction)
    tracker = cycle.swing_tracker
    registry = tracker.protected_lows if side == "low" else tracker.protected_highs
    original = copy.deepcopy(registry["5m"])
    scope_key = (side, "5m")
    original_scope = tracker._slot_scopes[scope_key]
    lineage = (tracker.low_lineage if side == "low"
               else tracker.high_lineage)["5m"]
    lineage_count = len(lineage)
    candles = base_snapshot["timeframes"]["5m"]["recent_candles"]
    settled = [row for row in candles if row.get("temporal_status") == "settled"]
    event_time = settled[-1]["timestamp"]
    previous_time = settled[-2]["timestamp"]
    future_time = (datetime.fromisoformat(event_time) + timedelta(minutes=5)).isoformat()
    direction_token = "below_low" if side == "low" else "above_high"
    target = original["level"] + (10.0 if side == "low" else -10.0)

    # Every case begins with a real occupied producer lifetime. Only the
    # current edge payload/registry scope is corrupted: these are defense-only
    # tests, not evidence that production emitters make these shapes.
    for defect in ("missing_scope", "contradictory_scope", "missing_fact",
                   "malformed_fact", "nonterminal_source", "unordered_source"):
        snapshot = copy.deepcopy(base_snapshot)
        candidate_tracker = copy.deepcopy(tracker)
        slot_scope = candidate_tracker._slot_scopes
        if defect == "missing_scope":
            slot_scope.pop(scope_key)
        elif defect == "contradictory_scope":
            slot_scope[scope_key] = ("CONTRADICTORY", "OTHER-SESSION")

        source_bars = [previous_time, event_time]
        fact = {"source_tf": "5m", "event_time": event_time,
                "sweep_direction": direction_token, "swept_level": target,
                "reclaimed": True, "reclaimed_at": event_time,
                "source_bars": source_bars}
        if defect == "missing_fact":
            fact_value = None
        elif defect == "malformed_fact":
            fact["swept_level"] = float("nan")
            fact_value = fact
        elif defect == "nonterminal_source":
            fact["source_bars"] = [previous_time, event_time, future_time]
            fact_value = fact
        elif defect == "unordered_source":
            fact["source_bars"] = [event_time, previous_time]
            fact_value = fact
        else:
            fact_value = fact

        block = {"sweep_detected": True, "reclaim_detected": True,
                 "sweep_direction": direction_token}
        if fact_value is not None:
            block["sweep_fact"] = fact_value
        snapshot["liquidity"]["5m"] = block
        snapshot["structure"]["5m"][
            "last_swing_low" if side == "low" else "last_swing_high"] = target

        state = candidate_tracker.update(snapshot)
        current = state["by_timeframe"]["lows" if side == "low" else "highs"]["5m"]
        assert current == original, (direction, defect, current, original)
        assert candidate_tracker._slot_scopes.get(scope_key) == slot_scope.get(scope_key)
        assert len((candidate_tracker.low_lineage if side == "low"
                    else candidate_tracker.high_lineage)["5m"]) == lineage_count


@pytest.mark.parametrize("direction", ["bullish", "bearish"])
def test_unknown_registration_does_not_suppress_real_close_invalidation(
        tmp_path, monkeypatch, direction):
    cycle, snapshot, side = _real_occupied_snapshot(tmp_path, monkeypatch, direction)
    tracker = copy.deepcopy(cycle.swing_tracker)
    registry = tracker.protected_lows if side == "low" else tracker.protected_highs
    original = copy.deepcopy(registry["5m"])
    candles = snapshot["timeframes"]["5m"]["recent_candles"]
    close = original["level"] - 0.25 if side == "low" else original["level"] + 0.25
    candles[-1]["close"] = close
    snapshot["liquidity"]["5m"] = {
        "sweep_detected": True, "reclaim_detected": True,
        "sweep_direction": "below_low" if side == "low" else "above_high"}
    snapshot["structure"]["5m"][
        "last_swing_low" if side == "low" else "last_swing_high"] = (
            original["level"] + 10 if side == "low" else original["level"] - 10)
    state = tracker.update(snapshot)
    assert "5m" not in state["by_timeframe"]["lows" if side == "low" else "highs"]


def test_real_htf_resweep_is_stable_across_five_minute_scan_occurrences(
        tmp_path, monkeypatch):
    cycle = _cycle(tmp_path, monkeypatch)
    _scan_prefix(cycle, 80)  # last observed bar is 02:14; resweep settles at 02:15
    side = "low"
    original = copy.deepcopy(cycle.swing_tracker.protected_lows["5m"])
    observed = []
    for end in range(85, 90):
        rows = TAPE_1M[:end]
        result = cycle.scan(rows, now=_now_for(rows), invoke_brain=False)
        snapshot = result["snapshot"]
        fact = snapshot["liquidity"]["5m"].get("sweep_fact") or {}
        assert fact.get("event_time") == "2026-08-19T02:15:00+00:00"
        observed.append(snapshot["timeframes"]["5m"]["recent_candles"][-1][
            "temporal_status"])
        state = cycle.swing_tracker.state()
        assert state["by_timeframe"]["lows"]["5m"] == original
        protected_events = [row for row in cycle.last_occurrence_writes
                            if row.get("event_type") in {
                                "PROTECTED_SWING_REGISTERED",
                                "PROTECTED_SWING_REPLACED"}]
        assert protected_events == []
    assert observed[0] == "settled"
    assert observed[1:5] == ["forming"] * 4
    from market_data.object_identity import market_object_id
    from market_data.sweep_occurrence import LIQUIDITY_SWEEP
    physical_id = market_object_id(
        LIQUIDITY_SWEEP, contract=CONTRACT, timeframe="5m",
        instant="2026-08-19T02:15:00+00:00")
    assert sum(row.get("occurrence_id") == physical_id
               for row in cycle.occurrence_ledger.occurrences(
                   event_type=LIQUIDITY_SWEEP, source_tf="5m")) == 1

    for end in range(90, len(TAPE_1M) - 5 + 1, 5):
        rows = TAPE_1M[:end]
        cycle.scan(rows, now=_now_for(rows), invoke_brain=False)

    # Continue to the established healthy return and prove the retained row
    # still reaches ECU and the real CandidateProducer after the cadence window.
    calls = []
    _mock_current_brain(monkeypatch, calls)
    scan = cycle.scan(TAPE_1M, now=_now_for(TAPE_1M), invoke_brain=True)
    assert len(calls) == 1
    assert any(row.get("tool_family") == "po3_reversal_order_block"
               for row in calls[0].get("authorized_tool_catalog", []))
    assert isinstance(_produce_candidate(scan), CandidateSnapshot)


@pytest.mark.parametrize("direction", ["bullish", "bearish"])
def test_real_newer_protected_pivot_replaces_incumbent_lifetime(
        tmp_path, monkeypatch, direction):
    """A confirmed new pivot remains replaceable after reaffirmation repair."""
    cycle = _cycle(tmp_path, monkeypatch)
    base_history = list(TAPE_1M)
    if direction == "bearish":
        base_history = [{**bar,
                         "open": 60000.0 - bar["open"],
                         "high": 60000.0 - bar["low"],
                         "low": 60000.0 - bar["high"],
                         "close": 60000.0 - bar["close"]}
                        for bar in base_history]
    for end in range(5, len(base_history) + 1, 5):
        rows = base_history[:end]
        cycle.scan(rows, now=_now_for(rows), invoke_brain=False)
    side = "low" if direction == "bullish" else "high"
    registry = cycle.swing_tracker.protected_lows if side == "low" \
        else cycle.swing_tracker.protected_highs
    incumbent = copy.deepcopy(registry["5m"])
    history = list(base_history)
    appended = [
        ("03:00", 29460, 29465, 29445, 29455),
        ("03:05", 29455, 29460, 29440, 29450),
        ("03:10", 29450, 29470, 29448, 29460),
        ("03:15", 29460, 29468, 29452, 29461),
        ("03:20", 29461, 29466, 29455, 29462),
        ("03:25", 29462, 29470, 29458, 29465),
        # Sweep the newly confirmed 29440 low while preserving the old 29429.75
        # lifetime. The capped high avoids a simultaneous buy-side sweep.
        ("03:30", 29460, 29464, 29438, 29448),
    ]
    last_scan = None
    for hhmm, open_, high, low, close in appended:
        if direction == "bearish":
            mirror = lambda value: 60000.0 - value
            open_, high, low, close = (
                mirror(open_), mirror(low), mirror(high), mirror(close))
        history.extend(_expand_5m((hhmm, open_, high, low, close)))
        last_scan = cycle.scan(history, now=_now_for(history), invoke_brain=False)

    snapshot = last_scan["snapshot"]
    fact = snapshot["liquidity"]["5m"].get("sweep_fact") or {}
    assert fact.get("sweep_direction") == (
        "below_low" if direction == "bullish" else "above_high"), fact
    assert fact.get("swept_level") == (29440.0 if direction == "bullish" else 30560.0)
    replacement = registry["5m"]
    assert replacement["level"] != incumbent["level"]
    assert replacement["registered_at"] != incumbent["registered_at"]
    assert replacement["registered_at"] == snapshot["timestamp"]


def test_changed_anchor_lifetime_cannot_reuse_retained_formation(
        tmp_path, monkeypatch):
    _, scan, _ = _current_return_scan(tmp_path, monkeypatch)
    changed = copy.deepcopy(scan["snapshot"])
    changed["protected_swings"]["by_timeframe"]["lows"]["5m"][
        "registered_at"] = "2026-08-19T02:00:00+00:00"
    rows = [row for row in authorized_tool_catalog(changed)
            if row.get("tool_family") == "po3_reversal_order_block"]
    assert rows == []
    with pytest.raises(NoCandidate) as refused:
        _produce_candidate(scan, snapshot=changed)
    assert refused.value.reason == "tool_not_detected"


def test_wrong_campaign_direction_and_invalid_action_refuse_at_candidate_boundary(
        tmp_path, monkeypatch):
    _, scan, _ = _current_return_scan(tmp_path, monkeypatch)
    wrong_direction = copy.deepcopy(scan["brain_result"])
    wrong_direction["parsed"]["narrative_direction"] = "bearish"
    wrong_direction["parsed"]["allowed_direction"] = "bearish"
    wrong_direction["parsed"]["forbidden_direction"] = "bullish"
    with pytest.raises(NoCandidate) as direction_refusal:
        _produce_candidate(scan, brain_result=wrong_direction)
    assert direction_refusal.value.reason == "campaign_lifecycle_refused"

    invalid_action = copy.deepcopy(scan["brain_result"])
    invalid_action["parsed"]["current_action"] = "pending confirmation"
    with pytest.raises(NoCandidate) as action_refusal:
        _produce_candidate(scan, brain_result=invalid_action)
    assert action_refusal.value.reason == "brain_action_invalid"


def test_revised_confirmation_bar_is_absent_from_current_ecu_input(
        tmp_path, monkeypatch):
    cycle = _cycle(tmp_path, monkeypatch)
    _scan_prefix(cycle, len(TAPE_1M) - 5)
    calls = []
    _mock_current_brain(monkeypatch, calls)
    revised = copy.deepcopy(TAPE_1M)
    # The final 1m constituent of the 02:20 5m validation candle carries its
    # close. Rewriting it below the existing confirmation reference changes
    # canonical overlap and must revoke the retained formation before cognition.
    proving_bar = revised[17 * 5 + 4]
    proving_bar.update(open=29490.0, high=29490.0, low=29455.0, close=29455.0)
    scan = cycle.scan(revised, now=_now_for(revised), invoke_brain=True)
    assert len(calls) == 1
    assert scan["snapshot"]["derived_state"]["history_revision"] == 1
    assert not any(row.get("tool_family") == "po3_reversal_order_block"
                   for row in calls[0].get("authorized_tool_catalog", []))
    assert not any(row.get("tool_family") == "po3_reversal_order_block"
                   for row in authorized_tool_catalog(scan["snapshot"]))
    with pytest.raises(NoCandidate) as refused:
        _produce_candidate(scan)
    assert refused.value.reason in {
        "campaign_lifecycle_refused", "tool_not_detected"}


def test_failed_anchor_and_unresolved_transfer_refuse_after_real_scan(
        tmp_path, monkeypatch):
    cycle, scan, calls = _current_return_scan(tmp_path, monkeypatch)
    # A new settled 5m close below the live protected low is a real invalidation
    # event. It must remove the object and keep the new scan out of participation.
    broken_bar = _expand_5m(("03:00", 29459.0, 29460.0, 29420.0, 29425.0))
    failed_history = TAPE_1M + broken_bar
    refused_scan = cycle.scan(
        failed_history, now=_now_for(failed_history), invoke_brain=True)
    assert len(calls) == 2  # one current Brain request for each normal scan
    assert not any(row.get("tool_family") == "po3_reversal_order_block"
                   for row in calls[-1].get("authorized_tool_catalog", []))
    assert cycle.swing_tracker.protected_lows.get("5m") is None
    assert refused_scan["snapshot"]["active_path_state"]["last_invalidated"]
    assert refused_scan["campaign_lifecycle"]["state"] == "TRANSFER_UNRESOLVED"
    with pytest.raises(NoCandidate) as refused:
        _produce_candidate(refused_scan)
    assert refused.value.reason == "campaign_lifecycle_refused"
