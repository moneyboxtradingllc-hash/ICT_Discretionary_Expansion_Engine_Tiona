"""TOPSTEP-PROTECTIVE-DISCOVERY-AND-LINEAGE-1.

`TOPSTEP-EMERGENCY-FLATTEN-ATOMICITY-1` made liquidation safe when its caller is
wrong. These prove the callers stop being wrong.

THE DEFECT UNDER TEST. `/api/Order/searchOpen` omits Suspended bracket children
by official Gateway contract, and every discovery path in this stack read it as
though it were the complete set of orders relevant to an open trade. Two
propositions were being substituted for one another:

    "this order is not in searchOpen"
    "this order does not exist"

The measured consequence sits in `topstepx_production_loop.manage_open_position`,
which flattens a live position when it cannot see an owned stop. A Suspended
stop therefore reads as NO PROTECTION, and the answer to an imagined danger is
to destroy a protected trade.
"""
import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import break_even_actuator as ACT              # noqa: E402
from broker import topstepx_emergency_liquidation as EL    # noqa: E402
from broker import topstepx_hard_flatten as HF             # noqa: E402
from broker import topstepx_mission_reconciler as RECON    # noqa: E402
from broker import topstepx_mission_state as MS            # noqa: E402
from broker import topstepx_order_discovery as DISC        # noqa: E402
from broker import topstepx_session_ledger as LG           # noqa: E402

MNQ = "CON.F.US.MNQ.U26"
ENTRY_ID = 3451056002
SL_ID = 3451056003          # the real stop from the 2026-08-26 incident
TP_ID = 3451056004
TAG = "EXPBOT-PRAC-20260826-T1"
TOKEN = "PRAC-20260826-T1"


class _Ledger:
    """Only what attribution needs: the token ids THIS SESSION issued."""

    def __init__(self, tokens=(TOKEN,)):
        self.known_token_ids = set(tokens)


def ledger(tokens=(TOKEN,)):
    return _Ledger(tokens)


def order(oid, *, status=DISC.STATUS_OPEN, otype=4, side=1, parent=ENTRY_ID,
          contract=MNQ, tag=None, **extra):
    row = {"id": oid, "contract_id": contract, "type": otype, "side": side,
           "size": 15, "status": status}
    if parent is not None:
        row["parent_order_id"] = parent
    if tag is not None:
        row["custom_tag"] = tag
    row.update(extra)
    return row


class Venue:
    """A venue that serves BOTH surfaces, and can be told to differ between them.

    `hidden` are orders the venue holds but `searchOpen` refuses to publish --
    which is not a contrived scenario but the documented behaviour for Suspended
    bracket children.
    """

    def __init__(self, orders=None, hidden=None, position=0, trades=None,
                 no_query=False, query_fails=False):
        self._orders = [dict(o) for o in (orders or [])]
        self._hidden = [dict(o) for o in (hidden or [])]
        self._position = position
        self._trades = list(trades or [])
        self.query_fails = query_fails
        self.cancelled = []
        self.closed = []
        #: a venue that takes the request and never acts on it
        self.cancel_is_ignored = False
        if no_query:
            self.query_orders = None

    # ── the COMPLETE surface ────────────────────────────────────────────────
    def query_orders(self, *, statuses=None, contract_id=None):
        assert statuses is None, "discovery must not filter by status"
        if self.query_fails:
            raise RuntimeError("v2/query unavailable")
        rows = self._orders + self._hidden
        if contract_id:
            rows = [o for o in rows if o.get("contract_id") == contract_id]
        return [dict(o) for o in rows]

    # ── the INCOMPLETE surface ──────────────────────────────────────────────
    def open_orders(self):
        return [dict(o) for o in self._orders
                if DISC.status_of(o) in DISC.WORKING_STATUSES]

    def open_positions(self):
        if not self._position:
            return []
        return [{"contract_id": MNQ, "size": abs(self._position),
                 "type": 1 if self._position > 0 else 2,
                 "avg_price": 29257.5,
                 "side": "long" if self._position > 0 else "short"}]

    def recent_trades(self):
        return list(self._trades)

    def cancel_order(self, oid):
        """A venue that ACCEPTS a cancel moves the order to Cancelled.

        The old shape -- record the call, leave the order untouched -- modelled
        a venue that never honours anything, which is why the certified planner
        would sit proving terminality that could never arrive. Terminality is
        proven per order by the oracle, so the fixture has to be
        able to supply it.
        """
        self.cancelled.append(oid)
        for row in self._orders + self._hidden:
            if str(row.get("id")) == str(oid) and not self.cancel_is_ignored:
                row["status"] = DISC.STATUS_CANCELLED

    def close_position(self, cid):
        self.closed.append(cid)
        self._position = 0

    def order_by_id(self, oid):
        for o in self._orders + self._hidden:
            if str(o.get("id")) == str(oid):
                return dict(o)
        return None


