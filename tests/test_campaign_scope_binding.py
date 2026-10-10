"""M3 current-snapshot consumers. Unit replays are distinct from real scans.

The M2 fixed W5 fixture supplies actual detector facts for custody replays.
Synthetic legacy unit fixtures can publish authentic UNBOUND ownership via
the real custody publisher, but never create a selected campaign or a detector
proof. Missing/copy/stale-publication tests deliberately do not use that helper.
"""
import copy
from collections import deque
from types import SimpleNamespace

import pytest

from ai_brain.narrative_continuity import (
    build_narrative_continuity, recheck_narrative_continuity,
    candidate_direction_authorized, output_direction_hold, campaign_premise_unbound)
from market_data import campaign_scope as CS, campaign_premise as CP
from broker.conditional_plan_authority import _current_scope_binding
from test_campaign_scope import natural, owner, _publish, _qualify, _proposal


_FIXTURE_OWNERS = deque(maxlen=512)


def authenticate_unbound_fixture(snapshot, *, session_id="UNIT-UNBOUND"):
    """Explicit synthetic fixture ownership, not a natural detector witness.

    Publish a fresh empty AVAILABLE inventory through the actual owner API.
    No premise life/proposal is invented and no ACTIVE scope can be minted.
    Call only at declared authoring boundaries, never to repair a negative copy.
    """
    revision = (snapshot.get("derived_state") or {}).get("history_revision", 0)
    for previous in _FIXTURE_OWNERS:
        if previous._fixture_snapshot is snapshot:
            previous.campaign_scope_custody.reset("fixture_next_scan")
    custody = CS.CampaignScopeCustody()
    fixture = SimpleNamespace(contract_id=snapshot.get("contract_id"), session_id=session_id,
                              _history=SimpleNamespace(revision=revision),
                              campaign_scope_custody=custody,
                              derived_state_is_current=lambda: True)
    # SimpleNamespace is not weak-referenceable; the real publisher requires
    # an actual owner object with process lifetime.
    class Owner:
        pass
    owner = Owner();owner.__dict__.update(fixture.__dict__)
    owner._fixture_snapshot = snapshot
    stamp = CP._instant(snapshot.get("timestamp"))
    session = CP._session_of(snapshot.get("timestamp"))
    snapshot["campaign_premise_shadow"] = {
        "status": CP.AVAILABLE, "cutoff": stamp, "history_revision": revision,
        "contract_id": owner.contract_id, "market_session": session, "lives": []}
    custody.advance(owner=owner, snapshot=snapshot, settled_1m=[], ledger_rows=[],
                    history_revision=revision, contract_id=owner.contract_id,
                    market_session=session)
    _FIXTURE_OWNERS.append(owner)
    if (snapshot.get("derived_state") or {}).get("current") is True:
        assert CS.read_current_campaign_scope(snapshot)["state"] == "UNBOUND"
    return owner


def _active(owner, natural):
    proposed = _publish(owner, natural, "14:36")
    assert _qualify(owner, proposed)["status"] == "PENDING"
    return _publish(owner, natural, "14:37")


def test_authentic_unbound_keeps_legacy_table(owner, natural):
    snap = _publish(owner, natural, "14:36")
    local = copy.deepcopy(snap)
    for key in ("derived_state", "campaign_scope_custody", "campaign_scope_custody_shadow",
                "campaign_premise_catalog", "campaign_premise_shadow"):
        local.pop(key, None)
    expected = build_narrative_continuity(local, {"available": False})
    actual = build_narrative_continuity(snap, {"available": False})
    assert actual["campaign_premise"] == campaign_premise_unbound()
    assert {k:v for k,v in actual.items() if k != "campaign_scope"} == expected
    assert _current_scope_binding(snap) is None


def test_activation_and_continuing_default_consumers(owner, natural):
    snap = _active(owner, natural)
    current = build_narrative_continuity(snap, {"available": False})
    assert current["control_state"] == "campaign_established"
    assert current["dominant_direction"] == "bearish"
    assert current["campaign_premise"]["status"] == "INTACT"
    ident = _current_scope_binding(snap)
    newer = _publish(owner, natural, "14:38")
    rechecked = recheck_narrative_continuity(newer, current)
    assert rechecked["control_state"] == "incumbent_intact"
    assert rechecked["transfer_confirmed"] is False
    assert rechecked["transfer_proof"] is None
    assert _current_scope_binding(newer) == ident
    assert candidate_direction_authorized("bearish", newer, current)[0]
    assert not candidate_direction_authorized("bullish", newer, current)[0]


