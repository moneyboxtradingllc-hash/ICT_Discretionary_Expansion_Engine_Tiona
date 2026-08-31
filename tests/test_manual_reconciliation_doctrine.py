"""Manual-vs-bot attribution, liquidity-objective validity and staleness law.

Grounded in the real 2026-08-05 event: Maurice traded this Combine manually
(5 MNQ short, +$40 gross / +$36.40 net, no customTag) while the bot collected
candles. No network; no orders.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from broker import topstepx_session_ledger as ledger              # noqa: E402
from broker import topstepx_smoke_auth as auth                    # noqa: E402
from broker.topstepx_candidate_freshness import (                 # noqa: E402
    CandidateSnapshot, CandidateStale, LiquidityObjective, assess, validate_objective,
)

NOW = datetime(2026, 8, 5, 15, 30, tzinfo=timezone.utc)
CID = "CON.F.US.MNQ.U26"
FP = "acct:fc84f7a928d9"

# The two real manual fills, verbatim shape from /api/Trade/search.
MANUAL_TRADES = [
    {"id": 2952155404, "contractId": CID, "side": 0, "size": 5, "price": 29868.75,
     "profitAndLoss": 40.0, "fees": 1.8, "customTag": None,
     "creationTimestamp": "2026-08-05T14:31:26.849693+00:00"},
    {"id": 2952150686, "contractId": CID, "side": 1, "size": 5, "price": 29872.75,
     "profitAndLoss": 0.0, "fees": 1.8, "customTag": None,
     "creationTimestamp": "2026-08-05T14:31:11.372504+00:00"},
]


def objective(price=29910.25, kind="prior_session_high", at=None):
    return LiquidityObjective(identity=f"{kind}@{price}", kind=kind, price=price,
                              created_at=at or (NOW - timedelta(minutes=2)))


def candidate(**over):
    kw = dict(candidate_id="c1", snapshot_id="snap-1", direction="bullish",
              entry_price=29880.0, invalidation_price=29872.0, objective=objective(),
              contract_id=CID, account_fingerprint=FP, created_at=NOW - timedelta(minutes=1),
              narrative="bullish continuation", account_state_digest="")
    kw.update(over)
    return CandidateSnapshot(**kw)


def market(**over):
    kw = dict(current_price=29885.0, high_since=29890.0, low_since=29878.0,
              tick_size=0.25, snapshot_id="snap-1", contract_id=CID,
              account_fingerprint=FP, account_state_digest="", data_age_seconds=2.0,
              in_window=True, manual_activity=False, now=NOW)
    kw.update(over)
    return kw


# ══════════════════════════════════════════════════════════════════════════════
class TestOriginAttribution:

    def test_an_untagged_trade_is_manual_not_bot(self):
        """The real manual fills carried no customTag."""
        for t in MANUAL_TRADES:
            assert ledger.classify(t) == ledger.MANUAL_OPERATOR

    def test_a_tagged_trade_from_a_known_token_is_the_bot(self):
        t = {"customTag": ledger.bot_tag("smoke-abc123")}
        assert ledger.classify(t, {"smoke-abc123"}) == ledger.EXPANSION_BOT

    def test_a_tag_from_an_unknown_token_is_external_not_bot(self):
        t = {"customTag": ledger.bot_tag("smoke-neverissued")}
        assert ledger.classify(t, {"smoke-abc123"}) == ledger.UNKNOWN_EXTERNAL

    def test_a_foreign_tag_is_external(self):
        assert ledger.classify({"customTag": "someone-elses-bot"}) == ledger.UNKNOWN_EXTERNAL

    def test_the_manual_trade_does_not_consume_the_bot_allowance(self, tmp_path):
        led = ledger.SessionLedger.load_or_new(FP, "20260805", str(tmp_path))
        led.reconcile_trades(MANUAL_TRADES)
        assert led.bot_filled_trade_count() == 0
        assert led.manual_trade_count() == 2

    def test_realized_pnl_is_attributed_to_the_operator(self, tmp_path):
        led = ledger.SessionLedger.load_or_new(FP, "20260805", str(tmp_path))
        led.reconcile_trades(MANUAL_TRADES)
        by = led.realized_by_origin()
        assert by[ledger.MANUAL_OPERATOR] == pytest.approx(36.40, abs=0.01)
        assert ledger.EXPANSION_BOT not in by

    def test_unknown_activity_forces_a_pause(self, tmp_path):
        led = ledger.SessionLedger.load_or_new(FP, "20260805", str(tmp_path))
        led.reconcile_trades([{"customTag": "mystery", "profitAndLoss": 5.0}])
        assert led.requires_pause() is not None
        assert "Refusing to add exposure" in led.requires_pause()

    def test_a_clean_manual_session_does_not_force_a_pause(self, tmp_path):
        led = ledger.SessionLedger.load_or_new(FP, "20260805", str(tmp_path))
        led.reconcile_trades(MANUAL_TRADES)
        assert led.requires_pause() is None

    def test_the_ledger_persists_and_reloads(self, tmp_path):
        led = ledger.SessionLedger.load_or_new(FP, "20260805", str(tmp_path))
        led.reconcile_trades(MANUAL_TRADES)
        led.save()
        again = ledger.SessionLedger.load_or_new(FP, "20260805", str(tmp_path))
        assert again.manual_trade_count() == 2

    def test_the_account_state_digest_changes_when_pnl_changes(self):
        a = ledger.account_state_digest(balance=50000.0, positions=0, orders=0, realized=0.0)
        b = ledger.account_state_digest(balance=50033.9, positions=0, orders=0, realized=36.4)
        assert a != b


class TestLiquidityObjective:

    def test_a_valid_unswept_objective_passes(self):
        v = validate_objective(objective(), direction="bullish", entry_price=29880.0,
                               high_since=29890.0, low_since=29878.0,
                               current_price=29885.0, tick_size=0.25, now=NOW)
        assert v["valid"] is True

    def test_an_objective_already_swept_is_refused(self):
        with pytest.raises(CandidateStale) as exc:
            validate_objective(objective(29910.25), direction="bullish",
                               entry_price=29880.0, high_since=29915.0,
                               low_since=29878.0, current_price=29912.0,
                               tick_size=0.25, now=NOW)
        assert exc.value.reason == "objective_swept"
        assert "do not move it farther away" in str(exc.value)

    def test_a_materially_delivered_objective_is_refused(self):
        """Entering after most of the move buys the remainder, not the trade."""
        with pytest.raises(CandidateStale) as exc:
            validate_objective(objective(29910.0), direction="bullish",
                               entry_price=29880.0, high_since=29905.0,
                               low_since=29878.0, current_price=29904.0,
                               tick_size=0.25, now=NOW)
        assert exc.value.reason == "objective_materially_delivered"

    def test_an_unknown_objective_kind_is_refused(self):
        bad = LiquidityObjective("x@1", "vibes", 29910.0, NOW)
        with pytest.raises(CandidateStale) as exc:
            validate_objective(bad, direction="bullish", entry_price=29880.0,
                               high_since=29890.0, low_since=29878.0,
                               current_price=29885.0, tick_size=0.25, now=NOW)
        assert exc.value.reason == "objective_unknown_kind"

    def test_a_wrong_side_objective_is_refused(self):
        with pytest.raises(CandidateStale) as exc:
            validate_objective(objective(29870.0), direction="bullish",
                               entry_price=29880.0, high_since=29890.0,
                               low_since=29878.0, current_price=29885.0,
                               tick_size=0.25, now=NOW)
        assert exc.value.reason == "objective_wrong_side"

    def test_an_off_tick_objective_is_refused(self):
        with pytest.raises(CandidateStale) as exc:
            validate_objective(objective(29910.13), direction="bullish",
                               entry_price=29880.0, high_since=29890.0,
                               low_since=29878.0, current_price=29885.0,
                               tick_size=0.25, now=NOW)
        assert exc.value.reason == "objective_off_tick"

    def test_a_stale_objective_is_refused(self):
        with pytest.raises(CandidateStale) as exc:
            validate_objective(objective(at=NOW - timedelta(hours=2)),
                               direction="bullish", entry_price=29880.0,
                               high_since=29890.0, low_since=29878.0,
                               current_price=29885.0, tick_size=0.25, now=NOW)
        assert exc.value.reason == "data_stale"


class TestStalenessLaw:

    def test_a_fresh_candidate_passes(self):
        assert assess(candidate(), **market())["fresh"] is True

    @pytest.mark.parametrize("over,reason", [
        ({"in_window": False}, "window_closed"),
        ({"contract_id": "CON.F.US.MNQ.Z26"}, "contract_changed"),
        ({"account_fingerprint": "acct:other"}, "account_state_changed"),
        ({"snapshot_id": "snap-2"}, "snapshot_superseded"),
        ({"manual_activity": True}, "manual_activity"),
        ({"data_age_seconds": 500.0}, "data_stale"),
        ({"low_since": 29870.0}, "invalidation_touched"),
        ({"high_since": 29915.0, "current_price": 29912.0}, "objective_swept"),
        ({"narrative": "bearish reversal"}, "narrative_changed"),
    ])
    def test_each_drift_condition_invalidates(self, over, reason):
        with pytest.raises(CandidateStale) as exc:
            assess(candidate(), **market(**over))
        assert exc.value.reason == reason

    def test_manual_activity_after_approval_kills_the_candidate(self):
        """The exact 2026-08-05 hazard: the operator traded mid-session."""
        with pytest.raises(CandidateStale) as exc:
            assess(candidate(), **market(manual_activity=True))
        assert "operator activity changed the account" in str(exc.value)

    def test_an_account_state_change_invalidates(self):
        c = candidate(account_state_digest="acctstate:aaa")
        with pytest.raises(CandidateStale) as exc:
            assess(c, **market(account_state_digest="acctstate:bbb"))
        assert exc.value.reason == "account_state_changed"

    def test_the_module_offers_no_way_to_repair_a_stale_candidate(self):
        """Repair is not a permitted outcome, so no API expresses it."""
        import broker.topstepx_candidate_freshness as f
        for banned in ("repair", "adjust", "extend_target", "widen_stop", "move_target"):
            assert not hasattr(f, banned)


class TestThesisBoundToken:

    def _token(self, **over):
        kw = dict(phrase=auth.AUTHORIZATION_PHRASE, account_fingerprint=FP,
                  contract_id=CID, direction="bullish", stop_price=29872.0,
                  target_price=29910.25, target_identity="prior_session_high@29910.25",
                  now=NOW)
        kw.update(over)
        return auth.issue(**kw)

    def test_a_token_is_bound_to_its_direction(self):
        t = self._token()
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(t, account_fingerprint=FP, contract_id=CID,
                                      size=1, risk_usd=10.0, direction="bearish", now=NOW)
        assert "bullish thesis" in str(exc.value)

    def test_a_token_is_bound_to_its_structural_stop(self):
        t = self._token()
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(t, account_fingerprint=FP, contract_id=CID,
                                      size=1, risk_usd=10.0, stop_price=29860.0, now=NOW)
        assert "bound to stop" in str(exc.value)

    def test_a_token_is_bound_to_its_target_price(self):
        t = self._token()
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(t, account_fingerprint=FP, contract_id=CID,
                                      size=1, risk_usd=10.0, target_price=29999.0, now=NOW)
        assert "bound to target" in str(exc.value)

    def test_a_token_is_bound_to_its_objective_identity(self):
        """Same price, different draw, is still a different thesis."""
        t = self._token()
        with pytest.raises(auth.AuthorizationError) as exc:
            auth.authorize_submission(t, account_fingerprint=FP, contract_id=CID,
                                      size=1, risk_usd=10.0,
                                      target_identity="session_high@29910.25", now=NOW)
        assert "bound to objective" in str(exc.value)

    def test_the_matching_thesis_is_authorized_once(self):
        t = self._token()
        auth.authorize_submission(t, account_fingerprint=FP, contract_id=CID, size=1,
                                  risk_usd=10.0, direction="bullish", stop_price=29872.0,
                                  target_price=29910.25,
                                  target_identity="prior_session_high@29910.25", now=NOW)
        assert t.spent

    def test_the_token_describes_its_thesis_without_secrets(self):
        d = self._token().describe()
        assert d["direction"] == "bullish" and d["target_identity"]
        assert "_secret" not in d


class TestAttributionViaOrderJoin:
    """REGRESSION - measured live 2026-08-05.

    Order 3367891717 was submitted with customTag 'EXPBOT-execsmoke-171100'.
    The resulting trade 2953374559 reported customTag=None, so reading the tag
    off the trade attributed the bot's own fill to the operator. The tag lives
    on the ORDER; trades carry orderId.
    """

    BOT_ORDER = {"id": 3367891717, "customTag": "EXPBOT-execsmoke-171100"}
    BOT_TRADE = {"id": 2953374559, "orderId": 3367891717, "customTag": None,
                 "size": 1, "side": 0, "price": 29746.0,
                 "profitAndLoss": None, "fees": 0.36, "commissions": 0.25}
    BOT_EXIT = {"id": 2953376245, "orderId": 3367893535, "customTag": None,
                "size": 1, "side": 1, "price": 29751.5,
                "profitAndLoss": 11.0, "fees": 0.36, "commissions": 0.25}

    def test_a_tagless_trade_is_attributed_through_its_order(self):
        origin = ledger.classify(self.BOT_TRADE, {"execsmoke-171100"},
                                 {3367891717: self.BOT_ORDER})
        assert origin == ledger.EXPANSION_BOT

    def test_without_the_join_the_bot_trade_looks_manual(self):
        """The exact defect: no order index, so the tag is invisible."""
        assert ledger.classify(self.BOT_TRADE, {"execsmoke-171100"}) == ledger.MANUAL_OPERATOR

    def test_reconcile_trades_accepts_orders_and_attributes_correctly(self, tmp_path):
        led = ledger.SessionLedger.load_or_new(FP, "20260805", str(tmp_path))
        led.record_token("execsmoke-171100")
        led.reconcile_trades([self.BOT_TRADE, self.BOT_EXIT], orders=[self.BOT_ORDER])
        assert led.bot_filled_trade_count() == 1     # only the tagged entry
        assert led.manual_trade_count() == 1         # the exit order carried no tag

    def test_an_unknown_order_tag_is_still_external(self):
        origin = ledger.classify({"orderId": 99, "customTag": None}, {"known"},
                                 {99: {"id": 99, "customTag": "EXPBOT-neverissued"}})
        assert origin == ledger.UNKNOWN_EXTERNAL

    def test_a_manual_ui_order_with_a_guid_tag_is_external_not_bot(self):
        """The operator's UI order carried a GUID; it must never read as bot."""
        origin = ledger.classify({"orderId": 7, "customTag": None}, set(),
                                 {7: {"id": 7, "customTag": "a9726eb4-e19e-4c5b-9615-06fcab9a3488"}})
        assert origin == ledger.UNKNOWN_EXTERNAL


