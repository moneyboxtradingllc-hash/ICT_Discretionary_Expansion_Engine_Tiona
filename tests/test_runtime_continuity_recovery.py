"""Step 2a — runtime continuity recovery, end to end.

V15 solved STARTUP continuity and made a runtime hole visible and fail-closed.
It did not make one RECOVERABLE: `repair_gaps()` existed with no production
caller and nothing consumed `rebuild_required` -- the same "method exists, tests
pass, production never calls it" shape as the V13 reconcilers, found by the
operator asking to see the caller.

The success criterion is deliberately NOT "repair_gaps() now has a caller":

    After an intraday historical gap, the system cannot resume authoritative
    cognition until BOTH canonical candle history AND every candle-derived
    state have converged onto the repaired history.

WHY A BOOLEAN WAS NOT ENOUGH. `rebuild_required` says a rebuild is owed; it
cannot say the rebuild that ran corresponds to the history that exists now.
Repaired candles with pre-repair trackers is the same lie under a new flag. So
history carries a REVISION that bumps only when the past is rewritten, and
derived state declares which revision it was built from. Cognition is permitted
only while they agree.

    canonical r1 / derived r1  -> eligible
    canonical r2 / derived r1  -> REFUSE
    canonical r2 / derived r2  -> eligible again

WHY REBUILD BY REPLACEMENT. Surgically removing the swings a hole fabricated
would require knowing which ones it fabricated. Re-deriving cannot leave a stale
object behind because the objects do not survive. Measured: ~6 ms per
`build_snapshot`, 1.33 s for a 240-bar warmup, and NO model call -- the Brain is
reached only under BRAIN_ECU_MODE, which is off.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.luna_candidate_producer import (                     # noqa: E402
    CandidateProducer, NoCandidate)
from data_feed import candle_continuity as CONT                  # noqa: E402
from live_scan.production_scan_cycle import ProductionScanCycle  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures",
                       "mnq_20260811_1420Z_1510Z_1m.json")
FIRST_MISSING = "2026-08-11T14:42:00+00:00"
LAST_MISSING = "2026-08-11T15:00:00+00:00"


def tape() -> list:
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)["bars"]


def holed() -> list:
    return [b for b in tape() if not (FIRST_MISSING <= b["timestamp"] <= LAST_MISSING)]


# ══════════════════════════════════════════════════════════════════════════════
class TestTheRevisionContract:
    """Growth is not revision. Only a rewritten past is."""

    def test_appending_at_the_tip_does_not_bump(self):
        history = CONT.HistoryRevision()
        assert history.observe(tape()[:30]) == 0
        assert history.observe(tape()[:40]) == 0, "ordinary growth bumped the revision"

    def test_inserting_before_the_tip_bumps(self):
        history = CONT.HistoryRevision()
        history.observe(holed())
        assert history.observe(tape()) == 1, "a rewritten past was not detected"

    def test_it_names_what_was_inserted(self):
        history = CONT.HistoryRevision()
        history.observe(holed())
        history.observe(tape())
        assert len(history.last_inserted) == 19
        assert FIRST_MISSING in history.last_inserted
        assert LAST_MISSING in history.last_inserted

    def test_repeated_observation_is_idempotent(self):
        history = CONT.HistoryRevision()
        history.observe(holed())
        history.observe(tape())
        assert history.observe(tape()) == 1, "a re-observation bumped again"

    def test_a_trimmed_window_is_not_a_rewrite(self):
        """A shorter view is a partial read, not a revision."""
        history = CONT.HistoryRevision()
        history.observe(tape())
        assert history.observe(tape()[-10:]) == 0

    def test_the_revision_is_monotonic(self):
        history = CONT.HistoryRevision()
        history.observe(holed())
        first = history.observe(tape())
        assert history.observe(holed()) == first, "the revision went backward"


class TestTheAuditedRebuildSet:
    """The set was ENUMERATED from a live instance, never inferred."""

    def test_every_named_attribute_actually_exists(self):
        cycle = ProductionScanCycle(symbol="MNQ")
        for name in ProductionScanCycle.CANDLE_DERIVED_STATE:
            assert hasattr(cycle, name) or name.startswith("_"), name

    def test_the_lazy_flip_registry_is_included(self):
        """Created inside scan(), so reading __init__ alone would have missed
        it -- which is why the set was introspected."""
        assert "_flip_registry" in ProductionScanCycle.CANDLE_DERIVED_STATE

    def test_the_two_sets_are_disjoint_and_cover_the_object(self):
        cycle = ProductionScanCycle(symbol="MNQ")
        rebuilt = set(ProductionScanCycle.CANDLE_DERIVED_STATE)
        kept = set(ProductionScanCycle.STATE_NOT_CANDLE_DERIVED)
        assert not (rebuilt & kept), rebuilt & kept
        cognitive = set(ProductionScanCycle.COGNITIVE_STATE_RE_ANCHORED)
        assert not (rebuilt & cognitive) and not (kept & cognitive)
        unclassified = set(vars(cycle)) - rebuilt - kept - cognitive - {
            "_history", "_derived_revision", "rebuilds"}
        assert not unclassified, f"unclassified stateful attributes: {unclassified}"

    def test_brain_state_is_RE_ANCHORED_not_merely_kept(self):
        """CONTRACT CORRECTED 2026-08-11 by audit.

        This test previously asserted that `stance_memory` and `thesis_engine`
        were NOT candle-derived and required nothing after a repair. That claim
        was wrong on both, by different routes:

            stance_memory -> history_summary() -> stance_history -> DIRECTLY
                             into Terra's prompt, persisted to disk
            thesis_engine -> snapshot["thesis_state"] -> consumed by
                             trade_qualification_engine, persisted to disk

        They are epistemically candle-derived even though they are not
        mechanically so. A belief formed while twenty minutes were missing is
        as stale as a swing computed across the same hole.
        """
        for name in ("stance_memory", "thesis_engine"):
            assert name in ProductionScanCycle.COGNITIVE_STATE_RE_ANCHORED
            assert name not in ProductionScanCycle.STATE_NOT_CANDLE_DERIVED


class TestRebuildIsReplacementNotCleaning:

    def test_every_candle_derived_object_is_a_NEW_instance(self):
        cycle = ProductionScanCycle(symbol="MNQ")
        before = {n: id(getattr(cycle, n, None))
                  for n in ("memory", "htf_engine", "setup_tracker",
                            "swing_tracker", "po3_stability", "expansion_stability")}
        cycle._rebuild_derived_state(tape(), 1)
        for name, was in before.items():
            assert id(getattr(cycle, name)) != was, f"{name} survived the rebuild"

    def test_brain_state_is_NOT_replaced(self):
        cycle = ProductionScanCycle(symbol="MNQ")
        stance, thesis = id(cycle.stance_memory), id(cycle.thesis_engine)
        cycle._rebuild_derived_state(tape(), 1)
        assert id(cycle.stance_memory) == stance
        assert id(cycle.thesis_engine) == thesis

    def test_the_rebuild_records_its_own_provenance(self):
        cycle = ProductionScanCycle(symbol="MNQ")
        record = cycle._rebuild_derived_state(tape(), 3)
        assert record["ok"] is True
        assert record["revision"] == 3 and record["bars"] == len(tape())
        assert cycle._derived_revision == 3
        assert cycle.rebuilds and cycle.rebuilds[-1] is record

    def test_it_reaches_no_model(self):
        """`build_snapshot` only calls the Brain under BRAIN_ECU_MODE."""
        import ai_brain.narrative_brain as NB
        calls = []
        original = NB.run_narrative_brain
        NB.run_narrative_brain = lambda *a, **k: calls.append(1)
        try:
            ProductionScanCycle(symbol="MNQ")._rebuild_derived_state(tape(), 1)
        finally:
            NB.run_narrative_brain = original
        assert calls == [], "the rebuild called the model"

    def test_a_failed_rebuild_leaves_the_revision_BEHIND(self):
        """Failing closed: the mismatch persists so the producer keeps refusing."""
        cycle = ProductionScanCycle(symbol="MNQ")
        record = cycle._rebuild_derived_state("not-a-tape", 5)
        assert record["ok"] is False and "error" in record
        assert cycle._derived_revision != 5
        assert cycle.derived_state_is_current() is False or cycle._history.revision == 0


class TestTradingStaysRefusedUntilBothConverge:

    def stale(self) -> dict:
        return {"derived_state": {"history_revision": 2, "derived_revision": 1,
                                  "current": False}}

    def test_a_stale_derived_state_refuses(self):
        with pytest.raises(NoCandidate) as caught:
            CandidateProducer._assert_derived_state_current(self.stale())
        assert caught.value.reason == "derived_state_stale"
        assert "r2" in str(caught.value) and "r1" in str(caught.value)

    def test_a_current_derived_state_permits(self):
        CandidateProducer._assert_derived_state_current(
            {"derived_state": {"history_revision": 2, "derived_revision": 2,
                               "current": True}})

    def test_a_snapshot_without_the_block_is_silent_not_refused(self):
        CandidateProducer._assert_derived_state_current({"timestamp": "t"})

    def test_a_malformed_block_fails_CLOSED(self):
        with pytest.raises(NoCandidate):
            CandidateProducer._assert_derived_state_current(
                {"derived_state": {"current": None}})

    def test_the_gate_is_WIRED_into_produce(self):
        import inspect
        source = inspect.getsource(CandidateProducer.produce)
        assert "_assert_derived_state_current" in source, \
            "the revision gate is defined but produce() never calls it"

    def test_the_reason_is_registered_for_tracing(self):
        from broker.luna_candidate_producer import _TRACE_STAGE
        assert "derived_state_stale" in _TRACE_STAGE


class TestTheRuntimeRepairCallerExists:
    """The finding that opened 2a: a helper with no production caller."""

    def test_the_loop_calls_repair(self):
        import inspect
        from broker import topstepx_production_loop as PL
        source = inspect.getsource(PL.ProductionLoop._scan_once)
        assert "_repair_history_if_holed" in source, \
            "the scan path never attempts runtime repair"

    def test_repair_is_attempted_before_the_scan_reads_the_tape(self):
        import inspect
        from broker import topstepx_production_loop as PL
        source = inspect.getsource(PL.ProductionLoop._scan_once)
        assert source.index("_repair_history_if_holed") < source.index("self.cycle.scan("), \
            "the cycle scanned the holed tape before repair was attempted"

    def test_the_repair_helper_calls_the_provider(self):
        import inspect
        from broker import topstepx_production_loop as PL
        source = inspect.getsource(PL.ProductionLoop._repair_history_if_holed)
        assert "repair_gaps" in source and "fetch_1m_candles" in source, \
            "repair must re-read: a call returning is not proof it worked"

    def test_a_provider_without_repair_degrades_quietly(self):
        import inspect
        from broker import topstepx_production_loop as PL
        source = inspect.getsource(PL.ProductionLoop._repair_history_if_holed)
        assert "getattr(self.candles" in source, \
            "a provider lacking repair_gaps must not raise"


class TestTheWholeSequence:
    """healthy -> hole -> refuse -> repair -> re-derive -> eligible."""

    def test_end_to_end_convergence(self):
        cycle = ProductionScanCycle(symbol="MNQ")

        # 1. healthy history, derived state current
        cycle._history.observe(holed())
        cycle._derived_revision = cycle._history.revision
        assert cycle.derived_state_is_current()

        # 2. the hole is visible and blocks a trade
        report = CONT.summarize(holed(), timeframe="1m")
        assert report["continuous"] is False
        with pytest.raises(NoCandidate):
            CandidateProducer._assert_candles_continuous(
                {"candle_continuity": report})

        # 3. repair: the past is rewritten
        revision = cycle._history.observe(tape())
        assert revision == 1
        assert cycle.derived_state_is_current() is False, \
            "repaired candles alone made the organism eligible again"

        # 4. candles are healthy but derived facts are NOT -- still refused
        assert CONT.summarize(tape(), timeframe="1m")["continuous"] is True
        with pytest.raises(NoCandidate):
            CandidateProducer._assert_derived_state_current(
                {"derived_state": {"history_revision": revision,
                                   "derived_revision": cycle._derived_revision,
                                   "current": False}})

        # 5. re-derive from the repaired tape
        record = cycle._rebuild_derived_state(tape(), revision)
        assert record["ok"] is True

        # 6. both converged -> eligible
        assert cycle.derived_state_is_current() is True
        CandidateProducer._assert_candles_continuous(
            {"candle_continuity": CONT.summarize(tape(), timeframe="1m")})
        CandidateProducer._assert_derived_state_current(
            {"derived_state": {"history_revision": revision,
                               "derived_revision": cycle._derived_revision,
                               "current": True}})

    def test_the_rebuilt_state_came_from_the_REPAIRED_tape(self):
        """Not merely that a rebuild ran -- that it saw the restored bars.

        29,805.0 existed only inside the hole, so a tracker that knows nothing
        above 29,800 was rebuilt from the wrong history.
        """
        cycle = ProductionScanCycle(symbol="MNQ")
        cycle._rebuild_derived_state(tape(), 1)
        state = cycle.swing_tracker.state()
        levels = [rec.get("level")
                  for bucket in (state.get("by_timeframe") or {}).values()
                  for rec in (bucket or {}).values() if isinstance(rec, dict)]
        highest = max([l for l in levels if l] or [0])
        assert highest > 29790, f"rebuilt from a tape that never saw the raid: {highest}"


class TestEveryCallSiteIsWired:
    """N2 escaped: nothing asserted that `scan()` CALLS the rebuild. That is the
    third time this project has shipped a gate whose call site was untested --
    the reconcilers, the continuity gate, now this. The lesson is being written
    down as a test rather than as a resolution."""

    def test_scan_calls_the_rebuild_when_history_is_revised(self):
        import inspect
        source = inspect.getsource(ProductionScanCycle.scan)
        assert "_rebuild_derived_state" in source, \
            "the rebuild is defined but scan() never calls it"
        assert "self._history.observe(" in source, \
            "scan() never observes the history revision"

    def test_the_rebuild_runs_before_the_snapshot_is_built(self):
        import inspect
        source = inspect.getsource(ProductionScanCycle.scan)
        assert source.index("_rebuild_derived_state") < source.index("build_snapshot("), \
            "a snapshot was built from state predating the repaired history"

    def test_the_revision_block_is_attached_for_the_producer(self):
        import inspect
        source = inspect.getsource(ProductionScanCycle.scan)
        assert 'snapshot["derived_state"]' in source


class TestEveryAuditedObjectIsActuallyReplaced:
    """N4 and N8 escaped: the replacement test covered six objects by name and
    silently omitted the lazy registry and the carried snapshot."""

    def rebuilt(self):
        cycle = ProductionScanCycle(symbol="MNQ")
        cycle._flip_registry = object()          # a live registry from before
        cycle.previous_snapshot = {"stale": True}
        cycle.previous_qual_state = "qualified"
        cycle.bars_in_state = 42
        cycle._rebuild_derived_state(tape(), 1)
        return cycle

    def test_the_lazy_flip_registry_is_discarded(self):
        assert self.rebuilt()._flip_registry is None or \
            type(self.rebuilt()._flip_registry).__name__ == "FlipRegistry"

    def test_the_carried_snapshot_is_discarded(self):
        assert self.rebuilt().previous_snapshot != {"stale": True}

    def test_the_carried_qualification_state_is_discarded(self):
        cycle = self.rebuilt()
        assert cycle.previous_qual_state is None
        assert cycle.bars_in_state == 0

    @pytest.mark.parametrize("name", [
        n for n in ProductionScanCycle.CANDLE_DERIVED_STATE
        if n not in ("previous_qual_state", "bars_in_state")])
    def test_every_named_object_is_reset_or_replaced(self, name):
        """Parametrised over the AUDITED list, so adding a name to the list
        without resetting it in the rebuild fails here automatically."""
        cycle = ProductionScanCycle(symbol="MNQ")
        sentinel = object()
        setattr(cycle, name, sentinel)
        cycle._rebuild_derived_state(tape(), 1)
        assert getattr(cycle, name, None) is not sentinel, f"{name} survived"


class TestRevisionMonotonicityAcrossManyRepairs:
    """N11 escaped: the monotonic test only ever reached revision 1, so
    `self.revision = 1` was indistinguishable from `+= 1`."""

    def test_three_successive_rewrites_increment(self):
        history = CONT.HistoryRevision()
        history.observe(tape()[:20] + tape()[40:])
        first = history.observe(tape()[:30] + tape()[40:])
        second = history.observe(tape())
        assert first == 1 and second == 2, f"{first}, {second}"

    def test_the_revision_never_repeats_for_distinct_rewrites(self):
        history = CONT.HistoryRevision()
        seen = []
        for cut in (20, 25, 30, 35):
            history.observe(tape()[:cut] + tape()[40:])
            seen.append(history.revision)
        assert seen == sorted(seen) and len(set(seen)) == len(seen), seen


class TestTheShortTapeGuardIsDistinct:
    """N12 escaped because the `derived == 0` check also catches an empty
    replay. The guard is defence in depth; this pins its distinct message so
    the two failure modes stay tellable apart in evidence."""

    def test_a_short_tape_names_the_lookback_requirement(self):
        cycle = ProductionScanCycle(symbol="MNQ")
        record = cycle._rebuild_derived_state(tape()[:5], 1)
        assert record["ok"] is False
        assert "bars" in record["error"] and "required" in record["error"]
        assert cycle._derived_revision == 0

    def test_an_empty_replay_is_reported_differently(self):
        cycle = ProductionScanCycle(symbol="MNQ")
        record = cycle._rebuild_derived_state([], 1)
        assert record["ok"] is False and record["bars"] == 0


class TestTheExceptionPathIsRealNotAssumed:
    """N6b escaped: the failure test passed a 10-character string, which hits
    the length guard and returns BEFORE the try block. The `except` branch --
    the one that must not mark the revision current -- was never executed."""

    def malformed_tape(self):
        """Long enough to pass the length guard, malformed enough to raise."""
        return [{"timestamp": f"2026-08-11T14:{m:02d}:00+00:00", "open": "x",
                 "high": None, "low": None, "close": None, "volume": 0}
                for m in range(20, 45)]

    def test_a_raising_replay_does_not_mark_the_revision_current(self):
        cycle = ProductionScanCycle(symbol="MNQ")
        record = cycle._rebuild_derived_state(self.malformed_tape(), 7)
        assert record["ok"] is False, "a malformed tape reported a good rebuild"
        assert "error" in record
        assert cycle._derived_revision != 7, \
            "a failed rebuild claimed the new revision"

    def test_the_exception_path_was_actually_reached(self):
        """Distinguishes the except branch from the early length return."""
        cycle = ProductionScanCycle(symbol="MNQ")
        record = cycle._rebuild_derived_state(self.malformed_tape(), 7)
        assert "required to confirm a pivot" not in record.get("error", ""), \
            "this hit the length guard, not the replay failure"

    def test_trading_stays_refused_after_a_failed_rebuild(self):
        cycle = ProductionScanCycle(symbol="MNQ")
        cycle._history.observe(holed())
        cycle._derived_revision = cycle._history.revision
        cycle._history.observe(tape())                 # history moves to r1
        cycle._rebuild_derived_state(self.malformed_tape(), cycle._history.revision)
        assert cycle.derived_state_is_current() is False
        with pytest.raises(NoCandidate):
            CandidateProducer._assert_derived_state_current(
                {"derived_state": {"history_revision": cycle._history.revision,
                                   "derived_revision": cycle._derived_revision,
                                   "current": cycle.derived_state_is_current()}})


class TestCognitiveStateIsReAnchored:
    """Step 2B. Mechanical convergence is not enough: the gate could reopen
    while Terra still carried a conviction formed from the mutilated world.

        history r8 / deterministic r8   OK
        Terra belief authored under r7  NOT OK
    """

    def test_prior_stances_are_marked_superseded(self):
        from ai_brain.stance_memory import StanceMemory
        memory = StanceMemory(persist=False)
        memory.record("t1", {"narrative_direction": "bearish",
                             "narrative_phase": "manipulation",
                             "phase_confidence": 64,
                             "current_action": "propose bearish entry"})
        memory.supersede(2, note="repaired")
        assert memory._buf[-1]["superseded_by_history_revision"] == 2

    def test_the_next_prompt_is_TOLD(self):
        """Terra must learn its own history was repaired, not be silently
        steered by a conviction formed from a tape that no longer exists."""
        from ai_brain.stance_memory import StanceMemory
        memory = StanceMemory(persist=False)
        memory.record("t1", {"narrative_direction": "bearish"})
        memory.supersede(2)
        summary = memory.history_summary()
        assert summary["history_revision"]["history_revision"] == 2
        assert summary["history_revision"]["stances_formed_before_a_repair"] == 1
        assert "repaired" in summary["history_revision"]["note"]

    def test_stances_are_marked_NOT_deleted(self):
        """They are evidence of what Terra actually thought. Authority is
        removed; the record is not."""
        from ai_brain.stance_memory import StanceMemory
        memory = StanceMemory(persist=False)
        for i in range(3):
            memory.record(f"t{i}", {"narrative_direction": "bearish"})
        memory.supersede(2)
        assert len(memory._buf) == 3

    def test_a_later_stance_is_not_retroactively_marked(self):
        from ai_brain.stance_memory import StanceMemory
        memory = StanceMemory(persist=False)
        memory.record("old", {"narrative_direction": "bearish"})
        memory.supersede(2)
        memory.record("new", {"narrative_direction": "bullish"})
        assert memory._buf[-1].get("superseded_by_history_revision") is None

    def test_an_active_thesis_is_invalidated(self):
        from ai_brain.thesis_lifecycle import ThesisLifecycleEngine
        engine = ThesisLifecycleEngine(persist=False, symbol="MNQ")
        engine._active = {"thesis_id": "t1", "status": "ACTIVE"}
        out = engine.invalidate_on_history_revision(4, ts="2026-08-11T15:02:00+00:00")
        assert out["invalidated"] is True and out["revision"] == 4
        assert engine._active is None

    def test_no_active_thesis_is_not_an_error(self):
        from ai_brain.thesis_lifecycle import ThesisLifecycleEngine
        engine = ThesisLifecycleEngine(persist=False, symbol="MNQ")
        assert engine.invalidate_on_history_revision(4)["invalidated"] is False

    def test_the_rebuild_CALLS_the_re_anchor(self):
        """The wiring assertion. Again."""
        import inspect
        source = inspect.getsource(ProductionScanCycle._rebuild_derived_state)
        assert "_reanchor_cognitive_state" in source, \
            "cognitive state is re-anchored nowhere in the rebuild"

    def test_re_anchoring_happens_end_to_end(self):
        cycle = ProductionScanCycle(symbol="MNQ")
        cycle.stance_memory = __import__(
            "ai_brain.stance_memory", fromlist=["StanceMemory"]).StanceMemory(persist=False)
        cycle.stance_memory.record("t", {"narrative_direction": "bearish"})
        cycle.thesis_engine._active = {"thesis_id": "t1", "status": "ACTIVE"}
        record = cycle._rebuild_derived_state(tape(), 5)
        assert record["ok"] is True
        assert record["cognitive"]["stance"]["marked"] == 1
        assert record["cognitive"]["thesis"]["invalidated"] is True
        assert cycle.stance_memory._buf[-1]["superseded_by_history_revision"] == 5

    def test_a_failed_rebuild_does_not_re_anchor(self):
        """Re-anchoring belongs to a rebuild that actually happened."""
        cycle = ProductionScanCycle(symbol="MNQ")
        record = cycle._rebuild_derived_state(tape()[:3], 5)
        assert record["ok"] is False
        assert "cognitive" not in record

    def test_the_invalidated_thesis_RECORDS_WHY(self):
        """P4 escaped the first campaign: dropping the status assignment still
        cleared the active thesis, so safety held and nothing failed. What was
        lost was the evidence -- a thesis that vanishes without saying it died
        because history was repaired is indistinguishable from one that expired
        normally. This project's whole doctrine is that a refusal must name
        itself."""
        from ai_brain.thesis_lifecycle import STATUS_INVALIDATED, ThesisLifecycleEngine
        engine = ThesisLifecycleEngine(persist=False, symbol="MNQ")
        engine._active = {"thesis_id": "t1", "status": "ACTIVE"}
        journalled = []
        engine._journal = lambda action, thesis, ts: journalled.append((action, thesis))
        engine.invalidate_on_history_revision(9, ts="2026-08-11T15:02:00+00:00")
        assert journalled, "the invalidation left no journal entry"
        action, thesis = journalled[-1]
        assert action == "invalidated_by_history_revision"
        assert thesis["status"] == STATUS_INVALIDATED
        assert thesis["invalidated_at_history_revision"] == 9
        assert "repaired" in thesis["invalidation_reason"]
