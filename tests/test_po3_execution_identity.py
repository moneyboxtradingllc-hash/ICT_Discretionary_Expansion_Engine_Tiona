"""PO3 execution identity: only the producer's own retained formation may execute.

S4I. On the real minute tape below, a 5m buy-side raid of the protected high
29519.75 has source time 14:45, the matching bearish ActivePath leg is released
at 14:46 (1m close above its 1m load-bearing high 29519.25), and the 5m bucket
14:55 validates the reversal block. ReversalFormationCustody correctly retires
that generation (raid <= release source <= cutoff). Before this repair,
po3_reversal_order_block() then fell back to a fresh detection, the catalog
published it as an executable row with no identity, and a family-only Brain
selection authored a CANDIDATE at 15:01 and 15:02.

The healthy twin (p2h) differs only in the 14:46 bar, which wicks through the
1m high but closes below it: no release, the retained formation keeps its
producer identity, and the candidate is authored from that exact identity.

Bars are lawful synthetic OHLC appended to Codex's fixed natural W5 seed. The
Brain transport is mocked and, adversarially, names the PO3 family on every
proposed entry whether or not any row is eligible, so these tests exercise the
CandidateProducer's refusal rather than a model that chose to stand down.
"""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

import test_campaign_scope as T
import test_campaign_scope_binding as B
import test_reversal_foundation_proof_closure as RF
from broker.luna_candidate_producer import NoCandidate, authorized_tool_catalog
from market_data.reversal_formation import current_block

# The producer's identity for the healthy bearish block (raid 14:45, validation
# 14:55, anchor 5m protected high registered 14:29). On p2 the same geometry is
# retired, so this string names a dead generation there.
EXPECTED_ID = ("PO3_REVERSAL_ORDER_BLOCK:CON.F.US.MNQ.Z26:5m:2026-08-19T14:55:00+00:00:"
               "bearish:LIQUIDITY_SWEEP:CON.F.US.MNQ.Z26:5m:2026-08-19T14:45:00+00:00:"
               "5m:swing_high:29519.8:2026-08-19T14:29:00+00:00")
# Well formed, but not the current producer identity on p2h.
STALE_ID = EXPECTED_ID.replace("5m:2026-08-19T14:55:00", "5m:2026-08-19T14:50:00")
# Pre-raid control: release 14:46 precedes the 14:50 raid; validation 15:00.
PRE_RAID_ID = ("PO3_REVERSAL_ORDER_BLOCK:CON.F.US.MNQ.Z26:5m:2026-08-19T15:00:00+00:00:"
               "bearish:LIQUIDITY_SWEEP:CON.F.US.MNQ.Z26:5m:2026-08-19T14:50:00+00:00:"
               "5m:swing_high:29519.8:2026-08-19T14:29:00+00:00")
UNAVAILABLE = "PO3_FORMATION_IDENTITY_UNAVAILABLE"


def _bars(seq, start_close):
    out, prev = [], start_close
    for hhmm, high, low, close in seq:
        out.append({"timestamp": f"2026-08-19T{hhmm}:00+00:00", "open": prev,
                    "high": max(high, prev, close), "low": min(low, prev, close),
                    "close": close, "volume": 10, "contract": T.CONTRACT})
        prev = close
    return out


# 14:47-14:49 close the 14:45 5m bucket back below 29519.75 (the raid); the
# 14:55 bucket closes 29503.5 below the run body 29509.5 (validation, first
# visible at the 14:59 scan); 15:00-15:03 retrace into the block.
_TAIL = [("14:50", 29516.5, 29513.5, 29514.0), ("14:51", 29514.5, 29512.0, 29512.5),
         ("14:52", 29513.0, 29510.5, 29511.0), ("14:53", 29511.5, 29509.5, 29510.0),
         ("14:54", 29510.5, 29509.75, 29510.25), ("14:55", 29510.5, 29507.5, 29508.0),
         ("14:56", 29508.5, 29506.0, 29506.5), ("14:57", 29507.0, 29505.0, 29505.5),
         ("14:58", 29506.0, 29504.0, 29504.5), ("14:59", 29505.0, 29503.0, 29503.5),
         ("15:00", 29507.0, 29503.0, 29506.5), ("15:01", 29511.0, 29506.0, 29510.5),
         ("15:02", 29512.0, 29509.5, 29511.0), ("15:03", 29511.5, 29508.0, 29508.5),
         ("15:04", 29509.0, 29505.0, 29505.5)]
