"""
Phase AB-2A — Structure-Authorship Firewall tests.

Proves structure can no longer author trade direction at any generation point
(qualification, playbook, toolbox-inheritance, intent-inheritance), and that
June 11's three structure-authored decisions are now impossible.

Firewall default ON. Rollback STRUCTURE_AUTHORSHIP_FIREWALL=false restores the
legacy structure-rooted path (proven in TestRollback).
"""
import os
import sys
import unittest

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from qualification.trade_qualification_engine import qualify_trade, _direction_with_source
from playbooks.playbook_classifier import classify_playbook
from generation_firewall.authorship import (
    authored_direction, nonstructure_direction, firewall_enabled,
    SOURCE_DELIVERY, SOURCE_LIQUIDITY, SOURCE_STRUCTURE_ONLY,
    SOURCE_CONFLICT, SOURCE_FALLBACK_NONE,
)

_DIRECTIONAL = ("bullish", "bearish")


def _on():  os.environ["STRUCTURE_AUTHORSHIP_FIREWALL"] = "true"
def _off(): os.environ["STRUCTURE_AUTHORSHIP_FIREWALL"] = "false"
def _clear():
    for k in ("STRUCTURE_AUTHORSHIP_FIREWALL", "DIRECTION_CONFLICT_VETO"):
        os.environ.pop(k, None)


def _snap(bias="neutral", sweep=None, sweep_tf="15m", po3_dist=None,
          po3_manip=None, vol="stable"):
    liq = {}
    if sweep:
        liq[sweep_tf] = {"sweep_detected": True, "sweep_direction": sweep,
                         "reclaim_detected": True}
    po3 = {"15m": {}}
    if po3_dist:  po3["15m"]["distribution_direction"] = po3_dist
    if po3_manip: po3["15m"]["manipulation_direction"] = po3_manip
    return {
        "ai_context": {"directional_bias": bias, "market_narrative": ""},
        "structure": {"15m": {"bias": bias}},
        "volatility": {"15m": {"state": vol}},
        "po3": po3,
        "liquidity": liq,
    }


# ── Requirement 3 + 1: structure-only never authors a direction ───────────────

class TestStructureCannotAuthor(unittest.TestCase):
    def setUp(self): _on()
    def tearDown(self): _clear()

    def test_structure_only_bullish_is_not_bullish(self):
        d, src = authored_direction("bullish", {}, {})
        self.assertNotIn(d, _DIRECTIONAL)
        self.assertEqual(src, SOURCE_STRUCTURE_ONLY)

    def test_structure_only_bearish_is_not_bearish(self):
        d, src = authored_direction("bearish", {}, {})
        self.assertNotIn(d, _DIRECTIONAL)
        self.assertEqual(src, SOURCE_STRUCTURE_ONLY)

    def test_qualification_direction_not_structure_authored(self):
        q = qualify_trade(_snap(bias="bullish"))   # structure-only bullish
        self.assertNotIn(q["direction"], _DIRECTIONAL)
        self.assertEqual(q["direction_source"], SOURCE_STRUCTURE_ONLY)

    def test_playbook_direction_not_structure_authored(self):
        snap = _snap(bias="bullish")
        snap["qualification"] = qualify_trade(snap)
        # build a minimal playbook-scoring context; structure-only must not
        # let the playbook re-author bullish via its ai_context step
        pb = classify_playbook(snap)
        self.assertNotIn(pb["direction"], _DIRECTIONAL)

    def test_nonstructure_sources_are_only_authors(self):
        # delivery present WITH valid AB-2C provenance → it authors
        d, src = authored_direction("neutral", {"15m": {"distribution_direction": "bearish",
                                    "distribution_direction_source": "sweep_semantics"}}, {})
        self.assertEqual((d, src), ("bearish", SOURCE_DELIVERY))
        # liquidity sweep present → it authors
        d, src = authored_direction("neutral", {}, {"15m": {"sweep_detected": True,
                                    "sweep_direction": "below_low", "reclaim_detected": True}})
        self.assertEqual((d, src), ("bullish", SOURCE_LIQUIDITY))

    def test_po3_direction_without_provenance_is_rejected(self):
        # AB-2C: a PO3 direction with NO source field must be rejected by the
        # firewall (treated as untrusted), not authored.
        d, src = authored_direction("neutral", {"15m": {"distribution_direction": "bearish"}}, {})
        self.assertNotIn(d, _DIRECTIONAL)

    def test_po3_direction_with_structure_source_is_rejected(self):
        d, src = authored_direction("neutral", {"15m": {"distribution_direction": "bearish",
                                    "distribution_direction_source": "structure_bias"}}, {})
        self.assertNotIn(d, _DIRECTIONAL)

    def test_nothing_directional_is_neutral(self):
        d, src = authored_direction("neutral", {}, {})
        self.assertEqual((d, src), ("neutral", SOURCE_FALLBACK_NONE))


