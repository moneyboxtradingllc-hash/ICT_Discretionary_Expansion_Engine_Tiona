"""PROTECTION-STATE-AUTHORITY-1 — the thesis stop and the working stop split.

`ExecutionContext.structural_stop_price` carried two meanings in one number:
where the THESIS is wrong, and what the VENUE will execute. That collision is
why "the stop is never adjustable" and "protect the bag" read as contradictory
doctrine. They never were. They were competing for one variable.

THE LIFECYCLE BOUNDARY IS THE HARD PART, AND THE OBVIOUS INVARIANT IS A DEFECT.
"the stop may never move farther from the fill" would have blocked the certified
post-fill re-anchor, whose entire job is to replace a fill-relative provisional
bracket with the authorized structural one -- frequently WIDER. Arming at fill
would flatten live positions. So the monotonic law does not exist until the
structural stop has been venue-PROVEN, and these tests pin both halves: that it
is absent before, and present after.

The numbers are the trade the contrastive replay actually authored on the
2026-08-20 session -- short 29455.00, invalidation 29470.25, objective 29240.25,
14.08R -- so the fixtures describe a real thesis rather than round arithmetic.

WHAT IS DELIBERATELY NOT HERE. No Luna management vocabulary, no authorized
level catalog, no partials, no native trailing, no break-even, no R or P&L
trigger. Unit 1 only makes the state truthful. `TestScopeRestraint` pins that.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from broker import protection_state as PS                      # noqa: E402
from broker import topstepx_slippage as SL                     # noqa: E402
from test_exec_price_anchor import (MNQ, STOP_ORDER_ID,        # noqa: E402
                                    TARGET_ORDER_ID, ENTRY_ORDER_ID,
                                    _children, _fill, _runner)

# ── the authored trade ───────────────────────────────────────────────────────
ENTRY = 29455.00
INVALIDATION = 29470.25           # 15.25 points of authored risk
OBJECTIVE = 29240.25

REDUCED = 29461.00                # still above entry: risk cut, not removed
AT_ENTRY = 29455.00               # break-even as a CONSEQUENCE, not a trigger
IN_PROFIT = 29447.00              # a newly protected high below entry
WIDER = 29475.00                  # restores risk already given up

# An authored invalidation that does NOT sit on the venue's 0.25 grid. The
# venue rounds it conservatively to 29470.50, so thesis truth and execution
# truth genuinely differ by 0.20. Seeding both from the aligned number would
# let broker rounding rewrite what the thesis said.
OFF_GRID = 29470.30
OFF_GRID_ALIGNED = 29470.50


def ctx_for(runner, *, direction="bearish", **over):
    """A real ExecutionContext on a real runner -- not a stand-in dict."""
    ctx = SL.ExecutionContext(
        candidate_id="c-1", candidate_fingerprint="f-1", snapshot_id="s-1",
        mission_id="m-1", account_fingerprint="acct:test", contract_id=MNQ.id,
        direction=direction, quantity=1, entry_order_id=ENTRY_ORDER_ID,
        entry_fill_price=ENTRY, structural_stop_price=INVALIDATION,
        liquidity_target_price=OBJECTIVE, stop_order_id=STOP_ORDER_ID,
        target_order_id=TARGET_ORDER_ID)
    for k, v in over.items():
        setattr(ctx, k, v)
    runner.execution_context = ctx
    return ctx


def short_runner(fill=ENTRY, *, stop_ticks=20):
    """A live short whose PROVISIONAL bracket is TIGHTER than its structure.

    stop_ticks=20 puts provisional protection 5 points from the fill while the
    authorized invalidation is 15.25 away, so the certified re-anchor must
    WIDEN. This is the exact case a naive fill-anchored invariant would kill.
    """
    return off_grid_runner(fill, stop_ticks=stop_ticks, invalidation=INVALIDATION)


def off_grid_runner(fill=ENTRY, *, stop_ticks=20, invalidation=OFF_GRID):
    r, session = _runner("bearish", ENTRY, invalidation, OBJECTIVE, fill,
                         orders=_children(fill, "bearish", stop_ticks=stop_ticks,
                                          target_ticks=200))
    return r, session


# ══════════════════════════════════════════════════════════════════════════════
class TestTheDefectItFixes:
    def test_one_field_used_to_carry_both_meanings(self):
        """`structural_stop_price` is still the AUTHORED risk, and now it is no
        longer also asked to be the working stop."""
        fields = SL.ExecutionContext.__dataclass_fields__
        for name in ("structural_stop_price", "original_thesis_invalidation",
                     "active_protective_stop", "protection_baseline_armed"):
            assert name in fields, name

    def test_a_fresh_context_is_not_armed(self):
        r, _ = short_runner()
        ctx = ctx_for(r)
        assert ctx.protection_baseline_armed is False
        assert ctx.active_protective_stop is None
        assert ctx.original_thesis_invalidation is None


class TestTheLifecycleBoundary:
    """PROVISIONAL protection is execution safety. It is not the baseline."""

    def test_the_law_does_not_exist_before_the_baseline_is_armed(self):
        out = PS.evaluate_advance(direction="bearish",
                                  active_protective_stop=INVALIDATION,
                                  proposed_stop=REDUCED, armed=False)
        assert out["outcome"] == PS.REFUSED
        assert out["reason"] == PS.BASELINE_NOT_ARMED

    def test_unarmed_refusal_is_NOT_reported_as_a_no_op(self):
        """A caller must never read 'not armed yet' as 'already there'."""
        out = PS.evaluate_advance(direction="bearish",
                                  active_protective_stop=INVALIDATION,
                                  proposed_stop=INVALIDATION, armed=False)
        assert out["outcome"] == PS.REFUSED
        assert out["reason"] == PS.BASELINE_NOT_ARMED

    def test_the_certified_reanchor_may_still_WIDEN_protection(self):
        """The defect a fill-anchored invariant would have introduced."""
        r, session = short_runner()
        ctx_for(r)
        provisional = session.open_orders()[0]["stop_price"]
        assert provisional == ENTRY + 5.0                  # tighter than structure
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert out["reanchored"] is True
        assert out["authorization"]["aligned_stop_price"] == INVALIDATION
        assert INVALIDATION > provisional                  # it widened, lawfully
        assert session.closed == []

    def test_the_baseline_arms_exactly_at_the_proven_reanchor(self):
        r, session = short_runner()
        ctx = ctx_for(r)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert out["baseline"]["armed"] is True
        assert ctx.protection_baseline_armed is True
        assert ctx.original_thesis_invalidation == INVALIDATION
        assert ctx.active_protective_stop == INVALIDATION

    def test_it_seeds_from_the_VENUE_price_not_the_geometry_object(self):
        """`geometry.stop_price` is unaligned; the venue holds the aligned tick.
        Seeding the WORKING stop from the authored object would start local
        state already disagreeing with working protection."""
        r, session = short_runner()
        ctx = ctx_for(r)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert ctx.active_protective_stop == out["authorization"]["aligned_stop_price"]


class TestTwoAuthoritiesNotOne:
    """Thesis truth comes from structure; execution truth comes from the venue.

    Venue alignment may never rewrite recorded thesis history. These use an
    authored invalidation off the 0.25 grid so the two genuinely differ.
    """

    def test_the_alignment_gap_is_real_not_hypothetical(self):
        r, _ = off_grid_runner()
        auth = r.authorize_actual_fill(_fill(ENTRY))
        assert auth["authorized_stop_price"] == OFF_GRID
        assert auth["aligned_stop_price"] == OFF_GRID_ALIGNED
        assert auth["authorized_stop_price"] != auth["aligned_stop_price"]

    def test_thesis_keeps_the_AUTHORED_price(self):
        r, session = off_grid_runner()
        ctx = ctx_for(r)
        r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert ctx.original_thesis_invalidation == OFF_GRID

    def test_working_protection_keeps_the_VENUE_price(self):
        r, session = off_grid_runner()
        ctx = ctx_for(r)
        r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert ctx.active_protective_stop == OFF_GRID_ALIGNED

    def test_the_difference_is_PRESERVED_not_collapsed(self):
        r, session = off_grid_runner()
        ctx = ctx_for(r)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert ctx.original_thesis_invalidation != ctx.active_protective_stop
        assert out["baseline"]["alignment_delta"] == pytest.approx(0.20)

    def test_broker_rounding_cannot_rewrite_thesis_history(self):
        """The regression that matters: if arming ever takes one input again,
        the authored 29470.30 silently becomes the venue's 29470.50."""
        r, session = off_grid_runner()
        ctx = ctx_for(r)
        r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert ctx.original_thesis_invalidation != OFF_GRID_ALIGNED

    def test_arming_requires_BOTH_authorities(self):
        for missing in ("thesis_invalidation", "proven_stop_price"):
            kwargs = {"direction": "bearish", "thesis_invalidation": OFF_GRID,
                      "proven_stop_price": OFF_GRID_ALIGNED, "already_armed": False}
            kwargs[missing] = None
            out = PS.arm_baseline(**kwargs)
            assert out["armed"] is False, missing
            assert out["reason"] == PS.NOT_A_PRICE

    def test_an_on_grid_thesis_simply_matches(self):
        """When there is no rounding, the two agree -- and still travel by
        separate routes."""
        out = PS.arm_baseline(direction="bearish", thesis_invalidation=INVALIDATION,
                              proven_stop_price=INVALIDATION, already_armed=False)
        assert out["original_thesis_invalidation"] == INVALIDATION
        assert out["active_protective_stop"] == INVALIDATION
        assert out["alignment_delta"] == 0.0

    def test_a_failed_reanchor_arms_nothing(self):
        """Every non-proven return path must leave the baseline unarmed."""
        r, session = short_runner()
        ctx = ctx_for(r)
        session.modify_error = RuntimeError("venue refused")
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert ctx.protection_baseline_armed is False
        assert ctx.active_protective_stop is None

    def test_an_unproven_readback_arms_nothing(self):
        r, session = short_runner()
        ctx = ctx_for(r)
        bad = _children(ENTRY, "bearish", stop_ticks=20, target_ticks=200)
        bad[0]["stop_price"] = INVALIDATION + 3.0          # not where we asked
        session.readback_override = bad
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert ctx.protection_baseline_armed is False


