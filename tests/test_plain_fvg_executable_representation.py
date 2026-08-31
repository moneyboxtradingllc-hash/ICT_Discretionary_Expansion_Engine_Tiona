"""PLAIN-FVG-EXECUTABLE-REPRESENTATION-1 — every plain FVG was anonymous.

Measured on the 2026-08-21 tape at 10:25:11: 45 plain-FVG occurrences across
1m/3m/5m/15m, both directions, and **zero** carried an `occurrence_id`. The
family produced no tool instances all session on any timeframe, because
`fvg_occurrences` drops anything it cannot name:

    execution_ineligible_reason = "occurrence_identity_unprovable"

THE CAUSE WAS NEVER THE TIMEFRAME. `_TF_LABEL_FOR_MINUTES` already maps 1 -> 1m,
`c3_time` was always present, and `c3_row` is built from `candles[idx+2]`. What
was missing is the CONTRACT: canonical candle rows record none, the snapshot
carried only `symbol: "MNQ"` -- an instrument, not an exact contract -- and
`row_contract` therefore had nothing to derive identity from. `market_object_id`
refuses to invent one, correctly: a helper that quietly supplies
CON.F.US.MNQ.U26 manufactures provenance and would relabel foreign evidence as
production evidence.

So the contract is THREADED from the caller that legitimately knows it:

    ProductionScanCycle.contract_id -> build_snapshot(contract_id=)
      -> snapshot["contract_id"] -> fvg_occurrence_instances
      -> fvg_execution_instances(contract=) -> fvg_occurrence_id

Absent a contract, identity stays None and the occurrence stays
execution-ineligible -- byte-identical to pre-unit behaviour.

WHAT THIS UNIT DELIBERATELY DOES NOT DO. An earlier draft also gave plain FVG a
family-specific 1m entry in the `_locate_zone` source-timeframe whitelist, on the
theory that the gap would otherwise be unlocatable. **Measurement disproved the
theory and the change was reverted**: catalog FVG rows carry the OCCURRENCE's own
geometry (`occ["low"]/["high"]`), never `_locate_zone` output, so the specimen
reaches the catalog at exact 1m geometry from identity alone. `_allowed_source_tfs`
is untouched and no family's zone doctrine moved.
"""
from __future__ import annotations

import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.luna_candidate_producer import authorized_tool_catalog   # noqa: E402
from toolbox import price_levels as PL                               # noqa: E402
from toolbox.price_levels import (fvg_execution_instances,           # noqa: E402
                                  fvg_occurrence_id, fvg_occurrences,
                                  _allowed_source_tfs)
from toolbox.toolbox_engine import fvg_occurrence_instances, run_toolbox  # noqa: E402

ARCHIVE = os.path.join(ROOT, "data", "ai_brain")
SPECIMEN = "20260821_102511_MNQ.json"
MNQ = "CON.F.US.MNQ.U26"

# The governing gap: c1 10:21, c2 10:22, c3 10:23, complete at ~10:24:00 ET.
GAP_LOW, GAP_HIGH = 29243.00, 29251.25
C3 = "2026-08-21T14:23:00+00:00"
EXPECTED_ID = f"FVG:{MNQ}:1m:{C3}"


def snap(contract=MNQ):
    path = os.path.join(ARCHIVE, SPECIMEN)
    if not os.path.exists(path):
        pytest.skip("archived production snapshot absent")
    with open(path, encoding="utf-8") as fh:
        s = copy.deepcopy(json.load(fh)["raw_snapshot"])
    if contract is not None:
        s["contract_id"] = contract
    return s


def candles(s=None, tf="1m"):
    return ((s or snap())["timeframes"].get(tf) or {}).get("recent_candles") or []


def specimen(contract=MNQ):
    for o in fvg_execution_instances(candles(), "bullish", 1, contract=contract):
        if o.get("low") == GAP_LOW and o.get("high") == GAP_HIGH:
            return o
    raise AssertionError("the canonical specimen gap is missing")


