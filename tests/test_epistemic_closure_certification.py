"""EPISTEMIC-CLOSURE-CERTIFICATION-1 — the gate, and proof that it bites.

THE DOCTRINE: no market fact may receive Luna decision authority until its
semantic, lifecycle, temporal, authority, consumer and replay contracts are
explicitly certified. A field name is not a semantic contract, and a green unit
test is not epistemic certification -- both were true of `registered_at` while
the producer re-stamped it and every consumer read it as a birth time.

THE MUTATION CAMPAIGN IS THE LOAD-BEARING PART. A verifier that returns False
when handed obvious garbage proves nothing. `TestMutationCampaign` reproduces the
SHAPE of defects this repository has actually suffered and requires the gate to
catch each one. If those tests are ever weakened, the gate is decoration.

NO BROKER, NO PROVIDER, NO NETWORK, NO ORDER.
"""
from __future__ import annotations

import copy
import glob
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from rule_governance.epistemic_closure import bootstrap_debt as BD                # noqa: E402
from rule_governance.epistemic_closure import capability_matrix as CM                 # noqa: E402
from rule_governance.epistemic_closure import closure_verifier as CV                  # noqa: E402
from rule_governance.epistemic_closure import fact_registry as FR                     # noqa: E402
from rule_governance.epistemic_closure import payload_coverage as PC                  # noqa: E402
from rule_governance.epistemic_closure import semantic_predicates as SP               # noqa: E402
from rule_governance.epistemic_closure.fact_contract import (BLOCKED, BRAIN_NARRATIVE,  # noqa: E402
                                           CANDIDATE_GENERATION, CERTIFIED,
                                           LEGACY, OBJECTIVE_RANKING,
                                           OBSERVE_ONLY, validate)

ARCHIVE = os.path.join(ROOT, "data", "ai_brain")


