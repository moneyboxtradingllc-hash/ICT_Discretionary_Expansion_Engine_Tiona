"""
Phase 5H — Rule Governance test suite.

5H.1 — Predicate library + Candidate Rule Registry
(5H.2-5H.4 test classes are appended in later sub-phases.)
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rule_governance.predicates import (
    PREDICATES,
    get_predicate,
    predicate_exists,
    regime_environmental_compound_v1,
    delivery_continuation_objection_v1,
    reversal_without_evidence_v1,
)
from rule_governance.rule_registry import (
    load_registry,
    active_rules,
    validate_record,
    transition_rule,
    rules_near_review,
    registry_path,
)

_REAL_REGISTRY = os.path.join(
    os.path.dirname(__file__), "..", "data", "rule_governance", "registry.json",
)


def _ctx(**overrides):
    base = {
        "regime": "trend_up", "volatility_state": "stable",
        "expansion_state": "expanding", "exhaustion_present": False,
        "reversal_present": False, "continuation_intact": True,
        "delivery_state": "bullish_delivery", "delivery_confidence": 85,
        "playbook": "trend_continuation",
    }
    base.update(overrides)
    return base


def _record(**overrides):
    rec = {
        "rule_id": "R-TEST", "name": "test_rule",
        "predicate_id": "regime_environmental_compound_v1",
        "sponsor": "REGIME", "rule_class": "blocking_candidate",
        "status": "shadow", "created": "2026-06-10",
        "review_by": "2026-07-10", "scope": ["QQQ"],
        "evidence_refs": [], "notes": "",
    }
    rec.update(overrides)
    return rec


# ══════════════════════════════════════════════════════════════════════════════
# 5H.1 — Predicates
# ══════════════════════════════════════════════════════════════════════════════

class TestPredicates(unittest.TestCase):

    # R-001 ─ regime_environmental_compound
    def test_r001_fires_on_two_hostile_conditions(self):
        fired, reason = regime_environmental_compound_v1(
            _ctx(regime="range_rotation", exhaustion_present=True))
        self.assertTrue(fired)
        self.assertIn("compound hostility (2)", reason)

    def test_r001_fires_on_three_hostile_conditions(self):
        fired, reason = regime_environmental_compound_v1(
            _ctx(regime="chop", exhaustion_present=True,
                 volatility_state="unstable"))
        self.assertTrue(fired)
        self.assertIn("(3)", reason)

    def test_r001_abstains_on_single_hostile_condition(self):
        fired, reason = regime_environmental_compound_v1(
            _ctx(regime="range_rotation"))
        self.assertFalse(fired)
        self.assertIn("= 1", reason)

    def test_r001_abstains_in_healthy_trend(self):
        fired, _ = regime_environmental_compound_v1(_ctx())
        self.assertFalse(fired)

    # R-002 ─ delivery_continuation_objection
    def test_r002_fires_on_broken_delivery_continuation(self):
        fired, reason = delivery_continuation_objection_v1(
            _ctx(playbook="trend_continuation", continuation_intact=False,
                 delivery_state="mixed", delivery_confidence=25))
        self.assertTrue(fired)
        self.assertIn("broken delivery", reason)

    def test_r002_abstains_on_reversal_playbook(self):
        fired, reason = delivery_continuation_objection_v1(
            _ctx(playbook="liquidity_sweep_reversal", continuation_intact=False,
                 delivery_state="mixed", delivery_confidence=10))
        self.assertFalse(fired)
        self.assertIn("not continuation-family", reason)

    def test_r002_never_fires_on_missing_data(self):
        fired, reason = delivery_continuation_objection_v1(
            _ctx(playbook="trend_continuation", continuation_intact=False,
                 delivery_state="unknown", delivery_confidence=0))
        self.assertFalse(fired)
        self.assertIn("missing data never fires", reason)

    def test_r002_abstains_on_healthy_delivery(self):
        fired, _ = delivery_continuation_objection_v1(_ctx())
        self.assertFalse(fired)

    # R-003 ─ reversal_without_evidence
    def test_r003_fires_on_reversal_without_evidence(self):
        fired, reason = reversal_without_evidence_v1(
            _ctx(playbook="liquidity_sweep_reversal", reversal_present=False))
        self.assertTrue(fired)
        self.assertIn("without measured reversal evidence", reason)

    def test_r003_abstains_with_reversal_evidence(self):
        fired, reason = reversal_without_evidence_v1(
            _ctx(playbook="liquidity_sweep_reversal", reversal_present=True))
        self.assertFalse(fired)
        self.assertIn("evidence present", reason)

    def test_r003_abstains_on_continuation_playbook(self):
        fired, _ = reversal_without_evidence_v1(
            _ctx(playbook="trend_continuation", reversal_present=False))
        self.assertFalse(fired)

    # Library invariants
    def test_predicates_never_raise_and_never_fire_on_garbage(self):
        for pid, fn in PREDICATES.items():
            fired, reason = fn(None)
            self.assertFalse(fired, f"{pid} fired on None context")
            fired, reason = fn({"regime": 123, "delivery_confidence": "x",
                                "playbook": ["bad"]})
            self.assertFalse(fired, f"{pid} fired on garbage context")

    def test_library_lookup(self):
        self.assertTrue(predicate_exists("regime_environmental_compound_v1"))
        self.assertFalse(predicate_exists("nonexistent_v9"))
        self.assertIsNotNone(get_predicate("delivery_continuation_objection_v1"))
        self.assertIsNone(get_predicate("nonexistent_v9"))


# ══════════════════════════════════════════════════════════════════════════════
# 5H.1 — Registry
# ══════════════════════════════════════════════════════════════════════════════

class TestRegistryValidation(unittest.TestCase):

    def test_valid_shadow_record_passes(self):
        ok, reason = validate_record(_record())
        self.assertTrue(ok, reason)

    def test_missing_review_by_rejected(self):
        ok, reason = validate_record(_record(review_by=None))
        self.assertFalse(ok)
        self.assertIn("review_by", reason)

    def test_shadow_without_library_predicate_rejected(self):
        ok, reason = validate_record(_record(predicate_id="ghost_v1"))
        self.assertFalse(ok)
        self.assertIn("library predicate", reason)

    def test_local_sponsor_cannot_sponsor_blocking_rule(self):
        for sponsor in ("QUALIFICATION", "TOOLBOX"):
            ok, reason = validate_record(_record(sponsor=sponsor))
            self.assertFalse(ok, f"{sponsor} was allowed to sponsor a block")
            self.assertIn("annotations only", reason)

    def test_local_sponsor_may_sponsor_annotation(self):
        ok, reason = validate_record(_record(sponsor="TOOLBOX",
                                             rule_class="annotation"))
        self.assertTrue(ok, reason)

    def test_grandfathered_requires_enforcement_ref(self):
        rec = _record(status="grandfathered", predicate_id=None)
        ok, reason = validate_record(rec)
        self.assertFalse(ok)
        self.assertIn("enforcement_ref", reason)
        rec["enforcement_ref"] = "src/somewhere.py:law"
        ok, reason = validate_record(rec)
        self.assertTrue(ok, reason)

    def test_invalid_status_rejected(self):
        ok, reason = validate_record(_record(status="enforced"))
        self.assertFalse(ok)

    def test_empty_scope_rejected(self):
        ok, reason = validate_record(_record(scope=[]))
        self.assertFalse(ok)


class TestRegistryFile(unittest.TestCase):
    """Against a temp copy so transitions never touch the real law book."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name), exist_ok=True)
        with open(_REAL_REGISTRY, encoding="utf-8") as f:
            data = json.load(f)
        with open(os.path.join(self.tmp.name, "registry.json"), "w",
                  encoding="utf-8") as f:
            json.dump(data, f)
        os.environ["RULE_GOVERNANCE_DIR"] = self.tmp.name
        self.addCleanup(lambda: os.environ.pop("RULE_GOVERNANCE_DIR", None))

    def test_seeded_registry_loads_clean(self):
        reg = load_registry()
        self.assertTrue(reg["loaded"])
        self.assertEqual(reg["quarantined"], [])
        ids = {r["rule_id"] for r in reg["rules"]}
        self.assertTrue({"R-001", "R-002", "R-003"} <= ids)
        self.assertTrue(any(i.startswith("GF-5F-") for i in ids))

    def test_three_shadow_rules_active(self):
        shadow = active_rules("shadow")
        self.assertEqual({r["rule_id"] for r in shadow},
                         {"R-001", "R-002", "R-003"})

    def test_grandfather_records_cover_5f_laws(self):
        gf = active_rules("grandfathered")
        self.assertEqual(len(gf), 7)
        for rec in gf:
            self.assertTrue(rec.get("enforcement_ref"),
                            f"{rec['rule_id']} missing enforcement_ref")

    def test_legal_transition_shadow_to_retired(self):
        result = transition_rule("R-003", "retired", "reports/test_evidence.md")
        self.assertTrue(result["ok"], result["reason"])
        statuses = {r["rule_id"]: r["status"] for r in load_registry()["rules"]}
        self.assertEqual(statuses["R-003"], "retired")

    def test_illegal_transition_rejected(self):
        result = transition_rule("GF-5F-001", "shadow", "reports/x.md")
        self.assertFalse(result["ok"])
        self.assertIn("illegal transition", result["reason"])

    def test_retired_is_terminal(self):
        transition_rule("R-003", "retired", "reports/x.md")
        result = transition_rule("R-003", "promoted", "reports/y.md")
        self.assertFalse(result["ok"])

    def test_transition_requires_evidence_ref(self):
        result = transition_rule("R-001", "retired", "")
        self.assertFalse(result["ok"])
        self.assertIn("evidence_ref is mandatory", result["reason"])

    def test_transition_records_evidence(self):
        transition_rule("R-001", "retired", "reports/weekly_2026W24.md")
        rec = next(r for r in load_registry()["rules"]
                   if r["rule_id"] == "R-001")
        self.assertEqual(rec["evidence_refs"][-1]["ref"],
                         "reports/weekly_2026W24.md")
        self.assertEqual(rec["evidence_refs"][-1]["transition"],
                         "shadow->retired")

    def test_corrupt_record_quarantined_not_fatal(self):
        path = os.path.join(self.tmp.name, "registry.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["rules"].append({"rule_id": "R-BAD", "status": "shadow"})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        reg = load_registry()
        self.assertTrue(reg["loaded"])
        self.assertIn("R-BAD", [q[0] for q in reg["quarantined"]])
        self.assertNotIn("R-BAD", [r["rule_id"] for r in reg["rules"]])

    def test_missing_registry_file_never_raises(self):
        os.environ["RULE_GOVERNANCE_DIR"] = os.path.join(self.tmp.name, "ghost")
        reg = load_registry()
        self.assertFalse(reg["loaded"])
        self.assertEqual(reg["rules"], [])

    def test_rules_near_review_flags_seeds(self):
        near = rules_near_review(days=365)
        ids = {r["rule_id"] for r in near}
        self.assertTrue({"R-001", "R-002", "R-003"} <= ids)


# ══════════════════════════════════════════════════════════════════════════════
# 5H.2 — Shadow Evaluator
# ══════════════════════════════════════════════════════════════════════════════

def _shadow_snapshot(ctx_overrides=None, would_authorize=True,
                     executed=False, trade_id=None, intent_id="TI_1"):
    ctx = _ctx(**(ctx_overrides or {}))
    return {
        "shared_context": ctx,
        "execution_gate": {"would_authorize_if_enabled": would_authorize},
        "paper_execution": {
            "status": "submitted" if executed else "skipped",
            "trade_id": trade_id,
        },
        "trade_intent": {"intent_id": intent_id},
        "council": {"members": [
            {"member": "REGIME", "vote": "no", "confidence": 95,
             "reasons": [], "concerns": []},
        ]},
    }


class TestShadowEvaluator(unittest.TestCase):

    def setUp(self):
        # Point at the real seeded registry (read-only usage here)
        os.environ.pop("RULE_GOVERNANCE_DIR", None)
        os.environ["RULE_GOVERNANCE_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("RULE_GOVERNANCE_ENABLED", None))
        from rule_governance.shadow_evaluator import evaluate_shadow_rules
        self.evaluate = evaluate_shadow_rules

    def test_healthy_trend_fires_nothing(self):
        rg = self.evaluate(_shadow_snapshot(), "QQQ")
        self.assertTrue(rg["enabled"])
        self.assertEqual(rg["authority_level"], "observe_only")
        self.assertEqual(rg["fired"], [])
        self.assertEqual(rg["events"], [])
        self.assertEqual(rg["evaluated"], 3)   # R-001, R-002, R-003

    def test_compound_hostility_fires_r001_on_opportunity(self):
        rg = self.evaluate(_shadow_snapshot(
            {"regime": "range_rotation", "exhaustion_present": True}), "QQQ")
        self.assertIn("R-001", rg["fired"])
        self.assertEqual(len(rg["events"]), 1)
        ev = rg["events"][0]
        self.assertEqual(ev["rule_id"], "R-001")
        self.assertTrue(ev["opportunity"])
        self.assertEqual(ev["resolution"]["state"], "pending")
        self.assertEqual(ev["context_digest"]["regime"], "range_rotation")
        self.assertEqual(ev["council_digest"][0]["member"], "REGIME")

    def test_firing_without_opportunity_creates_no_event(self):
        rg = self.evaluate(_shadow_snapshot(
            {"regime": "range_rotation", "exhaustion_present": True},
            would_authorize=False), "QQQ")
        self.assertIn("R-001", rg["fired"])       # rate stats still tracked
        self.assertEqual(rg["events"], [])        # but not scoreable

    def test_executed_trade_linked_in_event(self):
        rg = self.evaluate(_shadow_snapshot(
            {"regime": "chop", "volatility_state": "toxic"},
            executed=True, trade_id="PT_QQQ_X"), "QQQ")
        self.assertTrue(rg["events"][0]["executed"])
        self.assertEqual(rg["events"][0]["trade_id"], "PT_QQQ_X")
        self.assertEqual(rg["events"][0]["intent_id"], "TI_1")

    def test_symbol_scope_respected(self):
        rg = self.evaluate(_shadow_snapshot(
            {"regime": "range_rotation", "exhaustion_present": True}), "SPY")
        self.assertEqual(rg["evaluated"], 0)      # seeds are scoped to QQQ
        self.assertEqual(rg["fired"], [])

    def test_disabled_by_env(self):
        os.environ["RULE_GOVERNANCE_ENABLED"] = "false"
        rg = self.evaluate(_shadow_snapshot(), "QQQ")
        self.assertFalse(rg["enabled"])
        self.assertEqual(rg["events"], [])

    def test_never_raises_on_garbage(self):
        rg = self.evaluate(None, "QQQ")
        self.assertEqual(rg["authority_level"], "observe_only")
        rg = self.evaluate({"shared_context": "garbage"}, "QQQ")
        self.assertIn("fired", rg)


class TestShadowIsolation(unittest.TestCase):
    """Constitutional invariant: no return path to execution."""

    def test_gate_output_identical_with_and_without_shadow_plane(self):
        import copy
        from execution_gate.execution_gate import evaluate_gate
        from rule_governance.shadow_evaluator import evaluate_shadow_rules

        os.environ["EXECUTION_ENABLED"] = "true"
        self.addCleanup(lambda: os.environ.pop("EXECUTION_ENABLED", None))

        snap = _shadow_snapshot({"regime": "range_rotation",
                                 "exhaustion_present": True})
        # Make the snapshot gate-evaluable
        snap.update({
            "decision_authority": {"decision": "ready_for_execution",
                                   "trade_authorized": False},
            "risk": {"trade_allowed": True},
            "state_transition": {"invalidated": False},
            "setup_lifecycle": {"active": True, "current_phase": "maturing",
                                "age_scans": 3},
            "ai_debate": {"final_verdict": {"recommended_stance": "prepare_long"}},
            "confidence_fusion": {"fusion_status": "agreement"},
            "toolbox": {"preferred_tool": "bullish_fvg", "tool_candidates": [{
                "tool": "bullish_fvg",
                "trigger_prep": {"execution_ready": True,
                                 "raw_trigger_status": "confirmed"},
            }]},
            "regime_permissions": {"enabled": True, "allowed": True,
                                   "required_trigger_status": "confirmed",
                                   "min_setup_age_scans": 2},
        })

        gate_before = evaluate_gate(copy.deepcopy(snap))
        snap["rule_governance"] = evaluate_shadow_rules(snap, "QQQ")
        gate_after = evaluate_gate(snap)
        self.assertEqual(gate_before, gate_after)

    def test_no_execution_module_imports_rule_governance(self):
        """Static check: execution-path modules must not import the shadow plane."""
        execution_path_files = [
            "src/execution_gate/execution_gate.py",
            "src/paper_execution/execution_engine.py",
            "src/paper_execution/order_builder.py",
            "src/decision_authority/decision_engine.py",
            "src/regime_authority/regime_permission_matrix.py",
            "src/risk/risk_governor.py",
        ]
        root = os.path.join(os.path.dirname(__file__), "..")
        for rel in execution_path_files:
            with open(os.path.join(root, rel), encoding="utf-8") as f:
                content = f.read()
            self.assertNotIn("rule_governance", content,
                             f"{rel} imports the shadow plane — constitutional violation")

    def test_no_enforce_flag_exists_anywhere_in_module(self):
        root = os.path.join(os.path.dirname(__file__), "..", "src", "rule_governance")
        for fname in os.listdir(root):
            if not fname.endswith(".py"):
                continue
            with open(os.path.join(root, fname), encoding="utf-8") as f:
                content = f.read().lower()
            self.assertNotIn("enforce_mode", content, f"{fname} contains an enforce flag")
            self.assertNotIn("allow_execution", content,
                             f"{fname} references execution permission")


# ══════════════════════════════════════════════════════════════════════════════
# 5H.3 — Divergence Ledger
# ══════════════════════════════════════════════════════════════════════════════

def _event(event_id="EV_1", rule_id="R-001", executed=False,
           trade_id=None, intent_id="INT_1", resolution=None):
    return {
        "event_id": event_id, "rule_id": rule_id,
        "predicate_version": "x_v1", "symbol": "QQQ",
        "timestamp": "20260610T120000", "fired": True,
        "fire_reason": "test", "opportunity": True,
        "executed": executed, "trade_id": trade_id, "intent_id": intent_id,
        "context_digest": {}, "council_digest": [],
        "resolution": resolution or {"state": "pending"},
    }


class TestDivergenceLedger(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["RULE_GOVERNANCE_DIR"] = self.tmp.name
        self.addCleanup(lambda: os.environ.pop("RULE_GOVERNANCE_DIR", None))
        from rule_governance import divergence_ledger as dl
        self.dl = dl

    def test_append_and_load(self):
        result = self.dl.append_events([_event("EV_A"), _event("EV_B")], "QQQ")
        self.assertTrue(result["ok"])
        self.assertEqual(result["appended"], 2)
        events = self.dl.load_events("QQQ", days=2)
        self.assertEqual({e["event_id"] for e in events}, {"EV_A", "EV_B"})

    def test_append_deduplicates_event_ids(self):
        self.dl.append_events([_event("EV_A")], "QQQ")
        result = self.dl.append_events([_event("EV_A"), _event("EV_C")], "QQQ")
        self.assertEqual(result["appended"], 1)
        self.assertEqual(len(self.dl.load_events("QQQ", days=2)), 2)

    def test_empty_append_is_noop(self):
        self.assertEqual(self.dl.append_events([], "QQQ"),
                         {"appended": 0, "ok": True})

    def test_resolution_from_closed_trade_fill(self):
        from unittest.mock import patch
        self.dl.append_events(
            [_event("EV_T", executed=True, trade_id="PT_X", intent_id=None)], "QQQ")
        fake_files = [("20260610", "f.json",
                       [{"trade_id": "PT_X", "realized_r": -0.96}])]
        with patch("paper_execution.trade_journal._search_recent_files",
                   return_value=fake_files):
            stats = self.dl.resolve_pending("QQQ")
        self.assertEqual(stats["resolved"], 1)
        ev = self.dl.load_events("QQQ", days=2)[0]
        self.assertEqual(ev["resolution"]["source"], "fill")
        self.assertEqual(ev["resolution"]["r"], -0.96)

    def test_open_trade_stays_pending(self):
        from unittest.mock import patch
        self.dl.append_events(
            [_event("EV_T", executed=True, trade_id="PT_X", intent_id=None)], "QQQ")
        fake_files = [("20260610", "f.json",
                       [{"trade_id": "PT_X", "realized_r": None}])]
        with patch("paper_execution.trade_journal._search_recent_files",
                   return_value=fake_files):
            stats = self.dl.resolve_pending("QQQ")
        self.assertEqual(stats["resolved"], 0)
        self.assertEqual(stats["still_pending"], 1)

    def _resolve_with_intent(self, intent):
        from unittest.mock import patch
        self.dl.append_events([_event("EV_I", intent_id="INT_1")], "QQQ")
        with patch.object(self.dl, "_find_intent", return_value=intent):
            self.dl.resolve_pending("QQQ")
        return self.dl.load_events("QQQ", days=2)[0]["resolution"]

    def test_proxy_resolution_sl_first(self):
        res = self._resolve_with_intent(
            {"first_threshold_crossed": "sl_1r", "status": "open"})
        self.assertEqual(res["r"], -1.0)
        self.assertEqual(res["source"], "proxy")

    def test_proxy_resolution_tp_first(self):
        res = self._resolve_with_intent(
            {"first_threshold_crossed": "tp_2r", "status": "open"})
        self.assertEqual(res["r"], 2.0)

    def test_legacy_proxy_mae_first_assumption(self):
        res = self._resolve_with_intent({
            "first_threshold_crossed": None,
            "risk_per_share_reference": 2.0,
            "mfe": 5.0, "mae": 2.5,        # both thresholds hit, order unknown
            "status": "open",
        })
        self.assertEqual(res["r"], -1.0)   # conservative: against the rule
        self.assertEqual(res["basis"], "legacy_mae_first_assumption")

    def test_expired_indeterminate_scores_zero(self):
        res = self._resolve_with_intent({
            "first_threshold_crossed": None,
            "risk_per_share_reference": 2.0,
            "mfe": 1.0, "mae": 0.5, "status": "expired",
        })
        self.assertEqual(res["r"], 0.0)
        self.assertTrue(res["low_confidence"])

    def test_open_intent_stays_pending(self):
        from unittest.mock import patch
        self.dl.append_events([_event("EV_I", intent_id="INT_1")], "QQQ")
        with patch.object(self.dl, "_find_intent", return_value={
            "first_threshold_crossed": None,
            "risk_per_share_reference": 2.0,
            "mfe": 1.0, "mae": 0.5, "status": "open",
        }):
            stats = self.dl.resolve_pending("QQQ")
        self.assertEqual(stats["still_pending"], 1)

    def test_resolution_is_idempotent(self):
        from unittest.mock import patch
        self.dl.append_events([_event("EV_I", intent_id="INT_1")], "QQQ")
        with patch.object(self.dl, "_find_intent", return_value={
            "first_threshold_crossed": "tp_2r", "status": "open",
        }):
            self.dl.resolve_pending("QQQ")
            stats2 = self.dl.resolve_pending("QQQ")
        self.assertEqual(stats2["checked"], 0)   # already resolved — skipped

    def test_never_raises_on_missing_ledger_dir(self):
        os.environ["RULE_GOVERNANCE_DIR"] = os.path.join(self.tmp.name, "ghost")
        self.assertEqual(self.dl.load_events("QQQ"), [])
        stats = self.dl.resolve_pending("QQQ")
        self.assertEqual(stats["resolved"], 0)


class TestIntentThresholdTracking(unittest.TestCase):
    """5H.3 outcome_tracker enhancement: first_threshold_crossed ordering."""

    def _snapshot(self, current_price, midpoint=100.0, invalidation=98.0):
        return {
            "trade_intent": {
                "intent_type": "long", "direction": "bullish",
                "intent_created": True,
                "entry_zone": {"midpoint": midpoint, "zone_low": 99.0,
                               "zone_high": 101.0},
            },
            "toolbox": {
                "preferred_tool": "bullish_fvg",
                "tool_candidates": [{
                    "tool": "bullish_fvg",
                    "price_level": {"midpoint": midpoint,
                                    "invalidation_level": invalidation,
                                    "current_price": current_price,
                                    "price_relation": "inside_zone"},
                    "trigger_prep": {"raw_trigger_status": "confirmation_needed"},
                }],
            },
        }

    def test_risk_per_share_reference_from_invalidation(self):
        from intent_archive.intent_archive import _risk_per_share_reference
        snap = self._snapshot(100.0)
        rps = _risk_per_share_reference(snap, snap["trade_intent"])
        self.assertEqual(rps, 2.0)   # |100 - 98|

    def test_risk_reference_zone_fallback(self):
        from intent_archive.intent_archive import _risk_per_share_reference
        snap = self._snapshot(100.0, invalidation=None)
        snap["toolbox"]["tool_candidates"][0]["price_level"]["invalidation_level"] = None
        rps = _risk_per_share_reference(snap, snap["trade_intent"])
        self.assertEqual(rps, 1.0)   # |100 - zone_low 99|

    def test_sl_crossed_first_is_recorded_and_sticky(self):
        from intent_archive.intent_archive import update_archive
        import intent_archive.intent_archive as ia
        with tempfile.TemporaryDirectory() as tmpdir:
            with unittest.mock.patch.object(ia, "_ARCHIVE_DIR", tmpdir):
                # Scan 1: create intent (price at midpoint)
                snap = self._snapshot(100.0)
                snap["intent_score"] = {"raw_score": 75, "gated_score": 75,
                                        "gated_quality": "strong_watch"}
                snap["setup_lifecycle"] = {"active": True, "setup_id": "S1"}
                snap["market_regime"] = {}
                update_archive(snap, "QQQ")
                # Scan 2: price drops 1R -> SL threshold first
                update_archive(self._snapshot(98.0), "QQQ")
                # Scan 3: price rockets past 2R -> must NOT overwrite
                update_archive(self._snapshot(105.0), "QQQ")

                path = ia._archive_filepath("QQQ")
                with open(path, encoding="utf-8") as f:
                    rec = json.load(f)["intents"][0]
        self.assertEqual(rec["risk_per_share_reference"], 2.0)
        self.assertEqual(rec["first_threshold_crossed"], "sl_1r")


# ══════════════════════════════════════════════════════════════════════════════
# 5H.4 — Scoring, Calibration, Reports
# ══════════════════════════════════════════════════════════════════════════════

def _resolved_event(rule_id="R-001", r=-1.0, source="proxy",
                    low_confidence=False, council=None):
    ev = _event(event_id=f"EV_{rule_id}_{r}_{id(object())}", rule_id=rule_id)
    ev["resolution"] = {"state": "resolved", "source": source, "r": r}
    if low_confidence:
        ev["resolution"]["low_confidence"] = True
    if council:
        ev["council_digest"] = council
    return ev


class TestRuleScoring(unittest.TestCase):

    def setUp(self):
        from rule_governance.rule_scoring import score_rule
        self.score = score_rule

    def test_protected_missed_net_math(self):
        events = [
            _resolved_event(r=-1.0), _resolved_event(r=-1.0),
            _resolved_event(r=2.0),
        ]
        card = self.score("R-001", events)
        self.assertEqual(card["protected_loss_R"], 2.0)
        self.assertEqual(card["missed_opportunity_R"], 2.0)
        self.assertEqual(card["net_protected_R"], 0.0)
        self.assertEqual(card["efficiency"], 0.5)

    def test_promotion_eligible_on_strong_record(self):
        events = (
            [_resolved_event(r=-1.0, source="fill") for _ in range(6)]
            + [_resolved_event(r=-1.0) for _ in range(12)]
            + [_resolved_event(r=2.0) for _ in range(2)]
        )
        card = self.score("R-001", events, opportunities_seen=100,
                          sessions_seen=25)
        self.assertEqual(card["events_resolved"], 20)
        promo = card["promotion"]
        self.assertTrue(promo["eligible"], promo["checks"])

    def test_promotion_blocked_by_small_sample(self):
        events = [_resolved_event(r=-1.0, source="fill") for _ in range(10)]
        card = self.score("R-001", events, opportunities_seen=50,
                          sessions_seen=25)
        self.assertFalse(card["promotion"]["eligible"])
        self.assertFalse(card["promotion"]["checks"]["sample_size"])

    def test_promotion_blocked_by_outlier_dependence(self):
        # One huge save, otherwise net-negative
        events = (
            [_resolved_event(r=-8.0, source="fill")]
            + [_resolved_event(r=2.0) for _ in range(3)]
            + [_resolved_event(r=-0.2, source="fill") for _ in range(16)]
        )
        card = self.score("R-001", events, opportunities_seen=100,
                          sessions_seen=25)
        self.assertGreater(card["net_protected_R"], 0)
        self.assertLess(card["net_excl_best_R"], 0)
        self.assertFalse(card["promotion"]["eligible"])
        self.assertFalse(card["promotion"]["checks"]["outlier_robust"])

    def test_promotion_blocked_by_fire_rate(self):
        events = [_resolved_event(r=-1.0, source="fill") for _ in range(20)]
        card = self.score("R-001", events, opportunities_seen=25,
                          sessions_seen=25)
        self.assertFalse(card["promotion"]["checks"]["fire_rate"])  # 20/25 = 0.8

    def test_demotion_flagged_on_negative_net(self):
        events = (
            [_resolved_event(r=2.0) for _ in range(8)]
            + [_resolved_event(r=-1.0) for _ in range(4)]
        )
        card = self.score("R-001", events)
        self.assertTrue(card["demotion"]["flagged"])
        self.assertTrue(card["demotion"]["checks"]["net_negative"])

    def test_demotion_needs_minimum_window(self):
        events = [_resolved_event(r=2.0) for _ in range(5)]
        card = self.score("R-001", events)
        self.assertFalse(card["demotion"]["flagged"])
        self.assertIn("insufficient window", card["demotion"]["note"])

    def test_other_rules_events_excluded(self):
        events = [_resolved_event(rule_id="R-002", r=-1.0) for _ in range(5)]
        card = self.score("R-001", events)
        self.assertEqual(card["events_total"], 0)

    def test_never_raises(self):
        card = self.score("R-001", [{"bad": "event"}, None])
        self.assertIn("rule_id", card)


class TestMemberCalibration(unittest.TestCase):

    def setUp(self):
        from rule_governance.member_calibration import calibrate_members
        self.calibrate = calibrate_members

    @staticmethod
    def _vote(member, vote, conf):
        return {"member": member, "vote": vote, "confidence": conf}

    def test_no_vote_hit_rate_and_miss_cost(self):
        events = [
            _resolved_event(r=-1.0, council=[self._vote("REGIME", "no", 90)]),
            _resolved_event(r=-1.0, council=[self._vote("REGIME", "no", 90)]),
            _resolved_event(r=2.0,  council=[self._vote("REGIME", "no", 90)]),
        ]
        cal = self.calibrate(events)
        self.assertEqual(cal["REGIME"]["no_votes"], 3)
        self.assertEqual(cal["REGIME"]["no_hit_rate"], round(2 / 3, 4))
        self.assertEqual(cal["REGIME"]["no_miss_cost_R"], 2.0)

    def test_yes_vote_hit_rate(self):
        events = [
            _resolved_event(r=2.0,  council=[self._vote("TOOLBOX", "yes", 65)]),
            _resolved_event(r=-1.0, council=[self._vote("TOOLBOX", "yes", 65)]),
        ]
        cal = self.calibrate(events)
        self.assertEqual(cal["TOOLBOX"]["yes_hit_rate"], 0.5)

    def test_neutral_votes_excluded_from_accuracy(self):
        events = [
            _resolved_event(r=-1.0, council=[self._vote("RISK", "neutral", 60)]),
        ]
        cal = self.calibrate(events)
        self.assertEqual(cal["RISK"]["neutral_votes"], 1)
        self.assertIsNone(cal["RISK"]["no_hit_rate"])

    def test_confidence_buckets_and_honesty(self):
        events = (
            # 85+ bucket: 3/3 correct; 50-70 bucket: 1/3 correct -> monotone
            [_resolved_event(r=-1.0, council=[self._vote("REGIME", "no", 90)])
             for _ in range(3)]
            + [_resolved_event(r=2.0, council=[self._vote("REGIME", "no", 60)])
               for _ in range(2)]
            + [_resolved_event(r=-1.0, council=[self._vote("REGIME", "no", 60)])]
        )
        cal = self.calibrate(events)
        buckets = cal["REGIME"]["confidence_buckets"]
        self.assertEqual(buckets["b85_plus"], 1.0)
        self.assertEqual(buckets["b50_70"], round(1 / 3, 4))
        self.assertTrue(cal["REGIME"]["confidence_honest"]["honest"])

    def test_dishonest_confidence_detected(self):
        events = (
            # high confidence wrong, low confidence right -> not monotone
            [_resolved_event(r=2.0, council=[self._vote("REGIME", "no", 90)])
             for _ in range(2)]
            + [_resolved_event(r=-1.0, council=[self._vote("REGIME", "no", 55)])
               for _ in range(2)]
        )
        cal = self.calibrate(events)
        self.assertFalse(cal["REGIME"]["confidence_honest"]["honest"])

    def test_never_raises(self):
        self.assertIsInstance(self.calibrate([{"bad": 1}, None]), dict)


class TestGovernanceReports(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # registry copy + ledger in temp dir
        with open(_REAL_REGISTRY, encoding="utf-8") as f:
            data = json.load(f)
        with open(os.path.join(self.tmp.name, "registry.json"), "w",
                  encoding="utf-8") as f:
            json.dump(data, f)
        os.environ["RULE_GOVERNANCE_DIR"] = self.tmp.name
        self.addCleanup(lambda: os.environ.pop("RULE_GOVERNANCE_DIR", None))

        from rule_governance import divergence_ledger as dl
        from rule_governance.governance_report import (
            build_daily_digest, build_weekly_report,
        )
        self.dl = dl
        self.daily = build_daily_digest
        self.weekly = build_weekly_report

        from datetime import datetime
        import pytz
        self.today = datetime.now(
            pytz.timezone("America/New_York")).strftime("%Y%m%d")

    def _seed_events(self):
        ev1 = _event("EV_1", rule_id="R-001")
        ev1["timestamp"] = f"{self.today}T100000"
        ev1["resolution"] = {"state": "resolved", "source": "proxy", "r": -1.0}
        ev2 = _event("EV_2", rule_id="R-003")
        ev2["timestamp"] = f"{self.today}T110000"
        self.dl.append_events([ev1, ev2], "QQQ")

    def test_daily_digest(self):
        self._seed_events()
        digest = self.daily("QQQ")
        self.assertEqual(digest["events"], 2)
        self.assertEqual(digest["events_by_rule"], {"R-001": 1, "R-003": 1})
        self.assertEqual(digest["resolved"], 1)
        self.assertEqual(digest["pending_backlog"], 1)
        self.assertTrue(os.path.exists(digest["report_path"]))

    def test_weekly_report_scorecards_and_files(self):
        self._seed_events()
        report = self.weekly("QQQ", opportunities_seen=10, sessions_seen=1)
        self.assertNotIn("error", report)
        ids = {c["rule_id"] for c in report["scorecards"]}
        self.assertTrue({"R-001", "R-002", "R-003"} <= ids)
        r001 = next(c for c in report["scorecards"] if c["rule_id"] == "R-001")
        self.assertEqual(r001["events_resolved"], 1)
        self.assertFalse(r001["promotion"]["eligible"])   # tiny sample
        # grandfathered laws listed as enforced/instrumentation pending
        gf = next(c for c in report["scorecards"] if c["rule_id"] == "GF-5F-001")
        self.assertIn("enforced law", gf["note"])
        # rules near review present (seeds within 30 days)
        self.assertTrue(os.path.exists(report["report_path"]))
        md_path = report["report_path"].replace(".json", ".md")
        self.assertTrue(os.path.exists(md_path))
        with open(md_path, encoding="utf-8") as f:
            md = f.read()
        self.assertIn("human-reviewed code change", md)

    def test_reports_never_raise_on_empty_world(self):
        os.environ["RULE_GOVERNANCE_DIR"] = os.path.join(self.tmp.name, "ghost")
        digest = self.daily("QQQ")
        self.assertEqual(digest.get("events", 0), 0)
        report = self.weekly("QQQ")
        self.assertIn("report", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
