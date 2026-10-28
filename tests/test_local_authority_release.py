"""LOCAL-AUTHORITY-RELEASE-20261027 -- the dormant release connection.

The compiled release selection (`local_authority.RELEASE_SELECTION`) stays OFF
in this source. These tests prove, through the REAL launcher
(`run_production_scans`) -> `ProductionLoop.__init__` -> its own
`ProductionScanCycle`, that:

* the frozen normal launch builds the default cycle with DISABLED;
* a CONTROLLED selection fixture (monkeypatching the compiled literal; it is not
  the frozen launch) reaches the same constructor with the production profile,
  the launcher's real account/capital/quote bindings, and -- beside truthy
  execution switches, still disarmed -- the actual candidate, plan, brainless
  trigger and final-quote boundaries;
* invalid, offline, copied or conflicting selections refuse loudly, before any
  venue or model, and never run as legacy DISABLED;
* 5m regression controls and the constructed 15m chronology reach the actual
  CandidateProducer in both ECU modes, with matched negatives.

Brain replies and quotes are CONTROLLED (`local_authority_loop`); every run is
disarmed and reports zero orders, tokens and attempts. Nothing here is natural
model evidence, a historical quote or entry intent.
"""
from __future__ import annotations

import ast
import dataclasses
import json
import os
import shutil
import subprocess
import sys

import pytest

import local_authority_loop as H
import test_production_scan_loop as G
import test_protected_structure_continuity as P
from broker import conditional_plan_authority as CPA
from broker import topstepx_production_loop as PL
from broker import topstepx_session_authorization as SA
from broker.luna_candidate_producer import NoCandidate
from live_scan.production_scan_cycle import ProductionScanCycle
from market_data import local_authority as LA

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import topstepx_production_session as TOOL  # noqa: E402

SWITCHES = ("EXECUTION_ENABLED", "ALLOW_PAPER_ORDERS", "AUTO_EXECUTION_ENABLED",
            "TOPSTEPX_ARM_ORDERS")
DC_FAMILY = "raid_reclaim_delivery_change"
#: The constructed 15m chronology: Friday's tape, every 1m bar from 15:00 UTC
#: stretched into three lawful 1m bars (5m bucket -> 15m bucket), moved -2h.
STRETCH = {"anchor": "15:00", "shift_hours": -2}


def _switches_on(m):
    for name in SWITCHES:
        m.setenv(name, "true")


def _select(m, profile):
    """CONTROLLED selection fixture; the delivered literal stays None."""
    m.setattr(LA, "RELEASE_SELECTION", profile)


def _disarmed(result):
    assert result["zero_orders"] and result["tokens"] == 0 and result["attempts"] == 0
    assert result["loop"].armed is False


def _copy(profile):
    return dataclasses.replace(profile)


# ── the profile contract ──────────────────────────────────────────────────────
def test_delivered_release_selection_is_the_existing_policy_repair_literal(monkeypatch):
    tree = ast.parse(open(os.path.join(ROOT, "src/market_data/local_authority.py")).read())
    values = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(getattr(t, "id", None) == "RELEASE_SELECTION" for t in node.targets)]
    assert len(values) == 1 and isinstance(values[0], ast.Name)
    assert values[0].id == "PRODUCTION_EXISTING_POLICY_REPAIR_V1"
    assert LA.RELEASE_SELECTION is LA.PRODUCTION_EXISTING_POLICY_REPAIR_V1
    _select(monkeypatch, None)                  # CONTROLLED OFF fixture
    off = LA.release_selection()
    assert off["profile"] is None and off["resolved"] == "disabled" and off["cases"] == []
    assert off["source"] == "src/market_data/local_authority.py:RELEASE_SELECTION"


def test_production_profile_is_exact_and_runs_beside_execution_switches(monkeypatch):
    _switches_on(monkeypatch)
    assert LA.resolve_profile(LA.PRODUCTION_PROFILE_V1) == (LA.PRODUCTION_PROFILE_V1, None)
    assert LA.profile_cases(LA.PRODUCTION_PROFILE_V1) == [
        "member_order_witness", "retained_support", "delivery_change"]
    _select(monkeypatch, LA.PRODUCTION_PROFILE_V1)
    sel = LA.release_selection()
    assert sel["profile"] is LA.PRODUCTION_PROFILE_V1
    assert (sel["requested"], sel["resolved"]) == ("local_authority_production/v1",) * 2


