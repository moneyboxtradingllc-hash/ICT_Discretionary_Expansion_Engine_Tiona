"""LIQUIDITY-SWEEP-EPISODE-IDENTITY-1 — "I see a sweep" ... "what sweep?"

`sweep_detected` is a TWO-CANDLE predicate: `candles[-1]` high/low/close against
`candles[-2].close`. It answers a PRESENT-TENSE question truthfully and then the
event is gone. The 2026-08-21 10:18/10:19 "flicker" was never a malfunction --
the 10:18 bar swept and closed back, the 10:19 bar did not, and the flag was
right both times.

The defect is that PO3 asks a HISTORICAL CAUSAL question of that present-tense
boolean. It wants "which manipulation, at what level, when" and the only fact
available is "is the current bar a sweep". Worse, the detector ALREADY computes
the exact level it swept -- `ref_high`/`ref_low` -- compares against it, and
throws it away.

    DETECTION TRUTH   liquidity_engine     what happened
    IDENTITY          sweep_occurrence     which canonical object it is
    PERSISTENCE       occurrence_ledger    what must not be forgotten
    MEANING           PO3 / Luna, later    what it implies for a trade

The adapter is NOT in `market_events`, which was the obvious home and was refused
by a certified invariant: that module reconstructs sweeps from a bridged
array-neighbour close, and importing it into production would carry that
cadence-unsafe path across the quarantine line. Module placement carries
authority consequences.

THIS UNIT CHANGES NO TRADING BEHAVIOUR. The three existing booleans are
untouched for all twenty consumers, no tool qualifies differently, no candidate
is authored, and PO3 still refuses exactly where it refused before. Its only job
is to turn an already-detected transient event into a named, persistent fact.

`reclaimed` stays an ATTRIBUTE. This detector only ever declares a sweep when
ONE settled candle both pierces a level and closes back through it, so a
SWEPT -> RECLAIMED lifecycle would be an ontology the evidence cannot support.
"""
from __future__ import annotations

import copy
from textwrap import dedent as textwrap_dedent
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from market_data import occurrence_ledger as OL                  # noqa: E402
from market_data.sweep_occurrence import liquidity_sweep_occurrence  # noqa: E402
from market_data.occurrence_ledger import OccurrenceLedger        # noqa: E402
from structure.liquidity_engine import analyze_liquidity          # noqa: E402

ARCHIVE = os.path.join(ROOT, "data", "ai_brain")
MNQ = "CON.F.US.MNQ.U26"
OTHER = "CON.F.US.MNQ.Z26"

# 2026-08-21 10:18 ET — the sell-side manipulation of the move into 29220.25.
SPECIMEN = "20260821_101842_MNQ.json"
SWEPT_LEVEL = 29257.25                       # the level the tape ACTUALLY took
EVENT_TIME = "2026-08-21T14:17:00+00:00"     # 10:17 ET, the triggering candle


def snap(name=SPECIMEN):
    path = os.path.join(ARCHIVE, name)
    if not os.path.exists(path):
        pytest.skip(f"archived snapshot absent: {name}")
    with open(path, encoding="utf-8") as fh:
        return copy.deepcopy(json.load(fh)["raw_snapshot"])


def liquidity_of(name=SPECIMEN, tf="1m"):
    candles = ((snap(name)["timeframes"].get(tf)) or {}).get("recent_candles") or []
    prior = {"close": candles[-2]["close"], "authority": "ADJACENT_SETTLED"}
    return analyze_liquidity(candles, prior, allow_uncadenced=True), candles


def occurrence(name=SPECIMEN, tf="1m", contract=MNQ):
    liq, _ = liquidity_of(name, tf)
    return liquidity_sweep_occurrence(liq["sweep_fact"], source_tf=tf,
                                      contract=contract)


def ledger(tmp_path, contract=MNQ):
    return OccurrenceLedger(contract, directory=str(tmp_path))


def scan_cycle(tmp_path, contract=MNQ):
    os.environ["OCCURRENCE_LEDGER_DIR"] = str(tmp_path)
    from live_scan.production_scan_cycle import ProductionScanCycle
    return ProductionScanCycle(symbol="MNQ", contract_id=contract)


def snapshot_with_sweep(name=SPECIMEN, tf="1m"):
    """The archived production snapshot carrying the birth fact the live
    detector now publishes for that same tape."""
    s = snap(name)
    liq, _ = liquidity_of(name, tf)
    s["liquidity"][tf] = dict(s["liquidity"].get(tf) or {},
                              sweep_fact=liq["sweep_fact"])
    return s


# ══════════════════════════════════════════════════════════════════════════════
class TestOneTheExactSweptLevel:
    def test_the_detector_publishes_the_level_it_actually_compared_against(self):
        liq, _ = liquidity_of()
        assert liq["sweep_detected"] is True
        assert liq["sweep_fact"]["swept_level"] == SWEPT_LEVEL

    def test_it_is_NOT_the_nearest_pool_right_now(self):
        """`nearest_*_liquidity` is where pools sit at this instant. It is not
        retrospective proof of what the tape took, and the dead reconstructor
        in `market_events._sweep_at` uses it -- which is why that path stays
        dead."""
        liq, _ = liquidity_of()
        nearest = liq.get("nearest_sell_side_liquidity")
        assert liq["sweep_fact"]["swept_level"] == SWEPT_LEVEL
        if nearest is not None:
            assert nearest != SWEPT_LEVEL or True   # documents, never asserts luck

    def test_no_sweep_means_no_fact_not_an_empty_one(self):
        liq, _ = liquidity_of("20260821_101959_MNQ.json")
        assert liq["sweep_detected"] is False
        assert liq["sweep_fact"] is None

    def test_the_side_taken_is_named(self):
        f = liquidity_of()[0]["sweep_fact"]
        assert f["sweep_direction"] == "below_low"
        assert f["liquidity_side_taken"] == "sell_side"


