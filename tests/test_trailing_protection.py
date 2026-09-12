"""Trailing profit protection is deterministic, stair-stepped, and stop-only."""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from broker import break_even_actuator as ACT  # noqa: E402
from broker import break_even_journal as JOURNAL  # noqa: E402
from broker import trailing_protection as TRAIL  # noqa: E402
from test_break_even_production_wiring import (  # noqa: E402
    T2_FILL, T2_R, T2_STOP, T2_STOP_PX, T2_TARGET, loop_for,
)


def decision(*, direction="long", fill=100.0, stop=90.0, price=120.0,
             tick=.25):
    return TRAIL.evaluate(direction=direction, entry_fill_price=fill,
                          initial_stop_price=stop, current_price=price,
                          armed=True, tick_size=tick)


class TestStairStepDecision:
    def test_not_active_before_two_r(self):
        out = decision(price=119.9)
        assert out["outcome"] == TRAIL.HOLD

    def test_first_step_at_two_r_locks_one_r(self):
        out = decision(price=120.0)
        assert out["outcome"] == TRAIL.PROPOSE
        assert out["locked_r"] == 1
        assert out["desired_stop"] == 110.0

    def test_between_steps_does_not_chase_price(self):
        out = decision(price=127.5)
        assert out["locked_r"] == 1
        assert out["desired_stop"] == 110.0

    def test_second_step_and_large_jump_use_current_destination_once(self):
        assert decision(price=130.0)["desired_stop"] == 120.0
        jumped = decision(price=142.0)
        assert jumped["locked_r"] == 3
        assert jumped["desired_stop"] == 130.0

    def test_short_is_the_exact_directional_mirror(self):
        out = decision(direction="short", fill=100.0, stop=110.0, price=80.0)
        assert out["locked_r"] == 1
        assert out["desired_stop"] == 90.0

    def test_actual_fill_and_original_stop_define_the_unchanging_ruler(self):
        out = decision(fill=100.1, stop=90.0, price=120.3)
        assert out["initial_risk_points"] == pytest.approx(10.1)
        assert out["desired_stop"] == 110.25  # conservative long tick rounding

    def test_invalid_or_unarmed_quote_geometry_refuses(self):
        out = TRAIL.evaluate(direction="long", entry_fill_price=100.0,
                             initial_stop_price=90.0, current_price=None,
                             armed=True, tick_size=.25)
        assert out["outcome"] == TRAIL.REFUSED
        assert out["reason"] == "no_fresh_executable_quote"


