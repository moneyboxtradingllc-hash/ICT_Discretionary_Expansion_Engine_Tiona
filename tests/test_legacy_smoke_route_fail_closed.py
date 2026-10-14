"""The legacy one-trade smoke route may not participate without campaign Lifecycle.

Stage 4 obligation E. tools/topstepx_smoke_wait.py is a manually started,
phrase-authorized script whose one_scan builds a BARE snapshot (build_snapshot
only: no ProductionScanCycle, so no derived history, campaign scope, Draw,
formation custody or Lifecycle assessment) and hands the CandidateProducer's
result to attempt_trade -> ExecutionRunner.gated_submit, a real order path
outside the protected ProductionLoop. The ProductionLoop refuses before
producing a candidate unless participation authority is bound, and calls the
producer with require_campaign_lifecycle=True; the runner itself has no
campaign gate. The smoke route called the producer with the default
require_campaign_lifecycle=False, so the Lifecycle gate was skipped entirely.

Offline reproduction (no credentials, no session, no venue): a fake provider
returns the repository's lawful synthetic tape and the Brain transport is
mocked. On that tape the bare payload offers no authorized invalidation and
the validated Brain output declines, so the old route also refused -- but only
through those incidental gates. The route now fails closed on the Lifecycle
gate itself, before any candidate, while its scan/Brain diagnostics still run.
"""
import importlib.util
import os

import pytest

import test_reversal_foundation_proof_closure as RF
from broker.luna_candidate_producer import CandidateProducer

TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "topstepx_smoke_wait.py")


class _Provider:
    """Offline stand-in for the TopstepX provider: the settled synthetic tape."""

    def __init__(self, bars):
        self.bars = bars
        self.stopped = False

    def fetch_1m_candles(self, symbol, n):
        return [dict(bar) for bar in self.bars[-n:]]

    def stop(self):
        self.stopped = True


def _load_tool(monkeypatch):
    import dotenv
    # Importing the tool must not read an operator .env into the test process.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    spec = importlib.util.spec_from_file_location("legacy_smoke_wait", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("minute", ["02:56", "03:00", "03:02"])
def test_smoke_scan_refuses_on_the_lifecycle_gate_before_any_candidate(
        tmp_path, monkeypatch, capsys, minute):
    import data_feed
    tool = _load_tool(monkeypatch)
    tape = [bar for bar in RF.TAPE_1M + RF._expand_5m(("03:00", 29459.0, 29490.0, 29458.0, 29460.0))
            if bar["timestamp"][11:16] <= minute]
    provider = _Provider(tape)
    monkeypatch.setattr(data_feed, "get_provider", lambda name: provider)
    RF._cycle(tmp_path, monkeypatch)              # scoped runtime directories only
    calls = []
    RF._mock_current_brain(monkeypatch, calls)
    monkeypatch.setenv("BRAIN_ECU_MODE", "false")
    producer = CandidateProducer(account_fingerprint="acct:smoke-offline", contract=RF.MNQ)

    verdict = tool.one_scan(None, producer, None, "acct:smoke-offline", RF.MNQ, 1)

    # Diagnostics still run: one real (mocked-transport) Brain read of the bar.
    assert len(calls) == 1 and provider.stopped
    printed = capsys.readouterr().out
    assert f"px={tape[-1]['close']}" in printed
    # ... but participation is refused on the Lifecycle gate, not left to
    # whichever incidental gate happens to decline this tape.
    assert verdict == {"kind": "gate_refused"}
    assert "NO CANDIDATE: campaign_lifecycle_refused" in printed
    trace = producer.last_decision_trace
    assert trace["campaign_lifecycle_refusal"] == "current_campaign_lifecycle_assessment_unavailable"
    assert trace["campaign_lifecycle_state"] is None


def _production_scan(root, monkeypatch, upto):
    """The REAL ProductionScanCycle over the S4C healthy twin, ACTIVE bearish
    campaign, Brain mocked as in that test; the scan result at `upto`."""
    import test_campaign_scope as T
    import test_po3_anchor_replacement_revocation as C
    import test_po3_execution_identity as X
    import test_po3_post_settlement_death as D
    from datetime import datetime, timedelta, timezone
    from broker.topstepx_slippage import QuoteCapture
    from live_scan.production_scan_cycle import ProductionScanCycle
    root.mkdir()
    X._isolate(root, monkeypatch)
    tape = D._tape(C._HEALTHY)
    px = [tape[0]["close"]]
    cycle = ProductionScanCycle(
        symbol="MNQ", contract_id=T.CONTRACT, session_id="S4-E-SNAPSHOT",
        quote_provider=lambda: QuoteCapture(
            captured_at=datetime.now(timezone.utc), best_bid=px[0], best_ask=px[0] + .25,
            last_trade=px[0], contract_id=T.CONTRACT, market_data_age_seconds=.25))
    chosen = {}
    for end in range(20, len(tape) + 1):
        bars = tape[:end]
        px[0] = bars[-1]["close"]
        if end == 97:
            RF._mock_current_brain(monkeypatch, [], output_mutator=lambda out, n, payload: C._reply(
                out, n, payload, px[0], chosen))
            monkeypatch.setenv("BRAIN_ECU_MODE", "false")
        scan = cycle.scan(bars, now=datetime.fromisoformat(bars[-1]["timestamp"]) + timedelta(minutes=1),
                          invoke_brain=end >= 97)
        if bars[-1]["timestamp"][11:16] == upto:
            return scan, cycle, bars


def test_a_production_quality_snapshot_without_lifecycle_still_refuses_on_lifecycle(
        tmp_path, monkeypatch, capsys):
    """Not an incidental refusal. The bare route is handed the REAL scan
    snapshot of an ACTIVE campaign at a minute where the protected path authors
    a PO3 candidate, with only its Lifecycle assessment removed: protected
    invalidations, objectives and the executable PO3 row are all present. The
    route still refuses on the Lifecycle gate, before any other gate."""
    import data_feed
    import market_data.snapshot_builder as SB
    import test_campaign_scope_binding as B
    import test_po3_anchor_replacement_revocation as C
    import test_po3_execution_identity as X
    scan, cycle, bars = _production_scan(tmp_path / "production", monkeypatch, "15:07")
    produced = B._candidate(scan, cycle)
    assert produced.extras["selected_tool_occurrence_id"] == C.FORMATION_ID
    # The ORIGINAL snapshot object: a copy is not the formation's publication
    # and would carry no execution identity at all (O4), which would make this
    # refusal incidental again.
    snapshot = scan["snapshot"]
    snapshot.pop("campaign_lifecycle")
    assert [row["occurrence_id"] for row in X._po3(snapshot)
            if row["execution_eligible"]] == [C.FORMATION_ID]
    tool = _load_tool(monkeypatch)
    provider = _Provider(bars)
    monkeypatch.setattr(data_feed, "get_provider", lambda name: provider)
    monkeypatch.setattr(SB, "build_snapshot", lambda *a, **k: snapshot)
    producer = CandidateProducer(account_fingerprint="acct:smoke-offline", contract=RF.MNQ)

    verdict = tool.one_scan(None, producer, None, "acct:smoke-offline", RF.MNQ, 1)

    assert verdict == {"kind": "gate_refused"}
    assert "NO CANDIDATE: campaign_lifecycle_refused" in capsys.readouterr().out
    assert (producer.last_decision_trace["campaign_lifecycle_refusal"]
            == "current_campaign_lifecycle_assessment_unavailable")
