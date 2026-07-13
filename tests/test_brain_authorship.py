"""
BRAIN-AUTHORSHIP-CLOSURE (2026-07-13) — sole authorship of fresh exposure.

Audit (source-proven, then replay-reproduced): qualification's authoring seam
fell through to MECHANICAL direction when the Brain was neutral, and checked
owner=='ai_brain' without Brain HEALTH — deterministic-fallback theses and
served AB-7 theses on degraded cycles could author fresh-trade direction.
Current-stack replay: 175/255 authorized scans rode non-Brain-authored
direction.

Constitution under test: the Brain is the SOLE author of fresh trade
direction. Mechanics may observe/prove/constrain/reject/size/execute/protect
— never originate. Valid AB-7 inheritance (healthy current cycle per the
existing laundering doctrine) remains authorship. Downstream stages may
DECLINE, never substitute direction. Gate-only; position safety
unconditional; fail-closed while armed; default off = legacy.
"""
import copy
import os
import sys
import unittest
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import ai_brain.ecu as ecu                                        # noqa: E402
from ai_brain.ecu import (                                        # noqa: E402
    brain_authorship, _classify_authorship, healthy_directional_thesis,
    BRAIN_AUTHORSHIP_CODES,
)
from execution_gate.execution_gate import evaluate_gate           # noqa: E402

_ON = {"BRAIN_AUTHORSHIP_REQUIRED": "on"}


_MATCH = "__match_served__"


def _snap(direction="bullish", source="llm", cand_source=_MATCH,
          opportunity=True, qual=None, dec=None, prop=None, thesis_id="TH_1"):
    """Snapshot with a served thesis + downstream directions (None = match)."""
    d = direction if direction in ("bullish", "bearish") else None
    if cand_source is _MATCH:
        cand_source = "llm" if source == "ab7_active_thesis" else source
    return {
        "brain_thesis": {"owner": "ai_brain", "source": source,
                         "direction": direction, "opportunity": opportunity,
                         "thesis_id": thesis_id},
        "candidate_thesis": {"source": cand_source},
        "qualification": {"direction": qual if qual is not None else d},
        "decision_authority": {"direction": dec if dec is not None else d},
        "playbook": {"direction": prop if prop is not None else d},
    }


def _auth(**kw):
    with patch.dict(os.environ, _ON):
        return brain_authorship(_snap(**kw))


class TestAuthority(unittest.TestCase):
    def test_1_2_direct_healthy_authorship_passes(self):
        for d in ("bullish", "bearish"):
            r = _auth(direction=d)
            self.assertTrue(r["eligible"], d)
            self.assertEqual(r["code"], "valid_direct_llm_authorship")
            self.assertEqual(r["authorship"], "direct")
            self.assertTrue(r["provenance_valid"])

    def test_3_healthy_neutral_cannot_author(self):
        r = _auth(direction="neutral", qual="bullish", dec="bullish",
                  prop="bullish")   # mechanics found a setup — irrelevant
        self.assertFalse(r["eligible"])
        self.assertEqual(r["code"], "healthy_brain_neutral")

    def test_4_healthy_conflicted_cannot_author(self):
        r = _auth(direction="conflicted", qual="bearish", dec="bearish",
                  prop="bearish")
        self.assertFalse(r["eligible"])
        self.assertEqual(r["code"], "healthy_brain_conflicted")

    def test_5_degraded_sources_cannot_author(self):
        for src in ("deterministic", "llm_failed_fallback",
                    "contaminated_input", "degraded", "ecu_error:x"):
            r = _auth(source=src, cand_source=src)
            self.assertFalse(r["eligible"], src)
            self.assertEqual(r["code"], "degraded_brain", src)

    def test_6_unavailable_brain_cannot_author(self):
        with patch.dict(os.environ, _ON):
            r = brain_authorship({"qualification": {"direction": "bullish"}})
        self.assertFalse(r["eligible"])
        self.assertEqual(r["code"], "missing_brain_result")
        r = _auth(source="brain_disabled", cand_source="brain_disabled")
        self.assertFalse(r["eligible"])
        self.assertEqual(r["code"], "unavailable_brain")

    def test_7_8_fallback_and_unknown_sources_cannot_author(self):
        self.assertEqual(_auth(source="deterministic",
                               cand_source="deterministic")["code"],
                         "degraded_brain")
        self.assertEqual(_auth(source="something_new",
                               cand_source="something_new")["code"],
                         "non_sovereign_source")

    def test_9_invalid_inherited_provenance_fails(self):
        for bad_cycle in ("deterministic", "llm_failed_fallback", "", None):
            r = _auth(source="ab7_active_thesis", cand_source=bad_cycle)
            self.assertFalse(r["eligible"], repr(bad_cycle))
            self.assertEqual(r["code"], "invalid_inherited_provenance")
            self.assertFalse(r["provenance_valid"])

    def test_10_valid_inherited_passes(self):
        r = _auth(source="ab7_active_thesis", cand_source="llm")
        self.assertTrue(r["eligible"])
        self.assertEqual(r["code"], "valid_inherited_authorship")
        self.assertEqual(r["authorship"], "inherited")

    def test_opportunity_required(self):
        r = _auth(opportunity=False)
        self.assertFalse(r["eligible"])
        self.assertEqual(r["code"], "directional_without_opportunity")


