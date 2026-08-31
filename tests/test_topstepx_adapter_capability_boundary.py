"""TOPSTEPX-ADAPTER-CAPABILITY-BOUNDARY-1.

TWO AUTHORITY GAPS THAT `1c8a1d5` DISCLOSED IN ITS OWN REPORT.

**A. The deterministic lane was not yet structurally read-only.** Its boundary
was a DENYLIST of known mutating names, so the verdict "READ_ONLY" and the
admission "an unrecognised method name passes through" were printed in the same
report. Those are inconsistent. Accurately:

    KNOWN MUTATIONS DENIED      proven
    STRUCTURALLY READ-ONLY      not proven

The ruling was never "block the four mutator names we know today". It was: this
lane may READ a TopstepX account and may not CHANGE one. Only a grant can
establish that, so the model is inverted -- allow the certified read surface,
deny everything else, including names that do not exist yet.

**B. `broker/factory.py` still handed out a fully mutating adapter.** Any caller
asking `get_adapter(broker="topstepx")` received place, cancel, modify and close
authority over an environment-selected account, with no certified execution
authority in the path. The audit found no operational caller -- and "nothing
calls it today" is precisely the reasoning that left an ungated
`close_position` alive in the deterministic lane until a combined certification
went looking for it.

    THE SAFETY BOUNDARY IS THE BROKERAGE ACCOUNT, NOT THE ENTRYPOINT WE CALL
    PRODUCTION.

WHO MAY REQUEST LIQUIDATION can differ. HOW LIQUIDATION SAFELY OCCURS may not.
"""
import ast
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker import topstepx_read_capability as CAP                  # noqa: E402
from broker.factory import available_brokers, get_adapter           # noqa: E402
from integrations.topstepx.deterministic import (                # noqa: E402
    topstepx_mutation_authority as MA)


class Adapter:
    """Reads answer. Anything reaching a mutation is a LEAK and says so."""

    class _Client:
        def query_orders(self, *a, **kw):
            return [{"id": 1, "status": 1}]

        def order_by_id(self, *a, **kw):
            return {"id": 1, "status": 2}

        # Implemented so the B27 sweep covers the WHOLE granted client surface
        # rather than skipping part of it -- a partially-swept boundary is a
        # partially-proven one.
        def open_orders(self, *a, **kw):
            return [{"id": 2, "status": 1}]

        def open_positions(self, *a, **kw):
            return [{"contract_id": "CON.F.US.MNQ.U26", "size": 5, "type": 1}]

        def close_position(self, *a, **kw):
            raise AssertionError("LEAK: close_position reached the client")

        def place_order_raw(self, *a, **kw):
            raise AssertionError("LEAK: place_order_raw reached the client")

    _client = _Client()

    def connect(self):
        return "account"

    def is_connected(self):
        return True

    def get_account(self):
        return {"account": "PRAC", "balance": 50000.0}

    def get_position(self, symbol=""):
        return {"size": 5, "side": "long"}

    def bars_1m(self, **kw):
        return [{"timestamp": "2026-08-26T13:00:00Z", "close": 29250.0}]

    def _require(self):
        # THE REAL PRODUCTION RECORDS, not a shim. `TopstepXContract` carries
        # `points_to_ticks` and both carry `from_api` -- which is exactly why
        # `_require` is capability-bearing rather than data-only, and exactly
        # what the return-value guard has to hold.
        from broker.topstepx_client import TopstepXAccount, TopstepXContract
        return (TopstepXAccount(id=11111111, name="PRAC", balance=50000.0,
                                can_trade=True, simulated=True),
                TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU26",
                                 description="", tick_size=0.25,
                                 tick_value=0.5, active=True))

    # ── identity reads, so the B26 sweep covers the whole granted surface ──
    @property
    def name(self):
        return "topstepx"

    def capability(self):
        from broker.base import BrokerCapability
        return BrokerCapability(name="topstepx", supports_orders=False)

    def describe(self):
        return {"name": "topstepx", "account_id": 11111111}

    # ── the mutating surface, present exactly so its absence can be proven ──
    def submit_order(self, order):
        raise AssertionError("LEAK: submit_order was invoked")

    def flatten(self):
        raise AssertionError("LEAK: flatten was invoked")

    # ── names no denylist could have anticipated ────────────────────────────
    def liquidate_contract(self, *a):
        raise AssertionError("LEAK: liquidate_contract was invoked")

    def flatten_all(self, *a):
        raise AssertionError("LEAK: flatten_all was invoked")

    def replace_order(self, *a):
        raise AssertionError("LEAK: replace_order was invoked")

    def submit_oco(self, *a):
        raise AssertionError("LEAK: submit_oco was invoked")


