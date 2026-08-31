"""TOPSTEPX-PARALLEL-MUTATION-SURFACE-1.

THE SAFETY BOUNDARY IS THE BROKERAGE ACCOUNT, NOT THE ENTRYPOINT WE CALL
PRODUCTION.

`COMBINED-SAFETY-READINESS-CERTIFICATION-1` halted at its second question --
"show me every piece of code that can actually change the account" -- and found
a sixth defect behind five certified safety commits and 7,888 passing tests:

    integrations/topstepx/deterministic/loop.py
        -> TopstepXLaneClient.flatten()
        -> TopstepXBrokerAdapter.flatten()
        -> TopstepXClient.close_position(account_id, contract_id)

A bare close on a real TopstepX account: no canonical discovery, no ownership
classification, no ambiguity gate, no child neutralisation, no terminality
proof, no measured exposure, no re-read, no safe-terminal proof. And it was NOT
behind `TOPSTEPX_ARM_ORDERS`, which gates that lane's order path -- so placing
an order required arming while flattening a live position did not.

None of the five safety repairs applied, because none of them were on that path.

THE RULING. The lane is not the Combine execution organism and is not being
certified as one. Rather than grow the certified architecture to absorb a second
execution path, its mutation authority is REMOVED. Read-only means read-only,
in code -- not by convention, environment flag, or the fact that nobody
currently launches it.
"""
import ast
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from integrations.topstepx.deterministic import (                # noqa: E402
    topstepx_mutation_authority as MA)
from integrations.topstepx.deterministic.topstepx_lane_client import (  # noqa: E402
    TopstepXLaneClient)

LANE_DIR = os.path.join(ROOT, "src", "integrations", "topstepx", "deterministic")


class LoudAdapter:
    """Any mutation reaching this object is a LEAK, and says so by name."""

    class _Client:
        def query_orders(self, *a, **kw):
            return [{"id": 1, "status": 1}]

        def open_orders(self, *a, **kw):
            return []

        def close_position(self, *a, **kw):
            raise AssertionError("LEAK: close_position reached the venue client")

        def place_order_raw(self, *a, **kw):
            raise AssertionError("LEAK: place_order_raw reached the venue client")

        def cancel_order(self, *a, **kw):
            raise AssertionError("LEAK: cancel_order reached the venue client")

        def modify_order(self, *a, **kw):
            raise AssertionError("LEAK: modify_order reached the venue client")

    _client = _Client()

    def connect(self):
        return "account"

    def is_connected(self):
        return True

    def get_account(self):
        # The adapter's real contract, not an abbreviation of it.
        return {"account": "PRAC", "account_id": 11111111, "balance": 50000.0,
                "cash_value": 50000.0, "simulated": True, "can_trade": True}

    def get_position(self, symbol=""):
        # The adapter publishes `size` + `side`; the lane derives the SIGN.
        return {"size": 5, "side": "long", "avg_price": 29257.5, "flat": False}

    def bars_1m(self, **kw):
        # PRODUCTION SHAPE. The lane asserts bar freshness from `timestamp`
        # rather than inferring it downstream, so a fixture without one is
        # modelling a payload the client never emits.
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        return [{"timestamp": now, "open": 29250.0, "high": 29255.0,
                 "low": 29245.0, "close": 29250.0, "volume": 10}]

    def _require(self):
        class _Account:
            id = 11111111
            name = "PRAC"

        class _Contract:
            id = "CON.F.US.MNQ.U26"
            tick_size = 0.25
            tick_value = 0.5
        return _Account(), _Contract()

    def flatten(self):
        raise AssertionError("LEAK: adapter.flatten was invoked")

    def submit_order(self, order):
        raise AssertionError("LEAK: adapter.submit_order was invoked")


def lane(connected=True):
    c = TopstepXLaneClient(adapter=LoudAdapter())
    c._connected = connected
    return c


def denied(result) -> bool:
    return (isinstance(result, dict)
            and result.get("authority") == MA.DENIED
            and result.get("lane") == MA.LANE
            and not result.get("accepted")
            and not result.get("flattened"))


