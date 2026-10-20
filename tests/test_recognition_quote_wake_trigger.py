"""Stage 5 gap mission 3: quote wake -> conditional trigger -> final quote, offline.

The driver feeds the ACTUAL production `WakeRegistry` the way the launcher and
the live quote provider do (bootstrap, structure refresh on release, every
delivered sided quote to `on_quote`) and routes each tick like one launcher
loop iteration: `handle_pending_conditional_wake()` first, `scan_once()`
otherwise. A Brain-authored `watching` plan published at 16:30 on the
CONSTRUCTED distinct-anchor tape is woken by a sided quote at 16:32:30 and
triggers without any Brain call.

    DISARMED                the trigger stops at QUALIFIED_CANDIDATE_OBSERVED.
    REFUSING_VENUE_DOUBLE   the arm switch is ON against a venue whose every
                            write raises, so the trigger reaches the runner's
                            final-quote authentication (`validate_final_quote`)
                            and one refused place_order (SUBMIT_FAILED).

Every attack below has a healthy reachable control built from the same tape
and differs from it in one named input; the decisive cause is read from the
per-tick `offline_tick_trace/v1` artifact and the production plan events.
CONSTRUCTED data, MOCK Brain; no model, provider, venue or network is reached.

Declared limits (also in the ledger): a quote message that arrives between the
trigger scan and the final capture is modelled by emitting it on the hub at
capture time (one tick cannot hold two historical quotes); an interaction the
route itself raises is spent by the next offered tick.
"""
import contextlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_po3_distinct_anchor_premise as W  # noqa: E402
import test_recognition_current_path as CP  # noqa: E402
import test_recognition_scoring_cli as SCLI  # noqa: E402
from recognition_validation import __main__ as CLI  # noqa: E402
from recognition_validation import brain_gateway as G  # noqa: E402
from recognition_validation import child as CH  # noqa: E402
from recognition_validation import contracts as C  # noqa: E402
from recognition_validation import corpus as K  # noqa: E402
from recognition_validation import driver as DR  # noqa: E402
from recognition_validation import recorder as REC  # noqa: E402
from recognition_validation import report as RP  # noqa: E402

DISARMED, REFUSING = DR.VENUE_LANES
DAY = "2026-08-19T"
PREWARM, UNTIL = DAY + "16:20:00Z", DAY + "16:35:00Z"
WAKE = (DAY + "16:32:30+00:00", DAY + "16:32:30+00:00", 29514.0, 29514.25)   # tick, captured, bid, ask
LATE_WAKE = (DAY + "16:33:30+00:00", DAY + "16:33:30+00:00", 29514.0, 29514.25)
ZONE = (29513.25, 29517.5)          # the bearish order block the plan authorizes
STOP = 29518.5                      # its 3m protected high (INV_PH_3m_3)
OTHER_CONTRACT = "CON.F.US.MNQ.H27"

# variant -> (tape edits {minute: fields}, wakes, plan lifetime seconds, prewarm, revisions)
VARIANTS = {
    "HEALTHY": ({}, [WAKE], 1800, PREWARM, None),
    "EXPIRED": ({}, [WAKE], 135, PREWARM, None),
    "STALE_QUOTE": ({}, [(DAY + "16:32:40+00:00", WAKE[1], WAKE[2], WAKE[3])], 1800, PREWARM, None),
    "OTHER_CONTRACT": ({}, [WAKE + (OTHER_CONTRACT,)], 1800, PREWARM, None),
    "DUPLICATE_WAKE": ({}, [WAKE, (DAY + "16:32:40+00:00", DAY + "16:32:40+00:00", 29514.25, 29514.5)],
                       1800, PREWARM, None),
    "NORMAL_WAKE": ({}, [(DAY + "16:30:30+00:00", DAY + "16:30:30+00:00", 29510.75, 29511.0), WAKE],
                    1800, PREWARM, None),
    "OBJECTIVE_REACHED": ({"16:31": {"low": 29505.0}}, [WAKE], 1800, PREWARM, None),
    "PROVIDER_REVISION": ({}, [WAKE], 1800, PREWARM, "16:31"),
    "RESTART": ({}, [WAKE], 1800, DAY + "16:31:00Z", None),
    "STOP_3M_CLOSE": ({"16:32": {"close": 29519.0, "high": 29519.0}}, [LATE_WAKE], 1800, PREWARM, None),
    "STOP_3M_CONTROL": ({"16:32": {"close": 29518.25, "high": 29518.25}}, [LATE_WAKE], 1800, PREWARM, None),
}


