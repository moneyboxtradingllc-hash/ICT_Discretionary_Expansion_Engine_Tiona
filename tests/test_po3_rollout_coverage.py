"""Rolling-window rollout of a retained PO3 formation's witnesses is not a deletion.

Stage 4 obligation D (long rolling-window depth / eviction). Production scans
receive only the latest 1m bars (topstepx_production_loop: lookback_bars=300).
As the window slides, the 5m bucket holding the oldest 1m bar is aggregated
from a truncated set of constituents (members 4/5, complete False) for exactly
the minutes until its last constituent leaves. ReversalFormationCustody
compares the formation's witness bars by digest and already treats a witness
BEFORE coverage as ordinary rollout -- but the truncated leading bucket was
counted as coverage, so its digest mismatch revoked a healthy formation whose
anchor, sweep and leg were all intact (measured on the 300-bar window at
19:35 for the S4I p2h formation, and below on a 120-bar window).

Coverage now starts at the first whole bucket. A truncated, missing or
different INTERIOR witness, a complete leading witness that disagrees, and a
witness beyond coverage are still deletions/restatements and still revoke.
Custody cannot see which constituents a truncated bucket lost, so a minute
deleted from inside the leading bucket is caught one layer earlier: the
production HistoryRevision bumps on a removal inside consecutive windows'
overlap, and custody refuses any other revision.
"""
import copy
from datetime import datetime, timedelta

import pytest

import test_campaign_scope as T
import test_po3_execution_identity as X
from market_data.reversal_formation import ReversalFormationCustody, current_block

FORMATION_ID = X.EXPECTED_ID
WINDOW = 120                      # production passes 300; the mechanism is the same


def _quiet_tail(n):
    """Monotone, non-raiding 1m bars after 15:04: no sweep, no swing, no release."""
    rows, high = [], 29505.0
    start = datetime.fromisoformat("2026-08-19T15:05:00+00:00")
    for i in range(n):
        rows.append(((start + timedelta(minutes=i)).strftime("%H:%M"), high, high - 1.0, high - 0.75))
        high -= 0.25
    return rows


def test_rollout_of_the_leading_witness_bucket_keeps_the_formation(tmp_path, monkeypatch):
    from live_scan.production_scan_cycle import ProductionScanCycle
    X._isolate(tmp_path, monkeypatch)
    head = T._tape()[:106]
    tape = head + X._bars(list(X._P2H) + _quiet_tail(120), head[-1]["close"])
    cycle = ProductionScanCycle(symbol="MNQ", contract_id=T.CONTRACT, session_id="S4-D-ROLLOUT")
    rows = []
    for end in range(20, len(tape) + 1):
        bars = tape[max(0, end - WINDOW):end]
        scan = cycle.scan(bars, now=datetime.fromisoformat(bars[-1]["timestamp"]) + timedelta(minutes=1),
                          invoke_brain=False)
        snap = scan["snapshot"]
        five = (snap.get("timeframes") or {}).get("5m", {}).get("recent_candles") or []
        block = current_block(snap, "bearish")
        records = list(cycle.reversal_formation_custody._records.values())
        rows.append({
            "hm": bars[-1]["timestamp"][11:16], "first": bars[0]["timestamp"][11:16],
            "custody": ((block or {}).get("formation_authority") or {}).get("occurrence_id") if block else None,
            "catalog": [(r["execution_eligible"], r["occurrence_id"]) for r in X._po3(snap)],
            "witnesses": sorted((records[0].get("witness_bars") or {})) if records else [],
            "leading_5m": (five[0].get("timestamp", "")[11:16], five[0].get("members")) if five else None,
        })
    retained = [row for row in rows if row["hm"] >= "14:59"]
    # The formation is captured on the 14:59 scan and its witnesses include
    # 5m buckets that this window rolls out.
    assert retained[0]["custody"] == FORMATION_ID
    witnesses = retained[0]["witnesses"]
    assert "2026-08-19T14:35:00+00:00" in witnesses
    # Non-vacuous: the window does truncate that witness bucket while it is
    # still the leading 5m bucket (window starting 14:36 .. 14:39) ...
    truncated = [row for row in retained if row["first"] in ("14:36", "14:37", "14:38", "14:39")]
    assert [row["leading_5m"] for row in truncated] == [("14:35", 4), ("14:35", 3), ("14:35", 2), ("14:35", 1)]
    # ... and every later witness bucket is rolled out the same way.
    assert retained[-1]["first"] > max(stamp[11:16] for stamp in witnesses)
    # Rollout never revokes: same identity, executable, on every scan.
    for row in retained:
        assert row["custody"] == FORMATION_ID, row
        assert row["catalog"] == [(True, FORMATION_ID)], row