_P2 = [("14:47", 29521.0, 29518.0, 29518.5), ("14:48", 29519.0, 29516.5, 29517.0),
       ("14:49", 29517.5, 29515.5, 29516.0)] + _TAIL
_P2H = [("14:46", 29521.0, 29516.75, 29517.0)] + _P2
# After the healthy formation is retained, the 15:05 5m bucket closes 29521.75
# above the 5m anchor 29519.75: the producer revokes the formation at 15:09.
_REVOKE = _P2H + [("15:05", 29512.0, 29505.0, 29511.5), ("15:06", 29516.0, 29511.0, 29515.5),
                  ("15:07", 29519.0, 29515.0, 29518.5), ("15:08", 29521.0, 29518.0, 29520.5),
                  ("15:09", 29522.5, 29520.0, 29521.75)]
# Pre-raid control (release 14:46, then a 1m raid of 29524 inside the 14:50 5m
# bucket, validation by the 15:00 bucket).
_S1 = [("14:47", 29523.0, 29520.5, 29522.5), ("14:48", 29524.0, 29521.0, 29521.25),
       ("14:49", 29521.5, 29517.75, 29518.0), ("14:50", 29519.0, 29517.5, 29518.5),
       ("14:51", 29520.0, 29517.75, 29519.5), ("14:52", 29521.0, 29518.75, 29520.5),
       ("14:53", 29525.0, 29519.5, 29518.75), ("14:54", 29519.25, 29516.0, 29516.5),
       ("14:55", 29517.0, 29514.0, 29514.5), ("14:56", 29515.5, 29512.5, 29513.0),
       ("14:57", 29514.0, 29511.0, 29511.5), ("14:58", 29513.0, 29510.0, 29510.5),
       ("14:59", 29512.0, 29509.0, 29509.5), ("15:00", 29511.0, 29508.5, 29509.0),
       ("15:01", 29510.0, 29507.0, 29507.5), ("15:02", 29509.0, 29506.0, 29506.5),
       ("15:03", 29508.0, 29505.0, 29505.5), ("15:04", 29507.0, 29504.0, 29504.5)]
# Seed bars kept unchanged: p2/s1 keep the natural 14:46 release bar.
_TAPES = {"p2": (107, _P2), "p2h": (106, _P2H), "revoke": (106, _REVOKE), "s1": (107, _S1)}


def _tape(key):
    keep, seq = _TAPES[key]
    head = T._tape()[:keep]
    return head + _bars(seq, head[-1]["close"])


def _hm(snapshot):
    return snapshot["timestamp"][11:16]


def _po3(snapshot, direction="bearish"):
    return [r for r in authorized_tool_catalog(snapshot)
            if r.get("tool_family") == "po3_reversal_order_block"
            and r.get("direction") == direction]


def _isolate(tmp_path, monkeypatch):
    for name, leaf in (("OCCURRENCE_LEDGER_DIR", "occ"), ("AI_BRAIN_DIR", "brain"),
                       ("AI_RETRIEVAL_DIR", "retr"), ("REPLAY_SESSIONS_DIR", "replay")):
        monkeypatch.setenv(name, str(tmp_path / leaf))
    monkeypatch.chdir(tmp_path)
    for key, value in (("BRAIN_ECU_MODE", "false"), ("AI_BRAIN_ENABLED", "false"),
                       ("AI_BRAIN_LLM", "false")):
        monkeypatch.setenv(key, value)


def _adversarial(mode, price):
    """MOCKED Brain: the repository's bearish reply, retargeted at the farthest
    authorized objective, and on every proposed entry it names the PO3 family
    (plus an occurrence for 'named'/'stale_named') regardless of eligibility."""
    def mutate(output, ordinal, payload):
        out = RF._valid_model_reply(payload, direction="bearish")
        below = [r for r in payload.get("authorized_objectives", [])
                 if isinstance(r, dict) and r.get("objective_id")
                 and isinstance(r.get("price"), (int, float)) and r["price"] < price[0]]
        far = [r for r in below if r.get("kind") == "opposing_external_liquidity"] or below
        if far and out.get("objective_id"):
            out["objective_id"] = min(far, key=lambda r: r["price"])["objective_id"]
        if out.get("current_action") == "propose_entry":
            out.update(recommended_playbook_family="manipulation_to_distribution",
                       recommended_tool_family=["po3_reversal_order_block"])
            out.pop("recommended_tool_occurrence_id", None)
            if mode == "named":
                out["recommended_tool_occurrence_id"] = EXPECTED_ID
            elif mode == "stale_named":
                out["recommended_tool_occurrence_id"] = STALE_ID
        return out
    return mutate


