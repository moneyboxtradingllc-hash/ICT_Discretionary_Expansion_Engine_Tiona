"""Offline boundary checks for the new repair identity comparisons."""
from pathlib import Path

import pytest

import test_venue_rejection_attribution as H


@pytest.mark.parametrize('field', ['account_fingerprint', 'contract_id'])
def test_repair_requires_a_nonempty_mission_identity(tmp_path, monkeypatch, field):
    helper = H.TestTheBoundedLocalRepair()
    _, mission = helper.repo(tmp_path)
    setattr(mission, field, '')
    mission.save()
    before = Path(mission.path).read_bytes()
    result = helper.run(
        tmp_path, monkeypatch,
        extra=['--phrase', 'CLOSE THIS MISSION AS VENUE REJECTED ZERO FILL'])
    reread = H.MS.load(mission.path)
    assert result != 0, {
        'missing_identity': field, 'exit_code': result,
        'durable_state': reread.state, 'token_spent': reread.token_spent,
    }
    assert Path(mission.path).read_bytes() == before