#: Missions are built ON DISK, never as loose objects. Every ladder rung
#: re-reads the file it just wrote before it will believe its own transition,
#: so an in-memory stand-in does not exercise the code under test at all --
#: it exercises a different one.
_MISSION_SEQ = [0]


def mission(tmp_path, state=MS.POSITION_OPEN, **kw):
    _MISSION_SEQ[0] += 1
    path = str(tmp_path / f"trade_mission_{_MISSION_SEQ[0]}.json")
    m = MS.MissionState.__new__(MS.MissionState)
    for field, spec in MS.MissionState.__dataclass_fields__.items():
        default = spec.default
        if default is not None and repr(default).startswith("<dataclasses._MISSING"):
            default = None
        setattr(m, field, copy.copy(default))
    m.path = path
    m.mission_id, m.contract_id, m.order_id = "PRAC-T1", MNQ, ENTRY_ID
    m.account_fingerprint = m.authorization_fingerprint = "fp"
    m.session_id = "PRAC-20260826"
    m.state, m.protective_order_ids = state, []
    m.history = []
    m.max_attempts = 1
    for k, v in kw.items():
        setattr(m, k, v)
    m.save()
    return m


# ══ P1-P4  DISCOVERY SEES WHAT searchOpen HIDES ═════════════════════════════
class TestDiscoverySurface:

    def test_P1_a_suspended_owned_stop_omitted_by_searchopen_is_discovered(self):
        """THE SPECIMEN. The venue holds the stop; `searchOpen` will not say so."""
        v = Venue(hidden=[order(SL_ID, status=DISC.STATUS_SUSPENDED)])
        assert v.open_orders() == [], "the fixture must model the omission"
        found = DISC.discover_orders(v, contract_id=MNQ)
        assert found["complete"] is True
        assert [o["id"] for o in found["working"]] == [SL_ID]

    def test_P2_pending_cancellation_is_still_known_not_treated_cancelled(self):
        """`PendingCancellation` is a REQUEST, not an outcome. An order in it can
        still fill, so treating it as cancelled is how a 'clean' account fires."""
        v = Venue(orders=[order(SL_ID, status=DISC.STATUS_PENDING_CANCELLATION)])
        found = DISC.discover_orders(v, contract_id=MNQ)
        assert [o["id"] for o in found["working"]] == [SL_ID]
        assert DISC.is_terminal(found["working"][0]) is False

    def test_P3_a_pending_child_is_retained(self):
        v = Venue(orders=[order(TP_ID, status=DISC.STATUS_PENDING, otype=1)])
        assert DISC.discover_orders(v, contract_id=MNQ)["working"]

    def test_P4_an_unknown_future_status_survives_and_classifies_unknown(self):
        """No status filter is applied, so a value our enum has not heard of
        reaches classification instead of being stripped by the query."""
        v = Venue(orders=[order(SL_ID, status=99)])
        found = DISC.discover_orders(v, contract_id=MNQ)
        assert found["working"] and found["working"][0]["status"] == 99
        assert DISC.is_working(found["working"][0]) is True
        assert EL.classify_order(found["working"][0], position_size=-15) \
            == EL.UNKNOWN_AUTHORITY

    def test_status_zero_is_none_and_never_reads_as_open(self):
        assert DISC.status_of({"status": 0}) is None
        assert DISC.status_of({}) is None
        assert DISC.is_terminal({"status": 0}) is False

    def test_the_fallback_is_labelled_and_never_claims_completeness(self):
        v = Venue(orders=[order(SL_ID)], no_query=True)
        found = DISC.discover_orders(v, contract_id=MNQ)
        assert found["answered"] is True and found["complete"] is False
        assert found["source"] == DISC.INCOMPLETE

    def test_an_unreadable_venue_is_not_an_empty_account(self):
        v = Venue(orders=[order(SL_ID)], query_fails=True, no_query=False)
        v.open_orders = lambda: (_ for _ in ()).throw(RuntimeError("down"))
        found = DISC.discover_orders(v, contract_id=MNQ)
        assert found["answered"] is False and found["orders"] is None
        assert found["errors"]

    def test_terminal_rows_are_excluded_from_working(self):
        """v2/query is a history surface too. A consumer counting working orders
        must not start counting this morning's fills."""
        v = Venue(orders=[order(SL_ID, status=DISC.STATUS_FILLED),
                          order(TP_ID, status=DISC.STATUS_CANCELLED, otype=1)])
        found = DISC.discover_orders(v, contract_id=MNQ)
        assert len(found["orders"]) == 2 and found["working"] == []