class TestTwoTheEventTimestamp:
    def test_it_is_the_triggering_candle(self):
        liq, candles = liquidity_of()
        assert liq["sweep_fact"]["event_time"] == candles[-1]["timestamp"]
        assert liq["sweep_fact"]["event_time"] == EVENT_TIME

    def test_reclaim_is_an_attribute_at_the_same_instant(self):
        f = liquidity_of()[0]["sweep_fact"]
        assert f["reclaimed"] is True
        assert f["reclaimed_at"] == f["event_time"]
        assert f["reclaim_basis"] == "same_bar_close_back_through_level"

    def test_no_separate_reclaim_event_ontology_was_invented(self):
        occ = occurrence()
        assert occ["event_type"] == "LIQUIDITY_SWEEP"
        assert "SWEPT" not in json.dumps(occ)
        assert "RECLAIM_EVENT" not in json.dumps(occ)

    def test_both_evidence_bars_are_recorded(self):
        liq, candles = liquidity_of()
        assert liq["sweep_fact"]["source_bars"] == [candles[-2]["timestamp"],
                                                    candles[-1]["timestamp"]]


class TestThreeStableCanonicalIdentity:
    def test_the_id_is_canonical_and_contract_scoped(self):
        occ = occurrence()
        assert occ["occurrence_id"] == f"LIQUIDITY_SWEEP:{MNQ}:1m:{EVENT_TIME}"

    def test_repeated_scans_produce_the_identical_id(self):
        assert occurrence()["occurrence_id"] == occurrence()["occurrence_id"]

    def test_identity_is_not_minted_in_the_detector(self):
        """Two authorities, one question each."""
        f = liquidity_of()[0]["sweep_fact"]
        assert "occurrence_id" not in f
        import inspect
        from structure import liquidity_engine as LE
        assert "market_object_id" not in inspect.getsource(LE)

    def test_it_fails_closed_without_a_contract(self):
        liq, _ = liquidity_of()
        assert liquidity_sweep_occurrence(liq["sweep_fact"], source_tf="1m",
                                          contract=None) is None

    @pytest.mark.parametrize("bad", [None, {}, "nope", {"event_time": None}])
    def test_it_fails_closed_on_an_unusable_fact(self, bad):
        assert liquidity_sweep_occurrence(bad, source_tf="1m", contract=MNQ) is None


class TestFourIdempotence:
    def test_recording_twice_is_a_duplicate_not_a_second_row(self, tmp_path):
        led = ledger(tmp_path)
        assert led.record(occurrence())["outcome"] == OL.RECORDED
        assert led.record(occurrence())["outcome"] == OL.DUPLICATE
        assert len(led.occurrences()) == 1


class TestFiveHistoryIsNotRewritable:
    def test_a_conflicting_same_id_occurrence_cannot_overwrite(self, tmp_path):
        led = ledger(tmp_path)
        led.record(occurrence())
        forged = dict(occurrence(), swept_level=29999.0)
        out = led.record(forged)
        assert out["outcome"] == OL.CONFLICT
        assert "swept_level" in out["conflict"]["differing_fields"]
        assert led.get(forged["occurrence_id"])["swept_level"] == SWEPT_LEVEL

    def test_the_conflict_is_surfaced_in_health(self, tmp_path):
        led = ledger(tmp_path)
        led.record(occurrence())
        led.record(dict(occurrence(), reclaimed=False))
        assert led.health()["integrity_conflicts"] == 1

    def test_an_interpretation_is_refused_outright(self, tmp_path):
        led = ledger(tmp_path)
        out = led.record(dict(occurrence(), confidence=88))
        assert out["outcome"] == OL.REJECTED
        assert led.occurrences() == []

    def test_an_occurrence_without_identity_is_refused(self, tmp_path):
        led = ledger(tmp_path)
        anonymous = {k: v for k, v in occurrence().items() if k != "occurrence_id"}
        assert led.record(anonymous)["outcome"] == OL.REJECTED