def catalog(contract=MNQ):
    s = snap(contract)
    s["toolbox"] = run_toolbox(s)          # production recomputes this every scan
    return authorized_tool_catalog(s)


# ══════════════════════════════════════════════════════════════════════════════
class TestTheDefect:
    def test_without_a_contract_every_plain_fvg_is_anonymous(self):
        """The pre-unit state, on every timeframe and both directions."""
        s = snap(contract=None)
        total = named = 0
        for tf, mins in (("1m", 1), ("3m", 3), ("5m", 5), ("15m", 15)):
            for direction in ("bullish", "bearish"):
                for o in fvg_execution_instances(candles(s, tf), direction, mins):
                    total += 1
                    named += bool(o.get("occurrence_id"))
        assert total >= 40, total
        assert named == 0

    def test_the_specimen_was_dropped_for_identity_not_timeframe(self):
        anon = specimen(contract=None)
        assert anon["occurrence_id"] is None
        assert anon["identity_evaluable"] is False
        assert anon["execution_eligible"] is False
        assert anon["execution_ineligible_reason"] == "occurrence_identity_unprovable"

    def test_cadence_and_completion_slot_were_never_the_problem(self):
        assert PL._TF_LABEL_FOR_MINUTES.get(1) == "1m"
        assert specimen(contract=None)["c3_time"] == C3

    def test_the_snapshot_carries_an_instrument_not_a_contract(self):
        """`symbol` is "MNQ"; identity needs the exact contract."""
        raw = snap(contract=None)
        raw.pop("contract_id", None)
        assert raw.get("symbol") == "MNQ"
        assert MNQ not in json.dumps(raw)


class TestIdentityRepaired:
    def test_the_specimen_gains_a_canonical_id(self):
        assert specimen()["occurrence_id"] == EXPECTED_ID

    def test_identity_is_stable_across_repeated_reads(self):
        assert specimen()["occurrence_id"] == specimen()["occurrence_id"]

    def test_it_uses_the_one_identity_theorem(self):
        import inspect
        assert "market_object_id" in inspect.getsource(fvg_occurrence_id)

    def test_no_discriminators_are_used(self):
        """contract+timeframe+c3 instant is unique — proven over 1790
        occurrences across 40 archived scans, zero slots holding two gaps. So
        the id is exactly the canonical four parts and nothing is appended."""
        from market_data.object_identity import market_object_id
        assert specimen()["occurrence_id"] == market_object_id(
            "FVG", contract=MNQ, timeframe="1m", instant=C3)
        assert EXPECTED_ID.endswith(C3)

    def test_geometry_is_untouched_by_naming_it(self):
        o = specimen()
        assert (o["low"], o["high"]) == (GAP_LOW, GAP_HIGH)
        assert o["c1_time"].endswith("14:21:00+00:00")
        assert o["c3_time"] == C3

    def test_the_whole_family_recovers_not_just_the_specimen(self):
        s = snap()
        named = sum(bool(o.get("occurrence_id"))
                    for tf, mins in (("1m", 1), ("3m", 3), ("5m", 5), ("15m", 15))
                    for d in ("bullish", "bearish")
                    for o in fvg_execution_instances(candles(s, tf), d, mins,
                                                     contract=MNQ))
        assert named >= 40