class TestMonotonicLaw:
    @pytest.mark.parametrize("proposed", [REDUCED, AT_ENTRY, IN_PROFIT, 29390.0])
    def test_short_may_always_move_down(self, proposed):
        out = PS.evaluate_advance(direction="bearish",
                                  active_protective_stop=INVALIDATION,
                                  proposed_stop=proposed, armed=True)
        assert out["outcome"] == PS.ADVANCE

    @pytest.mark.parametrize("proposed", [WIDER, 29471.0, 29999.0])
    def test_short_may_never_move_up(self, proposed):
        out = PS.evaluate_advance(direction="bearish",
                                  active_protective_stop=INVALIDATION,
                                  proposed_stop=proposed, armed=True)
        assert out["outcome"] == PS.REFUSED
        assert out["reason"] == PS.RISK_RESTORATION

    @pytest.mark.parametrize("proposed", [29490.0, 29500.0, 29600.0])
    def test_long_may_always_move_up(self, proposed):
        out = PS.evaluate_advance(direction="bullish",
                                  active_protective_stop=29480.0,
                                  proposed_stop=proposed, armed=True)
        assert out["outcome"] == PS.ADVANCE

    @pytest.mark.parametrize("proposed", [29470.0, 29000.0])
    def test_long_may_never_move_down(self, proposed):
        out = PS.evaluate_advance(direction="bullish",
                                  active_protective_stop=29480.0,
                                  proposed_stop=proposed, armed=True)
        assert out["outcome"] == PS.REFUSED
        assert out["reason"] == PS.RISK_RESTORATION

    def test_equality_is_a_no_op_and_not_a_failure(self):
        out = PS.evaluate_advance(direction="bearish",
                                  active_protective_stop=INVALIDATION,
                                  proposed_stop=INVALIDATION, armed=True)
        assert out["outcome"] == PS.NO_OP
        assert out["reason"] is None

    def test_a_refusal_is_never_silently_clamped(self):
        """A clamp would report success for a request never honoured. The
        proposal is echoed back unchanged so the audit shows what was asked."""
        out = PS.evaluate_advance(direction="bearish",
                                  active_protective_stop=INVALIDATION,
                                  proposed_stop=WIDER, armed=True)
        assert out["proposed_stop"] == WIDER
        assert out["active_protective_stop"] == INVALIDATION

    @pytest.mark.parametrize("bad", [None, "", "nope", float("nan"),
                                     float("inf"), True, False, object()])
    def test_a_non_price_is_refused_not_coerced(self, bad):
        out = PS.evaluate_advance(direction="bearish",
                                  active_protective_stop=INVALIDATION,
                                  proposed_stop=bad, armed=True)
        assert out["outcome"] == PS.REFUSED
        assert out["reason"] == PS.NOT_A_PRICE

    def test_a_numeric_string_IS_a_price(self):
        """Venue and JSON payloads carry prices as strings; refusing them would
        reject lawful proposals. `True` is still not 1.0 -- a boolean reaching a
        price field is a bug, not a number."""
        out = PS.evaluate_advance(direction="bearish",
                                  active_protective_stop=INVALIDATION,
                                  proposed_stop="29461.00", armed=True)
        assert out["outcome"] == PS.ADVANCE
        assert out["proposed_stop"] == REDUCED
        assert PS.price(True) is None and PS.price(False) is None

    @pytest.mark.parametrize("bad", [None, "", "flat", "neutral", 1])
    def test_an_unknown_direction_is_refused(self, bad):
        out = PS.evaluate_advance(direction=bad,
                                  active_protective_stop=INVALIDATION,
                                  proposed_stop=REDUCED, armed=True)
        assert out["outcome"] == PS.REFUSED
        assert out["reason"] == PS.UNKNOWN_DIRECTION

    def test_armed_without_an_active_stop_is_an_impossible_state(self):
        out = PS.evaluate_advance(direction="bearish",
                                  active_protective_stop=None,
                                  proposed_stop=REDUCED, armed=True)
        assert out["outcome"] == PS.REFUSED
        assert out["reason"] == PS.NO_ACTIVE_STOP

    def test_reduction_is_strict_not_inclusive(self):
        assert PS.reduces_risk("bearish", INVALIDATION, INVALIDATION) is False
        assert PS.reduces_risk("bullish", 29480.0, 29480.0) is False