def _produce(tmp_path, monkeypatch, key, *, ecu, mode, brain_from):
    """REAL ProductionScanCycle over the tape; Brain mocked from `brain_from`.
    Returns {cutoff: (scan, candidate-or-NoCandidate)} at 15:01 and 15:02."""
    from live_scan.production_scan_cycle import ProductionScanCycle
    from broker.topstepx_slippage import QuoteCapture
    _isolate(tmp_path, monkeypatch)
    tape = _tape(key)
    price = [tape[0]["close"]]

    def quote():
        return QuoteCapture(captured_at=datetime.now(timezone.utc), best_bid=price[0],
                            best_ask=price[0] + .25, last_trade=price[0],
                            contract_id=T.CONTRACT, market_data_age_seconds=.25)

    cycle = ProductionScanCycle(symbol="MNQ", contract_id=T.CONTRACT,
                                session_id="S4I-PO3", quote_provider=quote)
    calls, armed, seen = [], False, {}
    for end in range(20, len(tape) + 1):
        bars = tape[:end]
        price[0] = bars[-1]["close"]
        hm = bars[-1]["timestamp"][11:16]
        brain = hm >= brain_from
        if brain and not armed:
            RF._mock_current_brain(monkeypatch, calls, output_mutator=_adversarial(mode, price))
            monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
            armed = True
        scan = cycle.scan(bars, now=datetime.fromisoformat(bars[-1]["timestamp"]) + timedelta(minutes=1),
                          invoke_brain=brain)
        if hm in ("15:01", "15:02"):
            try:
                outcome = B._candidate(scan, cycle)
            except NoCandidate as exc:
                outcome = exc
            seen[hm] = (scan, outcome, copy.deepcopy(cycle._active_path.releases))
    assert calls, "the mocked Brain was never invoked"
    return seen


def _assert_model_named_po3(scan, mode):
    output = (scan.get("brain_block") or {}).get("output") or {}
    assert (scan.get("brain_block") or {}).get("source") == "llm"
    assert output.get("current_action") == "propose_entry"
    assert output.get("recommended_tool_family") == ["po3_reversal_order_block"]
    expected = {"named": EXPECTED_ID, "stale_named": STALE_ID}.get(mode)
    assert output.get("recommended_tool_occurrence_id") == expected


@pytest.mark.parametrize("mode", ["family", "stale_named"])
@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_retired_po3_generation_cannot_execute(tmp_path, monkeypatch, ecu, mode):
    seen = _produce(tmp_path, monkeypatch, "p2", ecu=ecu, mode=mode, brain_from="14:56")
    assert sorted(seen) == ["15:01", "15:02"]
    for hm, (scan, outcome, releases) in seen.items():
        snapshot = scan["snapshot"]
        # The matching-direction generation died after the raid source time.
        bearish = [r for r in releases if r.get("owner") == "bearish"]
        assert bearish[-1]["source_bar_time"] == "2026-08-19T14:46:00+00:00"
        assert bearish[-1]["occurrence_id"].startswith(
            "PROTECTED_SWING_VIOLATED:CON.F.US.MNQ.Z26:1m:2026-08-19T14:46:00+00:00:high@29519.25")
        # Custody retired the formation: nothing is retained.
        assert current_block(snapshot, "bearish") is None
        # The fresh observation stays visible, but carries no identity and
        # cannot execute.
        rows = _po3(snapshot)
        assert len(rows) == 1, rows
        row = rows[0]
        assert row["sweep_event_time"] == "2026-08-19T14:45:00+00:00"
        assert row["validation_timestamp"] == "2026-08-19T14:55:00+00:00"
        assert (row["zone_low"], row["zone_high"]) == (29509.5, 29518.25)
        # The Brain still proposed this family; the producer must refuse. The
        # row and the candidate outcome are asserted together so a violation
        # reports both the executable row and the authored candidate.
        _assert_model_named_po3(scan, mode)
        observed = (hm, row["execution_eligible"], row["execution_ineligible_reason"],
                    row["occurrence_id"], row["formation_authority"] is None,
                    outcome.reason if isinstance(outcome, NoCandidate) else "CANDIDATE")
        assert observed == (hm, False, UNAVAILABLE, None, True,
                            "tool_not_execution_eligible")
        assert UNAVAILABLE in str(outcome.detail)