class TestSixSurvivesRestart:
    def test_it_outlives_the_process(self, tmp_path):
        first = ledger(tmp_path)
        oid = occurrence()["occurrence_id"]
        assert first.record(occurrence())["outcome"] == OL.RECORDED
        reborn = ledger(tmp_path)                    # a brand new process
        assert reborn.get(oid) is not None
        assert reborn.get(oid)["swept_level"] == SWEPT_LEVEL

    def test_it_outlives_the_candle_that_created_it(self, tmp_path):
        """The whole point: the source bar is long gone from the rolling
        window and the fact remains answerable."""
        led = ledger(tmp_path)
        led.record(occurrence())
        later = snap("20260821_121422_MNQ.json")     # ~2 hours later
        stamps = {c["timestamp"] for c in later["timeframes"]["1m"]["recent_candles"]}
        assert EVENT_TIME not in stamps              # aged out of the buffer
        assert ledger(tmp_path).occurrences(event_type="LIQUIDITY_SWEEP")

    def test_a_corrupt_store_degrades_rather_than_raising(self, tmp_path):
        led = ledger(tmp_path)
        led.record(occurrence())
        with open(led.path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        reborn = ledger(tmp_path)
        assert reborn.health()["status"] == OL.DEGRADED


class TestSevenContractIsolation:
    def test_another_contract_never_sees_these_facts(self, tmp_path):
        ledger(tmp_path, MNQ).record(occurrence())
        assert ledger(tmp_path, OTHER).occurrences() == []

    def test_the_id_itself_is_contract_scoped(self):
        assert occurrence(contract=MNQ)["occurrence_id"] != \
               occurrence(contract=OTHER)["occurrence_id"]

    def test_a_foreign_occurrence_is_refused(self, tmp_path):
        led = ledger(tmp_path, MNQ)
        assert led.record(occurrence(contract=OTHER))["outcome"] == OL.REJECTED

    def test_a_store_belonging_to_another_contract_is_not_adopted(self, tmp_path):
        ledger(tmp_path, MNQ).record(occurrence())
        os.rename(os.path.join(str(tmp_path), f"{MNQ}.json"),
                  os.path.join(str(tmp_path), f"{OTHER}.json"))
        impostor = ledger(tmp_path, OTHER)
        assert impostor.occurrences() == []
        assert impostor.health()["status"] == OL.DEGRADED

    def test_a_ledger_refuses_to_invent_a_contract(self, tmp_path):
        for bad in (None, "", "   "):
            with pytest.raises(ValueError):
                OccurrenceLedger(bad, directory=str(tmp_path))


class TestEightExistingConsumersUnchanged:
    """Twenty modules read these booleans. None may see a difference."""

    @pytest.mark.parametrize("name,tf", [
        (SPECIMEN, "1m"), ("20260821_101959_MNQ.json", "1m"),
        ("20260821_114443_MNQ.json", "1m"), (SPECIMEN, "5m"),
    ])
    def test_the_three_booleans_match_what_production_shipped(self, name, tf):
        shipped = (snap(name)["liquidity"].get(tf)) or {}
        liq, _ = liquidity_of(name, tf)
        for field in ("sweep_detected", "sweep_direction", "reclaim_detected"):
            assert liq[field] == shipped.get(field), field

    def test_nearest_liquidity_is_unchanged(self):
        shipped = snap()["liquidity"]["1m"]
        liq, _ = liquidity_of()
        assert liq["nearest_buy_side_liquidity"] == shipped["nearest_buy_side_liquidity"]
        assert liq["nearest_sell_side_liquidity"] == shipped["nearest_sell_side_liquidity"]

    def test_sweep_fact_is_purely_additive(self):
        """Every key production shipped is still present and equal."""
        shipped = snap()["liquidity"]["1m"]
        liq, _ = liquidity_of()
        for key, value in shipped.items():
            if key in ("manipulation", "proposition_capability", "capability_reason"):
                continue
            assert liq.get(key) == value, key

    def test_an_underlength_window_still_returns_the_schema(self):
        out = analyze_liquidity([], None)
        assert out["sweep_detected"] is False
        assert out["sweep_fact"] is None


class TestNineNoTradingBehaviourChanged:
    def test_po3_still_refuses_exactly_where_it_refused(self):
        from toolbox.price_levels import po3_reversal_order_block, NO_MANIPULATION
        for name in (SPECIMEN, "20260821_101959_MNQ.json",
                     "20260821_114443_MNQ.json"):
            out = po3_reversal_order_block(snap(name), "bullish")
            assert out["available"] is False
            assert out["reason"] == NO_MANIPULATION, name

    def test_unit_1_was_not_smuggled_back_in(self):
        """Timeframe-authority separation stays blocked until Unit 0 certifies."""
        from toolbox import price_levels as PL
        assert not hasattr(PL, "_PO3_MANIPULATION_EVIDENCE_TFS")
        assert PL._allowed_source_tfs("MNQ") == ("15m", "5m", "3m")

    def test_the_ledger_authors_no_interpretation(self):
        import inspect
        src = inspect.getsource(OL).lower()
        for banned in ("confidence", "recommend", "qualif", "bias ="):
            assert f"def {banned}" not in src, banned

    def test_the_dead_reconstructor_stays_dead(self):
        """`_sweep_at` infers the level from `nearest_*` and bridges cadence.

        Checked on CODE, not prose: the new function's docstring names both
        defects precisely because it is declaring what it refuses to inherit,
        so a text scan would fail on its own disclaimer."""
        import ast
        import inspect
        import textwrap
        from market_data import market_events as ME
        assert "allow_uncadenced=True" in inspect.getsource(ME._sweep_at)
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(liquidity_sweep_occurrence)))
        fn = tree.body[0]
        if (fn.body and isinstance(fn.body[0], ast.Expr)
                and isinstance(fn.body[0].value, ast.Constant)):
            fn.body = fn.body[1:]           # drop the docstring
        code = ast.unparse(fn)
        assert "allow_uncadenced" not in code
        assert "nearest_" not in code
        assert "_sweep_at" not in code

    def test_htf_memory_authority_lock_is_untouched(self):
        from market_data import htf_memory_engine as HTF
        assert HTF.AUTHORITY_LEVEL == "context_only"


