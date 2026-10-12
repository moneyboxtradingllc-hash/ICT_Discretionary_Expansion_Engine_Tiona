"""Settled-prefix chronology through real detectors; no injected authority.

Keep the original S4C minute tape here, independent of refounded positive
fixtures. Its bearish releases must not retire the bullish formation.
"""
import copy
from datetime import datetime, timedelta

import pytest
import test_reversal_foundation_proof_closure as RF
import test_po3_episode_retirement as E
from market_data.reversal_formation import current_block


def _original_expand(row):
    hhmm, o, h, low, c = row
    start = datetime.fromisoformat(f"2026-08-19T{hhmm}:00+00:00")
    middle = (low + c) / 2
    values = [(o, h, min(o, c), o), (o, max(o, c), low, low),
              (low, max(low, middle), min(low, middle), middle),
              (middle, max(middle, c), min(middle, c), c), (c, c, c, c)]
    return [dict(timestamp=(start + timedelta(minutes=i)).isoformat(),
                 open=a, high=b, low=d, close=e, volume=10, contract=RF.CONTRACT)
            for i, (a, b, d, e) in enumerate(values)]


TAPE = [bar for row in RF.RAW_5M for bar in _original_expand(row)] + E.EXT
BASE = len(RF.TAPE_1M)


def _facts(cycle, scan):
    snap = scan['snapshot']
    # Observation timestamps and scan counters describe actual scheduling;
    # authority compares source events, identities and full release history.
    return copy.deepcopy(dict(
        path=snap['active_path_state'], releases=cycle._active_path.releases,
        support=cycle._current_chronology_occurrences(),
        protected=snap['protected_swings'],
        records=cycle.reversal_formation_custody._records,
        block=current_block(snap, 'bullish')))


def _scan(cycle, end):
    rows = TAPE[:end]
    return cycle.scan(rows, now=RF._now_for(rows), invoke_brain=False)