def _watching_script(lifetime):
    """The CONSTRUCTED distinct-anchor Brain, authoring a `watching` plan instead of an entry."""
    inner, _ = CP._script()

    def script(request):
        reply = inner(request)
        if reply and reply.get("current_action") == "propose_entry":
            at = datetime.fromisoformat(request["decision_time"])
            reply = {**reply, "current_action": "watching",
                     "plan_expires_at": (at + timedelta(seconds=lifetime)).isoformat()}
        return reply
    return script


def _corpus(base, variant):
    edits, wakes, _, _, revision = VARIANTS[variant]
    tape = W._tape(W._HEALTHY)
    for bar in tape:
        bar.update(edits.get(bar["timestamp"][11:16], {}))
    quotes = [{"captured_at_utc": (datetime.fromisoformat(b["timestamp"]) + timedelta(minutes=1)).isoformat(),
               "bid": b["close"], "ask": b["close"] + 0.25, "contract_id": CP.CONTRACT} for b in tape]
    quotes += [{"captured_at_utc": w[1], "bid": w[2], "ask": w[3],
                "contract_id": w[4] if len(w) > 4 else CP.CONTRACT} for w in wakes]
    quotes.sort(key=lambda q: q["captured_at_utc"])
    revisions = None
    if revision:
        bar = next(b for b in tape if b["timestamp"][11:16] == revision)
        revisions = [{"bar_open_utc": bar["timestamp"], "available_at_utc": DAY + "16:32:10+00:00",
                      "bar": {"close": bar["close"] + 0.5, "high": max(bar["high"], bar["close"] + 0.5)}}]
    return K.build_constructed_corpus(base / "corpus", session_id=CP.SESSION, contract_id=CP.CONTRACT,
                                      market_date="2026-08-19", tape=tape, warmup_end="2026-08-19T15:30:00+00:00",
                                      notes=f"CONSTRUCTED distinct-anchor tape, mission 3 variant {variant}.",
                                      sealed_at="2026-10-17T00:00:00Z", quotes=quotes, revisions=revisions)


def _ticks(corpus_path, variant):
    _, wakes, _, prewarm, _ = VARIANTS[variant]
    stream = K.load_corpus(corpus_path).sessions[CP.SESSION].stream
    ticks = [t for t in DR.minute_schedule(stream, prewarm_until=DR.utc(prewarm)) if t.decision_time <= DR.utc(UNTIL)]
    ticks += [DR.Tick(0, DR.utc(w[0]), "QUOTE_WAKE") for w in wakes]
    ticks.sort(key=lambda t: t.decision_time)
    return [DR.Tick(i, t.decision_time, t.kind) for i, t in enumerate(ticks)]


def _traces(evidence):
    """{HH:MM:SS: (event, tick trace)} for every non-PREWARM tick."""
    out = {}
    for event in REC.read_events(evidence):
        trace = json.loads((evidence / event["evidence_refs"][0]["path"]).read_text()) if event["evidence_refs"] else {}
        out[event["observed_at"][11:19]] = (event, trace)
    return out


_CACHE: dict = {}


