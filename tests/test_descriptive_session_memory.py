"""BUILD-SAFE-DESCRIPTIVE-SESSION-MEMORY (2026-08-06).

The PROD-20260806 audit ended with 741 archived artifacts and 0 retrievable
records: the bot saved everything and learned nothing. The unsafe fix is to dump
172 scans into the corpus and let tomorrow's session read its own stand-downs
back as precedent.

These tests hold the boundary that makes the safe version safe:

    a descriptive record says what was OBSERVED, never that it was CORRECT;
    it is written after the session closes, never during;
    it is CONTEXT_ONLY, and cannot create, direct, size or invalidate a trade.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from _step7_fixture import detected as _detected      # noqa: E402
from _step7_fixture import priced as _priced          # noqa: E402

from ai_brain.production_model import (PREVIOUS_PRODUCTION_MODEL,  # noqa: E402
                                       PRODUCTION_MODEL,
                                       brain_contract_fingerprint)
from ai_retrieval import descriptive_memory as DM              # noqa: E402
from ai_retrieval import memory_authoring as MA                # noqa: E402
from ai_retrieval import retrieval_contract as RC              # noqa: E402
from ai_retrieval import session_segmentation as SEG           # noqa: E402
from ai_retrieval import vector_store                          # noqa: E402
from ai_retrieval.embedding_v2 import EMBED_DIM_V2             # noqa: E402
from ai_retrieval.retrieval import retrieve_analogs            # noqa: E402
from broker.luna_candidate_producer import (CandidateProducer,  # noqa: E402
                                            NoCandidate)
from broker.topstepx_client import TopstepXContract            # noqa: E402

ARCHIVE = os.path.join("data", "replay_sessions", "PROD-20260806")
MNQ = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6", description="MNQ",
                       tick_size=0.25, tick_value=0.5, active=True)

# THE DIRECTORY IS NOT THE ARCHIVE. `os.path.isdir(ARCHIVE)` self-defeats:
# these very tests write into the archive path while running, so on a checkout
# that ships no history the directory comes into existence with a stray file or
# two and the marker stops skipping -- then the tests fail on the 780+ artifacts
# that are still missing. The manifest is written only by a real archive, so ask
# for that instead.
archived = pytest.mark.skipif(
    not os.path.isfile(os.path.join(ARCHIVE, "SHA256SUMS.txt")),
    reason="EXTERNAL_EVIDENCE_REQUIRED: the PROD-20260806 archive is the "
           "operator's own recorded session and is git-ignored")

EMPTY_LEVEL = {"level": None, "timeframe": None, "basis": None,
               "registered_at": None}


# ── fixtures ──────────────────────────────────────────────────────────────────
def record(**over):
    base = dict(
        session_id="PROD-20260806", session_date="2026-08-06", instrument="MNQ",
        contract="CON.F.US.MNQ.U26", segment_start="11:31:44",
        segment_end="11:42:39", scan_count=10, source_model=PRODUCTION_MODEL,
        brain_contract_fingerprint_suffix="abc123", market_regime="range_rotation",
        volatility_state="toxic", session_phase="lunch",
        narrative_phase="transition", delivery_state="accumulation_building",
        structure_state="witness_quiet",
        structure_evidence={"bos_count": 0, "mss_count": 0, "quiet": True,
                            "parser": "structure_witness_v1"},
        liquidity_state="two_sided_pools",
        protected_high=EMPTY_LEVEL, protected_low=EMPTY_LEVEL,
        active_draw_present=True, exhaustion_present=False,
        direction_distribution={"conflicted": 10},
        action_distribution={"stand_down": 10}, dominant_direction="conflicted",
        dominant_action="stand_down",
        phase_confidence_summary={"observations": 10, "mean": 61.0},
        candidate_count=0, trade_count=0,
        no_candidate_reasons=["action_declines_entry"],
        source_artifact_ids=["a.json"], source_artifact_digest="d1",
        created_at="2026-08-06T20:00:00+00:00")
    base.update(over)
    return DM.make_descriptive_record(**base)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_RETRIEVAL_DIR", str(tmp_path / "retrieval"))
    return tmp_path


def query(**over):
    q = {"session": "lunch", "contract": "CON.F.US.MNQ.U26",
         "market_regime": {"regime_label": "range_rotation",
                           "volatility_state": "toxic"},
         "narrative_authority": {"narrative_direction": "conflicted",
                                 "narrative_phase": "transition",
                                 "active_liquidity_draw": "29500"},
         "shared_context": {"delivery_state": "accumulation_building",
                            "exhaustion_present": False},
         "protected_swings": {"protected_high": None, "protected_low": None},
         # v2.1 query-completeness law: every mandatory load-bearing block must
         # be stated or the query is refused outright.
         "liquidity": {"nearest_buy_side": 29800.0, "nearest_sell_side": 29200.0},
         "STRUCTURE_WITNESS": {tf: {"bos_event": False, "mss_event": False}
                               for tf in ("15m", "5m", "3m", "1m")},
         "phase_confidence_summary": {"mean": 61.0, "min": 40.0, "max": 80.0}}
    q.update(over)
    return q


# ══════════════════════════════════════════════════════════════════════════════
class TestAuthoringIsPostSessionOnly:
    """1-4. Nothing is learned until the session is over and proven flat."""

    def test_1_no_production_scan_module_can_write_memory(self):
        """A write reachable from the scan loop would let the organism read its
        own developing conclusions back as independent precedent an hour later."""
        import ast
        offenders = []
        for rel in ("live_scan/production_scan_cycle.py",
                    "broker/topstepx_production_loop.py",
                    "ai_brain/narrative_brain.py",
                    "broker/luna_candidate_producer.py"):
            tree = ast.parse(open(os.path.join("src", rel), encoding="utf-8").read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in (
                        "add_record", "add_records", "commit_records"):
                    offenders.append(f"{rel}:{node.lineno}")
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [a.name for a in node.names]
                    mod = getattr(node, "module", "") or ""
                    if "memory_authoring" in mod or "memory_authoring" in names:
                        offenders.append(f"{rel}:{node.lineno} imports authoring")
        assert not offenders, offenders

    def test_2_an_armed_session_flag_does_not_enable_authoring(self, store, monkeypatch):
        monkeypatch.setenv("PRODUCTION_ARMED_SESSION", "true")
        with pytest.raises(MA.AuthoringRefused):
            MA.commit_records([record()])          # approved defaults to False
        assert vector_store.count() == 0

    @archived
    def test_3_an_unclean_final_exit_defers_authoring(self, tmp_path):
        import shutil
        fake = tmp_path / "sess"
        shutil.copytree(ARCHIVE, fake, dirs_exist_ok=True)
        path = fake / "launcher" / "exit_statuses.json"
        data = json.load(open(path, encoding="utf-8"))
        data["phases"][-1] = {"phase": "C", "exit": "KILLED", "exit_code": None}
        json.dump(data, open(path, "w", encoding="utf-8"))
        out = MA.build_records(str(fake))
        assert out["status"] == MA.DEFERRED
        assert any("final_phase" in r for r in out["reasons"])
        assert out["records"] == []

    @archived
    def test_4_a_non_flat_account_refuses_authoring(self, tmp_path):
        import shutil
        fake = tmp_path / "sess"
        shutil.copytree(ARCHIVE, fake, dirs_exist_ok=True)
        path = fake / "account" / "reconciliation_redacted.json"
        data = json.load(open(path, encoding="utf-8"))
        data["positions"], data["working_orders"] = 1, 2
        json.dump(data, open(path, "w", encoding="utf-8"))
        out = MA.build_records(str(fake))
        assert out["status"] == MA.DEFERRED
        assert "open_positions:1" in out["reasons"]
        assert "working_orders:2" in out["reasons"]


class TestQualityFilters:
    """5-8. A bad read never becomes durable memory."""

    @archived
    def test_5_6_7_malformed_degraded_and_fallback_scans_are_excluded(self):
        read = SEG.load_session_observations(ARCHIVE)
        # PROD-20260806: 3 degraded + 2 llm_failed_fallback out of 172.
        assert read["total_scans"] == 172
        assert read["eligible" if "eligible" in read else "observations"]
        assert len(read["observations"]) == 167
        assert read["excluded"]["source_degraded"] == 3
        assert read["excluded"]["source_llm_failed_fallback"] == 2

    def test_8_a_test_artifact_never_contributes(self, tmp_path):
        session = _mini_archive(tmp_path, marks={"test_artifact": True})
        read = SEG.load_session_observations(session)
        assert read["observations"] == []
        assert read["excluded"]["test_artifact"] >= 1

    def test_an_unsanctioned_model_is_excluded_but_a_prior_one_is_not(self, tmp_path):
        """Luna is on the FORBIDDEN list because it may not be RUN today. That
        is not the same question as whether a read it produced when it WAS the
        production model may be described."""
        assert PREVIOUS_PRODUCTION_MODEL in SEG.SANCTIONED_MEMORY_MODELS
        assert PRODUCTION_MODEL in SEG.SANCTIONED_MEMORY_MODELS
        assert "gpt-4o-mini" not in SEG.SANCTIONED_MEMORY_MODELS
        read = SEG.load_session_observations(
            _mini_archive(tmp_path, model="gpt-4o-mini"))
        assert read["observations"] == []
        assert read["excluded"]["forbidden_model"] == 1


class TestIdentityFilters:
    """9-10. Retired and unlabelled evidence never reaches a production query."""

    def test_9_a_qqq_record_never_retrieves(self, store):
        vector_store.add_record({**record(), "instrument": "QQQ"})
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 0
        assert out["rejected_reasons"] == {"retired_instrument:qqq": 1}

    def test_10_an_identity_less_record_never_retrieves(self, store):
        naked = {k: v for k, v in record().items()
                 if k not in ("instrument", "provenance")}
        vector_store.add_record(naked)
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 0
        assert out["rejected_reasons"] == {"missing_instrument_identity": 1}


class TestSegmentationLaw:
    """11-14. A session becomes a description, not a transcript."""

    @archived
    def test_11_valid_mnq_observations_form_segments(self):
        out = MA.build_records(ARCHIVE)
        assert out["status"] == MA.DRY_RUN
        assert out["records"]
        assert all(r["instrument"] == "MNQ" for r in out["records"])

    def test_12_equivalent_consecutive_scans_merge(self):
        obs = [_obs(i) for i in range(30)]           # 30 identical scans
        cut = SEG.cut_segments(obs)
        assert len(cut["segments"]) == 1
        assert cut["segments"][0]["scans"] and len(cut["segments"][0]["scans"]) == 30

    def test_13_a_real_state_transition_creates_a_new_segment(self):
        obs = ([_obs(i) for i in range(10)]
               + [_obs(i, market_regime="chop") for i in range(10, 20)])
        cut = SEG.cut_segments(obs)
        assert len(cut["segments"]) == 2
        assert cut["segments"][1]["scans"][0]["market_regime"] == "chop"

    def test_a_one_scan_blip_does_not_become_a_segment(self):
        """The whole point of the minimum-duration rule."""
        obs = ([_obs(i) for i in range(10)]
               + [_obs(10, narrative_direction="bullish")]        # one blip
               + [_obs(i) for i in range(11, 21)])
        cut = SEG.cut_segments(obs)
        assert len(cut["segments"]) == 1
        assert len(cut["segments"][0]["scans"]) == 21        # the blip is kept

    def test_14_the_segment_count_never_exceeds_the_ceiling(self):
        """Alternate every scan so the finest tier would cut 60 runs."""
        obs = [_obs(i, market_regime="chop" if i % 2 else "range_rotation",
                    narrative_direction="bullish" if i % 3 else "bearish")
               for i in range(120)]
        cut = SEG.cut_segments(obs)
        assert len(cut["segments"]) <= SEG.SEGMENT_CEILING

    def test_the_ceiling_coarsens_rather_than_truncating(self):
        """Truncation would silently delete the afternoon."""
        obs = [_obs(i, session_phase="lunch" if i < 60 else "afternoon",
                    market_regime="chop" if i % 2 else "range_rotation",
                    narrative_direction="bullish" if i % 3 else "bearish")
               for i in range(120)]
        cut = SEG.cut_segments(obs)
        covered = sum(len(s["scans"]) for s in cut["segments"])
        assert covered == 120
        assert cut["segments"][-1]["scans"][-1]["et"] == obs[-1]["et"]

    @archived
    def test_the_archived_session_lands_under_the_ceiling(self):
        out = MA.build_records(ARCHIVE)
        assert len(out["records"]) <= SEG.SEGMENT_CEILING

    def test_prose_actions_are_reduced_to_tokens_not_stored(self):
        """172 live scans included whole paragraphs in `current_action`."""
        assert SEG.normalize_action("stand_down") == "stand_down"
        assert SEG.normalize_action(
            "Stand down with no exposure; wait for a genuine sweep.") == "stand_down"
        assert SEG.normalize_action(
            "Remain flat and wait for renewed bearish delivery") == "stand_down"
        assert SEG.normalize_action("prepare_bearish") == "prepare_bearish"
        assert SEG.normalize_action("something novel entirely") == "other"


class TestIdempotency:
    """15-17. Authoring the same session twice does not duplicate it."""

    def test_15_memory_ids_are_deterministic(self):
        assert record()["memory_id"] == record()["memory_id"]
        assert record()["memory_id"] != record(segment_start="12:00:00")["memory_id"]

    def test_16_re_authoring_identical_content_is_a_no_op(self, store):
        rec = record()
        assert MA.commit_records([rec], approved=True)["status"] == MA.AUTHORED
        assert vector_store.count() == 1
        again = MA.commit_records([rec], approved=True)
        assert again["status"] == MA.ALREADY_AUTHORED
        assert again["written"] == 0
        assert vector_store.count() == 1

    def test_17_conflicting_re_authoring_refuses_the_whole_batch(self, store):
        MA.commit_records([record()], approved=True)
        mutated = record(dominant_direction="bullish")
        assert mutated["memory_id"] == record()["memory_id"]     # same identity
        out = MA.commit_records([mutated, record(segment_start="13:00:00")],
                                approved=True)
        assert out["status"] == MA.CONFLICT_REFUSED
        assert out["written"] == 0
        assert vector_store.count() == 1        # the second record is NOT written


class TestAuthorityBoundary:
    """18-21. A description never becomes a verdict."""

    def test_18_every_descriptive_record_is_context_only(self):
        assert record()["authority"] == RC.AUTHORITY_LABEL == "CONTEXT_ONLY"
        assert record()["recommendation_authority"] == "none"
        assert record()["execution_authority"] == "none"

    def test_19_outcome_validated_is_false_and_cannot_be_forged(self):
        rec = record()
        assert rec["outcome_validated"] is False
        rec["outcome_validated"] = True
        ok, reasons = DM.validate_descriptive_record(rec)
        assert not ok and "outcome_validated_must_be_false" in reasons

    def test_20_no_record_asserts_that_a_decision_was_correct(self):
        rec = record(no_candidate_reasons=["the stand down was correct"])
        ok, reasons = DM.validate_descriptive_record(rec)
        assert not ok
        assert any("decision_correctness_claim" in r for r in reasons)

    def test_21_avoided_loss_language_is_refused(self):
        for text in ("standing down avoided a loss", "this avoided drawdown",
                     "saved capital by waiting"):
            rec = record(structure_state=text)
            ok, reasons = DM.validate_descriptive_record(rec)
            assert not ok, text
            assert any("avoided_loss_claim" in r for r in reasons), text

    def test_a_forged_record_cannot_be_committed(self, store):
        with pytest.raises(MA.AuthoringRefused):
            MA.commit_records([record(no_candidate_reasons=["a winning setup"])],
                              approved=True)
        assert vector_store.count() == 0

    def test_a_stored_record_claiming_authority_is_rejected_at_retrieval(self, store):
        """Defence in depth: the writer refuses it, and the reader refuses it."""
        vector_store.add_record({**record(), "authority": "DIRECTIONAL"})
        out = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert out["returned"] == 0
        assert out["rejected_reasons"] == {"authority_label_mismatch": 1}

    def test_no_account_identity_is_storable_on_a_market_analog(self):
        for field in ("account_id", "account_fingerprint", "account_balance",
                      "api_key", "authorization_fingerprint", "llm_prompt",
                      "llm_raw_response"):
            ok, reasons = DM.validate_descriptive_record({**record(), field: "x"})
            assert not ok and f"forbidden_field:{field}" in reasons


class TestContractAndRetention:
    """22-24. Prices are contract-scoped; age is a retrieval rule."""

    def test_22_levels_are_withheld_across_contracts(self, store):
        vector_store.add_record(record(
            protected_high={"level": 29780.0, "timeframe": "5m",
                            "basis": "buy_side_raid_rejected",
                            "registered_at": "2026-08-06T15:00:00+00:00"},
            protected_low={"level": 29530.0, "timeframe": "5m",
                           "basis": "sell_side_raid_rejected",
                           "registered_at": "2026-08-06T15:10:00+00:00"}))
        same = retrieve_analogs(query(), persist_log=False, today="2026-08-07")
        assert same["analogs"][0]["levels_withheld"] is False
        assert same["analogs"][0]["protected_high"] == 29780.0

        rolled = retrieve_analogs(query(contract="CON.F.US.MNQ.Z26"),
                                  persist_log=False, today="2026-08-07")
        a = rolled["analogs"][0]
        assert a["levels_withheld"] is True
        assert "protected_high" not in a and "protected_low" not in a
        # the categorical features survive the rollover; only prices do not
        assert a["market_regime"] == "range_rotation"
        assert a["dominant_direction"] == "conflicted"

    def test_23_expired_records_do_not_retrieve(self, store):
        vector_store.add_record(record())
        fresh = retrieve_analogs(query(), persist_log=False, today="2026-09-01")
        assert fresh["returned"] == 1
        stale = retrieve_analogs(query(), persist_log=False, today="2026-10-20")
        assert stale["returned"] == 0
        assert stale["rejected_reasons"] == {"expired": 1}

    def test_24_an_expired_record_remains_on_disk(self, store):
        vector_store.add_record(record())
        retrieve_analogs(query(), persist_log=False, today="2026-12-31")
        assert vector_store.count() == 1        # expiry is not deletion

    def test_expiry_is_measured_in_et_session_dates(self):
        rec = record(session_date="2026-08-06")
        assert rec["expires_at"] == "2026-10-05"       # +60 calendar days
        assert DM.is_expired(rec, "2026-10-05") is False
        assert DM.is_expired(rec, "2026-10-06") is True

    def test_a_record_whose_age_cannot_be_established_expires_immediately(self):
        assert DM.is_expired({"session_date": None, "expires_at": None},
                             "2026-08-07") is True
        assert DM.is_expired({"session_date": "not-a-date"}, "2026-08-07") is True


class TestRetrievedMemoryCannotAct:
    """25-29. The candidate boundary. This is the load-bearing set."""

    def _produce(self, parsed, brain_input, snapshot):
        # STEP 7: these assert that a retrieved analog cannot supply a
        # missing invalidation/objective. The selected tool must exist
        # first, or the producer declines on the tool instead and the
        # test would pass for the wrong reason.
        snapshot = {**(snapshot or {}), **_detected("ifvg", "fvg")}
        p = CandidateProducer(allow_prose_objective_fallback=True,
                                      account_fingerprint="acct:test", contract=MNQ)
        return p.produce(
            brain_result={"ok": True, "parsed": parsed, "fallback_reason": None,
                          "model": PRODUCTION_MODEL},
            brain_input=brain_input, snapshot=snapshot,
            qualification={"qualified": True},
            engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
            snapshot_id="s1", market_data_timestamp="2026-08-06T16:19:00+00:00",
            latest_closed_bar_timestamp="2026-08-06T16:19:00+00:00",
            now=datetime(2026, 8, 6, 16, 20, tzinfo=timezone.utc))

    def _analog_snapshot(self):
        """A snapshot carrying a rich, perfectly matching descriptive analog."""
        rec = record(dominant_direction="bearish",
                     direction_distribution={"bearish": 10},
                     protected_high={"level": 29500.0, "timeframe": "5m",
                                     "basis": "buy_side_raid_rejected",
                                     "registered_at": "2026-08-06T15:10:00+00:00"},
                     protected_low={"level": 29478.5, "timeframe": "5m",
                                    "basis": "sell_side_raid_rejected",
                                    "registered_at": "2026-08-06T16:00:00+00:00"},
                     active_draw_present=True)
        return {"ai_retrieval": {"enabled": True, "authority": "observe_only",
                                 "retrieval_authority": RC.AUTHORITY_LABEL,
                                 "analogs": [{"similarity": 1.0, **rec}]}}

    def test_25_a_retrieved_analog_alone_cannot_produce_a_candidate(self):
        """Luna says nothing. The analog says bearish, with levels. No trade."""
        with pytest.raises(NoCandidate) as exc:
            self._produce({}, {"market": _priced({"current_price": 29483.0})},
                          self._analog_snapshot())
        assert exc.value.reason in ("brain_invalid", "stand_down",
                                    "direction_invalid", "action_declines_entry")

    def test_26_a_retrieved_analog_cannot_supply_a_missing_invalidation(self):
        parsed = {"narrative_direction": "bearish", "allowed_direction": "bearish",
                  "current_action": "enter on retest of 29500",
                  "recommended_playbook_family": "trend_continuation",
                  "recommended_tool_family": ["fvg"], "invalidation_level": None,
                  "active_draw": "Sell-side liquidity at 29241.0"}
        brain_input = {"market": _priced({"current_price": 29483.0}),
                       "liquidity": {"nearest_sell_side": 29241.0},
                       "protected_swings": {}}          # nothing to lean on
        with pytest.raises(NoCandidate) as exc:
            self._produce(parsed, brain_input, self._analog_snapshot())
        assert "invalidation" in exc.value.reason

    def test_27_a_retrieved_analog_cannot_supply_a_liquidity_objective(self):
        parsed = {"narrative_direction": "bearish", "allowed_direction": "bearish",
                  "current_action": "enter on retest of 29500",
                  "recommended_playbook_family": "trend_continuation",
                  "recommended_tool_family": ["fvg"], "invalidation_level": 29500.0,
                  "active_draw": None}
        brain_input = {"market": _priced({"current_price": 29483.0}),
                       "liquidity": {},                 # no pools at all
                       "protected_swings": {
                           "protected_high": {"level": 29500.0,
                                              "timestamp": "2026-08-06T15:10:00+00:00"}}}
        with pytest.raises(NoCandidate) as exc:
            self._produce(parsed, brain_input, self._analog_snapshot())
        assert "objective" in exc.value.reason

    def test_28_29_an_analog_carries_no_risk_or_sizing_field(self):  # noqa: D102
        """The record schema simply has no lever to pull."""
        rec = record()
        for field in ("risk_usd", "max_risk", "contracts", "size", "quantity",
                      "reward_to_risk", "min_r", "stop_points", "leverage"):
            assert field not in rec, field
        view = None
        from ai_retrieval.retrieval import _descriptive_view
        view = _descriptive_view(rec, 1.0, "CON.F.US.MNQ.U26")
        for field in ("risk_usd", "contracts", "size", "reward_to_risk"):
            assert field not in view, field

    def test_the_prompt_states_the_authority_boundary(self):
        from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT
        text = BRAIN_SYSTEM_PROMPT
        assert "CONTEXT_ONLY" in text
        assert "not an outcome-validated trading recommendation" in text.lower() \
            or "NOT an outcome-validated" in text
        assert "cannot establish direction" in text.lower()
        # the prompt is hard-wrapped, so compare on collapsed whitespace
        flat = " ".join(text.split())
        assert "a prior stand_down means the system did not act, not that not "                "acting was correct" in flat
        assert "Never widen risk, size, or reward-to-risk" in flat


class TestDryRunAndApproval:
    """30-32. A forgotten flag must never be the difference."""

    @archived
    def test_30_a_dry_run_never_changes_the_live_store(self, tmp_path):
        live = vector_store._store_path()
        before = (open(live, "rb").read() if os.path.exists(live) else b"")
        out = MA.build_records(ARCHIVE)
        MA.write_proposed(out["records"], str(tmp_path / "proposed"))
        after = (open(live, "rb").read() if os.path.exists(live) else b"")
        assert after == before

    @archived
    def test_31_the_dry_run_is_deterministic(self):
        a = MA.build_records(ARCHIVE, now_iso="2026-08-06T20:00:00+00:00")
        b = MA.build_records(ARCHIVE, now_iso="2026-08-06T20:00:00+00:00")
        assert [r["memory_id"] for r in a["records"]] == \
               [r["memory_id"] for r in b["records"]]
        assert [r["content_digest"] for r in a["records"]] == \
               [r["content_digest"] for r in b["records"]]
        assert a["tier"] == b["tier"]

    def test_32_committing_requires_explicit_operator_approval(self, store):
        assert MA.OPERATOR_APPROVAL_REQUIRED is True
        with pytest.raises(MA.AuthoringRefused) as exc:
            MA.commit_records([record()])
        assert "OPERATOR_APPROVAL_REQUIRED" in str(exc.value)
        assert vector_store.count() == 0

    def test_the_cli_defaults_to_dry_run(self):
        import ast
        tree = ast.parse(open(os.path.join("tools",
                                           "author_descriptive_session_memory.py"),
                              encoding="utf-8").read())
        flags = [n.args[0].value for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", "") == "add_argument"
                 and n.args and isinstance(n.args[0], ast.Constant)]
        assert "--commit-memory" in flags and "--approve" in flags
        # no argument makes committing the default
        assert "--dry-run" in flags


class TestIsolationAndSuiteHygiene:
    """33-38. This suite may not teach the live organism anything."""

    def test_33_these_tests_use_an_isolated_store(self, store):
        assert "expansion-test-runtime-" in os.environ["AI_RETRIEVAL_DIR"] \
            or str(store) in os.environ["AI_RETRIEVAL_DIR"]
        vector_store.add_record(record())
        assert "data" + os.sep + "ai_retrieval" not in vector_store._store_path()

    def test_34_the_live_memory_store_is_untouched_by_this_suite(self, store):
        """The live corpus was empty until PROD-20260806 was authored on
        2026-08-06. Emptiness was never the invariant -- ISOLATION was. What
        must hold forever is that the suite writes to a redirected root and
        leaves the live store byte-identical (also enforced globally by the
        conftest mutation guard)."""
        import hashlib
        live = os.path.join("data", "ai_retrieval", "memory_store.jsonl")
        if not os.path.exists(live):
            pytest.skip("live store absent")
        before = hashlib.sha256(open(live, "rb").read()).hexdigest()
        # `store` gives this test its OWN redirected root, so the write cannot
        # leak into the shared session root and pollute later tests.
        vector_store.add_record(record())
        assert "data" + os.sep + "ai_retrieval" not in vector_store._store_path()
        assert hashlib.sha256(open(live, "rb").read()).hexdigest() == before

    def test_35_the_retrieval_contract_is_bound_into_the_brain_contract(self):
        """36-38 rely on this: changing retrieval must invalidate authorizations."""
        import importlib

        from ai_retrieval import retrieval_contract
        before = brain_contract_fingerprint()
        original = retrieval_contract.MIN_SIMILARITY
        try:
            retrieval_contract.MIN_SIMILARITY = 0.9
            importlib.reload  # no reload needed: the value is read at call time
            after = brain_contract_fingerprint()
        finally:
            retrieval_contract.MIN_SIMILARITY = original
        assert after != before, ("the Brain contract does not bind the retrieval "
                                 "policy; an authorization would survive a "
                                 "threshold change")
        assert brain_contract_fingerprint() == before

    def test_36_the_retrieval_policy_fingerprint_is_stable_and_prefixed(self):
        assert RC.retrieval_contract_fingerprint().startswith("retr:")
        assert RC.retrieval_contract_fingerprint() == RC.retrieval_contract_fingerprint()

    def test_37_the_embedding_dimension_matches_the_declared_manifest(self):
        """A silent dimension change would invalidate the whole corpus.

        v1 pinned this at 47. VECTOR-V2 replaced the space deliberately, while
        the corpus was still empty and migration cost nothing.
        """
        assert record()["feature_dimensions"] == EMBED_DIM_V2
        assert len(record()["feature_vector"]) == EMBED_DIM_V2
        assert record()["embedding_dimensions"] == EMBED_DIM_V2

    def test_38_a_descriptive_record_embeds_into_a_populated_vector(self):
        """The v1 defect: descriptive records fell through to the live-snapshot
        branch, embedded as near-zero, and were stored but never retrievable --
        visible only as 'returned: 0'."""
        vec = record()["feature_vector"]
        assert sum(1 for v in vec if v) >= 5, "near-zero vector: wrong encoder branch"
        from ai_retrieval.embedding_v2 import cosine_v2
        assert cosine_v2(vec, record()["feature_vector"]) == pytest.approx(1.0)


# ── helpers ───────────────────────────────────────────────────────────────────
def _obs(i, **over):
    base = {"artifact_id": f"{i:04d}.json", "et": f"11:{i % 60:02d}:00",
            "code_phase": "C", "instrument": "MNQ",
            "contract": "CON.F.US.MNQ.U26", "source_model": PRODUCTION_MODEL,
            "market_timestamp": "2026-08-06T15:00:00+00:00",
            "session_phase": "lunch", "market_regime": "range_rotation",
            "volatility_state": "toxic", "delivery_state": "accumulation_building",
            "narrative_direction": "conflicted", "narrative_phase": "transition",
            "phase_confidence": 60, "action": "stand_down", "draw_present": True,
            "protected_state": "none/none", "protected_high": None,
            "protected_low": None, "structure_state": "witness_quiet",
            "liquidity_state": "two_sided_pools"}
    base.update(over)
    return base


def _mini_archive(tmp_path, *, model=PRODUCTION_MODEL, marks=None):
    """A minimal well-formed archive with a single scan."""
    root = tmp_path / "MINI"
    for sub in (("scans", "inputs"), ("brain", "parsed_outputs"),
                ("brain", "full_artifacts"), ("launcher",), ("execution",),
                ("account",)):
        os.makedirs(root.joinpath(*sub), exist_ok=True)
    name = "20260806_093024_MNQ.json"
    json.dump({"session": "ny_open", "delivery": {"state": "mixed"},
               "liquidity": {}, "protected_swings": {},
               "governance_context": {"regime": "chop"},
               **(marks or {})},
              open(root / "scans" / "inputs" / name, "w", encoding="utf-8"))
    json.dump({"narrative_direction": "conflicted", "narrative_phase": "transition",
               "phase_confidence": 55, "current_action": "stand_down"},
              open(root / "brain" / "parsed_outputs" / name, "w", encoding="utf-8"))
    json.dump({"source": "llm", "llm_model": model, "fallback_reason": None,
               "symbol": "MNQ", **(marks or {})},
              open(root / "brain" / "full_artifacts" / name, "w", encoding="utf-8"))
    json.dump({"count": 1, "session": "MINI",
               "scans": [{"et": "09:30:24", "phase": "A", "instrument": "MNQ",
                          "contract": "CON.F.US.MNQ.U26"}]},
              open(root / "scans" / "scan_index.json", "w", encoding="utf-8"))
    return str(root)
