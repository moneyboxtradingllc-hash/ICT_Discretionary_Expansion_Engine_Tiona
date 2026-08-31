"""The authorization must die when the organism changes.

Twice on 2026-08-11 decision-relevant source changed while `verify_authorization`
still reported PASS:

  * v10-v12 created and materially rewrote `market_state/mtf_market_state.py`
    (the whole per-timeframe synthesis lane) -- fingerprint `...ab6366` unmoved.
  * v13 changed `ai_brain/brain_input.py` so Terra received the full
    per-timeframe invalidation menu instead of one collapsed summary level --
    brain contract `...cbcaf9` unmoved. That is not a refactor: the same market
    now produces a different set of choices.

The closure covered three files: prompt, schema, validator. Everything else
that determines what the Brain receives, or how its answer becomes a trade,
was outside it.

WHAT THIS FILE PINS: the closure's membership, both directions. A file that can
change the decision must be in it; the execution and mission-lifecycle modules
must stay OUT, because binding them would invalidate a live approval every time
a safety repair lands, without making any decision more honest.
"""
from __future__ import annotations

import hashlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain.production_model import (                            # noqa: E402
    _CONTRACT_SOURCES, _CONTRACT_SOURCES_REPO, brain_contract_fingerprint)

SRC = os.path.join(ROOT, "src")

#: Everything that changes WHAT THE BRAIN RECEIVES or HOW ITS ANSWER BECOMES A
#: TRADE. Each entry names why it is decision-relevant.
MUST_BE_BOUND = {
    "ai_brain/brain_prompt.py": "the instructions themselves",
    "ai_brain/brain_schema.py": "the shape of an acceptable answer",
    "ai_brain/brain_validation.py": "which answers are accepted or repaired",
    "ai_brain/brain_input.py": "the evidence payload -- the v13 defect",
    "narrative_authority/protected_swings.py": "which structures are protected",
    "market_state/mtf_market_state.py": "the per-timeframe synthesis",
    "structure/structure_flip.py": "the second invalidation family",
    "broker/luna_candidate_producer.py": "the invalidation/objective/TOOL catalogs",
    "broker/topstepx_combine_risk.py": "the risk doctrine and bracket geometry",
    "broker/daily_loss_budget.py":
        "whether a NEW ENTRY is permitted at all, the remaining session "
        "loss room, the dynamic ceiling on planned risk, and the "
        "CONTAMINATED/UNKNOWN fail-closed states that refuse an entry "
        "when realized-loss truth cannot be established",
    # ROADMAP STEP 7 (2026-08-12) — DELIBERATE GOVERNANCE DECISION, not drift.
    # Until Step 7 the toolbox was witness only: it changed what Terra SAW but
    # decided nothing, so it correctly sat outside the closure. Step 7 makes
    # `authorized_tool_catalog` gate authorization, so a detector threshold or a
    # zone-eligibility change now decides whether a candidate may exist at all.
    # Leaving these out would let that change silently alter what authorises
    # while an old approval still looked valid -- exactly the v13 failure this
    # closure exists to prevent.
    "toolbox/price_levels.py": "zone geometry and execution eligibility",
    "toolbox/toolbox_engine.py": "which tools are detected at all",
    # MARKET-REALITY CLOSURE (2026-08-12) — the third escape, and the worst.
    # PROD-20260812 launched armed against a production path that could not
    # fetch a single historical bar, grew a chart out of its own uptime, and the
    # fingerprint did not move one character. Toolbox decides whether a SETUP
    # exists; these decide whether the CHART exists.
    "broker/topstepx_live_session.py": "whether historical bars can be acquired at all",
    "data_feed/topstepx_provider.py": "acquisition, canonical ingestion, gap repair",
    "data_feed/startup_history_authority.py": "whether history may author an armed session",
    "data_feed/candle_continuity.py":
        "the fitness ALGORITHM itself -- coherent_window, contiguous_tail, "
        "verify_continuous and the 15-minute alignment constant. Binding the "
        "four obvious files while leaving this out would reproduce the defect "
        "one layer down: minimum_bars could drop to 5 and every authorization "
        "would still verify.",
    # v36 — the last hole in the same family. Acquisition decides WHICH 1m facts
    # exist; this decides how they become the 3m/5m/15m/1h world Terra reasons
    # about. A shifted boundary or an admitted partial bucket rewrites every
    # higher-timeframe structure the Brain sees.
    "data_feed/timeframe_builder.py":
        "how truthful 1m facts become the higher-timeframe chart Terra sees",
}

#: Bound, but anchored at the REPOSITORY ROOT rather than `src/`.
MUST_BE_BOUND_REPO = {
    "tools/topstepx_production_session.py":
        "the production entrypoint holds the armed startup authority call; "
        "deleting `candles=candles` would let an armed session scan a newborn "
        "chart while every authorization still verified. Living under tools/ "
        "is not an exemption -- authority decides inclusion, not directory.",
}

