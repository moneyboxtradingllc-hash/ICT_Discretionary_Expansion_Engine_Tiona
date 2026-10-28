"""LOCAL-AUTHORITY-EXISTING-POLICY-RELEASE-20261028 -- the selected release.

The compiled selection is PRODUCTION_EXISTING_POLICY_REPAIR_V1
(member_order_witness=True, retained_support=False, delivery_change=False):
the existing-family source-order repair only. Every normal-release case here
uses the ACTUAL compiled selection through the real launcher
(`run_production_scans` -> `ProductionLoop.__init__` -> its own
`ProductionScanCycle`); nothing patches the selection, cycle or producer.

Brain replies and quotes are CONTROLLED (`local_authority_loop`); every run is
disarmed with zero orders, tokens and attempts. Execution switches are set
only inside this isolated test environment.
"""
from __future__ import annotations

import copy
import json

import pytest

import local_authority_loop as H
import test_protected_structure_continuity as P
from broker import conditional_plan_authority as CPA
from broker import topstepx_production_loop as PL
from broker.luna_candidate_producer import NoCandidate
from market_data import local_authority as LA

SWITCHES = ("EXECUTION_ENABLED", "ALLOW_PAPER_ORDERS", "AUTO_EXECUTION_ENABLED",
            "TOPSTEPX_ARM_ORDERS")
REPAIR = LA.PRODUCTION_EXISTING_POLICY_REPAIR_V1


def _switches_on(m):
    for name in SWITCHES:
        m.setenv(name, "true")


def _disarmed(result):
    assert result["zero_orders"] and result["tokens"] == 0 and result["attempts"] == 0
    assert result["loop"].armed is False


# ── the exact release policy ─────────────────────────────────────────────────
def test_the_compiled_selection_is_the_existing_policy_repair_only():
    assert LA.RELEASE_SELECTION is REPAIR
    assert (REPAIR.version, REPAIR.member_order_witness, REPAIR.retained_support,
            REPAIR.delivery_change) == ("local_authority_existing_policy_repair/v1",
                                        True, False, False)
    selected = LA.release_selection()
    assert selected["profile"] is REPAIR
    assert selected["cases"] == ["member_order_witness"]
    # The all-three engineering profile stays known but unselected.
    assert LA.RELEASE_SELECTION is not LA.PRODUCTION_PROFILE_V1
    assert LA.resolve_profile(LA.PRODUCTION_PROFILE_V1) == (LA.PRODUCTION_PROFILE_V1, None)


def test_copies_of_the_repair_object_are_not_profiles(monkeypatch):
    _switches_on(monkeypatch)
    import dataclasses
    for value in (dataclasses.replace(REPAIR), REPAIR.version,
                  LA.LocalAuthorityProfile(REPAIR.version, True, False, False)):
        assert LA.resolve_profile(value) == (LA.DISABLED, "unrecognized_profile_disabled")


# ── normal launch, actual compiled selection ─────────────────────────────────
@pytest.fixture(scope="module", params=[True, False], ids=["ecu", "non_ecu"])
def release(request, tmp_path_factory):
    """Member-order scenario (Friday 15:37-15:57 UTC) through the NORMAL launcher."""
    with pytest.MonkeyPatch.context() as m:
        _switches_on(m)
        result = H.run(m, tmp_path_factory.mktemp(f"rel_m1_{request.param}"),
                       ecu=request.param, profile=None, warmup="15:36",
                       schedule=H.minutes("15:37", "15:57"), act_from="15:49",
                       direction="bullish", session="M1-RELEASE", launcher=True)
        last = result["scans"][-1]
        attempts = {}
        try:
            attempts["healthy"] = H.produce(result, last).direction
        except NoCandidate as exc:
            attempts["healthy"] = exc.reason
        try:
            H.produce(result, last, snapshot=copy.deepcopy(last["snapshot"]))
            attempts["copied_snapshot"] = "CANDIDATE"
        except NoCandidate as exc:
            attempts["copied_snapshot"] = exc.reason
        result["cycle"].local_authority.revoke("test_revocation")
        try:
            H.produce(result, last)
            attempts["revoked_issue"] = "CANDIDATE"
        except NoCandidate as exc:
            attempts["revoked_issue"] = exc.reason
        result["attempts_by_case"] = attempts
        yield result


def test_normal_launch_resolves_the_compiled_repair_with_real_bindings(release):
    cycle, loop = release["cycle"], release["loop"]
    assert cycle.local_authority.profile is REPAIR
    assert cycle._local_authority_profile is REPAIR
    assert cycle.account_provider == loop._topstep_account
    assert cycle.quote_provider is release["ps"].quote_provider
    assert cycle.session_id == "M1-RELEASE" and loop.armed is False
    startup = "\n".join(__import__("topstepx_production_session").local_authority_telemetry())
    assert ("requested local_authority_existing_policy_repair/v1, "
            "resolved local_authority_existing_policy_repair/v1") in startup
    assert "LOCAL AUTHORITY CASES        : member_order_witness" in startup