class TestProductionStairStep:
    def test_two_r_dominates_break_even_with_one_stop_only_write(self, tmp_path):
        # +2.2R: BE is eligible too, but +1R trailing is more protective.
        bid = T2_FILL + (2.2 * T2_R)
        loop, venue, _ = loop_for(tmp_path, bid=bid, ask=bid + .25)
        out = loop.manage_open_position()
        assert out["status"] == ACT.APPLIED
        assert out["decision"]["management_kind"] == "trailing"
        assert len(venue.modifies) == 1
        assert venue.modifies[0]["order_id"] == T2_STOP
        assert venue.modifies[0]["stop_price"] == T2_FILL + T2_R
        assert set(venue.modifies[0]) == {"order_id", "stop_price"}
        target = next(row for row in venue.open_orders() if row["id"] == T2_TARGET)
        assert target["limit_price"] == 29409.25

    def test_jump_to_four_r_writes_three_r_once_then_retrace_never_looses(self, tmp_path):
        bid = T2_FILL + (4.2 * T2_R)
        loop, venue, runner = loop_for(tmp_path, bid=bid, ask=bid + .25)
        first = loop.manage_open_position()
        assert first["decision"]["trailing"]["locked_r"] == 3
        assert len(venue.modifies) == 1
        locked = T2_FILL + (3 * T2_R)
        assert venue.modifies[0]["stop_price"] == locked
        # Price falls to 3.1R; the formula would name +2R, but the venue's +3R
        # stop is adopted as truth and no risk may be restored.
        loop.ps.quote_provider.bid = T2_FILL + (3.1 * T2_R)
        loop.ps.quote_provider.ask = loop.ps.quote_provider.bid + .25
        later = loop.manage_open_position()
        assert later["status"] == ACT.HELD
        assert len(venue.modifies) == 1
        assert runner.execution_context.active_protective_stop == locked

    def test_trailing_effect_is_durable_and_a_restart_never_blind_retries(self, tmp_path):
        bid = T2_FILL + (2.2 * T2_R)
        loop, venue, _ = loop_for(tmp_path, bid=bid, ask=bid + .25)

        def accepted_but_invisible(order_id, **kwargs):
            venue.modifies.append({"order_id": order_id,
                                   "stop_price": kwargs.get("stop_price")})
            return {"success": True}
        venue.modify_order = accepted_but_invisible
        first = loop.manage_open_position()
        assert first["status"] == ACT.AMBIGUOUS
        assert first["effect_id"].startswith("trail:")
        assert JOURNAL.is_unresolved(str(tmp_path), loop.ps.session_id,
                                     first["effect_id"])
        cold, venue2, _ = loop_for(tmp_path, bid=bid, ask=bid + .25)
        later = cold.manage_open_position()
        assert later["status"] == "unresolved_effect_reconciled"
        assert venue2.modifies == []

    def test_unresolved_first_step_blocks_later_step_in_same_process(self, tmp_path):
        first_bid = T2_FILL + (2.2 * T2_R)
        loop, venue, _ = loop_for(tmp_path, bid=first_bid,
                                  ask=first_bid + .25)

        def accepted_but_invisible(order_id, **kwargs):
            venue.modifies.append({"order_id": order_id,
                                   "stop_price": kwargs.get("stop_price")})
            return {"success": True}
        venue.modify_order = accepted_but_invisible

        first = loop.manage_open_position()
        assert first["status"] == ACT.AMBIGUOUS
        assert len(venue.modifies) == 1

        loop.ps.quote_provider.bid = T2_FILL + (3.2 * T2_R)
        loop.ps.quote_provider.ask = loop.ps.quote_provider.bid + .25
        second = loop.manage_open_position()
        assert second["status"] == "unresolved_effect_reconciled"
        assert second["actuation"]["write_suppressed"] is True
        assert len(venue.modifies) == 1

    def test_unresolved_first_step_blocks_later_step_after_restart(self, tmp_path):
        first_bid = T2_FILL + (2.2 * T2_R)
        loop, venue, _ = loop_for(tmp_path, bid=first_bid,
                                  ask=first_bid + .25)

        def accepted_but_invisible(order_id, **kwargs):
            venue.modifies.append({"order_id": order_id,
                                   "stop_price": kwargs.get("stop_price")})
            return {"success": True}
        venue.modify_order = accepted_but_invisible
        loop.manage_open_position()
        assert len(venue.modifies) == 1

        later_bid = T2_FILL + (3.2 * T2_R)
        cold, venue2, _ = loop_for(tmp_path, bid=later_bid,
                                   ask=later_bid + .25)
        accepts_without_effect = lambda order_id, **kwargs: {
            "success": True}
        venue2.modify_order = accepts_without_effect
        out = cold.manage_open_position()
        assert out["status"] == "unresolved_effect_reconciled"
        assert venue2.modifies == []

    def test_later_step_may_write_only_on_a_later_tick_after_resolution(self,
                                                                        tmp_path):
        first_bid = T2_FILL + (2.2 * T2_R)
        loop, venue, _ = loop_for(tmp_path, bid=first_bid,
                                  ask=first_bid + .25)

        def accepted_but_invisible(order_id, **kwargs):
            venue.modifies.append({"order_id": order_id,
                                   "stop_price": kwargs.get("stop_price")})
            return {"success": True}
        venue.modify_order = accepted_but_invisible
        loop.manage_open_position()

        loop.ps.quote_provider.bid = T2_FILL + (3.2 * T2_R)
        loop.ps.quote_provider.ask = loop.ps.quote_provider.bid + .25
        loop.manage_open_position()
        assert len(venue.modifies) == 1

        for order in venue._o:
            if order["id"] == T2_STOP:
                order["stop_price"] = T2_FILL + T2_R

        resolved = loop.manage_open_position()
        assert resolved["status"] == "unresolved_effect_reconciled"
        assert len(venue.modifies) == 1

        later = loop.manage_open_position()
        assert later["status"] == ACT.AMBIGUOUS
        assert len(venue.modifies) == 2
        assert venue.modifies[-1]["stop_price"] == T2_FILL + (2 * T2_R)

    def test_position_management_needs_no_brain(self, tmp_path):
        import ai_brain.narrative_brain as brain
        calls, original = [], brain.run_narrative_brain
        brain.run_narrative_brain = lambda *args, **kwargs: calls.append(True)
        try:
            bid = T2_FILL + (2.2 * T2_R)
            loop, _, _ = loop_for(tmp_path, bid=bid, ask=bid + .25)
            assert loop.manage_open_position()["status"] == ACT.APPLIED
        finally:
            brain.run_narrative_brain = original
        assert calls == []
