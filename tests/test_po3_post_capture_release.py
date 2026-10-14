"""PO3 post-capture P3: opposite-direction releases AFTER the formation is retained.

Stage 4 obligation A. The repository's lawful synthetic RF.TAPE_1M builds the
bullish 5m PO3 formation FORMATION_ID (5m raid 02:15 of the protected low
29429.75, validation 02:20, first retained by custody on the 02:24 scan). The
1m tail below, appended at 02:25, then produces, in this order:

  * 02:30 a rejected 1m buy-side raid of 29500 opens a bearish leg; its 3m
    load-bearing high 29500 is closed through by the 3m bar 02:36, a genuine
    bearish release observed at 02:38 (source 02:36), after capture;
  * 02:47 a second bearish leg (1m high 29509) released at 02:48 (source 02:48);
  * 02:57 a rejected 1m sell-side raid of the 1m swing low 29508 opens a
    bullish leg, and 02:59 closes above the 1m swing high 29518: a lawful,
    owned bullish ActivePath (load-bearing 1m low 29508) under which Draw and
    Lifecycle establish from the Brain's own selections;
  * 03:00-03:02 expansion to 29545 (a buy-side pool), 03:03-03:14 a shallow
    retracement that never closes below 29508.

The bearish releases are raid <= source <= cutoff for the formation, so only
the release-owner/formation-direction distinction keeps the bullish formation
current. With it, the real CandidateProducer authors a CANDIDATE from the exact
retained FORMATION_ID in both lanes. The matched control closes the 03:00 bar
below the bullish 1m load-bearing low instead: a same-direction release after
capture, which retires the same formation at once.

The quote follows the latest settled close (as in test_po3_execution_identity)
because this tail trades away from RF's fixed 29456 quote. The Brain transport
is mocked: the repository reply, naming the PO3 family, the exact bullish PO3
catalog occurrence and the 1m protected low the payload offers.
"""
import copy
from datetime import datetime, timezone

import pytest

import test_campaign_scope_binding as B
import test_po3_execution_identity as X
import test_reversal_foundation_proof_closure as RF
from broker.luna_candidate_producer import NoCandidate
from market_data.reversal_formation import ReversalFormationCustody, current_block

FORMATION_ID = ("PO3_REVERSAL_ORDER_BLOCK:CON.F.US.MNQ.Z26:5m:2026-08-19T02:20:00+00:00:bullish:"
                "LIQUIDITY_SWEEP:CON.F.US.MNQ.Z26:5m:2026-08-19T02:15:00+00:00:"
                "5m:swing_low:29429.8:2026-08-19T01:39:00+00:00")
CAPTURE = "2026-08-19T02:24:00+00:00"
UNAVAILABLE = X.UNAVAILABLE