def run(tmp_path_factory, variant, lane, *, ecu=False, instrument=None, tag=None):
    key = (variant, lane, ecu, tag)
    if key not in _CACHE:
        base = tmp_path_factory.mktemp(f"m3-{variant}-{lane}-{ecu}-{tag}".lower())
        corpus = _corpus(base, variant)
        with (instrument or contextlib.nullcontext)():
            summary = DR.run_offline(corpus_path=corpus, session_id=CP.SESSION, out_root=base / "run", ecu=ecu,
                                     trajectory_id=f"S5-M3-{variant}", ticks=_ticks(corpus, variant),
                                     quote_policy="CONSTRUCTED", venue_lane=lane,
                                     responder=G.ScriptedResponder(_watching_script(VARIANTS[variant][2]),
                                                                   fixture_digest=C.digest("m3-watching-v1")))
        evidence = Path(summary["evidence_root"])
        _CACHE[key] = {"summary": summary, "evidence": evidence, "ticks": _traces(evidence),
                       "manifest": RP.read_manifest(evidence), "corpus_path": corpus}
    return _CACHE[key]


def _plan_events(trace):
    return [(row.get("event"), row.get("trigger_decision_reason") or row.get("reason"))
            for row in trace.get("plan_events") or []]


def _refusal_detail(trace):
    return " ".join(str(row.get("detail")) for row in trace.get("plan_events") or [] if row.get("event") == "plan_refused")


def _published(world):
    event, trace = world["ticks"]["16:30:00"]
    assert event["outcome"] == "CONDITIONAL_PLAN_PUBLISHED" and event["primary_call_count"] == 1
    plan = trace["plan_after"]
    assert (plan["direction"], plan["zone_low"], plan["zone_high"]) == ("bearish",) + ZONE
    assert plan["invalidation_price"] == STOP
    assert plan["structural_invalidation"]["structure_identity"] == "INV_PH_3m_3"
    assert plan["structural_invalidation"]["authorized_catalog_row"]["timeframe"] == "3m"
    return plan


def _triggered(world, at):
    """The tick at `at` routed a matching zone wake into the brainless trigger."""
    event, trace = world["ticks"][at]
    assert trace["route"] == "CONDITIONAL_TRIGGER"
    assert event["primary_call_count"] == 0 and trace["brain_calls"] == {"primary": 0, "repair": 0}
    assert trace["registry"]["interaction_consumed"] is True
    assert "conditional_plan_zone_reached" in [w["reason"] for w in trace["registry"]["new_wakes"]]
    assert event["plan_id"] == trace["plan_before"]["plan_id"]
    assert trace["plan_after"] is None or trace["plan_after"]["plan_id"] != trace["plan_before"]["plan_id"]
    return event, trace


def _accepted(world, at, lane):
    event, trace = _triggered(world, at)
    events = _plan_events(trace)
    assert ("entry_condition_reached", None) in events and ("plan_mechanics_accepted", None) in events
    if lane == DISARMED:
        assert (event["outcome"], event["boundary"]) == ("QUALIFIED_CANDIDATE_OBSERVED", "PLAN_TRIGGER")
        assert trace["final_quote_economics"] is None and trace["venue_writes"] == []
        assert trace["mission"] == {"tokens": 0, "attempts": 0}
    else:
        economics = trace["final_quote_economics"]
        assert economics["decision"] == "EXECUTE_AS_AUTHORIZED" and economics.get("refusal_reason") is None
        assert ZONE[0] <= economics["final_entry_reference"] <= ZONE[1]
        assert ("final_quote_captured", None) in events and ("submission_started", None) in events
        assert (event["outcome"], event["boundary"]) == ("SUBMIT_FAILED", "PRE_VENUE")
        assert len(trace["venue_writes"]) == 1 and trace["venue_writes"][0]["call"] == "place_order"
        assert trace["mission"] == {"tokens": 1, "attempts": 1}
    return event, trace


def _refused(world, at, reason):
    event, trace = _triggered(world, at)
    assert event["outcome"] == "NO_CANDIDATE" and event["first_refusal_code"] == reason
    assert ("plan_mechanics_refused", reason) in _plan_events(trace) and ("plan_refused", reason) in _plan_events(trace)
    assert trace["final_quote_economics"] is None and trace["venue_writes"] == []
    assert trace["mission"] == {"tokens": 0, "attempts": 0}
    return event, trace


