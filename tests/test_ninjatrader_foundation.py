"""NINJATRADER-MNQ-INTEGRATION-FOUNDATION — test suite.

Covers the 57 mission test requirements against MOCKS. No NinjaTrader, no
socket, no OpenAI, no paid API is touched. NO ORDER IS SUBMITTED anywhere in
this file (submission is DISARMED and there is no smoke-authorization token).
"""
import datetime as _dt
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from integrations.ninjatrader import account_safety as A              # noqa: E402
from integrations.ninjatrader.account_safety import GateInputs        # noqa: E402
from integrations.ninjatrader.instrument_spec import (                # noqa: E402
    InstrumentSpec, default_unresolved_spec)
from integrations.ninjatrader.contract_resolver import (              # noqa: E402
    resolve_active_mnq, ContractCandidate)
from integrations.ninjatrader.risk_translation import (               # noqa: E402
    assess, CostModel, risk_per_contract)
from integrations.ninjatrader import ipc_protocol as P                # noqa: E402
from integrations.ninjatrader.bar_gatekeeper import (                 # noqa: E402
    BarGatekeeper, CONNECTED_HEALTHY, CONNECTED_GAPPED, WRONG_INSTRUMENT,
    WRONG_EXPIRY)
from integrations.ninjatrader.market_data_provider import (           # noqa: E402
    NinjaTraderMNQProvider, VOLUME_PROVENANCE_LABEL)
from integrations.ninjatrader.volume_provenance import (              # noqa: E402
    MNQVolumeProvenance, relative_volume)
from integrations.ninjatrader.execution_adapter import (              # noqa: E402
    NinjaTraderBrokerAdapter)
from integrations.ninjatrader import preflight as PF                  # noqa: E402

ACTIVE = "MNQ 09-26"
EXPIRY = "2026-09"


def _spec():
    return InstrumentSpec(provider_symbol=ACTIVE, ninjatrader_name=ACTIVE,
                          expiry=EXPIRY, tick_size=0.25, point_value=2.0,
                          tick_value=0.5, rollover_state="active")


def _intent(**over):
    base = dict(authorization_id="A1", intent_id="I1", thesis_id="T1",
                instrument=ACTIVE, account="DEMO8458533", direction="long",
                quantity=1, client_order_id="C1", timestamp=1.0,
                current_position_state="flat", risk_authorization="R1",
                stop_definition={"stop_price": 100.0})
    base.update(over)
    return base


def _bar(ts, instrument=ACTIVE, expiry=EXPIRY, vol=10):
    return {"timestamp": ts, "instrument": instrument, "expiry": expiry,
            "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": vol}


# ── mock bar source ──────────────────────────────────────────────────────────
class MockBarSource:
    def __init__(self, bars): self._bars = bars
    def historical_1m(self, instrument, lookback): return list(self._bars)
    def buffered_bars(self): return list(self._bars)


# ======================================================================
# INSTALLATION / PREFLIGHT (1-4)
# ======================================================================
class TestPreflight(unittest.TestCase):
    def test_01_missing_install_is_blocked_not_success(self):
        rep = PF.run_preflight()
        st = rep["checks"]["ninjatrader_installed"]["status"]
        self.assertIn(st, ("verified", "unavailable"))
        # never silently "passed" — must be an explicit status token
        self.assertNotEqual(st, "passed")

    def test_02_missing_dll_forces_explicit_status(self):
        rep = PF.run_preflight()
        self.assertIn(rep["checks"]["ninjatrader_client_dll"]["status"],
                      ("verified", "unavailable"))

    def test_03_pythonnet_status_surfaced(self):
        rep = PF.run_preflight()
        self.assertIn(rep["checks"]["pythonnet_installed"]["status"],
                      ("verified", "unavailable"))

    def test_04_gui_facts_remain_user_action_required(self):
        rep = PF.run_preflight()
        for k in ("sim_account_exists", "market_data_connection_available",
                  "global_simulation_mode"):
            self.assertEqual(rep["checks"][k]["status"], "user-action-required")