def test_obscured_same_direction_generation_reaches_the_actual_candidate(release):
    assert release["candidates"] == ["15:57"], {
        k: v.get("reason") for k, v in release["outputs"].items()}
    assert release["outputs"]["15:57"]["execution"] == PL.EXECUTION_DISARMED
    bases = [((s["brain_block"] or {}).get("narrative_continuity") or {}).get(
        "same_direction_successor_proof") or {} for s in release["scans"]]
    assert any(b.get("order_basis") == "constituent_member_order_witness" for b in bases)
    # Mechanical gates downstream of authority still refuse before 15:57.
    reasons = {o.get("reason") for hm, o in release["outputs"].items() if "15:50" <= hm < "15:57"}
    assert {"stop_distance_above_cap", "reward_below_qualification"} <= reasons
    _disarmed(release)


def test_the_actual_consumer_refuses_copied_and_revoked_witness(release):
    attempts = release["attempts_by_case"]
    assert attempts["healthy"] == "bullish"
    assert attempts["copied_snapshot"] != "CANDIDATE"
    assert attempts["revoked_issue"] != "CANDIDATE"


def test_the_normal_release_issues_no_retained_or_delivery_authority(release):
    for scan in release["scans"]:
        assert LA.local_refinements(scan["snapshot"]["active_path_state"]) == {
            "delivery_change": None, "retained_support": None}


@pytest.mark.parametrize("ecu", [True, False], ids=["ecu", "non_ecu"])
def test_the_former_composite_window_issues_no_composite_authority(tmp_path_factory, ecu):
    """Friday 16:22-16:27: the all-three engineering profile adopted a composite
    here; the selected release must not. Native routes stay available."""
    with pytest.MonkeyPatch.context() as m:
        _switches_on(m)
        result = H.run(m, tmp_path_factory.mktemp(f"rel_dc_{ecu}"), ecu=ecu, profile=None,
                       warmup="16:00", schedule=H.minutes("16:22", "16:27"),
                       act_from="16:24", direction="bearish", launcher=True)
    assert result["cycle"].local_authority.profile is REPAIR
    for scan in result["scans"]:
        assert LA.local_refinements(scan["snapshot"]["active_path_state"]) == {
            "delivery_change": None, "retained_support": None}
    assert "raid_reclaim_delivery_change" not in json.dumps(
        result["scans"][-1]["brain_input"], default=str)
    for out in result["outputs"].values():
        assert "ldc:" not in json.dumps(out, default=str)
    _disarmed(result)


# ── member-order-dependent watching plan ─────────────────────────────────────
def _plan_world(tmp_path_factory, ecu, attack=None):
    world = {}
    with pytest.MonkeyPatch.context() as m:
        _switches_on(m)
        result = H.run(m, tmp_path_factory.mktemp(f"rel_plan_{ecu}_{attack is not None}"),
                       ecu=ecu, profile=None, warmup="15:36",
                       schedule=H.minutes("15:37", "15:50"), act_from="15:49",
                       direction="bullish", session="M1-PLAN", watch="nearest", launcher=True)
        loop = result["loop"]
        plan = loop.active_conditional_plan
        world.update(result=result, plan=plan, outputs=result["outputs"])
        if plan is None:
            return world
        world["binding"] = plan["authority"].payload().get("local_authority_binding")
        zone = plan["candidate"].extras["activation_zone"]
        bid = round(((zone["low"] + zone["high"]) / 2) * 4) / 4
        built, original = {}, loop.ps.build_runner

        def build_runner(candidate, **kwargs):
            built["candidate"] = candidate
            return original(candidate, **kwargs)

        m.setattr(loop.ps, "build_runner", build_runner)
        if attack:
            attack(m, result)
        # The next settled minute: a later market state changes the transfer
        # evidence and the existing guard then (correctly) asks for review.
        world["trigger"] = result["tick"]("15:51", False, bid=bid)
        world["built"] = built
        if built:
            def final_quote():
                return CPA.validate_final_quote(
                    authority=plan["authority"], scope=loop.producer._conditional_plan_scope,
                    candidate=built["candidate"], contract_id=P.C, executable_price=bid,
                    now=result["clock"][0])
            world["final_healthy"] = final_quote()
            result["cycle"].local_authority.revoke("lost_between_trigger_and_final_quote")
            world["final_revoked"] = final_quote()
    return world


@pytest.mark.parametrize("ecu", [True, False], ids=["ecu", "non_ecu"])
def test_member_order_plan_binds_and_survives_trigger_and_final_quote(tmp_path_factory, ecu):
    world = _plan_world(tmp_path_factory, ecu)
    assert world["plan"] is not None, {k: v.get("reason") for k, v in world["outputs"].items()}
    binding = world["binding"]
    assert binding["member_order_fact"].startswith("mof:")
    assert binding["routes"] == {}
    assert {binding["contract_id"], binding["process_session_id"]} == {P.C, "M1-PLAN"}
    assert world["trigger"]["outcome"] == PL.QUALIFIED_CANDIDATE_OBSERVED
    assert world["final_healthy"] == (True, None)
    assert world["final_revoked"] == (False, "conditional_plan_local_authority_changed")
    _disarmed(world["result"])


def _foreign_witness(m, result):
    m.setattr(LA, "authenticated_member_order", lambda *a, **k: None)


def test_member_order_plan_refuses_a_withdrawn_current_witness(tmp_path_factory):
    world = _plan_world(tmp_path_factory, True, attack=_foreign_witness)
    assert world["plan"] is not None
    assert world["trigger"]["outcome"] == PL.NO_CANDIDATE and not world["built"]
    _disarmed(world["result"])