def cap():
    return CAP.read_only(Adapter(), label="test")


# ══ B1-B3  GRANTED READS WORK ═══════════════════════════════════════════════
class TestGrantedReads:

    @pytest.mark.parametrize("name,expect", [
        ("get_account", {"account": "PRAC", "balance": 50000.0}),
        ("get_position", {"size": 5, "side": "long"}),
        ("is_connected", True),
    ])
    def test_B1_certified_reads_are_allowed(self, name, expect):
        assert getattr(cap(), name)() == expect

    def test_B2_query_orders_is_granted_through_the_client(self):
        assert cap()._client.query_orders() == [{"id": 1, "status": 1}]

    def test_B3_the_terminality_oracle_is_granted(self):
        assert cap()._client.order_by_id(1)["status"] == 2

    def test_market_history_is_granted(self):
        assert cap().bars_1m()

    def test_the_pinned_account_and_contract_are_addressable(self):
        account, contract = cap()._require()
        assert account.id == 11111111
        assert contract.id == "CON.F.US.MNQ.U26"


# ══ B4-B9  DEFAULT DENY ═════════════════════════════════════════════════════
class TestDefaultDeny:

    def test_B4_an_unknown_attribute_is_denied(self):
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            cap().anything_at_all

    @pytest.mark.parametrize("invented", [
        "liquidate_contract",      # B5
        "submit_oco",              # B6
        "replace_order",           # B7
        "flatten_all",
        "wind_down_account",
        "square_up",
        "emergency_exit",
    ])
    def test_B5_B7_invented_mutation_names_are_denied(self, invented):
        """THE DIFFERENCE FROM A DENYLIST. None of these appear in any mutation
        vocabulary; they are denied because they were never GRANTED."""
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            getattr(cap(), invented)

    def test_the_known_mutators_remain_denied_too(self):
        for name in ("submit_order", "flatten"):
            with pytest.raises(CAP.TopstepXCapabilityDenied):
                getattr(cap(), name)

    def test_B8_the_raw_client_cannot_be_climbed(self):
        c = cap()._client
        assert c.query_orders(), "the granted read still works"
        for name in ("close_position", "place_order_raw", "cancel_order"):
            with pytest.raises(CAP.TopstepXCapabilityDenied):
                getattr(c, name)

    def test_B9_a_mutator_cannot_be_grafted_on(self):
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            cap().close_position = lambda *a: "MUTATED"

    def test_no_granted_read_leaks_a_mutating_object(self):
        """`NESTED` names the one attribute that hands back a capability. This
        proves nothing ELSE granted returns an object carrying a mutating name.
        """
        c = cap()
        for name in sorted(CAP.ADAPTER_READS):
            if name in CAP.NESTED:
                continue
            try:
                value = getattr(c, name)
            except AttributeError:
                continue          # the stub does not implement this read
            got = value() if callable(value) else value
            for row in (got if isinstance(got, tuple) else (got,)):
                for mutator in MA.REFUSED_OPERATIONS:
                    assert not hasattr(row, mutator), f"{name} leaked {mutator}"


