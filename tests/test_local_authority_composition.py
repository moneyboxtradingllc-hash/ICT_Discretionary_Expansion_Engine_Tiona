"""LOCAL-AUTHORITY-20261026 Mission 3 -- the whole composition, through the real loop.

Actual current facts -> actual Brain input -> CONTROLLED valid response ->
current authority -> Draw/Lifecycle -> exact tool -> CandidateProducer ->
disarmed ProductionLoop, in both ECU modes; then a CONTROLLED `watching` plan
captured with the local route's stable identity, revalidated by the real
brainless trigger, and reauthenticated at the final-quote consumer.

The Brain replies and quotes are CONTROLLED (see `local_authority_loop`): they
prove wiring and admission only. The archived Friday Brain replies were all
stand-down and are not represented here as intent. Execution is disarmed;
every run reports zero orders, tokens and attempts.
"""
from __future__ import annotations

import json
import uuid

import pytest

import local_authority_loop as H
import test_protected_structure_continuity as P
from broker import conditional_plan_authority as CPA
from broker import topstepx_production_loop as PL
from broker.luna_candidate_producer import NoCandidate
from market_data import local_authority as LA

DC_FAMILY = "raid_reclaim_delivery_change"


def _records(root):
    return [json.loads(line) for f in sorted(root.rglob("candidate_decisions.jsonl"))
            for line in f.read_text().splitlines() if line.strip()]


def _scan_at(result, hm):
    rows = [s for s in result["scans"] if s["snapshot"]["timestamp"] == P._cut(hm)]
    return rows[-1]


def _disarmed(result):
    assert result["zero_orders"] and result["tokens"] == 0 and result["attempts"] == 0


@pytest.fixture(scope="module", params=[True, False], ids=["ecu", "non_ecu"])
def entry(request, tmp_path_factory):
    ecu, out = request.param, {"ecu": request.param}
    for name, profile in (("default", None), ("offline", LA.OFFLINE_TEST_PROFILE_V1)):
        root = tmp_path_factory.mktemp(f"m3_entry_{name}_{ecu}")
        with pytest.MonkeyPatch.context() as m:
            result = H.run(m, root, ecu=ecu, profile=profile, warmup="16:00",
                           schedule=H.minutes("16:22", "16:27"), act_from="16:24",
                           direction="bearish")
            out[name], out[f"{name}_root"] = result, root
            if name == "offline":
                last = result["scans"][-1]
                attempts = {"healthy": H.produce(result, last).direction}
                copied = json.loads(json.dumps(last["snapshot"], default=str))
                for label, snap in (("copied_snapshot", copied),):
                    try:
                        H.produce(result, last, snapshot=snap)
                        attempts[label] = "CANDIDATE"
                    except NoCandidate as exc:
                        attempts[label] = exc.reason
                result["cycle"].local_authority.revoke("test_revocation")
                try:
                    H.produce(result, last)
                    attempts["revoked_issue"] = "CANDIDATE"
                except NoCandidate as exc:
                    attempts["revoked_issue"] = exc.reason
                out["attempts"] = attempts
    yield out


def test_default_loop_never_reaches_a_candidate(entry):
    default = entry["default"]
    assert default["candidates"] == []
    assert {o["outcome"] for o in default["outputs"].values()} == {PL.NO_CANDIDATE}
    _disarmed(default)


def test_offline_loop_reaches_the_disarmed_candidate_boundary(entry):
    offline = entry["offline"]
    assert offline["candidates"] == ["16:25", "16:26", "16:27"]
    # The newborn Draw (named by the first entry intent at 16:24) refuses first.
    assert offline["outputs"]["16:24"]["reason"] == "campaign_lifecycle_refused"
    _disarmed(offline)


def test_actual_brain_input_carries_the_composite_before_judgment(entry):
    scan = _scan_at(entry["offline"], "16:25")
    payload = json.dumps(scan["brain_input"], default=str)
    assert DC_FAMILY in payload and "DELIVERY_CHANGE_CONFIRMED" in payload
    assert '"bias"' not in payload              # no hidden opinion in physical evidence
    default = json.dumps(_scan_at(entry["default"], "16:25")["brain_input"], default=str)
    assert DC_FAMILY not in default


