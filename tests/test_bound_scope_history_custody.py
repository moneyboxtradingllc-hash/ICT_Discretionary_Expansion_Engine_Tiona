"""S4-09 on a BOUND campaign: history, restart and custody cells.

Existing permanent tests prove these attacks on unbound or same-life tapes
(test_campaign_draw_temporal_authority, test_campaign_scope,
test_po3_episode_retirement, test_conditional_plan_authority,
test_po3_reversal_order_block). Here the same attacks are driven through the
real ProductionScanCycle while a campaign is ACTIVE on the 15m premise and
the participating formation sits on a distinct 5m life (the CONSTRUCTED
tape of test_po3_distinct_anchor_premise):

  * a duplicate settled cutoff repeats the scan without advancing custody;
  * a provider restatement of the formation's own raid bar, delivered later,
    raises the history revision and voids scope, Draw and formation exactly
    then -- never earlier, never by append;
  * a JSON copy of the live snapshot carries no scope or formation custody;
  * a new process replaying the same settled prefix earns the same exact
    formation from lawful history at the same numeric revision, yet never
    restores the campaign scope a Brain proposal established.
"""
import copy
import json
from datetime import datetime, timedelta

import pytest

import test_po3_distinct_anchor_premise as W
from market_data.campaign_scope import read_current_campaign_scope

ACTIVE = ("ACTIVE", "ACTIVE", "bearish", "INTACT")


def _index(tape, hhmm):
    return next(i for i, bar in enumerate(tape) if bar["timestamp"][11:16] == hhmm) + 1


def _session_to(root, monkeypatch, hhmm, *, ecu):
    cycle, tape, scan, first = W._prime(root, monkeypatch, W._HEALTHY, ecu=ecu)
    last = _index(tape, hhmm)
    result = None
    for end in range(first, last + 1):
        result = scan(end, True)
    return cycle, tape, scan, last, result


def _scan_bars(cycle, bars):
    return cycle.scan(bars, now=datetime.fromisoformat(bars[-1]["timestamp"]) + timedelta(minutes=1),
                      invoke_brain=True)


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_duplicate_settled_cutoff_repeats_without_advancing_bound_custody(tmp_path, monkeypatch, ecu):
    cycle, tape, scan, last, first_scan = _session_to(tmp_path / "s", monkeypatch, "16:39", ecu=ecu)
    first = W._row(first_scan, cycle)
    scope_first = read_current_campaign_scope(first_scan["snapshot"])
    revision = cycle._history.revision
    repeat = scan(last, True)
    again = W._row(repeat, cycle)
    scope_again = read_current_campaign_scope(repeat["snapshot"])
    assert first["scope"] == ACTIVE and first["candidate"][:2] == ("CANDIDATE", W.FORMATION_ID)
    assert again == first
    assert scope_again == scope_first
    assert scope_again["last_transition"]["cutoff"] == "2026-08-19T15:45:00+00:00"
    assert cycle._history.revision == revision


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_provider_restatement_voids_bound_scope_and_formation_at_the_revision(tmp_path, monkeypatch, ecu):
    results = {}
    for name in ("healthy", "restated"):
        cycle, tape, scan, last, before = _session_to(tmp_path / name, monkeypatch, "16:39", ecu=ecu)
        bars = copy.deepcopy(tape[:last + 1])                              # 16:40 arrives
        if name == "restated":
            raid = next(bar for bar in bars if bar["timestamp"][11:16] == "16:15")
            raid["high"] = W.BASE + 18.25                                  # the 5m raid never happened
        results[name] = (W._row(before, cycle), cycle._history.revision,
                         W._row(_scan_bars(cycle, bars), cycle), cycle._history.revision)
    healthy, restated = results["healthy"], results["restated"]
    # Before the corrected release both twins hold identical authority at revision 0.
    assert healthy[0] == restated[0] and healthy[1] == restated[1] == 0
    assert restated[0]["scope"] == ACTIVE and restated[0]["custody"] == W.FORMATION_ID
    # The ordinary next minute keeps everything; the restated history is a new
    # revision that voids the bound scope, its Draw and the formation together.
    assert healthy[3] == 0 and healthy[2]["scope"] == ACTIVE
    assert healthy[2]["candidate"][:2] == ("CANDIDATE", W.FORMATION_ID)
    assert restated[3] == 1
    assert restated[2]["scope"][0] == "UNBOUND" and restated[2]["premise"] != "INTACT"
    assert restated[2]["custody"] is None and restated[2]["executable"] == []
    assert restated[2]["lifecycle"][1] is False
    assert restated[2]["candidate"][0] == "NoCandidate"