# ══ P5  OWNERSHIP ═══════════════════════════════════════════════════════════
class TestOwnershipContract:

    def test_P5_a_same_contract_manual_order_is_never_claimed(self):
        """Instrument is not lineage. An operator trading MNQ beside us produces
        orders indistinguishable by side and size."""
        manual = {"id": 555000, "contract_id": MNQ, "type": 4, "side": 1,
                  "status": 1}
        assert DISC.order_lineage(manual, entry_order_id=ENTRY_ID,
                                  contract_id=MNQ) == DISC.UNPROVEN
        assert DISC.owns(manual, entry_order_id=ENTRY_ID, contract_id=MNQ) is False

    @pytest.mark.parametrize("row,verdict", [
        ({"contract_id": MNQ, "parent_order_id": ENTRY_ID}, DISC.OWNED),
        ({"contract_id": MNQ, "parentOrderId": ENTRY_ID}, DISC.OWNED),
        ({"contract_id": MNQ, "linkedOrderId": ENTRY_ID}, DISC.OWNED),
        ({"contract_id": MNQ, "custom_tag": TAG}, DISC.OWNED),
        ({"contract_id": MNQ, "custom_tag": TAG + "-SL"}, DISC.OWNED),
        ({"contract_id": MNQ, "custom_tag": TAG + "X"}, DISC.UNPROVEN),
        ({"contract_id": MNQ}, DISC.UNPROVEN),
        ({"contract_id": "CON.F.US.ES.U26", "parent_order_id": ENTRY_ID},
         DISC.FOREIGN),
    ])
    def test_lineage_verdicts(self, row, verdict):
        assert DISC.order_lineage(row, entry_order_id=ENTRY_ID, contract_id=MNQ,
                                  custom_tag=TAG) == verdict

    def test_there_is_exactly_one_ownership_implementation(self):
        """The reconciler accepted only `parent_order_id` while the runner also
        accepted `linkedOrderId` and the tag, so one order could be OURS to the
        execution layer and a stranger to the record that outlives the process.
        """
        import inspect
        assert "DISC.lineage_orders" in inspect.getsource(RECON.lineage_orders)
        from broker.topstepx_execution_runner import ExecutionRunner
        assert "DISC.owns" in inspect.getsource(ExecutionRunner.mission_owns_order)

    def test_the_reconciler_now_accepts_the_linked_and_tag_evidence(self):
        rows = [{"id": 1, "contract_id": MNQ, "linkedOrderId": ENTRY_ID},
                {"id": 2, "contract_id": MNQ, "custom_tag": TAG + "-TP"}]
        got = RECON.lineage_orders(rows, contract_id=MNQ, entry_order_id=ENTRY_ID,
                                   custom_tag=TAG)
        assert [o["id"] for o in got] == [1, 2]