# -- acceptance: healthy plan -> sided quote -> genuine trigger, both lanes, both ECU modes --

@pytest.mark.parametrize("ecu", [False, True], ids=["non-ECU", "ECU"])
@pytest.mark.parametrize("lane", [DISARMED, REFUSING])
def test_healthy_quote_wake_triggers_the_plan_and_reaches_its_lane_boundary(tmp_path_factory, lane, ecu):
    world = run(tmp_path_factory, "HEALTHY", lane, ecu=ecu)
    plan = _published(world)
    for at in ("16:31:00", "16:32:00"):    # waiting: no Brain while the plan is live and the price is not in zone
        event, trace = world["ticks"][at]
        assert event["outcome"] == "CONDITIONAL_PLAN_WAITING" and event["primary_call_count"] == 0
        assert trace["plan_after"]["plan_id"] == plan["plan_id"]
    event, trace = _accepted(world, "16:32:30", lane)
    assert trace["quote"] == {"state": "DELIVERED", "origin": "CONSTRUCTED", "best_bid": WAKE[2], "best_ask": WAKE[3],
                              "captured_at": WAKE[1], "age_seconds": 0.0}
    assert trace["tick"]["kind"] == "QUOTE_WAKE" and trace["plan_before"]["plan_id"] == plan["plan_id"]
    assert trace["registry"]["interaction_pending_after_route"] is False
    if lane == REFUSING:
        assert trace["final_quote_economics"]["final_entry_reference"] == WAKE[2]   # sell side executes at bid
    manifest = world["manifest"]
    assert manifest["venue_lane"] == lane and manifest["ecu"] is ecu
    assert manifest["quote_wakes_routed"] >= 1 and manifest["conditional_triggers"] >= 1
    assert manifest["network_attempts"] == []
    assert manifest["mission_tokens"] == (0 if lane == DISARMED else 1)


# -- attacks, each against its own healthy control ------------------------------

def test_expired_plan_refuses_at_the_trigger(tmp_path_factory):
    control = run(tmp_path_factory, "HEALTHY", DISARMED)
    _accepted(control, "16:32:30", DISARMED)
    world = run(tmp_path_factory, "EXPIRED", DISARMED)
    plan = _published(world)
    assert datetime.fromisoformat(plan["expires_at"]) < datetime.fromisoformat(WAKE[0])
    event, trace = world["ticks"]["16:32:30"]
    assert event["first_refusal_code"] == "conditional_plan_expired" and trace["venue_writes"] == []
    assert event["primary_call_count"] == 0 and trace["mission"] == {"tokens": 0, "attempts": 0}


def test_stale_quote_refuses_because_the_trigger_is_no_longer_true(tmp_path_factory):
    _accepted(run(tmp_path_factory, "HEALTHY", DISARMED), "16:32:30", DISARMED)
    world = run(tmp_path_factory, "STALE_QUOTE", DISARMED)
    event, trace = world["ticks"]["16:32:40"]
    assert trace["quote"]["captured_at"] == WAKE[1] and trace["quote"]["age_seconds"] == 10.0
    _refused(world, "16:32:40", "conditional_plan_trigger_no_longer_true")


def test_quote_for_another_contract_is_missing_and_never_wakes_the_plan(tmp_path_factory):
    _accepted(run(tmp_path_factory, "HEALTHY", DISARMED), "16:32:30", DISARMED)
    world = run(tmp_path_factory, "OTHER_CONTRACT", DISARMED)
    plan = _published(world)
    event, trace = world["ticks"]["16:32:30"]
    assert trace["quote"] == {"state": "MISSING", "reason": "quote_contract_mismatch"}
    assert trace["route"] == "WAIT" and event["outcome"] == "QUOTE_WAKE_NO_QUOTE"
    assert "quote_contract_mismatch" in event["missing_evidence"]
    assert trace["registry"]["new_wakes"] == [] and trace["plan_after"]["plan_id"] == plan["plan_id"]
    assert world["summary"]["calls"][-1]["purpose"] == "PRIMARY"   # nothing silently triggered