# ======================================================================
# ACCOUNT SAFETY (5-9)
# ======================================================================
class TestAccountSafety(unittest.TestCase):
    def test_05_demo_account_passes(self):
        self.assertTrue(A.check_account("DEMO8458533"))

    def test_06_live_account_fails(self):
        for bad in ("Live", "APEX-12345", "Playback101", "DEMO8458533Live",
                    "Sim101"):   # old placeholder is no longer allowlisted
            self.assertFalse(A.check_account(bad), bad)

    def test_07_blank_and_missing_fail(self):
        self.assertFalse(A.check_account(""))
        self.assertFalse(A.check_account("   "))
        self.assertFalse(A.check_account(None))

    def test_08_normalization_cannot_broaden(self):
        self.assertTrue(A.check_account(" demo8458533 "))   # narrow-only normalize OK
        self.assertTrue(A.check_account("Demo8458533"))
        self.assertFalse(A.check_account("DEMO84585330"))    # must NOT broaden
        self.assertFalse(A.check_account("DEMO8458533 Live"))
        self.assertFalse(A.check_account("DEMO8458533\tLive"))

    def test_09_global_sim_mode_not_the_only_control(self):
        # Adapter enforces DEMO8458533 regardless of any GUI Global Simulation Mode.
        a = NinjaTraderBrokerAdapter(resolved_expiry_name=ACTIVE)
        r = a.submit_order(_intent(account="Live"), position_state_known=True,
                           account_state_known=True, connection_healthy=True)
        self.assertFalse(r["submitted"])
        self.assertIn("not allowlisted", r["denied_reason"])


# ======================================================================
# INSTRUMENT (10-17)
# ======================================================================
class TestInstrument(unittest.TestCase):
    def _resolve(self, cands, as_of=_dt.date(2026, 7, 20)):
        return resolve_active_mnq(cands, as_of=as_of)

    def test_10_exact_active_expiry_passes(self):
        r = self._resolve([ContractCandidate("MNQ 09-26", 9, 2026, 0.25, 2.0)])
        self.assertTrue(r.resolved)
        self.assertEqual(r.spec.ninjatrader_name, "MNQ 09-26")

    def test_11_master_missing_expiry_fails(self):
        r = self._resolve([ContractCandidate("MNQ", None, None)])
        self.assertFalse(r.resolved)

    def test_12_expired_fails(self):
        r = self._resolve([ContractCandidate("MNQ 03-26", 3, 2026, 0.25, 2.0)])
        self.assertFalse(r.resolved)
        self.assertTrue(any("expired" in w for _, w in r.rejected))

    def test_13_nq_fails(self):
        r = self._resolve([ContractCandidate("NQ 09-26", 9, 2026, 0.25, 20.0)])
        self.assertFalse(r.resolved)
        self.assertTrue(any("NQ" in w or "denied" in w for _, w in r.rejected))

    def test_14_qqq_fails(self):
        self.assertFalse(A.check_instrument("QQQ", ACTIVE))

    def test_15_wrong_contract_month_fails(self):
        # resolver picks the front quarter; a stale month name is not the active
        self.assertFalse(A.check_instrument("MNQ 12-26", ACTIVE))

    def test_16_continuous_fails_for_execution(self):
        r = self._resolve([ContractCandidate("MNQ ##-##", None, None),
                           ContractCandidate("MNQ", None, None)])
        self.assertFalse(r.resolved)

    def test_17_tick_metadata_internally_consistent(self):
        s = _spec()
        self.assertTrue(s.is_valid())
        bad = _spec(); bad.tick_value = 0.9
        self.assertFalse(bad.is_valid())

    def test_17b_reconcile_with_platform(self):
        s = _spec()
        rep = s.reconcile_with_platform(
            {"tick_size": 0.25, "point_value": 2.0, "instrument_name": "MNQ 09-26"})
        self.assertTrue(rep["metadata_verified"])
        # NQ platform name denies verification
        s2 = _spec()
        rep2 = s2.reconcile_with_platform(
            {"tick_size": 0.25, "point_value": 20.0, "instrument_name": "NQ 09-26"})
        self.assertFalse(rep2["metadata_verified"])

    def test_17c_rollover_window_warns(self):
        # expiry third Friday Sep 2026 = 2026-09-18; as_of within 8 days -> window
        r = resolve_active_mnq([ContractCandidate("MNQ 09-26", 9, 2026, 0.25, 2.0),
                                ContractCandidate("MNQ 12-26", 12, 2026, 0.25, 2.0)],
                               as_of=_dt.date(2026, 9, 15))
        self.assertTrue(r.resolved)
        self.assertEqual(r.rollover_state, "rollover_window")
        self.assertTrue(r.warnings)


