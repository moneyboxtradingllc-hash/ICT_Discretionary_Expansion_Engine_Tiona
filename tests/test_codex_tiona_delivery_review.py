"""Offline review of bfcc565. Expected invariants, with real HTTP parsing.

Only urllib's socket boundary is replaced for the submission tests. No real
credentials, venue requests, or production runtime files are used.
"""
import io
import json
from dataclasses import replace
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

import test_venue_rejection_attribution as H
from broker import topstepx_client as C
from broker import topstepx_submission_record as SUB
from broker.topstepx_live_session import TopstepXLiveSession
from broker.topstepx_redaction import account_fingerprint


class Wire:
    def __init__(self, order_replies):
        self.order_replies = list(order_replies)
        self.order_requests = 0
        self.failed_login_requests = 0
        self.fail_next_login = False

    def urlopen(self, request, timeout=None):
        url = request.full_url
        if url.endswith('/api/Auth/loginKey'):
            if self.fail_next_login:
                self.fail_next_login = False
                self.failed_login_requests += 1
                raise HTTPError(url, 401, 'Unauthorized', {}, io.BytesIO(b'{}'))
            body = {'success': True, 'token': 'synthetic-review-token'}
        elif url.endswith('/api/Order/place'):
            self.order_requests += 1
            reply = self.order_replies.pop(0)
            if isinstance(reply, int):
                raise HTTPError(url, reply, 'fixture response', {}, io.BytesIO(b'{}'))
            body = reply
        elif url.endswith('/api/Position/searchOpen'):
            body = {'success': True, 'positions': []}
        elif url.endswith('/api/Order/v2/query'):
            body = {'success': True, 'orders': [], 'totalCount': 0}
        elif url.endswith('/api/Order/searchOpen'):
            body = {'success': True, 'orders': []}
        else:
            raise AssertionError(f'Unexpected endpoint: {url}')
        return io.BytesIO(json.dumps(body).encode())


def scan_with_real_client(tmp_path, monkeypatch, replies, *, login_401=False):
    wire = Wire(replies)
    monkeypatch.setattr(C.urllib.request, 'urlopen', wire.urlopen)
    live = TopstepXLiveSession('fixture-user', 'fixture-key', clock=lambda: H.NOW)
    live.account = SimpleNamespace(id=77, name='TEST')
    live.contract = H.MNQ
    live._client._token = 'synthetic-cached-token'
    live._client._sleep = lambda _: None

    def submit(payload):
        if login_401:
            # Token expires after preflight; the login request fails once,
            # then credentials work again for the reconciliation reads.
            live._client._token = None
            wire.fail_next_login = True
        return live.place_order(payload)

    session = H.Session(place=submit)
    session.open_positions = live.open_positions
    session.open_orders = live.open_orders
    session.query_orders = live.query_orders
    _, ps, session, missions, _ = H.armed_rejection(tmp_path, venue=session)
    mission = missions.trade_missions[0]
    evidence = SUB.mission_venue_evidence(
        str(tmp_path), ps.session_id, mission.mission_id, token_id=mission.token_id)
    facts = dict(runner_submit_calls=session.place_calls,
                 http_order_requests=wire.order_requests,
                 failed_login_requests=wire.failed_login_requests,
                 mission_state=mission.state, token_spent=mission.token_spent,
                 ledger_states=evidence['states'],
                 ledger_submission_count=evidence['submission_count'],
                 ledger_accepts_zero_fill=SUB.zero_fill_rejection(
                     evidence, positions=0, working_orders=0)[0])
    return mission, facts


def test_control_one_clean_refusal_terminalizes(tmp_path, monkeypatch):
    mission, facts = scan_with_real_client(tmp_path, monkeypatch, [H.NO_ID_REJECTION])
    assert facts['http_order_requests'] == 1, facts
    assert mission.state == H.MS.VENUE_REJECTED_ZERO_FILL, facts


def test_internal_503_then_refusal_remains_uncertain(tmp_path, monkeypatch):
    mission, facts = scan_with_real_client(
        tmp_path, monkeypatch, [503, H.NO_ID_REJECTION])
    assert facts['runner_submit_calls'] == 1, facts
    assert mission.state == H.MS.ATTEMPT_CONSUMED, json.dumps(facts, sort_keys=True)
    assert not mission.token_spent, facts
    assert not facts['ledger_accepts_zero_fill'], facts


def test_login_endpoint_http_401_is_not_an_order_refusal(tmp_path, monkeypatch):
    mission, facts = scan_with_real_client(tmp_path, monkeypatch, [], login_401=True)
    assert facts['failed_login_requests'] == 1, facts
    assert facts['http_order_requests'] == 0, facts
    assert mission.state == H.MS.ATTEMPT_CONSUMED, json.dumps(facts, sort_keys=True)
    assert not mission.token_spent, facts


@pytest.mark.parametrize('mismatch', ['account', 'contract'])
def test_repair_refuses_evidence_from_a_different_identity(
        tmp_path, monkeypatch, mismatch):
    helper = H.TestTheBoundedLocalRepair()
    _, mission = helper.repo(tmp_path)
    venue = H.FakeLiveSession()
    live_fp = account_fingerprint(venue.account.id, venue.account.name)

    def checked_pin(*, account_id=None, expected_fingerprint=''):
        assert account_id == venue.account.id
        assert expected_fingerprint == live_fp
        return venue.account

    venue.pin = checked_pin
    mission.account_fingerprint = live_fp
    if mismatch == 'account':
        mission.account_fingerprint = account_fingerprint(90000043, 'OTHER-FIXTURE')
    else:
        wrong_contract = replace(H.MNQ, id='CON.F.US.MNQ.Z26', name='MNQZ6')
        venue.resolve_contract = lambda text='MNQ': wrong_contract
    mission.save()
    monkeypatch.setenv('TOPSTEPX_ACCOUNT_FINGERPRINT', live_fp)
    before = open(mission.path, 'rb').read()
    code = helper.run(
        tmp_path, monkeypatch, venue=venue,
        extra=['--phrase', 'CLOSE THIS MISSION AS VENUE REJECTED ZERO FILL'])
    reread = H.MS.load(mission.path)
    assert code != 0, dict(mismatch=mismatch, exit_code=code,
                           durable_state=reread.state, token_spent=reread.token_spent)
    assert open(mission.path, 'rb').read() == before