# ══ B7  THE FUTURE-API THEOREM ══════════════════════════════════════════════
class TestFutureApiGrowth:
    """Adding a method to the adapter does NOT make it available here. A new
    capability requires an explicit grant, reviewed as a grant."""

    def test_a_brand_new_adapter_method_is_not_reachable(self):
        class Tomorrow(Adapter):
            def brand_new_read(self):
                return "should require a grant"

        c = CAP.read_only(Tomorrow(), label="test")
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            c.brand_new_read

    def test_the_surface_is_a_grant_not_a_ban(self):
        import inspect
        src = inspect.getsource(CAP.TopstepXReadCapability.__getattr__)
        assert "not in surface" in src
        assert "MUTATIONS" not in src, "no denylist may govern this"


# ══ B10-B13  CONFIGURATION IS NOT AUTHORITY ═════════════════════════════════
class TestConfigurationGrantsNothing:

    @pytest.mark.parametrize("var,value", [
        ("TOPSTEPX_ARM_ORDERS", "true"),        # B12
        ("TOPSTEPX_ALLOW_LIVE", "true"),        # B13
        ("TOPSTEPX_ACCOUNT_NAME", "PRACTICEJUL2419435750"),   # B10
        ("TOPSTEPX_ACCOUNT_ID", "11111111"),
        ("TOPSTEPX_API_KEY", "same-credential"),              # B11
        ("TOPSTEPX_ACCOUNT_ROLE", "TRADING_COMBINE"),
    ])
    def test_B10_B13_no_env_var_restores_mutation(self, monkeypatch, var, value):
        monkeypatch.setenv(var, value)
        c = cap()
        assert c.get_account()["account"] == "PRAC", "reads still work"
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            c.flatten


# ══ B14-B18  THE GENERIC FACTORY ════════════════════════════════════════════
class TestGenericFactory:

    def test_topstepx_remains_registered(self):
        assert set(available_brokers()) == {"paper", "tradestation",
                                            "topstepx"}

    def test_B14_the_factory_returns_a_read_only_capability(self):
        a = get_adapter(broker="topstepx")
        assert isinstance(a, CAP.ReadOnlyTopstepXBrokerAdapter)
        assert a.name == "topstepx"
        assert a.describe()["order_authority"] is False

    @pytest.mark.parametrize("operation", [
        "submit_order",      # B15
        "cancel_order",      # B16
        "modify_order",      # B17
        "close_position",    # B18
        "flatten",
        "place_bracket_market_order",
    ])
    def test_B15_B18_generic_callers_cannot_mutate(self, operation):
        a = get_adapter(broker="topstepx")
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            got = getattr(a, operation)      # denied on ACCESS for ungranted
            got() if callable(got) else got  # ... or on CALL for the two the
                                             # BrokerAdapter interface requires


    def test_the_factory_never_constructs_the_mutating_adapter_directly(self):
        import inspect

        from broker import factory
        src = inspect.getsource(factory)
        assert "ReadOnlyTopstepXBrokerAdapter" in src
        assert '_REGISTRY["topstepx"] = TopstepXBrokerAdapter' not in src

    def test_B24_no_operational_caller_acquires_a_mutating_adapter(self):
        """AST over src/ and tools/. The mutating class may EXIST -- a public
        class in source is not an operational entrypoint -- but nothing outside
        the read-only facade may construct one."""
        allowed = {
            os.path.join("src", "broker", "topstepx_adapter.py"),          # itself
            os.path.join("src", "broker", "topstepx_read_capability.py"),  # wraps it
            os.path.join("src", "broker", "topstepx_preflight.py"),        # read-only
            os.path.join("src", "integrations", "topstepx", "deterministic",
                         "topstepx_lane_client.py"),                       # wrapped
        }
        offenders = []
        for base in ("src", "tools"):
            for root, _dirs, files in os.walk(os.path.join(ROOT, base)):
                if "__pycache__" in root:
                    continue
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(root, name)
                    rel = os.path.relpath(path, ROOT)
                    if rel in allowed:
                        continue
                    with open(path, encoding="utf-8-sig") as fh:
                        src = fh.read()
                    if "TopstepXBrokerAdapter(" in src:
                        offenders.append(rel)
        assert offenders == [], offenders

    def test_the_lane_and_the_factory_share_ONE_boundary(self):
        """Two implementations of one rule is the defect class this whole day
        was about."""
        import inspect
        assert "topstepx_read_capability" in inspect.getsource(MA)