def test_actual_candidate_consumer_refuses_copied_and_revoked_authority(entry):
    attempts = entry["attempts"]
    assert attempts["healthy"] == "bearish"
    assert attempts["copied_snapshot"] != "CANDIDATE"
    assert attempts["revoked_issue"] != "CANDIDATE"


def test_v2_records_name_the_route_proof_source_and_first_refusal(entry):
    offline, default = _records(entry["offline_root"]), _records(entry["default_root"])
    assert default and all("local_authority_route" not in r for r in default)
    routed = [r for r in offline if "local_authority_route" in r]
    assert routed
    for record in routed:
        block = record["local_authority_route"]
        assert block["schema"] == "local_authority_route.v1"
        assert [x["route"] for x in block["routes"]] == ["delivery_change"]
        assert block["routes"][0]["proof_id"].startswith("ldc:")
        assert block["current_source"]["status"] == "CURRENT_PRODUCER_ISSUE"
        assert block["current_source"]["contract_id"] == P.C
    refused = [r for r in routed if r.get("final_rejection_reason")]
    assert refused and refused[0]["local_authority_route"]["first_refusal"]["code"] == \
        "campaign_lifecycle_refused"
    created = [r for r in routed if r.get("final_disposition") == "CANDIDATE_CREATED"]
    assert created and all(r["local_authority_route"]["first_refusal"] is None for r in created)


# ── retained support and the constructed mirror ──────────────────────────────
@pytest.fixture(scope="module", params=[True, False], ids=["ecu", "non_ecu"])
def retained(request, tmp_path_factory):
    out = {}
    for name, profile in (("default", None),
                          ("offline", LA.OFFLINE_RETAINED_SUPPORT_TEST_PROFILE_V1)):
        with pytest.MonkeyPatch.context() as m:
            out[name] = H.run(m, tmp_path_factory.mktemp(f"m3_rs_{name}_{request.param}"),
                              ecu=request.param, profile=profile, warmup="17:05",
                              schedule=H.minutes("17:10", "17:17"), act_from="17:10",
                              direction="bearish")
    yield out


def test_retained_support_adds_an_authenticated_support_but_no_admission_delta(retained):
    default, offline = retained["default"], retained["offline"]
    # The accepted native route already admits this 13:15 ET bearish leg: the
    # loop outcomes are IDENTICAL minute by minute (candidate at 13:15 ET, the
    # unchanged protected risk rule refusing the distant stop). The
    # local proof changes what is published, not who participates. Recorded,
    # never tuned.
    assert {hm: (o["outcome"], o.get("reason")) for hm, o in offline["outputs"].items()} == \
        {hm: (o["outcome"], o.get("reason")) for hm, o in default["outputs"].items()}
    assert offline["candidates"] == default["candidates"] == ["17:15"]
    assert offline["outputs"]["17:16"]["reason"] == "stop_distance_above_cap"
    plain = _scan_at(default, "17:16")["snapshot"]["active_path_state"]
    assert LA.local_refinements(plain) == {"delivery_change": None, "retained_support": None}
    _disarmed(default)
    _disarmed(offline)


def test_constructed_mirror_reaches_the_bullish_candidate_boundary(tmp_path_factory):
    with pytest.MonkeyPatch.context() as m:
        result = H.run(m, tmp_path_factory.mktemp("m3_mirror"), ecu=True,
                       profile=LA.OFFLINE_TEST_PROFILE_V1, warmup="16:00",
                       schedule=H.minutes("16:22", "16:26"), act_from="16:24",
                       direction="bullish", tape=H.mirrored_tape(P.TAPE))
    assert result["candidates"] == ["16:25", "16:26"]
    _disarmed(result)


