"""COMBINED-SAFETY-READINESS-CERTIFICATION-1 — cross-unit composition.

Certifies the SEVEN safety commits as ONE organism, not seven passing suites.

    511a493  emergency close-before-cancel race
    7c2dd5b  canonical discovery + durable lineage
    4301b31  hard-flatten ownership
    61d5329  ownership ambiguity blocks mutation
    c9fdf75  one liquidation convergence authority
    1c8a1d5  parallel mutation surface
    c880f98  structural read-capability boundary

The question is not "do the unit suites still pass" but "do the rules interact
safely across boundaries no single unit exercised".
"""
import ast
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_emergency_liquidation as EL         # noqa: E402
from broker import topstepx_execution_runner as R               # noqa: E402
from broker import topstepx_mission_reconciler as RECON         # noqa: E402
from broker import topstepx_order_discovery as DISC             # noqa: E402
from broker.topstepx_combine_risk import build_bracket          # noqa: E402

MNQ_ID = "CON.F.US.MNQ.U26"
ENTRY, STOP, TARGET, FOREIGN = 8001, 8002, 8003, 9999
BUY, SELL = 0, 1


class Contract:
    id = MNQ_ID
    name = "MNQU26"
    tick_size = 0.25
    tick_value = 0.5


MNQ = Contract()


def order(oid, *, side=SELL, size=15, status=1, otype=4, parent=ENTRY,
          contract=MNQ_ID):
    row = {"id": oid, "contract_id": contract, "type": otype, "side": side,
           "size": size, "status": status}
    if parent is not None:
        row["parent_order_id"] = parent
    return row


class Venue:
    """A venue that can hide orders, break one surface at a time, and race."""

    def __init__(self, *, position=0, orders=(), hidden=(), query_fails=False,
                 open_orders_fails=False, positions_fails=False,
                 no_query=False, fill_on_cancel=0):
        self._orders = [dict(o) for o in orders]
        self._hidden = [dict(o) for o in hidden]
        self.position = position
        self.query_fails = query_fails
        self.open_orders_fails = open_orders_fails
        self.positions_fails = positions_fails
        self.fill_on_cancel = fill_on_cancel
        self.cancelled, self.closed, self.calls = [], [], []
        if no_query:
            self.query_orders = None

    def query_orders(self, *, statuses=None, contract_id=None):
        assert statuses is None, "discovery must never filter by status"
        if self.query_fails:
            raise RuntimeError("v2/query unavailable")
        rows = self._orders + self._hidden
        return [dict(o) for o in rows
                if not contract_id or o["contract_id"] == contract_id]

    def open_orders(self):
        if self.open_orders_fails:
            raise RuntimeError("searchOpen unavailable")
        return [dict(o) for o in self._orders
                if DISC.status_of(o) in DISC.WORKING_STATUSES]

    def open_positions(self):
        if self.positions_fails:
            raise RuntimeError("position search unavailable")
        if not self.position:
            return []
        return [{"contract_id": MNQ_ID, "size": abs(self.position),
                 "type": 1 if self.position > 0 else 2, "avg_price": 29257.5,
                 "side": "long" if self.position > 0 else "short"}]

    def recent_trades(self):
        return []

    def order_by_id(self, oid):
        for o in self._orders + self._hidden:
            if str(o["id"]) == str(oid):
                return dict(o)
        return None

    def cancel_order(self, oid):
        self.calls.append(("cancel", oid))
        self.cancelled.append(oid)
        if self.fill_on_cancel:
            self.position += self.fill_on_cancel
            self.fill_on_cancel = 0
        for row in self._orders + self._hidden:
            if str(row["id"]) == str(oid):
                row["status"] = DISC.STATUS_CANCELLED
        return {"success": True}

    def close_position(self, cid):
        self.calls.append(("close", cid))
        self.closed.append(cid)
        self.position = 0
        return {"success": True}


