"""N1: lawful prefix eviction versus missing or insufficient rolling history.

The production loop hands ProductionScanCycle.scan a coherent window: at most
300 minutes, contiguous, with its start aligned UP to the next 15m boundary.
Once the provider is full, that alignment shortens the window by up to 14 bars
at every quarter hour (300 -> 286) and it regrows one bar a minute. At f822371
the rolling chronology refused any window shorter than the previous one, so
derived state went stale and retained formation custody was cleared at the
first quarter-hour step (CP3 / N1).

These cases drive the real cycle over the original S4C minute tape with a
rolling 150-bar window and then offer one more window. Lawful eviction (the
window shortened by at most one partial 15m bucket, still contiguous and
still connected to the processed tip) continues the chronology. A window
shorter than that, a missing minute, a backward tip or a rewritten bar does
not.
"""
import copy

import pytest
import test_reversal_foundation_proof_closure as RF
import test_scan_chronology_catchup as K
from market_data.reversal_formation import current_block

CAP = 150
# One partial 15m bucket: the most a coherent window can lose to alignment.
SLACK = 14
TIP = 170


def _rolling(cycle, end):
    rows = K.TAPE[max(0, end - CAP):end]
    return cycle.scan(rows, now=RF._now_for(rows), invoke_brain=False)


def _warm(tmp_path, monkeypatch):
    cycle = RF._cycle(tmp_path, monkeypatch)
    for end in range(5, TIP + 1):
        scan = _rolling(cycle, end)
    assert scan['snapshot']['derived_state']['current'] is True
    assert len(cycle._chronology_window) == CAP
    return cycle


def _offer(cycle, rows):
    return cycle.scan(rows, now=RF._now_for(rows), invoke_brain=False)


def _state(scan):
    return scan['snapshot']['derived_state']


def _count_po3_updates(cycle, monkeypatch):
    from structure.po3_alignment_manager import Po3StabilityManager
    calls = []
    original = Po3StabilityManager.update

    def counted(instance, results):
        if instance is cycle.po3_stability:
            calls.append(True)
        return original(instance, results)
    monkeypatch.setattr(Po3StabilityManager, 'update', counted)
    return calls


@pytest.mark.parametrize('missed', [0, 4])
def test_alignment_eviction_continues_the_chronology(tmp_path, monkeypatch, missed):
    cycle = _warm(tmp_path, monkeypatch)
    advances = _count_po3_updates(cycle, monkeypatch)
    end = TIP + 1 + missed
    # The window loses one full alignment step of leading bars while its tip
    # advances: contiguous, still covering the processed tip.
    rows = K.TAPE[end - (CAP - SLACK):end]
    assert len(rows) == CAP - SLACK and rows[0]['timestamp'] < K.TAPE[TIP - 1]['timestamp']
    state = _state(_offer(cycle, rows))
    assert state['current'] is True, state['coverage']
    assert state['coverage']['complete'] is True
    assert state['coverage']['catch_up_bars'] == missed
    assert cycle._processed_tip == rows[-1]['timestamp']
    # Each settled minute advances live mechanics exactly once.
    assert len(advances) == missed + 1
    # The next ordinary minute keeps growing from the shorter window.
    after = K.TAPE[end + 1 - (CAP - SLACK + 1):end + 1]
    assert _state(_offer(cycle, after))['current'] is True
    assert len(advances) == missed + 2


def test_window_shorter_than_one_alignment_step_is_insufficient_context(tmp_path, monkeypatch):
    cycle = _warm(tmp_path, monkeypatch)
    tip, window = cycle._processed_tip, copy.deepcopy(cycle._chronology_window)
    advances = _count_po3_updates(cycle, monkeypatch)
    end = TIP + 1
    rows = K.TAPE[end - (CAP - SLACK - 1):end]
    scan = _offer(cycle, rows)
    state = _state(scan)
    assert state['current'] is False
    assert state['coverage']['complete'] is False
    assert 'rolling_context_unavailable' in state['coverage']['reason']
    assert scan['snapshot']['active_path_state']['state_available'] is False
    assert current_block(scan['snapshot'], 'bullish') is None
    assert advances == []
    # Refusal leaves the processed chronology exactly where it was ...
    assert cycle._processed_tip == tip and cycle._chronology_window == window
    # ... and a full window resumes it without crediting the refused minute
    # retroactively: that minute is caught up at the actual later cutoff.
    resumed = _rolling(cycle, end + 1)
    assert _state(resumed)['current'] is True
    assert _state(resumed)['coverage']['catch_up_bars'] == 1
    assert len(advances) == 2