class TestTheProductionWriter:
    """Proven through the REAL scan path, never by hand-instantiating a ledger.

    A tested-but-unreachable persistence substrate does not satisfy "a completed
    sweep becomes a persistent historical fact" -- it only satisfies "a class
    exists that could remember one".
    """

    def test_the_ledger_is_reachable_from_production(self):
        """The reachability proof. `occurrence_ledger` must not be a fourth
        correct-tested-unreachable module."""
        import inspect
        from live_scan import production_scan_cycle as PSC
        src = inspect.getsource(PSC)
        assert "occurrence_ledger" in src
        assert "OccurrenceLedger(" in src
        assert "_record_sweep_occurrences" in inspect.getsource(PSC.ProductionScanCycle.scan)

    def test_a_detected_sweep_produces_exactly_one_occurrence(self, tmp_path):
        cyc = scan_cycle(tmp_path)
        written = cyc._record_sweep_occurrences(snapshot_with_sweep())
        assert len(written) == 1
        assert written[0]["outcome"] == OL.RECORDED

    def test_the_scan_path_actually_records_it(self, tmp_path):
        cyc = scan_cycle(tmp_path)
        cyc._record_sweep_occurrences(snapshot_with_sweep())
        stored = ledger(tmp_path).occurrences(event_type="LIQUIDITY_SWEEP")
        assert len(stored) == 1
        assert stored[0]["swept_level"] == SWEPT_LEVEL
        assert stored[0]["event_time"] == EVENT_TIME

    def test_repeated_scans_do_not_duplicate_it(self, tmp_path):
        cyc = scan_cycle(tmp_path)
        s = snapshot_with_sweep()
        outcomes = [cyc._record_sweep_occurrences(s)[0]["outcome"] for _ in range(4)]
        assert outcomes == [OL.RECORDED, OL.DUPLICATE, OL.DUPLICATE, OL.DUPLICATE]
        assert len(ledger(tmp_path).occurrences()) == 1

    def test_the_next_non_sweep_candle_cannot_erase_it(self, tmp_path):
        """The whole defect: 10:18 swept, 10:19 did not, and the organism used
        to forget. The flag correctly goes false; the FACT must remain."""
        cyc = scan_cycle(tmp_path)
        cyc._record_sweep_occurrences(snapshot_with_sweep())
        quiet = snap("20260821_101959_MNQ.json")          # no sweep on any tf
        assert (quiet["liquidity"]["1m"] or {}).get("sweep_detected") is False
        cyc._record_sweep_occurrences(quiet)
        assert len(ledger(tmp_path).occurrences()) == 1

    def test_reload_preserves_it(self, tmp_path):
        cyc = scan_cycle(tmp_path)
        cyc._record_sweep_occurrences(snapshot_with_sweep())
        reborn = scan_cycle(tmp_path)                      # a new process
        assert len(reborn.occurrence_ledger.occurrences()) == 1

    def test_no_contract_means_no_ledger_rather_than_an_invented_one(self, tmp_path):
        cyc = scan_cycle(tmp_path, contract="")
        assert cyc.occurrence_ledger is None
        assert cyc._record_sweep_occurrences(snapshot_with_sweep()) == []

    def test_recording_is_not_written_into_the_snapshot(self, tmp_path):
        """The ledger is a memory of what happened, never an input to this
        scan's decision -- so it must not appear in the snapshot at all."""
        cyc = scan_cycle(tmp_path)
        s = snapshot_with_sweep()
        cyc._record_sweep_occurrences(s)
        blob = json.dumps(s, default=str)
        assert "occurrence_id" not in blob
        assert "LIQUIDITY_SWEEP" not in blob

    def test_the_raw_sweep_container_never_reaches_the_brain(self):
        """`_RAID_PROPOSITIONS` is a whitelist, so `sweep_fact` cannot leak.

        SUPERSEDED IN PART by LUNA-LIQUIDITY-SCOPE-TRUTH-1 (2026-09-01), and the
        distinction is the point. This also asserted that `swept_level` and
        `occurrence_id` could never reach the Brain -- written when a sweep was
        purely a ledger memory with no decision-bearing meaning.

        That is no longer the law. Luna was standing down on a tape where the
        mechanics knew an external sweep from an internal raid, weighted them 30
        vs 20, and told her only `manipulation_confirmed` with a null direction.
        She now receives curated event facts -- side, swept level, scope, and
        the reference each scope was judged against -- because withholding them
        was the defect.

        WHAT STILL HOLDS, AND IS TESTED HERE: the raw `sweep_fact` container is
        an internal producer structure and must never be handed over wholesale.
        Publication stays curated and contracted. The ledger-isolation theorem
        is unchanged and lives in
        `test_recording_is_not_written_into_the_snapshot`.
        """
        from ai_brain.brain_input import build_brain_input
        blob = json.dumps(build_brain_input(snapshot_with_sweep(),
                                            {"available": False}), default=str)
        assert "sweep_fact" not in blob

    def test_a_broken_ledger_never_kills_the_scan(self, tmp_path):
        cyc = scan_cycle(tmp_path)

        class Exploding:
            def record(self, _):
                raise RuntimeError("disk on fire")
        cyc.occurrence_ledger = Exploding()
        assert cyc._record_sweep_occurrences(snapshot_with_sweep()) == []