# ══ P6-P12  DURABLE LINEAGE ═════════════════════════════════════════════════
class TestDurableLineage:

    def _reconcile(self, venue, m, **kw):
        return RECON.MissionReconciler(venue=venue, contract_id=MNQ).reconcile(
            m, **kw)

    def test_P6_empty_protective_ids_are_recovered_from_venue_lineage(self, tmp_path):
        v = Venue(orders=[order(SL_ID), order(TP_ID, otype=1)], position=15)
        m = mission(tmp_path, state=MS.VENUE_ACKNOWLEDGED)
        self._reconcile(v, m)
        assert sorted(m.protective_order_ids) == [SL_ID, TP_ID]

    def test_P7_an_identity_survives_the_child_leaving_active_discovery(self, tmp_path):
        """Leaving active discovery is a change of STATE, not a retraction of
        EXISTENCE."""
        m = mission(tmp_path, protective_order_ids=[SL_ID, TP_ID])
        m.observe_protection(protective_order_ids=[])
        assert m.protective_order_ids == [SL_ID, TP_ID]
        m.observe_protection(protective_order_ids=[SL_ID])
        assert m.protective_order_ids == [SL_ID, TP_ID], "union, never replacement"

    def test_P8_a_filled_stop_and_its_cancelled_sibling_stay_attributable(self, tmp_path):
        v = Venue(orders=[order(SL_ID, status=DISC.STATUS_FILLED),
                          order(TP_ID, status=DISC.STATUS_CANCELLED, otype=1)],
                  position=0,
                  trades=[{"orderId": ENTRY_ID, "price": 29257.5, "size": 15,
                           "contractId": MNQ},
                          {"orderId": SL_ID, "price": 29243.0, "size": 15,
                           "contractId": MNQ}])
        m = mission(tmp_path, state=MS.VENUE_ACKNOWLEDGED)
        self._reconcile(v, m)
        assert sorted(m.protective_order_ids) == [SL_ID, TP_ID]
        assert m.exit_type == RECON.EXIT_STOP
        assert m.exit_order_id == SL_ID and m.exit_price == 29243.0

    def test_the_2026_08_26_regression_late_fill_rung_carries_lineage(self, tmp_path):
        """THE PROVEN ROOT CAUSE, bound as a test.

        PRAC-20260826-T1 opened and closed inside one 60-second scan tick, so
        the only reconciliation it ever received took the branch evidenced as
        "venue trade history (fill seen only after close)". That branch called
        `observe_position_open` WITHOUT `protective_order_ids` at all -- a rung
        that cannot carry lineage guarantees the lineage is lost. The durable
        record shows the result: `protective_order_ids: []`, exit `unattributed`.
        """
        v = Venue(orders=[order(SL_ID, status=DISC.STATUS_FILLED)], position=0,
                  trades=[{"orderId": ENTRY_ID, "price": 29257.5, "size": 15,
                           "contractId": MNQ}])
        m = mission(tmp_path, state=MS.VENUE_ACKNOWLEDGED)
        self._reconcile(v, m)
        assert MS.POSITION_OPEN in [h["to"] for h in m.history]
        assert m.protective_order_ids == [SL_ID], \
            "the late-fill rung must carry the lineage it can see"

    def test_P11_restart_rediscovers_a_suspended_child(self, tmp_path):
        """PROCESS UPTIME DOES NOT DEFINE PROTECTIVE MEMORY. A fresh process
        with an empty record rebuilds lineage from venue truth."""
        v = Venue(hidden=[order(SL_ID, status=DISC.STATUS_SUSPENDED)],
                  position=15)
        m = mission(tmp_path, state=MS.VENUE_ACKNOWLEDGED)
        self._reconcile(v, m)
        assert m.protective_order_ids == [SL_ID]

    def test_P12_restart_after_a_terminal_child_recovers_the_identity(self, tmp_path):
        v = Venue(orders=[order(SL_ID, status=DISC.STATUS_FILLED)], position=15)
        m = mission(tmp_path, state=MS.VENUE_ACKNOWLEDGED)
        self._reconcile(v, m)
        assert m.protective_order_ids == [SL_ID], \
            "venue history supports the identity even though it cannot protect"

    def test_P20_a_reloaded_mission_keeps_its_protective_identities(self, tmp_path):
        m = mission(tmp_path)
        m.observe_protection(protective_order_ids=[SL_ID, TP_ID])
        back = MS.load(m.path)
        assert sorted(back.protective_order_ids) == [SL_ID, TP_ID]

    def test_an_incomplete_view_may_not_complete_a_mission(self, tmp_path):
        """"No working lineage order" read off `searchOpen` is compatible with a
        Suspended child still resting at the venue."""
        v = Venue(orders=[], position=0, no_query=True)
        m = mission(tmp_path, state=MS.EXIT_PENDING_RECONCILIATION)
        out = self._reconcile(v, m)
        assert m.state != MS.COMPLETE
        assert out["orders_complete"] is False

    def test_a_complete_view_still_completes_the_mission(self, tmp_path):
        v = Venue(orders=[], position=0)
        m = mission(tmp_path, state=MS.EXIT_PENDING_RECONCILIATION)
        self._reconcile(v, m)
        assert m.state == MS.COMPLETE


# ══ P9-P10  REPLACEMENT / MODIFY LIFECYCLE ══════════════════════════════════
class TestReplacementLifecycle:

    def test_P9_a_break_even_modify_that_keeps_its_id_keeps_its_lineage(self, tmp_path):
        v = Venue(orders=[order(SL_ID, stop_price=29243.0)], position=15)
        m = mission(tmp_path, state=MS.VENUE_ACKNOWLEDGED)
        r = RECON.MissionReconciler(venue=v, contract_id=MNQ)
        r.reconcile(m)
        v._orders[0]["stop_price"] = 29257.5          # advanced to break-even
        r.reconcile(m)
        assert m.protective_order_ids == [SL_ID], "one identity, one entry"

    def test_P10_a_replacement_child_preserves_the_ancestry(self, tmp_path):
        """Cancel-and-replace mints a NEW order id. Overwriting would erase the
        only identity capable of explaining what the old one did."""
        v = Venue(orders=[order(SL_ID)], position=15)
        r = RECON.MissionReconciler(venue=v, contract_id=MNQ)
        m = mission(tmp_path, state=MS.VENUE_ACKNOWLEDGED)
        r.reconcile(m)
        v._orders[0]["status"] = DISC.STATUS_CANCELLED
        v._orders.append(order(SL_ID + 100))
        r.reconcile(m)
        assert sorted(m.protective_order_ids) == [SL_ID, SL_ID + 100]
        assert sorted(m.stop_order_ids) == [SL_ID, SL_ID + 100]