def test_authentic_unbound_hold_explanation_matches_legacy(owner, natural):
    args = copy.deepcopy(natural["14:36"])
    snap = args["snapshot"]
    snap["active_path_state"]["transfer_evidence"].pop("load_bearing_failure")
    args.update(owner=owner, history_revision=0, contract_id=owner.contract_id,
                market_session=CP._session_of(snap["timestamp"]))
    owner.campaign_scope_custody.advance(**args)
    assert CS.read_current_campaign_scope(snap)["state"] == "UNBOUND"
    local = copy.deepcopy(snap)
    for key in ("derived_state", "campaign_scope_custody", "campaign_scope_custody_shadow",
                "campaign_premise_catalog", "campaign_premise_shadow"):
        local.pop(key, None)
    actual = build_narrative_continuity(snap, {"available": False})
    legacy = build_narrative_continuity(local, {"available": False})
    assert actual["control_state"] == "unresolved"
    output = {"narrative_direction": "bullish", "current_action": "propose_entry"}
    held, guard = output_direction_hold(output, actual)
    assert (held, guard) == output_direction_hold(output, legacy)
    assert "unbound (UNKNOWN)" in held["dominant_reasoning"]
    copied = recheck_narrative_continuity(copy.deepcopy(snap), actual)
    technical, _ = output_direction_hold(output, copied)
    assert "current scope is unavailable" in technical["dominant_reasoning"]


@pytest.mark.parametrize("defect", ["copy", "json_fields", "missing", "altered", "stale", "reset", "foreign"])
def test_current_ownership_cannot_be_replaced_by_labels(owner, natural, defect):
    snap = _active(owner, natural)
    authored = build_narrative_continuity(snap, {"available": False})
    if defect == "copy":
        snap = copy.deepcopy(snap)
    elif defect == "json_fields":
        snap = {k:copy.deepcopy(v) for k,v in snap.items()}
    elif defect == "missing":
        snap.pop("campaign_scope_custody")
    elif defect == "altered":
        snap["campaign_scope_custody"]["campaign"]["direction"] = "bullish"
    elif defect == "stale":
        _publish(owner, natural, "14:38")
    elif defect == "reset":
        owner.campaign_scope_custody.reset()
    else:
        owner.campaign_scope_custody = CS.CampaignScopeCustody()
    result = recheck_narrative_continuity(snap, authored)
    assert result["campaign_premise"]["status"] == "UNKNOWN"
    assert result["dominant_direction"] is None
    for direction in ("bullish", "bearish"):
        assert not candidate_direction_authorized(direction, snap, authored)[0]
        held, guard = output_direction_hold({"narrative_direction":direction,
                                             "current_action":"propose_entry"}, result)
        assert held["current_action"] == "stand_down" and guard
        assert "current scope is unavailable" in held["dominant_reasoning"]
    with pytest.raises(ValueError, match="campaign_scope_changed"):
        _current_scope_binding(snap)
    forged_current = {"control_state":"incumbent_intact","dominant_direction":"bullish"}
    assert not candidate_direction_authorized("bullish", snap, authored,
                                              current_continuity=forged_current)[0]


@pytest.mark.parametrize("defect,expected", [
    ("opposite", "developing_transfer"), ("contested", "developing_transfer"),
    ("failed", "developing_transfer"), ("challenged", "developing_transfer"),
    ("unknown_flags", "unresolved"), ("missing_path", "unresolved")])