# ══ M1-M6  EVERY MUTATION IS REFUSED ════════════════════════════════════════
class TestLaneMutationsDenied:

    def test_M1_M2_a_deterministic_bracket_order_is_denied(self):
        out = lane().deterministic_order({"direction": "long", "quantity": 1,
                                          "structural_stop_price": 29200.0,
                                          "target_points": 40.0})
        assert denied(out), out

    def test_M5_flatten_is_denied_and_never_reaches_close_position(self):
        """THE SIXTH DEFECT, closed. `LoudAdapter` raises on any leak, so a
        passing test is positive proof the venue was never asked."""
        assert denied(lane().flatten("MNQ"))

    def test_M6_an_emergency_flatten_is_still_denied(self):
        """"emergency", "safety", "cleanup" and "flatten" are not authorities.
        A safety action taken without certified authority is still an
        unauthorized mutation."""
        assert denied(lane().flatten())

    def test_M3_M4_submit_paths_are_denied(self):
        assert denied(lane().submit_market_entry({"direction": "long"}))
        out = lane().submit_oco({"price": 1}, {"price": 2})
        assert out.get("accepted") is False

    def test_a_denial_is_distinguishable_from_a_transport_failure(self):
        """An operator debugging "why did nothing happen" must not be told the
        same thing by an authority refusal and a dropped connection."""
        refusal = lane().flatten()
        disconnected = lane(connected=False).flatten()
        assert refusal["authority"] == MA.DENIED
        assert disconnected["authority"] == MA.DENIED
        # ... and neither is a silent no-op:
        assert refusal["reason"] and MA.DENIED in refusal["reason"]

    def test_denial_happens_before_the_connection_check(self):
        """Not-connected is a reason an AUTHORIZED caller might fail. This lane
        is not an authorized caller at all, so authority is settled first."""
        assert denied(lane(connected=False).deterministic_order({}))


# ══ M7-M10  NO ENVIRONMENT OR ACCOUNT RESTORES AUTHORITY ════════════════════
class TestNoConfigurationRestoresAuthority:

    @pytest.mark.parametrize("armed", ["true", "false", "1", "on", "", "yes"])
    def test_M7_M8_TOPSTEPX_ARM_ORDERS_cannot_re_arm_this_lane(self, monkeypatch,
                                                              armed):
        """The flag that gated the ORDER path never gated `flatten`, which is
        how the defect survived. It now governs nothing here in either
        direction: an environment variable is a convention, and authority is
        structural."""
        monkeypatch.setenv("TOPSTEPX_ARM_ORDERS", armed)
        assert denied(lane().flatten())
        assert denied(lane().deterministic_order({}))

    def test_M9_M10_the_production_account_and_credential_change_nothing(
            self, monkeypatch):
        """Same account name, same API key, same contract as the certified
        production organism -- still denied. Configuration is not authority."""
        monkeypatch.setenv("TOPSTEPX_ACCOUNT_NAME", "PRACTICEJUL2419435750")
        monkeypatch.setenv("TOPSTEPX_ACCOUNT_ID", "11111111")
        monkeypatch.setenv("TOPSTEPX_CONTRACT", "CON.F.US.MNQ.U26")
        monkeypatch.setenv("TOPSTEPX_ALLOW_LIVE", "true")
        assert denied(lane().flatten())
        assert denied(lane().deterministic_order({}))


# ══ M11-M12  READS SURVIVE ══════════════════════════════════════════════════
class TestReadsRemainFunctional:
    """The lane keeps its certified read-only purpose. Removing authority must
    not remove observation."""

    def test_M11_account_and_position_reads_work(self):
        c = lane()
        state = c.account_state()
        assert state["known"] is True and state["account_id"] == 11111111
        assert c.position("MNQ")["qty"] == 5

    def test_M12_market_data_acquisition_works(self):
        assert lane().historical_1m("MNQ", 5) is not None

    def test_order_discovery_reads_through_the_proxy(self):
        """The lane legitimately reaches `adapter._client.query_orders` for
        discovery -- which is exactly the climb the proxy has to allow while
        still refusing what sits beside it."""
        assert lane().order_summary()["known"] is True


