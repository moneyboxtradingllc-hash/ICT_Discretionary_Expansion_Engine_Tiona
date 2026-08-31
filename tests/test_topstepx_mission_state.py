"""Crash-safe one-attempt authorization locks. No network, no orders."""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker import topstepx_mission_state as M                # noqa: E402

FP = "acct:fc84f7a928d9"
CID = "CON.F.US.MNQ.U26"
MID = "smoke-20260805"
AUTH = "authfp:abc123"


def opened(tmp_path, **over):
    kw = dict(path=str(tmp_path / "mission.json"), mission_id=MID,
              account_fingerprint=FP, contract_id=CID,
              authorization_fingerprint=AUTH)
    kw.update(over)
    return M.open_mission(**kw)


class TestFreshMission:

    def test_a_fresh_mission_arms_and_permits_evaluation(self, tmp_path):
        st = opened(tmp_path)
        assert st.state == M.ARMED and st.attempt_count == 0
        ok, why = st.may_attempt_entry()
        assert ok is True and why is None

    def test_arming_persists_immediately(self, tmp_path):
        opened(tmp_path)
        data = json.load(open(tmp_path / "mission.json", encoding="utf-8"))
        assert data["state"] == M.ARMED and data["attempt_count"] == 0

    def test_a_missing_file_does_not_silently_resurrect_an_old_mission(self, tmp_path):
        """Absence means new; it must not inherit a spent allowance."""
        assert M.load(str(tmp_path / "nope.json")) is None


class TestAttemptConsumption:

    def test_the_attempt_persists_and_is_verified(self, tmp_path):
        st = opened(tmp_path)
        out = st.consume_attempt(candidate_fingerprint="cand:1", token_id="smoke-a")
        assert out["verified"] is True and out["attempt_count"] == 1
        on_disk = json.load(open(tmp_path / "mission.json", encoding="utf-8"))
        assert on_disk["state"] == M.ATTEMPT_CONSUMED
        assert on_disk["attempt_count"] == 1

    def test_a_second_consumption_is_refused(self, tmp_path):
        st = opened(tmp_path)
        st.consume_attempt(candidate_fingerprint="cand:1", token_id="smoke-a")
        with pytest.raises(M.MissionStateError):
            st.consume_attempt(candidate_fingerprint="cand:2", token_id="smoke-b")

    def test_consumption_is_refused_if_it_cannot_be_verified(self, tmp_path, monkeypatch):
        """If the write cannot be proven, the submit must not proceed."""
        st = opened(tmp_path)
        monkeypatch.setattr(M, "load", lambda p: None)
        with pytest.raises(M.MissionStateError) as exc:
            st.consume_attempt(candidate_fingerprint="cand:1", token_id="smoke-a")
        assert "refusing to submit" in str(exc.value)


class TestRestartRecovery:

    @pytest.mark.parametrize("state", sorted(M.ATTEMPT_SPENT_STATES))
    def test_restart_after_a_spent_attempt_cannot_attempt_again(self, tmp_path, state):
        st = opened(tmp_path)
        st.attempt_count = 1
        st.transition(state, "spent")
        again = opened(tmp_path)
        ok, why = again.may_attempt_entry()
        assert ok is False
        # A spent attempt is either still awaiting reconciliation, or already
        # finished. VENUE_REJECTED_ZERO_FILL is the second kind: the venue
        # answered, it answered "rejected, zero fill", and there is nothing
        # left to reconcile.
        assert again.must_reconcile() or state in M.TERMINAL_STATES

    def test_restart_after_submit_unknown_reconciles_and_never_retries(self, tmp_path):
        st = opened(tmp_path)
        st.consume_attempt(candidate_fingerprint="c", token_id="t")
        st.transition(M.SUBMIT_UNKNOWN, "no response persisted")
        again = opened(tmp_path)
        assert again.state == M.SUBMIT_UNKNOWN
        assert again.may_attempt_entry()[0] is False
        assert again.must_reconcile() is True

    def test_restart_with_an_open_position_manages_but_does_not_enter(self, tmp_path):
        st = opened(tmp_path)
        st.consume_attempt(candidate_fingerprint="c", token_id="t")
        st.position_state = "long_1"
        st.transition(M.POSITION_OPEN, "filled")
        again = opened(tmp_path)
        assert again.may_attempt_entry()[0] is False
        assert again.must_reconcile() is True
        assert again.position_state == "long_1"

    def test_a_completed_mission_stays_blocked_forever(self, tmp_path):
        st = opened(tmp_path)
        st.attempt_count = 1
        st.transition(M.COMPLETE, "smoke done")
        again = opened(tmp_path)
        ok, why = again.may_attempt_entry()
        assert ok is False and "terminal" in why

    def test_a_venue_rejection_does_not_restore_the_attempt(self, tmp_path):
        """One attempt was authorized, not retries until accepted."""
        st = opened(tmp_path)
        st.consume_attempt(candidate_fingerprint="c", token_id="t")
        st.transition(M.TERMINAL_REFUSAL, "venue rejected the order")
        again = opened(tmp_path)
        assert again.attempt_count == 1
        assert again.may_attempt_entry()[0] is False

    def test_a_crash_right_after_transport_cannot_yield_attempt_two(self, tmp_path):
        """Simulates death immediately after the request left the process."""
        st = opened(tmp_path)
        st.consume_attempt(candidate_fingerprint="c", token_id="t")
        del st                                    # process dies here
        again = opened(tmp_path)
        assert again.attempt_count == 1
        assert again.may_attempt_entry()[0] is False