# ══ P13-P15  THE BREAK-EVEN FALSE-NO-STOP PATH ══════════════════════════════
class TestBreakEvenProtectionPresence:

    def test_P13_searchopen_empty_while_protection_exists_is_UNKNOWN(self):
        """THE $307.50 PATH, CLOSED. Under the old contract this probe returned
        `stop=None` with no way to say why, and the production owner answered
        that by flattening a live, protected position."""
        v = Venue(hidden=[order(SL_ID, status=DISC.STATUS_SUSPENDED)],
                  position=15, no_query=True)
        probe = ACT.inspect_protection(session=v, contract_id=MNQ,
                                       entry_order_id=ENTRY_ID)
        assert probe["known"] is True
        assert probe["complete"] is False
        assert probe["presence"] == DISC.UNKNOWN
        assert probe["stop"] is None

    def test_P14_a_complete_view_of_a_real_stop_reports_PRESENT(self):
        v = Venue(hidden=[order(SL_ID, status=DISC.STATUS_SUSPENDED)],
                  position=15)
        probe = ACT.inspect_protection(session=v, contract_id=MNQ,
                                       entry_order_id=ENTRY_ID)
        assert probe["presence"] == DISC.PRESENT
        assert probe["stop"]["id"] == SL_ID

    def test_a_complete_view_with_no_stop_still_reports_ABSENT(self):
        """The safety response is NOT weakened -- a genuinely unprotected
        position must still reach the certified authority."""
        v = Venue(orders=[], position=15)
        probe = ACT.inspect_protection(session=v, contract_id=MNQ,
                                       entry_order_id=ENTRY_ID)
        assert probe["presence"] == DISC.ABSENT

    def test_P15_incomplete_discovery_refuses_to_mutate(self):
        """No blind modify, no fabricated absence. Refusing costs one management
        tick; guessing either way costs the trade."""
        v = Venue(hidden=[order(SL_ID, status=DISC.STATUS_SUSPENDED)],
                  position=15, no_query=True)
        out = ACT.apply_break_even(
            session=v, contract_id=MNQ, entry_order_id=ENTRY_ID,
            direction="long", proposed_stop=29257.5)
        assert out["outcome"] == ACT.PROTECTION_UNKNOWN
        assert out["reason"] == ACT.DISCOVERY_INCOMPLETE
        assert v.cancelled == [] and v.closed == []

    def test_the_production_owner_holds_instead_of_flattening(self):
        """The routing, at the one call site that can destroy a position."""
        import inspect

        from broker.topstepx_production_loop import ProductionLoop
        src = inspect.getsource(ProductionLoop.manage_open_position)
        assert "DISC.UNKNOWN" in src
        hold = src.index("protection_unknown_discovery_incomplete")
        flat = src.index("emergency_flatten")
        assert hold < flat, "the UNKNOWN branch must return before the flatten"

    def test_an_unreadable_venue_is_still_silence_not_a_defect(self):
        v = Venue(position=15, query_fails=True, no_query=False)
        v.open_orders = lambda: (_ for _ in ()).throw(RuntimeError("down"))
        probe = ACT.inspect_protection(session=v, contract_id=MNQ,
                                       entry_order_id=ENTRY_ID)
        assert probe["known"] is False and probe["presence"] == DISC.UNKNOWN


