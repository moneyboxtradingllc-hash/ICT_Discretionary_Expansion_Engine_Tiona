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