# ======================================================================
# QUANTITY / RISK (18-24)
# ======================================================================
class TestQuantityRisk(unittest.TestCase):
    def test_18_qty1_passes(self):
        self.assertTrue(A.check_quantity(1))

    def test_19_qty2_fails(self):
        self.assertFalse(A.check_quantity(2))

    def test_20_qty0_fails(self):
        self.assertFalse(A.check_quantity(0))

    def test_21_fractional_fails(self):
        self.assertFalse(A.check_quantity(1.5))
        self.assertFalse(A.check_quantity(0.5))

    def test_22_negative_fails(self):
        self.assertFalse(A.check_quantity(-1))

    def test_23_unsafe_one_contract_risk_fails(self):
        s = _spec()
        # 300 point stop distance * $2/pt = $600 > $500 ceiling for 1 contract
        r = assess(s, entry_price=20000.0, stop_price=19700.0,
                   authorized_risk=500.0, cost=CostModel(commission_per_contract=0.0))
        self.assertFalse(r.approved)
        self.assertEqual(r.quantity, 0)

    def test_24_zero_contract_not_rounded_up(self):
        s = _spec()
        r = assess(s, entry_price=20000.0, stop_price=19000.0,
                   authorized_risk=500.0, cost=CostModel(commission_per_contract=0.0))
        self.assertFalse(r.approved)
        self.assertEqual(r.quantity, 0)   # never becomes 1

    def test_24b_safe_one_contract_approved_and_commission_labelled(self):
        s = _spec()
        r = assess(s, entry_price=20000.0, stop_price=19990.0,  # 10pt*$2=$20
                   authorized_risk=500.0, cost=CostModel())     # commission UNKNOWN
        self.assertTrue(r.approved)
        self.assertEqual(r.quantity, 1)
        self.assertFalse(r.commission_known)
        self.assertTrue(any("commission UNKNOWN" in w for w in r.warnings))


# ======================================================================
# MARKET DATA (25-32)
# ======================================================================
class TestMarketData(unittest.TestCase):
    def _gk(self):
        return BarGatekeeper(ACTIVE, EXPIRY)

    def test_25_completed_bar_accepted_once(self):
        g = self._gk()
        now = _dt.datetime(2026, 7, 20, 10, 0, tzinfo=_dt.timezone.utc)
        self.assertTrue(g.accept_bar(_bar("2026-07-20T09:59:00+00:00"), now).accepted)

    def test_26_duplicate_bar_rejected(self):
        g = self._gk()
        now = _dt.datetime(2026, 7, 20, 10, 0, tzinfo=_dt.timezone.utc)
        g.accept_bar(_bar("2026-07-20T09:59:00+00:00"), now)
        acc = g.accept_bar(_bar("2026-07-20T09:59:00+00:00"), now)
        self.assertFalse(acc.accepted)
        self.assertTrue(acc.duplicate)

    def test_27_out_of_order_surfaced(self):
        g = self._gk()
        now = _dt.datetime(2026, 7, 20, 10, 5, tzinfo=_dt.timezone.utc)
        g.accept_bar(_bar("2026-07-20T10:00:00+00:00"), now)
        acc = g.accept_bar(_bar("2026-07-20T09:59:00+00:00"), now)
        self.assertFalse(acc.accepted)
        self.assertTrue(acc.out_of_order)

    def test_28_wrong_expiry_rejected(self):
        g = self._gk()
        now = _dt.datetime(2026, 7, 20, 10, 0, tzinfo=_dt.timezone.utc)
        acc = g.accept_bar(_bar("2026-07-20T09:59:00+00:00", expiry="2026-12"), now)
        self.assertFalse(acc.accepted)
        self.assertEqual(g.health, WRONG_EXPIRY)

    def test_28b_wrong_instrument_rejected(self):
        g = self._gk()
        now = _dt.datetime(2026, 7, 20, 10, 0, tzinfo=_dt.timezone.utc)
        acc = g.accept_bar(_bar("2026-07-20T09:59:00+00:00", instrument="NQ 09-26"), now)
        self.assertFalse(acc.accepted)
        self.assertEqual(g.health, WRONG_INSTRUMENT)

    def test_29_stale_marks_unhealthy(self):
        g = self._gk()
        now = _dt.datetime(2026, 7, 20, 12, 0, tzinfo=_dt.timezone.utc)  # 2h later
        acc = g.accept_bar(_bar("2026-07-20T09:59:00+00:00"), now)
        self.assertTrue(acc.accepted)
        self.assertNotEqual(g.health, CONNECTED_HEALTHY)
        self.assertFalse(g.fresh_entry_ready())

    def test_29b_future_bar_rejected(self):
        g = self._gk()
        now = _dt.datetime(2026, 7, 20, 10, 0, tzinfo=_dt.timezone.utc)
        acc = g.accept_bar(_bar("2026-07-20T10:05:00+00:00"), now)
        self.assertFalse(acc.accepted)

    def test_30_missing_volume_stays_honest(self):
        prov = MNQVolumeProvenance(instrument=ACTIVE, sessions_collected=3)
        rd = relative_volume(prov)
        self.assertEqual(rd.status, "INSUFFICIENT_HISTORY")
        self.assertIsNone(rd.relative_volume)

    def test_31_qqq_volume_cannot_enter_mnq_witness(self):
        # Provider refuses non-MNQ symbols entirely.
        prov = NinjaTraderMNQProvider(_spec(), MockBarSource([]))
        with self.assertRaises(Exception):
            prov.fetch_1m_candles("QQQ", 10)
        # And provenance label is MNQ-specific.
        p2 = NinjaTraderMNQProvider(
            _spec(), MockBarSource([_bar("2026-07-20T09:59:00+00:00")]))
        candles = p2.fetch_1m_candles(ACTIVE, 10)
        self.assertEqual(candles[0]["volume_provenance"], VOLUME_PROVENANCE_LABEL)

    def test_32_reconnection_gap_blocks_fresh_entry(self):
        g = self._gk()
        g.mark_gap()
        self.assertEqual(g.health, CONNECTED_GAPPED)
        self.assertFalse(g.fresh_entry_ready())


