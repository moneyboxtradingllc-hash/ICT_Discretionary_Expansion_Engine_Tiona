"""M2 shadow custody: real lawful producer witness plus adversarial unit paths.

The fixed W5 seed is the previously audited synthetic witness, never a seed
search. Detector outputs are not injected. Unit custody cases reuse detached
facts from that real producer; Brain selections/transport are explicitly mocked.
"""
import copy
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from market_data import campaign_scope as CS
from market_data import campaign_premise as CP
from ai_brain.production_model import PRODUCTION_MODEL
from live_scan.production_scan_cycle import ProductionScanCycle
from data_feed.timeframe_builder import build_timeframes


CONTRACT = "CON.F.US.MNQ.Z26"


@pytest.mark.parametrize("custody", [None, object()])
def test_uninitialized_shadow_owner_publishes_unavailable_without_escaping(custody):
    # Existing integration fixtures can construct a cycle with __new__.
    # A missing shadow owner must preserve the main scan's failure isolation.
    cycle = ProductionScanCycle.__new__(ProductionScanCycle)
    if custody is not None:
        cycle.campaign_scope_custody = custody
    snapshot = {"timestamp": "2026-08-19T14:37:00+00:00",
                "campaign_premise_catalog": {"stale": True}}
    result = cycle._advance_campaign_scope(snapshot, {})
    assert result["status"] == "UNAVAILABLE"
    assert result["authority"] == "none"
    assert result["reason"] == "scope_error:AttributeError"
    assert snapshot["campaign_scope_custody_shadow"] == result
    assert "campaign_premise_catalog" not in snapshot
    assert CS.read_current_campaign_scope(snapshot)["status"] == "UNAVAILABLE"