def payloads(day="20260825", limit=None):
    from ai_brain.brain_input import build_brain_input
    out = []
    for path in sorted(glob.glob(os.path.join(ARCHIVE, f"{day}_*_MNQ.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                snap = json.load(fh)["raw_snapshot"]
        except Exception:  # noqa: BLE001
            continue
        out.append((os.path.basename(path), build_brain_input(snap, {})))
        if limit and len(out) >= limit:
            break
    return out


@pytest.fixture(scope="module")
def real_payloads():
    got = payloads()
    if not got:
        pytest.skip("archived canonical snapshots absent")
    return got


def mutate(monkeypatch, fact_id, **changes):
    """Substitute one contract with a defective copy."""
    contracts = []
    for contract in FR.CONTRACTS:
        if contract["fact_id"] == fact_id:
            contract = dict(copy.deepcopy(contract), **changes)
        contracts.append(contract)
    monkeypatch.setattr(FR, "CONTRACTS", tuple(contracts))
    return contracts


def kinds(report):
    return {f["kind"] for f in report["findings"]}


# ══ THE GATE PASSES TODAY ═══════════════════════════════════════════════════
class TestTheGateHolds:

    def test_the_registry_is_well_formed(self):
        assert FR.validate_registry() == []

    def test_every_contract_individually_validates(self):
        for contract in FR.CONTRACTS:
            assert validate(contract) == [], contract["fact_id"]

    def test_the_capability_matrix_is_internally_honest(self):
        assert CM.validate_matrix() == []

    def test_the_payload_manifest_is_consistent(self):
        assert PC.validate_manifest() == []

    def test_the_full_gate_passes(self):
        report = CV.verify(run_predicates=False)
        assert report["ok"], report["findings"]

    def test_the_gate_passes_with_semantics_executed(self):
        report = CV.verify()
        assert report["ok"], report["findings"]
        statuses = {r["status"] for r in report["semantic_results"]}
        assert "FAIL" not in statuses and "ERROR" not in statuses

    def test_the_report_renders_without_the_code(self):
        text = CV.render(CV.verify(run_predicates=False))
        assert "EPISTEMIC CLOSURE:" in text
        assert "KNOWN BLOCKED CAPABILITIES" in text


# ══ HONEST BOOTSTRAP ════════════════════════════════════════════════════════
class TestBootstrapIsHonest:
    """§19: passing must NOT mean the roadmap is finished. It must mean the
    organism knows what it knows AND what it does not."""

    def test_blocked_facts_are_actually_registered_blocked(self):
        blocked = {c["fact_id"] for c in FR.with_class(BLOCKED)}
        for expected in ("occurrence.causal_event_key.category_b",
                         "recovery.session_state_completeness",
                         "liquidity.pool_lifecycle",
                         "active_path.multi_scope",
                         "dealing_range.containment",
                         "occurrence.sweep_writer_authority"):
            assert expected in blocked, expected

    def test_the_legacy_liquidity_fields_are_not_certified(self):
        legacy = {c["fact_id"] for c in FR.with_class(LEGACY)}
        assert "liquidity.brain.nearest_buy_side" in legacy
        assert "liquidity.brain.nearest_sell_side" in legacy

    def test_category_a_is_capability_not_production(self):
        contract = FR.get("occurrence.causal_event_key.category_a")
        assert contract["authority_class"] == CERTIFIED
        assert "CAPABILITY ONLY" in " ".join(contract["limitations"])
        assert SP.run("causal.production_is_v1")["status"] == "PASS"

    def test_the_scale_hierarchy_is_representation_not_brain_authority(self):
        contract = FR.get("liquidity.scale_hierarchy")
        assert contract["authority_class"] != CERTIFIED
        assert "NOT AS BRAIN AUTHORITY" in " ".join(contract["limitations"])

    def test_every_blocked_capability_names_its_owning_unit(self):
        """A gap that names no owner is a complaint, not a plan.

        Ownership is a FIELD. Two earlier versions of this test inferred it from
        prose -- first by looking for a "-1" suffix, then for the phrase "Owned
        by" -- and both would pass any sentence that happened to contain the
        pattern. `owner_unit` is validated directly."""
        for cap in CM.blocked():
            assert cap.get("owner_unit"), cap["capability_id"]

    def test_the_uncertified_debt_is_counted_not_hidden(self, real_payloads):
        report = CV.verify(run_predicates=False, payload=real_payloads[-1][1])
        assert report["ok"]
        assert report["uncertified_debt"] > 0, (
            "a zero debt at bootstrap would mean the manifest is claiming more "
            "than this framework has actually certified")

    def test_grandfathered_debt_is_declared_dated_and_owned(self):
        """The mechanism that replaced `accepted_promotion`. Every debt pins its
        exact blast radius, its discovery date and who owes the remediation."""
        report = CV.verify(run_predicates=False)
        debts = report["grandfathered_authority_debts"]
        assert len(debts) == 3
        for row in debts:
            assert row["reason"] and row["remediation_owner_unit"]
            assert row["discovered_on"] == BD.BOOTSTRAP_DATE
            assert row["payload_paths"] and row["consumers"] and row["influence"]


# ══ BRAIN PAYLOAD COVERAGE ══════════════════════════════════════════════════
class TestBrainPayloadCoverage:

    def test_every_path_of_every_archived_payload_is_classified(self):
        """THE FRONTIER. Run across BOTH tapes, not a sample: a lane manifest
        that only covers the payload shape you happened to look at is not a
        gate."""
        unclassified = {}
        checked = 0
        for day in ("20260825", "20260824"):
            for name, payload in payloads(day):
                checked += 1
                for path in PC.coverage(payload)["unclassified"]:
                    unclassified.setdefault(path, name)
        if not checked:
            pytest.skip("archived canonical snapshots absent")
        assert unclassified == {}, unclassified

    def test_coverage_maps_only_registered_facts(self, real_payloads):
        registry = FR.by_id()
        for _name, payload in real_payloads[:5]:
            for fact_id in PC.coverage(payload)["contracted_facts"]:
                assert fact_id in registry

    def test_a_path_belongs_to_exactly_one_lane(self, real_payloads):
        _name, payload = real_payloads[-1]
        report = PC.coverage(payload)
        seen = []
        for lane_paths in report["lanes"].values():
            seen.extend(lane_paths)
        assert len(seen) == len(set(seen)), "a path was classified twice"


# ══ THE MUTATION CAMPAIGN ═══════════════════════════════════════════════════
class TestMutationCampaign:
    """§17. Each mutation resembles a defect this repository has actually
    suffered. A gate that cannot catch these is not a gate."""

    def test_M1_protected_swing_restamp_fails_certification(self, monkeypatch):
        """THE DEFECT THAT CREATED THIS FRAMEWORK. Restore the pre-repair
        tracker -- a blind whole-record assignment -- and the semantic predicate
        must catch it on real tape."""
        from narrative_authority.protected_swings import ProtectedSwingTracker

        def blind_register(existing, *, tf, side, level, ts, basis):
            return {"level": round(level, 4), "timeframe": tf,
                    "role": "execution", "registered_at": ts,
                    "swing_id": f"{tf}:swing_{side}:{round(level, 4):g}",
                    "basis": basis}

        monkeypatch.setattr(ProtectedSwingTracker, "_register",
                            staticmethod(blind_register))
        result = SP.run("protected_swing.formation_immutable")
        assert result["status"] == "FAIL", result
        assert "re-stamp" in result["detail"]

    def test_M2_declaring_a_legacy_field_certified_fails(self, monkeypatch):
        """Claiming `nearest_buy_side` means what its name says, while the
        predicate proving it is highest-timeframe-first still stands.

        This is the subtle route: grandfathering excuses the fact from the
        promotion gate, so promoting it by editing its class would otherwise
        pass unchallenged. The debt manifest pins the class it HAD."""
        mutate(monkeypatch, "liquidity.brain.nearest_buy_side",
               authority_class=CERTIFIED)
        report = CV.verify(run_predicates=False)
        assert not report["ok"]
        drift = [f for f in report["blockers"]
                 if f["kind"] == "AUTHORITY_EXPANSION"]
        assert drift, kinds(report)
        assert drift[0]["fact_id"] == "liquidity.brain.nearest_buy_side"
        assert "silent promotion" in drift[0]["detail"]

    def test_M3_wiring_recovery_without_updating_the_contract_fails(
            self, monkeypatch, tmp_path):
        """A late start silently gaining production recovery. The CODE changing
        while the CONTRACT still says BLOCKED is exactly the drift this catches."""
        fake = tmp_path / "startup_wiring.py"
        fake.write_text("from market_state import session_recovery\n",
                        encoding="utf-8")

        real_walk = os.walk

        def walk_with_intruder(path, *a, **kw):
            for entry in real_walk(path, *a, **kw):
                yield entry
            yield (str(tmp_path), [], ["startup_wiring.py"])

        monkeypatch.setattr(SP.os, "walk", walk_with_intruder)
        result = SP.run("recovery.kernel_unwired")
        assert result["status"] == "FAIL", result
        assert "startup_wiring.py" in result["detail"]

    def test_M4_one_event_with_many_identities_fails(self, monkeypatch):
        """Re-introduce scan-clock identity: one 15m edge minting a key per
        observation."""
        import market_data.causal_identity as CI
        original = CI.causal_event_key

        def scan_keyed(occurrence):
            key = original(occurrence)
            if key and isinstance(occurrence, dict):
                return f"{key}|{occurrence.get('observed_at')}"
            return key

        monkeypatch.setattr(CI, "causal_event_key", scan_keyed)
        result = SP.run("causal.one_edge_one_event")
        assert result["status"] == "FAIL", result
        assert "collapse did not occur" in result["detail"]

    def test_M5_a_new_brain_fact_without_a_contract_fails(self, real_payloads):
        """§7's real requirement: a new decision-bearing field cannot arrive
        silently."""
        _name, payload = real_payloads[-1]
        mutated = copy.deepcopy(payload)
        mutated["institutional_flow"] = {"bias": "bullish", "confidence": 0.8}
        report = CV.verify(run_predicates=False, payload=mutated)
        assert not report["ok"]
        assert "COVERAGE" in kinds(report)
        assert any("institutional_flow" in f["detail"] for f in report["findings"])

    def test_M6_promoting_a_blocked_fact_to_objective_authority_fails(
            self, monkeypatch):
        """A BLOCKED claim quietly acquiring objective-ranking authority."""
        mutate(monkeypatch, "liquidity.pool_lifecycle",
               decision_influence=(OBJECTIVE_RANKING, CANDIDATE_GENERATION))
        report = CV.verify(run_predicates=False)
        assert not report["ok"]
        assert "PROMOTION" in kinds(report) or "REGISTRY" in kinds(report)

    def test_M7_two_semantic_writers_cannot_be_certified(self, monkeypatch):
        """The dual sweep writer, if anyone tried to certify it."""
        mutate(monkeypatch, "occurrence.sweep_writer_authority",
               authority_class=CERTIFIED,
               certification_tests=("tests/test_epistemic_closure_certification.py",))
        report = CV.verify(run_predicates=False)
        assert not report["ok"]
        assert "OWNERSHIP" in kinds(report)

    def test_M7b_the_unresolved_owner_is_registered_as_a_gap_today(self):
        contract = FR.get("occurrence.sweep_writer_authority")
        assert contract["authority_class"] == BLOCKED
        assert contract["producer_owner"].startswith("UNRESOLVED")
        assert CM.status_of("occurrence.single_semantic_owner") == BLOCKED


# ══ THE GATE'S OWN INTEGRITY ════════════════════════════════════════════════
class TestTheGateCannotBeSoftened:

    def test_a_certified_fact_needs_certification_tests(self, monkeypatch):
        mutate(monkeypatch, "protected_swing.registered_at",
               certification_tests=())
        report = CV.verify(run_predicates=False)
        assert not report["ok"]
        assert {"TESTS", "REGISTRY"} & kinds(report)

    def test_a_named_certification_test_must_exist(self, monkeypatch):
        mutate(monkeypatch, "protected_swing.registered_at",
               certification_tests=("tests/test_this_never_existed.py::X",))
        report = CV.verify(run_predicates=False)
        assert not report["ok"]
        assert "TESTS" in kinds(report)

    def test_a_contract_cannot_grant_itself_an_exemption(self, monkeypatch):
        """THE REJECTED MECHANISM, kept out. `accepted_promotion` let any
        contract excuse itself by carrying a reason, an owner and a date. It is
        gone, and adding the field back grants nothing: exemption comes only
        from membership of the frozen bootstrap universe."""
        mutate(monkeypatch, "liquidity.pool_lifecycle",
               accepted_promotion={"reason": "r", "owner_unit": "U",
                                   "accepted_on": "2027-01-01"},
               decision_influence=(OBJECTIVE_RANKING,))
        report = CV.verify(run_predicates=False)
        assert not report["ok"]
        assert {"PROMOTION", "REGISTRY"} & kinds(report)

    def test_only_universe_membership_confers_exemption(self):
        """Exemption is not a property a contract can carry. It is membership of
        an immutable historical set, checked against the fact_id alone."""
        for contract in FR.CONTRACTS:
            excused = BD.is_grandfathered(contract["fact_id"])
            assert excused == (contract["fact_id"] in BD.BOOTSTRAP_DEBT_UNIVERSE)

    def test_a_decision_bearing_fact_needs_a_semantic_predicate(self, monkeypatch):
        """The `registered_at` lesson: a consumer's belief must be bound to the
        producer by something executable."""
        mutate(monkeypatch, "active_path.owner", semantic_predicates=())
        report = CV.verify(run_predicates=False)
        assert not report["ok"]
        assert "CONSUMER" in kinds(report)

    def test_an_unknown_semantic_predicate_is_caught(self, monkeypatch):
        mutate(monkeypatch, "active_path.owner",
               semantic_predicates=("nope.does.not.exist",))
        report = CV.verify(run_predicates=False)
        assert not report["ok"]
        assert "CONSUMER" in kinds(report)

    def test_a_crashing_predicate_is_a_failure_not_a_pass(self, monkeypatch):
        def explode():
            raise RuntimeError("tape unreadable")
        monkeypatch.setitem(SP.PREDICATES, "causal.production_is_v1", explode)
        result = SP.run("causal.production_is_v1")
        assert result["status"] == "ERROR"
        report = CV.verify()
        assert not report["ok"]
        assert "SEMANTIC" in kinds(report)

    def test_a_capability_may_not_rest_on_an_uncertified_fact(self, monkeypatch):
        mutate(monkeypatch, "protected_swing.registered_at",
               authority_class=OBSERVE_ONLY, decision_influence=("telemetry_only",))
        report = CV.verify(run_predicates=False)
        assert not report["ok"]
        assert "MATRIX" in kinds(report)

    def test_a_duplicate_fact_id_is_caught(self, monkeypatch):
        doubled = tuple(list(FR.CONTRACTS) + [copy.deepcopy(FR.CONTRACTS[0])])
        monkeypatch.setattr(FR, "CONTRACTS", doubled)
        report = CV.verify(run_predicates=False)
        assert not report["ok"]
        assert "REGISTRY" in kinds(report)

    def test_a_consumer_without_a_stated_belief_is_invalid(self):
        contract = copy.deepcopy(FR.get("active_path.owner"))
        contract["consumers"] = [{"name": "somewhere", "influence": BRAIN_NARRATIVE}]
        problems = validate(contract)
        assert any("believes" in p for p in problems)


# ══ LEGACY AND BLOCKED FACTS STAY THAT WAY ══════════════════════════════════
class TestLegacyFactsAreNotCertified:

    def test_the_legacy_label_is_earned_on_real_data(self):
        for pid in ("liquidity.nearest_is_htf_first",
                    "liquidity.sell_side_is_htf_first"):
            result = SP.run(pid)
            assert result["status"] in ("PASS", "SKIPPED"), result

    def test_the_capability_says_nearest_is_not_nearest(self):
        assert CM.status_of("liquidity.nearest_is_nearest") == BLOCKED


class TestBlockedFactsStayBlocked:

    def test_the_dealing_range_is_still_unclamped(self):
        result = SP.run("range.position_unclamped")
        assert result["status"] in ("PASS", "SKIPPED"), result

    def test_containment_authority_is_blocked(self):
        assert FR.get("dealing_range.containment")["authority_class"] == BLOCKED
        assert CM.status_of("range.containment") == BLOCKED

    def test_category_b_mints_nothing(self):
        result = SP.run("causal.category_b_refused")
        assert result["status"] in ("PASS", "SKIPPED"), result


class TestAuthorityOwnership:

    def test_no_certified_fact_has_an_unresolved_owner(self):
        for contract in FR.with_class(CERTIFIED):
            owner = contract["producer_owner"]
            assert not owner.startswith(("UNRESOLVED", "NONE")), contract["fact_id"]

    def test_the_dual_sweep_writer_is_recorded_as_the_gap_it_is(self):
        assert CV.check_ownership() == []
        contract = FR.get("occurrence.sweep_writer_authority")
        assert "SWEEP-OCCURRENCE-AUTHORITY-1" in " ".join(contract["limitations"])


# ══ ORGANISM-LEVEL END-TO-END ═══════════════════════════════════════════════
class TestOrganismEpistemicClosure:
    """§13. Real archived tape -> canonical mechanics -> state -> Brain payload,
    asserting not that Luna is RIGHT but that every load-bearing fact survived
    the pipeline with a certified owner and no blocked fact was promoted."""

    @pytest.mark.parametrize("day", ["20260825", "20260824"])
    def test_the_pipeline_preserves_certified_semantics(self, day):
        got = payloads(day)
        if not got:
            pytest.skip(f"archive for {day} absent")
        name, payload = got[-1]

        report = CV.verify(run_predicates=False, payload=payload)
        assert report["ok"], report["findings"]

        # the fact that burned us must survive the whole pipeline with meaning
        by_tf = (payload.get("protected_swings") or {}).get("by_timeframe") or {}
        stamps = [rec.get("registered_at")
                  for side in ("lows", "highs")
                  for rec in (by_tf.get(side) or {}).values()]
        for stamp in stamps:
            assert stamp, f"{name}: a protected level reached Luna with no birth time"
            assert stamp <= payload["timestamp"], (
                f"{name}: a level claims to have been born in the future")

    def test_no_blocked_fact_reaches_a_decision_lane_undeclared(self):
        report = CV.verify(run_predicates=False)
        assert "PROMOTION" not in kinds(report)

    def test_the_pre_live_report_states_what_mechanics_believes(self):
        from rule_governance.epistemic_closure.pre_live_report import render_payload_truth
        text = render_payload_truth()
        if "No archived canonical snapshot" in text:
            pytest.skip("archive absent")
        for heading in ("ACTIVE PATH", "PROTECTED STRUCTURE", "LIQUIDITY",
                        "DEALING RANGE", "SESSION COMPLETENESS",
                        "KNOWN REPRESENTATION GAPS"):
            assert heading in text, heading
        # it must state limits, not only values
        assert "HIGHEST-TIMEFRAME-FIRST" in text
        assert "Startup recovery is NOT wired" in text

    def test_the_report_is_not_in_the_hot_path(self):
        offenders = []
        for root, _dirs, files in os.walk(os.path.join(ROOT, "src")):
            if "__pycache__" in root or "epistemic_closure" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(root, name), encoding="utf-8") as fh:
                    if "pre_live_report" in fh.read():
                        offenders.append(name)
        assert offenders == [], offenders


# ══ GOVERNANCE DECIDES NOTHING ══════════════════════════════════════════════
class TestGovernanceIsInert:

    def test_no_production_module_imports_fact_governance(self):
        offenders = []
        for root, _dirs, files in os.walk(os.path.join(ROOT, "src")):
            if "__pycache__" in root or "epistemic_closure" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(root, name), encoding="utf-8") as fh:
                    if "epistemic_closure" in fh.read():
                        offenders.append(name)
        assert offenders == [], offenders

    def test_the_package_reaches_no_broker_or_provider(self):
        import inspect

        from rule_governance.epistemic_closure import fact_contract
        for module in (fact_contract, FR, CM, PC, CV, SP):
            src = inspect.getsource(module).lower()
            for banned in ("place_order", "modify_order", "requests.",
                           "websocket", "topstepx_client"):
                assert banned not in src, f"{module.__name__}: {banned}"

    def test_the_brain_payload_is_unchanged_by_this_unit(self, real_payloads):
        """Governance observes the payload; it may never add to it."""
        _name, payload = real_payloads[-1]
        assert "epistemic_closure" not in json.dumps(payload, default=str)


# ══ GRANDFATHERED DEBT — FROZEN, NON-EXPANDABLE, PROVABLY REMOVABLE ═════════
class TestGrandfatheredDebtIsFrozen:
    """Bootstrap debt is HISTORICAL INVENTORY, not future permission.

    The mechanism it replaced -- a per-contract `accepted_promotion` block --
    was a form to fill in: any future BLOCKED fact could have acquired decision
    authority by writing a reason, an owner and a date. These tests exist so
    that cannot come back.
    """

    def test_the_frozen_set_is_exactly_the_bootstrap_debt(self):
        """PINNED. Adding a member must break this test, which is the point:
        it forces a conscious governance review rather than a quiet diff."""
        assert BD.GRANDFATHERED_FACT_IDS == frozenset({
            "liquidity.brain.nearest_buy_side",
            "liquidity.brain.nearest_sell_side",
            "dealing_range.containment",
        })

    def test_each_debt_pins_its_exact_authority_surface(self):
        expected = {
            "liquidity.brain.nearest_buy_side":
                ("liquidity.brain.nearest_buy_side",
                 ("liquidity.nearest_buy_side",), ("ai_brain.brain_prompt",),
                 "brain_narrative"),
            "liquidity.brain.nearest_sell_side":
                ("liquidity.brain.nearest_sell_side",
                 ("liquidity.nearest_sell_side",), ("ai_brain.brain_prompt",),
                 "brain_narrative"),
            "dealing_range.containment":
                ("dealing_range.containment", ("market.dealing_range",),
                 ("ai_brain.brain_prompt",), "brain_narrative"),
        }
        for debt in BD.GRANDFATHERED_AUTHORITY_DEBT:
            assert BD.authority_surface(debt) == expected[debt["fact_id"]]

    def test_the_manifest_validates(self):
        assert BD.validate_manifest() == []

    def test_no_contract_carries_an_acceptance_block(self):
        """The rejected mechanism must be gone, not merely unused."""
        for contract in FR.CONTRACTS:
            assert "accepted_promotion" not in contract, contract["fact_id"]

    def test_M8_a_grandfathered_fact_gaining_a_consumer_fails(self, monkeypatch):
        """Grandfathering freezes the EXISTING blast radius."""
        contract = copy.deepcopy(FR.get("liquidity.brain.nearest_buy_side"))
        contract["consumers"] = list(contract["consumers"]) + [{
            "name": "broker.luna_candidate_producer",
            "believes": "a target", "influence": CANDIDATE_GENERATION}]
        mutate(monkeypatch, "liquidity.brain.nearest_buy_side",
               consumers=contract["consumers"])
        report = CV.verify(run_predicates=False)
        assert not report["ok"]
        expansion = [f for f in report["blockers"]
                     if f["kind"] == "AUTHORITY_EXPANSION"]
        assert expansion, kinds(report)
        assert expansion[0]["fact_id"] == "liquidity.brain.nearest_buy_side"
        assert "luna_candidate_producer" in expansion[0]["detail"]
        assert expansion[0]["remediation_owner"] == "OBJECTIVE-SCALE-PRESERVATION-1B"

    def test_M8b_a_stronger_influence_is_also_expansion(self, monkeypatch):
        mutate(monkeypatch, "dealing_range.containment",
               consumers=[{"name": "ai_brain.brain_prompt",
                           "believes": "premium/discount location",
                           "influence": OBJECTIVE_RANKING}])
        report = CV.verify(run_predicates=False)
        assert not report["ok"]
        expansion = [f for f in report["blockers"]
                     if f["kind"] == "AUTHORITY_EXPANSION"]
        assert expansion and expansion[0]["fact_id"] == "dealing_range.containment"

    def test_M9_new_debt_cannot_grandfather_itself(self, monkeypatch):
        """A post-bootstrap debt declaring itself historical."""
        intruder = dict(copy.deepcopy(BD.GRANDFATHERED_AUTHORITY_DEBT[0]),
                        fact_id="liquidity.pool_lifecycle",
                        discovered_on="2027-01-01")
        monkeypatch.setattr(
            BD, "GRANDFATHERED_AUTHORITY_DEBT",
            BD.GRANDFATHERED_AUTHORITY_DEBT + (intruder,))
        problems = BD.validate_manifest()
        assert any("cannot grandfather" in p for p in problems), problems
        assert any("may not be grandfathered" in p for p in problems), problems
        report = CV.verify(run_predicates=False)
        assert not report["ok"]
        assert "BOOTSTRAP" in kinds(report)

    def test_M9b_a_frozen_id_with_no_entry_is_caught(self, monkeypatch):
        monkeypatch.setattr(BD, "BOOTSTRAP_DEBT_UNIVERSE",
                            BD.BOOTSTRAP_DEBT_UNIVERSE | {"invented.fact"})
        assert any("neither an active debt nor a remediation tombstone" in p
                   for p in BD.validate_manifest())

    def test_M13_specimen_absence_is_not_resolution(self, monkeypatch):
        """THE CARDINAL ERROR, refused.

        A market-fact branch is CONDITIONAL. A frozen path can vanish from a
        payload because this specimen had no active protected swing, an empty
        list, or an absent timeframe family. Treating that as proof the
        authority was deleted would be the framework committing exactly the
        inference it exists to prevent.
        """
        src_root = os.path.join(ROOT, "src")
        debt = BD.by_id()["liquidity.brain.nearest_buy_side"]
        contract = FR.get("liquidity.brain.nearest_buy_side")
        state = BD.resolution_state(debt, contract, src_root=src_root,
                                    observed_paths=[])      # path NOT observed
        assert state["observed_in_fixture"] is False
        assert state["state"] == BD.ACTIVE, state
        assert state["note"] == BD.NOT_OBSERVED
        # The authority is still demonstrably there in SOURCE, which is what
        # decides -- the missing value contributed nothing.
        assert state["governance_remediation"] == "NOT_PROVEN"

    def test_M13b_the_verifier_never_reports_absence_as_removal(self, monkeypatch):
        empty = {"available": True, "path_to_fact": {}, "counts": {},
                 "unclassified": [], "uncertified_debt": 0}
        _blocking, resolutions = CV.check_bootstrap_debt(empty)
        assert resolutions, "no debt was evaluated"
        for row in resolutions:
            assert row["state"] == BD.ACTIVE, row

    def test_P13_real_remediation_makes_a_debt_eligible_for_removal(
            self, monkeypatch, tmp_path):
        """THE POSITIVE CONTROL. Remove the authority for real -- no producer
        site, no consumer read, and the contract no longer declares the
        grandfathered class -- and the debt becomes removable."""
        from rule_governance.epistemic_closure import authority_ast as AST
        # PROVEN ABSENT, not merely unfound: the inspector saw clean modules and
        # nothing dynamic that could hide the field.
        monkeypatch.setattr(
            AST, "field_authority",
            lambda paths, field: {"state": AST.ABSENT, "sites": [],
                                  "unresolved": []})
        contract = dict(copy.deepcopy(FR.get("dealing_range.containment")),
                        authority_class=CERTIFIED, consumers=[])
        state = BD.resolution_state(BD.by_id()["dealing_range.containment"],
                                    contract, src_root=str(tmp_path))
        assert state["producer_authority"] == AST.ABSENT
        assert state["consumer_authority"] == AST.ABSENT
        assert state["governance_remediation"] == "PROVEN"
        assert state["state"] == BD.ELIGIBLE_FOR_REMOVAL, state
        assert state["fact_id"] == "dealing_range.containment"
        assert state["remediation_owner"] == "ACTIVE-RANGE-CONTAINMENT-1"

    def test_P13b_unrelated_debts_are_untouched_by_one_remediation(
            self, monkeypatch, tmp_path):
        from rule_governance.epistemic_closure import authority_ast as AST
        monkeypatch.setattr(
            AST, "field_authority",
            lambda paths, field: {"state": AST.ABSENT, "sites": [],
                                  "unresolved": []})
        others = [f for f in BD.active_fact_ids()
                  if f != "dealing_range.containment"]
        assert others, "no unrelated debt to check"
        for fid in others:
            state = BD.resolution_state(BD.by_id()[fid], FR.get(fid),
                                        src_root=str(tmp_path))
            # Their contracts STILL declare the grandfathered class and their
            # consumers still claim it, so governance proof fails and they stay
            # ACTIVE. One remediation may not retire its neighbours.
            assert state["governance_remediation"] == "NOT_PROVEN", fid
            assert state["state"] == BD.ACTIVE, (fid, state)


# ══ AST AUTHORITY INSPECTION ════════════════════════════════════════════════
class TestAuthorityIsReadStructurally:
    """A comment is not a call. The first version of the v2 check searched
    source text and flagged the governance package for describing v2."""

    def test_M11_governance_prose_naming_v2_is_not_activation(self, tmp_path):
        """POSITIVE CONTROL for the AST mechanism."""
        from rule_governance.epistemic_closure import authority_ast as AST
        module = tmp_path / "describes_v2.py"
        module.write_text(
            '"""A contract noting causal_identity_version=2 exists."""\n'
            "# production must never pass causal_identity_version=2 here\n"
            "DOC = 'causal_identity_version=2'\n"
            "def build():\n"
            "    return Ledger(contract='X')\n", encoding="utf-8")
        sites = AST.keyword_call_sites(str(tmp_path), "causal_identity_version")
        assert sites == [], sites

    def test_M12_a_real_production_call_selecting_v2_is_caught(self, tmp_path):
        from rule_governance.epistemic_closure import authority_ast as AST
        module = tmp_path / "activates_v2.py"
        module.write_text(
            "def build():\n"
            "    return OccurrenceLedger('X', causal_identity_version=2)\n",
            encoding="utf-8")
        sites = AST.keyword_call_sites(str(tmp_path), "causal_identity_version")
        assert len(sites) == 1
        assert sites[0]["value"] == 2 and sites[0]["literal"]
        assert sites[0]["callee"] == "OccurrenceLedger"

    def test_explicit_v1_is_allowed_and_distinguished(self, tmp_path):
        from rule_governance.epistemic_closure import authority_ast as AST
        (tmp_path / "explicit_v1.py").write_text(
            "def build():\n"
            "    return OccurrenceLedger('X', causal_identity_version=1)\n",
            encoding="utf-8")
        sites = AST.keyword_call_sites(str(tmp_path), "causal_identity_version")
        assert sites[0]["literal"] and sites[0]["value"] == 1

    def test_a_dynamic_value_is_unknown_not_assumed_safe(self, tmp_path):
        """An unresolvable expression may not be silently treated as v1."""
        from rule_governance.epistemic_closure import authority_ast as AST
        (tmp_path / "dynamic.py").write_text(
            "def build(v):\n"
            "    return OccurrenceLedger('X', causal_identity_version=v)\n",
            encoding="utf-8")
        sites = AST.keyword_call_sites(str(tmp_path), "causal_identity_version")
        assert sites and sites[0]["literal"] is False
        assert sites[0]["value"] is None

    def test_the_live_predicate_reports_v1(self):
        result = SP.run("causal.production_is_v1")
        assert result["status"] == "PASS", result
        assert "AST-verified" in result["detail"]

    def test_describing_the_kernel_is_not_importing_it(self, tmp_path):
        from rule_governance.epistemic_closure import authority_ast as AST
        (tmp_path / "mentions.py").write_text(
            '"""session_recovery is deliberately unwired."""\n'
            "NOTE = 'session_recovery'\n", encoding="utf-8")
        assert AST.imports_module(str(tmp_path), "session_recovery") == []

    def test_a_real_import_of_the_kernel_is_caught(self, tmp_path):
        from rule_governance.epistemic_closure import authority_ast as AST
        (tmp_path / "wires.py").write_text(
            "from market_state import session_recovery\n", encoding="utf-8")
        hits = AST.imports_module(str(tmp_path), "session_recovery")
        assert len(hits) == 1 and hits[0]["file"] == "wires.py"


# ══ CURRENT-TREE FRONTIER GUARD ═════════════════════════════════════════════
class TestCurrentTreeCoverage:
    """Archives cannot contain a field somebody adds to the builder today."""

    def test_coverage_is_built_by_the_current_builder(self):
        report = CV.verify(run_predicates=False)
        assert report["coverage"]["basis"] == "current-tree build_brain_input"

    def test_the_archived_corpus_is_reported_separately(self):
        report = CV.verify(run_predicates=False)
        cov = report["coverage"]
        assert cov["archived_payloads"] > 100, cov
        assert cov["archived_unclassified"] == 0, cov

    def test_M10_a_new_builder_field_fails_the_gate(self, monkeypatch):
        """THE FRONTIER, exercised through the SAME path release verification
        uses -- not by calling classify() on a made-up string."""
        import ai_brain.brain_input as BI
        original = BI.build_brain_input

        def with_new_fact(snapshot, stance_history):
            payload = original(snapshot, stance_history)
            payload["institutional_order_flow"] = {
                "bias": "bullish", "delta": 1420, "confidence": 0.81}
            return payload

        monkeypatch.setattr(BI, "build_brain_input", with_new_fact)
        report = CV.verify(run_predicates=False)
        assert not report["ok"]
        coverage_findings = [f for f in report["blockers"]
                             if f["kind"] == "COVERAGE"]
        assert coverage_findings, kinds(report)
        assert any("institutional_order_flow" in f["detail"]
                   for f in coverage_findings)

    def test_P10_the_unmodified_builder_passes(self):
        """POSITIVE CONTROL: the frontier guard is not simply always failing."""
        report = CV.verify(run_predicates=False)
        assert report["ok"], report["blockers"]


# ══ REPORTING NEVER LAUNDERS DEBT ═══════════════════════════════════════════
class TestReportingIsHonest:

    def test_the_headline_says_debt_exists(self):
        text = CV.render(CV.verify(run_predicates=False))
        assert "PASS WITH DECLARED LEGACY DEBT" in text
        assert "EPISTEMIC CLOSURE: PASS\n" not in text

    def test_the_counts_are_separated(self):
        report = CV.verify(run_predicates=False)
        assert report["blockers"] == []
        assert len(report["grandfathered_authority_debts"]) == 3
        assert report["blocked_capabilities"] == 9
        assert report["partial_capabilities"] == 2
        assert report["certified_capabilities"] == 3

    def test_json_exposes_each_array(self):
        report = CV.verify(run_predicates=False)
        blob = json.loads(json.dumps(report, default=str))
        for key in ("blockers", "grandfathered_authority_debts",
                    "blocked_capabilities", "partial_capabilities",
                    "certified_capabilities", "debt_resolution"):
            assert key in blob, key

    def test_each_debt_names_its_remediation_owner_in_the_report(self):
        text = CV.render(CV.verify(run_predicates=False))
        assert "OBJECTIVE-SCALE-PRESERVATION-1B" in text
        assert "ACTIVE-RANGE-CONTAINMENT-1" in text


# ══ CAPABILITY OWNERSHIP IS STRUCTURAL ══════════════════════════════════════
class TestCapabilityOwnershipIsAField:
    """Not inferred from prose. An earlier version checked whether "-1"
    appeared in the gap text, which quietly passed units named without one."""

    def test_every_blocked_or_partial_capability_names_an_owner_unit(self):
        for cap in CM.CAPABILITIES:
            if cap["status"] in (BLOCKED, CM.PARTIAL):
                assert cap.get("owner_unit"), cap["capability_id"]

    def test_certified_capabilities_name_no_owner(self):
        for cap in CM.CAPABILITIES:
            if cap["status"] == CERTIFIED:
                assert not cap.get("owner_unit"), cap["capability_id"]


# ══ TRI-STATE AUTHORITY — UNKNOWN IS NOT ABSENT ═════════════════════════════
class TestAuthorityIsTriState:
    """A static inspector is not omniscient.

    A payload assembled through a helper, an alias, a computed key or a merge
    can carry a field whose name never appears as a literal. Treating "I found
    nothing" as "it is gone" would reintroduce failure-to-prove-presence as
    proof-of-absence one layer below the one we just fixed.
    """

    def test_a_named_field_is_PRESENT(self, tmp_path):
        from rule_governance.epistemic_closure import authority_ast as AST
        module = tmp_path / "reads.py"
        module.write_text("def use(payload):\n"
                          "    return payload['nearest_buy_side']\n",
                          encoding="utf-8")
        result = AST.field_authority([str(module)], "nearest_buy_side")
        assert result["state"] == AST.PRESENT
        assert result["sites"]

    def test_P14_a_clean_module_without_the_field_is_ABSENT(self, tmp_path):
        """POSITIVE CONTROL: ABSENT must still be reachable, or the tri-state is
        just UNKNOWN wearing three names and no debt could ever retire."""
        from rule_governance.epistemic_closure import authority_ast as AST
        module = tmp_path / "clean.py"
        module.write_text("def use(payload):\n"
                          "    return payload['something_else']\n",
                          encoding="utf-8")
        result = AST.field_authority([str(module)], "nearest_buy_side")
        assert result["state"] == AST.ABSENT
        assert result["unresolved"] == []

    @pytest.mark.parametrize("source,why", [
        ("def build(a, b):\n    return {**a, **b}\n", "dict merge"),
        ("def build(d, k):\n    return d[k]\n", "non-literal subscript"),
        ("def build(o, name):\n    return getattr(o, name)\n", "getattr"),
        ("def build(keys):\n    return {k: 1 for k in keys}\n", "comprehension"),
        ("def build(d, e):\n    d.update(e)\n    return d\n", "update"),
        ("def build(d, k):\n    return d.get(k)\n", "computed get"),
    ])
    def test_M14_dynamic_construction_yields_UNKNOWN(self, tmp_path, source, why):
        """UNKNOWN is not ABSENT. Each of these can author or read a key whose
        name the parser never sees."""
        from rule_governance.epistemic_closure import authority_ast as AST
        module = tmp_path / "dynamic.py"
        module.write_text(source, encoding="utf-8")
        result = AST.field_authority([str(module)], "nearest_buy_side")
        assert result["state"] == AST.UNKNOWN, (why, result)
        assert result["unresolved"], why

    def test_M14b_unknown_authority_keeps_a_debt_alive(self, monkeypatch,
                                                       tmp_path):
        """The invariant that matters: UNKNOWN never retires a debt, even when
        governance remediation IS proven."""
        from rule_governance.epistemic_closure import authority_ast as AST
        monkeypatch.setattr(
            AST, "field_authority",
            lambda paths, field: {"state": AST.UNKNOWN, "sites": [],
                                  "unresolved": [{"reason": "computed key"}]})
        contract = dict(copy.deepcopy(FR.get("dealing_range.containment")),
                        authority_class=CERTIFIED, consumers=[])
        state = BD.resolution_state(BD.by_id()["dealing_range.containment"],
                                    contract, src_root=str(tmp_path))
        assert state["producer_authority"] == AST.UNKNOWN
        assert state["consumer_authority"] == AST.UNKNOWN
        assert state["governance_remediation"] == "PROVEN"
        assert state["state"] == BD.REVIEW_REQUIRED, state
        assert state["state"] != BD.ELIGIBLE_FOR_REMOVAL
        assert state["unresolved"], "the reason must be surfaced, not swallowed"

    def test_an_unparseable_module_is_not_treated_as_clean(self, tmp_path):
        from rule_governance.epistemic_closure import authority_ast as AST
        broken = tmp_path / "broken.py"
        broken.write_text("def (:\n", encoding="utf-8")
        result = AST.field_authority([str(broken)], "anything")
        assert result["state"] == AST.UNKNOWN


# ══ REMOVAL CANNOT PROVE ITSELF ═════════════════════════════════════════════
class TestRemediationIsNotCircular:
    """"The debt entry was removed, therefore the debt was remediated" lets
    deletion certify deletion. Remediation must be proven while the record still
    exists; only then may the ACTIVE entry be retired to a tombstone."""

    def test_the_universe_is_immutable_and_pinned(self):
        assert BD.BOOTSTRAP_DEBT_UNIVERSE == frozenset({
            "liquidity.brain.nearest_buy_side",
            "liquidity.brain.nearest_sell_side",
            "dealing_range.containment",
        })

    def test_active_debt_is_a_subset_of_the_universe(self):
        assert BD.active_fact_ids() <= BD.BOOTSTRAP_DEBT_UNIVERSE

    def test_governance_proof_reads_the_live_contract_not_the_manifest(self):
        """Proof comes from the contract still declaring the grandfathered
        class -- something that exists independently of the debt entry."""
        for fid in BD.active_fact_ids():
            state = BD.resolution_state(
                BD.by_id()[fid], FR.get(fid),
                src_root=os.path.join(ROOT, "src"))
            assert state["governance_remediation"] == "NOT_PROVEN", fid
            assert state["state"] == BD.ACTIVE, (fid, state)

    def test_a_debt_may_not_simply_vanish(self, monkeypatch):
        """Deleting an active entry without a tombstone must fail: that is the
        circular route, closed."""
        remaining = tuple(d for d in BD.GRANDFATHERED_AUTHORITY_DEBT
                          if d["fact_id"] != "dealing_range.containment")
        monkeypatch.setattr(BD, "GRANDFATHERED_AUTHORITY_DEBT", remaining)
        problems = BD.validate_manifest()
        assert any("may not vanish without proof" in p for p in problems), problems

    def test_a_tombstone_permits_retirement(self, monkeypatch):
        remaining = tuple(d for d in BD.GRANDFATHERED_AUTHORITY_DEBT
                          if d["fact_id"] != "dealing_range.containment")
        monkeypatch.setattr(BD, "GRANDFATHERED_AUTHORITY_DEBT", remaining)
        monkeypatch.setattr(BD, "REMEDIATED_BOOTSTRAP_DEBTS", ({
            "fact_id": "dealing_range.containment",
            "remediated_on": "2026-09-01",
            "remediation_owner_unit": "ACTIVE-RANGE-CONTAINMENT-1",
            "remediation_target_unit": "ACTIVE-RANGE-CONTAINMENT-1",
            "proof": ("range.position_clamped", "tests/test_active_range.py"),
        },))
        assert BD.validate_manifest() == []
        assert BD.active_fact_ids() == frozenset({
            "liquidity.brain.nearest_buy_side",
            "liquidity.brain.nearest_sell_side"})
        assert "dealing_range.containment" in BD.remediated_fact_ids()

    def test_a_tombstone_confers_no_authority(self, monkeypatch):
        """A retired fact is NOT grandfathered. If it regains decision authority
        the promotion gate must treat that as NEW authority and block."""
        remaining = tuple(d for d in BD.GRANDFATHERED_AUTHORITY_DEBT
                          if d["fact_id"] != "dealing_range.containment")
        monkeypatch.setattr(BD, "GRANDFATHERED_AUTHORITY_DEBT", remaining)
        monkeypatch.setattr(BD, "REMEDIATED_BOOTSTRAP_DEBTS", ({
            "fact_id": "dealing_range.containment",
            "remediated_on": "2026-09-01",
            "remediation_owner_unit": "ACTIVE-RANGE-CONTAINMENT-1",
            "remediation_target_unit": "ACTIVE-RANGE-CONTAINMENT-1",
            "proof": ("range.position_clamped",),
        },))
        assert BD.is_grandfathered("dealing_range.containment") is False
        report = CV.verify(run_predicates=False)
        assert not report["ok"], "the retired fact still holds BLOCKED authority"
        assert "PROMOTION" in kinds(report)

    def test_a_tombstone_for_a_non_bootstrap_fact_is_rejected(self, monkeypatch):
        monkeypatch.setattr(BD, "REMEDIATED_BOOTSTRAP_DEBTS", ({
            "fact_id": "liquidity.pool_lifecycle",
            "remediated_on": "2027-01-01",
            "remediation_owner_unit": "X", "remediation_target_unit": "X",
            "proof": ("nope",),
        },))
        assert any("never bootstrap debt" in p for p in BD.validate_manifest())

    def test_a_fact_cannot_be_both_active_and_remediated(self, monkeypatch):
        monkeypatch.setattr(BD, "REMEDIATED_BOOTSTRAP_DEBTS", ({
            "fact_id": "dealing_range.containment",
            "remediated_on": "2026-09-01",
            "remediation_owner_unit": "X", "remediation_target_unit": "X",
            "proof": ("p",),
        },))
        assert any("BOTH an active debt and a remediation tombstone" in p
                   for p in BD.validate_manifest())