class TestBreakEvenIsAConsequenceNotATrigger:
    """The operator ruling, pinned as behaviour rather than prose."""

    def test_entry_is_not_a_special_price(self):
        """Moving to exactly entry is an ordinary advance -- nothing in the
        verifier knows what 'break-even' is."""
        out = PS.evaluate_advance(direction="bearish",
                                  active_protective_stop=INVALIDATION,
                                  proposed_stop=AT_ENTRY, armed=True)
        assert out["outcome"] == PS.ADVANCE
        assert "even" not in (out["reason"] or "") + out["detail"]

    def test_crossing_entry_uses_the_identical_path(self):
        below = PS.evaluate_advance(direction="bearish",
                                    active_protective_stop=AT_ENTRY,
                                    proposed_stop=IN_PROFIT, armed=True)
        assert below["outcome"] == PS.ADVANCE

    def test_a_partial_risk_reduction_is_lawful_without_reaching_entry(self):
        """29470.25 -> 29461.00 cuts 15.25 points of risk to 6.00 without
        pretending the trade is risk-free."""
        out = PS.evaluate_advance(direction="bearish",
                                  active_protective_stop=INVALIDATION,
                                  proposed_stop=REDUCED, armed=True)
        assert out["outcome"] == PS.ADVANCE
        assert round(REDUCED - ENTRY, 2) == 6.00
        assert round(INVALIDATION - ENTRY, 2) == 15.25

    def test_the_module_names_no_r_or_pnl_threshold(self):
        import inspect
        src = inspect.getsource(PS).lower()
        for banned in ("breakeven", "break_even", "trigger_r", "take_profit",
                       "r_multiple", "unrealized", "pnl"):
            assert banned not in src, banned