#: Deliberately OUT. Safety machinery: it governs how a decision is carried
#: out, not what is decided, and it changes far more often.
MUST_STAY_OUT = {
    "broker/topstepx_execution_runner.py",
    "broker/topstepx_mission_state.py",
    "broker/topstepx_mission_reconciler.py",
    "broker/topstepx_mission_recovery.py",
    "broker/topstepx_production_loop.py",
    "broker/topstepx_production_session.py",
    "broker/topstepx_submission_record.py",
    # circular: the container that carries the hash, and the module computing it
    "broker/topstepx_session_authorization.py",
    "ai_brain/production_model.py",
    # Collector/diagnostic tooling. It exposes bars_1m too, but the production
    # path does not use it -- binding it would invalidate approvals when an
    # offline collector changed, which is overbinding, not governance.
    "broker/topstepx_readonly.py",
}

BOUND = {rel for _, rel in _CONTRACT_SOURCES}
BOUND_REPO = {rel for _, rel in _CONTRACT_SOURCES_REPO}


class TestMembership:

    @pytest.mark.parametrize("rel,why", sorted(MUST_BE_BOUND.items()))
    def test_decision_relevant_source_is_bound(self, rel, why):
        assert rel in BOUND, f"{rel} can change the decision ({why}) but is unbound"

    @pytest.mark.parametrize("rel", sorted(MUST_STAY_OUT))
    def test_lifecycle_machinery_stays_out(self, rel):
        assert rel not in BOUND, (
            f"{rel} is execution machinery; binding it would kill live "
            "authorizations on every safety repair")

    @pytest.mark.parametrize("rel,why", sorted(MUST_BE_BOUND_REPO.items()))
    def test_repo_rooted_source_is_bound(self, rel, why):
        assert rel in BOUND_REPO, f"{rel} can change the decision ({why}) but is unbound"

    def test_a_semantic_edit_to_the_loss_governor_moves_the_fingerprint(self):
        """MEMBERSHIP IS NOT BINDING, so this proves the seal actually bites.

        The list above says the governor OUGHT to be bound. This mutates the
        real file on disk -- the remaining-room arithmetic itself -- and asserts
        the digest moves, which is the property the owner actually asked for:
        an isolated edit to this module, touching no entrypoint, must invalidate
        a previously minted execution authorization.
        """
        import importlib, os, shutil, tempfile
        from ai_brain import production_model as PM
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
            PM.__file__))), "broker", "daily_loss_budget.py")
        before = PM.brain_contract_fingerprint()
        backup = tempfile.NamedTemporaryFile(delete=False).name
        shutil.copyfile(src, backup)
        try:
            raw = open(src, "rb").read()
            assert b"remaining" in raw, "the arithmetic this test mutates moved"
            open(src, "wb").write(raw.replace(b"remaining", b"rem_aining", 1))
            after = PM.brain_contract_fingerprint()
        finally:
            shutil.copyfile(backup, src)
            os.unlink(backup)
        assert after != before, (
            "daily_loss_budget.py was edited and the Brain contract "
            "fingerprint did not move; the governor is NOT sealed")
        assert PM.brain_contract_fingerprint() == before, "restore failed"

    def test_the_closure_is_exactly_this_set(self):
        assert BOUND == set(MUST_BE_BOUND), (
            "the closure changed without this list changing; membership is a "
            "governance decision, not an implementation detail")
        assert BOUND_REPO == set(MUST_BE_BOUND_REPO)

    def test_every_bound_path_actually_exists(self):
        for _, rel in _CONTRACT_SOURCES:
            assert os.path.exists(os.path.join(SRC, rel)), rel
        for _, rel in _CONTRACT_SOURCES_REPO:
            assert os.path.exists(os.path.join(ROOT, rel)), rel

    def test_the_two_anchors_do_not_overlap(self):
        """A path bound under both anchors would be hashed twice and could mask
        a change in one of them."""
        assert not (BOUND & BOUND_REPO)

    def test_labels_are_unique(self):
        labels = [label for label, _ in _CONTRACT_SOURCES + _CONTRACT_SOURCES_REPO]
        assert len(labels) == len(set(labels)), "a duplicate label collapses two files"