def test_bound_campaign_does_not_remove_local_refusals(owner, natural, defect, expected):
    authored = build_narrative_continuity(_active(owner,natural), {"available":False})
    # Explicit unit replay: alter local evidence BEFORE its owner publication,
    # keeping real M1 own-timeframe measurement inputs unchanged.
    args = copy.deepcopy(natural["14:38"]);snap=args["snapshot"]
    path=snap["active_path_state"]
    if defect == "opposite": path["owner"]="bullish"
    elif defect == "contested": path["status"]="contested"
    elif defect == "failed": path["status"]="invalidated"
    elif defect == "challenged": path["transfer_evidence"]["opposing_structure_break"]=True
    elif defect == "unknown_flags": path["transfer_evidence"].pop("load_bearing_failure")
    else: path["state_available"]=False
    args.update(owner=owner,history_revision=0,contract_id=owner.contract_id,
                market_session=CP._session_of(snap["timestamp"]))
    owner.campaign_scope_custody.advance(**args)
    actual=recheck_narrative_continuity(snap,authored)
    assert actual["control_state"]==expected
    assert actual["dominant_direction"]=="bearish"
    assert actual["campaign_premise"]["status"]=="INTACT"
    assert not actual["transfer_confirmed"]
    for direction in ("bullish","bearish"):
        assert not candidate_direction_authorized(direction,snap,authored)[0]


def test_production_missing_owner_is_not_unbound_fallback():
    import test_narrative_authority_1 as local
    snap={"timestamp":local.NOW,"contract_id":local.CONTRACT.id,
          "derived_state":{"current":True},"active_path_state":local.path_state("bullish")}
    result=build_narrative_continuity(snap,{"available":False})
    assert result["control_state"]=="unresolved"
    assert result["campaign_premise"]["reason"]=="campaign_scope_unavailable"
    assert not candidate_direction_authorized("bullish",snap,result)[0]


def test_continuing_scope_does_not_require_visible_activation_transfer(owner,natural):
    authored=build_narrative_continuity(_active(owner,natural),{"available":False})
    args=copy.deepcopy(natural["14:38"]);snap=args["snapshot"]
    snap["active_path_state"]["last_invalidated"]=None
    args.update(owner=owner,history_revision=0,contract_id=owner.contract_id,
                market_session=CP._session_of(snap["timestamp"]))
    owner.campaign_scope_custody.advance(**args)
    current=recheck_narrative_continuity(snap,authored)
    assert current["control_state"]=="incumbent_intact"
    assert current["campaign_premise"]["binding"]["campaign_id"]==authored["campaign_premise"]["binding"]["campaign_id"]
    assert current["transfer_proof"] is None
    assert candidate_direction_authorized("bearish",snap,authored)[0]


def test_unknown_retirement_then_available_unbound_is_exact_d0a(owner,natural):
    authored=build_narrative_continuity(_active(owner,natural),{"available":False})
    args=copy.deepcopy(natural["14:38"]);snap=args["snapshot"]
    snap["campaign_premise_shadow"]["status"]="UNAVAILABLE"
    args.update(owner=owner,history_revision=0,contract_id=owner.contract_id,
                market_session=CP._session_of(snap["timestamp"]))
    owner.campaign_scope_custody.advance(**args)
    assert recheck_narrative_continuity(snap,authored)["dominant_direction"] is None
    next_snap=_publish(owner,natural,"14:39")
    scope=CS.read_current_campaign_scope(next_snap)
    assert scope["state"]=="UNBOUND" and scope["last_transition"]["reason"]=="premise_observation_unknown"
    assert recheck_narrative_continuity(next_snap,authored)["campaign_premise"]==campaign_premise_unbound()
    assert _current_scope_binding(next_snap) is None


@pytest.mark.parametrize("defect",["suspended","certificate_unknown","proof_identity","proposal_identity"])
def test_table_inconsistent_or_suspended_scope_never_permits(owner,natural,monkeypatch,defect):
    # Explicit pure table defense: the accessor is mocked to exercise states
    # that the real D6=a publisher never emits, not a producer-authentic claim.
    snap=_active(owner,natural);scope=CS.read_current_campaign_scope(snap)
    if defect=="suspended":scope["state"]="SUSPENDED"
    elif defect=="certificate_unknown":scope["campaign"]["certificate"]["status"]="UNKNOWN"
    elif defect=="proof_identity":scope["last_transition"]["scope_proof_id"]="other-proof"
    else:scope["last_transition"]["proposal_id"]="other-proposal"
    monkeypatch.setattr(CS,"read_current_campaign_scope",lambda _snapshot:copy.deepcopy(scope))
    current=build_narrative_continuity(snap,{"available":False})
    assert current["campaign_premise"]["status"]=="UNKNOWN"
    assert current["dominant_direction"] is None
    assert not candidate_direction_authorized("bearish",snap,current)[0]