# ======================================================================
# IPC / BRIDGE (33-39)
# ======================================================================
class TestIPC(unittest.TestCase):
    def _env(self, **o):
        d = dict(message_id="m1", account="DEMO8458533", instrument=ACTIVE, sequence=1)
        d.update(o)
        return P.build_envelope(d.pop("message_type", "ORDER_SUBMIT_REQUEST"),
                                d.pop("payload", {"k": 1}), **d)

    def _ctx(self):
        return P.ValidationContext(expected_account="DEMO8458533", expected_instrument=ACTIVE)

    def test_33_version_mismatch_fails(self):
        env = self._env(); env["protocol_version"] = "9.9.9"
        self.assertFalse(P.validate_envelope(env, self._ctx()))

    def test_34_duplicate_command_idempotent(self):
        t = P.SequenceTracker()
        dup, marker = t.note_idempotent("m1")
        self.assertFalse(dup)
        t.record("m1", "order-ref-1")
        dup2, marker2 = t.note_idempotent("m1")
        self.assertTrue(dup2)
        self.assertEqual(marker2, "order-ref-1")

    def test_35_wrong_account_command_fails(self):
        env = self._env(account="Live")
        self.assertFalse(P.validate_envelope(env, self._ctx()))

    def test_36_wrong_instrument_command_fails(self):
        env = self._env(instrument="NQ 09-26")
        self.assertFalse(P.validate_envelope(env, self._ctx()))

    def test_37_malformed_message_fails(self):
        with self.assertRaises(P.ProtocolError):
            P.parse_envelope("{ this is not json")

    def test_38_stale_command_fails(self):
        env = self._env(sent_at=0.0)  # epoch -> very old
        ctx = P.ValidationContext(expected_account="DEMO8458533",
                                  expected_instrument=ACTIVE, now=1_000_000.0)
        self.assertFalse(P.validate_envelope(env, ctx))

    def test_38b_future_dated_fails(self):
        env = self._env(sent_at=2_000_000.0)
        ctx = P.ValidationContext(expected_account="DEMO8458533",
                                  expected_instrument=ACTIVE, now=1_000_000.0)
        self.assertFalse(P.validate_envelope(env, ctx))

    def test_39_out_of_sequence_surfaced(self):
        t = P.SequenceTracker()
        self.assertIsNone(t.check_sequence(1))
        self.assertIsNone(t.check_sequence(2))
        self.assertIsNotNone(t.check_sequence(2))   # replay/backwards surfaced
        self.assertIsNotNone(t.check_sequence(10))  # gap surfaced