# ══ B19-B21  NOTHING CERTIFIED REGRESSED ════════════════════════════════════
class TestNothingCertifiedRegressed:

    def test_B19_preflight_still_reads(self):
        import inspect

        from broker import topstepx_preflight as PF
        src = inspect.getsource(PF)
        for read in ("adapter.connect()", "adapter.get_account()",
                     "adapter.bars_1m(", "adapter.get_position()"):
            assert read in src
        for mutation in ("adapter.submit_order", "adapter.flatten"):
            assert mutation not in src

    def test_B20_the_lane_still_reads_market_and_account_data(self):
        from integrations.topstepx.deterministic.topstepx_lane_client import (
            TopstepXLaneClient)
        c = TopstepXLaneClient(adapter=Adapter())
        c._connected = True
        assert c.position("MNQ")["qty"] == 5
        assert c.order_summary()["known"] is True

    def test_B21_the_certified_production_organism_still_mutates(self):
        import inspect

        from broker.topstepx_execution_runner import ExecutionRunner
        src = inspect.getsource(ExecutionRunner)
        assert "self.session.place_order(" in src
        assert "self.session.close_position(" in src
        assert "self.session.cancel_order(" in src
        assert "self.session.modify_order(" in src

    def test_the_production_organism_does_not_use_the_generic_factory(self):
        for rel in (os.path.join("tools", "topstepx_production_session.py"),
                    os.path.join("src", "broker", "topstepx_production_session.py"),
                    os.path.join("src", "broker", "topstepx_execution_runner.py")):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                assert "get_adapter(" not in fh.read(), rel


# ══ B22-B23  THE OPERATOR SMOKE TOOL ════════════════════════════════════════
class TestOperatorSmokeAuthorityFrozen:
    """Disposition ACCEPTED: explicit operator authority, certified convergence.

    WHO MAY REQUEST LIQUIDATION can differ between an operator tool and the
    production organism. HOW LIQUIDATION SAFELY OCCURS may not.
    """

    def _src(self):
        with open(os.path.join(ROOT, "tools", "topstepx_execution_smoke.py"),
                  encoding="utf-8") as fh:
            return fh.read()

    def test_B22_it_uses_the_certified_convergence_authority(self):
        src = self._src()
        assert "hard_flatten(session, contract, ledger=ledger)" in src
        assert "session.close_position(" not in src, \
            "no second liquidation policy may return here"

    def test_B22_residual_cancellation_is_lineage_not_instrument(self):
        assert "LG.classify(o, known) != LG.EXPANSION_BOT" in self._src()

    def test_B23_it_cannot_be_reached_automatically_from_production(self):
        """A different authority to INITIATE, never an automatic one."""
        for rel in (os.path.join("tools", "topstepx_production_session.py"),
                    os.path.join("src", "broker", "topstepx_production_loop.py"),
                    os.path.join("src", "broker", "topstepx_production_session.py")):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                body = fh.read()
            assert "topstepx_execution_smoke" not in body, rel

    def test_its_authority_boundary_is_still_mechanical(self):
        src = self._src()
        assert "expected_fingerprint=os.getenv" in src
        assert "ABORT: not flat" in src
        assert "ledger.requires_pause()" in src

    def test_no_module_imports_the_smoke_tool(self):
        offenders = []
        for base in ("src", "tools"):
            for root, _dirs, files in os.walk(os.path.join(ROOT, base)):
                if "__pycache__" in root:
                    continue
                for name in files:
                    if not name.endswith(".py") or name == "topstepx_execution_smoke.py":
                        continue
                    path = os.path.join(root, name)
                    with open(path, encoding="utf-8-sig") as fh:
                        src = fh.read()
                    for node in ast.walk(ast.parse(src)):
                        if isinstance(node, (ast.Import, ast.ImportFrom)):
                            text = ast.unparse(node)
                            if "topstepx_execution_smoke" in text:
                                offenders.append(os.path.relpath(path, ROOT))
        assert offenders == [], offenders