# ══ THE PROXY ITSELF ════════════════════════════════════════════════════════
class TestReadOnlyProxy:

    def test_the_climb_through_client_is_refused(self):
        """THE HAZARD THIS EXISTS FOR. Handing back the raw client would let a
        caller reach `close_position` one attribute after a legitimate read."""
        ro = MA.read_only(LoudAdapter())
        assert ro._client.query_orders() == [{"id": 1, "status": 1}]
        with pytest.raises(MA.TopstepXMutationAuthorityDenied):
            ro._client.close_position(1, "x")

    def test_a_mutation_cannot_be_grafted_back_on(self):
        ro = MA.read_only(LoudAdapter())
        with pytest.raises(MA.TopstepXMutationAuthorityDenied):
            ro.flatten = lambda: "MUTATED"

    def test_a_method_added_tomorrow_is_denied_by_default(self):
        """THIS ASSERTION WAS INVERTED, AND THAT IS THE UNIT.

        It used to end by documenting a hole: `assert ro.liquidate_everything()
        == "not in the vocabulary"`. The boundary was a DENYLIST, so a mutation
        under a name nobody had thought of passed straight through -- which
        meant the report could say "KNOWN MUTATIONS DENIED" but never
        "STRUCTURALLY READ-ONLY".

        `TOPSTEPX-ADAPTER-CAPABILITY-BOUNDARY-1` inverted it into a GRANT. The
        surface is now what was explicitly allowed, so a name that does not
        exist yet is already refused, and adding a method to the adapter does
        NOT make it reachable from this lane.
        """
        class Future:
            def close_position(self, *a):
                raise AssertionError("LEAK")

            def liquidate_everything(self, *a):
                raise AssertionError("LEAK: an ungranted name was reachable")

            def get_account(self):
                return {"granted": True}

        ro = MA.read_only(Future())
        assert ro.get_account() == {"granted": True}, "granted reads still work"
        for invented in ("liquidate_everything", "close_position", "flatten_all",
                         "replace_order", "submit_oco", "wind_down"):
            with pytest.raises(MA.TopstepXCapabilityDenied):
                getattr(ro, invented)

    def test_the_denial_is_not_a_venue_error(self):
        """A `TopstepXError` means the account said no. This means we never
        asked, and never will from here."""
        from broker.topstepx_client import TopstepXError
        assert not issubclass(MA.TopstepXMutationAuthorityDenied, TopstepXError)


# ══ M16-M19  THE STRUCTURAL PROHIBITION ═════════════════════════════════════
class TestCallGraphProhibition:
    """Binds the ARCHITECTURE, not today's method list. These fail if a future
    change reintroduces a reachable TopstepX mutation from this lane -- through
    a new wrapper, a new adapter, or a revived body."""

    #: The only module permitted to name the mutating surface, because naming it
    #: is how it refuses it.
    AUTHORITY = "topstepx_mutation_authority.py"

    def _lane_sources(self):
        for name in sorted(os.listdir(LANE_DIR)):
            if not name.endswith(".py") or name == self.AUTHORITY:
                continue
            with open(os.path.join(LANE_DIR, name), encoding="utf-8") as fh:
                yield name, fh.read()

    @pytest.mark.parametrize("operation", [
        "close_position", "place_order", "place_order_raw",
        "place_bracket_market_order", "cancel_order", "modify_order",
        "submit_order",
    ])
    def test_M16_M19_no_lane_module_calls_a_topstepx_mutation(self, operation):
        offenders = []
        for name, src in self._lane_sources():
            for node in ast.walk(ast.parse(src)):
                if not isinstance(node, ast.Call):
                    continue
                try:
                    called = ast.unparse(node.func)
                except Exception:            # noqa: BLE001
                    continue
                if called.endswith(f".{operation}") or called == operation:
                    offenders.append(f"{name}: {called}")
        assert offenders == [], offenders

    def test_the_lane_never_holds_a_raw_adapter(self):
        """Every TopstepX handle in this package must pass through `read_only`.
        A bare `TopstepXBrokerAdapter()` assigned to an attribute would restore
        the whole mutating surface in one line."""
        for name, src in self._lane_sources():
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                value = ast.unparse(node.value)
                if "TopstepXBrokerAdapter(" in value:
                    assert "_read_only(" in value or "read_only(" in value, \
                        f"{name}: unwrapped adapter -> {value}"

    def test_the_revived_order_body_is_gone_not_merely_unreachable(self):
        """Unreachable order-submission code beside a live credential is an
        invitation: the next reader sees a working implementation one `return`
        away from running."""
        src = open(os.path.join(LANE_DIR, "topstepx_lane_client.py"),
                   encoding="utf-8").read()
        assert "stopLossBracket" not in src
        assert "target_points=" not in src