class TestOriginalInvalidationIsImmutable:
    def test_re_arming_is_refused(self):
        out = PS.arm_baseline(direction="bearish", thesis_invalidation=INVALIDATION,
                              proven_stop_price=IN_PROFIT, already_armed=True)
        assert out["armed"] is False
        assert out["reason"] == PS.BASELINE_ALREADY_ARMED

    def test_a_second_reanchor_cannot_rewrite_it(self):
        r, session = short_runner()
        ctx = ctx_for(r)
        r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        # protection advances FOR REAL: the venue moves and local follows.
        session.modify_order(STOP_ORDER_ID, stop_price=IN_PROFIT)
        session.modifies.clear()
        ctx.active_protective_stop = IN_PROFIT
        again = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert again["reanchored"] is False
        assert again["reason"] == PS.BASELINE_ALREADY_ARMED
        assert ctx.original_thesis_invalidation == INVALIDATION
        assert ctx.active_protective_stop == IN_PROFIT   # untouched
        assert session.modifies == []                    # and nothing was sent

    def test_arming_refuses_a_non_price(self):
        for bad in (None, "nope", float("nan"), True):
            out = PS.arm_baseline(direction="bearish",
                                  thesis_invalidation=INVALIDATION,
                                  proven_stop_price=bad, already_armed=False)
            assert out["armed"] is False
            assert out["reason"] == PS.NOT_A_PRICE

    def test_arming_refuses_an_unknown_direction(self):
        out = PS.arm_baseline(direction="sideways",
                              thesis_invalidation=INVALIDATION,
                              proven_stop_price=INVALIDATION, already_armed=False)
        assert out["armed"] is False
        assert out["reason"] == PS.UNKNOWN_DIRECTION

    def test_the_lineage_record_keeps_both_numbers(self):
        from broker import trade_lineage
        import inspect
        src = inspect.getsource(trade_lineage)
        assert '"original_thesis_invalidation": ctx.get(' in src
        assert '"active_protective_stop": ctx.get(' in src

    def test_R_stays_denominated_on_the_AUTHORED_risk(self):
        """An advanced stop must not inflate the R of the trade taken."""
        from broker.trade_lineage import realized_r
        record = {"entry_fill_price": ENTRY, "structural_stop_price": INVALIDATION,
                  "exit_price": OBJECTIVE, "direction": "short",
                  "active_protective_stop": IN_PROFIT}
        assert realized_r(record) == pytest.approx(14.08, abs=0.01)
        # the advanced stop is present in the record and deliberately unused
        assert realized_r({k: v for k, v in record.items()
                           if k != "active_protective_stop"}) == \
            pytest.approx(14.08, abs=0.01)