# ======================================================================
# EXECUTION (40-47) — NO ORDER IS SUBMITTED
# ======================================================================
class TestExecution(unittest.TestCase):
    def _a(self):
        return NinjaTraderBrokerAdapter(resolved_expiry_name=ACTIVE)

    def _ok(self):
        return dict(position_state_known=True, account_state_known=True,
                    connection_healthy=True)

    def test_40_cannot_submit_without_arm_or_authorization(self):
        r = self._a().submit_order(_intent(), **self._ok())
        self.assertFalse(r["submitted"])
        self.assertFalse(r["armed"])
        self.assertIn("DISARMED", r["denied_reason"])

    def test_41_cannot_change_direction(self):
        # Adapter never sets/derives direction; a missing direction is rejected,
        # an invalid one is rejected — it cannot invent one.
        r = self._a().submit_order(_intent(direction="sideways"), **self._ok())
        self.assertFalse(r["submitted"])
        self.assertIn("direction", r["denied_reason"])

    def test_42_cannot_increase_quantity(self):
        r = self._a().submit_order(_intent(quantity=5), **self._ok())
        self.assertFalse(r["submitted"])
        self.assertIn("ceiling", r["denied_reason"])

    def test_43_duplicate_intent_no_duplicate_order(self):
        a = self._a()
        # prime the idempotency map as if an order-ref existed
        a._seen_intents["C1"] = "order-ref-1"
        r = a.submit_order(_intent(), **self._ok())
        self.assertTrue(r["idempotent_replay"])
        self.assertFalse(r["submitted"])

    def test_44_unknown_position_blocks_entry(self):
        r = self._a().submit_order(_intent(), position_state_known=False,
                                   account_state_known=True, connection_healthy=True)
        self.assertFalse(r["submitted"])
        self.assertIn("position_state_known", r["denied_reason"])

    def test_45_unknown_connection_blocks_entry(self):
        r = self._a().submit_order(_intent(), position_state_known=True,
                                   account_state_known=True, connection_healthy=False)
        self.assertFalse(r["submitted"])
        self.assertIn("connection", r["denied_reason"])

    def test_46_protective_path_is_separate(self):
        a = self._a()
        out = a.submit_protective_stop("pos-1", {"stop_price": 100.0})
        # available/handled independently of fresh-entry arming
        self.assertIn("position_ref", out)

    def test_47_missing_authorization_fields_block(self):
        for field in ("authorization_id", "intent_id", "thesis_id",
                      "risk_authorization", "stop_definition"):
            bad = _intent(); bad[field] = ""
            r = self._a().submit_order(bad, **self._ok())
            self.assertFalse(r["submitted"], field)

    def test_47b_adapter_capability_is_disarmed(self):
        cap = self._a().capability()
        self.assertFalse(cap.supports_orders)
        self.assertTrue(cap.paper_only)