# ══ P16-P18  PROTECTIVE VALIDITY IS NOT VISIBILITY ══════════════════════════
class TestProtectiveValidity:

    @staticmethod
    def _runner(session, size=15, direction="bullish"):
        from broker.topstepx_execution_runner import ExecutionRunner

        class C:
            id = MNQ
            tick_size = 0.25
        r = ExecutionRunner.__new__(ExecutionRunner)
        r.contract, r.session, r.order_id = C(), session, ENTRY_ID
        r.submission_custom_tag, r.token = TAG, None
        r.geometry = None
        return r

    def test_P16_a_terminal_child_is_not_protection(self):
        """DISCOVERED + OWNED is still not PROTECTING. A filled stop and its
        replacement would otherwise present as two owned stops and read as
        ambiguous ownership."""
        rows = [order(SL_ID, status=DISC.STATUS_FILLED), order(SL_ID + 1)]
        got = self._runner(Venue()).protective_children(rows)
        assert got["stop"]["id"] == SL_ID + 1
        assert got["ambiguous"] is True, "no target is still ambiguous"

    def test_P17_a_suspended_child_IS_available_to_protection_reasoning(self):
        rows = [order(SL_ID, status=DISC.STATUS_SUSPENDED),
                order(TP_ID, status=DISC.STATUS_SUSPENDED, otype=1)]
        got = self._runner(Venue()).protective_children(rows)
        assert got["ambiguous"] is False
        assert got["stop"]["id"] == SL_ID and got["target"]["id"] == TP_ID

    def test_P18_a_terminal_child_with_fill_volume_is_position_relevant(self):
        """A finished order can have changed the account on its way out, which
        is why terminality is never read as 'nothing happened'."""
        row = order(SL_ID, status=DISC.STATUS_FILLED, fill_volume=15)
        assert DISC.is_terminal(row) is True
        assert EL.STATUS_FILLED in EL.POSITION_MAY_HAVE_MOVED

    def test_the_runner_discovers_protection_off_the_complete_surface(self):
        v = Venue(hidden=[order(SL_ID, status=DISC.STATUS_SUSPENDED)])
        assert [o["id"] for o in self._runner(v).working_orders()] == [SL_ID]

    def test_an_unreadable_venue_raises_rather_than_returning_empty(self):
        """Every caller replaced a call that DID throw, and each wraps it in a
        `try` whose except branch is the only thing between an unreadable venue
        and a claim of safety."""
        from broker.topstepx_client import TopstepXError
        v = Venue(query_fails=True, no_query=False)
        v.open_orders = lambda: (_ for _ in ()).throw(RuntimeError("down"))
        with pytest.raises(TopstepXError):
            self._runner(v).working_orders()

    def test_the_three_way_split_can_still_see_a_foreign_contract(self):
        """`foreign` means a different contract, so scoping discovery to our own
        instrument would make the category unreachable."""
        v = Venue(orders=[order(SL_ID),
                          {"id": 555000, "contract_id": MNQ, "status": 1},
                          {"id": 666000, "contract_id": "CON.F.US.ES.U26",
                           "status": 1, "parent_order_id": ENTRY_ID}])
        split = self._runner(v).classify_working_orders()
        assert [o["id"] for o in split["ours"]] == [SL_ID]
        assert [o["id"] for o in split["unproven"]] == [555000]
        assert [o["id"] for o in split["foreign"]] == [666000]


# ══ P19  HARD FLATTEN ═══════════════════════════════════════════════════════
class TestHardFlatten:

    class _C:
        id = MNQ

    def test_P19_a_suspended_child_cannot_be_orphaned(self):
        """It was invisible to the old discovery, so the position could be
        closed and the child left resting -- an ENTRY order the instant the
        account went flat.

        ATTRIBUTION IS NOW SUPPLIED, as production supplies it. This used to
        pass with no ledger because ownership was instrument equality; the child
        is claimed here because its tag carries a token THIS SESSION issued.
        """
        v = Venue(hidden=[order(SL_ID, status=DISC.STATUS_SUSPENDED,
                                tag=LG.bot_tag(TOKEN) + "-SL")],
                  position=15)
        rep = HF.hard_flatten(v, self._C(), ledger=ledger())
        assert SL_ID in rep["cancelled"]
        assert rep["flat"] is True

    def test_it_cancels_before_it_closes(self):
        v = Venue(orders=[order(SL_ID, tag=LG.bot_tag(TOKEN))], position=15)
        seq = []
        v.cancel_order = lambda oid: (seq.append("cancel"),
                                      v._orders.clear())
        v.close_position = lambda cid: (seq.append("close"),
                                        setattr(v, "_position", 0))
        HF.hard_flatten(v, self._C(), ledger=ledger())
        assert seq[0] == "cancel" and "close" in seq

    def test_an_unproven_order_is_left_alone_and_blocks_the_flat_claim(self):
        v = Venue(orders=[{"id": 555000, "contract_id": "CON.F.US.ES.U26",
                           "status": 1, "side": 1, "size": 2, "type": 1}],
                  position=0)
        rep = HF.hard_flatten(v, self._C())
        assert 555000 not in rep["cancelled"], "another contract is not ours"


# ══ THE STATUS VOCABULARY HAS ONE OWNER ═════════════════════════════════════
class TestStatusVocabulary:

    def test_the_client_and_the_safety_authority_agree(self):
        """Two copies drift, and a status the venue means as Suspended becoming
        one we treat as terminal is a silent orphan."""
        from broker.topstepx_client import TopstepXClient as C
        assert C.TERMINAL_ORDER_STATUSES == DISC.TERMINAL_STATUSES
        assert C.ACTIVE_ORDER_STATUSES == DISC.WORKING_STATUSES
        assert set(C.ORDER_STATUS) == set(range(9))

    def test_discovery_reexports_rather_than_redeclares(self):
        assert DISC.TERMINAL_STATUSES is EL.TERMINAL_STATUSES
        assert DISC.WORKING_STATUSES is EL.ACTIVE_STATUSES