class TestDirectionChain(unittest.TestCase):
    def test_11_to_16_mismatches_fail(self):
        cases = (("bullish", dict(qual="bearish"), "qualification_direction_mismatch"),
                 ("bullish", dict(dec="bearish"), "decision_direction_mismatch"),
                 ("bullish", dict(prop="bearish"), "proposed_direction_mismatch"),
                 ("bearish", dict(qual="bullish"), "qualification_direction_mismatch"),
                 ("bearish", dict(dec="bullish"), "decision_direction_mismatch"),
                 ("bearish", dict(prop="bullish"), "proposed_direction_mismatch"))
        for d, kw, code in cases:
            r = _auth(direction=d, **kw)
            self.assertFalse(r["eligible"], (d, kw))
            self.assertEqual(r["code"], code)

    def test_17_missing_downstream_direction_does_not_pass_gate(self):
        # a stage that emits no direction DECLINES (neutral downstream);
        # authorship itself passes, but the gate's own decision/trigger
        # requirements then refuse — proven at the gate level:
        snap = _snap(direction="bullish", qual="", dec="", prop="")
        with patch.dict(os.environ, _ON):
            gate = evaluate_gate(snap)
        self.assertFalse(gate["would_authorize_if_enabled"])

    def test_18_matching_chain_passes_guard(self):
        r = _auth(direction="bearish")
        self.assertTrue(r["eligible"])

    def test_downstream_neutral_is_decline_not_mismatch(self):
        # neutral downstream = declined, not substituted — the guard does not
        # invent a mismatch; the gate's readiness checks handle the decline
        r = _auth(direction="bullish", qual="neutral")
        self.assertTrue(r["eligible"])


class TestHealthDoctrine(unittest.TestCase):
    def test_19_20_first_degraded_scan_denies_regardless_of_thresholds(self):
        # per-scan authorship denies on the FIRST degraded cycle — the
        # session-level 5-consecutive BrainHealthGate is a separate rail and
        # creates no early-scans permission window
        r = _auth(source="deterministic", cand_source="deterministic")
        self.assertFalse(r["eligible"])

    def test_21_restored_health_restores_eligibility(self):
        self.assertTrue(_auth(direction="bullish", source="llm")["eligible"])

    def test_22_session_gate_untouched(self):
        # session-level revocation stays where it lives (brain_preflight)
        with open(os.path.join(os.path.dirname(__file__), "..", "src",
                               "ai_brain", "brain_preflight.py"),
                  encoding="utf-8") as fh:
            self.assertNotIn("BRAIN_AUTHORSHIP_REQUIRED", fh.read())

    def test_consistency_with_canonical_health_predicate(self):
        # the guard must never disagree with healthy_directional_thesis on
        # health/provenance/directionality — HDT true => guard reaches the
        # chain stage (eligible when chain agrees); HDT false => guard denies
        matrix = (
            dict(direction="bullish"), dict(direction="bearish"),
            dict(direction="neutral"), dict(direction="conflicted"),
            dict(source="deterministic", cand_source="deterministic"),
            dict(source="ab7_active_thesis", cand_source="llm"),
            dict(source="ab7_active_thesis", cand_source="deterministic"),
            dict(opportunity=False),
        )
        for kw in matrix:
            snap = _snap(**kw)
            hdt, _ = healthy_directional_thesis(snap)
            rec = _classify_authorship(snap)
            self.assertEqual(hdt, rec["eligible"], kw)