@pytest.mark.parametrize("mode,ecu", [("family", False), ("family", True), ("named", False),
                                      ("stale_named", False)],
                         ids=["family-non-ecu", "family-ecu", "named-non-ecu", "stale-named-non-ecu"])
def test_healthy_retained_po3_keeps_exact_identity_and_candidate(tmp_path, monkeypatch, mode, ecu):
    seen = _produce(tmp_path, monkeypatch, "p2h", ecu=ecu, mode=mode, brain_from="14:47")
    assert sorted(seen) == ["15:01", "15:02"]
    entries = {"15:01": 29510.5, "15:02": 29511.0}
    for hm, (scan, outcome, releases) in seen.items():
        snapshot = scan["snapshot"]
        # No bearish generation died at or after the 14:45 raid.
        assert not [r for r in releases if r.get("owner") == "bearish"
                    and r.get("source_bar_time", "") >= "2026-08-19T14:45:00+00:00"]
        retained = current_block(snapshot, "bearish")
        authority = retained["formation_authority"]
        assert authority["status"] == "CURRENT_PROCESS_REVALIDATED"
        assert authority["occurrence_id"] == EXPECTED_ID
        assert authority["history_revision"] == snapshot["derived_state"]["history_revision"]
        assert retained["sweep_evidence"]["event_time"] == "2026-08-19T14:45:00+00:00"
        assert retained["validation_timestamp"] == "2026-08-19T14:55:00+00:00"
        rows = _po3(snapshot)
        assert len(rows) == 1
        row = rows[0]
        assert row["execution_eligible"] is True and row["execution_ineligible_reason"] is None
        assert row["occurrence_id"] == EXPECTED_ID
        assert row["formation_authority"] == authority
        _assert_model_named_po3(scan, mode)
        if mode == "stale_named":
            # A well-formed ID that is not the producer's current object is refused.
            assert isinstance(outcome, NoCandidate)
            assert outcome.reason == "tool_occurrence_unknown"
            continue
        assert not isinstance(outcome, NoCandidate), (hm, outcome)
        assert outcome.direction == "bearish"
        assert outcome.extras["tool_family"] == ["po3_reversal_order_block"]
        assert outcome.extras["selected_tool_occurrence_id"] == EXPECTED_ID
        assert outcome.entry_price == entries[hm]
        assert outcome.invalidation_price == 29519.75


def _brainless(tmp_path, monkeypatch, key, stop=None, on_scan=None):
    """REAL brainless ProductionScanCycle. Custody is live state, so anything
    that depends on it must be read at scan time (`on_scan`) or at `stop`."""
    from live_scan.production_scan_cycle import ProductionScanCycle
    _isolate(tmp_path, monkeypatch)
    tape = _tape(key)
    cycle = ProductionScanCycle(symbol="MNQ", contract_id=T.CONTRACT, session_id="S4I-PO3")
    scans = {}
    for end in range(20, len(tape) + 1):
        bars = tape[:end]
        scan = cycle.scan(bars, now=datetime.fromisoformat(bars[-1]["timestamp"]) + timedelta(minutes=1),
                          invoke_brain=False)
        scans[_hm(scan["snapshot"])] = scan
        if on_scan is not None:
            on_scan(scan["snapshot"])
        if stop and _hm(scan["snapshot"]) == stop:
            break
    return cycle, scans


def _anonymous(rows):
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["execution_eligible"] is False
    assert row["execution_ineligible_reason"] == UNAVAILABLE
    assert row["occurrence_id"] is None and row["formation_authority"] is None
    # Still the same visible observation (geometry), not a different object.
    assert row["validation_timestamp"] == "2026-08-19T14:55:00+00:00"
    return row