def test_duplicate_wake_after_a_trigger_spends_nothing_twice(tmp_path_factory):
    world = run(tmp_path_factory, "DUPLICATE_WAKE", REFUSING)
    _accepted(world, "16:32:30", REFUSING)
    event, trace = world["ticks"]["16:32:40"]
    assert trace["route"] == "WAIT" and event["outcome"] == "QUOTE_WAKE_NO_INTERACTION"
    assert trace["registry"]["new_wakes"] == [] and trace["plan_before"] is None
    assert trace["mission"] == {"tokens": 1, "attempts": 1} and trace["venue_writes"] == []


def test_normal_wake_requests_a_scan_and_the_live_plan_suppresses_the_brain(tmp_path_factory):
    world = run(tmp_path_factory, "NORMAL_WAKE", DISARMED)
    plan = _published(world)
    event, trace = world["ticks"]["16:30:30"]
    assert trace["registry"]["interaction_consumed"] is True
    assert "conditional_plan_zone_reached" not in [w["reason"] for w in trace["registry"]["new_wakes"]]
    assert trace["route"] == "SCAN" and event["outcome"] == "CONDITIONAL_PLAN_WAITING"
    assert event["primary_call_count"] == 0 and trace["plan_after"]["plan_id"] == plan["plan_id"]
    _accepted(world, "16:32:30", DISARMED)   # the same plan still triggers on its own zone wake


@pytest.mark.parametrize("variant,reason", [
    ("OBJECTIVE_REACHED", "conditional_plan_review_required"),
    ("PROVIDER_REVISION", "campaign_lifecycle_refused"),
])
def test_changed_market_facts_refuse_the_trigger(tmp_path_factory, variant, reason):
    _accepted(run(tmp_path_factory, "HEALTHY", DISARMED), "16:32:30", DISARMED)
    world = run(tmp_path_factory, variant, DISARMED)
    _published(world)
    _refused(world, "16:32:30", reason)


def test_provider_revision_is_a_versioned_release_before_the_trigger(tmp_path_factory):
    world = run(tmp_path_factory, "PROVIDER_REVISION", DISARMED)
    control = run(tmp_path_factory, "HEALTHY", DISARMED)
    # the 16:31 bar's version 2 becomes available at 16:32:10: only the revised world's history moves
    assert (world["ticks"]["16:32:30"][0]["history_revision"] > world["ticks"]["16:32:00"][0]["history_revision"])
    assert (control["ticks"]["16:32:30"][0]["history_revision"] == control["ticks"]["16:32:00"][0]["history_revision"])


def test_restart_has_no_plan_to_trigger_and_the_wake_requests_fresh_cognition(tmp_path_factory):
    world = run(tmp_path_factory, "RESTART", DISARMED)
    # the 16:30 authoring scan was prewarm (no cognition): nothing was captured to trigger at the wake
    assert all(trace.get("route") != "CONDITIONAL_TRIGGER" for at, (_, trace) in world["ticks"].items() if at <= "16:32:30")
    assert world["ticks"]["16:30:00"][0]["event_kind"].startswith("PREWARM")
    event, trace = world["ticks"]["16:32:30"]
    assert trace["plan_before"] is None and trace["registry"]["bootstrapped"] is False
    assert trace["route"] == "SCAN" and event["primary_call_count"] == 1


@pytest.mark.parametrize("lane", [DISARMED, REFUSING])
def test_completed_3m_close_beyond_the_stop_retires_the_invalidation(tmp_path_factory, lane):
    control = run(tmp_path_factory, "STOP_3M_CONTROL", lane)
    _published(control)
    _accepted(control, "16:33:30", lane)
    world = run(tmp_path_factory, "STOP_3M_CLOSE", lane)
    _published(world)
    _refused(world, "16:33:30", "invalidation_id_unknown")


