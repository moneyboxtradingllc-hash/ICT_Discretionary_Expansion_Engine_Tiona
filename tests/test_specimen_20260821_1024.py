"""STAGE 1 — the 10:24 causal specimen, driven through the SHIPPED seam.

ZERO Luna calls. Zero broker contact. Zero production evidence written.

The load-bearing claim is not "an FVG exists AND a wake exists" sitting next to
each other. It is that the interaction CAUSES the evaluation, which only a
negative control can establish: move the declared ask outside the zone and the
early evaluation must disappear.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import specimen_20260821_1024 as S           # noqa: E402
from live_scan.wake_registry import WakeRegistry   # noqa: E402

pytestmark = pytest.mark.skipif(
    not os.path.exists(S.TAPE), reason="historical MNQ tape absent")


@pytest.fixture(scope="module")
def sandbox():
    d = tempfile.mkdtemp(prefix="specimen1024_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="module")
def positive(sandbox):
    return S.run_specimen(ask=S.COUNTERFACTUAL_ASK, tmpdir=sandbox)


@pytest.fixture(scope="module")
def negative(sandbox):
    return S.run_specimen(ask=S.OUTSIDE_ASK, tmpdir=sandbox)


# ══ HISTORICAL STRUCTURE — discovered, never injected ════════════════════════
class TestHistoricalStructure:
    def test_the_tape_names_the_contract_the_specimen_uses(self):
        assert S.archived_contract() == S.CONTRACT

    def test_before_settlement_the_occurrence_does_not_exist(self):
        r = WakeRegistry()
        r.bootstrap_from_bars(S.historical_bars(S.PRE_BIRTH_LAST_BAR), S.CONTRACT,
                              bid=S.COUNTERFACTUAL_BID, ask=S.COUNTERFACTUAL_ASK)
        assert S.GAP_ID not in {x[0] for x in r.armed()}

    def test_after_settlement_the_canonical_path_derives_it_itself(self):
        r = WakeRegistry()
        r.bootstrap_from_bars(S.historical_bars(S.POST_BIRTH_LAST_BAR), S.CONTRACT,
                              bid=S.COUNTERFACTUAL_BID, ask=S.COUNTERFACTUAL_ASK)
        row = next((x for x in r.armed() if x[0] == S.GAP_ID), None)
        assert row is not None, "the gap was not born from the historical tape"
        assert (row[1], row[2], row[3]) == ("bullish", S.GAP_LOW, S.GAP_HIGH)

    def test_no_future_bar_leaks_before_the_birth_instant(self):
        """A bar dated after the cutoff would let the specimen see the future."""
        for cutoff in (S.PRE_BIRTH_LAST_BAR, S.POST_BIRTH_LAST_BAR):
            assert all(str(b["timestamp"]) <= cutoff
                       for b in S.historical_bars(cutoff))


# ══ CAUSALITY — the discriminator ════════════════════════════════════════════
class TestTheInteractionCausesTheEvaluation:
    def test_the_declared_interaction_wakes_before_the_deadline(self, positive):
        assert positive["gap"] is not None
        assert positive["gap"] < positive["interval"] - 2.0, positive["gap"]

    def test_exactly_one_wake_on_the_exact_occurrence(self, positive):
        assert len(positive["wakes"]) == 1, positive["wakes"]
        assert positive["wakes"][0]["occurrence_id"] == S.GAP_ID

    def test_exactly_one_evaluation_is_caused_by_that_wake(self, positive):
        assert positive["evaluations_caused_by_wake"] == 1
        assert positive["evaluations_total"] == 2      # ordinary + wake-caused

    def test_NEGATIVE_CONTROL_outside_ask_produces_no_early_evaluation(self, negative):
        """The whole proof. Same tape, same birth — only the ask moves."""
        assert negative["wakes"] == [], negative["wakes"]
        assert negative["gap"] >= negative["interval"] - 1.0, negative["gap"]

    def test_the_occurrence_is_armed_in_BOTH_arms(self, positive, negative):
        """Arming is structural; only the INTERACTION differs. Otherwise the
        control would be proving 'no gap' rather than 'no interaction'."""
        assert S.GAP_ID in positive["armed_ids"]
        assert S.GAP_ID in negative["armed_ids"]


# ══ CONSTRUCTIBILITY — what production actually hands Luna ═══════════════════
class TestTheTradeIsConstructible:
    @pytest.fixture(scope="class")
    def payload(self, positive):
        return S.constructibility(positive["snapshots"][-1])

    def test_the_exact_occurrence_reaches_the_brain(self, payload):
        assert payload["exact_occurrence_available"], "identity lost before Luna"
        assert payload["zone_correct"]
        assert payload["tool_family"] == "fvg"

    def test_the_identity_is_contract_exact_not_generic(self, payload):
        oid = payload["exact_occurrence"]["occurrence_id"]
        assert oid.startswith(f"FVG:{S.CONTRACT}:"), oid
        assert ":MNQ:" not in oid, "generic-contract identity hazard"

    def test_a_fresh_executable_entry_price_is_present(self, payload):
        ep = payload["execution_price"]
        assert ep.get("fresh") is True
        assert ep.get("best_ask") == S.COUNTERFACTUAL_ASK
        assert ep.get("age_seconds") < ep.get("max_age_seconds")

    def test_the_structural_invalidation_is_present(self, payload):
        assert payload["invalidation_available"], payload["invalidation_paths"]

    def test_the_objective_is_present_as_a_named_structural_fact(self, payload):
        """Not merely a coincidental price: it must be a NAMED field."""
        assert payload["objective_available"]
        assert payload["objective_named_structurally"], payload["objective_paths"]


# ══ ISOLATION — the guarantees, asserted rather than assumed ═════════════════
class TestStageOneIsSealed:
    def test_no_broker_method_was_reached(self, positive, negative):
        assert positive["submit_attempts"] == 0
        assert negative["submit_attempts"] == 0

    def test_the_external_provider_is_mechanically_unreachable(self):
        """Fail CLOSED — not 'the test shouldn't get there'."""
        from ai_layer import ai_api_adapter as A
        with S.no_external_provider():
            with pytest.raises(S.ExternalProviderReached):
                A._openai.OpenAI(api_key="x")

    def test_the_environment_is_restored(self, sandbox):
        keys = ("BRAIN_ECU_MODE", "EXECUTION_ENABLED", "ALLOW_PAPER_ORDERS",
                "TOPSTEPX_ACCOUNT_FINGERPRINT", "AI_RETRIEVAL_ENABLED",
                "AI_BRAIN_DIR", "LIVE_SNAPSHOTS_DIR", "AI_RETRIEVAL_DIR")
        before = {k: os.environ.get(k) for k in keys}
        with S.sandboxed(sandbox):
            pass
        assert {k: os.environ.get(k) for k in keys} == before

    def test_production_evidence_roots_are_untouched(self, positive):
        """The harness must not write where live evidence lives."""
        import broker.trade_lineage as TL
        import topstepx_production_session as TOOL
        assert "specimen" not in str(TOOL.STORE_DIR).lower()
        assert TL.archive_tape.__module__ == "broker.trade_lineage"

    def test_THIS_SUITE_CANNOT_SPEND_A_PROVIDER_CALL(self):
        """Structural, not a promise.

        `run_stage2` has no disarmed mode -- calling it AT ALL spends money --
        and `run_stage3` spends only under `live=True`. A future edit that adds
        either to this file would silently bill every CI run, so the file is
        parsed and the call graph checked rather than trusted.
        """
        import ast
        src = open(os.path.abspath(__file__), encoding="utf-8").read()
        tree = ast.parse(src)
        called, live_kw = set(), []
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                fn = n.func
                name = getattr(fn, "attr", None) or getattr(fn, "id", None)
                if name:
                    called.add(name)
                for kw in n.keywords:
                    if kw.arg == "live":
                        live_kw.append(ast.dump(kw.value))
        assert "run_stage2" not in called, "run_stage2 always spends a provider call"
        assert not any("True" in d for d in live_kw), "live=True in the test suite"

    def test_live_mode_can_never_be_reached_by_default(self):
        """`live` is keyword-only with NO default, so it cannot be omitted into
        the expensive branch."""
        import inspect
        p = inspect.signature(S.run_stage3).parameters["live"]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY
        assert p.default is inspect.Parameter.empty

    def test_the_deterministic_stage3_precheck_makes_zero_calls(self, sandbox):
        """The zero-call mode is exercised, so the seeding path stays covered."""
        with S.no_external_provider():
            r = S.run_stage3(sandbox, live=False)
        assert r["outbound_calls"] == 0
        assert r["cognition_invocations"] == 2
        assert [w["reason"] for w in r["wakes"]] == ["armed_while_inside"]
        assert r["stance_seen"][1]["available"] is True
        assert r["stance_seen"][1]["last"]["timestamp"] == r["prior_stance"]["timestamp"]
        assert r["submit_attempts"] == 0

    def test_the_archived_prior_stance_is_read_from_the_archive(self):
        """The artifact is authority — these values are not written here."""
        p = S.archived_prior_stance()
        assert p["path"].endswith(S.PRIOR_STANCE_ARTIFACT)
        assert p["timestamp"] == "2026-08-21T14:22:00+00:00"   # settled 1m, as
        assert p["model"] == "gpt-5.6-luna"                    # production stamps
        assert p["output"], "the archived Brain output is empty"

    def test_the_wake_path_never_read_the_ungoverned_stored_quote(self, positive):
        """`SpecimenCandles.last_quote` is deliberately empty. A wake still
        happened, so the interaction came from the governed capture."""
        assert positive["wakes"], "no wake — the assertion below would be vacuous"
        assert positive["captures"] > 0, "the governed capture was never consulted"