def _w5_reply(output, ordinal, payload, *, entry, action="propose_entry", expires=None):
    """MOCKED primary judgment selects actual current catalog identities."""
    stops=[r for r in payload.get("authorized_invalidations", [])
           if isinstance(r.get("price"),(int,float)) and r["price"]>entry]
    targets=[r for r in payload.get("authorized_objectives", [])
             if isinstance(r.get("price"),(int,float)) and r["price"]<entry]
    assert stops and targets
    stop=min(stops,key=lambda r:r["price"])
    target=min(targets,key=lambda r:r["price"])
    output.update(narrative_direction="bearish",allowed_direction="bearish",
                  forbidden_direction="bullish",narrative_phase="continuation",
                  current_action="stand_down" if ordinal==1 else action,
                  objective_id=target["objective_id"],invalidation_id=stop["invalidation_id"],
                  invalidation_level=stop["price"],active_draw="sell side liquidity below",
                  recommended_playbook_family="continuation",recommended_tool_family=["fvg"],
                  market_story="Bearish delivery after the rejected buy side raid; select current catalog geometry.",
                  dominant_reasoning=("After the buy side liquidity raid and reclaimed rejection, "
                    "market structure shifted bearish and displacement delivered lower. The intact "
                    "protected high supports the selected lower objective and continuation while "
                    "delivery remains incomplete."))
    if ordinal==1:
        output.update(objective_id=None,invalidation_id=None,invalidation_level=None,
                      active_draw="none",recommended_playbook_family="none",
                      recommended_tool_family=["none"])
        row=next(r for r in payload["campaign_premise_catalog"]["rows"]
                 if r["supports"]=="bearish" and r["d3"]["route_b"])
        output["campaign_scope_proposal"]={"kind":"establish","direction":"bearish",
            "premise_candidate_id":row["premise_candidate_id"],"scope_reason":"MOCKED fixed W5 selection"}
    else:
        tools=[r for r in payload["authorized_tool_catalog"] if r.get("tool_family")=="fvg"
               and r.get("direction")=="bearish" and r.get("execution_eligible") is True]
        if action=="watching":
            tools=[r for r in tools if r["zone_high"]<stop["price"]]
        assert tools
        selected=min(tools,key=lambda r:abs((r["zone_low"]+r["zone_high"])/2-entry))
        output["recommended_tool_occurrence_id"]=selected["occurrence_id"]
        if expires is not None:output["plan_expires_at"]=expires.isoformat()
    return output


def _w5_producer(tmp_path, monkeypatch, ecu, *, action="propose_entry"):
    from datetime import datetime,timezone,timedelta
    import test_reversal_foundation_proof_closure as RF
    from test_campaign_scope import _tape,CONTRACT
    from live_scan.production_scan_cycle import ProductionScanCycle
    from broker.topstepx_slippage import QuoteCapture
    for name,leaf in (("OCCURRENCE_LEDGER_DIR","occ"),("AI_BRAIN_DIR","brain"),
                      ("AI_RETRIEVAL_DIR","retr"),("REPLAY_SESSIONS_DIR","replay")):
        monkeypatch.setenv(name,str(tmp_path/leaf))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BRAIN_ECU_MODE","false")
    monkeypatch.setenv("AI_BRAIN_ENABLED","false")
    monkeypatch.setenv("AI_BRAIN_LLM","false")
    tape=_tape();px=[tape[0]["close"]]
    def quote():
        return QuoteCapture(captured_at=datetime.now(timezone.utc),best_bid=px[0],
                            best_ask=px[0]+.25,last_trade=px[0],contract_id=CONTRACT,
                            market_data_age_seconds=.25)
    cycle=ProductionScanCycle(symbol="MNQ",contract_id=CONTRACT,
                              session_id="W5-M3",quote_provider=quote)
    def scan(end, *, brain=True):
        bars=tape[:end];px[0]=bars[-1]["close"]
        if scan.quote_override is not None:px[0]=scan.quote_override
        return cycle.scan(bars,now=datetime.fromisoformat(bars[-1]["timestamp"])
                          +timedelta(minutes=1),invoke_brain=brain)
    scan.quote_override=None
    scan.tape=tape
    for end in range(20,97):scan(end,brain=False)
    calls=[]
    RF._mock_current_brain(monkeypatch,calls,output_mutator=lambda out,n,payload:
        _w5_reply(out,n,payload,entry=px[0],action=action,
                  expires=datetime.fromisoformat(tape[98]["timestamp"])+timedelta(minutes=5)))
    monkeypatch.setenv("BRAIN_ECU_MODE","true" if ecu else "false")
    return cycle,scan,calls