# -- changed environment lineage, Draw and final quote: instrumented in-process --

@contextlib.contextmanager
def _during_trigger(flag):
    from broker.topstepx_production_loop import ProductionLoop
    original = ProductionLoop.handle_pending_conditional_wake

    def wrapped(self):
        flag["on"] = True
        try:
            return original(self)
        finally:
            flag["on"] = False
    ProductionLoop.handle_pending_conditional_wake = wrapped
    try:
        yield
    finally:
        ProductionLoop.handle_pending_conditional_wake = original


def _brain_fingerprint_changes():
    """The Brain contract fingerprint differs at the trigger's plan revalidation only."""
    from ai_brain import production_model as PM
    from broker import conditional_plan_authority as CPA
    original, validate = PM.brain_contract_fingerprint, CPA.validate
    flag = {"on": False}

    def revalidate(**kwargs):
        flag["on"] = True
        try:
            return validate(**kwargs)
        finally:
            flag["on"] = False

    @contextlib.contextmanager
    def ctx():
        PM.brain_contract_fingerprint = lambda: original() + (":CHANGED" if flag["on"] else "")
        CPA.validate = revalidate
        try:
            yield
        finally:
            PM.brain_contract_fingerprint, CPA.validate = original, validate
    return ctx


def _draw_changes():
    import broker.topstepx_production_loop as PL
    flag, original = {"on": False}, PL.scan_participation_authority

    def changed(scan):
        draw = original(scan)
        if flag["on"] and isinstance(draw, dict):
            draw = {**draw, "campaign_episode_id": str(draw.get("campaign_episode_id")) + ":CHANGED"}
        return draw

    @contextlib.contextmanager
    def ctx():
        PL.scan_participation_authority = changed
        try:
            with _during_trigger(flag):
                yield
        finally:
            PL.scan_participation_authority = original
    return ctx


def _final_quote_moves(bid, ask):
    """A sided quote that arrives between the trigger scan and the runner's final capture."""
    from broker.topstepx_execution_runner import ExecutionRunner
    original, built = ExecutionRunner._capture_final_executable_entry, {}
    build = DR.build_organism

    def capture(self, candidate_snapshot, market):
        built["organism"].venue.market_hub.emit("GatewayQuote", [self.contract.id, {"bestBid": bid, "bestAsk": ask}])
        return original(self, candidate_snapshot, market)

    def remember(**kwargs):
        built["organism"] = build(**kwargs)
        return built["organism"]

    @contextlib.contextmanager
    def ctx():
        ExecutionRunner._capture_final_executable_entry = capture
        DR.build_organism = remember
        try:
            yield
        finally:
            ExecutionRunner._capture_final_executable_entry = original
            DR.build_organism = build
    return ctx


@pytest.mark.parametrize("lane", [DISARMED, REFUSING])
def test_changed_brain_fingerprint_refuses_the_trigger(tmp_path_factory, lane):
    _accepted(run(tmp_path_factory, "HEALTHY", lane), "16:32:30", lane)
    world = run(tmp_path_factory, "HEALTHY", lane, instrument=_brain_fingerprint_changes(), tag="brainfp")
    _published(world)
    # The sealed plan wrapper no longer verifies, so the current-phase Lifecycle refusal stands; the
    # wrapper's own reason is the decisive cause carried in the refusal detail.
    _, trace = _refused(world, "16:32:30", "campaign_lifecycle_refused")
    assert "conditional_plan_environment_lineage_changed" in _refusal_detail(trace)


def test_changed_draw_refuses_the_trigger(tmp_path_factory):
    _accepted(run(tmp_path_factory, "HEALTHY", DISARMED), "16:32:30", DISARMED)
    world = run(tmp_path_factory, "HEALTHY", DISARMED, instrument=_draw_changes(), tag="draw")
    _published(world)
    _, trace = _refused(world, "16:32:30", "campaign_lifecycle_refused")
    assert "conditional_plan_campaign_draw_changed_or_unavailable" in _refusal_detail(trace), _refusal_detail(trace)