# ══ AN UNREADABLE VENUE MAY NEVER READ AS AN EMPTY BOOK ═════════════════════
class TestUnreadableIsNotEmpty:
    """`discover_orders` deliberately never throws -- an exception mid-
    liquidation is worse than a labelled degraded read.

    Every OTHER caller replaced `session.open_orders()`, which DID throw, and
    treats the returned list as a venue answer. Handing those callers `[]`
    converts "we cannot see" into "there is nothing there" -- the exact
    substitution this unit exists to remove -- and at the two gates that decide
    whether a trade may be placed it does not merely lose information, it grants
    entry authority against a venue nobody could read.
    """

    @staticmethod
    def _blind():
        v = Venue(orders=[order(SL_ID)], query_fails=True)
        v.open_orders = lambda: (_ for _ in ()).throw(RuntimeError("down"))
        return v

    def test_require_working_orders_raises(self):
        from broker.topstepx_client import TopstepXError
        with pytest.raises(TopstepXError):
            DISC.require_working_orders(self._blind(), contract_id=MNQ)

    def test_a_degraded_but_answered_view_still_returns(self):
        """INCOMPLETE is not UNREADABLE. A `searchOpen` answer is a real answer;
        it simply cannot prove absence."""
        v = Venue(orders=[order(SL_ID)], no_query=True)
        assert [o["id"] for o in
                DISC.require_working_orders(v, contract_id=MNQ)] == [SL_ID]

    def test_the_lane_resolver_fails_closed(self):
        """An `OPEN` lane carries `new_entry_permitted: True`."""
        import inspect

        from broker.topstepx_production_session import ProductionSession
        src = inspect.getsource(ProductionSession)
        assert "_DISC.require_working_orders(" in src
        assert "_DISC.discover_orders(" not in src

    def test_the_scan_loop_entry_gate_fails_closed(self):
        import inspect

        from broker.topstepx_production_loop import ProductionLoop
        src = inspect.getsource(ProductionLoop._execute)
        assert "DISC.require_working_orders(" in src

    def test_the_runner_helper_delegates_to_the_one_rule(self):
        import inspect

        from broker.topstepx_execution_runner import ExecutionRunner
        assert "DISC.require_working_orders(" in inspect.getsource(
            ExecutionRunner.working_orders)


