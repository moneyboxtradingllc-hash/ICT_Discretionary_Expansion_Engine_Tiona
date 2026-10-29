"""Affirmative entry permission without changing historical opportunity law."""
import copy
import json
from pathlib import Path

import pytest
import test_luna_candidate_producer as T
from broker.luna_candidate_producer import CandidateProducer, NoCandidate


@pytest.mark.parametrize('action', ['propose_entry', 'enter'])
def test_explicit_entries_keep_original_geometry(action):
    c = T.produce(res=T.result(parsed=T.parsed(current_action=action)))
    assert c.direction == 'bullish'
    assert c.invalidation_price == 29875.0
    assert c.objective.price == 29910.25


@pytest.mark.parametrize('action', [None, '', {}, 'await_retest', 'something',
    'watching: authorize only on retest; do not enter at current price',
    'enter on retest', 'propose bearish entry', 'stand_down'])
def test_prose_missing_or_negative_action_never_creates_immediate_candidate(action):
    with pytest.raises(NoCandidate):
        T.produce(res=T.result(parsed=T.parsed(current_action=action)))


def test_watching_still_publishes_plan_and_revalidates_trigger():
    res = T.result(parsed=T.parsed(current_action='watching',
                                  plan_expires_at='2026-08-05T15:31:00+00:00'))
    with pytest.raises(NoCandidate, match='conditional_plan_mode_required'):
        T.produce(res=res)
    plan = T.produce(res=res, conditional_plan=True)
    assert plan.extras['conditional_plan'] is True
    # Existing trigger qualifications, not action alone, own candidate eligibility.
    trigger = T.produce(res=res, conditional_trigger=True)
    assert trigger.direction == plan.direction


@pytest.mark.parametrize('case', ['continuation','counterflow','contested_same_direction'])
def test_original_local_paths_keep_participation(case):
    # Frozen paired input from the independently recorded Oct-2 regression.
    fixture = Path(__file__).with_name('restoration_paired_inputs.json')
    world = json.loads(fixture.read_text())[case]
    snap = T._detected('ifvg','fvg')
    snap.update(timestamp='2026-08-05T15:29:00+00:00',active_path_state=world['path'])
    bi = T.brain_input()
    bi['narrative_continuity'] = copy.deepcopy(world['continuity'])
    c = T.produce(res=T.result(parsed=T.parsed(current_action='propose_entry')),
                  snapshot=snap,bi=bi)
    assert c.direction == 'bullish'


def test_activated_broken_action_gate_reproduces_unsafe_candidate(monkeypatch):
    parsed = T.parsed(current_action='watching: do not enter now')
    with pytest.raises(NoCandidate, match='brain_action_invalid'):
        T.produce(res=T.result(parsed=parsed))
    monkeypatch.setattr(CandidateProducer,'_assert_action_permits_entry',lambda *_: None)
    unsafe = T.produce(res=T.result(parsed=parsed))
    assert unsafe.direction == 'bullish'
    with pytest.raises(AssertionError):
        assert unsafe is None