def test_final_quote_moved_outside_the_zone_is_refused_before_the_venue(tmp_path_factory):
    control = run(tmp_path_factory, "HEALTHY", REFUSING, instrument=_final_quote_moves(29514.0, 29514.25),
                  tag="final-inside")
    _accepted(control, "16:32:30", REFUSING)
    world = run(tmp_path_factory, "HEALTHY", REFUSING, instrument=_final_quote_moves(29519.0, 29519.25),
                tag="final-outside")
    event, trace = _triggered(world, "16:32:30")
    economics = trace["final_quote_economics"]
    assert economics["decision"] == "REFUSE" and economics["final_entry_reference"] == 29519.0
    assert economics["refusal_reason"].startswith("conditional_plan_final_quote")
    assert trace["venue_writes"] == [] and event["boundary"] == "FINAL_QUOTE"


# -- lane and tick guards --------------------------------------------------------

def test_refusing_venue_lane_is_never_available_to_mode_c(tmp_path):
    class Live:
        origin, fixture_digest = "CURRENT_EXTERNAL", None
    corpus = _corpus(tmp_path, "HEALTHY")
    with pytest.raises(C.ContractError) as err:
        DR.run_offline(corpus_path=corpus, session_id=CP.SESSION, out_root=tmp_path / "run", ecu=False,
                       trajectory_id="S5-M3-C", ticks=_ticks(corpus, "HEALTHY"), quote_policy="CONSTRUCTED",
                       venue_lane=REFUSING, responder=Live())
    assert err.value.code == "REFUSING_VENUE_LANE_MODE_C"
    with pytest.raises(C.ContractError) as err:
        DR.run_offline(corpus_path=corpus, session_id=CP.SESSION, out_root=tmp_path / "run2", ecu=False,
                       trajectory_id="S5-M3-X", ticks=_ticks(corpus, "HEALTHY"), quote_policy="CONSTRUCTED",
                       venue_lane="LIVE", responder=G.ScriptedResponder(lambda r: None, fixture_digest="x"))
    assert err.value.code == "VENUE_LANE_UNKNOWN"
    doc = json.loads((ROOT / "src/recognition_validation/examples/current_brain_disabled.json").read_text())
    assert doc["mode"] == "C"
    C.validate(doc)
    with pytest.raises(C.ContractError) as err:
        C.validate({**doc, "venue_lane": REFUSING})
    assert err.value.code == "REFUSING_VENUE_LANE_MODE_C"


def test_quote_wake_needs_an_explicit_quote_stream(tmp_path):
    corpus = K.build_constructed_corpus(tmp_path / "corpus", session_id=CP.SESSION, contract_id=CP.CONTRACT,
                                        market_date="2026-08-19", tape=W._tape(W._HEALTHY),
                                        warmup_end="2026-08-19T15:30:00+00:00", notes="no quotes",
                                        sealed_at="2026-10-17T00:00:00Z")
    ticks = [DR.Tick(0, DR.utc(DAY + "15:31:00Z"), "SCAN"), DR.Tick(1, DR.utc(DAY + "15:31:30Z"), "QUOTE_WAKE")]
    with pytest.raises(C.ContractError) as err:
        DR.run_offline(corpus_path=corpus, session_id=CP.SESSION, out_root=tmp_path / "run", ecu=False,
                       trajectory_id="S5-M3-Q", ticks=ticks, quote_policy="CONSTRUCTED",
                       responder=G.ScriptedResponder(lambda r: None, fixture_digest="x"))
    assert err.value.code == "QUOTE_WAKE_WITHOUT_QUOTE_STREAM"
    with pytest.raises(C.ContractError) as err:
        DR.run_offline(corpus_path=corpus, session_id=CP.SESSION, out_root=tmp_path / "run2", ecu=False,
                       trajectory_id="S5-M3-T", ticks=[DR.Tick(0, DR.utc(DAY + "15:31:00Z"), "FILL")],
                       responder=G.ScriptedResponder(lambda r: None, fixture_digest="x"))
    assert err.value.code == "TICK_ADAPTER_UNAVAILABLE"