def _tape():
    rng = random.Random(300)
    start = datetime(2026, 8, 19, 13, tzinfo=timezone.utc)
    q = lambda x: round(round(x / .25) * .25, 2)
    px = 29500.0 + rng.uniform(-20, 20)
    bars = []
    pivot, vol = rng.randint(70, 110), rng.uniform(1.2, 3.0)
    for i in range(200):
        if i < pivot:
            drift = (-rng.uniform(.2, .9) if (i // rng.randint(6, 12)) % 3
                     else rng.uniform(.1, .8))
        elif i < pivot + rng.randint(8, 20):
            drift = rng.uniform(.8, 2.2)
        elif i < pivot + rng.randint(25, 40):
            drift = -rng.uniform(.3, 1.2)
        else:
            drift = (rng.uniform(.1, 1.0) if (i // rng.randint(5, 10)) % 3
                     else -rng.uniform(.1, .7))
        o = px; c = q(o + drift + rng.gauss(0, vol))
        hi = q(max(o, c) + abs(rng.gauss(0, vol * .6)))
        lo = q(min(o, c) - abs(rng.gauss(0, vol * .6)))
        if i > pivot + 30 and i % 5 == 4 and rng.random() < .35 and len(bars) >= 15:
            lo = q(min(lo, min(b["low"] for b in bars[-15:]) - rng.uniform(.5, 3.0)))
            c = q(max(o, c) + rng.uniform(.25, 1.5)); hi = q(max(hi, c))
        bars.append({"timestamp": (start + timedelta(minutes=i)).isoformat(),
                     "open": q(o), "high": hi, "low": lo, "close": c,
                     "volume": rng.randint(5, 60), "contract": CONTRACT})
        px = c
    assert hashlib.sha256(json.dumps(bars, sort_keys=True).encode()).hexdigest() == \
        "8fe54c5d1bb9e392ad4b92b44ad8c69f373d47db290d0d07a49f6e53b4a20d7b"
    return bars


@pytest.fixture(scope="module")
def natural(tmp_path_factory):
    root = tmp_path_factory.mktemp("scope_witness")
    with pytest.MonkeyPatch.context() as m:
        m.setenv("OCCURRENCE_LEDGER_DIR", str(root / "occ"))
        m.setenv("AI_BRAIN_DIR", str(root / "brain"))
        m.setenv("AI_RETRIEVAL_DIR", str(root / "retr"))
        m.setenv("REPLAY_SESSIONS_DIR", str(root / "replay"))
        m.setenv("AI_BRAIN_ENABLED", "false"); m.setenv("AI_BRAIN_LLM", "false")
        m.setenv("BRAIN_ECU_MODE", "false"); m.chdir(root)
        cycle = ProductionScanCycle(symbol="MNQ", contract_id=CONTRACT, session_id="SCOPE")
        tape = _tape(); result = {}
        for end in range(20, 161):
            bars = tape[:end]
            out = cycle.scan(bars, now=datetime.fromisoformat(bars[-1]["timestamp"])
                             + timedelta(minutes=1), invoke_brain=False)
            hm = bars[-1]["timestamp"][11:16]
            if hm in ("14:29", "14:35", "14:36", "14:37", "14:38", "14:39", "15:38", "15:39", "15:40"):
                result[hm] = {"snapshot": copy.deepcopy(out["snapshot"]),
                              "settled_1m": copy.deepcopy(build_timeframes(bars)["1m"]),
                              "ledger_rows": copy.deepcopy(cycle.occurrence_ledger.occurrences())}
        yield result


class _Owner:
    """Unit owner replays REAL facts, not a detector or execution authority."""
    def __init__(self):
        self.contract_id = CONTRACT; self.session_id = "UNIT"
        self._history = SimpleNamespace(revision=0)
        self.campaign_scope_custody = CS.CampaignScopeCustody()
    def derived_state_is_current(self):
        return True


@pytest.fixture
def owner():
    return _Owner()


def _publish(owner, natural, hm):
    args = copy.deepcopy(natural[hm]); snap = args["snapshot"]
    args.update(owner=owner, history_revision=owner._history.revision,
                contract_id=owner.contract_id, market_session=CP._session_of(snap["timestamp"]))
    owner.campaign_scope_custody.advance(**args)
    return snap


def _proposal(snap, direction="bearish", kind="establish"):
    row = next(r for r in snap["campaign_premise_catalog"]["rows"]
               if r["supports"] == direction and r["d3"]["route_b"])
    return {"kind": kind, "direction": direction,
            "premise_candidate_id": row["premise_candidate_id"], "scope_reason": "MOCKED selection"}


def _brain(proposal):
    return {"source": "llm", "llm_model": PRODUCTION_MODEL, "fallback_reason": None,
            "repair_attempted": False, "family_repair_fixed": False,
            "invalidation_repair_fixed": False,
            "output": {"narrative_direction": proposal["direction"],
                       "campaign_scope_proposal": proposal}}


def _qualify(owner, snap, proposal=None, brain=None, payload=None):
    return owner.campaign_scope_custody.qualify(
        snapshot=snap, brain_result=brain or _brain(proposal or _proposal(snap)),
        brain_input=payload or {"campaign_premise_catalog": CS.current_campaign_catalog(snap)})


def test_real_catalog_and_strict_scope(owner, natural):
    from ai_brain.brain_input import build_brain_input
    from ai_brain.brain_validation import scan_payload_taint
    snap = _publish(owner, natural, "14:36")
    catalog = CS.current_campaign_catalog(snap)
    assert catalog and catalog["rows"]
    row = next(r for r in catalog["rows"] if r["d3"]["route_b"])
    assert row["certificate"]["covered_buckets"] == 1
    proof = row["d3"]["route_b"]
    assert proof["R"] == "2026-08-19T14:25:00+00:00"
    assert proof["D"] == "2026-08-19T14:23:00+00:00"
    assert proof["D_source"] == "1m_source"
    assert proof["from"] == "bullish" and proof["to"] == "bearish"
    payload = build_brain_input(snap, {})
    assert payload["campaign_premise_catalog"] == catalog
    assert scan_payload_taint(payload) == (True, [])
    assert CS.read_current_campaign_scope(snap)["authority"] == "none"
    assert snap["campaign_premise_shadow"]["retained_chains"] == 0


def test_pending_is_private_and_activates_only_later(owner, natural):
    snap = _publish(owner, natural, "14:36")
    original = copy.deepcopy(snap["campaign_scope_custody_shadow"])
    old_id = _proposal(snap)["premise_candidate_id"]
    result = _qualify(owner, snap)
    assert result["status"] == "PENDING"
    assert snap["campaign_scope_custody_shadow"] == original
    assert CS.read_current_campaign_scope(snap)["campaign"] is None
    duplicate = _publish(owner, natural, "14:36")
    assert duplicate["campaign_scope_custody_shadow"] == original
    assert CS.read_current_campaign_scope(snap)["status"] == "UNAVAILABLE"
    newer = _publish(owner, natural, "14:37")
    current = CS.read_current_campaign_scope(newer)
    assert current["authority"] == "none" and current["state"] == "ACTIVE"
    assert current["campaign"]["activated_at"] == newer["timestamp"]
    assert current["last_transition"]["kind"] == "establish"
    assert current["pending"] is None and current["retained_chains"] == 1
    assert old_id not in {r["premise_candidate_id"] for r in newer["campaign_premise_catalog"]["rows"]}
    continued = CS.read_current_campaign_scope(_publish(owner, natural, "14:38"))
    assert continued["campaign"]["campaign_id"] == current["campaign"]["campaign_id"]
    assert continued["campaign"]["scope_proof"] == current["campaign"]["scope_proof"]


@pytest.mark.parametrize("active", [False, True])
def test_same_cutoff_fact_conflict_cannot_republish_or_activate(owner, natural, active):
    snap = _publish(owner, natural, "14:36")
    proposal = _proposal(snap)
    assert _qualify(owner, snap, proposal)["status"] == "PENDING"
    if active:
        snap = _publish(owner, natural, "14:37")
        assert CS.read_current_campaign_scope(snap)["state"] == "ACTIVE"
    hm = "14:37" if active else "14:36"
    args = copy.deepcopy(natural[hm])
    args["snapshot"]["active_path_state"]["origin"]["occurrence_id"] = "conflicting-origin"
    def advance(value):
        return owner.campaign_scope_custody.advance(owner=owner, **value,
            history_revision=0, contract_id=CONTRACT, market_session="20260819")
    for value in [args, copy.deepcopy(args), copy.deepcopy(natural[hm])]:
        result = advance(value)
        assert result["status"] == "UNAVAILABLE"
        assert result["reason"] == "conflicting_same_cutoff_facts"
        assert "campaign_premise_catalog" not in value["snapshot"]
        assert CS.read_current_campaign_scope(value["snapshot"])["status"] == "UNAVAILABLE"
        assert CS.current_campaign_catalog(value["snapshot"]) is None
    assert CS.read_current_campaign_scope(snap)["status"] == "UNAVAILABLE"
    later = CS.read_current_campaign_scope(_publish(owner, natural, "14:38"))
    assert later["status"] == "AVAILABLE" and later["state"] == "UNBOUND"
    assert later["campaign"] is None and later["pending"] is None
    assert later["retained_chains"] == 0
    if active:
        assert later["last_transition"]["reason"] == "premise_observation_unknown"
        assert later["last_transition"]["failure_bucket"] is None
    else:
        assert later["pending_disposition"]["reason"] == "conflicting_same_cutoff_facts"


@pytest.mark.parametrize("change", ["repair_attempted", "family_repair_fixed",
                                  "invalidation_repair_fixed", "model", "fallback", "source", "missing"])
def test_provenance_disqualified_does_not_select(owner, natural, change):
    snap = _publish(owner, natural, "14:36"); brain = _brain(_proposal(snap))
    if change == "model": brain["llm_model"] = "wrong-model"
    elif change == "fallback": brain["fallback_reason"] = "degraded"
    elif change == "source": brain["source"] = "deterministic"
    elif change == "missing": brain.pop("repair_attempted")
    else: brain[change] = True
    before = copy.deepcopy(brain)
    assert _qualify(owner, snap, brain=brain)["status"] == "ABSENT"
    assert brain == before
    assert CS.read_current_campaign_scope(_publish(owner, natural, "14:37"))["campaign"] is None


@pytest.mark.parametrize("change", ["extra", "kind", "direction", "id_type", "reason_type", "missing"])
def test_malformed_optional_field_refused_without_changing_brain(owner, natural, change):
    snap = _publish(owner, natural, "14:36"); proposal = _proposal(snap)
    if change == "extra": proposal["unknown"] = True
    elif change == "kind": proposal["kind"] = "amend"
    elif change == "direction": proposal["direction"] = "BEARISH"
    elif change == "id_type": proposal["premise_candidate_id"] = 1
    elif change == "reason_type": proposal["scope_reason"] = None
    else: proposal.pop("kind")
    brain = _brain({**proposal, "direction": proposal.get("direction", "bearish")})
    before = copy.deepcopy(brain)
    assert _qualify(owner, snap, brain=brain)["status"] == "REFUSED"
    assert brain == before and owner.campaign_scope_custody._pending is None


def test_absent_null_duplicate_conflict(owner, natural):
    snap = _publish(owner, natural, "14:36")
    assert _qualify(owner, snap, brain={"output": {}})["status"] == "ABSENT"
    assert _qualify(owner, snap, brain={"output": {"campaign_scope_proposal": None}})["status"] == "ABSENT"
    proposal = _proposal(snap)
    first = _qualify(owner, snap, proposal)
    assert first["status"] == "PENDING"
    duplicate = _qualify(owner, snap, proposal)
    assert duplicate["status"] == "DUPLICATE" and duplicate["proposal_id"] == first["proposal_id"]
    other = {**proposal, "scope_reason": "different same-cutoff selection"}
    assert _qualify(owner, snap, other)["reasons"] == ["conflicting_same_cutoff_proposals"]
    assert _qualify(owner, snap, proposal)["status"] == "REFUSED"
    assert CS.read_current_campaign_scope(_publish(owner, natural, "14:37"))["campaign"] is None


def test_stale_catalog_id_and_payload_do_not_activate(owner, natural):
    old = _publish(owner, natural, "14:36"); proposal = _proposal(old)
    snap = _publish(owner, natural, "14:37")
    assert _qualify(owner, snap, proposal)["reasons"] == ["unknown_or_ambiguous_id"]
    assert _qualify(owner, snap, _proposal(snap), payload={"campaign_premise_catalog": old["campaign_premise_catalog"]})["reasons"] == ["stale_catalog"]
    assert CS.read_current_campaign_scope(_publish(owner, natural, "14:38"))["campaign"] is None


def test_pre_hold_direction_is_used(owner, natural):
    snap = _publish(owner, natural, "14:36"); brain = _brain(_proposal(snap))
    brain["output"]["narrative_direction"] = "conflicted"
    brain["narrative_authority_guard"] = {"status": "unestablished_campaign_held", "proposed_direction": "bearish"}
    assert _qualify(owner, snap, brain=brain)["status"] == "PENDING"


@pytest.mark.parametrize("change", ["copy", "projection", "catalog", "path", "revision", "contract", "restart", "foreign"])
def test_producer_ownership_refuses_forgery_and_stale_data(owner, natural, change):
    snap = _publish(owner, natural, "14:36")
    assert CS.read_current_campaign_scope(snap)["status"] == "AVAILABLE"
    if change == "copy": snap = copy.deepcopy(snap)
    elif change == "projection": snap["campaign_scope_custody_shadow"]["authority"] = "scope"
    elif change == "catalog": snap["campaign_premise_catalog"]["digest"] = "forged"
    elif change == "path": snap["active_path_state"]["owner"] = "bullish"
    elif change == "revision": owner._history.revision += 1
    elif change == "contract": owner.contract_id = "foreign"
    elif change == "restart": owner.campaign_scope_custody = CS.CampaignScopeCustody()
    else:
        foreign = _publish(_Owner(), natural, "14:36")
        snap["campaign_scope_custody_shadow"] = foreign["campaign_scope_custody_shadow"]
    assert CS.read_current_campaign_scope(snap)["status"] == "UNAVAILABLE"
    assert CS.current_campaign_catalog(snap) is None


@pytest.mark.parametrize("change", ["R_equal_D", "R_before_D", "future_death", "non_1m_missing_edge", "missing_origin"])
def test_strict_scope_negative_predicates(owner, natural, change):
    snap = _publish(owner, natural, "14:36")
    row = next(r for r in snap["campaign_premise_catalog"]["rows"] if r["d3"]["route_b"])
    snap, row = copy.deepcopy(snap), copy.deepcopy(row)
    death = snap["active_path_state"]["last_invalidated"]
    if change == "R_equal_D": row["raids"][0]["event_time"] = death["source_bar_time"]
    elif change == "R_before_D": row["raids"][0]["event_time"] = "2026-08-19T14:00:00+00:00"
    elif change == "future_death": death["source_bar_time"] = "2026-08-19T17:00:00+00:00"
    elif change == "non_1m_missing_edge": death["source_tf"] = "15m"; death["settled_edge_time"] = None
    else: snap["active_path_state"]["origin"]["occurrence_id"] = None
    assert CS.campaign_scope_proof(snap, row)[0] is None


def test_multiple_raid_references_preserved(owner, natural):
    snap = _publish(owner, natural, "15:38")
    row = next(r for r in snap["campaign_premise_catalog"]["rows"] if r["supports"] == "bullish")
    proof, reason = CS.campaign_scope_proof(snap, row)
    assert reason is None and len(row["raids"]) == len(proof["raid_references"]) == 3
    assert proof["cited_raid_id"] == min(row["raids"], key=lambda x: x["event_time"])["canonical_sweep_id"]
    assert proof["local_transfer_proof"]["load_bearing_structure"]["timeframe"] == "1m"
    assert row["life"]["source_tf"] == "5m"  # independent supporting life, not price equality


def test_private_seal_corruption_voids(owner, natural):
    snap = _publish(owner, natural, "14:36"); assert _qualify(owner, snap)["status"] == "PENDING"
    owner.campaign_scope_custody._pending["accepted"]["proposal"]["scope_reason"] = "tampered"
    projection = CS.read_current_campaign_scope(_publish(owner, natural, "14:37"))
    assert projection["campaign"] is None
    assert projection["last_transition"]["reason"] == "stale_proposal_seal"


def test_revision_boundary_voids_and_restart_never_restores(owner, natural):
    snap = _publish(owner, natural, "14:36"); _qualify(owner, snap)
    owner._history.revision = 1
    current = CS.read_current_campaign_scope(_publish(owner, natural, "14:37"))
    assert current["campaign"] is None and current["pending"] is None
    assert current["last_transition"]["reason"] == "context_boundary"
    owner.campaign_scope_custody.reset()
    assert CS.read_current_campaign_scope(snap)["status"] == "UNAVAILABLE"


def test_catalog_filter_and_bound_observation_are_separate(owner, natural):
    snap = _publish(owner, natural, "14:36"); _qualify(owner, snap)
    active = CS.read_current_campaign_scope(_publish(owner, natural, "14:37"))
    args = copy.deepcopy(natural["14:38"])
    args["snapshot"]["protected_swings"]["by_timeframe"]["highs"].pop("5m", None)
    owner.campaign_scope_custody.advance(owner=owner, **args, history_revision=0,
        contract_id=CONTRACT, market_session="20260819")
    current = CS.read_current_campaign_scope(args["snapshot"])
    assert current["campaign"]["campaign_id"] == active["campaign"]["campaign_id"]
    assert current["campaign"]["certificate"]["status"] == "INTACT"
    assert not any(r["supports"] == "bearish" for r in args["snapshot"]["campaign_premise_catalog"]["rows"])


def test_unknown_observation_retires_without_failure(owner, natural):
    snap = _publish(owner, natural, "14:36"); _qualify(owner, snap)
    _publish(owner, natural, "14:37")
    args = copy.deepcopy(natural["14:39"])
    args["settled_1m"] = [b for b in args["settled_1m"] if b["timestamp"][11:16] != "14:38"]
    owner.campaign_scope_custody.advance(owner=owner, **args, history_revision=0,
        contract_id=CONTRACT, market_session="20260819")
    current = CS.read_current_campaign_scope(args["snapshot"])
    assert current["campaign"] is None and current["state"] == "UNBOUND"
    assert current["last_transition"]["reason"] == "premise_observation_unknown"
    assert current["last_transition"]["failure_bucket"] is None
    assert current["retained_chains"] == 0


def test_newborn_cannot_enter_catalog_with_k_one(owner, natural):
    snap = _publish(owner, natural, "14:29")
    lives = [r for r in snap["campaign_premise_shadow"]["lives"]
             if r["registered_at"] == "2026-08-19T14:29:00+00:00"]
    assert lives and lives[0]["certificate"]["covered_buckets"] == 0
    assert not any(r["life"]["registered_at"] == lives[0]["registered_at"]
                   for r in snap["campaign_premise_catalog"]["rows"])


def test_failed_close_is_a_failure_with_witness(owner, natural):
    snap = _publish(owner, natural, "14:36"); _qualify(owner, snap)
    _publish(owner, natural, "14:37")
    args = copy.deepcopy(natural["14:39"])
    last = args["settled_1m"][-1]
    last["close"] = 29521.0; last["high"] = max(last["high"], last["close"])
    owner.campaign_scope_custody.advance(owner=owner, **args, history_revision=0,
        contract_id=CONTRACT, market_session="20260819")
    current = CS.read_current_campaign_scope(args["snapshot"])
    assert current["campaign"] is None
    assert current["last_transition"]["reason"] == "premise_failed"
    assert current["last_transition"]["failure_bucket"]["close"] == 29521.0


@pytest.mark.parametrize("change", ["origin", "unverified"])
def test_current_transfer_proof_must_be_revalidated(owner, natural, change):
    snap = _publish(owner, natural, "14:36"); _qualify(owner, snap)
    args = copy.deepcopy(natural["14:37"])
    if change == "origin": args["snapshot"]["active_path_state"]["origin"]["occurrence_id"] = "different-current-origin"
    else: args["snapshot"]["active_path_state"]["status"] = "contested"
    owner.campaign_scope_custody.advance(owner=owner, **args, history_revision=0,
        contract_id=CONTRACT, market_session="20260819")
    current = CS.read_current_campaign_scope(args["snapshot"])
    assert current["campaign"] is None and current["pending"] is None
    expected = "lt_origin_or_from_to_changed" if change == "origin" else "lt_not_verified"
    assert current["last_transition"]["reason"] == expected
    assert CS.read_current_campaign_scope(_publish(owner, natural, "14:38"))["campaign"] is None


def test_retained_pending_certificate_can_continue_from_real_tip(owner, natural):
    snap = _publish(owner, natural, "14:36"); _qualify(owner, snap)
    args = copy.deepcopy(natural["14:37"])
    args["settled_1m"] = [b for b in args["settled_1m"] if b["timestamp"] >= "2026-08-19T14:30:00+00:00"]
    args["snapshot"]["campaign_premise_shadow"] = CP.CampaignPremiseShadow().advance(
        **args, history_revision=0, contract_id=CONTRACT, market_session="20260819", cutoff=args["snapshot"]["timestamp"])
    assert any(r["certificate"]["status"] == "UNKNOWN" for r in args["snapshot"]["campaign_premise_shadow"]["lives"])
    owner.campaign_scope_custody.advance(owner=owner, **args, history_revision=0,
        contract_id=CONTRACT, market_session="20260819")
    current = CS.read_current_campaign_scope(args["snapshot"])
    assert current["campaign"] is not None
    assert current["campaign"]["certificate"]["status"] == "INTACT"


def test_failure_precedes_transfer_and_keeps_real_failure_audit(owner, natural):
    snap = _publish(owner, natural, "14:36"); _qualify(owner, snap)
    incumbent = CS.read_current_campaign_scope(_publish(owner, natural, "14:37"))["campaign"]
    snap = _publish(owner, natural, "15:38")
    assert CS.read_current_campaign_scope(snap)["campaign"]["campaign_id"] == incumbent["campaign_id"]
    assert _qualify(owner, snap, _proposal(snap, "bullish", "transfer"))["status"] == "PENDING"
    current = CS.read_current_campaign_scope(_publish(owner, natural, "15:39"))
    assert current["campaign"] is None
    assert current["last_transition"]["kind"] == "retire"
    assert current["last_transition"]["reason"] == "premise_failed"
    assert current["last_transition"]["failure_bucket"]
    assert current["pending_disposition"]["reason"] == "incumbent_not_active"
    assert current["retained_chains"] == 0


@pytest.mark.parametrize("ecu", [False, True])
def test_real_primary_transport_proposal_and_brainless_activation(tmp_path, monkeypatch, ecu):
    import test_reversal_foundation_proof_closure as RF
    import ai_brain.ecu as ECU
    monkeypatch.setenv("OCCURRENCE_LEDGER_DIR", str(tmp_path / "occ"))
    monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path / "brain"))
    monkeypatch.setenv("BRAIN_ECU_MODE", "false"); monkeypatch.setenv("AI_BRAIN_ENABLED", "false")
    monkeypatch.setenv("AI_BRAIN_LLM", "false")
    cycle = ProductionScanCycle(symbol="MNQ", contract_id=CONTRACT, session_id="INTEGRATION")
    tape = _tape()
    for end in range(20, 97):
        cycle.scan(tape[:end], now=datetime.fromisoformat(tape[end-1]["timestamp"])
                   + timedelta(minutes=1), invoke_brain=False)
    calls = []
    def mocked_selection(output, ordinal, payload):
        result = {**output, "narrative_direction": "bearish", "allowed_direction": "bearish",
                  "forbidden_direction": "bullish", "current_action": "stand_down",
                  "narrative_phase": "continuation", "phase_confidence": 80,
                  "recommended_playbook_family": "none", "recommended_tool_family": ["none"],
                  "objective_id": None, "invalidation_id": None, "invalidation_level": None}
        if ordinal == 1:
            result["campaign_scope_proposal"] = _proposal({"campaign_premise_catalog": payload["campaign_premise_catalog"]})
        return result
    RF._mock_current_brain(monkeypatch, calls, output_mutator=mocked_selection)
    monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
    try:
        first = cycle.scan(tape[:97], now=datetime.fromisoformat(tape[96]["timestamp"])
                           + timedelta(minutes=1), invoke_brain=True)
        assert len(calls) == 1
        assert first["brain_block"]["source"] == "llm"
        assert first["snapshot"]["campaign_scope_proposal_outcome"]["status"] == "PENDING"
        assert first["snapshot"]["campaign_scope_custody_shadow"]["campaign"] is None
        second = cycle.scan(tape[:98], now=datetime.fromisoformat(tape[97]["timestamp"])
                            + timedelta(minutes=1), invoke_brain=False)
        assert len(calls) == 1
        assert "campaign_scope_proposal_outcome" not in second["snapshot"]
        projection = CS.read_current_campaign_scope(second["snapshot"])
        assert projection["state"] == "ACTIVE" and projection["authority"] == "none"
        third = cycle.scan(tape[:99], now=datetime.fromisoformat(tape[98]["timestamp"])
                           + timedelta(minutes=1), invoke_brain=True)
        assert len(calls) == 2
        assert third["snapshot"]["campaign_scope_proposal_outcome"]["status"] == "ABSENT"
        assert CS.read_current_campaign_scope(third["snapshot"])["campaign"]["campaign_id"] == projection["campaign"]["campaign_id"]
    finally:
        ECU._STANCE = None