class TestPersistenceSurvivesRestart:
    """The load whitelist is hand-maintained. A field missing from it is
    written to disk and silently dropped -- exactly how a restart forgets an
    advanced stop."""

    def path(self, tmp_path):
        return str(tmp_path / "ctx.json")

    def test_all_three_fields_round_trip(self, tmp_path):
        r, _ = short_runner()
        ctx = ctx_for(r, original_thesis_invalidation=INVALIDATION,
                      active_protective_stop=IN_PROFIT,
                      protection_baseline_armed=True)
        ctx.path = self.path(tmp_path)
        ctx.save()
        back = SL.ExecutionContext.load(ctx.path)
        assert back.original_thesis_invalidation == INVALIDATION
        assert back.active_protective_stop == IN_PROFIT
        assert back.protection_baseline_armed is True

    def test_the_advanced_stop_is_what_survives_not_the_invalidation(self, tmp_path):
        r, _ = short_runner()
        ctx = ctx_for(r, original_thesis_invalidation=INVALIDATION,
                      active_protective_stop=IN_PROFIT,
                      protection_baseline_armed=True)
        ctx.path = self.path(tmp_path)
        ctx.save()
        back = SL.ExecutionContext.load(ctx.path)
        assert back.active_protective_stop != back.original_thesis_invalidation

    def test_a_legacy_record_is_never_read_as_armed(self, tmp_path):
        """A context written before this unit has no flag at all."""
        import json
        p = self.path(tmp_path)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"candidate_id": "c-1", "direction": "bearish",
                       "structural_stop_price": INVALIDATION}, fh)
        back = SL.ExecutionContext.load(p)
        assert back.protection_baseline_armed is False
        assert back.active_protective_stop is None

    def test_the_whitelist_actually_names_them(self):
        """AST-free but literal: the bug would be a silent omission."""
        import inspect
        src = inspect.getsource(SL.ExecutionContext.load)
        for name in ("original_thesis_invalidation", "active_protective_stop",
                     "protection_baseline_armed"):
            assert f'"{name}"' in src, name