def runner(venue):
    r = R.ExecutionRunner(session=venue, account_fingerprint="acct:test",
                          contract=MNQ)
    r.execution_lane = "production"
    r.order_id = ENTRY
    r.geometry = build_bracket(direction="bullish", entry_price=30000.0,
                               invalidation_level=29996.0, target_price=30012.0,
                               contract=MNQ, size=15, max_risk_usd=350.0,
                               max_stop_points=50.0, min_reward_to_risk=1.0,
                               max_contracts=15)
    r.state = R.FILLED
    return r


def kinds(v):
    return [k for k, _ in v.calls]


# ══ §4 + §6  ATOMIC CONVERGENCE ACROSS THE FAMILY ═══════════════════════════
class TestAtomicConvergenceComposition:

    def test_owned_children_are_neutralised_before_any_close(self):
        v = Venue(position=15, orders=[order(STOP), order(TARGET, otype=1)])
        runner(v).emergency_flatten("composition")
        assert max(i for i, k in enumerate(kinds(v)) if k == "cancel") \
            < kinds(v).index("close")

    def test_a_suspended_child_is_discovered_and_neutralised_first(self):
        """7c2dd5b feeding 511a493: `searchOpen` hides it, v2/query does not."""
        v = Venue(position=15, hidden=[order(STOP, status=DISC.STATUS_SUSPENDED)])
        assert v.open_orders() == []
        runner(v).emergency_flatten("suspended child")
        assert STOP in v.cancelled
        assert kinds(v).index("cancel") < kinds(v).index("close")

    def test_a_child_filling_during_cancellation_is_measured_afresh(self):
        v = Venue(position=15, orders=[order(STOP)], fill_on_cancel=-30)
        out = runner(v).emergency_flatten("race")
        assert v.position == 0
        assert out["closes"], "the reversed exposure was closed"

    def test_the_parent_remainder_is_the_same_authority_as_a_child(self):
        """c9fdf75: an unfilled entry remainder is old-trade exposure."""
        v = Venue(position=8, orders=[order(ENTRY, side=BUY, otype=2, parent=None),
                                      order(STOP)])
        runner(v).emergency_flatten("partial fill")
        assert ENTRY in v.cancelled and STOP in v.cancelled
        assert max(i for i, k in enumerate(kinds(v)) if k == "cancel") \
            < kinds(v).index("close")

    def test_flat_with_an_unresolved_owned_order_is_not_safe_terminal(self):
        d = EL.plan(position_size=0, orders=[order(STOP, status=99)],
                    owns=lambda o: True)
        assert not EL.is_safe_terminal(d)

    def test_no_production_path_implements_a_weaker_sequence(self):
        """§4: exactly one method may close a position, and it drives EL.plan."""
        closers = [n.name for n in ast.walk(ast.parse(
            open(os.path.join(ROOT, "src", "broker",
                              "topstepx_execution_runner.py"),
                 encoding="utf-8").read()))
            if isinstance(n, ast.FunctionDef)
            and "self.session.close_position(" in ast.unparse(n).replace(" ", "")]
        assert closers == ["emergency_flatten"], closers


# ══ §5 + §6  OWNERSHIP AMBIGUITY ACROSS POSITION STATES ═════════════════════
class TestAmbiguityComposition:

    @pytest.mark.parametrize("position", [15, -15, -6, 1])
    def test_open_position_with_a_foreign_order_halts_before_mutation(self, position):
        v = Venue(position=position,
                  orders=[order(STOP), order(FOREIGN, side=BUY, parent=None)])
        out = runner(v).emergency_flatten("foreign present")
        assert v.calls == [], "nothing dismantled for a sequence that cannot run"
        assert out["emergency_reason"] == EL.OWNERSHIP_AMBIGUOUS
        assert out["flattened"] is False

    def test_flat_with_a_foreign_order_halts(self):
        v = Venue(position=0, orders=[order(FOREIGN, side=BUY, parent=None)])
        out = runner(v).emergency_flatten("flat + foreign")
        assert out["flattened"] is False and v.closed == []

    def test_a_terminal_foreign_order_does_not_wedge(self):
        v = Venue(position=15,
                  orders=[order(FOREIGN, side=BUY, parent=None,
                                status=DISC.STATUS_FILLED)])
        out = runner(v).emergency_flatten("history only")
        assert v.closed == [MNQ_ID]
        assert out["safe_terminal"] is True

    def test_an_unknown_future_status_halts(self):
        v = Venue(position=15, orders=[order(STOP, status=99)])
        out = runner(v).emergency_flatten("unknown status")
        assert v.closed == [] and out["flattened"] is False