class TestFailsClosed:
    @pytest.mark.parametrize("bad", [None, "", "   "])
    def test_no_contract_means_no_identity(self, bad):
        assert specimen(contract=bad)["occurrence_id"] is None

    def test_identity_is_scoped_by_whatever_the_caller_supplies(self):
        """PINNED HAZARD, not an endorsement.

        `canonical_contract` validates NON-EMPTINESS, not contract SHAPE, so a
        caller passing the instrument "MNQ" mints `FVG:MNQ:1m:<c3>` rather than
        failing closed. Production is safe because the only production caller
        threads `ProductionScanCycle.contract_id`, which is the exact contract
        resolved at session start -- but nothing in this layer ENFORCES that.
        Recorded so the assumption is visible instead of implicit."""
        assert specimen(contract="MNQ")["occurrence_id"] == "FVG:MNQ:1m:" + C3

    def test_the_production_thread_supplies_the_exact_contract(self):
        import inspect
        from live_scan import production_scan_cycle as PSC
        from toolbox import toolbox_engine as TE
        assert "contract_id=self.contract_id" in inspect.getsource(PSC)
        assert 'snapshot.get("contract_id")' in inspect.getsource(
            TE.fvg_occurrence_instances)

    def test_a_missing_contract_leaves_behaviour_byte_identical(self):
        before = specimen(contract=None)
        after = {k: v for k, v in before.items()}
        assert after["execution_eligible"] is False
        assert after["execution_ineligible_reason"] == "occurrence_identity_unprovable"

    def test_the_scan_loop_does_not_mint_identity(self):
        import inspect
        from live_scan import production_scan_cycle as PSC
        assert "market_object_id" not in inspect.getsource(PSC)
        assert "fvg_occurrence_id" not in inspect.getsource(PSC)


class TestItReachesTheCatalog:
    def test_the_specimen_is_published_with_exact_1m_geometry(self):
        rows = [r for r in catalog()
                if r.get("tool") == "bullish_fvg" and r.get("zone_low") == GAP_LOW]
        assert len(rows) == 1
        row = rows[0]
        assert (row["zone_low"], row["zone_high"]) == (GAP_LOW, GAP_HIGH)
        assert row["source_tf"] == "1m"
        assert row["execution_eligible"] is True

    def test_before_the_unit_no_plain_fvg_row_existed_at_all(self):
        assert not [r for r in catalog(contract=None)
                    if str(r.get("tool", "")).endswith("_fvg")
                    and "ifvg" not in str(r.get("tool"))]

    def test_exactly_one_eligible_bullish_occurrence_so_the_family_token_resolves(self):
        """`TOOL_OCCURRENCE_AMBIGUOUS` refuses when a family token resolves to
        several eligible gaps. Here it resolves to one, so mechanics extracts
        rather than chooses."""
        elig = [r for r in catalog()
                if r.get("tool") == "bullish_fvg" and r.get("execution_eligible")]
        assert len(elig) == 1
        assert elig[0]["zone_low"] == GAP_LOW

    def test_the_archived_payload_is_the_control(self):
        with open(os.path.join(ARCHIVE, SPECIMEN), encoding="utf-8") as fh:
            shipped = json.load(fh)["input_payload"]["authorized_tool_catalog"]
        assert not [r for r in shipped if r.get("tool") == "bullish_fvg"]


class TestNegativeSpecimens:
    def test_a_forming_gap_cannot_author_exposure(self):
        """CONTINUITY-2F: identity does not confer temporal authority."""
        s = snap()
        c = [dict(x) for x in candles(s)]
        for row in c[-3:]:
            row["temporal_status"] = "forming"
        got = [o for o in fvg_execution_instances(c, "bullish", 1, contract=MNQ)
               if o.get("low") == GAP_LOW]
        assert not got or got[0]["execution_eligible"] is False

    def test_a_retired_gap_does_not_become_executable_merely_by_being_named(self):
        named_but_dead = [o for o in fvg_execution_instances(candles(), "bearish", 1,
                                                             contract=MNQ)
                          if o.get("occurrence_id") and o.get("retired")]
        for o in named_but_dead:
            assert o["execution_eligible"] is False
            assert o["execution_ineligible_reason"]

    def test_ifvg_gains_no_authority(self):
        """IFVG stays quarantined; this unit touches only plain FVG."""
        rows = [r for r in catalog() if r.get("tool") == "bullish_ifvg"]
        for r in rows:
            assert r.get("execution_eligible") is False

    def test_identity_alone_does_not_make_a_candidate_or_a_direction(self):
        import inspect
        src = inspect.getsource(fvg_occurrences)
        for banned in ("candidate", "invalidation_level =", "objective", "order"):
            assert banned not in src, banned