def test_real_scoped_transfer_replaces_an_intact_incumbent(tmp_path, monkeypatch):
    """Real producer, explicit MOCKED primary selections; no detector injection.

    A lawful new 15:39 close below the old high keeps that own-TF premise
    intact while the independently scoped opposing local proof survives.
    """
    monkeypatch.setenv("OCCURRENCE_LEDGER_DIR", str(tmp_path / "occ"))
    monkeypatch.setenv("BRAIN_ECU_MODE", "false"); monkeypatch.setenv("AI_BRAIN_ENABLED", "false")
    monkeypatch.setenv("AI_BRAIN_LLM", "false")
    cycle = ProductionScanCycle(symbol="MNQ", contract_id=CONTRACT, session_id="TRANSFER")
    tape = _tape()
    def scan(end):
        return cycle.scan(tape[:end], now=datetime.fromisoformat(tape[end-1]["timestamp"])
                          + timedelta(minutes=1), invoke_brain=False)["snapshot"]
    for end in range(20, 98): snap = scan(end)
    assert snap["timestamp"][11:16] == "14:36"
    assert _qualify(cycle, snap)["status"] == "PENDING"
    incumbent = CS.read_current_campaign_scope(scan(98))["campaign"]
    assert incumbent["direction"] == "bearish"
    for end in range(99, 160): snap = scan(end)
    before = CS.read_current_campaign_scope(snap)
    assert before["campaign"]["campaign_id"] == incumbent["campaign_id"]
    assert before["campaign"]["certificate"]["status"] == "INTACT"
    assert _qualify(cycle, snap, _proposal(snap, "bullish", "transfer"))["status"] == "PENDING"
    # Alter only the next, not-yet-seen candle; preserve lawful OHLC.
    tape[159]["close"] = 29519.5
    tape[159]["low"] = min(tape[159]["low"], 29519.25)
    current = CS.read_current_campaign_scope(scan(160))
    assert current["authority"] == "none" and current["state"] == "ACTIVE"
    assert current["campaign"]["direction"] == "bullish"
    assert current["campaign"]["campaign_id"] != incumbent["campaign_id"]
    assert current["last_transition"]["kind"] == "transfer"
    assert current["last_transition"]["predecessor_campaign_id"] == incumbent["campaign_id"]
    assert current["campaign"]["scope_proof"]["from"] == "bearish"
    assert current["campaign"]["scope_proof"]["to"] == "bullish"
    assert current["retained_chains"] == 1