_TAIL = [
    ("02:25", 29495.0, 29486.0, 29488.0), ("02:26", 29489.0, 29482.0, 29484.0), ("02:27", 29486.0, 29480.0, 29482.0),
    ("02:28", 29484.0, 29478.0, 29480.0), ("02:29", 29483.0, 29477.0, 29479.0), ("02:30", 29503.0, 29478.0, 29492.0),
    ("02:31", 29494.0, 29486.0, 29488.0), ("02:32", 29490.0, 29484.0, 29486.0), ("02:33", 29488.0, 29482.0, 29484.0),
    ("02:34", 29486.0, 29480.0, 29482.0), ("02:35", 29485.0, 29478.0, 29480.0), ("02:36", 29507.0, 29480.0, 29506.0),
    ("02:37", 29509.0, 29503.0, 29505.0), ("02:38", 29508.0, 29503.0, 29506.0), ("02:39", 29507.0, 29501.0, 29505.0),
    ("02:40", 29508.0, 29504.0, 29507.0), ("02:41", 29510.0, 29506.0, 29509.0), ("02:42", 29509.0, 29505.0, 29506.0),
    ("02:43", 29508.0, 29504.0, 29505.0), ("02:44", 29511.0, 29505.0, 29510.0), ("02:45", 29513.0, 29509.0, 29512.0),
    ("02:46", 29512.0, 29508.0, 29509.0), ("02:47", 29511.0, 29507.0, 29508.0), ("02:48", 29512.0, 29507.0, 29511.0),
    ("02:49", 29514.0, 29510.0, 29513.0), ("02:50", 29516.0, 29511.0, 29515.0), ("02:51", 29517.0, 29512.0, 29516.0),
    ("02:52", 29518.0, 29513.0, 29517.0), ("02:53", 29516.0, 29508.0, 29510.0), ("02:54", 29514.0, 29509.0, 29513.0),
    ("02:55", 29515.0, 29510.0, 29514.0), ("02:56", 29516.0, 29511.0, 29515.0), ("02:57", 29514.0, 29505.0, 29511.0),
    ("02:58", 29516.0, 29510.0, 29515.0), ("02:59", 29520.0, 29514.0, 29519.0), ("03:00", 29530.0, 29518.0, 29528.0),
    ("03:01", 29538.0, 29526.0, 29536.0), ("03:02", 29545.0, 29534.0, 29540.0), ("03:03", 29541.0, 29530.0, 29532.0),
    ("03:04", 29535.0, 29522.0, 29524.0), ("03:05", 29527.0, 29514.0, 29516.0), ("03:06", 29520.0, 29513.0, 29518.0),
    ("03:07", 29522.0, 29515.0, 29519.0), ("03:08", 29524.0, 29516.0, 29521.0), ("03:09", 29523.0, 29517.0, 29520.0),
    ("03:10", 29524.0, 29518.0, 29522.0), ("03:11", 29525.0, 29519.0, 29523.0), ("03:12", 29526.0, 29520.0, 29524.0),
    ("03:13", 29525.0, 29520.0, 29523.0), ("03:14", 29527.0, 29521.0, 29525.0),
]
# Matched control: identical through 02:59, then 03:00 closes 29506 below the
# bullish 1m load-bearing low 29508 (a same-direction release after capture).
_SAME = [row for row in _TAIL if row[0] <= "02:59"] + [
    ("03:00", 29520.0, 29505.0, 29506.0), ("03:01", 29508.0, 29502.0, 29504.0),
    ("03:02", 29506.0, 29500.0, 29503.0)]

BRAIN_FROM = "03:05"
OPPOSITE = {("bearish", "3m", "02:36", "02:38"), ("bearish", "1m", "02:48", "02:48")}
_REAL_CURRENT_GENERATION = ReversalFormationCustody.__dict__["_current_generation"].__func__


def _tape(seq):
    head = [bar for bar in RF.TAPE_1M if bar["timestamp"] <= CAPTURE]
    return head + X._bars(seq, head[-1]["close"])


def _choose(selected):
    def mutate(output, ordinal, payload):
        if output.get("current_action") != "propose_entry" or output.get("narrative_direction") != "bullish":
            return output
        po3 = next((r for r in payload.get("authorized_tool_catalog", [])
                    if r.get("tool_family") == "po3_reversal_order_block"
                    and r.get("direction") == "bullish"), None)
        stop = next((r for r in payload.get("authorized_invalidations", [])
                     if r.get("type") == "protected_low" and r.get("timeframe") == "1m"), None)
        selected[ordinal] = po3 and po3.get("occurrence_id")
        out = {**output, "recommended_tool_family": ["po3_reversal_order_block"],
               "recommended_tool_occurrence_id": selected[ordinal]}
        if stop:
            out.update(invalidation_id=stop["invalidation_id"], invalidation_level=stop["price"])
        return out
    return mutate


def _release(row):
    return (row.get("owner"), row.get("source_tf"), str(row.get("source_bar_time"))[11:16],
            str(row.get("at"))[11:16])