def test_json_copy_of_the_live_snapshot_carries_no_custody(tmp_path, monkeypatch):
    cycle, tape, scan, last, live = _session_to(tmp_path / "s", monkeypatch, "16:39", ecu=False)
    assert read_current_campaign_scope(live["snapshot"])["state"] == "ACTIVE"
    assert W.current_block(live["snapshot"], "bearish")["formation_authority"]["occurrence_id"] == W.FORMATION_ID
    restored = json.loads(json.dumps(live["snapshot"], default=str))
    assert (read_current_campaign_scope(restored) or {}).get("state") != "ACTIVE"
    assert W.current_block(restored, "bearish") is None
    copied = {**live, "snapshot": restored}
    row = W._row(copied, cycle)
    assert row["custody"] is None and row["executable"] == []
    assert row["candidate"][0] == "NoCandidate"


def test_new_process_replay_earns_the_formation_but_never_restores_scope(tmp_path, monkeypatch):
    """Lane-independent: the replay is brainless, so no cognition transport
    (ECU or non-ECU) runs; scope can only come from a new primary proposal."""
    cycle, tape, scan, last, live = _session_to(tmp_path / "old", monkeypatch, "16:44", ecu=False)
    old = W._row(live, cycle)
    assert old["scope"] == ACTIVE and old["custody"] == W.FORMATION_ID
    fresh, fresh_tape, fresh_scan, first = W._prime(tmp_path / "new", monkeypatch, W._HEALTHY, ecu=False,
                                                    brain=False)
    result = None
    for end in range(first, len(fresh_tape) + 1):
        result = fresh_scan(end, False)
    new = W._row(result, fresh)
    assert fresh._history.revision == cycle._history.revision == 0
    assert new["custody"] == W.FORMATION_ID and new["anchor_life"] == W.ANCHOR
    assert new["highs"]["15m"] == W.PREMISE
    assert new["scope"][0] == "UNBOUND"
    assert new["candidate"][0] == "NoCandidate"


# Activated controls: each mutant removes one boundary the cells above rely
# on, and the decisive assertion must fail on it.

def test_control_revision_skip_keeps_stale_bound_authority(tmp_path, monkeypatch):
    """T06 mutant: a restated settled bar is folded in without a new revision."""
    from data_feed import candle_continuity as CONT
    original = CONT.HistoryRevision.observe

    def skipping(self, candles):
        before = self.revision
        after = original(self, candles)
        if after > before:
            self.revision = before
            return before
        return after
    monkeypatch.setattr(CONT.HistoryRevision, "observe", skipping)
    with pytest.raises(AssertionError):
        test_provider_restatement_voids_bound_scope_and_formation_at_the_revision(
            tmp_path, monkeypatch, False)
    cycle, tape, scan, last, _ = _session_to(tmp_path / "probe", monkeypatch, "16:39", ecu=False)
    bars = copy.deepcopy(tape[:last + 1])
    next(bar for bar in bars if bar["timestamp"][11:16] == "16:15")["high"] = W.BASE + 18.25
    stale = W._row(_scan_bars(cycle, bars), cycle)
    # Killed at the decisive boundary: without the revision the bound scope
    # survives the corrected history. The formation is still revoked by its
    # own settled-bar witness revalidation -- an independent second defense,
    # which is why the revision is the scope's only protection here.
    assert cycle._history.revision == 0
    assert stale["scope"] == ACTIVE and stale["premise"] == "INTACT"
    assert stale["custody"] is None


def test_control_trusting_a_serialized_formation_view_is_detected(tmp_path, monkeypatch):
    """T07 mutant: a JSON copy of the formation view is accepted as custody."""
    import market_data.reversal_formation as RFM
    original = RFM.current_block

    def trusting(snapshot, direction):
        block = original(snapshot, direction)
        if block is not None:
            return block
        rows = ((snapshot or {}).get("reversal_formation_view") or {}).get(direction) or {}
        for record in rows.values():
            if isinstance(record, dict) and (record.get("block") or {}).get("available"):
                block = copy.deepcopy(record["block"])
                block["formation_authority"] = {"status": "CURRENT_PROCESS_REVALIDATED",
                                                "occurrence_id": record.get("occurrence_id"),
                                                "anchor_identity": copy.deepcopy(record.get("anchor_identity"))}
                return block
        return None
    monkeypatch.setattr(RFM, "current_block", trusting)
    monkeypatch.setattr(W, "current_block", trusting)
    with pytest.raises(AssertionError):
        test_json_copy_of_the_live_snapshot_carries_no_custody(tmp_path, monkeypatch)
    cycle, tape, scan, last, live = _session_to(tmp_path / "probe", monkeypatch, "16:39", ecu=False)
    restored = json.loads(json.dumps(live["snapshot"], default=str))
    row = W._row({**live, "snapshot": restored}, cycle)
    # Killed at the decisive boundary: the real PO3 catalog consumer now
    # publishes the serialized formation as an executable row.
    assert row["executable"] == [W.FORMATION_ID]