def test_copied_restored_stale_and_forged_authority_cannot_publish_executable_row(
        tmp_path, monkeypatch):
    import toolbox.price_levels as price_levels
    _, scans = _brainless(tmp_path, monkeypatch, "p2h", stop="15:01")
    live = scans["15:01"]["snapshot"]
    retained = current_block(live, "bearish")
    assert retained["formation_authority"]["occurrence_id"] == EXPECTED_ID
    [row] = _po3(live)
    assert row["execution_eligible"] is True and row["occurrence_id"] == EXPECTED_ID

    # A deep copy and a JSON restore lose the producer's sealed custody view.
    # The fallback detector still sees the geometry; it cannot execute.
    _anonymous(_po3(copy.deepcopy(live)))
    _anonymous(_po3(json.loads(json.dumps(live, default=str))))
    # The producer view removed (as on a snapshot no custody vouched for).
    missing = {k: v for k, v in live.items() if k != "reversal_formation_view"}
    _anonymous(_po3(missing))
    # A different history revision than the one custody revalidated.
    stale = dict(live)
    stale["derived_state"] = dict(live["derived_state"],
                                  history_revision=live["derived_state"]["history_revision"] + 1,
                                  derived_revision=live["derived_state"]["history_revision"] + 1)
    _anonymous(_po3(stale))

    # Copied formation metadata is not authority: the genuine retained block,
    # carried onto a snapshot whose custody does not vouch for it.
    real = price_levels.po3_reversal_order_block
    copied_block = copy.deepcopy(retained)
    monkeypatch.setattr(price_levels, "po3_reversal_order_block",
                        lambda snap, direction: (copy.deepcopy(copied_block)
                                                 if direction == "bearish" else real(snap, direction)))
    rows = _po3(copy.deepcopy(live))
    assert len(rows) == 1
    assert rows[0]["execution_eligible"] is False
    assert rows[0]["execution_ineligible_reason"] == UNAVAILABLE
    assert rows[0]["occurrence_id"] is None and rows[0]["formation_authority"] is None
    # An ID string on its own is not authority, even on the live snapshot.
    forged = copy.deepcopy(retained)
    forged["formation_authority"]["occurrence_id"] = "PO3_REVERSAL_ORDER_BLOCK:forged"
    monkeypatch.setattr(price_levels, "po3_reversal_order_block",
                        lambda snap, direction: (copy.deepcopy(forged)
                                                 if direction == "bearish" else real(snap, direction)))
    rows = _po3(live)
    assert len(rows) == 1
    assert rows[0]["execution_eligible"] is False
    assert rows[0]["occurrence_id"] is None and rows[0]["formation_authority"] is None
    monkeypatch.setattr(price_levels, "po3_reversal_order_block", real)
    # The untouched live snapshot is still the producer's executable object.
    [row] = _po3(live)
    assert row["execution_eligible"] is True and row["occurrence_id"] == EXPECTED_ID


def test_producer_revocation_removes_execution_identity_from_an_earlier_snapshot(
        tmp_path, monkeypatch):
    earlier, timeline = {}, []

    def on_scan(snapshot):
        hm = _hm(snapshot)
        if hm == "15:01":
            earlier["snapshot"] = snapshot
        if "snapshot" in earlier:
            rows = _po3(earlier["snapshot"])
            timeline.append((hm, current_block(snapshot, "bearish") is not None,
                             [(r["execution_eligible"], r["occurrence_id"],
                               r["execution_ineligible_reason"]) for r in rows]))

    _brainless(tmp_path, monkeypatch, "revoke", on_scan=on_scan)
    by_minute = {hm: (retained, rows) for hm, retained, rows in timeline}
    # While the producer retains the formation, the 15:01 publication is still
    # the producer's executable object.
    for hm in ("15:01", "15:04", "15:08"):
        retained, rows = by_minute[hm]
        assert retained is True
        assert rows == [(True, EXPECTED_ID, None)]
    # The 5m bucket 15:05 closes 29521.75 above the 5m anchor 29519.75: the
    # producer drops the formation at the 15:09 scan, and the 15:01 snapshot
    # can no longer execute.
    retained, rows = by_minute["15:09"]
    assert retained is False
    assert rows == [(False, None, UNAVAILABLE)]


def test_pre_raid_release_keeps_retained_identity_executable(tmp_path, monkeypatch):
    _, scans = _brainless(tmp_path, monkeypatch, "s1", stop="15:04")
    snapshot = scans["15:04"]["snapshot"]
    retained = current_block(snapshot, "bearish")
    assert retained["formation_authority"]["occurrence_id"] == PRE_RAID_ID
    [row] = _po3(snapshot)
    assert row["execution_eligible"] is True
    assert row["occurrence_id"] == PRE_RAID_ID
    assert row["formation_authority"] == retained["formation_authority"]