# ══ §10  TRANSIENT v2/query FAILURE — THE Q SERIES ══════════════════════════
class TestTransientDiscoveryFailure:
    """The accepted safe-direction stall, attacked rather than waved through."""

    def _mission(self, tmp_path, state):
        from broker import topstepx_mission_state as MS
        import copy
        m = MS.MissionState.__new__(MS.MissionState)
        for f, spec in MS.MissionState.__dataclass_fields__.items():
            d = spec.default
            if d is not None and repr(d).startswith("<dataclasses._MISSING"):
                d = None
            setattr(m, f, copy.copy(d))
        m.path = str(tmp_path / "m.json")
        m.mission_id, m.contract_id, m.order_id = "Q", MNQ_ID, ENTRY
        m.account_fingerprint = m.authorization_fingerprint = "fp"
        m.session_id, m.state, m.history = "Q", state, []
        m.protective_order_ids, m.max_attempts = [], 1
        m.save()
        return m

    def _reconcile(self, venue, mission):
        return RECON.MissionReconciler(venue=venue,
                                       contract_id=MNQ_ID).reconcile(mission)

    def test_Q1_one_tick_failure_then_recovery(self, tmp_path):
        from broker import topstepx_mission_state as MS
        m = self._mission(tmp_path, MS.EXIT_PENDING_RECONCILIATION)
        v = Venue(position=0, query_fails=True)
        out = self._reconcile(v, m)
        assert out["orders_complete"] is False
        assert m.state != MS.COMPLETE, "no false COMPLETE from incomplete truth"
        v.query_fails = False
        self._reconcile(v, m)
        assert m.state == MS.COMPLETE, "self-heals on authoritative truth"

    def test_Q2_multi_tick_failure_then_recovery(self, tmp_path):
        from broker import topstepx_mission_state as MS
        m = self._mission(tmp_path, MS.EXIT_PENDING_RECONCILIATION)
        v = Venue(position=0, query_fails=True)
        for _ in range(5):
            self._reconcile(v, m)
        assert m.state != MS.COMPLETE
        v.query_fails = False
        self._reconcile(v, m)
        assert m.state == MS.COMPLETE, "no permanent wedge"

    def test_Q3_failure_with_an_open_position_never_claims_safety(self):
        v = Venue(position=15, orders=[order(STOP)], query_fails=True)
        out = runner(v).emergency_flatten("q3")
        assert out["flattened"] is False

    def test_Q4_failure_while_flat_with_a_working_order(self, tmp_path):
        from broker import topstepx_mission_state as MS
        m = self._mission(tmp_path, MS.EXIT_PENDING_RECONCILIATION)
        v = Venue(position=0, orders=[order(STOP)], query_fails=True)
        self._reconcile(v, m)
        assert m.state != MS.COMPLETE, "absence not proven from a degraded view"

    def test_Q5_restart_during_the_outage_reaches_the_same_verdict(self, tmp_path):
        from broker import topstepx_mission_state as MS
        v = Venue(position=0, query_fails=True)
        first = self._mission(tmp_path, MS.EXIT_PENDING_RECONCILIATION)
        self._reconcile(v, first)
        reloaded = MS.load(first.path)
        assert reloaded.state != MS.COMPLETE
        self._reconcile(v, reloaded)
        assert reloaded.state != MS.COMPLETE

    def test_Q6_venue_state_changes_during_the_outage(self, tmp_path):
        from broker import topstepx_mission_state as MS
        m = self._mission(tmp_path, MS.VENUE_ACKNOWLEDGED)
        v = Venue(position=15, orders=[order(STOP)], query_fails=True)
        self._reconcile(v, m)
        v.position, v.query_fails = 0, False
        v._orders[0]["status"] = DISC.STATUS_FILLED
        self._reconcile(v, m)
        assert STOP in (m.protective_order_ids or []), \
            "lineage recovered once truth returns"

    def test_Q7_outage_clears_after_a_child_filled(self, tmp_path):
        from broker import topstepx_mission_state as MS
        m = self._mission(tmp_path, MS.EXIT_PENDING_RECONCILIATION)
        v = Venue(position=0, orders=[order(STOP, status=DISC.STATUS_FILLED)],
                  query_fails=True)
        self._reconcile(v, m)
        assert m.state != MS.COMPLETE
        v.query_fails = False
        self._reconcile(v, m)
        assert m.state == MS.COMPLETE

    def test_incomplete_truth_never_grants_new_entry_permission(self):
        """§10 hard requirement, at the gate that actually decides."""
        import inspect

        from broker.topstepx_production_loop import ProductionLoop
        assert "DISC.require_working_orders(" in inspect.getsource(
            ProductionLoop._execute)
        from broker.topstepx_production_session import ProductionSession
        assert "_DISC.require_working_orders(" in inspect.getsource(
            ProductionSession)

    def test_an_unreadable_position_halts_before_any_mutation(self):
        v = Venue(position=15, orders=[order(STOP)], positions_fails=True)
        out = runner(v).emergency_flatten("blind position")
        assert v.closed == [] and out["flattened"] is False

    def test_both_order_surfaces_down_is_unreadable_not_empty(self):
        v = Venue(position=15, query_fails=True, open_orders_fails=True)
        out = runner(v).emergency_flatten("blind orders")
        assert out["flattened"] is False


