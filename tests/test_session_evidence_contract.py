"""SEAL-PROD-20260807-SESSION-EVIDENCE (2026-08-07).

Two guarantees are under test.

ARCHIVE HONESTY. A sealed session must say what actually happened, including the
parts that are unflattering. The archive binds to the commit that RAN the
session, not the commits that fixed it afterwards; telemetry recovered from
UNSCOPED carries its original location; and artifacts that merely shared a
directory are not adopted.

EVIDENCE ACCOUNTING. Every propose_entry terminates in exactly one terminal
disposition. PROD-20260807 lost its live qualification entirely, which is why
`terra_proposals == sum(dispositions)` is now a test and not a hope.

Evidence never becomes authority: a failed write cannot create permission, and
writing a record cannot change what the producer decides.
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from _step7_fixture import detected as _detected      # noqa: E402
from _step7_fixture import priced as _priced          # noqa: E402
from _step7_fixture import EXECUTABLE_TOOL_EXEMPLAR as EXEMPLAR  # noqa: E402

from broker.candidate_decision_record import (  # noqa: E402
    CANDIDATE_CREATED, QUALIFICATION_REJECTED, TERMINAL_DISPOSITIONS,
    UNCLASSIFIED, blank_trace, build_record, reconcile, terminal_disposition)

ARCHIVE = os.path.join(ROOT, "data", "replay_sessions", "PROD-20260807")
RUNTIME_HEAD = "d167b20"


def _archive(name):
    path = os.path.join(ARCHIVE, name)
    if not os.path.exists(path):
        pytest.skip(f"{name} not present; archive not sealed in this checkout")
    return json.load(open(path, encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════════
class TestArchiveIdentity:
    """1-5."""

    def test_1_the_archive_binds_the_commit_that_ran_the_session(self):
        assert _archive("manifest.json")["runtime_head"] == RUNTIME_HEAD

    def test_2_a_repair_head_cannot_overwrite_runtime_identity(self):
        m = _archive("manifest.json")
        assert m["post_session_repair_head"] != RUNTIME_HEAD
        assert m["runtime_head"] == RUNTIME_HEAD, (
            "the fix must never be recorded as the thing that ran")
        ident = _archive(os.path.join("launcher", "runtime_identity.json"))
        assert ident["runtime_head"] == RUNTIME_HEAD

    def test_3_unscoped_telemetry_carries_explicit_provenance(self):
        p = _archive(os.path.join("memory_retrieval", "PROVENANCE.json"))
        assert p["original_runtime_location"] == "data/replay_sessions/UNSCOPED/"
        assert p["recovered_for_session"] == "PROD-20260807"
        assert p["recovery_reason"] and p["runtime_defect_later_repaired"] is True
        # a recovered association is not an original value
        assert "NOT" in p["original_contract_field"].upper()

    def test_4_only_august_7_records_were_adopted(self):
        path = os.path.join(ARCHIVE, "memory_retrieval", "retrieval_scans.jsonl")
        if not os.path.exists(path):
            pytest.skip("archive not sealed")
        rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        assert rows
        assert all(str(r["timestamp_et"]).startswith("2026-08-07") for r in rows)
        # the offline August 6 replay shared the UNSCOPED directory and was
        # correctly refused
        cd = _archive(os.path.join("memory_retrieval",
                                   "CANDIDATE_DECISIONS_PROVENANCE.json"))
        assert cd["records_adopted"] == 0
        assert cd["records_rejected_as_foreign"] > 0

    def test_5_every_archived_file_verifies_against_the_manifest(self):
        sums = os.path.join(ARCHIVE, "SHA256SUMS.txt")
        if not os.path.exists(sums):
            pytest.skip("archive not sealed")
        checked = 0
        for line in open(sums, encoding="utf-8"):
            digest, rel = line.strip().split("  ", 1)
            full = os.path.join(ARCHIVE, rel.replace("/", os.sep))
            h = hashlib.sha256()
            with open(full, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            assert h.hexdigest() == digest, rel
            checked += 1
        assert checked == _archive("manifest.json")["file_count"]


class TestAttribution:
    """6. Never guess who traded."""

    def test_6_attribution_refuses_rather_than_guesses(self):
        from tools_shim import reconcile_activity as R  # noqa: F401
        out = R(orders=[], trades=[], known_token_ids=set(),
                starting_balance=50042.96, ending_balance=50029.66)
        assert out["balance_change_classification"] == \
            "BALANCE_CHANGE_ATTRIBUTION_UNRESOLVED"
        assert out["bot_attribution"] == "BOT_ACTIVITY_ABSENT"

    def test_6b_a_tagged_order_is_the_bots_and_an_untagged_one_is_not(self):
        from tools_shim import reconcile_activity as R
        out = R(orders=[{"id": 1, "custom_tag": "EXPBOT-tok1"},
                        {"id": 2, "custom_tag": None}],
                trades=[{"order_id": 1, "pnl": -10.0, "fees": 1.5, "voided": False},
                        {"order_id": 2, "pnl": -20.0, "fees": 1.5, "voided": False}],
                known_token_ids={"tok1"},
                starting_balance=100.0, ending_balance=67.0)
        assert out["bot_fills"] == 1 and out["non_bot_fills"] == 1
        assert out["balance_change_classification"] == "MIXED_BOT_AND_EXTERNAL"

    def test_the_recorded_august_7_verdict_does_not_assert_manual(self):
        rec = _archive("activity_reconciliation.json")
        assert rec["bot_generated_order_ids"] == 0 and rec["bot_fills"] == 0
        assert rec["bot_attribution"] == "BOT_ACTIVITY_ABSENT"
        assert rec["balance_change_classification"] == \
            "BALANCE_CHANGE_ATTRIBUTION_UNRESOLVED"


class TestParity:
    """7-9."""

    def test_7_the_parity_table_covers_every_required_fact(self):
        from tools_shim import FACTS
        names = {f[0] for f in FACTS}
        for required in ("current price/reference", "delivery",
                         "buy-side liquidity", "sell-side liquidity",
                         "liquidity sweep/raid state", "protected high",
                         "protected low", "active draw",
                         "PO3 / narrative phase", "volatility",
                         "session phase", "market regime",
                         "authorized objectives", "authorized invalidations"):
            assert required in names, required

    def test_7b_no_outstanding_fact_parity_defects(self):
        p = _archive("fact_parity.json")
        assert p["defects_outstanding"] == []
        assert p["catalog_published_today"] is True
        # the historical defect is preserved, not erased
        assert p["defects_historical_repaired"]

    def test_8_9_the_catalog_terra_sees_equals_the_deterministic_one(self):
        p = _archive("fact_parity.json")
        for row in p["catalog_parity"]:
            if not row.get("comparable"):
                continue
            assert row["identity_match"] is True, row["window"]
            assert row["all_have_ids"] is True
            assert row["deterministic_is_stable"] is True
            assert row["invalidations_have_ids"] is True


class TestDecisionEvidence:
    """10-18. One proposal, one certificate."""

    def test_10_17_a_record_carries_every_stage_field(self):
        r = build_record(session_id="S", scan_id="s1", timestamp_et="t",
                         instrument="MNQ", contract="C", parsed={},
                         trace={}, disposition=CANDIDATE_CREATED)
        for field in blank_trace():
            assert field in r, field
        assert r["final_disposition"] == CANDIDATE_CREATED
        assert r["schema_version"] == "candidate_decision.v1"

    @pytest.mark.parametrize("reason,expected", [
        ("qualification_rejected", "QUALIFICATION_REJECTED"),
        ("objective_id_missing", "OBJECTIVE_ID_MISSING"),
        ("objective_id_unknown", "OBJECTIVE_ID_UNKNOWN"),
        ("objective_wrong_side", "OBJECTIVE_INVALID"),
        ("invalidation_missing", "INVALIDATION_ID_MISSING"),
        ("invalidation_wrong_side", "INVALIDATION_INVALID"),
        ("zero_risk", "GEOMETRY_REJECTED"),
        ("reward_below_qualification", "REWARD_BELOW_QUALIFICATION"),
        ("stand_down", "STOOD_DOWN"),
    ])
    def test_11_16_every_producer_reason_maps_to_one_terminal_cause(
            self, reason, expected):
        assert terminal_disposition(reason) == expected
        assert expected in TERMINAL_DISPOSITIONS

    def test_a_created_candidate_outranks_any_reason(self):
        assert terminal_disposition(None, created=True) == CANDIDATE_CREATED

    def test_18_accounting_reconciles_or_says_it_failed(self):
        good = [{"final_disposition": CANDIDATE_CREATED},
                {"final_disposition": QUALIFICATION_REJECTED}]
        assert reconcile(good)["status"] == "RECONCILED"
        assert reconcile(good)["terra_proposals"] == 2

        bad = good + [{"final_disposition": "SOMETHING_NEW"}]
        out = reconcile(bad)
        assert out["status"] == "CANDIDATE_DECISION_ACCOUNTING_FAILURE"
        assert out["unclassified"] == 1
        assert out["dispositions"][UNCLASSIFIED] == 1

    def test_a_proposal_can_never_vanish(self):
        """An unmapped reason is counted, not dropped."""
        out = reconcile([{"final_disposition": terminal_disposition("brand_new")}])
        assert out["disposition_total"] == 1
        assert out["status"] == "CANDIDATE_DECISION_ACCOUNTING_FAILURE"


class TestTraceIsWrittenByTheProducer:
    """11-17 against the real producer."""

    def _produce(self, **over):
        from ai_brain import production_model as PM
        from broker.luna_candidate_producer import CandidateProducer, NoCandidate
        from broker.topstepx_client import TopstepXContract
        mnq = TopstepXContract(id="CON.F.US.MNQ.U26", name="MNQU6",
                               description="MNQ", tick_size=0.25,
                               tick_value=0.5, active=True)
        bi = {"timestamp": "2026-08-07T13:47:00+00:00",
              "market": _priced({"current_price": 29695.75}),
              "liquidity": {"nearest_buy_side": 29780.0,
                            "nearest_sell_side": 29452.5},
              "protected_swings": {"protected_low": {"level": 29493.25},
                                   "protected_low_status": "above"}}
        parsed = {"narrative_direction": "bearish", "allowed_direction": "bearish",
                  "narrative_phase": "distribution",
                  "current_action": "propose bearish liquidity_sweep_reversal entry",
                  "recommended_playbook_family": "liquidity_sweep_reversal",
                  "recommended_tool_family": [EXEMPLAR],
                  "invalidation_level": 29780.0,
                  "active_draw": "Sell-side liquidity at 29452.50"}
        parsed.update(over.pop("parsed", {}))
        p = CandidateProducer(account_fingerprint="acct:test", contract=mnq)
        try:
            p.produce(brain_result={"ok": True, "parsed": parsed,
                                    # The PRODUCTION constant, not a literal. These tests are about the
                                    # trace contract, not about which tier is doctrine; a
                                    # hardcoded model made every one of them fail with
                                    # `wrong_model` the moment the operator moved
                                    # Terra -> Luna, hiding their real subject.
                                    "fallback_reason": None,
                                    "model": PM.PRODUCTION_MODEL},
                      brain_input=bi, snapshot=_detected("ifvg", "fvg"),
                      qualification=over.pop("qualification", {"qualified": True}),
                      engine_inventory={"liquidity": "PRESENT_AND_POPULATED"},
                      snapshot_id="s1",
                      market_data_timestamp=bi["timestamp"],
                      latest_closed_bar_timestamp=bi["timestamp"],
                      now=datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc))
            return p.last_decision_trace, None
        except NoCandidate as exc:
            return p.last_decision_trace, exc

    def test_11_objective_resolution_status_is_explicit(self):
        trace, exc = self._produce()
        assert exc.reason == "objective_id_missing"
        assert trace["objective_resolution_status"] == "ID_MISSING"
        assert trace["objective_rejection_reason"] == "objective_id_missing"
        assert trace["objective_lookup_found"] is False

    def test_12_invalidation_resolution_status_is_explicit(self):
        trace, exc = self._produce(parsed={"invalidation_level": 29000.0})
        assert exc.reason == "invalidation_wrong_side"
        assert trace["invalidation_resolution_status"] == "WRONG_SIDE"
        assert trace["invalidation_rejection_reason"] == "invalidation_wrong_side"

    def test_13_qualification_result_is_explicit(self):
        """PHASE 3 (2026-08-12): qualification is OBSERVED, never a gate.

        This used to assert `qualification_result == "REJECTED"` and a
        `qualification_rejected` refusal -- a mechanical opinion holding a veto
        over the discretionary lane. The evidence requirement is unchanged: the
        trace must still say explicitly what mechanics thought and why. What
        changed is that saying it no longer kills Terra's thesis.
        """
        trace, exc = self._produce(qualification={"qualified": False,
                                                  "reason": "no setup"})
        assert trace["qualification_result"] == "OBSERVED"
        assert "no setup" in str(trace["qualification_reason"])
        assert trace["mechanical_qualification_observation"] == "no setup"
        assert exc is None or exc.reason != "qualification_rejected"

    def test_14_15_geometry_and_rr_results_are_explicit(self):
        from broker.luna_candidate_producer import authorized_objective_catalog
        bi = {"timestamp": "2026-08-07T13:47:00+00:00",
              "market": _priced({"current_price": 29695.75}),
              "liquidity": {"nearest_buy_side": 29780.0,
                            "nearest_sell_side": 29452.5},
              "protected_swings": {"protected_low": {"level": 29493.25},
                                   "protected_low_status": "above"}}
        ssl = [o for o in authorized_objective_catalog({}, bi, 29695.75)
               if abs(o["price"] - 29452.5) < 0.01][0]
        trace, exc = self._produce(parsed={"objective_id": ssl["objective_id"]})
        assert exc is None, "this geometry should produce a candidate"
        assert trace["geometry_valid"] is True
        assert trace["reward_risk"] is not None
        assert trace["reward_risk_valid"] is True
        assert trace["resolved_objective_price"] == 29452.5
        assert trace["objective_resolution_status"] == "RESOLVED"

    def test_16_17_a_stage_never_reached_stays_none(self):
        """Absence must be readable: None means 'died earlier', not 'passed'.

        PHASE 3: `qualified: False` no longer ends the run, so the early death is
        now triggered by Terra's OWN answer being empty -- she named no playbook.
        That is still a genuine early exit, and the stages behind it must still
        read as never-reached rather than as passed.
        """
        trace, exc = self._produce(parsed={"recommended_playbook_family": "none"})
        assert exc is not None and exc.reason == "playbook_unauthorized"
        assert trace["objective_resolution_status"] is None
        assert trace["reward_risk"] is None
        assert trace["geometry_valid"] is None


class TestEvidenceIsNotAuthority:
    """19-20."""

    def test_19_a_failed_evidence_write_cannot_create_authority(self):
        src = open(os.path.join(ROOT, "src", "broker",
                                "topstepx_production_loop.py"),
                   encoding="utf-8").read()
        block = src[src.index("def _record_decision"):]
        block = block[:block.index("@staticmethod")]
        assert "except Exception" in block and "pass" in block, (
            "evidence writing must swallow its own failures")
        assert "return" not in block.split("try:")[0].split("\n")[-3], (
            "the recorder must not decide anything")

    def test_20_writing_evidence_cannot_change_what_the_producer_decides(self):
        """The trace is written; it is never read back by trade logic."""
        src = open(os.path.join(ROOT, "src", "broker",
                                "luna_candidate_producer.py"),
                   encoding="utf-8").read()
        # every mention is an assignment/update, never a branch condition
        for line in src.splitlines():
            s = line.strip()
            if "last_decision_trace" in s or ("trace[" in s and "=" not in s):
                assert not s.startswith(("if ", "elif ", "while ", "assert ")), s

    def test_20b_two_identical_produces_give_identical_outcomes(self):
        a, ea = TestTraceIsWrittenByTheProducer()._produce()
        b, eb = TestTraceIsWrittenByTheProducer()._produce()
        assert (ea.reason if ea else None) == (eb.reason if eb else None)
        assert a == b


class TestRuntimeGuarantees:
    """21-26."""

    def test_21_stdout_is_line_buffered_before_startup_telemetry(self):
        launcher = os.path.join(ROOT, "tools", "topstepx_production_session.py")
        assert os.path.exists(launcher), "the production launcher must exist"
        src = open(launcher, encoding="utf-8").read()
        assert "reconfigure(line_buffering=True)" in src
        # and it must happen before anything substantial is printed
        assert src.index("line_buffering=True") < src.index("def main")

    def test_22_regime_resolves_to_observe_only(self, monkeypatch):
        from regime_authority.regime_authority_mode import regime_authority_mode
        # unset, and blank -- a blank .env line must not re-arm enforcement
        monkeypatch.delenv("REGIME_AUTHORITY_MODE", raising=False)
        assert regime_authority_mode() == "observe_only"
        monkeypatch.setenv("REGIME_AUTHORITY_MODE", "")
        assert regime_authority_mode() == "observe_only"
        monkeypatch.setenv("REGIME_AUTHORITY_MODE", "   ")
        assert regime_authority_mode() == "observe_only"
        # and an explicit word still wins, so enforcement remains reachable
        monkeypatch.setenv("REGIME_AUTHORITY_MODE", "enforce")
        assert regime_authority_mode() == "enforce"

    def test_23_regime_cannot_mechanically_veto_production(self):
        for module in ("topstepx_production_loop", "luna_candidate_producer",
                       "topstepx_session_authorization"):
            src = open(os.path.join(ROOT, "src", "broker", f"{module}.py"),
                       encoding="utf-8").read()
            assert "market_regime" not in src or "regime_veto" not in src
            assert "regime_blocks" not in src

    def test_24_live_memory_holds_both_sessions_as_v2_2_records(self):
        # Read the real production corpus by path. Going through vector_store
        # would pick up the tests' redirected store and prove nothing.
        live = os.path.join(ROOT, "data", "ai_retrieval", "memory_store.jsonl")
        assert os.path.exists(live), "the live descriptive corpus must exist"
        records = [json.loads(l) for l in open(live, encoding="utf-8") if l.strip()]
        assert records, "live corpus is empty"
        # AUTHOR-PROD-20260807-DESCRIPTIVE-MEMORY (2026-08-07): the hold on
        # August 7 was lifted once its closure, contract identity and
        # partial-observation provenance were proven. Ten August 6 records plus
        # six August 7 records -- still CONTEXT_ONLY, still outcome-free.
        assert len(records) == 16
        assert {r["embedding_version"] for r in records} == \
            {"descriptive.embedding.v2.2"}
        assert {r["embedding_dimensions"] for r in records} == {58}
        assert {r["authority"] for r in records} == {"CONTEXT_ONLY"}
        assert not any(r.get("outcome_validated") for r in records)
        assert len({r["memory_id"] for r in records}) == 16
        assert collections.Counter(r["session_id"] for r in records) == \
            {"PROD-20260806": 10, "PROD-20260807": 6}

    def test_25_26_no_authorization_and_no_order_endpoint_in_this_mission(self):
        import ast
        for name in ("seal_session_archive.py", "fact_parity_audit.py",
                     "reconcile_session_activity.py"):
            path = os.path.join(ROOT, "tools", name)
            tree = ast.parse(open(path, encoding="utf-8").read())
            called = {getattr(n.func, "attr", "") or getattr(n.func, "id", "")
                      for n in ast.walk(tree) if isinstance(n, ast.Call)}
            for forbidden in ("place_bracket_market_order", "place_order_raw",
                              "gated_submit", "issue", "cancel_order",
                              "modify_order"):
                assert forbidden not in called, f"{name}: {forbidden}"