def _candidate(scan, cycle, *, producer=None, conditional_plan=False, now=None, **kwargs):
    from datetime import datetime,timezone
    import test_reversal_foundation_proof_closure as RF
    from broker.luna_candidate_producer import CandidateProducer
    from market_data.campaign_draw_truth import scan_participation_authority
    producer=producer or CandidateProducer(account_fingerprint="acct:scope",contract=RF.MNQ)
    return producer.produce(brain_result=scan["brain_result"],brain_input=scan["brain_input"],
        snapshot=scan["snapshot"],qualification=scan["qualification"],
        engine_inventory={"liquidity":"PRESENT_AND_POPULATED"},snapshot_id=scan["snapshot_id"],
        market_data_timestamp=scan["snapshot"]["timestamp"],
        latest_closed_bar_timestamp=scan["snapshot"]["timestamp"],
        now=now or datetime.now(timezone.utc),require_campaign_lifecycle=True,
        campaign_draw=scan_participation_authority(scan),campaign_session_id=cycle.session_id,
        conditional_plan=conditional_plan,**kwargs)


@pytest.mark.parametrize("ecu", [False,True], ids=["non-ecu","ecu"])
def test_real_t2_pending_t3_newborn_refusal_t4_candidate(tmp_path,monkeypatch,ecu):
    from broker.luna_candidate_producer import NoCandidate
    cycle,scan,calls=_w5_producer(tmp_path,monkeypatch,ecu)
    t2=scan(97)
    assert t2["snapshot"]["campaign_scope_proposal_outcome"]["status"]=="PENDING"
    assert CS.read_current_campaign_scope(t2["snapshot"])["state"]=="UNBOUND"
    assert t2["campaign_draw_acceptance"]["accepted"] is False
    t3=scan(98)
    campaign=CS.read_current_campaign_scope(t3["snapshot"])["campaign"]
    assert campaign["status"]=="ACTIVE" and campaign["certificate"]["status"]=="INTACT"
    assert t3["campaign_lifecycle"]["participation_permitted"] is False
    assert t3["campaign_draw_truth"]["anchor_bar_time"]==t3["snapshot"]["timestamp"]
    with pytest.raises(NoCandidate,match="campaign_lifecycle_refused"):_candidate(t3,cycle)
    t4=scan(99)
    candidate=_candidate(t4,cycle)
    assert candidate.direction=="bearish"
    assert t4["campaign_lifecycle"]["state"]=="ACTIVE_DELIVERY"
    assert CS.read_current_campaign_scope(t4["snapshot"])["campaign"]["campaign_id"]==campaign["campaign_id"]
    assert t4["campaign_draw_authority"]["record_id"]==t3["campaign_draw_truth"]["record_id"]
    assert len(calls)==3
    for reply in (t2,t3,t4):
        assert reply["brain_block"]["source"]=="llm"
        assert reply["brain_block"]["repair_attempted"] is False
    brainless=scan(100,brain=False)
    assert len(calls)==3
    assert _current_scope_binding(brainless["snapshot"])["campaign_id"]==campaign["campaign_id"]
    # A detached copy carrying the very same fields cannot reach a candidate.
    copied={**t4,"snapshot":copy.deepcopy(t4["snapshot"])}
    with pytest.raises(NoCandidate):_candidate(copied,cycle)