class TestCommissionAccounting:
    """REGRESSION - the unexplained P&L gap, solved 2026-08-05.

    `commissions` is billed separately from `fees`. Omitting it left
    gross-minus-fees overstating net by $2.50 (manual) and $0.50 (bot).
    Including it reconciles the whole day to the cent: 51.00 - 4.32 - 3.00
    = 43.68 = the exact balance movement.
    """

    DAY = [
        {"size": 5, "profitAndLoss": None, "fees": 1.8, "commissions": 1.25},
        {"size": 5, "profitAndLoss": 40.0, "fees": 1.8, "commissions": 1.25},
        {"size": 1, "profitAndLoss": None, "fees": 0.36, "commissions": 0.25},
        {"size": 1, "profitAndLoss": 11.0, "fees": 0.36, "commissions": 0.25},
    ]

    def test_the_full_day_reconciles_to_the_balance_movement(self, tmp_path):
        led = ledger.SessionLedger.load_or_new(FP, "20260805", str(tmp_path))
        led.reconcile_trades(self.DAY)
        total = sum(led.realized_by_origin().values())
        assert total == pytest.approx(43.68, abs=0.01)

    def test_commissions_are_recorded_per_trade(self, tmp_path):
        led = ledger.SessionLedger.load_or_new(FP, "20260805", str(tmp_path))
        led.reconcile_trades(self.DAY)
        assert all("commissions" in e for e in led.entries)

    def test_omitting_commissions_would_overstate_net(self):
        gross = sum(float(t.get("profitAndLoss") or 0) for t in self.DAY)
        fees = sum(float(t["fees"]) for t in self.DAY)
        comm = sum(float(t["commissions"]) for t in self.DAY)
        assert gross - fees == pytest.approx(46.68, abs=0.01)      # the old, wrong figure
        assert gross - fees - comm == pytest.approx(43.68, abs=0.01)