class TestFailureSemantics(unittest.TestCase):
    def test_23_helper_exception_denies(self):
        class Hostile:
            def get(self, *a, **k):
                raise ValueError("hostile")
        with patch.dict(os.environ, _ON):
            r = brain_authorship(Hostile())
        self.assertFalse(r["eligible"])
        self.assertEqual(r["code"], "authorship_evaluation_error")

    def test_24_25_gate_survives_guard_explosion_and_denies(self):
        with patch.dict(os.environ, _ON), \
             patch("ai_brain.ecu.brain_authorship",
                   side_effect=RuntimeError("guard exploded")):
            gate = evaluate_gate(_snap())
        self.assertFalse(gate["authorization_checks"]["brain_authorship_ok"])
        self.assertFalse(gate["would_authorize_if_enabled"])

    def test_26_structured_code_emitted(self):
        with patch.dict(os.environ, _ON):
            gate = evaluate_gate(_snap(direction="neutral"))
        self.assertEqual(gate["brain_authorship"]["code"],
                         "healthy_brain_neutral")
        self.assertTrue(any("[healthy_brain_neutral]" in b
                            for b in gate["blocking_factors"]))
        for c in gate["brain_authorship"]:
            pass   # record present and iterable
        self.assertIn(gate["brain_authorship"]["code"],
                      BRAIN_AUTHORSHIP_CODES)

    def test_27_flag_off_legacy(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BRAIN_AUTHORSHIP_REQUIRED", None)
            r = brain_authorship(_snap(direction="neutral"))
            gate = evaluate_gate(_snap(direction="neutral"))
        self.assertTrue(r["eligible"])
        self.assertEqual(r["code"], "off")
        self.assertTrue(gate["authorization_checks"]["brain_authorship_ok"])


class TestLifecycleInheritance(unittest.TestCase):
    def test_28_healthy_inherited_passes(self):
        self.assertTrue(_auth(source="ab7_active_thesis",
                              cand_source="llm")["eligible"])

    def test_29_30_31_dead_lifecycle_is_never_served(self):
        # invalidated/expired/completed theses are excluded at the SERVE
        # boundary — as_brain_thesis returns None, so no such thesis can even
        # reach the guard as ab7_active_thesis
        from ai_brain.thesis_lifecycle import (ThesisLifecycleEngine,
                                               STATUS_INVALIDATED,
                                               STATUS_EXPIRED, STATUS_COMPLETED)
        eng = ThesisLifecycleEngine(persist=False)
        for status in (STATUS_INVALIDATED, STATUS_EXPIRED, STATUS_COMPLETED):
            eng._active = {"status": status, "direction": "bullish",
                           "thesis_type": "trade", "playbook_family": "x",
                           "tool_family": "y"}
            self.assertIsNone(eng.as_brain_thesis(), status)

    def test_32_direction_flip_impossible_by_construction(self):
        # the lifecycle REPLACES a thesis rather than flipping it — direction
        # is written once at _new_thesis and never reassigned on update paths
        import re
        with open(os.path.join(os.path.dirname(__file__), "..", "src",
                               "ai_brain", "thesis_lifecycle.py"),
                  encoding="utf-8") as fh:
            txt = fh.read()
        # exactly one assignment site for the active thesis's direction (at
        # creation); no update path REASSIGNS it (comparisons == are fine)
        self.assertEqual(txt.count('"direction":             cf["direction"]'), 1)
        self.assertIsNone(re.search(r'a\["direction"\]\s*=[^=]', txt))

    def test_33_degraded_origin_cannot_hide_behind_inheritance(self):
        r = _auth(source="ab7_active_thesis", cand_source="deterministic")
        self.assertFalse(r["eligible"])
        self.assertEqual(r["code"], "invalid_inherited_provenance")

    def test_34_thesis_never_mutated(self):
        snap = _snap(direction="neutral")
        before = copy.deepcopy(snap["brain_thesis"])
        with patch.dict(os.environ, _ON):
            brain_authorship(snap)
        self.assertEqual(snap["brain_thesis"], before)


class TestPositionSafetyIsolation(unittest.TestCase):
    def test_35_to_41_position_management_independent(self):
        snap = _snap(direction="neutral")
        snap["position_monitor"] = {"has_open_position": True, "side": "long",
                                    "qty": 1, "current_price": 500.0}
        with patch.dict(os.environ, _ON):
            gate = evaluate_gate(snap)
        self.assertFalse(gate["would_authorize_if_enabled"])   # no fresh entry
        self.assertTrue(snap["position_monitor"]["has_open_position"])
        from paper_execution.position_supremacy import enforce_position_supremacy
        with patch.dict(os.environ, _ON):
            enforce_position_supremacy(snap)   # must not raise

    def test_flag_and_helper_absent_from_safety_files(self):
        src = os.path.join(os.path.dirname(__file__), "..", "src")
        for parts in (("paper_execution", "position_monitor.py"),
                      ("paper_execution", "stop_enforcer.py"),
                      ("paper_execution", "trade_manager.py"),
                      ("paper_execution", "order_builder.py"),
                      ("paper_execution", "paper_broker.py"),
                      ("paper_execution", "position_supremacy.py"),
                      ("paper_execution", "trade_reconciliation.py"),
                      ("risk", "risk_governor.py"),
                      ("operational_readiness", "eod_authority.py")):
            with open(os.path.join(src, *parts), encoding="utf-8") as fh:
                txt = fh.read()
            for needle in ("brain_authorship", "BRAIN_AUTHORSHIP_REQUIRED"):
                self.assertNotIn(needle, txt, "/".join(parts))


class TestBypassProof(unittest.TestCase):
    def _src(self, *parts):
        with open(os.path.join(os.path.dirname(__file__), "..", "src", *parts),
                  encoding="utf-8") as fh:
            return fh.read()

    def test_42_fresh_submission_consumes_the_gate(self):
        engine = self._src("paper_execution", "execution_engine.py")
        self.assertIn('eg.get("allow_execution", False)', engine)
        self.assertIn('eg.get("would_authorize_if_enabled", False)', engine)
        self.assertIn("submit_paper_order", engine)

    def test_44_no_alternate_fresh_entry_path(self):
        # submit_paper_order has exactly ONE src caller: the execution engine
        import subprocess
        out = subprocess.run(
            ["git", "grep", "-l", "submit_paper_order", "--", "src"],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), "..")).stdout.split()
        self.assertEqual(sorted(out),
                         ["src/paper_execution/execution_engine.py",
                          "src/paper_execution/paper_broker.py"])

    def test_45_retry_lifecycle_cannot_create_entries(self):
        pol = self._src("paper_execution", "pending_order_lifecycle.py")
        self.assertNotIn("submit_paper_order", pol)
        self.assertNotIn("submit_order", pol)

    def test_46_intent_builder_cannot_submit(self):
        # (docstrings legitimately SAY "does not interact with any broker" —
        # assert no imports/calls, not prose)
        ib = self._src("trade_intent", "intent_builder.py")
        for needle in ("submit_paper_order", "submit_order",
                       "import paper_broker", "from paper_execution"):
            self.assertNotIn(needle, ib)

    def test_launcher_and_stack_carry_flag(self):
        with open(os.path.join(os.path.dirname(__file__), "..",
                               "launch_paper_session_fc.ps1"),
                  encoding="utf-8") as fh:
            self.assertIn('$env:BRAIN_AUTHORSHIP_REQUIRED     = "on"', fh.read())
        from replay_validation.live_brain_study import CURRENT_STACK
        self.assertEqual(CURRENT_STACK.get("BRAIN_AUTHORSHIP_REQUIRED"), "on")

    def test_52_no_model_call(self):
        import ai_brain.narrative_brain as nb
        with patch.dict(os.environ, _ON), \
             patch.object(nb, "_call_llm",
                          side_effect=AssertionError("LLM called")):
            brain_authorship(_snap())
            with patch.dict(os.environ, _ON):
                evaluate_gate(_snap(direction="neutral"))


if __name__ == "__main__":
    unittest.main()