def test_venue_write_is_an_offline_violation_only_in_the_disarmed_lane():
    for lane, expected in ((DISARMED, True), (REFUSING, False), (None, True)):
        manifest = {"events": 0, "venue_writes": ["place_order(CONSTRUCTED)"], "network_attempts": []}
        if lane:
            manifest["venue_lane"] = lane
        result = RP.build_result(document_id="S5-M3-RESULT", run_digest="0" * 64, mode="B", scored=[],
                                 manifest=manifest, artifact_refs=[], missing_prerequisites=[])
        assert ("VENUE_WRITE_OFFLINE" in json.dumps(result)) is expected


# -- the CLI runs the refusing lane in a fresh child -----------------------------

def test_cli_child_runs_the_refusing_lane_to_final_quote(tmp_path):
    corpus_path = _corpus(tmp_path, "HEALTHY")
    corpus = K.load_corpus(corpus_path)
    world = {"corpus_path": corpus_path, "digest": corpus.digest}
    run_path = SCLI._run_doc(world, tmp_path / "m3.run.json", ecu=False, trajectory_id="S5-M3-CLI",
                             venue_lane=REFUSING)
    doc = json.loads(run_path.read_text())
    schedule_path = run_path.parent / doc["schedule_ref"]["path"]
    schedule = json.loads(schedule_path.read_text())
    schedule.update(ticks=[{"session_id": CP.SESSION, "ordinal": t.ordinal, "decision_time_utc": t.decision_time.isoformat(),
                            "kind": t.kind, "source_ref": None} for t in _ticks(corpus_path, "HEALTHY")], seal=None)
    schedule["seal"] = {"sha256": C.seal_digest(schedule), "sealed_at": "2026-10-17T00:00:00Z", "sealer_ref": "TEST_ONLY"}
    data = C.canonical(schedule)
    schedule_path.write_bytes(data)
    doc["schedule_ref"] = {"path": schedule_path.name, "sha256": C.sha256_hex(data), "bytes": len(data),
                           "origin": "CONSTRUCTED"}
    C.validate(doc)
    run_path.write_text(json.dumps(doc))
    script = tmp_path / "watching_script.py"
    script.write_text("import sys\nfrom datetime import datetime, timedelta\n"
                      f"sys.path.insert(0, {str(ROOT / 'tests')!r})\n"
                      "import test_recognition_current_path as CP\n"
                      "_inner, _state = CP._script()\n"
                      "def script(request):\n"
                      "    reply = _inner(request)\n"
                      "    if reply and reply.get('current_action') == 'propose_entry':\n"
                      "        at = datetime.fromisoformat(request['decision_time'])\n"
                      "        reply = {**reply, 'current_action': 'watching',\n"
                      "                 'plan_expires_at': (at + timedelta(seconds=1800)).isoformat()}\n"
                      "    return reply\n")
    code = CLI.main(["run", "--mode", "B", "--run", str(run_path), "--corpus", str(corpus_path),
                     "--out", str(tmp_path / "out"), "--script", str(script)])
    evidence = tmp_path / "out" / "evidence"
    assert code == 0, (evidence / CH.STATUS_FILE).read_text()
    manifest = RP.read_manifest(evidence)
    assert manifest["process_isolation"]["kind"] == "FRESH_CHILD" and manifest["venue_lane"] == REFUSING
    _accepted({"ticks": _traces(evidence)}, "16:32:30", REFUSING)
    child_exit = json.loads((evidence / CH.EXIT_FILE).read_text())
    assert child_exit["network_attempts"] == [] and child_exit["status"] == "RUN_COMPLETE"