class TestFailClosed:

    def test_corrupt_state_is_uncertain_not_unarmed(self, tmp_path):
        p = tmp_path / "mission.json"
        p.write_text('{"mission_id": "x", "state": ', encoding="utf-8")   # torn write
        st = M.load(str(p))
        assert st.state == M.STATE_UNCERTAIN
        assert st.may_attempt_entry()[0] is False

    def test_state_missing_required_fields_is_uncertain(self, tmp_path):
        p = tmp_path / "mission.json"
        p.write_text('{"state": "ARMED"}', encoding="utf-8")
        assert M.load(str(p)).state == M.STATE_UNCERTAIN

    def test_an_account_mismatch_fails_closed(self, tmp_path):
        opened(tmp_path)
        other = opened(tmp_path, account_fingerprint="acct:someoneelse")
        assert other.state == M.STATE_UNCERTAIN
        assert other.may_attempt_entry()[0] is False

    def test_a_contract_mismatch_fails_closed(self, tmp_path):
        opened(tmp_path)
        other = opened(tmp_path, contract_id="CON.F.US.MNQ.Z26")
        assert other.state == M.STATE_UNCERTAIN

    def test_a_mission_id_mismatch_fails_closed(self, tmp_path):
        opened(tmp_path)
        other = opened(tmp_path, mission_id="smoke-different")
        assert other.state == M.STATE_UNCERTAIN

    def test_uncertain_state_is_never_reset_by_reopening(self, tmp_path):
        p = tmp_path / "mission.json"
        p.write_text("garbage", encoding="utf-8")
        assert opened(tmp_path).state == M.STATE_UNCERTAIN
        assert opened(tmp_path).state == M.STATE_UNCERTAIN


class TestAtomicWrite:

    def test_no_temporary_file_survives_a_successful_save(self, tmp_path):
        st = opened(tmp_path)
        st.transition(M.CANDIDATE_APPROVED, "c")
        leftovers = [f for f in os.listdir(tmp_path) if f.startswith(".mission-")]
        assert leftovers == []

    def test_the_file_is_always_complete_json_after_a_transition(self, tmp_path):
        st = opened(tmp_path)
        for s in (M.CANDIDATE_APPROVED, M.TOKEN_MINTED):
            st.transition(s, s)
            json.load(open(tmp_path / "mission.json", encoding="utf-8"))

    def test_a_failed_write_leaves_the_previous_state_intact(self, tmp_path, monkeypatch):
        st = opened(tmp_path)
        st.transition(M.CANDIDATE_APPROVED, "c")
        monkeypatch.setattr(os, "replace",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(OSError):
            st.transition(M.TOKEN_MINTED, "t")
        on_disk = json.load(open(tmp_path / "mission.json", encoding="utf-8"))
        assert on_disk["state"] == M.CANDIDATE_APPROVED


class TestOrderingContract:

    def test_attempt_is_persisted_before_any_transport_is_invoked(self, tmp_path):
        """The ordering law: consumption lands on disk before the order can send."""
        events = []
        st = opened(tmp_path)

        def transport(payload):
            # by the time the venue is touched, disk must already say CONSUMED
            on_disk = json.load(open(tmp_path / "mission.json", encoding="utf-8"))
            events.append(("transport", on_disk["state"], on_disk["attempt_count"]))
            return {"order_id": 1}

        st.consume_attempt(candidate_fingerprint="c", token_id="t")
        events.append(("consumed", st.state, st.attempt_count))
        transport({})
        assert events[0] == ("consumed", M.ATTEMPT_CONSUMED, 1)
        assert events[1] == ("transport", M.ATTEMPT_CONSUMED, 1)

    def test_the_in_memory_latch_still_exists_alongside_the_durable_one(self):
        from broker.topstepx_execution_runner import ExecutionRunner
        import dataclasses
        names = {f.name for f in dataclasses.fields(ExecutionRunner)}
        assert "_entry_attempted" in names