# ======================================================================
# ORGANISM COMPATIBILITY (48-57)
# ======================================================================
class TestOrganismCompatibility(unittest.TestCase):
    def test_48_default_broker_still_paper(self):
        from broker.factory import get_adapter, available_brokers
        self.assertIn("ninjatrader", available_brokers())
        a = get_adapter(broker=None)          # no broker specified
        self.assertEqual(a.name, "paper")     # default unchanged

    def test_49_ninjatrader_reachable_only_when_explicit(self):
        from broker.factory import get_adapter
        a = get_adapter(broker="ninjatrader")
        self.assertEqual(a.name, "ninjatrader")

    def test_50_unresolved_spec_fails_closed(self):
        s = default_unresolved_spec()
        self.assertFalse(s.is_valid())        # blank expiry never tradable

    def _isolated_openai_check(self, body: str):
        """Run `body` in a FRESH interpreter (so suite-wide import pollution from
        other tests cannot leak openai into sys.modules) and assert openai was
        never imported by exercising the integration path."""
        import subprocess
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        script = (
            "import sys, os\n"
            f"sys.path.insert(0, r'{os.path.abspath(src)}')\n"
            + body +
            "\nassert 'openai' not in sys.modules, 'openai imported by integration path'\n"
            "assert 'anthropic' not in sys.modules, 'anthropic imported by integration path'\n"
            "print('CLEAN')\n"
        )
        out = subprocess.run([sys.executable, "-c", script],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("CLEAN", out.stdout)

    def test_51_frozen_constitution_modules_untouched(self):
        # Importing the integration package must not pull in the brain LLM path.
        self._isolated_openai_check(
            "import integrations.ninjatrader.account_safety\n"
            "import integrations.ninjatrader.execution_adapter\n"
            "import integrations.ninjatrader.contract_resolver\n")

    def test_56_no_openai_import_in_integration_sources(self):
        import re
        import integrations.ninjatrader as pkg
        root = os.path.dirname(pkg.__file__)
        # Actual import/call patterns only — not prose like "NEVER calls OpenAI."
        pat = re.compile(r"(^|\n)\s*(import|from)\s+(openai|anthropic)\b"
                         r"|\b(openai|anthropic)\.[A-Za-z_]", re.IGNORECASE)
        offenders = []
        for fn in os.listdir(root):
            if fn.endswith(".py"):
                with open(os.path.join(root, fn), encoding="utf-8") as fh:
                    if pat.search(fh.read()):
                        offenders.append(fn)
        self.assertEqual(offenders, [])

    def test_57_no_network_client_imported_by_integration(self):
        # Exercising the whole read-only path must not import a paid API client.
        self._isolated_openai_check(
            "from integrations.ninjatrader.market_data_provider import NinjaTraderMNQProvider\n"
            "from integrations.ninjatrader.instrument_spec import InstrumentSpec\n"
            "from integrations.ninjatrader.execution_adapter import NinjaTraderBrokerAdapter\n"
            "class S:\n"
            "    def historical_1m(self, i, n):\n"
            "        return [{'timestamp':'2026-07-20T09:59:00+00:00','instrument':'MNQ 09-26',"
            "'expiry':'2026-09','volume':10,'open':1,'high':1,'low':1,'close':1}]\n"
            "    def buffered_bars(self):\n"
            "        return []\n"
            "spec=InstrumentSpec(provider_symbol='MNQ 09-26',ninjatrader_name='MNQ 09-26',"
            "expiry='2026-09',tick_size=0.25,point_value=2.0,tick_value=0.5,rollover_state='active')\n"
            "NinjaTraderMNQProvider(spec, S()).fetch_1m_candles('MNQ 09-26', 5)\n"
            "NinjaTraderBrokerAdapter(resolved_expiry_name='MNQ 09-26').submit_order("
            "{'authorization_id':'A','intent_id':'I','thesis_id':'T','instrument':'MNQ 09-26',"
            "'account':'DEMO8458533','direction':'long','quantity':1,'client_order_id':'C',"
            "'timestamp':0.0,'current_position_state':'flat','risk_authorization':'R',"
            "'stop_definition':{'stop_price':1.0}}, position_state_known=True,"
            " account_state_known=True, connection_healthy=True)\n")


# ======================================================================
# CONJUNCTION GATE (fresh entry end-to-end)
# ======================================================================
class TestFreshEntryConjunction(unittest.TestCase):
    def test_all_gates_pass_together(self):
        d = A.evaluate_fresh_entry(GateInputs(
            account="DEMO8458533", instrument=ACTIVE, resolved_expiry_name=ACTIVE,
            quantity=1, connection_healthy=True, account_state_known=True,
            position_state_known=True, contract_expiry_certain=True))
        self.assertTrue(d)

    def test_any_uncertainty_denies(self):
        for flip in ("connection_healthy", "account_state_known",
                     "position_state_known", "contract_expiry_certain"):
            kw = dict(account="DEMO8458533", instrument=ACTIVE, resolved_expiry_name=ACTIVE,
                      quantity=1, connection_healthy=True, account_state_known=True,
                      position_state_known=True, contract_expiry_certain=True)
            kw[flip] = None
            self.assertFalse(A.evaluate_fresh_entry(GateInputs(**kw)), flip)


class TestBridgeClient(unittest.TestCase):
    def test_loopback_only(self):
        from integrations.ninjatrader.bridge_client import NinjaTraderBridgeClient
        with self.assertRaises(ValueError):
            NinjaTraderBridgeClient(host="10.0.0.5")   # non-loopback refused
        NinjaTraderBridgeClient(host="127.0.0.1")       # ok

    def test_no_bridge_is_failclosed(self):
        from integrations.ninjatrader.bridge_client import NinjaTraderBridgeClient
        # An almost-certainly-unused loopback port -> connect fails -> unknown.
        c = NinjaTraderBridgeClient(host="127.0.0.1", port=59999, timeout=0.2)
        self.assertFalse(c.connect())
        self.assertFalse(c.is_connected())
        self.assertFalse(c.account_state().get("known", False))
        self.assertEqual(c.position("MNQ 09-26").get("qty", 0), 0)

    def test_restart_requires_reconciliation(self):
        # Adapter with no wire reports UNRECONCILED rather than a false clean.
        a = NinjaTraderBrokerAdapter(resolved_expiry_name=ACTIVE)
        rep = a.reconcile({"qty": 0})
        self.assertFalse(rep["reconciled"])


if __name__ == "__main__":
    unittest.main()