def _live_check(tmp_path, monkeypatch):
    """The real custody check, captured on the healthy p2h scan at 15:01."""
    captured = {}
    real = ReversalFormationCustody._still_current

    def spy(self, snapshot, record, revision, contract, session, canonical_timeframes, releases=None):
        result = real(self, snapshot, record, revision, contract, session, canonical_timeframes, releases)
        if record.get("direction") == "bearish" and result:
            captured["call"] = (self, snapshot, record, revision, contract, session,
                                copy.deepcopy(canonical_timeframes), releases)
        return result
    monkeypatch.setattr(ReversalFormationCustody, "_still_current", spy)
    X._brainless(tmp_path, monkeypatch, "p2h", stop="15:01")
    monkeypatch.setattr(ReversalFormationCustody, "_still_current", real)
    self, snapshot, record, revision, contract, session, timeframes, releases = captured["call"]

    def check(five):
        frames = copy.deepcopy(timeframes)
        frames[record["source_tf"]] = five
        return real(self, snapshot, record, revision, contract, session, frames, releases)
    return record, timeframes[record["source_tf"]], check


def _truncated(row, **changes):
    out = dict(row, members=4, expected_members=5, complete=False)
    out.update(changes)
    return out


def test_only_the_leading_bucket_is_excused_and_only_as_rollout(tmp_path, monkeypatch):
    record, five, check = _live_check(tmp_path, monkeypatch)
    stamps = sorted(record["witness_bars"])
    first = stamps[0]
    index = next(i for i, row in enumerate(five) if row.get("timestamp") == first)
    assert index > 0, "the earliest witness must have earlier coverage for the interior cases"
    witness = five[index]
    rewritten = dict(witness, open=witness["open"] + 3.5, low=witness["low"] + 2.25)
    assert check(five) is True
    # Rollout: the earliest witness is now the truncated LEADING bucket.
    assert check([_truncated(rewritten)] + five[index + 1:]) is True
    # A leading bucket that is whole but different is a restatement.
    assert check([dict(rewritten, members=5, expected_members=5, complete=True)] + five[index + 1:]) is False
    # Interior truncation, interior deletion and interior rewrite stay deletions.
    assert check(five[:index] + [_truncated(rewritten)] + five[index + 1:]) is False
    assert check(five[:index] + five[index + 1:]) is False
    assert check(five[:index] + [rewritten] + five[index + 1:]) is False
    # A witness beyond coverage is not rollout.
    last = stamps[-1]
    assert check([row for row in five if row.get("timestamp") < last]) is False


@pytest.mark.parametrize("deleted", [False, True], ids=["rollout", "interior_deletion"])
def test_a_deleted_minute_inside_the_truncated_leading_bucket_still_revokes(
        tmp_path, monkeypatch, deleted):
    """The leading-bucket excuse cannot hide a deletion. Custody alone cannot
    tell which constituents a truncated bucket lost, so a minute deleted from
    the middle of the leading bucket must be caught where it happens: the
    production HistoryRevision compares consecutive windows and bumps on a
    timestamp removed inside their overlap, and custody refuses any revision
    other than its record's."""
    from live_scan.production_scan_cycle import ProductionScanCycle
    X._isolate(tmp_path, monkeypatch)
    head = T._tape()[:106]
    tape = head + X._bars(list(X._P2H) + _quiet_tail(120), head[-1]["close"])
    cycle = ProductionScanCycle(symbol="MNQ", contract_id=T.CONTRACT, session_id="S4-D-DELETE")
    rows = []
    for end in range(20, len(tape) + 1):
        bars = tape[max(0, end - WINDOW):end]
        if bars[0]["timestamp"][11:16] == "14:37":
            if deleted:
                bars = [bar for bar in bars if bar["timestamp"][11:16] != "14:38"]
            scan = cycle.scan(bars, now=datetime.fromisoformat(bars[-1]["timestamp"]) + timedelta(minutes=1),
                              invoke_brain=False)
            snap = scan["snapshot"]
            five = (snap.get("timeframes") or {}).get("5m", {}).get("recent_candles") or []
            block = current_block(snap, "bearish")
            rows.append({"leading_5m": (five[0]["timestamp"][11:16], five[0].get("members")),
                         "revision": snap["derived_state"]["history_revision"],
                         "custody": ((block or {}).get("formation_authority") or {}).get("occurrence_id")
                         if block else None})
            break
        scan = cycle.scan(bars, now=datetime.fromisoformat(bars[-1]["timestamp"]) + timedelta(minutes=1),
                          invoke_brain=False)
        if bars[0]["timestamp"][11:16] == "14:36":
            snap = scan["snapshot"]
            block = current_block(snap, "bearish")
            assert ((block or {}).get("formation_authority") or {}).get("occurrence_id") == FORMATION_ID
    (row,) = rows
    if not deleted:
        # Ordinary rollout: 14:35 leads with 3 of 5 members, same revision, kept.
        assert row == {"leading_5m": ("14:35", 3), "revision": 0, "custody": FORMATION_ID}
    else:
        # The same truncated leading bucket, now missing 14:38 from its middle:
        # the canonical history revises and the formation is revoked.
        assert row == {"leading_5m": ("14:35", 2), "revision": 1, "custody": None}