def _run(root, monkeypatch, seq, *, ecu, brain_from=None):
    """REAL ProductionScanCycle at 1m cadence; per-minute facts from 02:23."""
    from broker.topstepx_slippage import QuoteCapture
    from live_scan.production_scan_cycle import ProductionScanCycle
    root.mkdir()
    X._isolate(root, monkeypatch)
    tape = _tape(seq)
    price = [tape[0]["close"]]

    def quote():
        return QuoteCapture(captured_at=datetime.now(timezone.utc), best_bid=price[0],
                            best_ask=price[0] + .25, last_trade=price[0],
                            contract_id=RF.CONTRACT, market_data_age_seconds=.25)

    consulted = []

    def spy(record, releases, current_at):
        result = _REAL_CURRENT_GENERATION(record, releases, current_at)
        if record.get("direction") == "bullish":
            consulted.append(({_release(r) for r in releases or [] if isinstance(r, dict)}, result))
        return result
    monkeypatch.setattr(ReversalFormationCustody, "_current_generation", staticmethod(spy))

    cycle = ProductionScanCycle(symbol="MNQ", contract_id=RF.CONTRACT,
                                session_id=RF.SESSION_ID, quote_provider=quote)
    calls, selected, armed, out = [], {}, False, {}
    for end in range(5, len(tape) + 1):
        bars = tape[:end]
        price[0] = bars[-1]["close"]
        hm = bars[-1]["timestamp"][11:16]
        brain = brain_from is not None and hm >= brain_from
        if brain and not armed:
            RF._mock_current_brain(monkeypatch, calls, output_mutator=_choose(selected))
            monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
            armed = True
        n_calls, n_consulted = len(calls), len(consulted)
        scan = cycle.scan(bars, now=RF._now_for(bars), invoke_brain=brain)
        if hm < "02:23":
            continue
        snap = scan["snapshot"]
        block = current_block(snap, "bullish")
        authority = (block or {}).get("formation_authority") or {}
        path = snap.get("active_path_state") or {}
        row = {
            "custody": (authority.get("occurrence_id"), authority.get("status")) if block else None,
            "catalog": [(r["execution_eligible"], r["occurrence_id"], r["execution_ineligible_reason"])
                        for r in X._po3(snap, "bullish")],
            "releases": {_release(r) for r in cycle._active_path.releases
                         if str(r.get("at")) > CAPTURE},
            "path": (path.get("owner"), path.get("status")),
            "forming": cycle._active_path.forming_direction,
            "load_bearing": ((cycle._active_path.load_bearing or {}).get("level"),
                             (cycle._active_path.load_bearing or {}).get("timeframe")),
            "lifecycle": (scan.get("campaign_lifecycle") or {}).get("state"),
            "consulted": consulted[n_consulted:],
        }
        if brain:
            row["calls"] = len(calls) - n_calls
            row["named"] = selected.get(len(calls))
            row["offered"] = [(r.get("occurrence_id"), r.get("execution_eligible"))
                              for r in calls[-1].get("authorized_tool_catalog", [])
                              if r.get("tool_family") == "po3_reversal_order_block"
                              and r.get("direction") == "bullish"]
            try:
                candidate = B._candidate(scan, cycle)
                row["candidate"] = ("CANDIDATE", candidate.direction,
                                    candidate.extras.get("selected_tool_occurrence_id"),
                                    candidate.entry_price, candidate.invalidation_price,
                                    candidate.objective.price)
            except NoCandidate as exc:
                row["candidate"] = ("NoCandidate", exc.reason)
            row["close"] = bars[-1]["close"]
        out[hm] = row
    return out


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_post_capture_opposite_releases_keep_the_formation_and_it_executes(tmp_path, monkeypatch, ecu):
    out = _run(tmp_path / "run", monkeypatch, _TAIL, ecu=ecu, brain_from=BRAIN_FROM)
    # Capture: custody retains the formation first on the 02:24 scan.
    assert out["02:23"]["custody"] is None
    retained = (FORMATION_ID, "CURRENT_PROCESS_REVALIDATED")
    for hm, row in out.items():
        if hm >= "02:24":
            assert row["custody"] == retained, hm
            assert row["catalog"] == [(True, FORMATION_ID, None)], hm
    # Both opposite releases happen after capture, and are the only releases
    # after it: nothing on this tape releases the bullish owner.
    assert out["02:37"]["releases"] == set()
    assert out["02:38"]["releases"] == {("bearish", "3m", "02:36", "02:38")}
    assert out["03:14"]["releases"] == OPPOSITE
    # The retirement predicate consulted each release for this formation on
    # the scan that observed it, and kept the generation current.
    for hm, release in (("02:38", ("bearish", "3m", "02:36", "02:38")),
                        ("02:48", ("bearish", "1m", "02:48", "02:48"))):
        seen = [result for releases, result in out[hm]["consulted"] if release in releases]
        assert seen and all(result is True for result in seen), hm
    # A lawful owned path: forming from the 02:57 sell-side raid, active from
    # the 02:59 break, load-bearing 1m low 29508 intact through 03:14.
    assert out["02:56"]["path"] == ("none", "none")
    assert out["02:57"]["forming"] == "bullish"
    for hm, row in out.items():
        if hm >= "02:59":
            assert row["path"] == ("bullish", "active"), hm
            assert row["load_bearing"] == (29508.0, "1m"), hm
    # Draw/Lifecycle chronology from the Brain's own selections: the 03:05
    # Draw (newborn) is not yet a measurement; its 29518 objective is reached
    # by the 03:06 high 29520; the 03:06 Draw (29545) is ACTIVE_DELIVERY from 03:07.
    assert out["03:05"]["lifecycle"] == "AUTHORITY_UNKNOWN"
    assert out["03:06"]["lifecycle"] == "DESTINATION_SUBSTANTIALLY_DELIVERED"
    for hm in ("03:05", "03:06"):
        assert out[hm]["candidate"] == ("NoCandidate", "campaign_lifecycle_refused"), hm
    for hm, row in out.items():
        if hm < BRAIN_FROM:
            continue
        assert row["calls"] == 1, hm
        assert row["offered"] == [(FORMATION_ID, True)], hm
        assert row["named"] == FORMATION_ID, hm
        if hm >= "03:07":
            assert row["lifecycle"] == "ACTIVE_DELIVERY", hm
            assert row["candidate"] == ("CANDIDATE", "bullish", FORMATION_ID,
                                        row["close"] + .25, 29508.0, 29545.0), hm


def test_post_capture_same_direction_release_retires_the_same_formation(tmp_path, monkeypatch):
    out = _run(tmp_path / "run", monkeypatch, _SAME, ecu=False)
    retained = (FORMATION_ID, "CURRENT_PROCESS_REVALIDATED")
    # Identical to the healthy tape through 02:59.
    assert out["02:59"]["custody"] == retained
    assert out["02:59"]["path"] == ("bullish", "active")
    assert out["02:59"]["load_bearing"] == (29508.0, "1m")
    # 03:00 closes below the bullish load-bearing low: the owner's own release,
    # raid 02:15 <= source 03:00 <= cutoff, retires the generation immediately.
    release = ("bullish", "1m", "03:00", "03:00")
    assert out["03:00"]["releases"] == OPPOSITE | {release}
    seen = [result for releases, result in out["03:00"]["consulted"] if release in releases]
    assert seen and all(result is False for result in seen)
    for hm in ("03:00", "03:01", "03:02"):
        assert out[hm]["custody"] is None, hm
        # No executable row and no row carrying the retired identity (a
        # fallback detection, if any, is published only as UNAVAILABLE).
        assert all(row == (False, None, UNAVAILABLE) for row in out[hm]["catalog"]), hm