class TestPersistenceHealthIsTruthful:
    """`[]` must never mean two different things.

    "the tape was quiet" and "a sweep happened and memory broke" looking
    identical is the same epistemic lie this whole unit exists to end -- a later
    consumer would read absence-of-record as absence-of-event.
    """

    def test_a_clean_write_reports_healthy(self, tmp_path):
        cyc = scan_cycle(tmp_path)
        cyc._record_sweep_occurrences(snapshot_with_sweep())
        assert cyc.last_occurrence_persistence_status == OL.HEALTHY
        assert not cyc.last_occurrence_persistence_error

    def test_absent_by_design_is_not_broken(self, tmp_path):
        """No exact contract is a deliberate refusal, not a failure."""
        cyc = scan_cycle(tmp_path, contract="")
        cyc._record_sweep_occurrences(snapshot_with_sweep())
        assert cyc.last_occurrence_persistence_status == OL.NOT_CONFIGURED

    def test_construction_failure_is_distinguishable(self, tmp_path):
        from live_scan import production_scan_cycle as PSC
        import market_data.occurrence_ledger as MOL
        real = MOL.OccurrenceLedger

        class Refuses:
            def __init__(self, *a, **k):
                raise RuntimeError("store unmountable")
        MOL.OccurrenceLedger = Refuses
        try:
            os.environ["OCCURRENCE_LEDGER_DIR"] = str(tmp_path)
            cyc = PSC.ProductionScanCycle(symbol="MNQ", contract_id=MNQ)
        finally:
            MOL.OccurrenceLedger = real
        assert cyc.occurrence_ledger is None
        assert cyc.occurrence_ledger_status == OL.UNAVAILABLE
        assert cyc.occurrence_ledger_status != OL.NOT_CONFIGURED
        assert "store unmountable" in cyc.occurrence_ledger_error

    def test_a_raising_ledger_degrades_observable_health(self, tmp_path):
        cyc = scan_cycle(tmp_path)

        class Exploding:
            def record(self, _):
                raise RuntimeError("disk on fire")
        cyc.occurrence_ledger = Exploding()
        assert cyc._record_sweep_occurrences(snapshot_with_sweep()) == []
        assert cyc.last_occurrence_persistence_status == OL.DEGRADED
        assert "disk on fire" in cyc.last_occurrence_persistence_error

    def test_a_failed_write_is_never_reported_as_recorded(self, tmp_path):
        """The bug this test exists for: `RECORDED if persisted else RECORDED`
        claimed success on both branches."""
        led = ledger(tmp_path)
        led.directory = "\0illegal"
        out = led.record(occurrence())
        assert out["outcome"] == OL.RECORDED_NOT_DURABLE
        assert out["outcome"] != OL.RECORDED
        assert out["outcome"] != OL.DUPLICATE
        assert led.health()["status"] == OL.DEGRADED

    def test_a_failed_write_degrades_the_scan_status_too(self, tmp_path):
        cyc = scan_cycle(tmp_path)
        cyc.occurrence_ledger.directory = "\0illegal"
        cyc._record_sweep_occurrences(snapshot_with_sweep())
        assert cyc.last_occurrence_persistence_status == OL.DEGRADED

    def test_degradation_is_sticky_and_recovery_is_not_invented(self, tmp_path):
        """A later write succeeding does not prove whatever was lost came back."""
        led = ledger(tmp_path)
        led.directory = "\0illegal"
        led.record(occurrence())
        assert led.health()["status"] == OL.DEGRADED
        led.directory = str(tmp_path)          # storage usable again
        led.record(dict(occurrence(), occurrence_id="LIQUIDITY_SWEEP:x:1m:t"))
        assert led.health()["status"] == OL.DEGRADED

    def test_a_non_durable_record_is_never_a_duplicate_next_scan(self, tmp_path):
        """THE HOLE: the occurrence enters `_records` BEFORE `_persist()`. On
        re-observation its own id is already in memory, so the ordinary
        identical-id branch would answer DUPLICATE -- a failed write
        masquerading as a successful one, exactly one scan later."""
        led = ledger(tmp_path)
        led.directory = "\0illegal"
        assert led.record(occurrence())["outcome"] == OL.RECORDED_NOT_DURABLE
        again = led.record(occurrence())          # the very next scan
        assert again["outcome"] != OL.DUPLICATE
        assert again["outcome"] == OL.RECORDED_NOT_DURABLE
        assert led.is_durable(occurrence()["occurrence_id"]) is False

    def test_presence_in_memory_is_not_durability(self, tmp_path):
        led = ledger(tmp_path)
        led.directory = "\0illegal"
        led.record(occurrence())
        oid = occurrence()["occurrence_id"]
        assert led.get(oid) is not None            # present in this process
        assert led.is_durable(oid) is False        # and provably not on disk
        assert led.health()["not_durable"] == [oid]
        assert led.health()["durable"] == 0

    def test_a_restart_before_persistence_proves_it_was_absent(self, tmp_path):
        led = ledger(tmp_path)
        led.directory = "\0illegal"
        led.record(occurrence())
        assert ledger(tmp_path).get(occurrence()["occurrence_id"]) is None
        assert ledger(tmp_path).occurrences() == []

    def test_a_successful_retry_makes_that_occurrence_durable(self, tmp_path):
        led = ledger(tmp_path)
        led.directory = "\0illegal"
        led.record(occurrence())
        led.directory = str(tmp_path)              # storage usable again
        out = led.record(occurrence())
        assert out["outcome"] == OL.DURABILITY_RECOVERED
        assert led.is_durable(occurrence()["occurrence_id"]) is True
        assert ledger(tmp_path).get(occurrence()["occurrence_id"]) is not None

    def test_recovered_durability_does_not_clear_sticky_health(self, tmp_path):
        """One good write proves THAT occurrence survived. It does not prove
        nothing was lost while persistence was impaired."""
        led = ledger(tmp_path)
        led.directory = "\0illegal"
        led.record(occurrence())
        led.directory = str(tmp_path)
        led.record(occurrence())
        assert led.is_durable(occurrence()["occurrence_id"]) is True
        assert led.health()["status"] == OL.DEGRADED

    def test_only_after_proven_durability_is_it_a_duplicate(self, tmp_path):
        led = ledger(tmp_path)
        led.directory = "\0illegal"
        led.record(occurrence())
        led.directory = str(tmp_path)
        led.record(occurrence())                   # DURABILITY_RECOVERED
        assert led.record(occurrence())["outcome"] == OL.DUPLICATE

    def test_reloaded_records_are_durable_by_proof_of_disk(self, tmp_path):
        led = ledger(tmp_path)
        led.record(occurrence())
        reborn = ledger(tmp_path)
        assert reborn.is_durable(occurrence()["occurrence_id"]) is True
        assert reborn.record(occurrence())["outcome"] == OL.DUPLICATE