@pytest.mark.parametrize('case', ['missing-catch-up-minute', 'hole-in-new-span',
                                  'hole-in-shared-span', 'backward-tip'])
def test_missing_or_regressed_history_is_not_eviction(tmp_path, monkeypatch, case):
    cycle = _warm(tmp_path, monkeypatch)
    lawful = CAP - SLACK
    if case == 'missing-catch-up-minute':
        # The window starts after the first unprocessed minute.
        rows, reason = K.TAPE[TIP + 1:TIP + 4], 'missing_prefix_after_processed_tip'
    elif case == 'hole-in-new-span':
        rows = K.TAPE[TIP + 4 - lawful:TIP + 4]
        del rows[-2]
        reason = 'canonical_tape_not_contiguous'
    elif case == 'hole-in-shared-span':
        rows = K.TAPE[TIP + 1 - lawful:TIP + 1]
        del rows[len(rows) // 2]
        reason = None  # a removal inside the overlap is a history revision
    else:
        rows, reason = K.TAPE[TIP - 1 - CAP:TIP - 1], 'canonical_cutoff_before_processed_tip'
    scan = _offer(cycle, rows)
    state = _state(scan)
    assert state['current'] is False, case
    assert scan['snapshot']['active_path_state']['state_available'] is False
    assert current_block(scan['snapshot'], 'bullish') is None
    if reason:
        assert reason in state['coverage']['reason'], state['coverage']
    else:
        assert state['history_revision'] == 1
        assert 'canonical_tape_not_contiguous' in cycle.rebuilds[-1]['error']


def test_rewritten_shared_bar_rebuilds_without_old_revision_authority(tmp_path, monkeypatch):
    cycle = _warm(tmp_path, monkeypatch)
    old_path = cycle._active_path
    old_custody = cycle.reversal_formation_custody
    rows = copy.deepcopy(K.TAPE[TIP + 1 - (CAP - SLACK):TIP + 1])
    rows[len(rows) // 2]['close'] += 0.25
    rows[len(rows) // 2]['high'] = max(rows[len(rows) // 2]['high'], rows[len(rows) // 2]['close'])
    scan = _offer(cycle, rows)
    state = _state(scan)
    # The rewrite is HistoryRevision's, not eviction. This 136-bar window does
    # not cover the session's witnessed occurrences, so the existing rebuild
    # contract refuses it; nothing minted under revision 0 stays consumable.
    assert state['history_revision'] == 1
    rebuilt = cycle.rebuilds[-1]
    assert rebuilt['revision'] == 1 and rebuilt['ok'] is False
    assert 'rebuild_ledger_coverage_incomplete' in rebuilt['error']
    assert state['current'] is False
    assert scan['snapshot']['active_path_state']['state_available'] is False
    assert current_block(scan['snapshot'], 'bullish') is None
    assert not cycle.reversal_formation_custody._records
    # A window that does cover the session rebuilds under revision 1 only.
    full = copy.deepcopy(K.TAPE[:TIP + 1])
    full[-len(rows):] = rows
    scan = _offer(cycle, full)
    assert _state(scan)['current'] is True and _state(scan)['history_revision'] == 1
    assert cycle.rebuilds[-1]['ok'] is True and cycle.rebuilds[-1]['revision'] == 1
    assert cycle._active_path is not old_path
    assert cycle.reversal_formation_custody is not old_custody
    assert all(record.get('history_revision') == 1
               for record in cycle.reversal_formation_custody._records.values())