class TestRestartCannotWidenProtection:
    def test_an_armed_position_refuses_a_second_reanchor(self):
        r, session = short_runner()
        ctx = ctx_for(r, original_thesis_invalidation=INVALIDATION,
                      active_protective_stop=IN_PROFIT,
                      protection_baseline_armed=True)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert out["reanchored"] is False
        assert out["reason"] == PS.BASELINE_ALREADY_ARMED

    def test_the_refusal_issues_no_venue_modify(self):
        r, session = short_runner()
        ctx_for(r, original_thesis_invalidation=INVALIDATION,
                active_protective_stop=IN_PROFIT, protection_baseline_armed=True)
        r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert session.modifies == []

    def test_the_refusal_does_NOT_flatten_a_healthy_position(self):
        """Killing a managed position to resolve our own bookkeeping would be
        the worse outcome."""
        r, session = short_runner()
        ctx_for(r, original_thesis_invalidation=INVALIDATION,
                active_protective_stop=IN_PROFIT, protection_baseline_armed=True)
        r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert session.closed == []
        assert session.cancelled == []

    def test_already_established_is_establishment_not_failure(self):
        """Otherwise production halts a healthy position on PROTECTION_MISSING."""
        r, session = short_runner()
        ctx_for(r, original_thesis_invalidation=INVALIDATION,
                active_protective_stop=IN_PROFIT, protection_baseline_armed=True)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert out["already_established"] is True
        established = bool(out.get("reanchored") or out.get("already_established"))
        assert established is True


class TestArmedFlagIsNotRestartProof:
    """A persisted flag lives in yesterday's JSON. It cannot answer "what will
    actually exit me now" -- only the venue can.

    The flag buys a refusal to re-anchor. It never buys a claim of
    establishment.
    """

    def armed(self, runner):
        return ctx_for(runner, original_thesis_invalidation=INVALIDATION,
                       active_protective_stop=IN_PROFIT,
                       protection_baseline_armed=True)

    def test_armed_plus_MISSING_venue_stop_is_not_established(self):
        r, _ = short_runner()
        self.armed(r)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=[])
        assert out["already_established"] is False
        assert out["reason"] == "protection_unproven_at_venue"

    def test_that_case_reports_protection_UNESTABLISHED_to_production(self):
        """`establish_structural_protection` must not call this healthy, or a
        naked position is treated as a managed one."""
        r, _ = short_runner()
        self.armed(r)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=[])
        established = bool(out.get("reanchored") or out.get("already_established"))
        assert established is False

    def test_a_FOREIGN_stop_does_not_satisfy_establishment(self):
        """An order we cannot prove is ours is not our protection."""
        r, _ = short_runner()
        self.armed(r)
        foreign = [{"id": 7777, "contract_id": MNQ.id, "type": 4, "size": 1,
                    "stop_price": 29460.0}]
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=foreign)
        assert out["already_established"] is False

    def test_an_UNREADABLE_venue_does_not_satisfy_establishment(self):
        r, session = short_runner()
        ctx = self.armed(r)

        def boom():
            raise RuntimeError("venue down")
        session.open_orders = boom
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=None)
        assert out["already_established"] is False
        assert ctx.active_protective_stop == IN_PROFIT   # nothing invented

    def test_a_PROVEN_venue_stop_does_satisfy_establishment(self):
        r, session = short_runner()
        self.armed(r)
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=session.open_orders())
        assert out["already_established"] is True
        assert out["adoption"]["outcome"] in (PS.ADOPTED, PS.IDENTICAL)

    def test_restart_reconciles_venue_truth_into_local_state(self):
        """load context -> inspect owned stop -> adopt -> only then established."""
        r, session = short_runner()
        ctx = self.armed(r)                      # local believes 29447
        orders = _children(ENTRY, "bearish", stop_ticks=20, target_ticks=200)
        orders[0]["stop_price"] = INVALIDATION   # venue actually holds 29470.25
        out = r.reanchor_protection_to_structure(
            fill_event=_fill(ENTRY), working_orders=orders)
        assert ctx.active_protective_stop == INVALIDATION
        assert out["adoption"]["local_believed_tighter"] is True
        assert out["already_established"] is True

    def test_the_guard_never_modifies_the_venue(self):
        r, session = short_runner()
        self.armed(r)
        for orders in ([], session.open_orders()):
            r.reanchor_protection_to_structure(
                fill_event=_fill(ENTRY), working_orders=orders)
        assert session.modifies == []
        assert session.closed == []
        assert session.cancelled == []