class TestHashingIsDeterministicAndSensitive:

    def test_repeated_calls_agree(self):
        assert brain_contract_fingerprint() == brain_contract_fingerprint()

    def test_it_is_a_stable_shape(self):
        fp = brain_contract_fingerprint()
        assert fp.startswith("brain:") and len(fp) == len("brain:") + 16

    @pytest.mark.parametrize("rel", sorted(MUST_BE_BOUND))
    def test_touching_any_bound_file_changes_the_fingerprint(self, rel, tmp_path):
        """One byte in ANY member must move it. Restored via the original bytes,
        and the restore is verified by hash -- not by a finally block alone."""
        path = os.path.join(SRC, rel)
        original = open(path, "rb").read()
        digest = hashlib.sha256(original).hexdigest()
        before = brain_contract_fingerprint()
        try:
            with open(path, "wb") as fh:
                fh.write(original + b"\n# closure probe\n")
            assert brain_contract_fingerprint() != before, \
                f"editing {rel} left the authorization valid"
        finally:
            with open(path, "wb") as fh:
                fh.write(original)
        assert hashlib.sha256(open(path, "rb").read()).hexdigest() == digest
        assert brain_contract_fingerprint() == before

    @pytest.mark.parametrize("rel", sorted(MUST_BE_BOUND_REPO))
    def test_touching_the_production_entrypoint_changes_the_fingerprint(self, rel):
        """The entrypoint is hashed from the REPOSITORY ROOT, not from src/.
        A second anchor is easy to wire up so that it silently hashes
        `<missing>` for every file, which would bind nothing at all."""
        path = os.path.join(ROOT, rel)
        original = open(path, "rb").read()
        digest = hashlib.sha256(original).hexdigest()
        before = brain_contract_fingerprint()
        try:
            with open(path, "wb") as fh:
                fh.write(original + b"\n# closure probe\n")
            assert brain_contract_fingerprint() != before, \
                f"editing {rel} left the authorization valid"
        finally:
            with open(path, "wb") as fh:
                fh.write(original)
        assert hashlib.sha256(open(path, "rb").read()).hexdigest() == digest
        assert brain_contract_fingerprint() == before

    def test_the_repo_anchor_is_not_silently_resolving_to_missing(self):
        """If the second anchor were wrong, every repo-rooted member would hash
        as `<missing>` and the mutation test above would still pass for the
        wrong reason -- because deleting bytes from a file nobody reads cannot
        change anything. Prove the file is actually being READ."""
        for _, rel in _CONTRACT_SOURCES_REPO:
            assert os.path.isfile(os.path.join(ROOT, rel)), rel
            assert not os.path.exists(os.path.join(SRC, rel)), (
                f"{rel} also resolves under src/; the anchor under test is ambiguous")

    def test_a_MISSING_bound_source_is_distinguishable_from_an_EMPTY_one(self):
        """Survived the first closure mutation campaign.

        `<missing>` is not decoration. Without that marker an absent bound file
        contributes only its label -- exactly what an EMPTY file contributes --
        so deleting a load-bearing source would produce the same fingerprint as
        blanking it, and "the file is gone" would be indistinguishable from "the
        file says nothing". Moved aside with `os.replace` rather than deleted:
        an interrupted test must never be able to lose a production source.
        """
        path = os.path.join(SRC, "data_feed", "startup_history_authority.py")
        aside = path + ".closure-probe"
        original = open(path, "rb").read()
        digest = hashlib.sha256(original).hexdigest()
        try:
            os.replace(path, aside)
            missing = brain_contract_fingerprint()
        finally:
            os.replace(aside, path)
        try:
            with open(path, "wb") as fh:
                fh.write(b"")
            empty = brain_contract_fingerprint()
        finally:
            with open(path, "wb") as fh:
                fh.write(original)
        assert hashlib.sha256(open(path, "rb").read()).hexdigest() == digest
        assert missing != empty, (
            "an absent bound source hashes the same as an empty one; the "
            "<missing> marker is load-bearing")

    def test_ordering_is_fixed_not_filesystem_dependent(self):
        """A closure hashed in directory order would drift between machines."""
        assert isinstance(_CONTRACT_SOURCES, tuple)

    def test_a_lifecycle_edit_does_NOT_change_it(self, tmp_path):
        """The other direction: safety repairs must not invalidate approvals."""
        path = os.path.join(SRC, "broker", "topstepx_mission_reconciler.py")
        original = open(path, "rb").read()
        before = brain_contract_fingerprint()
        try:
            with open(path, "wb") as fh:
                fh.write(original + b"\n# lifecycle probe\n")
            assert brain_contract_fingerprint() == before
        finally:
            with open(path, "wb") as fh:
                fh.write(original)