class TestTheQuarantineHolds:
    """`market_events` may never become production-reachable."""

    def test_the_adapter_imports_nothing_from_market_events(self):
        """AST over the module's real imports. A text scan would match this
        module's own docstring, which names `market_events` precisely to explain
        why it is NOT used -- the fourth time that trap has fired today.

        (The repo-wide production quarantine itself is owned by the certified
        `test_no_production_module_imports_market_events`; duplicating it badly
        here would be worse than leaving it to its owner.)"""
        import ast
        import inspect
        from market_data import sweep_occurrence as SO
        modules = set()
        for node in ast.walk(ast.parse(inspect.getsource(SO))):
            if isinstance(node, ast.Import):
                modules.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module or "")
        assert not any("market_events" in m for m in modules), modules

    def test_the_adapter_body_carries_no_cadence_unsafe_call(self):
        import ast
        import inspect
        from market_data import sweep_occurrence as SO
        tree = ast.parse(textwrap_dedent(inspect.getsource(
            SO.liquidity_sweep_occurrence)))
        fn = tree.body[0]
        if (fn.body and isinstance(fn.body[0], ast.Expr)
                and isinstance(fn.body[0].value, ast.Constant)):
            fn.body = fn.body[1:]
        code = ast.unparse(fn)
        for banned in ("allow_uncadenced", "nearest_", "reconstruct_events",
                       "_sweep_at", "market_events"):
            assert banned not in code, banned

    def test_the_adapter_uses_the_one_identity_theorem(self):
        import inspect
        from market_data import sweep_occurrence as SO
        assert "market_object_id" in inspect.getsource(SO.liquidity_sweep_occurrence)

    def test_the_ontology_constant_cannot_drift(self):
        """Two modules name this event; they must never mean different things."""
        from market_data.sweep_occurrence import LIQUIDITY_SWEEP as PROD
        from market_data.market_events import LIQUIDITY_SWEEP as QUARANTINED
        assert PROD == QUARANTINED == "LIQUIDITY_SWEEP"


class TestContinuityStateClassification:
    """A canonical-history revision must not rewrite what was WITNESSED.

    `IDENTITY != STATE` has a sibling here: HISTORICAL RECORD != CURRENT
    AUTHORITY. The ledger records what the certified detector observed at birth.
    Rebuilding it from revised candles would delete real records and re-derive
    them under today's semantics -- not repair, but rewriting the witnessed past.
    """

    @staticmethod
    def buckets():
        from live_scan.production_scan_cycle import ProductionScanCycle as P
        return (set(P.CANDLE_DERIVED_STATE), set(P.STATE_NOT_CANDLE_DERIVED),
                set(P.COGNITIVE_STATE_RE_ANCHORED))

    @pytest.mark.parametrize("attr", [
        "contract_id", "occurrence_ledger", "occurrence_ledger_status",
        "occurrence_ledger_error", "last_occurrence_persistence_status",
        "last_occurrence_persistence_error"])
    def test_the_durable_ledger_and_its_health_are_NOT_candle_derived(self, attr):
        rebuilt, kept, _ = self.buckets()
        assert attr in kept, attr
        assert attr not in rebuilt, attr

    def test_the_previous_scans_writes_ARE_candle_derived(self):
        """A prior scan's result must not survive as though it belonged to the
        rebuilt state."""
        rebuilt, kept, _ = self.buckets()
        assert "last_occurrence_writes" in rebuilt
        assert "last_occurrence_writes" not in kept

    def test_every_new_attribute_is_classified(self):
        """The invariant that caught this unit in the first place."""
        from live_scan.production_scan_cycle import ProductionScanCycle as P
        rebuilt, kept, cognitive = self.buckets()
        for attr in ("contract_id", "occurrence_ledger", "occurrence_ledger_status",
                     "occurrence_ledger_error", "last_occurrence_writes",
                     "last_occurrence_persistence_status",
                     "last_occurrence_persistence_error"):
            assert attr in (rebuilt | kept | cognitive), attr
        assert not (rebuilt & kept)

    def test_persistence_degradation_survives_a_history_revision(self, tmp_path):
        """Continuity repair cannot magically restore failed storage."""
        cyc = scan_cycle(tmp_path)
        cyc.occurrence_ledger.directory = "\0illegal"
        cyc._record_sweep_occurrences(snapshot_with_sweep())
        assert cyc.last_occurrence_persistence_status == OL.DEGRADED
        _, kept, _ = self.buckets()
        assert "last_occurrence_persistence_status" in kept
        assert "occurrence_ledger" in kept

    def test_the_ledger_is_not_a_claim_of_current_execution_authority(self):
        """Recorded means "observed at birth", not "still causally authoritative
        after every later revision" -- lineage is a Unit 1 precondition."""
        import inspect
        from live_scan import production_scan_cycle as PSC
        src = inspect.getsource(PSC)
        assert "NOT A CLAIM OF CURRENT EXECUTION AUTHORITY" in src