# ── conditional plan: capture, brainless trigger, final quote ────────────────
def _plan_world(tmp_path_factory, *, ecu=True, before_trigger=None, tag="plan"):
    world = {}
    with pytest.MonkeyPatch.context() as m:
        result = H.run(m, tmp_path_factory.mktemp(f"m3_{tag}_{ecu}"), ecu=ecu,
                       profile=LA.OFFLINE_TEST_PROFILE_V1, warmup="16:00",
                       schedule=H.minutes("16:22", "16:25"), act_from="16:24",
                       direction="bearish", watch=True)
        loop = result["loop"]
        world["published"] = result["outputs"]["16:25"]
        plan = loop.active_conditional_plan
        assert plan is not None, world["published"]
        world["binding"] = plan["authority"].payload().get("local_authority_binding")
        zone = plan["candidate"].extras["activation_zone"]
        bid = round(((zone["low"] + zone["high"]) / 2) * 4) / 4
        built = {}
        original = loop.ps.build_runner

        def build_runner(candidate, **kwargs):     # the runner's own inputs
            built["candidate"], built["kwargs"] = candidate, kwargs
            return original(candidate, **kwargs)

        m.setattr(loop.ps, "build_runner", build_runner)
        if before_trigger:
            before_trigger(m, result)
        world["trigger"] = result["tick"]("16:26", False, bid=bid)
        world.update(result=result, built=built, bid=bid, plan=plan)

        def final_quote():
            return CPA.validate_final_quote(
                authority=plan["authority"], scope=loop.producer._conditional_plan_scope,
                candidate=built["candidate"], contract_id=P.C, executable_price=bid,
                now=result["clock"][0])
        world["final_quote"] = final_quote
        if built:
            world["final_healthy"] = final_quote()
            result["cycle"].local_authority.revoke("lost_between_trigger_and_final_quote")
            world["final_revoked"] = final_quote()
    return world


@pytest.mark.parametrize("ecu", [True, False], ids=["ecu", "non_ecu"])
def test_plan_binds_the_route_and_survives_the_brainless_trigger_and_final_quote(
        tmp_path_factory, ecu):
    world = _plan_world(tmp_path_factory, ecu=ecu)
    assert world["published"]["outcome"] == "CONDITIONAL_PLAN_PUBLISHED"
    binding = world["binding"]
    assert binding["routes"]["delivery_change"].startswith("ldc:")
    assert {binding["contract_id"], binding["market_session"],
            binding["process_session_id"]} == {P.C, "20261023", "LA-OFFLINE"}
    assert binding["custody_lineage"]
    assert world["trigger"]["outcome"] == PL.QUALIFIED_CANDIDATE_OBSERVED
    evidence = world["built"]["candidate"].extras["conditional_plan_authority"]
    assert evidence["local_authority_binding"] == binding
    assert world["final_healthy"] == (True, None)
    # The UNBOUND scope binding (None) is unchanged; only the local proof moved.
    assert world["final_revoked"] == (False, "conditional_plan_local_authority_changed")
    _disarmed(world["result"])


def _new_custody_lineage(m, result):
    m.setattr(result["cycle"].campaign_scope_custody, "_lineage", uuid.uuid4().hex)


def _withdraw_current_proof(m, result):
    m.setattr(LA, "delivery_change_packet", lambda **_kw: (None, "forced_test_withdrawal"))


@pytest.mark.parametrize("attack,expected", [
    (_new_custody_lineage, "conditional_plan_local_authority_changed"),
    (_withdraw_current_proof, None),
], ids=["same_facts_other_issuer_lineage", "current_proof_withdrawn"])
def test_changed_or_withdrawn_local_authority_refuses_the_brainless_trigger(
        tmp_path_factory, attack, expected):
    world = _plan_world(tmp_path_factory, before_trigger=attack, tag=attack.__name__)
    trigger = world["trigger"]
    assert trigger["outcome"] == PL.NO_CANDIDATE and not world["built"]
    detail = json.dumps(trigger, default=str)
    if expected:
        assert expected in detail
    _disarmed(world["result"])