@pytest.mark.parametrize("profile", [LA.OFFLINE_TEST_PROFILE_V1,
                                     LA.OFFLINE_RETAINED_SUPPORT_TEST_PROFILE_V1,
                                     LA.OFFLINE_MEMBER_ORDER_TEST_PROFILE_V1])
def test_offline_profiles_still_refuse_beside_execution_switches(monkeypatch, profile):
    assert LA.resolve_profile(profile) == (profile, None)
    for name in SWITCHES:
        with monkeypatch.context() as m:
            m.setenv(name, "true")
            assert LA.resolve_profile(profile) == (
                LA.DISABLED, "offline_profile_refused_execution_environment")


@pytest.mark.parametrize("value", [
    "local_authority_production/v1", {"version": "local_authority_production/v1"},
    _copy(LA.PRODUCTION_PROFILE_V1), _copy(LA.OFFLINE_TEST_PROFILE_V1),
    LA.LocalAuthorityProfile("local_authority_production/v1", True, True, True), True, 1,
], ids=["string", "dict", "production_copy", "offline_copy", "lookalike", "true", "one"])
def test_unknown_copies_and_lookalikes_never_become_profiles(monkeypatch, value):
    _switches_on(monkeypatch)
    assert LA.resolve_profile(value) == (LA.DISABLED, "unrecognized_profile_disabled")
    _select(monkeypatch, value)
    with pytest.raises(LA.ProfileSelectionRefused, match="unknown_release_selection"):
        LA.release_selection()


def test_offline_objects_are_not_releasable_even_when_disarmed(monkeypatch):
    for profile in (LA.OFFLINE_TEST_PROFILE_V1, LA.OFFLINE_MEMBER_ORDER_TEST_PROFILE_V1):
        _select(monkeypatch, profile)
        with pytest.raises(LA.ProfileSelectionRefused, match="offline_profile_not_releasable"):
            LA.release_selection()