def _session_authorization(candidate,cycle,now):
    from broker import topstepx_session_authorization as SA
    from ai_brain import production_model as PM
    from ai_retrieval.retrieval import retrieval_enabled
    date=now.strftime("%Y%m%d")
    auth=SA.SessionAuthorization(session_id=cycle.session_id,
        account_fingerprint=candidate.account_fingerprint,contract_id=candidate.contract_id,
        session_date=date,decision_window=SA.window_text(date),brain_model=PM.PRODUCTION_MODEL,
        brain_reasoning_effort=PM.reasoning_effort() or "",json_mode_required=True,
        brain_contract_fingerprint=PM.brain_contract_fingerprint(),retrieval_enabled=retrieval_enabled(),
        daily_loss_budget_usd=SA.DAILY_LOSS_BUDGET_USD,issued_at=now.isoformat())
    auth.authorization_fingerprint=auth.fingerprint()
    return auth


@pytest.mark.parametrize("ecu",[False,True],ids=["non-ecu","ecu"])
def test_real_bound_plan_survives_fresh_cutoff_and_refuses_lost_custody(tmp_path,monkeypatch,ecu):
    from datetime import datetime,timedelta
    import test_reversal_foundation_proof_closure as RF
    from broker.luna_candidate_producer import CandidateProducer
    from broker.conditional_plan_authority import validate_final_quote
    cycle,scan,calls=_w5_producer(tmp_path,monkeypatch,ecu,action="watching")
    scan(97);scan(98)
    # Declared lawful next-candle variation: a quieter high and close preserve
    # the chosen gap while allowing the real tighter local pivot to register.
    # Author only AFTER that local replacement's Draw is measured again.
    scan.tape[99].update(high=29517.75,close=29517.0)
    scan.tape[100].update(open=29517.0,high=29517.5,close=29516.5)
    scan(99);scan(100)
    authored=scan(101)
    assert authored["campaign_lifecycle"]["participation_permitted"], (
        authored["brain_block"].get("source"),
        (authored["brain_block"].get("output") or {}).get("warnings"),
        authored["campaign_lifecycle"]["reason"])
    producer=CandidateProducer(account_fingerprint="acct:scope",contract=RF.MNQ)
    now=datetime.fromisoformat(authored["snapshot"]["timestamp"])+timedelta(minutes=1)
    plan=_candidate(authored,cycle,producer=producer,conditional_plan=True,now=now)
    authorization=_session_authorization(plan,cycle,now)
    authority=producer.capture_conditional_plan_authority(candidate=plan,scan=authored,
        authorization=authorization,process_session_id=cycle.session_id,now=now)
    duplicate=producer.capture_conditional_plan_authority(candidate=plan,scan=authored,
        authorization=authorization,process_session_id=cycle.session_id,now=now)
    assert authority.payload()==duplicate.payload() and authority is not duplicate
    bound=authority.payload()["campaign_scope_binding"]
    current_campaign=CS.read_current_campaign_scope(authored["snapshot"])["campaign"]
    assert bound=={"campaign_id":current_campaign["campaign_id"],
                   "scope_proof_id":current_campaign["scope_proof"]["proof_id"]}
    assert bound==_current_scope_binding(authored["snapshot"])
    zone=authority.payload()["activation_zone"]
    scan.quote_override=int(4*(zone["low"]+zone["high"])/2)/4
    assert scan.tape[101]["low"]<=scan.quote_override<=scan.tape[101]["high"]
    trigger=scan(102,brain=False)
    assert len(calls)==5
    assert trigger["snapshot"]["timestamp"]!=authored["snapshot"]["timestamp"]
    assert _current_scope_binding(trigger["snapshot"])==bound
    from broker.conditional_plan_authority import _public_path
    old_path=authority.payload()["active_path"]
    new_path=_public_path(trigger["snapshot"])
    assert old_path==new_path, {k:(old_path.get(k),new_path.get(k))
                               for k in old_path if old_path.get(k)!=new_path.get(k)}
    sealed=authority.payload()["brain_result"]
    fresh=_candidate({**trigger,"brain_result":sealed},cycle,producer=producer,
        now=now+timedelta(minutes=1),conditional_trigger=True,
        conditional_plan_authority=authority,conditional_plan_candidate=plan,
        conditional_session_authorization=authorization,process_session_id=cycle.session_id,
        conditional_plan_trigger_event={"plan_id":plan.candidate_id,
            "occurrence_id":plan.extras["selected_tool_occurrence_id"],
            "reason":"conditional_plan_zone_reached"})
    assert fresh.extras["conditional_plan_authority"]["campaign_scope_binding"]==bound
    fresh.extras["conditional_plan_id"]=plan.candidate_id
    args=dict(authority=authority,scope=producer._conditional_plan_scope,candidate=fresh,
              contract_id=fresh.contract_id,executable_price=scan.quote_override,
              now=now+timedelta(minutes=1))
    assert validate_final_quote(**args)==(True,None)
    assert validate_final_quote(**{**args,"authority":duplicate})==(False,"campaign_scope_changed")
    # Ownership disappearing AFTER a successful trigger is refused again at
    # final quote; copied VERIFIED evidence cannot restore it.
    cycle.campaign_scope_custody.reset("test_restart")
    assert validate_final_quote(**args)==(False,"campaign_scope_changed")
    # A fresh authentic UNBOUND publication after restart is still a changed
    # binding, not a route to recover this previously bound plan.
    from data_feed.timeframe_builder import build_timeframes
    cycle._advance_campaign_scope(trigger["snapshot"],build_timeframes(scan.tape[:102]))
    assert _current_scope_binding(trigger["snapshot"]) is None
    assert validate_final_quote(**args)==(False,"campaign_scope_changed")