class TestReconciliationPolarity:
    """The flags are easy to invert and expensive to get wrong, so both
    directions are pinned with explicit numbers rather than reasoning."""

    @pytest.mark.parametrize("direction,local,venue", [
        ("bearish", 29420.0, 29440.0),   # short: lower is tighter
        ("bullish", 29440.0, 29420.0),   # long:  higher is tighter
    ])
    def test_local_tighter_than_venue_is_the_DANGEROUS_case(self, direction,
                                                            local, venue):
        """The process believed it had more protection than the venue holds."""
        out = PS.reconcile_with_venue(direction=direction,
                                      active_protective_stop=local,
                                      venue_stop_price=venue)
        assert out["local_believed_tighter"] is True
        assert out["local_believed_wider"] is False
        assert out["adopted"] == venue

    @pytest.mark.parametrize("direction,local,venue", [
        ("bearish", 29440.0, 29420.0),
        ("bullish", 29420.0, 29440.0),
    ])
    def test_venue_tighter_than_local_means_local_believed_WIDER(self, direction,
                                                                 local, venue):
        out = PS.reconcile_with_venue(direction=direction,
                                      active_protective_stop=local,
                                      venue_stop_price=venue)
        assert out["local_believed_wider"] is True
        assert out["local_believed_tighter"] is False
        assert out["adopted"] == venue

    def test_the_two_flags_are_never_both_true(self):
        for direction in ("bearish", "bullish"):
            for local, venue in ((29420.0, 29440.0), (29440.0, 29420.0)):
                out = PS.reconcile_with_venue(
                    direction=direction, active_protective_stop=local,
                    venue_stop_price=venue)
                assert not (out["local_believed_tighter"] and
                            out["local_believed_wider"])

    def test_the_helper_asks_whether_LOCAL_is_tighter(self):
        """Guards the argument order that makes the mapping read backwards:
        `reduces_risk(side, venue, local)` asks 'is LOCAL less risk than the
        venue', not 'is the venue tighter'."""
        assert PS.reduces_risk("bearish", 29440.0, 29420.0) is True
        assert PS.reduces_risk("bearish", 29420.0, 29440.0) is False


class TestVenueIsTruth:
    def test_a_tighter_venue_stop_is_adopted(self):
        r, session = short_runner()
        ctx = ctx_for(r, active_protective_stop=INVALIDATION,
                      original_thesis_invalidation=INVALIDATION,
                      protection_baseline_armed=True)
        orders = _children(ENTRY, "bearish", stop_ticks=20, target_ticks=200)
        orders[0]["stop_price"] = IN_PROFIT
        out = r.adopt_venue_protection(orders)
        assert out["outcome"] == PS.ADOPTED
        assert ctx.active_protective_stop == IN_PROFIT

    def test_a_WIDER_venue_stop_is_also_adopted(self):
        """NOT a monotonic violation. Monotonicity governs proposals we author,
        never observations of a reality that does not answer to us."""
        r, session = short_runner()
        ctx = ctx_for(r, active_protective_stop=IN_PROFIT,
                      original_thesis_invalidation=INVALIDATION,
                      protection_baseline_armed=True)
        orders = _children(ENTRY, "bearish", stop_ticks=20, target_ticks=200)
        orders[0]["stop_price"] = INVALIDATION
        out = r.adopt_venue_protection(orders)
        assert out["outcome"] == PS.ADOPTED
        assert ctx.active_protective_stop == INVALIDATION

    def test_believing_we_were_better_protected_is_flagged_as_the_dangerous_case(self):
        out = PS.reconcile_with_venue(direction="bearish",
                                      active_protective_stop=IN_PROFIT,
                                      venue_stop_price=INVALIDATION)
        assert out["local_believed_tighter"] is True
        assert out["local_believed_wider"] is False
        assert out["divergence"] is True

    def test_the_safe_divergence_is_reported_separately(self):
        out = PS.reconcile_with_venue(direction="bearish",
                                      active_protective_stop=INVALIDATION,
                                      venue_stop_price=IN_PROFIT)
        assert out["local_believed_wider"] is True
        assert out["local_believed_tighter"] is False

    def test_agreement_is_not_a_divergence(self):
        out = PS.reconcile_with_venue(direction="bearish",
                                      active_protective_stop=INVALIDATION,
                                      venue_stop_price=INVALIDATION)
        assert out["outcome"] == PS.IDENTICAL
        assert out["divergence"] is False

    def test_adoption_never_writes_back_to_the_venue(self):
        r, session = short_runner()
        ctx_for(r, active_protective_stop=IN_PROFIT,
                protection_baseline_armed=True)
        orders = _children(ENTRY, "bearish", stop_ticks=20, target_ticks=200)
        orders[0]["stop_price"] = INVALIDATION
        r.adopt_venue_protection(orders)
        assert session.modifies == []
        assert session.closed == []

    def test_an_unprovable_stop_is_not_a_source_of_truth(self):
        """An order whose lineage is not ours never moves local state."""
        r, _ = short_runner()
        ctx = ctx_for(r, active_protective_stop=IN_PROFIT,
                      protection_baseline_armed=True)
        foreign = [{"id": 7777, "contract_id": MNQ.id, "type": 4, "size": 1,
                    "stop_price": 29999.0}]
        out = r.adopt_venue_protection(foreign)
        assert out["outcome"] == PS.NO_VENUE_STOP
        assert ctx.active_protective_stop == IN_PROFIT

    def test_no_working_stop_leaves_local_state_alone(self):
        r, _ = short_runner()
        ctx = ctx_for(r, active_protective_stop=IN_PROFIT,
                      protection_baseline_armed=True)
        out = r.adopt_venue_protection([])
        assert out["outcome"] == PS.NO_VENUE_STOP
        assert ctx.active_protective_stop == IN_PROFIT

    def test_an_unreadable_venue_does_not_invent_protection(self):
        r, session = short_runner()
        ctx = ctx_for(r, active_protective_stop=IN_PROFIT,
                      protection_baseline_armed=True)

        def boom():
            raise RuntimeError("venue down")
        session.open_orders = boom
        out = r.adopt_venue_protection()
        assert out["outcome"] == PS.NO_VENUE_STOP
        assert out["reason"] == "venue_unreadable"
        assert ctx.active_protective_stop == IN_PROFIT