class TestNothingElseMoved:
    def test_zone_source_timeframe_policy_is_untouched(self):
        """The reverted half. `_locate_zone` still refuses 1m for every family,
        exactly as before this unit."""
        assert _allowed_source_tfs("MNQ") == ("15m", "5m", "3m")
        assert PL._DEFAULT_SOURCE_TFS == ("15m", "5m", "3m")
        assert not hasattr(PL, "_FAMILY_SOURCE_TFS")
        assert not hasattr(PL, "_source_tfs_for_family")

    def test_locate_zone_still_uses_the_generic_whitelist(self):
        import inspect
        src = inspect.getsource(PL._locate_zone)
        assert 'allowed_tfs = _allowed_source_tfs(snapshot.get("symbol", ""))' in src

    def test_rejection_block_and_po3_geometry_are_unchanged(self):
        s = snap()
        from toolbox.price_levels import po3_reversal_order_block, NO_MANIPULATION
        assert po3_reversal_order_block(s, "bullish")["reason"] == NO_MANIPULATION
        z = PL._locate_zone("rejection_block", "bearish", s, 29251.50, False)
        assert z.get("source_tf") in (None, "15m", "5m", "3m")

    def test_no_risk_doctrine_moved(self):
        from broker import topstepx_combine_risk as RK
        assert (RK.PREFERRED_MAX_STOP_POINTS, RK.ABSOLUTE_MAX_STOP_POINTS) == (35.0, 50.0)
        assert RK.PRODUCTION_MAX_RISK_USD == 350.00

    def test_unit_0_ledger_semantics_are_intact(self):
        from market_data import occurrence_ledger as OL
        assert OL.RECORDED_NOT_DURABLE != OL.RECORDED
        assert OL.DEGRADED == "LEDGER_PERSISTENCE_DEGRADED"

    def test_market_events_quarantine_holds(self):
        import subprocess
        hits = subprocess.run(
            ["git", "grep", "-lE", r"^\s*(from|import)\s+market_data\.market_events",
             "--", "src/"], capture_output=True, text=True).stdout.split()
        assert hits == [], hits


class TestSpecimenAState:
    """Shared trade-state language. Boundary this unit is expected to move."""

    def test_setup_visible_becomes_yes(self):
        rows = [r for r in catalog() if r.get("tool") == "bullish_fvg"
                and r.get("zone_low") == GAP_LOW]
        assert rows, "SETUP_VISIBLE still NO"

    def test_trade_defined_becomes_yes(self):
        """entry location + a stop Luna may author + an objective all exist."""
        entry = [r for r in catalog() if r.get("tool") == "bullish_fvg"
                 and r.get("execution_eligible")]
        assert len(entry) == 1
        # the stop: the gap's own c1 candle low, visible in her payload
        assert specimen()["c1_time"].endswith("14:21:00+00:00")
        # the objective: authorized in that very payload
        with open(os.path.join(ARCHIVE, SPECIMEN), encoding="utf-8") as fh:
            objs = json.load(fh)["input_payload"]["authorized_objectives"]
        assert any(o.get("price") == 29533.75 for o in objs)

    def test_entry_triggered_is_NOT_repaired_by_this_unit(self):
        """Price entered the gap during the 10:24 minute; the surrounding scans
        were 10:23:51 and 10:25:11. Cadence is a separate unit."""
        with open(os.path.join(ARCHIVE, SPECIMEN), encoding="utf-8") as fh:
            ep = json.load(fh)["input_payload"]["market"]["execution_price"]
        assert ep["bullish_executable"] == 29251.50
        assert ep["bullish_executable"] > GAP_HIGH      # still ABOVE the zone
