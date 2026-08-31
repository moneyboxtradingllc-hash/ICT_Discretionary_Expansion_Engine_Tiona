"""POSITION-MANAGEMENT-BREAK-EVEN-1 — the layer that owns a trade after it exists.

2026-08-24, live PRAC. Luna authored the thesis, mechanics verified it, risk
sized it, execution submitted it, the venue filled 8 MNQ short at 29090.25 with
an 18.00-point requested stop. Then nothing. The organism had no opinion about
the open position at all, and the operator closed it by hand.

Two facts from that trade drive this whole file:

  ACTUAL FILL, NOT REQUESTED ENTRY. Requested 29092.25, filled 29090.25 -- a
  2.00-point improvement. Against the same 29110.25 stop that is 18.00 points
  of requested risk and 20.00 points of REAL risk. Managing from the request
  moves protection at the wrong moment.

  BREAK-EVEN IS NOT THE FILL. Closing at the fill loses the round trip, so the
  target price is offset by the SAME canonical friction sizing already uses.

No broker. No provider. No clock. No live trade.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import break_even as BE                                  # noqa: E402
from broker import protection_state as PS                            # noqa: E402
from broker.topstepx_client import TopstepXContract                  # noqa: E402

MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQ", description="",
                       tick_size=0.25, tick_value=0.50, active=True)

# The real 2026-08-24 trade.
FILL, REQUESTED, STOP = 29090.25, 29092.25, 29110.25


def _code_only(module) -> str:
    """Module source with comments and docstrings stripped.

    A source guard proves the CODE does not do something. Grepping raw text
    also greps the prose explaining why it must not, so the more carefully a
    prohibition is documented the more likely the guard trips on its own
    explanation.
    """
    import inspect
    import io
    import tokenize
    out = []
    for tok in tokenize.generate_tokens(
            io.StringIO(inspect.getsource(module)).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def ev(**kw):
    base = dict(direction="short", entry_fill_price=FILL, initial_stop_price=STOP,
                active_protective_stop=STOP, current_price=29060.0, armed=True,
                contract=MNQ)
    base.update(kw)
    return BE.evaluate(**base)


# ══════════════════════════════════════════════════════════════════════════════
class TestRIsMeasuredFromTheActualFill:

    def test_requested_and_actual_R_really_differ_on_the_live_trade(self):
        """Guard against a vacuous suite: if they were equal, every assertion
        below about using the fill would prove nothing."""
        req = BE.initial_risk_points(direction="short", entry_fill_price=REQUESTED,
                                     initial_stop_price=STOP)
        act = BE.initial_risk_points(direction="short", entry_fill_price=FILL,
                                     initial_stop_price=STOP)
        assert req == 18.0 and act == 20.0

    def test_the_trigger_uses_actual_R_not_requested_R(self):
        """At 1R-from-requested the position is only 0.9R real. Managing from
        the request would protect early."""
        one_r_from_requested = REQUESTED - 18.0        # 29074.25
        d = ev(current_price=one_r_from_requested)
        assert d["outcome"] == BE.HOLD
        assert d["open_r"] < BE.TRIGGER_R

    def test_long_and_short_are_mirrored(self):
        assert BE.initial_risk_points(direction="long", entry_fill_price=100.0,
                                      initial_stop_price=90.0) == 10.0
        assert BE.initial_risk_points(direction="short", entry_fill_price=100.0,
                                      initial_stop_price=110.0) == 10.0

    def test_positive_entry_slippage_enlarges_real_risk(self):
        better = BE.initial_risk_points(direction="short", entry_fill_price=29090.25,
                                        initial_stop_price=STOP)
        assert better > 18.0

    def test_negative_entry_slippage_shrinks_real_risk(self):
        worse = BE.initial_risk_points(direction="short", entry_fill_price=29095.0,
                                       initial_stop_price=STOP)
        assert worse < 18.0


class TestTheTrigger:

    def test_below_one_r_holds(self):
        d = ev(current_price=FILL - 20.0 * 0.99)
        assert d["outcome"] == BE.HOLD and d["reason"] == BE.NOT_YET
        assert d.get("break_even_price") is None

    def test_exactly_one_r_proposes(self):
        d = ev(current_price=FILL - 20.0)
        assert d["outcome"] == BE.PROPOSE
        assert d["open_r"] == pytest.approx(1.0)

    def test_beyond_one_r_proposes_the_same_price(self):
        a = ev(current_price=FILL - 20.0)
        b = ev(current_price=FILL - 60.0)
        assert a["break_even_price"] == b["break_even_price"]

    def test_a_long_triggers_on_the_other_side(self):
        d = BE.evaluate(direction="long", entry_fill_price=100.0,
                        initial_stop_price=90.0, active_protective_stop=90.0,
                        current_price=110.0, armed=True, friction_points=0.5)
        assert d["outcome"] == BE.PROPOSE
        assert d["break_even_price"] == 100.5      # beyond the fill, not at it

    def test_the_trigger_is_frozen_doctrine(self):
        assert BE.TRIGGER_R == 1.00


class TestCostAdjustment:

    def test_break_even_is_beyond_the_fill_never_at_it(self):
        be = BE.cost_adjusted_break_even(direction="short", entry_fill_price=FILL,
                                         contract=MNQ)
        assert be < FILL, "a short must protect BELOW the fill to be whole"

    def test_the_long_mirror(self):
        be = BE.cost_adjusted_break_even(direction="long", entry_fill_price=FILL,
                                         contract=MNQ)
        assert be > FILL

    def test_the_cost_comes_from_the_canonical_model(self):
        """Same fees, commissions and declared slippage reserve sizing uses --
        management and sizing must not disagree about what a trade costs.

        Asserted on the RAW offset, because the returned price is afterwards
        snapped to a venue tick and can therefore only ever protect MORE."""
        from broker.topstepx_combine_risk import friction_per_contract
        total = friction_per_contract(MNQ)["total"]
        expected_points = (total / MNQ.tick_value) * MNQ.tick_size
        raw = BE.cost_adjusted_break_even(direction="short", entry_fill_price=FILL,
                                          contract=MNQ, tick_size=None,
                                          friction_points=expected_points)
        assert FILL - raw >= expected_points - 1e-9
        # and the un-normalized path reproduces the model exactly
        bare = BE.cost_adjusted_break_even(direction="short", entry_fill_price=100.0,
                                           friction_points=expected_points)
        assert 100.0 - bare == pytest.approx(expected_points, abs=1e-6)

    def test_an_unavailable_cost_model_refuses_rather_than_guessing(self):
        d = ev(contract=None)
        assert d["outcome"] == BE.REFUSED
        assert d["reason"] == "cost_model_unavailable"

    def test_explicit_friction_overrides_the_lookup(self):
        be = BE.cost_adjusted_break_even(direction="short", entry_fill_price=100.0,
                                         friction_points=2.0)
        assert be == 98.0


class TestRefusals:

    def test_an_unarmed_baseline_is_refused(self):
        """A provisional broker bracket is not a management baseline."""
        d = ev(armed=False)
        assert d["outcome"] == BE.REFUSED and d["reason"] == BE.NOT_ARMED

    def test_a_missing_fill_is_refused(self):
        assert ev(entry_fill_price=None)["reason"] == BE.NO_FILL

    def test_a_missing_stop_is_refused(self):
        assert ev(initial_stop_price=None)["reason"] == BE.NO_STOP

    def test_a_missing_quote_is_refused_never_substituted(self):
        """EXEC-PRICE-FRESHNESS-1: a settled close is not where this executes."""
        d = ev(current_price=None)
        assert d["outcome"] == BE.REFUSED and d["reason"] == BE.NO_QUOTE

    def test_a_stop_on_the_wrong_side_is_refused(self):
        d = ev(initial_stop_price=FILL - 10.0)
        assert d["reason"] == BE.DEGENERATE_R

    def test_a_zero_width_stop_is_refused(self):
        assert ev(initial_stop_price=FILL)["reason"] == BE.DEGENERATE_R

    def test_an_unknown_direction_is_refused(self):
        assert ev(direction="sideways")["reason"] == BE.UNKNOWN_DIRECTION

    def test_nothing_raises_on_garbage(self):
        for bad in ("x", float("nan"), float("inf"), object()):
            assert BE.evaluate(direction="long", entry_fill_price=bad,
                               initial_stop_price=bad, active_protective_stop=bad,
                               current_price=bad, armed=True)["outcome"] in (
                BE.REFUSED, BE.HOLD)


class TestIdempotenceAndRatchet:

    def test_already_applied_short_circuits(self):
        d = ev(already_applied=True)
        assert d["outcome"] == BE.HOLD and d["reason"] == BE.ALREADY_APPLIED

    def test_repeated_observations_propose_an_identical_price(self):
        """Duplicate +1R observations must not produce a second amendment."""
        prices = {ev(current_price=FILL - 20.0 - i)["break_even_price"]
                  for i in range(6)}
        assert len(prices) == 1

    def test_the_second_proposal_is_a_no_op_at_the_verifier(self):
        """The real idempotence guarantee: even without the flag, the monotonic
        verifier answers NO_OP because protection is already there."""
        d = ev(current_price=FILL - 20.0)
        be = d["break_even_price"]
        again = PS.evaluate_advance(direction="short", active_protective_stop=be,
                                    proposed_stop=be, armed=True)
        assert again["outcome"] == PS.NO_OP

    def test_protection_already_better_than_break_even_holds(self):
        """No ratcheting backwards, and no pointless venue traffic."""
        d = ev(current_price=FILL - 60.0, active_protective_stop=FILL - 30.0)
        assert d["outcome"] == BE.HOLD
        assert d["reason"] == BE.WOULD_RESTORE_RISK

    def test_the_module_never_widens_a_stop(self):
        """Whatever it proposes must pass the monotonic verifier from the
        original stop, in both directions."""
        for direction, fill, stop, now in (("short", FILL, STOP, FILL - 40.0),
                                           ("long", 100.0, 90.0, 115.0)):
            d = BE.evaluate(direction=direction, entry_fill_price=fill,
                            initial_stop_price=stop, active_protective_stop=stop,
                            current_price=now, armed=True, friction_points=0.5)
            assert d["outcome"] == BE.PROPOSE
            v = PS.evaluate_advance(direction=direction, active_protective_stop=stop,
                                    proposed_stop=d["break_even_price"], armed=True)
            assert v["outcome"] == PS.ADVANCE, (direction, v)


class TestAuthorityBoundaries:
    """What this module is NOT allowed to be."""

    def test_it_never_calls_a_provider_or_a_broker(self):
        src = _code_only(BE)
        for forbidden in ("openai", "requests", "session.", "place_order",
                          "modify_order", "narrative_brain", "run_narrative"):
            assert forbidden not in src, forbidden

    def test_it_does_not_reimplement_the_monotonic_law(self):
        """`protection_state.evaluate_advance` is the single verifier. A second
        copy of 'may risk be restored' is the duplicated-authority defect."""
        src = _code_only(BE)
        assert "def evaluate_advance" not in src
        assert "reduces_risk" not in src

    def test_it_proposes_and_never_asserts_lawfulness(self):
        d = ev(current_price=FILL - 40.0)
        assert d["outcome"] == BE.PROPOSE
        assert "advance" not in str(d.get("outcome"))

    def test_it_owns_no_target_partial_or_trail(self):
        src = _code_only(BE).lower()
        for forbidden in ("take_profit", "target_price", "partial", "scale_out",
                          "trail"):
            assert forbidden not in src, forbidden

    def test_the_trigger_is_not_configurable_from_the_environment(self):
        """A tunable trigger invites fitting it to whichever session hurt most
        recently."""
        assert "getenv" not in _code_only(BE)


class TestTheLiveTradeSpecimen:
    """The 2026-08-24 position, end to end."""

    def test_it_would_have_protected_the_real_trade(self):
        d = ev(current_price=29070.25)          # exactly +1R from the real fill
        assert d["outcome"] == BE.PROPOSE
        assert d["initial_risk_points"] == 20.0
        assert d["break_even_price"] < FILL
        v = PS.evaluate_advance(direction="short", active_protective_stop=STOP,
                                proposed_stop=d["break_even_price"], armed=True)
        assert v["outcome"] == PS.ADVANCE

    def test_it_would_not_have_fired_early(self):
        assert ev(current_price=29075.0)["outcome"] == BE.HOLD


# ══════════════════════════════════════════════════════════════════════════════
class TestVenueTickNormalization:
    """A CORRECT NUMBER IS NOT AN EXECUTABLE ONE.

    The first certified build proposed 29088.64 against an MNQ tick of 0.25 --
    arithmetically right, impossible to submit, and exactly the kind of defect
    that surfaces as a rejected stop modification at the worst moment. Rounding
    must also go the SAFE way: the nearer tick 29088.75 protects 1.50 points
    against a 1.61 point friction allowance, i.e. it under-covers the round trip
    that break-even exists to cover."""

    def test_the_live_specimen_is_now_tick_valid(self):
        d = ev(current_price=FILL - 20.0)
        be = d["break_even_price"]
        assert be == 29088.50
        assert (be / MNQ.tick_size) == int(be / MNQ.tick_size)

    def test_the_live_specimen_still_covers_the_friction(self):
        from broker.topstepx_combine_risk import friction_per_contract
        pts = (friction_per_contract(MNQ)["total"] / MNQ.tick_value) * MNQ.tick_size
        be = ev(current_price=FILL - 20.0)["break_even_price"]
        assert (FILL - be) >= pts, "normalization must never under-cover costs"

    def test_the_nearer_tick_would_have_under_covered(self):
        """Pins WHY floor is correct for a short rather than round-to-nearest."""
        from broker.topstepx_combine_risk import friction_per_contract
        pts = (friction_per_contract(MNQ)["total"] / MNQ.tick_value) * MNQ.tick_size
        assert (FILL - 29088.75) < pts
        assert (FILL - 29088.50) >= pts

    def test_long_rounds_up_short_rounds_down(self):
        assert BE.normalize_to_tick(direction="long", raw_price=100.61,
                                    tick_size=0.25) == 100.75
        assert BE.normalize_to_tick(direction="short", raw_price=100.61,
                                    tick_size=0.25) == 100.50

    def test_a_raw_price_already_on_a_tick_is_unchanged(self):
        for side in ("long", "short"):
            assert BE.normalize_to_tick(direction=side, raw_price=100.50,
                                        tick_size=0.25) == 100.50

    def test_binary_noise_does_not_push_a_whole_extra_tick(self):
        """0.1+0.2 style representation error must not read as 'between ticks'
        and cost a full tick of protection."""
        noisy = 100.25 + 0.25 - 1e-13
        assert BE.normalize_to_tick(direction="long", raw_price=noisy,
                                    tick_size=0.25) == 100.50

    def test_normalization_is_never_toward_less_protection(self):
        import random
        rng = random.Random(20260824)
        for _ in range(400):
            raw = rng.uniform(90.0, 110.0)
            up = BE.normalize_to_tick(direction="long", raw_price=raw, tick_size=0.25)
            dn = BE.normalize_to_tick(direction="short", raw_price=raw, tick_size=0.25)
            assert up >= raw - 1e-9, (raw, up)
            assert dn <= raw + 1e-9, (raw, dn)
            for v in (up, dn):
                assert abs((v / 0.25) - round(v / 0.25)) < 1e-9

    def test_other_tick_geometries_work_without_hardcoding(self):
        assert BE.normalize_to_tick(direction="long", raw_price=100.03,
                                    tick_size=0.10) == 100.10
        assert BE.normalize_to_tick(direction="short", raw_price=100.03,
                                    tick_size=0.10) == 100.00

    def test_absent_tick_geometry_returns_the_raw_price_not_a_guess(self):
        assert BE.normalize_to_tick(direction="long", raw_price=100.61,
                                    tick_size=None) is None
        raw_only = BE.cost_adjusted_break_even(direction="short",
                                               entry_fill_price=100.0,
                                               friction_points=1.61)
        assert raw_only == 98.39

    def test_the_normalized_price_is_what_the_verifier_sees(self):
        """The monotonic law must reason about the price that will actually be
        submitted, in both directions."""
        d = ev(current_price=FILL - 20.0)
        v = PS.evaluate_advance(direction="short", active_protective_stop=STOP,
                                proposed_stop=d["break_even_price"], armed=True)
        assert v["outcome"] == PS.ADVANCE
        assert v["proposed_stop"] == 29088.50
        dl = BE.evaluate(direction="long", entry_fill_price=100.0,
                         initial_stop_price=90.0, active_protective_stop=90.0,
                         current_price=115.0, armed=True, friction_points=1.61,
                         tick_size=0.25)
        vl = PS.evaluate_advance(direction="long", active_protective_stop=90.0,
                                 proposed_stop=dl["break_even_price"], armed=True)
        assert dl["break_even_price"] == 101.75
        assert vl["outcome"] == PS.ADVANCE

    def test_normalization_cannot_turn_a_lawful_advance_unlawful(self):
        """Snapping must never cross the existing protection and become a risk
        restoration."""
        for direction, stop, fill in (("short", 100.5, 100.0), ("long", 99.5, 100.0)):
            d = BE.evaluate(direction=direction, entry_fill_price=fill,
                            initial_stop_price=stop,
                            active_protective_stop=stop,
                            current_price=(fill - 20 if direction == "short"
                                           else fill + 20),
                            armed=True, friction_points=1.61, tick_size=0.25)
            if d["outcome"] == BE.PROPOSE:
                v = PS.evaluate_advance(direction=direction,
                                        active_protective_stop=stop,
                                        proposed_stop=d["break_even_price"],
                                        armed=True)
                assert v["outcome"] in (PS.ADVANCE, PS.NO_OP), (direction, v)