def test_a_reviewed_selection_change_rotates_the_brain_contract_fingerprint(tmp_path):
    """On disposable copies (never the shared checkout): flipping the literal and
    nothing else changes the fingerprint every session authorization binds."""
    def fingerprint(root):
        code = ("import sys; sys.path.insert(0, 'src'); "
                "from ai_brain.production_model import brain_contract_fingerprint as f; "
                "print(f())")
        return subprocess.run([sys.executable, "-c", code], cwd=root, check=True,
                              capture_output=True, text=True,
                              env={"PATH": os.environ.get("PATH", ""),
                                   "PYTHONDONTWRITEBYTECODE": "1"}).stdout.strip()
    copies = {}
    for name in ("off", "on"):
        dest = tmp_path / name
        shutil.copytree(os.path.join(ROOT, "src"), dest / "src",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(os.path.join(ROOT, "tools"), dest / "tools",
                        ignore=shutil.ignore_patterns("__pycache__"))
        copies[name] = dest
    target = copies["on"] / "src/market_data/local_authority.py"
    text = target.read_text()
    selected = "\nRELEASE_SELECTION = PRODUCTION_EXISTING_POLICY_REPAIR_V1\n"
    assert text.count(selected) == 1
    # The delivered source selects the repair; flipping it either way rotates.
    target.write_text(text.replace(selected, "\nRELEASE_SELECTION = PRODUCTION_PROFILE_V1\n"))
    other = copies["off"] / "src/market_data/local_authority.py"
    other.write_text(other.read_text().replace(selected, "\nRELEASE_SELECTION = None\n"))
    off, on = fingerprint(copies["off"]), fingerprint(copies["on"])
    from ai_brain.production_model import brain_contract_fingerprint
    current = brain_contract_fingerprint()
    assert len({off, on, current}) == 3 and off and on


# ── the ProductionLoop constructor seam ───────────────────────────────────────
def _loop_parts(root):
    venue = G.Session()
    runtime = G.Runtime(venue.market_hub)
    from broker.topstepx_production_session import ProductionSession
    from broker.topstepx_quote_provider import LiveQuoteProvider
    import test_reversal_foundation_proof_closure as RF
    quotes = LiveQuoteProvider(venue.market_hub, RF.MNQ)
    ps = ProductionSession(session=venue, account_fingerprint=G.FP, contract=RF.MNQ,
                           mission_id="LA", store_dir=str(root), runtime=runtime,
                           quote_provider=quotes)
    auth = G.authorization(root, session_id="LA-SEAM", contract_id=P.C)
    mission = SA.ProductionSessionMission(authorization=auth, store_dir=str(root))
    from broker.luna_candidate_producer import CandidateProducer
    return dict(production_session=ps, session_mission=mission,
                producer=CandidateProducer(account_fingerprint=G.FP, contract=RF.MNQ),
                candles=H.Candles([]), runtime=runtime, account_id=77, armed=False)


def test_loop_forwards_the_profile_to_its_own_cycle_with_the_real_bindings(
        tmp_path, monkeypatch):
    _switches_on(monkeypatch)
    parts = _loop_parts(tmp_path)
    loop = PL.ProductionLoop(**parts, local_authority_profile=LA.PRODUCTION_PROFILE_V1)
    cycle = loop.cycle
    assert type(cycle) is ProductionScanCycle
    assert cycle.local_authority.profile is LA.PRODUCTION_PROFILE_V1
    assert cycle.account_provider == loop._topstep_account
    assert cycle.quote_provider is parts["production_session"].quote_provider
    assert (cycle.session_id, cycle.contract_id) == ("LA-SEAM", P.C)
    legacy = PL.ProductionLoop(**_loop_parts(tmp_path / "legacy"))
    assert legacy.cycle.local_authority.profile is LA.DISABLED


@pytest.mark.parametrize("requested", [
    LA.OFFLINE_TEST_PROFILE_V1, _copy(LA.PRODUCTION_PROFILE_V1), "local_authority_production/v1",
], ids=["offline_beside_switches", "production_copy", "string"])
def test_a_refused_requested_profile_fails_construction(tmp_path, monkeypatch, requested):
    _switches_on(monkeypatch)
    with pytest.raises(LA.ProfileSelectionRefused):
        PL.ProductionLoop(**_loop_parts(tmp_path), local_authority_profile=requested)


def test_a_requested_profile_never_silently_loses_to_a_supplied_cycle(tmp_path):
    other = ProductionScanCycle(symbol="MNQ", contract_id=P.C, session_id="LA-SEAM")
    with pytest.raises(LA.ProfileSelectionRefused,
                       match="profile_conflicts_with_supplied_scan_cycle"):
        PL.ProductionLoop(**_loop_parts(tmp_path), scan_cycle=other,
                          local_authority_profile=LA.PRODUCTION_PROFILE_V1)
    same = ProductionScanCycle(symbol="MNQ", contract_id=P.C, session_id="LA-SEAM",
                               local_authority_profile=LA.PRODUCTION_PROFILE_V1)
    loop = PL.ProductionLoop(**_loop_parts(tmp_path / "same"), scan_cycle=same,
                             local_authority_profile=LA.PRODUCTION_PROFILE_V1)
    assert loop.cycle is same
    # Existing calls (no explicit selection) are unchanged.
    assert PL.ProductionLoop(**_loop_parts(tmp_path / "plain"), scan_cycle=other).cycle is other


# ── the real launcher ─────────────────────────────────────────────────────────
def _launch(m, root):
    venue = G.Session()
    runtime = G.Runtime(venue.market_hub)
    from broker.topstepx_production_session import ProductionSession
    from broker.topstepx_quote_provider import LiveQuoteProvider
    import test_reversal_foundation_proof_closure as RF
    quotes = LiveQuoteProvider(venue.market_hub, RF.MNQ)
    ps = ProductionSession(session=venue, account_fingerprint=G.FP, contract=RF.MNQ,
                           mission_id="LA", store_dir=str(root), runtime=runtime,
                           quote_provider=quotes)
    loop, startup = H.launch(m, root, ps=ps, runtime=runtime, candles=H.Candles([]),
                             venue=venue, session="LA-LAUNCH")
    return loop, startup, ps


def test_controlled_off_launch_builds_the_real_default_cycle_disabled(tmp_path, monkeypatch):
    _select(monkeypatch, None)                  # CONTROLLED OFF fixture
    loop, _startup, ps = _launch(monkeypatch, tmp_path)
    assert type(loop.cycle) is ProductionScanCycle
    assert loop.cycle.local_authority.profile is LA.DISABLED
    assert loop.cycle.local_authority.profile_reason == "default_disabled"
    assert loop.cycle._local_authority_profile is None
    assert loop.cycle.account_provider == loop._topstep_account
    assert loop.cycle.quote_provider is ps.quote_provider
    assert loop.cycle.session_id == "LA-LAUNCH" and loop.armed is False
    lines = TOOL.local_authority_telemetry()
    assert lines[0].endswith("OFF (legacy DISABLED; no local cases)")


def test_controlled_selection_reaches_the_launch_built_cycle(tmp_path, monkeypatch):
    _switches_on(monkeypatch)
    _select(monkeypatch, LA.PRODUCTION_PROFILE_V1)
    loop, _startup, ps = _launch(monkeypatch, tmp_path)
    assert loop.cycle.local_authority.profile is LA.PRODUCTION_PROFILE_V1
    assert loop.cycle.account_provider == loop._topstep_account
    assert loop.cycle.quote_provider is ps.quote_provider and loop.armed is False
    text = "\n".join(TOOL.local_authority_telemetry())
    assert "requested local_authority_production/v1, resolved local_authority_production/v1" in text
    assert "member_order_witness, retained_support, delivery_change" in text
    assert "local_authority.py:RELEASE_SELECTION" in text


def test_startup_banner_prints_the_resolved_selection_without_identifiers(monkeypatch):
    out = TOOL.execution_path_telemetry(armed=False, mission_id="X", symbol="MNQ")
    assert "resolved local_authority_existing_policy_repair/v1" in out
    assert "LOCAL AUTHORITY CASES        : member_order_witness" in out
    _select(monkeypatch, None)                  # CONTROLLED OFF fixture
    out = TOOL.execution_path_telemetry(armed=False, mission_id="X", symbol="MNQ")
    assert "LOCAL AUTHORITY SELECTION    : OFF (legacy DISABLED; no local cases)" in out
    _select(monkeypatch, LA.PRODUCTION_PROFILE_V1)
    out = TOOL.execution_path_telemetry(armed=False, mission_id="X", symbol="MNQ")
    assert "resolved local_authority_production/v1" in out
    assert "TOPSTEPX_ACCOUNT" not in out


@pytest.mark.parametrize("value", [LA.OFFLINE_TEST_PROFILE_V1, _copy(LA.PRODUCTION_PROFILE_V1),
                                   "local_authority_production/v1"],
                         ids=["offline", "copy", "string"])
def test_invalid_selection_refuses_main_before_any_venue_or_model(monkeypatch, capsys, value):
    from broker import topstepx_live_session

    class NoVenue:
        def __init__(self, *a, **k):
            raise AssertionError("an invalid selection reached the venue")

    monkeypatch.setattr(topstepx_live_session, "TopstepXLiveSession", NoVenue)
    _select(monkeypatch, value)
    assert TOOL.main(["--scans", "1"]) == 2
    out = capsys.readouterr().out
    assert "PRODUCTION SESSION REFUSED" in out and "LOCAL AUTHORITY RELEASE SELECTION" in out
    assert "REFUSED" in "\n".join(TOOL.local_authority_telemetry())


def test_invalid_selection_refuses_the_launcher_before_authorization(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(TOOL, "load_or_refuse_authorization",
                        lambda **k: called.append(k))
    _select(monkeypatch, _copy(LA.PRODUCTION_PROFILE_V1))
    with pytest.raises(LA.ProfileSelectionRefused):
        _launch(monkeypatch, tmp_path)
    assert called == []


def test_armed_launch_still_requires_the_existing_durable_authorization(tmp_path, monkeypatch):
    _select(monkeypatch, LA.PRODUCTION_PROFILE_V1)
    built = []
    monkeypatch.setattr(PL, "ProductionLoop", lambda **k: built.append(k))
    monkeypatch.setattr(TOOL, "STORE_DIR", str(tmp_path))
    monkeypatch.setenv("TOPSTEPX_ACCOUNT_FINGERPRINT", G.FP)
    import test_reversal_foundation_proof_closure as RF
    with pytest.raises(SA.AuthorizationRefused, match="NO_SESSION_AUTHORIZATION"):
        TOOL.run_production_scans(ps=None, runtime=None, candles=None, session=None,
                                  contract=RF.MNQ, armed=True, symbol="MNQ",
                                  mission_id="LA-ARMED", scans=0, interval=0)
    assert built == []


# ── the launch-built loop through the actual consumers (5m regression control) ─
@pytest.fixture(scope="module", params=[True, False], ids=["ecu", "non_ecu"])
def launched_5m(request, tmp_path_factory):
    out = {}
    for name, profile in (("off", None), ("selected", LA.PRODUCTION_PROFILE_V1)):
        with pytest.MonkeyPatch.context() as m:
            _switches_on(m)
            _select(m, profile)
            result = H.run(m, tmp_path_factory.mktemp(f"rel5_{name}_{request.param}"),
                           ecu=request.param, profile=None, warmup="16:00",
                           schedule=H.minutes("16:22", "16:27"), act_from="16:24",
                           direction="bearish", launcher=True)
            if name == "selected":
                last = result["scans"][-1]
                attempts = {"healthy": H.produce(result, last).direction}
                copied = json.loads(json.dumps(last["snapshot"], default=str))
                try:
                    H.produce(result, last, snapshot=copied)
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
            out[name] = result
    yield out


def test_frozen_off_launch_reaches_no_local_candidate(launched_5m):
    off = launched_5m["off"]
    assert off["cycle"].local_authority.profile is LA.DISABLED
    assert off["candidates"] == []
    _disarmed(off)


def test_selected_launch_reaches_the_actual_candidate_beside_execution_switches(launched_5m):
    selected = launched_5m["selected"]
    assert selected["cycle"].local_authority.profile is LA.PRODUCTION_PROFILE_V1
    # The same minutes the accepted offline profile reached (Mission 3 control).
    assert selected["candidates"] == ["16:25", "16:26", "16:27"]
    assert selected["outputs"]["16:24"]["reason"] == "campaign_lifecycle_refused"
    payload = json.dumps(selected["scans"][-1]["brain_input"], default=str)
    assert DC_FAMILY in payload
    _disarmed(selected)


def test_launch_built_consumer_refuses_copied_and_revoked_authority(launched_5m):
    attempts = launched_5m["selected"]["attempts_by_case"]
    assert attempts["healthy"] == "bearish"
    assert attempts["copied_snapshot"] != "CANDIDATE"
    assert attempts["revoked_issue"] != "CANDIDATE"


@pytest.mark.parametrize("ecu", [True, False], ids=["ecu", "non_ecu"])
def test_launch_built_plan_survives_trigger_and_final_quote(tmp_path_factory, ecu):
    with pytest.MonkeyPatch.context() as m:
        _switches_on(m)
        _select(m, LA.PRODUCTION_PROFILE_V1)
        result = H.run(m, tmp_path_factory.mktemp(f"rel_plan_{ecu}"), ecu=ecu, profile=None,
                       warmup="16:00", schedule=H.minutes("16:22", "16:25"), act_from="16:24",
                       direction="bearish", watch=True, launcher=True)
        loop = result["loop"]
        assert result["outputs"]["16:25"]["outcome"] == "CONDITIONAL_PLAN_PUBLISHED"
        plan = loop.active_conditional_plan
        binding = plan["authority"].payload()["local_authority_binding"]
        assert binding["routes"]["delivery_change"].startswith("ldc:")
        assert binding["process_session_id"] == "LA-OFFLINE"
        zone = plan["candidate"].extras["activation_zone"]
        bid = round(((zone["low"] + zone["high"]) / 2) * 4) / 4
        built, original = {}, loop.ps.build_runner

        def build_runner(candidate, **kwargs):
            built["candidate"] = candidate
            return original(candidate, **kwargs)

        m.setattr(loop.ps, "build_runner", build_runner)
        trigger = result["tick"]("16:26", False, bid=bid)
        assert trigger["outcome"] == PL.QUALIFIED_CANDIDATE_OBSERVED

        def final_quote():
            return CPA.validate_final_quote(
                authority=plan["authority"], scope=loop.producer._conditional_plan_scope,
                candidate=built["candidate"], contract_id=P.C, executable_price=bid,
                now=result["clock"][0])
        assert final_quote() == (True, None)
        result["cycle"].local_authority.revoke("lost_between_trigger_and_final_quote")
        assert final_quote() == (False, "conditional_plan_local_authority_changed")
        _disarmed(result)


# ── full 15m coverage on the constructed chronology ───────────────────────────
def _stretched(direction):
    tape = H.stretched_tape(P.TAPE, **STRETCH)
    return tape if direction == "bearish" else H.mirrored_tape(tape)


def _run_15m(tmp_path_factory, *, tape, ecu, direction, tag, profile=LA.PRODUCTION_PROFILE_V1,
             schedule=("17:10", "17:18"), act_from="17:12"):
    with pytest.MonkeyPatch.context() as m:
        _switches_on(m)
        _select(m, profile)
        return H.run(m, tmp_path_factory.mktemp(f"rel15_{tag}_{ecu}"), ecu=ecu, profile=None,
                     warmup="16:00", schedule=H.minutes(*schedule), act_from=act_from,
                     direction=direction, tape=tape, launcher=True)


def _packets(result):
    """Every composite the launch-built cycle published, keyed by cutoff."""
    out = {}
    for scan in result["scans"]:
        path = scan["snapshot"]["active_path_state"]
        route = LA.local_refinements(path).get("delivery_change")
        if route:
            out[scan["snapshot"]["timestamp"][11:16]] = route
    return out


@pytest.fixture(scope="module", params=[True, False], ids=["ecu", "non_ecu"])
def bearish_15m(request, tmp_path_factory):
    result = _run_15m(tmp_path_factory, tape=_stretched("bearish"), ecu=request.param,
                      direction="bearish", tag="bear")
    last = result["scans"][-1]                       # 17:18, a candidate minute
    copied = json.loads(json.dumps(last["snapshot"], default=str))
    attempts = {"healthy": H.produce(result, last).direction}
    try:
        H.produce(result, last, snapshot=copied)
        attempts["copied_snapshot"] = "CANDIDATE"
    except NoCandidate as exc:
        attempts["copied_snapshot"] = exc.reason
    result["attempts_by_case"] = attempts
    yield result


def test_15m_bearish_composite_is_produced_on_15m_and_first_available_when_complete(
        bearish_15m):
    generation = bearish_15m["cycle"].local_authority._generation
    assert generation["life"]["source_tf"] == "15m"
    assert generation["body_confirmation"]["timeframe"] == "15m"
    assert generation["structure"]["source_tf"] == "15m"
    assert generation["completed_at"] == P._cut("17:15")
    # Conjunction-completion chronology: the failure settles before completion.
    assert LA.failure_available_at(generation["failure"]) < LA._dt(P._cut("17:15"))
    packets = _packets(bearish_15m)
    # Forming: the 17:00 bucket is incomplete through 17:13, so nothing exists yet.
    assert min(packets) == "17:14"
    assert {"17:10", "17:11", "17:12", "17:13"}.isdisjoint(packets)


def test_15m_bearish_reaches_the_actual_candidate(bearish_15m):
    assert bearish_15m["cycle"].local_authority.profile is LA.PRODUCTION_PROFILE_V1
    assert bearish_15m["candidates"] == ["17:16", "17:17", "17:18"]
    payload = json.dumps(bearish_15m["scans"][-1]["brain_input"], default=str)
    assert DC_FAMILY in payload
    attempts = bearish_15m["attempts_by_case"]
    assert attempts["healthy"] == "bearish" and attempts["copied_snapshot"] != "CANDIDATE"
    _disarmed(bearish_15m)


def _drop_minute(tape, hm):
    return [b for b in tape if b["timestamp"] != P._cut(hm)]


def _new_extreme(tape, hm, price, side):
    out = H.copy.deepcopy(tape)
    bar = next(b for b in out if b["timestamp"] == P._cut(hm))
    bar[side] = price
    return out


@pytest.mark.parametrize("ecu", [True, False], ids=["ecu", "non_ecu"])
def test_15m_matched_negatives_refuse_the_composite(tmp_path_factory, bearish_15m, ecu):
    healthy = bearish_15m["cycle"].local_authority._generation
    run = healthy["body_confirmation"]["run"]
    inside = run["first_open_time"][11:16]
    extreme = healthy["body_confirmation"]["run"]["extreme"]
    cases = {
        # A missing settled 1m bar inside the opposite-delivery run.
        "gapped_run": _drop_minute(_stretched("bearish"), inside),
        # A new invalidating extreme inside the confirming bucket (owner challenge).
        "confirming_bar_new_extreme": _new_extreme(_stretched("bearish"), "17:05",
                                                   extreme + 5.0, "high"),
    }
    for tag, tape in cases.items():
        result = _run_15m(tmp_path_factory, tape=tape, ecu=ecu, direction="bearish", tag=tag)
        reused = [r for r in _packets(result).values()
                  if r == healthy["market_proof_id"]
                  or (isinstance(r, dict) and r.get("market_proof_id") == healthy["market_proof_id"])]
        assert reused == [], tag
        generation = result["cycle"].local_authority._generation
        assert not generation or generation["market_proof_id"] != healthy["market_proof_id"], tag
        _disarmed(result)


@pytest.mark.parametrize("ecu", [True, False], ids=["ecu", "non_ecu"])
def test_15m_default_off_launch_reaches_no_composite(tmp_path_factory, ecu):
    result = _run_15m(tmp_path_factory, tape=_stretched("bearish"), ecu=ecu,
                      direction="bearish", tag="off", profile=None)
    assert _packets(result) == {} and result["candidates"] == []
    _disarmed(result)
