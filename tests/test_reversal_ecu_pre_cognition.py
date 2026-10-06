"""Production ECU must see current scan facts before its one Brain call.

The market tape below is a deterministic test fixture, not October 1 provider
history. Model transport and account/order endpoints remain unreachable.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from live_scan.production_scan_cycle import ProductionScanCycle  # noqa: E402
from market_data.occurrence_ledger import HEALTHY, OccurrenceLedger  # noqa: E402
from test_runtime_continuity_recovery import tape  # noqa: E402


def test_real_production_scan_attaches_current_facts_before_one_ecu_call(
        monkeypatch, tmp_path):
    import ai_brain.ecu as ecu
    import ai_brain.narrative_brain as narrative_brain
    from ai_brain.brain_input import build_brain_input

    observed = []

    class TestStance:
        def history_summary(self):
            return {"available": False}

        def record(self, *args, **kwargs):
            return None

    def inspect_input(snapshot, history):
        from broker.luna_candidate_producer import authorized_tool_catalog
        catalog = authorized_tool_catalog(snapshot)
        result = build_brain_input(snapshot, history)
        observed.append({"snapshot_object": id(snapshot), "input": result,
                         "catalog": catalog})
        return result

    monkeypatch.setenv("BRAIN_ECU_MODE", "true")
    monkeypatch.setenv("AI_BRAIN_ENABLED", "true")
    monkeypatch.setenv("AI_BRAIN_LLM", "false")
    monkeypatch.setattr(ecu, "_stance", lambda: TestStance())
    monkeypatch.setattr(narrative_brain, "build_brain_input", inspect_input)
    monkeypatch.setattr(narrative_brain, "persist_brain_call", lambda *a, **k: {})
    cycle = ProductionScanCycle(
        symbol="MNQ", contract_id="CON.F.US.MNQ.Z26", session_id="audit")
    cycle.occurrence_ledger = OccurrenceLedger(
        cycle.contract_id, directory=str(tmp_path))
    cycle.occurrence_ledger_status = HEALTHY

    path_calls = []
    occurrence_calls = []
    original_path = cycle._update_active_path
    original_record = cycle._record_sweep_occurrences
    cycle._update_active_path = lambda snap: (
        path_calls.append(id(snap)) or original_path(snap))
    cycle._record_sweep_occurrences = lambda snap: (
        occurrence_calls.append(id(snap)) or original_record(snap))

    result = cycle.scan(
        tape(), now=datetime(2026, 8, 11, 15, 0, tzinfo=timezone.utc))
    snapshot = result["snapshot"]

    assert len(observed) == 1, "normal ECU scan must make one canonical call"
    assert observed[0]["snapshot_object"] == id(snapshot)
    payload = observed[0]["input"]
    assert payload["derived_state"] == {
        key: snapshot["derived_state"][key]
        for key in ("history_revision", "derived_revision", "current")}
    assert payload["derived_state"]["current"] is True
    assert "last_rebuild" not in payload["derived_state"]
    assert payload["active_path_state"] == snapshot["active_path_state"]
    assert payload["active_path_state"]["state_available"] is True
    assert isinstance(snapshot["reversal_formation_view"], dict)
    assert payload["authorized_tool_catalog"] == observed[0]["catalog"]
    assert payload["authorized_tool_catalog"]
    assert len(path_calls) == len(occurrence_calls) == 1
    assert snapshot["ai_brain"] is snapshot["candidate_thesis"]["brain_block"]


def test_snapshot_builder_runs_the_hook_before_ecu_cognition(monkeypatch):
    from ai_brain import ecu
    from data_feed.timeframe_builder import build_timeframes
    from market_data.snapshot_builder import build_snapshot

    from test_runtime_continuity_recovery import tape

    seen = []
    marker = {"current_occurrence": "same-snapshot"}

    def hook(snapshot):
        snapshot["audit_current_facts"] = marker

    def cognition(snapshot):
        seen.append(snapshot.get("audit_current_facts"))
        return {"owner": "ai_brain", "source": "fallback",
                "direction": "neutral", "opportunity": False,
                "brain_block": {"source": "fallback", "output": None,
                                "fallback_reason": "test"}}

    monkeypatch.setenv("BRAIN_ECU_MODE", "true")
    monkeypatch.setattr(ecu, "produce_thesis", cognition)
    build_snapshot(build_timeframes(tape()), symbol="MNQ", invoke_brain=True,
                   pre_cognition_hook=hook)
    assert seen == [marker]