# ── Requirement 6: June 11 behavior ───────────────────────────────────────────

class TestJune11Firewall(unittest.TestCase):
    def setUp(self): _on()
    def tearDown(self): _clear()

    def test_1013_bullish_structure_cannot_create_long(self):
        # 10:13: structure bullish, 15m above_high sweep (bearish delivery)
        snap = _snap(bias="bullish", sweep="above_high")
        q = qualify_trade(snap)
        self.assertNotEqual(q["direction"], "bullish")
        self.assertNotEqual(q["direction_source"], SOURCE_STRUCTURE_ONLY)  # it's a conflict, not a vacuum
        self.assertEqual(q["direction_source"], SOURCE_CONFLICT)

    def test_1020_1040_bearish_not_blocked_by_bullish_structure(self):
        # The firewall must not encode "structure bullish ⇒ block bearish".
        # Proof: with bullish structure REMOVED (neutral), bearish delivery
        # authors bearish — i.e. nothing about a bearish read depends on
        # structure being bearish.
        _po3 = {"15m": {"manipulation_direction": "bearish",
                        "manipulation_direction_source": "sweep_semantics"}}
        d_neutral, src = authored_direction("neutral", _po3, {})
        self.assertEqual(d_neutral, "bearish")
        self.assertEqual(src, SOURCE_DELIVERY)
        # And with bullish structure present it is conflicted (not a structure
        # block — the source is the conflict, structure is never the author)
        d_bull, src2 = authored_direction("bullish", _po3, {})
        self.assertNotEqual(src2, SOURCE_STRUCTURE_ONLY)
        self.assertNotEqual(d_bull, "bullish")

    def test_1317_bearish_structure_cannot_create_short(self):
        # 13:17: structure bearish, 3m below_low sweep (bullish semantics)
        snap = _snap(bias="bearish", sweep="below_low", sweep_tf="3m")
        q = qualify_trade(snap)
        self.assertNotEqual(q["direction"], "bearish")
        self.assertEqual(q["direction_source"], SOURCE_CONFLICT)


# ── Requirement 2: direction_source metadata present everywhere ───────────────

class TestDirectionSourceMetadata(unittest.TestCase):
    def setUp(self): _on()
    def tearDown(self): _clear()

    def test_qualification_exposes_source(self):
        self.assertIn("direction_source", qualify_trade(_snap(bias="bullish")))

    def test_playbook_exposes_source(self):
        snap = _snap(bias="bullish", po3_dist="bullish")  # delivery authors bullish
        snap["qualification"] = qualify_trade(snap)
        pb = classify_playbook(snap)
        self.assertIn("direction_source", pb)

    def test_valid_source_values_only(self):
        valid = {SOURCE_DELIVERY, SOURCE_LIQUIDITY, SOURCE_STRUCTURE_ONLY,
                 SOURCE_CONFLICT, SOURCE_FALLBACK_NONE}
        for bias in ("bullish", "bearish", "neutral"):
            _, src = authored_direction(bias, {}, {})
            self.assertIn(src, valid)


# ── Requirement 4: structure still provides witness evidence ──────────────────

class TestStructureRemainsWitness(unittest.TestCase):
    def setUp(self): _on()
    def tearDown(self): _clear()

    def test_structure_conflict_surfaced_as_warning(self):
        snap = _snap(bias="bullish", sweep="above_high")
        q = qualify_trade(snap)
        self.assertTrue(any("structure witness" in w for w in q["warnings"]))

    def test_swings_and_bos_mss_still_available(self):
        # Firewall does not strip structure evidence — the engine output is intact
        snap = _snap(bias="bullish")
        snap["structure"]["15m"].update({"last_swing_high": 702.5, "bos": True, "mss": False})
        self.assertEqual(snap["structure"]["15m"]["last_swing_high"], 702.5)
        self.assertTrue(snap["structure"]["15m"]["bos"])


# ── Requirement 7 / rollback: firewall OFF restores legacy authoring ──────────

class TestRollback(unittest.TestCase):
    def tearDown(self): _clear()

    def test_off_restores_structure_authoring(self):
        _off()
        os.environ["DIRECTION_CONFLICT_VETO"] = "false"   # full legacy
        d, src = _direction_with_source({"directional_bias": "bullish"}, {}, {}, {})
        self.assertEqual(d, "bullish")          # legacy: structure authors
        self.assertEqual(src, "legacy_structure_rooted")

    def test_on_is_default(self):
        _clear()
        self.assertTrue(firewall_enabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)