class TestTheHistoricalMisses:
    """Named so the escapes cannot quietly return."""

    def test_brain_input_is_bound_v13(self):
        assert "ai_brain/brain_input.py" in BOUND

    def test_mtf_market_state_is_bound_v10_v12(self):
        assert "market_state/mtf_market_state.py" in BOUND

    def test_market_reality_is_bound_prod20260812(self):
        for rel in ("broker/topstepx_live_session.py",
                    "data_feed/topstepx_provider.py",
                    "data_feed/startup_history_authority.py",
                    "data_feed/candle_continuity.py",
                    "data_feed/timeframe_builder.py"):
            assert rel in BOUND, rel
        assert "tools/topstepx_production_session.py" in BOUND_REPO

    def test_the_whole_chart_pipeline_is_bound_end_to_end(self):
        """venue history -> canonical 1m -> continuity/fitness -> higher
        timeframes -> Terra. Every hop that can change what the Brain sees."""
        for rel in ("broker/topstepx_live_session.py",      # acquisition
                    "data_feed/topstepx_provider.py",       # canonical 1m
                    "data_feed/candle_continuity.py",       # continuity law
                    "data_feed/startup_history_authority.py",  # fitness
                    "data_feed/timeframe_builder.py",       # 3m/5m/15m/1h
                    "market_state/mtf_market_state.py"):    # per-TF synthesis
            assert rel in BOUND, f"{rel} is a hop in the chart pipeline"


class TestAnAuthorizationDiesWhenMarketRealityChanges:
    """§6 — the end-to-end governance proof, through the real verifier.

    Membership lists and digest comparisons are necessary but not sufficient:
    what actually matters is that a signed authorization REFUSES after the
    market-data contract moves underneath it. On 2026-08-12 it did not.
    """

    ACCT = "acct:test000000"
    CID = "CON.F.US.MNQ.U26"
    DATE = "20260812"

    def _issue(self, tmp_path):
        from broker import topstepx_session_authorization as SA
        return SA.issue(path=str(tmp_path / "auth.json"), session_id="TEST-CLOSURE",
                        account_fingerprint=self.ACCT, contract_id=self.CID,
                        session_date=self.DATE)

    def test_a_freshly_issued_authorization_verifies(self, tmp_path):
        auth = self._issue(tmp_path)
        auth.verify(account_fingerprint=self.ACCT, contract_id=self.CID,
                    session_date=self.DATE)

    def test_it_records_the_CURRENT_fingerprint(self, tmp_path):
        auth = self._issue(tmp_path)
        assert auth.brain_contract_fingerprint == brain_contract_fingerprint()

    @pytest.mark.parametrize("rel", [
        "broker/topstepx_live_session.py",
        "data_feed/topstepx_provider.py",
        "data_feed/startup_history_authority.py",
        "data_feed/candle_continuity.py",
        "data_feed/timeframe_builder.py",
    ])
    def test_changing_market_reality_INVALIDATES_a_signed_authorization(self, rel, tmp_path):
        from broker import topstepx_session_authorization as SA
        auth = self._issue(tmp_path)
        path = os.path.join(SRC, rel)
        original = open(path, "rb").read()
        digest = hashlib.sha256(original).hexdigest()
        try:
            with open(path, "wb") as fh:
                fh.write(original + b"\n# market reality probe\n")
            with pytest.raises(SA.AuthorizationRefused) as exc:
                auth.verify(account_fingerprint=self.ACCT, contract_id=self.CID,
                            session_date=self.DATE)
            assert "BRAIN_CONTRACT_CHANGED" in str(exc.value)
        finally:
            with open(path, "wb") as fh:
                fh.write(original)
        assert hashlib.sha256(open(path, "rb").read()).hexdigest() == digest
        auth.verify(account_fingerprint=self.ACCT, contract_id=self.CID,
                    session_date=self.DATE)

    def test_changing_the_production_entrypoint_INVALIDATES_it_too(self, tmp_path):
        from broker import topstepx_session_authorization as SA
        auth = self._issue(tmp_path)
        path = os.path.join(ROOT, "tools", "topstepx_production_session.py")
        original = open(path, "rb").read()
        digest = hashlib.sha256(original).hexdigest()
        try:
            with open(path, "wb") as fh:
                fh.write(original + b"\n# entrypoint probe\n")
            with pytest.raises(SA.AuthorizationRefused) as exc:
                auth.verify(account_fingerprint=self.ACCT, contract_id=self.CID,
                            session_date=self.DATE)
            assert "BRAIN_CONTRACT_CHANGED" in str(exc.value)
        finally:
            with open(path, "wb") as fh:
                fh.write(original)
        assert hashlib.sha256(open(path, "rb").read()).hexdigest() == digest

    def test_a_lifecycle_edit_does_NOT_invalidate_it(self, tmp_path):
        """§7 — no overbinding. Safety repairs must not kill live approvals."""
        auth = self._issue(tmp_path)
        path = os.path.join(SRC, "broker", "topstepx_mission_reconciler.py")
        original = open(path, "rb").read()
        try:
            with open(path, "wb") as fh:
                fh.write(original + b"\n# lifecycle probe\n")
            auth.verify(account_fingerprint=self.ACCT, contract_id=self.CID,
                        session_date=self.DATE)
        finally:
            with open(path, "wb") as fh:
                fh.write(original)