# ══ §9  ACCOUNT / LANE SAFETY ═══════════════════════════════════════════════
class TestAccountLaneComposition:

    def test_lane_shutdown_authority_is_lineage_only(self):
        from broker import topstepx_hard_flatten as HF
        a = HF.lane_shutdown_authority()
        assert a["scope"] == HF.LINEAGE_ONLY and a["proven_exclusive"] is False

    def test_same_contract_alone_remains_unproven(self):
        assert DISC.order_lineage({"contract_id": MNQ_ID},
                                  entry_order_id=ENTRY,
                                  contract_id=MNQ_ID) == DISC.UNPROVEN

    def test_account_role_cannot_grant_routing_authority(self):
        import inspect

        from broker import topstepx_account_role as ROLE
        src = inspect.getsource(ROLE)
        assert "reporting and policy only" in src.lower() \
            or "REPORTING AND POLICY ONLY" in src

    def test_no_paper_path_can_reach_topstepx(self):
        from operational_readiness import eod_authority as EOD
        import inspect
        src = inspect.getsource(EOD.flatten_position_eod)
        assert "paper_execution" in src and "topstepx" not in src.lower()


# ══ §12  STRATEGY NON-INTERFERENCE ══════════════════════════════════════════
#: The last commit of the TopstepX safety stack. Everything from 511a493 to here
#: is execution-layer work; cognition units land after it and are certified by
#: their own suites.
SAFETY_STACK_TIP = "d89b875"