# ══ B25-B30  RETURN-VALUE ESCAPE ════════════════════════════════════════════
class TestReturnValueEscape:
    """AN ALLOWED READ MAY NOT RETURN AN UNCONTROLLED MUTATING CAPABILITY.

    The outer allowlist is worthless if a PERMITTED read hands the caller an
    object through which authority is reacquired:

        read capability -> allowed method -> returns object -> object exposes
        mutation

    And the fix must not be "scan return values for known bad method names" --
    that reproduces the denylist problem one layer deeper. The rule is
    structural: data crosses, BEHAVIOUR does not, whatever it is called.
    """

    def test_B25_require_returns_records_whose_behaviour_is_not_granted(self):
        """`_require` is CAPABILITY_BEARING, not data-only, and always was.

        `TopstepXContract` carries `points_to_ticks`; both records carry a
        `from_api` classmethod reachable from an instance. Nothing dangerous is
        reachable through them TODAY -- but "this method is harmless" is a
        judgement about a name, and that is exactly what must not hold the
        boundary up.
        """
        account, contract = cap()._require()
        assert account.id == 11111111, "data still crosses"
        assert contract.id == "CON.F.US.MNQ.U26"
        for behaviour in ("points_to_ticks", "from_api"):
            with pytest.raises(CAP.TopstepXCapabilityDenied):
                getattr(contract, behaviour)

    def test_the_real_contract_record_is_the_one_under_test(self):
        """Bound to the PRODUCTION type, not a stand-in -- the shape that made
        `_require` capability-bearing has to be the shape being guarded."""
        from broker.topstepx_client import TopstepXContract
        real = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU26",
                                description="", tick_size=0.25,
                                tick_value=0.5, active=True)
        assert callable(real.points_to_ticks), "the method genuinely exists"
        view = CAP.guard(real, "t")
        assert view.tick_size == 0.25
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            view.points_to_ticks

    @pytest.mark.parametrize("name", sorted(CAP.ADAPTER_READS - {"_client"}))
    def test_B26_no_granted_adapter_read_returns_an_uncontrolled_object(self, name):
        c = cap()
        try:
            value = getattr(c, name)
        except AttributeError:
            pytest.skip("the stub does not implement this read")
        got = value() if callable(value) else value
        self._assert_controlled(got)

    @pytest.mark.parametrize("name", sorted(CAP.CLIENT_READS))
    def test_B27_no_granted_client_read_returns_an_uncontrolled_object(self, name):
        client = cap()._client
        try:
            value = getattr(client, name)
        except AttributeError:
            pytest.skip("the stub does not implement this read")
        got = value(1) if callable(value) else value
        self._assert_controlled(got)

    @staticmethod
    def _assert_controlled(value, depth=0):
        """Recursively: data, a guarded view, or a further grant. Never raw."""
        assert depth < 8, "guard recursion is bounded"
        if isinstance(value, CAP.DATA_TYPES):
            return
        if isinstance(value, (CAP.TopstepXDataView, CAP.TopstepXReadCapability)):
            return
        if isinstance(value, dict):
            for v in value.values():
                TestReturnValueEscape._assert_controlled(v, depth + 1)
            return
        if isinstance(value, (list, tuple, set, frozenset)):
            for v in value:
                TestReturnValueEscape._assert_controlled(v, depth + 1)
            return
        raise AssertionError(f"uncontrolled object crossed the boundary: {value!r}")

    def test_B28_nested_containers_are_guarded_all_the_way_down(self):
        class Deep:
            def mutate(self):
                raise AssertionError("LEAK")

        class Adapter2(Adapter):
            def get_account(self):
                return {"rows": [{"inner": Deep()}], "n": 1}

        c = CAP.read_only(Adapter2(), label="t")
        got = c.get_account()
        assert got["n"] == 1
        inner = got["rows"][0]["inner"]
        assert isinstance(inner, CAP.TopstepXDataView)
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            inner.mutate

    def test_B29_an_arbitrary_callable_name_is_denied(self):
        """THE THEOREM MUST NOT DEPEND ON RECOGNISING A NAME AS MUTATING.

        None of these appear in any vocabulary. They are refused because they
        are BEHAVIOUR, which does not cross a read boundary.
        """
        class Returned:
            value = 7

            def liquidate_contract(self):
                raise AssertionError("LEAK")

            def wind_down(self):
                raise AssertionError("LEAK")

            def perfectly_innocent_helper(self):
                raise AssertionError("LEAK: behaviour crossed the boundary")

        class Adapter3(Adapter):
            def get_position(self, symbol=""):
                return Returned()

        c = CAP.read_only(Adapter3(), label="t")
        got = c.get_position()
        assert got.value == 7, "data still crosses"
        for name in ("liquidate_contract", "wind_down",
                     "perfectly_innocent_helper"):
            with pytest.raises(CAP.TopstepXCapabilityDenied):
                getattr(got, name)

    def test_B30_a_returned_object_holding_the_raw_client_is_no_escape(self):
        """THE SIX-MONTHS-FROM-NOW SHAPE. `_require()` becomes
        `SessionContext(client=raw_client, ...)` and nobody notices, because the
        outer allowlist is still perfectly correct."""
        class RawClient:
            def close_position(self, *a):
                raise AssertionError("LEAK: reached the live client")

        class SessionContext:
            client = RawClient()
            session_id = "PRAC-20260826"

        class Adapter4(Adapter):
            def _require(self):
                return SessionContext(), SessionContext()

        c = CAP.read_only(Adapter4(), label="t")
        ctx, _ = c._require()
        assert ctx.session_id == "PRAC-20260826", "data still crosses"
        assert isinstance(ctx.client, CAP.TopstepXDataView)
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            ctx.client.close_position

    def test_the_guard_is_structural_not_a_name_scan(self):
        import inspect
        src = inspect.getsource(CAP.TopstepXDataView.__getattr__)
        assert "callable(got)" in src
        for vocabulary in ("MUTATIONS", "REFUSED_OPERATIONS", "close_position",
                           "place_order"):
            assert vocabulary not in src,                 "no name vocabulary may govern the return boundary"

    def test_a_data_view_cannot_be_widened_by_assignment(self):
        account, _ = cap()._require()
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            account.close_position = lambda *a: "MUTATED"