@pytest.mark.parametrize("ecu",[False,True],ids=["non-ecu","ecu"])
def test_real_post_transition_successor_and_unscoped_opposition(tmp_path,monkeypatch,ecu):
    cycle,scan,calls=_w5_producer(tmp_path,monkeypatch,ecu)
    scan(97);scan(98);t4=scan(99)
    authored=t4["brain_block"]["narrative_continuity"]
    incumbent=CS.read_current_campaign_scope(t4["snapshot"])["campaign"]
    challenges=0
    for end in range(100,160):
        current=scan(end,brain=False)
        custody=CS.read_current_campaign_scope(current["snapshot"])
        assert custody["campaign"]["campaign_id"]==incumbent["campaign_id"]
        assert custody["campaign"]["certificate"]["status"]=="INTACT"
        continuity=recheck_narrative_continuity(current["snapshot"],authored)
        if continuity["control_state"] in ("developing_transfer","unresolved"):
            challenges+=1
            for direction in ("bullish","bearish"):
                assert not candidate_direction_authorized(direction,current["snapshot"],authored)[0]
    assert challenges>0
    snap=current["snapshot"]
    assert snap["timestamp"][11:16]=="15:38"
    assert snap["active_path_state"]["owner"]=="bullish"
    held=recheck_narrative_continuity(snap,authored)
    assert held["control_state"]=="developing_transfer" and held["dominant_direction"]=="bearish"
    assert held["campaign_premise"]["status"]=="INTACT" and not held["transfer_confirmed"]
    # MOCKED primary proposal at the qualification seam, using real current
    # catalog/proof. This is not another model turn or injected detector output.
    assert _qualify(cycle,snap,_proposal(snap,"bullish","transfer"))["status"]=="PENDING"
    scan.tape[159]["close"]=29519.5
    scan.tape[159]["low"]=min(scan.tape[159]["low"],29519.25)
    activated=scan(160,brain=False)
    scope=CS.read_current_campaign_scope(activated["snapshot"])
    successor=scope["campaign"]
    assert successor["campaign_id"]!=incumbent["campaign_id"]
    actual=recheck_narrative_continuity(activated["snapshot"],authored)
    assert actual["control_state"]=="confirmed_transfer"
    assert actual["dominant_direction"]==actual["confirmed_to"]=="bullish"
    assert actual["confirmed_from"]=="bearish"
    assert actual["transfer_proof"]==successor["scope_proof"]["local_transfer_proof"]
    assert actual["campaign_premise"]["binding"]["campaign_id"]==successor["campaign_id"]
    assert scope["last_transition"]["predecessor_campaign_id"]==incumbent["campaign_id"]
    assert candidate_direction_authorized("bullish",activated["snapshot"],authored)[0]
    assert not candidate_direction_authorized("bearish",activated["snapshot"],authored)[0]
    assert len(calls)==3