@pytest.fixture(scope='module')
def minute_oracle(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        cycle = RF._cycle(tmp_path_factory.mktemp('minute-oracle'), mp)
        facts = {}
        for end in range(5, len(TAPE) + 1):
            facts[end] = _facts(cycle, _scan(cycle, end))
        assert len(facts[len(TAPE)]['releases']) == 4
        assert {r['owner'] for r in facts[len(TAPE)]['releases']} == {'bearish'}
        assert facts[len(TAPE)]['block']['validation_timestamp'] == '2026-08-19T02:20:00+00:00'
        yield facts


@pytest.mark.parametrize('cadence', ['five-minute', 'jump', '03:39', '03:44', '03:51'])
def test_every_common_cutoff_matches_minute_chronology(tmp_path, monkeypatch, minute_oracle, cadence):
    cycle = RF._cycle(tmp_path, monkeypatch)
    if cadence == 'five-minute':
        ends = list(range(5, len(TAPE) + 1, 5)) + [len(TAPE)]
    elif cadence == 'jump':
        ends = [BASE, len(TAPE)]
    else:
        ends = [end for end in range(5, len(TAPE) + 1)
                if TAPE[end-1]['timestamp'][11:16] != cadence]
    for end in sorted(set(ends)):
        scan = _scan(cycle, end)
        assert scan['snapshot']['derived_state']['current'] is True
        assert _facts(cycle, scan) == minute_oracle[end], (cadence, TAPE[end-1]['timestamp'])


def test_cold_replay_adopts_real_path_and_positive_support(tmp_path, monkeypatch, minute_oracle):
    cycle = RF._cycle(tmp_path, monkeypatch)
    before = copy.deepcopy(cycle.occurrence_ledger.occurrences())
    rebuilt = cycle._rebuild_derived_state(TAPE, cycle._history.revision)
    assert rebuilt['ok'] is True
    assert rebuilt['derived'] == len(TAPE)
    assert cycle._active_path is not None and len(cycle._active_path.releases) == 4
    assert cycle.occurrence_ledger.occurrences() == before
    scan = _scan(cycle, len(TAPE))
    assert current_block(scan['snapshot'], 'bullish') is not None
    assert _facts(cycle, scan) == minute_oracle[len(TAPE)]
    # A retry may neither re-ingest nor re-birth source support.
    assert _facts(cycle, _scan(cycle, len(TAPE))) == minute_oracle[len(TAPE)]


@pytest.mark.parametrize('ecu', [True, False])
def test_missing_rolling_prefix_refuses_both_cognition_lanes(tmp_path, monkeypatch, ecu):
    cycle = RF._cycle(tmp_path, monkeypatch)
    _scan(cycle, BASE)
    calls = []
    RF._mock_current_brain(monkeypatch, calls)
    monkeypatch.setenv('BRAIN_ECU_MODE', 'true' if ecu else 'false')
    rows = TAPE[BASE+2:]
    scan = cycle.scan(rows, now=RF._now_for(rows))
    snap = scan['snapshot']
    assert snap['derived_state']['current'] is False
    assert snap['derived_state']['coverage']['complete'] is False
    assert 'missing_prefix_after_processed_tip' in snap['derived_state']['coverage']['reason']
    assert snap['active_path_state']['state_available'] is False
    assert current_block(snap, 'bullish') is None
    assert not [r for r in RF.authorized_tool_catalog(snap)
                if r['tool_family'] == 'po3_reversal_order_block']
    with pytest.raises(RF.NoCandidate):
        RF._produce_candidate(scan)


@pytest.mark.parametrize('ecu', [True, False])
def test_jump_finishes_chronology_before_single_brain_call(tmp_path, monkeypatch, ecu, minute_oracle):
    cycle = RF._cycle(tmp_path, monkeypatch)
    _scan(cycle, BASE)
    calls = []
    RF._mock_current_brain(monkeypatch, calls)
    monkeypatch.setenv('BRAIN_ECU_MODE', 'true' if ecu else 'false')
    rows = TAPE
    scan = cycle.scan(rows, now=RF._now_for(rows))
    assert len(calls) == 1
    assert _facts(cycle, scan) == minute_oracle[len(TAPE)]
    assert calls[0]['active_path_state'] == minute_oracle[len(TAPE)]['path']
    assert calls[0]['derived_state']['current'] is True
    assert scan['snapshot']['derived_state']['coverage']['catch_up_bars'] == len(TAPE)-BASE-1
    # Newly witnessed catch-up facts retain the actual observation cutoff.
    catch_up = [r for r in cycle.occurrence_ledger.occurrences()
                if r.get('observation_basis') == 'catch_up_canonical_prefix']
    assert catch_up and {r['catch_up_observed_at'] for r in catch_up} == {TAPE[-1]['timestamp']}


def test_restart_requires_coverage_of_witnessed_session(tmp_path, monkeypatch, minute_oracle):
    cycle = RF._cycle(tmp_path, monkeypatch)
    # Observe the early session in this process, rather than deriving it only
    # in the write-free cold bootstrap at BASE.
    _scan(cycle, 5)
    _scan(cycle, BASE)
    _scan(cycle, len(TAPE))
    witnessed = copy.deepcopy(cycle.occurrence_ledger.occurrences())
    assert witnessed
    restarted = RF._cycle(tmp_path, monkeypatch)
    key = lambda row: (row['event_time'], row['occurrence_id'])
    assert sorted(restarted.occurrence_ledger.occurrences(), key=key) == sorted(witnessed, key=key)
    scan = _scan(restarted, len(TAPE))
    assert _facts(restarted, scan) == minute_oracle[len(TAPE)]
    assert sorted(restarted.occurrence_ledger.occurrences(), key=key) == sorted(witnessed, key=key)
    incomplete = RF._cycle(tmp_path, monkeypatch)
    rows = TAPE[BASE:]
    from market_data.object_identity import canonical_instant
    assert min(canonical_instant(r['event_time'], strict=True) for r in witnessed) < rows[0]['timestamp']
    refused = incomplete.scan(rows, now=RF._now_for(rows), invoke_brain=False)
    state = refused['snapshot']['derived_state']
    assert state['current'] is False and state['coverage']['complete'] is False
    assert 'restart_ledger_coverage_incomplete' in state['coverage']['reason']
    assert refused['snapshot']['active_path_state']['state_available'] is False
    assert current_block(refused['snapshot'], 'bullish') is None


def test_rebuild_rejects_hole_and_revokes_prior_view(tmp_path, monkeypatch):
    cycle = RF._cycle(tmp_path, monkeypatch)
    before = _scan(cycle, BASE)
    assert current_block(before['snapshot'], 'bullish') is not None
    hole = TAPE[:BASE-2] + TAPE[BASE-1:BASE]
    rebuilt = cycle._rebuild_derived_state(hole, cycle._history.revision)
    assert rebuilt['ok'] is False
    assert 'canonical_tape_not_contiguous' in rebuilt['error']
    assert cycle.derived_state_is_current() is False
    assert current_block(before['snapshot'], 'bullish') is None


def test_failed_same_revision_rebuild_stays_closed_until_covered_retry(tmp_path, monkeypatch, minute_oracle):
    cycle = RF._cycle(tmp_path, monkeypatch)
    _scan(cycle, 5)
    _scan(cycle, BASE)
    before = _scan(cycle, len(TAPE))
    assert current_block(before['snapshot'], 'bullish') is not None
    witnessed = copy.deepcopy(cycle.occurrence_ledger.occurrences())
    rows = TAPE[BASE:]
    from market_data.object_identity import canonical_instant
    assert min(canonical_instant(r['event_time'], strict=True) for r in witnessed) < rows[0]['timestamp']
    rebuilt = cycle._rebuild_derived_state(rows, cycle._history.revision)
    assert rebuilt['ok'] is False
    assert 'rebuild_ledger_coverage_incomplete' in rebuilt['error']
    assert cycle.derived_state_is_current() is False
    assert current_block(before['snapshot'], 'bullish') is None
    # Unchanged revision is not permission to reopen a failed reconstruction.
    refused = cycle.scan(rows, now=RF._now_for(rows), invoke_brain=False)
    assert refused['snapshot']['derived_state']['current'] is False
    assert current_block(refused['snapshot'], 'bullish') is None
    key = lambda row: (row['event_time'], row['occurrence_id'])
    assert sorted(cycle.occurrence_ledger.occurrences(), key=key) == sorted(witnessed, key=key)
    recovered = _scan(cycle, len(TAPE))
    assert recovered['snapshot']['derived_state']['current'] is True
    assert _facts(cycle, recovered) == minute_oracle[len(TAPE)]


def test_rolling_window_jump_matches_actual_rolling_minute_context(tmp_path, monkeypatch):
    cap = 150
    minute = RF._cycle(tmp_path / 'minute', monkeypatch)
    for end in range(5, len(TAPE)+1):
        rows = TAPE[max(0,end-cap):end]
        reference = minute.scan(rows, now=RF._now_for(rows), invoke_brain=False)
    expected = _facts(minute, reference)
    jump = RF._cycle(tmp_path / 'jump', monkeypatch)
    initial = TAPE[:BASE]
    jump.scan(initial, now=RF._now_for(initial), invoke_brain=False)
    rows = TAPE[-cap:]
    actual = jump.scan(rows, now=RF._now_for(rows), invoke_brain=False)
    assert actual['snapshot']['derived_state']['current'] is True
    assert _facts(jump, actual) == expected


@pytest.mark.parametrize('deep', [False, True])
def test_each_prefix_receives_only_its_actual_optional_context(tmp_path, monkeypatch, deep):
    import live_scan.production_scan_cycle as PC
    calls = []
    original = PC.build_snapshot
    def observed(data, **kwargs):
        calls.append(copy.deepcopy(kwargs.get('deep_1m')))
        return original(data, **kwargs)
    monkeypatch.setattr(PC, 'build_snapshot', observed)
    cycle = RF._cycle(tmp_path, monkeypatch)
    rows = TAPE[:10]
    supplied = TAPE[:20] if deep else None
    cycle.scan(rows, now=RF._now_for(rows), deep_1m=supplied, invoke_brain=False)
    assert len(calls) == 10
    assert calls == [TAPE[:end] if deep else None for end in range(1,11)]


def test_rebuild_terminal_and_retry_do_not_advance_live_stability_twice(tmp_path, monkeypatch):
    from structure.po3_alignment_manager import Po3StabilityManager
    cycle = RF._cycle(tmp_path, monkeypatch)
    calls = []
    original = Po3StabilityManager.update
    def counted(instance, results):
        if instance is cycle.po3_stability:
            calls.append(True)
        return original(instance, results)
    monkeypatch.setattr(Po3StabilityManager, 'update', counted)
    rows = TAPE[:20]
    assert cycle._rebuild_derived_state(rows, cycle._history.revision)['ok'] is True
    assert len(calls) == 20
    before = copy.deepcopy(vars(cycle.po3_stability))
    first = cycle.scan(rows, now=RF._now_for(rows), invoke_brain=False)
    retry = cycle.scan(rows, now=RF._now_for(rows), invoke_brain=False)
    assert len(calls) == 20
    assert vars(cycle.po3_stability) == before
    assert first['snapshot']['po3'] == retry['snapshot']['po3']