# ══ B31-B35  THE WRAPPER ITSELF ═════════════════════════════════════════════
class TestWrapperSelfEscape:
    """A GUARD THAT RETURNS ITS OWN BACKING OBJECT GUARDS NOTHING.

    Found during certification of this very unit, and it was real:

        capability._obj._client.close_position(...)      ->  MUTATED

    `__getattr__` runs only when normal lookup FAILS, and `__slots__` installs
    real descriptors on the class -- so `_obj` resolved through ordinary
    attribute lookup and the policy never ran. Every RETURNED object was
    recursively guarded while the front door stood open.

    SCOPE, STATED HONESTLY. This is not a defence against hostile reflection
    inside one interpreter: `object.__getattribute__`, `gc`, `ctypes` and name
    mangling all remain, and a Python object graph is not a security boundary
    against code sharing its process. The theorem is narrower and mechanically
    real:

        NORMAL APPLICATION-LEVEL ATTRIBUTE ACCESS THROUGH A CAPABILITY CANNOT
        RECOVER THE BACKING ADAPTER OR CLIENT.
    """

    @pytest.mark.parametrize("internal", sorted(CAP.WRAPPER_INTERNALS))
    def test_B31_B32_the_capability_refuses_its_own_internals(self, internal):
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            getattr(cap(), internal)

    def test_B33_the_capability_yields_no_instance_dict(self):
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            cap().__dict__

    @pytest.mark.parametrize("internal", ["_obj", "_label", "__dict__",
                                          "__wrapped__", "_wrapped", "_target"])
    def test_B34_a_nested_data_view_refuses_its_backing_object(self, internal):
        account, _ = cap()._require()
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            getattr(account, internal)

    def test_B34_a_nested_client_capability_refuses_its_backing_object(self):
        client = cap()._client
        assert client.query_orders(), "the granted read still works"
        for internal in ("_obj", "_surface", "_label"):
            with pytest.raises(CAP.TopstepXCapabilityDenied):
                getattr(client, internal)

    def test_B35_no_granted_read_is_a_helper_that_returns_the_source(self):
        """Every name on the granted surface must yield DATA or a further
        controlled capability -- never the unwrapped adapter or client."""
        raw_types = set()

        class Marked:
            pass

        class Adapter5(Adapter):
            def get_position(self, symbol=""):
                return self          # a helper handing back the source

        c = CAP.read_only(Adapter5(), label="t")
        got = c.get_position()
        assert isinstance(got, CAP.TopstepXDataView), type(got)
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            got.submit_order          # behaviour, refused as behaviour
        assert not raw_types

    def test_the_backing_adapter_is_not_reachable_by_any_granted_name(self):
        """THE WHOLE THEOREM, swept. No granted name -- called or read --
        returns the raw adapter or the raw client."""
        raw_adapter_type, raw_client_type = Adapter, Adapter._Client
        c = cap()
        for name in sorted(CAP.ADAPTER_READS):
            value = getattr(c, name)
            got = value() if callable(value) and name != "_client" else value
            for row in (got if isinstance(got, tuple) else (got,)):
                assert not isinstance(row, raw_adapter_type), name
                assert not isinstance(row, raw_client_type), name

    def test_the_factory_facade_refuses_its_own_backing_capability(self):
        a = get_adapter(broker="topstepx")
        for internal in ("_capability", "_config"):
            with pytest.raises(CAP.TopstepXCapabilityDenied):
                getattr(a, internal)

    def test_the_facade_still_serves_its_granted_reads(self):
        """Closing the door must not lock the facade out of its own
        capability -- its methods reach it deliberately, not publicly."""
        a = get_adapter(broker="topstepx")
        assert a.name == "topstepx"
        assert a.describe()["order_authority"] is False

    def test_getattribute_is_what_holds_the_boundary(self):
        """Bound structurally: `__getattr__` alone cannot hold it, because a
        slot descriptor never fails lookup."""
        import inspect
        for cls in (CAP.TopstepXReadCapability, CAP.TopstepXDataView):
            assert "__getattribute__" in vars(cls), cls.__name__
            src = inspect.getsource(cls.__getattribute__)
            assert "_refuse_internals" in src
            # BLANKET, not a name list: every private name is routed to the
            # policy, and the policy refuses the wrapper's own __slots__ as a
            # class -- so a slot added tomorrow is covered without an edit.
            assert 'name.startswith("_")' in src
        policy = inspect.getsource(CAP._refuse_internals)
        assert "__slots__" in policy and "__mro__" in policy

    def test_a_future_slot_is_covered_without_an_edit(self):
        """The denylist-one-layer-in failure mode: a backing slot added to a
        wrapper tomorrow and forgotten in `WRAPPER_INTERNALS`."""
        class Future(CAP.TopstepXReadCapability):
            __slots__ = ("_secret_backdoor",)

        f = Future(Adapter(), CAP.ADAPTER_READS, "probe")
        object.__setattr__(f, "_secret_backdoor", Adapter())
        assert "_secret_backdoor" not in CAP.WRAPPER_INTERNALS
        with pytest.raises(CAP.TopstepXCapabilityDenied):
            f._secret_backdoor

    def test_any_private_name_is_refused(self):
        for name in ("_anything", "_x", "_client_secret", "_creds"):
            with pytest.raises(CAP.TopstepXCapabilityDenied):
                getattr(cap(), name)