# ══ H1-H7  LANE SHUTDOWN AUTHORITY != MISSION OWNERSHIP ═════════════════════
class TestHardFlattenOwnershipAuthority:
    """THE CONTRADICTION THIS CLASS EXISTS TO CLOSE.

    The discovery unit certified one ownership law -- same contract alone is
    UNPROVEN, never cancelled, never claimed -- and then the missionless
    `hard_flatten` path used `contract_of(order) == contract.id` as its
    ownership predicate. Two doctrines, and the broader one lived where nobody
    was looking: end-of-session, with no mission to check it against.

    These are DIFFERENT AUTHORITIES:

        MISSION_ORDER_OWNERSHIP   this order is ours because lineage proves it
        LANE_SHUTDOWN_AUTHORITY   this order is ours to clear because the LANE
                                  is ours, whatever its lineage says

    The second is only sound on an account mechanically incapable of holding
    someone else's order. This one is not.
    """

    class _C:
        id = MNQ

    OTHER = {"id": 555000, "contract_id": MNQ, "status": 1, "side": 1,
             "size": 2, "type": 1}                       # no tag -> MANUAL

    def test_H1_a_session_tagged_stop_may_be_neutralised(self):
        v = Venue(orders=[order(SL_ID, tag=LG.bot_tag(TOKEN))], position=15)
        rep = HF.hard_flatten(v, self._C(), ledger=ledger())
        assert rep["cancelled"] == [SL_ID]
        assert rep["attribution"] == "session_token_lineage"

    def test_H2_a_manual_same_contract_order_is_never_cancelled(self):
        """Instrument coincidence is not lineage. Cancelling an operator's own
        working order is an unrecoverable act against someone else's intent,
        and 15:55 does not make it recoverable."""
        v = Venue(orders=[dict(self.OTHER)], position=0)
        rep = HF.hard_flatten(v, self._C(), ledger=ledger())
        assert v.cancelled == [] and rep["cancelled"] == []
        assert 555000 in rep["unproven"]
        assert rep["flat"] is False, "an unattributed order blocks the claim"

    def test_H3_exclusive_lane_authority_is_the_only_route_to_the_broad_claim(self):
        """There is exactly ONE place that could grant it, and it refuses."""
        a = HF.lane_shutdown_authority(ledger=ledger())
        assert a["scope"] == HF.LINEAGE_ONLY
        assert a["proven_exclusive"] is False
        assert a["reasons"], "a refusal must say why"

    def test_H4_unknown_exclusivity_never_promotes_an_order_to_ours(self):
        """No ledger, no tokens, no mission: NOTHING is provable. The shutdown
        escalates to the operator rather than guessing in either direction."""
        v = Venue(orders=[order(SL_ID, tag=LG.bot_tag(TOKEN))], position=0)
        rep = HF.hard_flatten(v, self._C())          # no ledger
        assert rep["attribution"] == "none_provable"
        assert v.cancelled == []
        assert rep["flat"] is False
        assert rep["operator_escalation"]

    def test_H5_a_different_contract_is_never_touched(self):
        v = Venue(orders=[{"id": 666000, "contract_id": "CON.F.US.ES.U26",
                           "status": 1, "side": 1, "size": 1, "type": 1,
                           "custom_tag": LG.bot_tag(TOKEN)}], position=0)
        HF.hard_flatten(v, self._C(), ledger=ledger())
        assert v.cancelled == []

    def test_H6_a_foreign_token_is_not_this_session(self):
        """A tag that parses as ours but carries a token this session never
        issued is UNKNOWN_EXTERNAL -- the class the ledger pauses for."""
        v = Venue(orders=[order(SL_ID, tag=LG.bot_tag("SOMEONE-ELSE"))],
                  position=0)
        rep = HF.hard_flatten(v, self._C(), ledger=ledger())
        assert v.cancelled == []
        assert SL_ID in rep["unproven"]

    def test_H7_a_runner_delegates_and_carries_no_second_doctrine(self):
        calls = []

        class _Runner:
            def emergency_flatten(self, reason):
                calls.append(reason)
                return {"flattened": True, "cancelled_mission_orders": [SL_ID],
                        "foreign_orders_left_alone": [], "halts": [],
                        "cancellation_failures": [], "confirmed": {"closed": True}}

        v = Venue(orders=[order(SL_ID)], position=15)
        rep = HF.hard_flatten(v, self._C(), runner=_Runner(), ledger=ledger())
        assert rep["delegated"] is True
        assert rep["authority"] == "MISSION_ORDER_OWNERSHIP"
        assert rep["attribution"] == "mission_lineage"
        assert v.cancelled == [] and v.closed == [], "the runner owns the writes"

    def test_instrument_equality_appears_nowhere_as_ownership(self):
        """The specific shape that was wrong, forbidden by inspection."""
        import inspect
        src = inspect.getsource(HF.hard_flatten)
        assert "owns=owns" in src
        assert "contract_of(o)" not in src
        assert "== str(contract.id)" not in src

    def test_the_two_laws_are_stated_and_do_not_overlap(self):
        assert HF.LINEAGE_ONLY != HF.BOT_EXCLUSIVE_LANE
        # mission ownership is unchanged by any of this
        assert DISC.order_lineage(dict(self.OTHER), entry_order_id=ENTRY_ID,
                                  contract_id=MNQ) == DISC.UNPROVEN

    def test_an_unattributed_order_blocks_the_close_not_just_the_claim(self):
        """A close underneath an order we may not cancel is a coin flip.

        Either it is the operator's -- and his order now acts against a net
        position he did not choose -- or it is OUR orphaned child, in which case
        it is an ENTRY the instant the account goes flat. That second case is
        2026-08-26 with the ownership proof missing instead of the ordering
        wrong, and that session proved the bot can fail to recognise its own
        children.
        """
        v = Venue(orders=[dict(self.OTHER)], position=15)
        rep = HF.hard_flatten(v, self._C(), ledger=ledger())
        assert v.closed == [], "the position must NOT be closed"
        assert v.cancelled == [], "the order must NOT be cancelled"
        assert rep["operator_escalation"]
        assert rep["flat"] is False

    def test_the_shared_planner_halts_under_unproven_with_a_position_open(self):
        """THE SPECIMEN THIS REPLACED, NOW ASSERTING THE REPAIR.

        This test previously existed to hold a KNOWN-WRONG behaviour visible:
        `EL.plan` halted on an unproven executable order when the position was
        already flat, but with a position OPEN it fell through to
        `ACTION_CLOSE`. A nonzero position quantity is not a proof of anything,
        so the asymmetry had nothing behind it.

        `TOPSTEP-UNPROVEN-ORDER-CLOSE-AUTHORITY-1` made it symmetric. The
        specimen is kept rather than deleted, restated as the positive theorem:

            an executable order whose authority is UNPROVEN may not be mutated
            around by creating or changing flatness
        """
        d = EL.plan(position_size=15,
                    orders=[dict(self.OTHER, side=1, status=1)],
                    owns=lambda o: False)
        assert d["found"]["unproven"], "the order is correctly UNPROVEN"
        assert d["action"] == EL.ACTION_HALT
        assert d["reason"] == EL.OWNERSHIP_AMBIGUOUS
        assert d["unresolved_live_exposure"] is True
        assert d["terminal_success"] is False
