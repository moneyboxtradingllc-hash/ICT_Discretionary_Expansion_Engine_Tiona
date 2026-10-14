"""The one canonical ECU Brain call is fed the same settled structure facts as non-ECU.

S4L O3. Structure flips (BROKEN_SUPPORT_FLIP / BROKEN_RESISTANCE_FLIP) and the
MTF_MARKET_STATE built from them are advanced by
ProductionScanCycle._update_structure_flips. The non-ECU path advances them
before run_narrative_brain reads its input. Under ECU the single Brain call runs
inside build_snapshot (pre_cognition_hook, then produce_thesis); the hook
attached path, formation, scope and Draw facts but not the flips, which were
advanced only afterwards. The TRANSPORTED ECU payload therefore carried no
structure_flips, no INV_BSF_/INV_BRF_ authorized invalidation and no
MTF_MARKET_STATE, while the scan's returned snapshot and rebuilt brain_input did
carry them.

These tests read the exact payload handed to the (mocked) model transport, not
the scan's returned metadata. Bars are lawful synthetic OHLC appended to Codex's
fixed natural W5 seed (test_po3_execution_identity / test_formation_view_publication).
"""
import copy
from datetime import datetime, timedelta, timezone

import pytest

import test_campaign_scope as T
import test_campaign_scope_binding as B
import test_formation_view_publication as P
import test_po3_execution_identity as X
import test_reversal_foundation_proof_closure as RF
from broker.luna_candidate_producer import NoCandidate

FLIP_PREFIXES = ("INV_BSF_", "INV_BRF_")


def _flip_ids(rows):
    return sorted((r.get("invalidation_id"), r.get("price")) for r in rows or []
                  if isinstance(r, dict))


def _run(root, monkeypatch, key, *, ecu, brain_from="14:59", brainless=()):
    """REAL ProductionScanCycle; records, per Brain scan, the transported
    payload and the snapshot it was built from, and counts flip advances."""
    from live_scan.production_scan_cycle import ProductionScanCycle
    from broker.topstepx_slippage import QuoteCapture
    root.mkdir()
    X._isolate(root, monkeypatch)
    tape = P._tape(key)
    price = [tape[0]["close"]]

    def quote():
        return QuoteCapture(captured_at=datetime.now(timezone.utc), best_bid=price[0],
                            best_ask=price[0] + .25, last_trade=price[0],
                            contract_id=T.CONTRACT, market_data_age_seconds=.25)

    cycle = ProductionScanCycle(symbol="MNQ", contract_id=T.CONTRACT,
                                session_id="S4L-O3", quote_provider=quote)
    advances = []
    real_update = cycle._update_structure_flips

    def counted(snapshot):
        advances.append(snapshot.get("timestamp"))
        return real_update(snapshot)
    cycle._update_structure_flips = counted

    calls, armed, out = [], False, {}
    for end in range(20, len(tape) + 1):
        bars = tape[:end]
        price[0] = bars[-1]["close"]
        hm = bars[-1]["timestamp"][11:16]
        brain = hm >= brain_from and hm not in brainless
        if hm >= brain_from and not armed:
            RF._mock_current_brain(monkeypatch, calls,
                                   output_mutator=X._adversarial("family", price))
            monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
            armed = True
        before_calls, before_adv = len(calls), len(advances)
        scan = cycle.scan(bars, now=datetime.fromisoformat(bars[-1]["timestamp"]) + timedelta(minutes=1),
                          invoke_brain=brain)
        if hm >= brain_from:
            snapshot = scan["snapshot"]
            payload = copy.deepcopy(calls[-1]) if len(calls) > before_calls else None
            try:
                outcome = B._candidate(scan, cycle) if brain else None
                outcome = outcome and (outcome.entry_price, outcome.invalidation_price,
                                       (outcome.extras.get("structural_invalidation") or {})
                                       .get("structure_identity"))
            except NoCandidate as exc:
                outcome = ("NoCandidate", exc.reason)
            out[hm] = {"brain": brain, "calls": len(calls) - before_calls,
                       "advances": len(advances) - before_adv,
                       "snapshot_flips": _flip_ids(snapshot.get("structure_flips")),
                       "snapshot_mtf": copy.deepcopy(snapshot.get("mtf_market_state")),
                       "payload": payload, "outcome": outcome,
                       "releases": copy.deepcopy(cycle._active_path.releases)}
    return out


def _payload_facts(payload):
    return {
        "flips": _flip_ids(payload.get("structure_flips")),
        "flip_invalidations": _flip_ids(
            r for r in payload.get("authorized_invalidations") or []
            if str(r.get("invalidation_id") or "").startswith(FLIP_PREFIXES)),
        "mtf": payload.get("MTF_MARKET_STATE"),
    }


@pytest.mark.parametrize("key", ["p2h", "post"])
def test_ecu_transport_carries_the_settled_flip_facts_non_ecu_carries(tmp_path, monkeypatch, key):
    lanes = {ecu: _run(tmp_path / ("ecu" if ecu else "non-ecu"), monkeypatch, key, ecu=ecu)
             for ecu in (False, True)}
    flip_minutes = 0
    for hm in sorted(lanes[False]):
        plain, canonical = lanes[False][hm], lanes[True][hm]
        # One Brain call per Brain scan in each lane; one flip advance per scan.
        assert plain["calls"] == canonical["calls"] == 1, hm
        assert plain["advances"] == canonical["advances"] == 1, hm
        # Settled chronology is lane-independent.
        assert plain["releases"] == canonical["releases"], hm
        assert plain["snapshot_flips"] == canonical["snapshot_flips"], hm
        assert plain["snapshot_mtf"] == canonical["snapshot_mtf"], hm
        for lane in (plain, canonical):
            facts = _payload_facts(lane["payload"])
            # What the model actually received equals the scan's settled facts.
            assert facts["flips"] == lane["snapshot_flips"], hm
            assert facts["flip_invalidations"] == lane["snapshot_flips"], hm
            assert facts["mtf"], hm
        assert _payload_facts(plain["payload"]) == _payload_facts(canonical["payload"]), hm
        # Same stop catalog => same candidate geometry (or the same refusal).
        assert plain["outcome"] == canonical["outcome"], hm
        flip_minutes += bool(plain["snapshot_flips"])
    assert flip_minutes == len(lanes[False]), "every Brain minute must carry a flip fact"


def test_brainless_scans_still_advance_flips_once_without_a_brain_call(tmp_path, monkeypatch):
    # LATENCY-1 preauthorized-plan scans make no Brain call; the ECU hook does
    # not run and the post-build advance remains the single advance.
    out = _run(tmp_path / "ecu", monkeypatch, "post", ecu=True, brainless=("15:01", "15:02"))
    for hm in ("15:01", "15:02"):
        row = out[hm]
        assert row["brain"] is False and row["calls"] == 0 and row["payload"] is None, hm
        assert row["advances"] == 1, hm
        assert row["snapshot_flips"] and row["snapshot_mtf"], hm
    for hm in ("15:00", "15:03"):
        assert out[hm]["calls"] == 1 and out[hm]["advances"] == 1, hm
        assert _payload_facts(out[hm]["payload"])["flips"] == out[hm]["snapshot_flips"], hm