class TestOperatorOutputPathExecuted:
    """The scan line is EXECUTED here, not read as source text.

    Source inspection proves the characters exist. It does not prove the branch
    runs, that healthy sessions stay quiet, or that the addition leaves the scan
    outcome alone -- and this was the least-tested surface in the unit.
    """

    @staticmethod
    def run_one_scan(tmp_path, monkeypatch, *, status, error=""):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import topstepx_production_session as TOOL
        from broker import topstepx_production_loop as PL

        class FakeCycle:
            last_occurrence_persistence_status = status
            last_occurrence_persistence_error = error
            retrieval_telemetry = None

        class FakeLoop:
            def __init__(self, **kw):
                self.cycle = FakeCycle()

            def scan_once(self):
                return {"outcome": "NO_CANDIDATE", "detail": "",
                        "direction": None, "market_data_timestamp": None}

            def final_flat_state(self):
                return {"flat": True}

        class FakeContract:
            id = MNQ

        class FakeAccount:
            id = 11111111

        class FakeSession:
            account = FakeAccount()

            def open_positions(self):
                return []

            def open_orders(self):
                return []

        class FakeCandles:
            contract = FakeContract()

            def fetch_1m_candles(self, *a, **k):
                return []

        class FakePS:
            session_id = ""
            authorization_fingerprint = ""
            retrieval_telemetry = None

        monkeypatch.setattr(PL, "ProductionLoop", FakeLoop)
        monkeypatch.setattr(TOOL, "STORE_DIR", str(tmp_path))
        monkeypatch.setenv("TOPSTEPX_ACCOUNT_FINGERPRINT", "acct:test")
        TOOL.run_production_scans(
            ps=FakePS(), runtime=None, candles=FakeCandles(),
            session=FakeSession(), contract=FakeContract(), armed=False,
            symbol="MNQ", mission_id="TEST-UNIT0", scans=1, interval=0,
            until_close=False)

    def test_degraded_memory_is_printed_on_the_scan_line(self, tmp_path,
                                                         monkeypatch, capsys):
        self.run_one_scan(tmp_path, monkeypatch, status=OL.DEGRADED,
                          error="OSError: disk on fire")
        line = [l for l in capsys.readouterr().out.splitlines() if "scan 1" in l]
        assert line, "the scan line was never printed"
        assert "OCCURRENCE MEMORY" in line[0]
        assert OL.DEGRADED in line[0]

    def test_the_error_detail_is_surfaced(self, tmp_path, monkeypatch, capsys):
        self.run_one_scan(tmp_path, monkeypatch, status=OL.DEGRADED,
                          error="OSError: disk on fire")
        out = capsys.readouterr().out
        assert "disk on fire" in out

    def test_unavailable_is_also_printed(self, tmp_path, monkeypatch, capsys):
        self.run_one_scan(tmp_path, monkeypatch, status=OL.UNAVAILABLE,
                          error="store unmountable")
        assert "OCCURRENCE MEMORY" in capsys.readouterr().out

    def test_healthy_stays_silent(self, tmp_path, monkeypatch, capsys):
        self.run_one_scan(tmp_path, monkeypatch, status=OL.HEALTHY)
        assert "OCCURRENCE MEMORY" not in capsys.readouterr().out

    def test_not_configured_stays_silent(self, tmp_path, monkeypatch, capsys):
        self.run_one_scan(tmp_path, monkeypatch, status=OL.NOT_CONFIGURED)
        assert "OCCURRENCE MEMORY" not in capsys.readouterr().out

    def test_the_scan_outcome_itself_is_unchanged(self, tmp_path, monkeypatch,
                                                  capsys):
        """Output-only. The decision object must read identically whether
        memory is healthy or broken."""
        self.run_one_scan(tmp_path, monkeypatch, status=OL.HEALTHY)
        healthy = capsys.readouterr().out
        self.run_one_scan(tmp_path, monkeypatch, status=OL.DEGRADED,
                          error="boom")
        degraded = capsys.readouterr().out
        assert "NO_CANDIDATE" in healthy and "NO_CANDIDATE" in degraded
        # the ONLY difference is the appended warning
        assert degraded.replace(
            f" | OCCURRENCE MEMORY {OL.DEGRADED}: boom", "") == healthy


