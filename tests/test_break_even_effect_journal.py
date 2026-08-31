"""BREAK-EVEN-2C — durable effect recovery and the ambiguity latch.

THE DEFECT, MEASURED ON THE REAL PRODUCTION PATH BEFORE THIS UNIT:

    tick 1  accepted, effect not visible   ->  1 modify sent
    tick 2  same unresolved state          ->  2 modifies sent
    ticks 3-5                              ->  5 modifies sent
    cold restart                           ->  sends again, knows nothing

`retryable=False` was advisory: it lived in `self.last_management`, which is
RAM. A flag no durable record survives to enforce cannot bind anything.

Venue lineage is the REAL 2026-08-25 T2 specimen; the favourable price movement
is synthetic. No broker. No provider. No network.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from broker import break_even_actuator as ACT                        # noqa: E402
from broker import break_even_journal as J                           # noqa: E402
from test_break_even_production_wiring import (                      # noqa: E402
    CID, T2_ENTRY, T2_STOP, T2_TARGET, T2_STOP_PX, T2_TARGET_PX, loop_for,
    t2_children)

SESSION = "PRAC-20260825"


def accepts_without_effect(venue):
    """The venue takes the request and the stop never appears to move."""
    def modify(order_id, **kw):
        venue.modifies.append({"order_id": order_id,
                               "stop_price": kw.get("stop_price")})
        return {"success": True}
    venue.modify_order = modify
    return venue


def eligible(tmp_path, **kw):
    """A loop whose long is comfortably past +1R on the bid."""
    return loop_for(tmp_path, bid=29261.0, ask=29261.25, **kw)


# ══ IDENTITY ════════════════════════════════════════════════════════════════
class TestEffectIdentity:

    def kw(self, **over):
        base = dict(mission_id="PRAC-20260825-T2", contract_id=CID,
                    entry_order_id=T2_ENTRY, stop_order_id=T2_STOP,
                    proposed_stop=29210.75, account_fingerprint="acct:aaaaaaaaaaaa")
        base.update(over)
        return base

    def test_the_same_intention_derives_the_same_id_after_a_restart(self):
        assert J.effect_id(**self.kw()) == J.effect_id(**self.kw())

    def test_a_float_reread_from_json_does_not_mint_a_second_identity(self):
        a = J.effect_id(**self.kw(proposed_stop=29210.75))
        b = J.effect_id(**self.kw(proposed_stop=json.loads("29210.7500000")))
        assert a == b

    def test_identity_is_not_time_based(self):
        import time
        a = J.effect_id(**self.kw())
        time.sleep(0.01)
        assert J.effect_id(**self.kw()) == a

    def test_every_bound_fact_changes_the_identity(self):
        base = J.effect_id(**self.kw())
        for field, value in (("mission_id", "OTHER"), ("contract_id", "CON.X"),
                             ("entry_order_id", 111), ("stop_order_id", 222),
                             ("proposed_stop", 29211.00),
                             ("account_fingerprint", "acct:other")):
            assert J.effect_id(**self.kw(**{field: value})) != base, field


# ══ THE JOURNAL ═════════════════════════════════════════════════════════════
class TestJournal:

    def test_a_record_survives_and_reloads(self, tmp_path):
        assert J.record(store_dir=str(tmp_path), session_id=SESSION,
                        effect_id="be:x", state=J.INTENT, proposed_stop=1.0)
        rows = J.load(str(tmp_path), SESSION, "be:x")
        assert len(rows) == 1 and rows[0]["state"] == J.INTENT

    def test_only_the_latest_state_decides_resolution(self, tmp_path):
        for state in (J.INTENT, J.ACCEPTED, J.READBACK_APPLIED):
            J.record(store_dir=str(tmp_path), session_id=SESSION,
                     effect_id="be:x", state=state)
        assert J.latest_state(str(tmp_path), SESSION, "be:x") == J.READBACK_APPLIED
        assert J.is_unresolved(str(tmp_path), SESSION, "be:x") is False

    def test_unresolved_states_forbid_a_write(self, tmp_path):
        for state in (J.INTENT, J.ACCEPTED, J.TRANSPORT_AMBIGUOUS,
                      J.READBACK_UNPROVEN):
            J.record(store_dir=str(tmp_path), session_id=SESSION,
                     effect_id=f"be:{state}", state=state)
            assert J.is_unresolved(str(tmp_path), SESSION, f"be:{state}")

    def test_terminal_states_do_not(self, tmp_path):
        for state in (J.READBACK_APPLIED, J.EXPLICITLY_REJECTED, J.HELD_ALREADY,
                      J.POSITION_FLAT, J.PROTECTION_DEFECT):
            J.record(store_dir=str(tmp_path), session_id=SESSION,
                     effect_id=f"be:{state}", state=state)
            assert not J.is_unresolved(str(tmp_path), SESSION, f"be:{state}")

    def test_a_torn_line_is_never_authority(self, tmp_path):
        J.record(store_dir=str(tmp_path), session_id=SESSION, effect_id="be:x",
                 state=J.INTENT)
        with open(J.journal_path(str(tmp_path), SESSION), "a", encoding="utf-8") as fh:
            fh.write('{"half written\n')
        assert J.latest_state(str(tmp_path), SESSION, "be:x") == J.INTENT

    def test_a_missing_journal_is_empty_not_an_error(self, tmp_path):
        assert J.load(str(tmp_path), "NOPE") == []
        assert J.is_unresolved(str(tmp_path), "NOPE", "be:x") is False

    def test_an_unwritable_journal_reports_failure(self, tmp_path):
        ok = J.record(store_dir=os.path.join(str(tmp_path), "x\0y"),
                      session_id=SESSION, effect_id="be:x", state=J.INTENT)
        assert ok is False


# ══ THE LATCH ON THE REAL PRODUCTION PATH ═══════════════════════════════════
class TestNoDuplicateWrites:

    def test_five_ticks_after_an_unproven_accept_send_exactly_one_modify(self, tmp_path):
        loop, venue, _ = eligible(tmp_path)
        accepts_without_effect(venue)
        first = loop.manage_open_position()
        assert first["status"] == ACT.AMBIGUOUS
        for _ in range(4):
            later = loop.manage_open_position()
            assert later["status"] == "unresolved_effect_reconciled"
        assert len(venue.modifies) == 1, "the latch did not hold"

    def test_the_latch_survives_a_process_restart(self, tmp_path):
        loop, venue, _ = eligible(tmp_path)
        accepts_without_effect(venue)
        loop.manage_open_position()
        assert len(venue.modifies) == 1

        cold, venue2, _ = eligible(tmp_path)          # cold loop, same store_dir
        accepts_without_effect(venue2)
        out = cold.manage_open_position()
        assert out["status"] == "unresolved_effect_reconciled"
        assert venue2.modifies == [], "a restart re-sent an unresolved effect"

    def test_intent_is_durable_before_the_mutation(self, tmp_path):
        loop, venue, _ = eligible(tmp_path)
        accepts_without_effect(venue)
        out = loop.manage_open_position()
        rows = J.load(str(tmp_path), SESSION, out["effect_id"])
        assert rows[0]["state"] == J.INTENT, "intent was not written first"
        assert rows[0]["original_initial_stop"] == T2_STOP_PX
        assert rows[0]["entry_fill_price"] is not None

    def test_a_failed_pre_write_intent_prevents_the_mutation(self, tmp_path, monkeypatch):
        loop, venue, _ = eligible(tmp_path)
        monkeypatch.setattr(J, "record", lambda **kw: False)
        out = loop.manage_open_position()
        assert out["status"] == "intent_not_persisted"
        assert venue.modifies == [], "a mutation followed an unpersisted intent"


# ══ RECOVERY OUTCOMES ═══════════════════════════════════════════════════════
class TestRecoveryOutcomes:
    """A latched effect must be RESOLVED by venue truth, never by assumption."""

    def latch(self, tmp_path, **kw):
        loop, venue, runner = eligible(tmp_path, **kw)
        accepts_without_effect(venue)
        loop.manage_open_position()
        return loop, venue, runner

    def test_case_A_the_effect_landed_resolves_applied_with_no_write(self, tmp_path):
        loop, venue, _ = self.latch(tmp_path)
        be = venue.modifies[0]["stop_price"]
        for o in venue._o:                            # it lands a moment later
            if o["id"] == T2_STOP:
                o["stop_price"] = be
        out = loop.manage_open_position()
        assert out["actuation"]["outcome"] == ACT.HELD
        assert len(venue.modifies) == 1
        assert J.latest_state(str(tmp_path), SESSION,
                              out["effect_id"]) == J.HELD_ALREADY

    def test_case_B_a_flat_position_resolves_without_a_write(self, tmp_path):
        loop, venue, _ = self.latch(tmp_path)
        venue._p = []
        out = loop.manage_open_position()
        assert out["actuation"]["outcome"] == ACT.HELD
        assert len(venue.modifies) == 1

    def test_case_C_a_missing_stop_reaches_the_emergency_authority(self, tmp_path):
        loop, venue, runner = self.latch(tmp_path)
        venue._o = [o for o in venue._o if o["id"] == T2_TARGET]
        out = loop.manage_open_position()
        assert out["status"] == "protection_defect"
        assert len(runner.flattens) == 1
        assert len(venue.modifies) == 1, "a blind retry accompanied the defect"

    def test_case_E_an_unreadable_venue_stays_unresolved_and_silent(self, tmp_path):
        loop, venue, _ = self.latch(tmp_path)

        def blind():
            raise RuntimeError("venue unreachable")
        venue.open_positions = blind
        out = loop.manage_open_position()
        assert len(venue.modifies) == 1, "a blind venue produced a write"
        # No identity can be derived without venue truth, so it bails BEFORE
        # journalling anything -- a spurious intent under a bogus identity
        # would be worse than no row.
        assert out["status"] == "venue_unreadable_for_effect_identity"
        assert J.is_unresolved(str(tmp_path), SESSION,
                               J.unresolved_effects(str(tmp_path), SESSION)[0]["effect_id"])

    def test_case_F_still_original_stays_latched(self, tmp_path):
        loop, venue, _ = self.latch(tmp_path)
        out = loop.manage_open_position()
        assert out["status"] == "unresolved_effect_reconciled"
        assert out["actuation"]["write_suppressed"] is True
        assert J.is_unresolved(str(tmp_path), SESSION, out["effect_id"])
        assert len(venue.modifies) == 1


# ══ EXPLICIT REJECTION IS TERMINAL, AMBIGUITY IS NOT ════════════════════════
class TestRejectionIsDistinguished:

    def test_an_explicit_refusal_is_terminal_and_not_retried(self, tmp_path):
        from broker.topstepx_client import TopstepXError
        loop, venue, _ = eligible(tmp_path)

        def refuse(order_id, **kw):
            venue.modifies.append({"order_id": order_id,
                                   "stop_price": kw.get("stop_price")})
            raise TopstepXError("modify failed: errorCode=3",
                                venue_body={"success": False, "errorCode": 3,
                                            "errorMessage": "not modifiable"})
        venue.modify_order = refuse
        out = loop.manage_open_position()
        assert out["actuation"]["outcome"] == ACT.REJECTED
        assert J.latest_state(str(tmp_path), SESSION,
                              out["effect_id"]) == J.EXPLICITLY_REJECTED
        assert not J.is_unresolved(str(tmp_path), SESSION, out["effect_id"])

    def test_a_transport_failure_is_recorded_as_ambiguous_not_rejected(self, tmp_path):
        loop, venue, _ = eligible(tmp_path)

        def die(order_id, **kw):
            venue.modifies.append({"order_id": order_id,
                                   "stop_price": kw.get("stop_price")})
            raise TimeoutError("read timed out")
        venue.modify_order = die
        out = loop.manage_open_position()
        assert J.latest_state(str(tmp_path), SESSION,
                              out["effect_id"]) == J.TRANSPORT_AMBIGUOUS
        assert J.is_unresolved(str(tmp_path), SESSION, out["effect_id"])

    def test_transport_ambiguity_does_not_retry_on_the_next_tick(self, tmp_path):
        """No bounded-retry authority exists, so `retryable=True` must never
        become "try again every tick". Safety over achieving break-even."""
        loop, venue, _ = eligible(tmp_path)

        def die(order_id, **kw):
            venue.modifies.append({"order_id": order_id,
                                   "stop_price": kw.get("stop_price")})
            raise TimeoutError("read timed out")
        venue.modify_order = die
        loop.manage_open_position()
        for _ in range(3):
            loop.manage_open_position()
        assert len(venue.modifies) == 1


# ══ ORDINARY SUCCESS ════════════════════════════════════════════════════════
class TestOrdinarySuccess:

    def test_a_clean_apply_is_recorded_terminal_and_never_repeated(self, tmp_path):
        loop, venue, _ = eligible(tmp_path)
        out = loop.manage_open_position()
        assert out["status"] == ACT.APPLIED
        assert J.latest_state(str(tmp_path), SESSION,
                              out["effect_id"]) == J.READBACK_APPLIED
        for _ in range(3):
            loop.manage_open_position()
        assert len(venue.modifies) == 1

    def test_restart_after_success_sends_nothing(self, tmp_path):
        loop, venue, _ = eligible(tmp_path)
        applied = loop.manage_open_position()
        be = applied["actuation"]["active_protective_stop"]
        cold, venue2, _ = eligible(tmp_path, stop_px=be, orders=t2_children(be))
        cold.manage_open_position()
        assert venue2.modifies == []


# ══ TARGET IMMUTABILITY THROUGH RECOVERY ════════════════════════════════════
class TestTargetSurvivesRecovery:

    def test_target_is_untouched_across_intent_ambiguity_and_restart(self, tmp_path):
        loop, venue, _ = eligible(tmp_path)
        accepts_without_effect(venue)
        loop.manage_open_position()
        cold, venue2, _ = eligible(tmp_path)
        accepts_without_effect(venue2)
        cold.manage_open_position()
        for v in (venue, venue2):
            t = [o for o in v.open_orders() if o["id"] == T2_TARGET][0]
            assert t["limit_price"] == T2_TARGET_PX
            assert t["parent_order_id"] == T2_ENTRY
        assert all(m.get("limit_price") is None for m in venue.modifies
                   if "limit_price" in m)


# ══ MANAGEMENT-ONLY ═════════════════════════════════════════════════════════
class TestManagementOnlyEndToEnd:

    def test_the_whole_post_cap_path_stays_deterministic(self, tmp_path):
        import ai_brain.narrative_brain as NB
        from broker import topstepx_session_lifecycle as LC
        calls = []
        real = NB.run_narrative_brain
        NB.run_narrative_brain = lambda *a, **k: calls.append(1)
        try:
            loop, venue, _ = eligible(tmp_path)
            managing = LC.resolve(mission=loop.mission, venue=venue,
                                  contract_id=CID)
            assert managing["mode"] == LC.MANAGEMENT_ONLY
            assert loop.manage_open_position()["status"] == ACT.APPLIED
            venue._p, venue._o = [], []
            after = LC.resolve(mission=loop.mission, venue=venue, contract_id=CID)
            assert after["mode"] == LC.SESSION_COMPLETE and after["may_exit"]
        finally:
            NB.run_narrative_brain = real
        assert calls == [], "management consulted a provider"