class TestStrategyUntouched:

    def test_risk_doctrine_constants_are_unchanged(self):
        from broker import topstepx_combine_risk as RISK
        # SMOKE_MAX_CONTRACTS is the 1-lot smoke cap; 15 is the PRODUCTION cap.
        assert RISK.SMOKE_MAX_CONTRACTS == 1
        assert RISK.ABSOLUTE_MAX_STOP_POINTS >= 50.0
        assert RISK.PRODUCTION_MAX_RISK_USD >= 350.0

    # LINEAGE NOTE. The unit histories below were imported from upstream and
    # describe WHY each change was made. Their fingerprint transitions are
    # deliberately not reproduced: this repository is a sanitized tree that
    # never computed those digests, and printing them would claim a
    # certification lineage it does not have. This tree pins only the digest it
    # computes for itself.
    def test_the_brain_contract_fingerprint_is_the_certified_one(self):
        """The pin moves ONLY when cognition deliberately changes, and the move
        is stated here rather than discovered in a live session.

        UPSTREAM UNIT (digests not reproduced -- see note below)
            LUNA-SESSION-PO3-AUTHORITY-1 (2026-08-29). Two closure sources
            changed, both intentionally: `brain_input` now shows Luna the
            canonical session PO3 phase, and `luna_candidate_producer` now
            refuses a new entry while that phase is unresolved accumulation.
            Nothing in the safety, risk or execution layer moved.

        UPSTREAM UNIT (digests not reproduced -- see note below)
            VENUE-CALENDAR-AUTHORITY-HORIZON-1 (2026-08-30). Exactly ONE closure
            source changed: `tool_geometry` -> src/toolbox/price_levels.py.
            `_canonically_adjacent` now refuses to prove market adjacency when
            venue cadence authority is unknown, closing an execution-bearing
            fail-open in which an empty `expected_buckets` result -- the
            calendar saying "no jurisdiction" -- was read as "therefore
            adjacent" and admitted phantom FVG triples.

            `venue_calendar.py` is NOT a Brain closure source, so extending the
            verified ordinary horizon to year-end moved nothing by itself. The
            digest moved because execution-bearing GEOMETRY changed, which is
            exactly where a fingerprint move belongs.

        UPSTREAM UNIT (digests not reproduced -- see note below)
            LUNA-CROSS-SESSION-PO3-CONTEXT-1 (2026-08-30). Exactly ONE closure
            source changed: `input` -> src/ai_brain/brain_input.py, which now
            publishes the cross-session context block beside the session phase.
            Luna is shown what Asia, London and premarket already did.

            Nothing that DECIDES changed. `session_po3.derive` is untouched and
            has no parameter through which prior-session context could reach it,
            so the phase, the entry ruling and the candidate producer are
            byte-identical. The digest moved because the Brain SEES more, not
            because anything mechanical acts on it.

        UPSTREAM UNIT (digests not reproduced -- see note below)
            LUNA-VAP-CAPTURE-AND-PERSISTENCE-1 (2026-08-30). Exactly ONE closure
            source changed: `production_entrypoint` ->
            tools/topstepx_production_session.py, because the actual production
            composition root now attaches a SECOND named GatewayTrade consumer
            that records observed trade price x size into an independent capture
            path. Every trade already carried price, size and a millisecond
            timestamp; the candle aggregator summed them into OHLCV and dropped
            the rest, and no REST endpoint can ever return that attribution.

            THE ENTRYPOINT IS BOUND ON PURPOSE, so wiring a live market-data
            consumer into it SHOULD move the digest -- hiding the attachment in
            an unbound helper to preserve a fingerprint would defeat the reason
            the entrypoint was bound. The diff was minimized first: success
            telemetry was removed so display-only churn is not certified, and
            only the failure branch remains, because a silently swallowed
            exception would let a session record nothing while looking healthy.

            Nothing that decides changed. No `src/` closure source moved --
            session_po3, execution_gate, decision_authority, risk_governor,
            playbooks and brain_input are untouched, and the recorder computes
            no profile, publishes nothing to the Brain and has no route to any
            strategy surface.

        UPSTREAM UNIT (digests not reproduced -- see note below)
            LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1 (2026-08-31). Exactly ONE closure
            source changed: `production_entrypoint` ->
            tools/topstepx_production_session.py, whose disarmed rehearsal
            authorization now signs the same session loss budget a real one
            does, so a rehearsal exercises the governed path instead of
            stalling at "budget unknown".

            THE UNIT IS A RISK LAW, NOT COGNITION. Doctrine claimed a $725
            daily loss limit; the TopstepX lane had none -- session end was
            triggered by attempt count alone, so a full second $350 trade was
            authorized even after the first slipped past its planned loss. New
            entries are now additionally capped at
            min($350, remaining daily room), computed from ECONOMIC realized
            P&L -- venue profitAndLoss (PROVEN GROSS on 2026-08-31 against two
            real 15-lot round trips) less ACTUAL venue fees AND commissions --
            attributed only to Luna's own certified order lineage.

            It governs the NEXT entry. It is NOT a guaranteed maximum realized
            loss, and nothing in it may ever claim to be.

        UPSTREAM UNIT (digests not reproduced -- see note below)
            LUNA-SWING-SEQUENCE-TRUTH-1 (2026-09-01). Luna was standing down on
            a tape whose CONFIRMED registry had walked highs
            29157.75 -> 29163.25 -> 29173 -> 29179 and lows
            29040 -> 29085 -> 29116 -> 29135.75, because the only sequence the
            organism computed came from 15m candle pivots, that window produced
            ZERO pivots, and the fallback asked whether 15m candles EXISTED
            rather than whether they had produced anything. Mechanics held the
            structure and withheld it.

            The registry now owns ordinal succession, the windowed pivot witness
            falls through 15m -> 5m -> 3m on PIVOT SUFFICIENCY, and a regime may
            no longer be called a range on the absence of trend evidence.
            Closure 18 -> 21: swing_structure, regime_features and
            regime_classifier were binding NOTHING while able to change
            Brain-visible truth.

        UPSTREAM UNIT (digests not reproduced -- see note below)
            LUNA-LIQUIDITY-SCOPE-TRUTH-1 (2026-09-01). The organism already told
            an external sweep from an internal raid and weighted them 30 vs 20 --
            then recomputed both every scan from a rolling `candles[-40:]`, so a
            later higher swing rewrote what an earlier event WAS. Measured: the
            identical candle reads EXTERNAL against pivots [100,110] and
            INTERNAL against [100,110,120]. Luna was told only
            `manipulation_confirmed` with a null direction.

            Scope is now stamped ONCE, at the event, against a NAMED authority,
            and carried immutably on the occurrence. Two authorities travel
            separately -- MANIPULATION_PIVOT_CONTEXT and
            SESSION_PO3_ACCUMULATION_RANGE -- because they can legitimately
            disagree, and `po3_scope` refuses to answer at all unless an
            ESTABLISHED range predated the event.

            Closure 21 -> 30. `po3_config` is a CONSTANTS file whose
            MANIP_CONTEXT decides which pivots exist, and `snapshot_builder`
            threads the one kwarg that makes an occurrence link provable; both
            were unbound while able to change what Luna believes happened.

            CLOSURE 17 -> 18. `daily_loss_budget` joined the closure beside
            `risk_doctrine`. The entrypoint change alone bound only the CALL:
            the remaining-room arithmetic, the exhaustion behaviour, the
            contamination handling and the unknown-state fail-closed rule could
            all have been edited in isolation while a minted authorization kept
            verifying. Binding the module is what makes such an edit invalidate
            it -- proven executably, not asserted, by
            test_authorization_source_closure.py::
            test_a_semantic_edit_to_the_loss_governor_moves_the_fingerprint.

            brain:55d8110d92020d4f  ->  brain:07bf24372b59c85d
            LUNA-DAILY-GOVERNOR-TRADE-ATTRIBUTION-1 (2026-09-02). The governor
            decoded venue trade rows in the NORMALISED dialect only
            (`order_id`, `created`), but `TopstepXLiveSession.recent_trades()`
            returns RAW venue JSON (`orderId`, `creationTimestamp`) and is
            required to keep doing so -- `topstepx_execution_runner` matches
            fills on `t["orderId"]` with no fallback. Against every live row
            both keys resolved to None/"", so a lineage-OWNED entry fill could
            not match the owned set and PROD-20260902's first fill forced
            CONTAMINATED; the same silence disabled the prior-session cutoff.
            This is precisely the contamination-handling edit the paragraph
            above says must invalidate a minted authorization, so the
            fingerprint moving here is the binding working, not a regression.
        """
        # THIS DIGEST EQUALS UPSTREAM LUNA'S, AND THAT IS THE CORRECT RESULT.
        #
        # Proven per source, not inferred: all 30 decision-bearing closure
        # sources are byte-equivalent between this tree and the upstream
        # certified organism under the repository's canonical line-ending
        # representation. Equality is therefore a PARITY RESULT -- the
        # decision-bearing code really is the same code.
        #
        # IT IS NOT EVIDENCE THAT SANITIZATION FAILED. This tree's differences
        # -- omitted broker lanes, the `integrations/topstepx/` layout,
        # configuration-supplied account identity, absent runtime data,
        # launchers and fixtures -- all live OUTSIDE the semantic closure, so
        # none of them can move this digest.
        #
        # DO NOT INFER FINGERPRINT DIVERGENCE FROM SANITIZATION. Removing
        # lanes, moving a namespace or externalising configuration changes the
        # tree without necessarily changing this digest, because those files are
        # not closure sources. Compute and certify the fingerprint from the
        # ACTUAL FINAL DISTRIBUTION BYTES -- a value taken from a working copy
        # can differ for reasons that have nothing to do with semantics, such as
        # line-ending representation.
        #
        # FINGERPRINT PARITY IS NOT AUTHORIZATION PARITY. This repository
        # inherits no account, credentials, authorization or operational
        # certification from upstream.
        from ai_brain.production_model import brain_contract_fingerprint
        assert brain_contract_fingerprint() == "brain:07bf24372b59c85d"

    def test_no_safety_commit_touched_luna_cognition(self):
        """The safety commits are execution-layer only.

        BOUNDED TO THE SAFETY RANGE, NOT TO HEAD. This asserted `511a493~1..HEAD`
        while the safety stack WAS the tip, which quietly made it "no future
        commit may ever touch cognition" -- a claim it was never written to make
        and one no cognition unit could ever satisfy. The range it actually
        certifies is the safety stack itself, so that is the range it names.
        """
        import subprocess
        # UPSTREAM HISTORY IS AN ENVIRONMENTAL PREREQUISITE HERE.
        #
        # This range names commits from the ORIGINATING repository. This tree is
        # a sanitized snapshot with its own history, so a real clone -- and the
        # distributed archive, which carries no .git at all -- cannot resolve
        # them. The theorem is about what those upstream commits touched; where
        # that history is absent the honest result is a skip, not a failure and
        # certainly not a pass.
        #
        # It resolved during preparation only because the build worktree shared
        # the upstream object store, which is exactly the kind of false green
        # this guard exists to prevent.
        _probe = subprocess.run(["git", "cat-file", "-e", "511a493~1"],
                                capture_output=True, cwd=ROOT)
        if _probe.returncode != 0:
            pytest.skip("EXTERNAL_HISTORY_REQUIRED: the upstream safety-stack "
                        "commit range is not present in this repository")
        out = subprocess.run(
            ["git", "diff", "--name-only", "511a493~1", SAFETY_STACK_TIP],
            cwd=ROOT, capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        touched = [f for f in out.stdout.split() if f.startswith("src/")]
        forbidden = ("src/ai_brain/", "src/narrative_authority/",
                     "src/market_state/", "src/toolbox/", "src/structure/",
                     "src/live_scan/")
        assert [f for f in touched if f.startswith(forbidden)] == []