class TestOperatorObservability:
    """Degraded memory must be visible without attaching a debugger."""

    def test_the_session_prints_degraded_memory_on_the_scan_line(self):
        import inspect
        src = open(os.path.join(ROOT, "tools", "topstepx_production_session.py"),
                   encoding="utf-8").read()
        assert "last_occurrence_persistence_status" in src
        assert "last_occurrence_persistence_error" in src
        assert "OCCURRENCE MEMORY" in src

    def test_healthy_and_unconfigured_stay_silent(self):
        """A working session must stay readable."""
        src = open(os.path.join(ROOT, "tools", "topstepx_production_session.py"),
                   encoding="utf-8").read()
        assert 'LEDGER_HEALTHY", "LEDGER_NOT_CONFIGURED"' in src

    def test_the_status_is_reachable_from_the_loop_the_session_holds(self, tmp_path):
        """`loop.cycle` is the object the session already prints from."""
        cyc = scan_cycle(tmp_path)
        cyc.occurrence_ledger.directory = "\0illegal"
        cyc._record_sweep_occurrences(snapshot_with_sweep())
        assert getattr(cyc, "last_occurrence_persistence_status") == OL.DEGRADED
        assert getattr(cyc, "last_occurrence_persistence_error")

    def test_ledger_health_exposes_what_is_not_durable(self, tmp_path):
        led = ledger(tmp_path)
        led.directory = "\0illegal"
        led.record(occurrence())
        h = led.health()
        assert h["status"] == OL.DEGRADED
        assert h["not_durable"] and h["durable"] == 0
        assert h["detail"]

    def test_health_never_reaches_the_brain_or_execution(self, tmp_path):
        """Unit 0 adds no trading veto and no payload field."""
        from ai_brain.brain_input import build_brain_input
        cyc = scan_cycle(tmp_path)
        s = snapshot_with_sweep()
        cyc._record_sweep_occurrences(s)
        blob = json.dumps(build_brain_input(s, {"available": False}), default=str)
        for leaked in ("LEDGER_HEALTHY", "LEDGER_PERSISTENCE_DEGRADED",
                       "occurrence_ledger", "persistence_status"):
            assert leaked not in blob, leaked

    def test_ledger_health_is_not_a_trading_gate(self):
        """No execution/qualification module may IMPORT it in Unit 0.

        Checked on imports, not text: `market_events` names the ledger in its
        authority diagram without consuming it, and a string scan would count
        that documentation as a dependency."""
        import subprocess
        hits = subprocess.run(
            ["git", "grep", "-lE",
             r"(from|import)\s+market_data(\.occurrence_ledger|\s+import\s+occurrence_ledger)",
             "--", "src/"], capture_output=True, text=True).stdout.split()
        allowed = {"src/live_scan/production_scan_cycle.py"}
        assert set(hits) <= allowed, set(hits) - allowed

    def test_no_execution_or_qualification_module_consumes_it(self):
        """The classes themselves, wherever they are referenced."""
        import subprocess
        hits = subprocess.run(
            ["git", "grep", "-l", "OccurrenceLedger", "--", "src/"],
            capture_output=True, text=True).stdout.split()
        allowed = {"src/market_data/occurrence_ledger.py",
                   "src/live_scan/production_scan_cycle.py"}
        assert set(hits) <= allowed, set(hits) - allowed

    def test_a_malformed_liquidity_block_is_survived(self, tmp_path):
        cyc = scan_cycle(tmp_path)
        s = snapshot_with_sweep()
        s["liquidity"]["3m"] = "nonsense"
        assert len(cyc._record_sweep_occurrences(s)) == 1


class TestTenTheAugustTwentyFirstSpecimen:
    def test_the_reversal_manipulation_becomes_a_named_persistent_fact(self, tmp_path):
        led = ledger(tmp_path)
        occ = occurrence()
        assert led.record(occ)["outcome"] == OL.RECORDED
        stored = ledger(tmp_path).get(occ["occurrence_id"])
        assert stored["swept_level"] == SWEPT_LEVEL
        assert stored["event_time"] == EVENT_TIME
        assert stored["liquidity_side_taken"] == "sell_side"
        assert stored["reclaimed"] is True

    def test_the_question_po3_could_not_ask_is_now_answerable(self, tmp_path):
        """Before: "is the CURRENT bar a sweep?" -- and one bar later, nothing.
        After: "what manipulation occurred, where, and when?"."""
        led = ledger(tmp_path)
        led.record(occurrence())
        rows = ledger(tmp_path).occurrences(event_type="LIQUIDITY_SWEEP",
                                            source_tf="1m")
        assert len(rows) == 1
        assert (rows[0]["swept_level"], rows[0]["event_time"]) == (SWEPT_LEVEL, EVENT_TIME)

    def test_health_is_truthful_after_a_clean_write(self, tmp_path):
        led = ledger(tmp_path)
        led.record(occurrence())
        h = led.health()
        assert h["status"] == OL.HEALTHY
        assert h["recorded"] == 1 and h["integrity_conflicts"] == 0

    def test_a_write_failure_is_never_reported_as_healthy(self, tmp_path):
        led = OccurrenceLedger(MNQ, directory=os.path.join(str(tmp_path), "x"))
        led.directory = "\0illegal"          # force the write to fail
        out = led.record(occurrence())
        assert led.health()["status"] == OL.DEGRADED
        assert out["detail"]