class TestSlippageMeasuresTheWorkingStop:
    def test_the_exit_reference_prefers_the_active_stop(self):
        import inspect
        from broker import topstepx_production_session as PSN
        src = inspect.getsource(PSN.ProductionSession.reconcile_exit)
        assert "ctx.active_protective_stop" in src
        # the older fields survive only as the fallback
        assert src.index("ctx.active_protective_stop") < \
               src.index("ctx.structural_stop_price")

    def test_an_unarmed_position_still_falls_back(self):
        import inspect
        from broker import topstepx_production_session as PSN
        src = inspect.getsource(PSN.ProductionSession.reconcile_exit)
        assert "ctx.structural_stop_price" in src
        assert "candidate.invalidation_price" in src


class TestScopeRestraint:
    """Unit 1 makes state truthful. It does not manage anything."""

    def test_no_luna_management_vocabulary_yet(self):
        import inspect
        src = inspect.getsource(PS).lower()
        for banned in ("advance_protection", "hold_protection", "exit_position"):
            assert banned not in src, banned

    def test_the_retired_structure_trail_is_not_resurrected(self):
        from paper_execution import trade_manager
        import inspect
        src = inspect.getsource(trade_manager)
        assert "protection_state" not in src
        assert "active_protective_stop" not in src

    def test_no_partials_and_no_native_trailing(self):
        """Checked on NAMES, not prose. The docstring says both words precisely
        because it is declaring what the module refuses to do, and a text scan
        would fail on its own disclaimer."""
        import ast
        import inspect
        names = set()
        for node in ast.walk(ast.parse(inspect.getsource(PS))):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.add(node.name.lower())
            elif isinstance(node, ast.Name):
                names.add(node.id.lower())
            elif isinstance(node, ast.Attribute):
                names.add(node.attr.lower())
            elif isinstance(node, ast.keyword) and node.arg:
                names.add(node.arg.lower())
        for name in names:
            assert "partial" not in name, name
            assert "trail" not in name, name

    def test_the_verifier_is_pure(self):
        """It touches no broker, no clock and no state."""
        import inspect
        src = inspect.getsource(PS.evaluate_advance)
        for banned in ("session", "modify_order", "time.", "open_orders"):
            assert banned not in src, banned

    def test_no_risk_doctrine_moved(self):
        from broker import topstepx_combine_risk as RK
        assert (RK.PREFERRED_MAX_STOP_POINTS, RK.ABSOLUTE_MAX_STOP_POINTS) == (35.0, 50.0)
        assert RK.PRODUCTION_MAX_RISK_USD == 350.00