# ══ M13-M15  THE CERTIFIED PRODUCTION PATH IS UNTOUCHED ═════════════════════
class TestProductionPathUnchanged:
    """This unit REMOVES authority from a parallel lane. It must not remove any
    from the organism that will trade the Combine."""

    def test_M13_the_production_runner_can_still_place_an_order(self):
        import inspect

        from broker.topstepx_execution_runner import ExecutionRunner
        assert "self.session.place_order(" in inspect.getsource(ExecutionRunner)

    def test_M14_the_certified_emergency_authority_still_closes(self):
        import inspect

        from broker.topstepx_execution_runner import ExecutionRunner
        src = inspect.getsource(ExecutionRunner.emergency_flatten)
        assert "self.session.close_position(" in src
        assert "EL.plan(" in src

    def test_M15_management_can_still_cancel_and_modify(self):
        import inspect

        from broker import break_even_actuator as ACT
        from broker.topstepx_execution_runner import ExecutionRunner
        runner_src = inspect.getsource(ExecutionRunner)
        assert "self.session.cancel_order(" in runner_src
        assert "self.session.modify_order(" in runner_src
        assert "session.modify_order(" in inspect.getsource(ACT.apply_break_even)

    def test_the_production_lane_does_not_import_the_deterministic_lane(self):
        launcher = open(os.path.join(ROOT, "tools",
                                     "topstepx_production_session.py"),
                        encoding="utf-8").read()
        assert "ninjatrader" not in launcher.lower()


# ══ M20  THE OPERATOR SMOKE TOOL ════════════════════════════════════════════
class TestOperatorSmokeToolAuthority:
    """Classified mechanically, not by the folder it lives in.

    It targets the SAME account with the same credentials, so `tools/` is not a
    safety boundary. What makes it EXPLICIT OPERATOR AUTHORITY rather than a
    parallel unsafe one is that it pins the account by id AND fingerprint,
    aborts unless the book is empty, and honours the session pause -- and, now,
    that its liquidation goes through the certified convergence authority
    instead of a close-first sequence of its own.
    """

    def _src(self):
        return open(os.path.join(ROOT, "tools", "topstepx_execution_smoke.py"),
                    encoding="utf-8").read()

    def test_M20_it_no_longer_closes_before_cancelling(self):
        src = self._src()
        assert "session.close_position(" not in src
        assert "hard_flatten(session, contract, ledger=ledger)" in src

    def test_it_cancels_by_lineage_never_by_instrument(self):
        src = self._src()
        assert "LG.classify(o, known) != LG.EXPANSION_BOT" in src

    def test_it_discovers_canonically_when_a_submit_is_uncertain(self):
        assert "DISC.discover_orders(session, contract_id=contract.id)" in self._src()

    def test_its_authority_boundary_is_mechanical(self):
        """Exact account id AND expected fingerprint, an empty-book
        precondition, and the ledger pause law. Intent is not a boundary;
        these are."""
        src = self._src()
        assert "expected_fingerprint=os.getenv" in src
        assert "ABORT: not flat" in src
        assert "ledger.requires_pause()" in src
