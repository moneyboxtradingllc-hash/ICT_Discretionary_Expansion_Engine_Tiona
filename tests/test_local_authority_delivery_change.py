"""LOCAL-AUTHORITY-20261026 Mission 2 -- delivery change and retained support.

Tape: the archived PROD-20261023-C1 settled 1m bars (Friday, UTC below; ET is
UTC-4). Two profile-gated local proofs, both dormant in a default cycle:

* DELIVERY_CHANGE_CONFIRMED (family `raid_reclaim_delivery_change`). The 5m
  12:00 ET rejected buy-side raid is associated with the still-INTACT 5m
  29294.5 high (registered 11:59 ET). The bullish local leg fails on the 1m
  12:23 ET bar (knowable 12:24). The settled 5m 12:20 bucket then closes
  through the prior bullish run's first open (body-open break) and prints the
  5m bearish structure break; both are knowable only at 12:25 ET. At the 12:24
  ET open cutoff (16:24 UTC) the composite completes AFTER the failure settled.
* Retained support. At 13:15 ET (17:15 UTC) a native bearish generation (1m
  raid 13:09 after the 13:08 bullish failure, 1m structure 13:15) rests on
  nothing; the exact INTACT raid-associated 5m 29294.5 high is revalidated as
  its support with zero ladder credit, and withdrawn when the leg is contested.

Mirrored cases are CONSTRUCTED (price mirror), never historical sessions.
Nothing here is an entry, a fill, model evidence or historical intent.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pytest

import local_authority_loop as H
import test_protected_structure_continuity as P
from ai_brain.narrative_continuity import _transfer_proof, build_narrative_continuity
from live_scan.production_scan_cycle import ProductionScanCycle
from market_data import campaign_scope as CS
from market_data import local_authority as LA

RUNTIME_DIRS = ("OCCURRENCE_LEDGER_DIR", "AI_BRAIN_DIR", "AI_RETRIEVAL_DIR",
                "REPLAY_SESSIONS_DIR")
DC_CUTOFF = "16:24"
RS_CUTOFF = "17:15"
LIFE_HIGH = 29294.5


def _isolate(monkeypatch, root):
    for key in RUNTIME_DIRS:
        monkeypatch.setenv(key, str(root / key))


def _scan(cycle, tape, hm):
    cut = P._cut(hm)
    bars = [b for b in tape if b["timestamp"] <= cut][-300:]
    return cycle.scan(bars, now=datetime.fromisoformat(cut) + timedelta(minutes=1),
                      invoke_brain=False), bars


def _inputs(cycle, scan, bars):
    snap = scan["snapshot"]
    path = snap["active_path_state"]
    return {"path": copy.deepcopy(path), "facts": copy.deepcopy(snap["campaign_premise_shadow"]),
            "ledger_rows": copy.deepcopy(cycle._current_chronology_occurrences()),
            "settled_1m": copy.deepcopy(bars), "cutoff": LA._instant(snap["timestamp"]),
            "contract_id": P.C, "market_session": path.get("session"),
            "history_revision": cycle._history.revision}


def _events(cycle, snap):
    diag = cycle.local_authority.diagnostics
    if diag and diag[-1].get("cutoff") == LA._instant(snap["timestamp"]):
        return [e["kind"] for e in diag[-1]["events"]]
    return []


def _walk(cycle, tape, start, end, inspect=None):
    rows = {}
    for hm in P._minutes(start, end):
        scan, bars = _scan(cycle, tape, hm)
        snap = scan["snapshot"]
        path = snap["active_path_state"]
        frm = {"bullish": "bearish", "bearish": "bullish"}.get(path.get("owner"))
        rows[hm] = {"path": copy.deepcopy(path),
                    "route": copy.deepcopy(LA.authenticated_local_route(path, snap)),
                    "proof": copy.deepcopy(_transfer_proof(path, frm, path.get("owner"),
                                                           snapshot=snap)) if frm else None,
                    "events": _events(cycle, snap) if cycle.local_authority.enabled else []}
        if inspect:
            inspect(hm, cycle, scan, bars)
    return rows


def _cycle(name, profile=None):
    kwargs = {} if profile is None else {"local_authority_profile": profile}
    return ProductionScanCycle(symbol="MNQ", contract_id=P.C, session_id=name, **kwargs)


@pytest.fixture(scope="module")
def friday(tmp_path_factory):
    captured = {}

    def inspect(hm, cycle, scan, bars):
        snap = scan["snapshot"]
        path = snap["active_path_state"]
        if hm == DC_CUTOFF:
            captured["inputs"] = _inputs(cycle, scan, bars)
            captured["packet"] = copy.deepcopy(cycle.local_authority._generation)
            captured["ladder"] = list(cycle._active_path.ladder)
            captured["ledger_types"] = sorted({r.get("event_type") for r in
                                               cycle._current_chronology_occurrences()})
        if hm == "16:25":
            captured["snapshot"] = snap
            captured["copied"] = _transfer_proof(copy.deepcopy(path), "bullish", "bearish",
                                                 snapshot=copy.deepcopy(snap))
            captured["continuity_live"] = build_narrative_continuity(snap, {})
            cycle.local_authority.revoke("test_revocation")
            captured["revoked_proof"] = _transfer_proof(path, "bullish", "bearish",
                                                        snapshot=snap)
            captured["revoked_continuity"] = build_narrative_continuity(snap, {})
            again, _ = _scan(cycle, P.TAPE, hm)          # same cutoff: re-derived once
            captured["duplicate_events"] = _events(cycle, again["snapshot"])
            captured["duplicate_route"] = LA.authenticated_local_route(
                again["snapshot"]["active_path_state"], again["snapshot"])

    with pytest.MonkeyPatch.context() as m:
        _isolate(m, tmp_path_factory.mktemp("m2_default"))
        default_rows = _walk(_cycle("M2-DEFAULT"), P.TAPE, "16:10", "16:50")
    with pytest.MonkeyPatch.context() as m:
        _isolate(m, tmp_path_factory.mktemp("m2_offline"))
        offline = _cycle("M2-OFFLINE", LA.OFFLINE_TEST_PROFILE_V1)
        offline_rows = _walk(offline, P.TAPE, "16:10", "16:50", inspect)
    yield {"default": default_rows, "offline": offline_rows, "captured": captured}


@pytest.fixture(scope="module")
def retained(tmp_path_factory):
    captured = {}

    def inspect(hm, cycle, scan, bars):
        if hm == RS_CUTOFF:
            captured["inputs"] = _inputs(cycle, scan, bars)
            # The published path already carries the adoption; the producer
            # derived it from the same path with no support yet.
            captured["inputs"]["path"]["load_bearing_structure"] = None
            captured["support"] = copy.deepcopy(cycle.local_authority._support)
            captured["ladder"] = list(cycle._active_path.ladder)
            captured["snapshot"] = scan["snapshot"]

    with pytest.MonkeyPatch.context() as m:
        _isolate(m, tmp_path_factory.mktemp("m2_rs_default"))
        default_rows = _walk(_cycle("M2-RS-DEFAULT"), P.TAPE, "17:05", "17:42")
    with pytest.MonkeyPatch.context() as m:
        _isolate(m, tmp_path_factory.mktemp("m2_rs_offline"))
        rows = _walk(_cycle("M2-RS", LA.OFFLINE_RETAINED_SUPPORT_TEST_PROFILE_V1),
                     P.TAPE, "17:05", "17:42", inspect)
    yield {"default": default_rows, "offline": rows, "captured": captured}


@pytest.fixture(scope="module")
def mirror(tmp_path_factory):
    with pytest.MonkeyPatch.context() as m:
        _isolate(m, tmp_path_factory.mktemp("m2_mirror"))
        rows = _walk(_cycle("M2-MIRROR", LA.OFFLINE_TEST_PROFILE_V1),
                     H.mirrored_tape(P.TAPE), "16:10", "16:30")
    yield rows


def _origin(path):
    return (path or {}).get("origin") or {}


def _lb(path):
    return (path or {}).get("load_bearing_structure") or {}


# ── profiles ─────────────────────────────────────────────────────────────────
def test_component_profile_is_an_exact_object_and_disabled_otherwise(monkeypatch):
    for key in LA._EXECUTION_SWITCHES:
        monkeypatch.delenv(key, raising=False)
    rs = LA.OFFLINE_RETAINED_SUPPORT_TEST_PROFILE_V1
    assert LA.resolve_profile(rs) == (rs, None)
    assert (rs.member_order_witness, rs.retained_support, rs.delivery_change) == (True, True, False)
    mo = LA.OFFLINE_MEMBER_ORDER_TEST_PROFILE_V1
    assert LA.resolve_profile(mo) == (mo, None)
    assert (mo.member_order_witness, mo.retained_support, mo.delivery_change) == (True, False, False)
    assert len({p.version for p in LA._OFFLINE_PROFILES}) == len(LA._OFFLINE_PROFILES) == 3
    for value in (copy.deepcopy(rs), rs.version, LA.LocalAuthorityProfile(**vars(rs))):
        assert LA.resolve_profile(value) == (LA.DISABLED, "unrecognized_profile_disabled")
    monkeypatch.setenv("TOPSTEPX_ARM_ORDERS", "true")
    assert LA.resolve_profile(rs) == (LA.DISABLED, "offline_profile_refused_execution_environment")


# ── default-off: the accepted source is unchanged ────────────────────────────
def test_default_cycle_never_carries_or_admits_a_local_refinement(friday, retained):
    for rows in (friday["default"], retained["default"]):
        for hm, row in rows.items():
            assert LA.local_refinements(row["path"]) == {"delivery_change": None,
                                                         "retained_support": None}, hm
            assert row["route"] == {} and "local_authority_route" not in (row["proof"] or {})
    # 12:24-12:50 ET: the default path never carries a bearish owner at all.
    assert all(friday["default"][hm]["path"]["owner"] != "bearish"
               for hm in H.minutes("16:24", "16:44"))
    # 13:15 ET: the native bearish generation exists but rests on nothing.
    row = retained["default"][RS_CUTOFF]
    assert row["path"]["owner"] == "bearish" and _lb(row["path"]) == {}
    assert row["proof"] is None


def _without_witness(path):
    path = copy.deepcopy(path)
    if isinstance(path.get("origin"), dict):
        path["origin"].pop("member_order_witness", None)   # Mission 1's only addition
    return path


def test_offline_equals_default_until_the_first_local_adoption(friday):
    for hm in H.minutes("16:10", "16:23"):
        assert (_without_witness(friday["offline"][hm]["path"])
                == friday["default"][hm]["path"]), hm


# ── DELIVERY_CHANGE_CONFIRMED: the 12:24 ET conjunction ──────────────────────
def test_under_the_full_profile_no_bullish_successor_follows_the_12_23_failure(friday):
    # The same-minute crossing never proves a bullish successor; the settled
    # composite instead makes the bearish delivery change the 12:24 ET owner.
    for hm in H.minutes("16:24", "16:30"):
        path = friday["offline"][hm]["path"]
        assert path["owner"] == "bearish", hm
        assert "member_order_witness" not in _origin(path)


def test_earlier_prefixes_do_not_complete_the_conjunction(friday):
    events = {hm: friday["offline"][hm]["events"] for hm in H.minutes("16:10", "16:23")}
    assert all("delivery_change_adopted" not in e for e in events.values())
    assert friday["offline"]["16:23"]["path"]["owner"] == "none"


def test_the_composite_is_adopted_at_the_first_settled_cutoff(friday):
    row = friday["offline"][DC_CUTOFF]
    packet = friday["captured"]["packet"]
    assert row["events"] == ["delivery_change_adopted"]
    assert row["path"]["owner"] == "bearish" and row["path"]["status"] == "active"
    assert packet["failure"]["owner"] == "bullish"
    assert packet["failure"]["source_bar_time"] == "2026-10-23T16:23:00+00:00"
    assert packet["failure"]["available_at"] == "2026-10-23T16:24:00+00:00"
    assert packet["earlier_raid"] == {
        "occurrence_id": "LIQUIDITY_SWEEP:CON.F.US.MNQ.Z26:5m:2026-10-23T16:00:00+00:00",
        "source_tf": "5m", "source_bar_time": "2026-10-23T16:00:00+00:00",
        "sweep_direction": "above_high", "swept_level": LIFE_HIGH,
        "association_observed_at": "2026-10-23T16:04:00+00:00"}
    assert packet["life"]["swing_id"] == "5m:swing_high:29294.5"
    assert packet["life"]["registered_at"] == "2026-10-23T15:59:00+00:00"
    body = packet["body_confirmation"]
    assert (body["timeframe"], body["break_open_time"], body["available_at"]) == (
        "5m", "2026-10-23T16:20:00+00:00", "2026-10-23T16:25:00+00:00")
    assert body["run"]["anchor_open"] == 29231.75 and body["break_close"] < 29231.75
    assert packet["structure"]["available_at"] == "2026-10-23T16:25:00+00:00"
    assert packet["completed_at"] == "2026-10-23T16:25:00+00:00"
    assert packet["market_proof_id"] == row["route"]["delivery_change"]


def test_the_composite_is_a_delivery_change_never_a_fictitious_raid(friday):
    origin = _origin(friday["offline"][DC_CUTOFF]["path"])
    assert origin["event"] == "delivery_change_confirmed"
    assert origin["proof_family"] == "raid_reclaim_delivery_change"
    assert origin["occurrence_id"].startswith("DELIVERY_CHANGE_CONFIRMED:")
    # Every native identity is kept, at its own source time.
    assert origin["earlier_raid"]["source_bar_time"] == "2026-10-23T16:00:00+00:00"
    assert origin["source_bar_time"] == "2026-10-23T16:20:00+00:00"
    assert origin["settled_edge_time"] == "2026-10-23T16:25:00+00:00"
    assert origin["failure_id"].startswith("PROTECTED_SWING_VIOLATED:")
    # Nothing is appended to the canonical occurrence history.
    assert not any("DELIVERY_CHANGE" in t or "BODY_OPEN" in t
                   for t in friday["captured"]["ledger_types"])


def test_support_is_the_existing_life_with_zero_ladder_credit(friday):
    support = _lb(friday["offline"][DC_CUTOFF]["path"])
    assert support["level"] == LIFE_HIGH and support["timeframe"] == "5m"
    assert support["registered_at"] == "2026-10-23T15:59:00+00:00"     # not re-registered
    assert support["adoption"]["ladder_credit"] == 0
    assert friday["captured"]["ladder"] == []
    assert friday["offline"][DC_CUTOFF]["path"]["progression"]["favourable_ladder"] == []


def test_every_continuing_cutoff_revalidates_the_same_market_proof(friday):
    proof_id = friday["captured"]["packet"]["market_proof_id"]
    for hm in H.minutes("16:26", "16:45"):
        row = friday["offline"][hm]
        assert row["route"]["delivery_change"] == proof_id, hm
        assert row["proof"]["local_authority_route"]["delivery_change"] == proof_id
        assert "delivery_change_withdrawn" not in row["events"]
    # The adopted generation later dies natively; nothing survives it.
    assert friday["offline"]["16:46"]["events"] == ["delivery_change_ended_natively"]
    assert friday["offline"]["16:46"]["route"] == {}


def test_copied_revoked_and_duplicate_authority(friday):
    cap = friday["captured"]
    assert cap["copied"] is None
    # No authored prior campaign here, so the verified local proof establishes.
    assert cap["continuity_live"]["control_state"] in ("confirmed_transfer",
                                                       "campaign_established")
    assert cap["continuity_live"]["dominant_direction"] == "bearish"
    assert cap["revoked_proof"] is None
    # Incumbency cannot launder a revoked proof into `incumbent_intact`.
    assert cap["revoked_continuity"]["control_state"] == "unresolved"
    assert cap["revoked_continuity"]["dominant_direction"] is None
    # Same-cutoff re-assembly republishes; it never mints a second adoption.
    assert "delivery_change_adopted" not in cap["duplicate_events"]
    assert cap["duplicate_route"]["delivery_change"] == cap["packet"]["market_proof_id"]


# ── delivery-change refusal families (positive control first) ────────────────
def _packet(inputs, **change):
    args = copy.deepcopy(inputs)
    args.update(change)
    return LA.delivery_change_packet(**args)


def _with_life(inputs, edit):
    facts = copy.deepcopy(inputs["facts"])
    for life in facts["lives"]:
        if life["swing_id"] == "5m:swing_high:29294.5":
            edit(life)
    return facts


def _bars(inputs, edit):
    bars = copy.deepcopy(inputs["settled_1m"])
    edit(bars)
    return bars


def _member(bars, hm):
    return next(b for b in bars if b["timestamp"] == P._cut(hm))


def _set_close(bar, close, *, low=None):
    """Move a settled member's close, keeping the bar internally consistent."""
    bar["close"] = close
    bar["high"] = max(bar["high"], bar["open"], close)
    bar["low"] = min(bar["low"] if low is None else low, bar["open"], close)


def _remove_failure(path):
    path["last_invalidated"] = None


def _same_direction_failure(path):
    path["last_invalidated"]["owner"] = "bearish"


def _future_failure(path):
    path["last_invalidated"].update(source_bar_time="2026-10-23T16:25:00+00:00",
                                    settled_edge_time=None)


def _late_failure(path):
    # A failure known only after the confirmation completed is the wrong generation.
    path["last_invalidated"].update(source_bar_time="2026-10-23T16:24:00+00:00")


PACKET_ATTACKS = {
    "matched_retracement_no_failure": (lambda i: {"path": {**i["path"], "last_invalidated": None}},
                                       "incumbent_failure_unestablished"),
    "failure_of_the_same_direction": (
        lambda i: {"path": _edit(i["path"], _same_direction_failure)},
        "no_exact_current_supporting_life_and_raid"),
    "failure_not_yet_settled": (lambda i: {"path": _edit(i["path"], _future_failure)},
                                "incumbent_failure_not_settled"),
    "confirmation_not_after_failure": (lambda i: {"path": _edit(i["path"], _late_failure)},
                                       "confirmation_not_after_settled_failure"),
    "forming_bucket_one_minute_earlier": (
        lambda i: {"cutoff": "2026-10-23T16:23:00+00:00",
                   "facts": {**i["facts"], "cutoff": "2026-10-23T16:23:00+00:00"}},
        None),
    "equal_close_at_the_anchor": (
        lambda i: {"settled_1m": _bars(i, lambda b: _set_close(_member(b, "16:24"), 29231.75))},
        None),
    "wick_only_breach": (
        lambda i: {"settled_1m": _bars(i, lambda b: _set_close(_member(b, "16:24"), 29240.0,
                                                                low=29200.0))},
        None),
    "gap_inside_the_run": (
        lambda i: {"settled_1m": _bars(i, lambda b: b.remove(_member(b, "15:52")))},
        "body_open_break_unavailable:tape_gap"),
    "duplicate_member": (
        lambda i: {"settled_1m": _bars(i, lambda b: b.append(dict(_member(b, "16:10"))))},
        "body_open_break_unavailable:tape_unreadable"),
    "no_structural_break": (
        lambda i: {"ledger_rows": [r for r in i["ledger_rows"]
                                   if r.get("event_type") != "STRUCTURE_BREAK"]},
        "no_settled_structural_break"),
    "structure_of_the_wrong_side": (
        lambda i: {"ledger_rows": [dict(r, direction="bullish")
                                   if r.get("event_type") == "STRUCTURE_BREAK" else r
                                   for r in i["ledger_rows"]]},
        "no_settled_structural_break"),
    "missing_raid_association": (
        lambda i: {"facts": _with_life(i, lambda l: l.update(sweep_occurrence_ids=[]))},
        "no_exact_current_supporting_life_and_raid"),
    "certificate_failed": (
        lambda i: {"facts": _with_life(i, lambda l: l["certificate"].update(status="FAILED"))},
        "no_exact_current_supporting_life_and_raid"),
    "life_replaced_not_eligible": (
        lambda i: {"facts": _with_life(i, lambda l: l.update(eligible_for_new_selection=False))},
        "no_exact_current_supporting_life_and_raid"),
    "same_price_different_life": (
        lambda i: {"facts": _with_life(i, lambda l: l.update(swing_id="5m:swing_high:other"))},
        "no_exact_current_supporting_life_and_raid"),
    "stale_registration": (
        lambda i: {"facts": _with_life(i, lambda l: l.update(
            registered_at="2026-10-23T15:54:00+00:00"))},
        "no_exact_current_supporting_life_and_raid"),
    "non_campaign_timeframe_life": (
        lambda i: {"facts": _with_life(i, lambda l: l.update(source_tf="3m"))},
        "no_exact_current_supporting_life_and_raid"),
    "changed_contract": (lambda i: {"contract_id": "CON.F.US.MNQ.H27"},
                         "premise_facts_not_current"),
    "changed_session": (lambda i: {"market_session": "20261024"}, "premise_facts_not_current"),
    "changed_revision": (lambda i: {"history_revision": i["history_revision"] + 1},
                         "premise_facts_not_current"),
    "raid_observed_in_the_future": (
        lambda i: {"ledger_rows": [dict(r, observed_at="2026-10-23T16:30:00+00:00",
                                        event_time="2026-10-23T16:30:00+00:00")
                                   if str(r.get("occurrence_id", "")).endswith("16:00:00+00:00")
                                   and r.get("event_type") == "LIQUIDITY_SWEEP" else r
                                   for r in i["ledger_rows"]]},
        None),
    "rolling_eviction_of_the_run": (
        lambda i: {"settled_1m": [b for b in i["settled_1m"]
                                  if b["timestamp"] >= P._cut("15:56")]},
        None),
}


def _edit(path, fn):
    out = copy.deepcopy(path)
    fn(out)
    return out


def test_unaltered_inputs_reproduce_the_live_packet(friday):
    packet, reason = _packet(friday["captured"]["inputs"])
    assert reason is None and packet == friday["captured"]["packet"]


@pytest.mark.parametrize("attack", sorted(PACKET_ATTACKS))
def test_each_broken_relation_refuses_the_delivery_change(friday, attack):
    change, expected = PACKET_ATTACKS[attack]
    packet, reason = _packet(friday["captured"]["inputs"],
                             **change(friday["captured"]["inputs"]))
    assert packet is None and reason
    if expected is not None:
        assert reason == expected


@pytest.mark.parametrize("close,low", [(29231.75, None), (29240.0, 29200.0)],
                         ids=["equal_close_at_the_anchor", "wick_only_breach"])
def test_the_cited_raid_body_break_is_pending_without_a_strict_close(friday, close, low):
    inputs = friday["captured"]["inputs"]
    bars = _bars(inputs, lambda b: _set_close(_member(b, "16:24"), close, low=low))
    out = LA.body_open_break(bars, minutes=5, direction="bearish",
                             extreme_at="2026-10-23T16:00:00+00:00",
                             settled_through="2026-10-23T16:25:00+00:00", contract=P.C)
    assert (out["status"], out["reason"]) == ("PENDING", "no_settled_break")
    healthy = LA.body_open_break(inputs["settled_1m"], minutes=5, direction="bearish",
                                 extreme_at="2026-10-23T16:00:00+00:00",
                                 settled_through="2026-10-23T16:25:00+00:00", contract=P.C)
    assert healthy["status"] == "CONFIRMED"


def test_a_cited_generation_withdraws_when_its_graph_changes(friday):
    inputs, packet = friday["captured"]["inputs"], friday["captured"]["packet"]
    same, _ = _packet(inputs, cited=packet)
    assert same == packet
    other = copy.deepcopy(packet)
    other["structure"]["occurrence_id"] = "STRUCTURE_BREAK:elsewhere"
    assert _packet(inputs, cited=other) == (None, "cited_graph_changed")


# ── settled body-open break: both directions, 5m AND 15m ─────────────────────
def _constructed_buckets(minutes, closes, start="2026-10-23T14:00:00+00:00"):
    """CONSTRUCTED settled 1m bars whose `minutes` buckets open/close as listed."""
    bars, t = [], datetime.fromisoformat(start)
    for open_, close in closes:
        for i in range(minutes):
            o = open_ if i == 0 else close
            bars.append({"timestamp": t.isoformat(), "open": o, "close": close,
                         "high": max(o, close) + .25, "low": min(o, close) - .25})
            t += timedelta(minutes=1)
    return bars


@pytest.mark.parametrize("minutes", [5, 15])
@pytest.mark.parametrize("direction", ["bearish", "bullish"])
def test_body_open_break_on_campaign_timeframes(minutes, direction):
    # A bucket of the other delivery proves where the run starts.
    up = [(99.5, 99.0), (100.0, 101.0), (101.0, 102.0), (102.0, 104.0), (104.0, 103.0),
          (103.0, 99.5)]
    if direction == "bullish":
        up = [(200 - o, 200 - c) for o, c in up]
    bars = _constructed_buckets(minutes, up)
    extreme = datetime.fromisoformat("2026-10-23T14:00:00+00:00") + timedelta(minutes=3 * minutes)
    edge = datetime.fromisoformat(bars[-1]["timestamp"]) + timedelta(minutes=1)
    out = LA.body_open_break(bars, minutes=minutes, direction=direction,
                             extreme_at=extreme.isoformat(), settled_through=edge.isoformat(),
                             contract=P.C)
    assert out["status"] == "CONFIRMED" and out["timeframe"] == f"{minutes}m"
    assert out["run"]["anchor_open"] == (100.0 if direction == "bearish" else 100.0)
    assert out["event"]["available_at"] == edge.isoformat()
    # The confirming bucket still forming: nothing is confirmed.
    early = LA.body_open_break(bars[:-1], minutes=minutes, direction=direction,
                               extreme_at=extreme.isoformat(),
                               settled_through=(edge - timedelta(minutes=1)).isoformat(),
                               contract=P.C)
    assert early["status"] == "PENDING"
    # Equal close at the anchor confirms nothing.
    level = 100.0
    flat = up[:-1] + [(up[-1][0], level)]
    # Without the bucket before the run, its true first open is unknown.
    unproved = LA.body_open_break(bars[minutes:], minutes=minutes, direction=direction,
                                  extreme_at=extreme.isoformat(),
                                  settled_through=edge.isoformat(), contract=P.C)
    assert (unproved["status"], unproved["reason"]) == ("UNAVAILABLE", "run_start_not_covered")
    equal = LA.body_open_break(_constructed_buckets(minutes, flat), minutes=minutes,
                               direction=direction, extreme_at=extreme.isoformat(),
                               settled_through=edge.isoformat(), contract=P.C)
    assert equal["status"] == "PENDING"


# ── the constructed mirror ───────────────────────────────────────────────────
def test_constructed_mirror_adopts_the_bullish_delivery_change(mirror):
    row = mirror[DC_CUTOFF]
    assert row["events"] == ["delivery_change_adopted"]
    assert row["path"]["owner"] == "bullish"
    origin = _origin(row["path"])
    assert origin["proof_family"] == "raid_reclaim_delivery_change"
    assert origin["earlier_raid"]["sweep_direction"] == "below_low"
    assert _lb(row["path"])["side"] == "low" and _lb(row["path"])["adoption"]["ladder_credit"] == 0
    assert row["proof"]["local_authority_route"]["route"] == "delivery_change"
    assert all("delivery_change_adopted" not in mirror[hm]["events"]
               for hm in H.minutes("16:10", "16:23"))


# ── retained support: the 13:15 ET high ──────────────────────────────────────
def test_retained_high_is_revalidated_as_support_only_by_the_full_proof(retained):
    row = retained["offline"][RS_CUTOFF]
    support = retained["captured"]["support"]
    assert row["events"] == ["retained_support_adopted"]
    assert row["path"]["owner"] == "bearish"
    assert _origin(row["path"])["proof_family"] == "rejected_raid_reclaim"   # native family
    assert _origin(row["path"])["source_bar_time"] == "2026-10-23T17:09:00+00:00"
    assert support["failure"]["owner"] == "bullish"
    assert support["failure"]["source_bar_time"] == "2026-10-23T17:08:00+00:00"
    assert support["life"]["swing_id"] == "5m:swing_high:29294.5"
    assert support["life"]["registered_at"] == "2026-10-23T15:59:00+00:00"  # birth precedes
    lb = _lb(row["path"])
    assert lb["level"] == LIFE_HIGH and lb["adoption"]["ladder_credit"] == 0
    assert retained["captured"]["ladder"] == []
    assert row["route"] == {"retained_support": support["adoption_id"], "route": "retained_support"}
    assert row["proof"]["local_authority_route"]["retained_support"] == support["adoption_id"]
    # Before 13:15 ET the leg is only forming; nothing is adopted.
    assert all("retained_support_adopted" not in retained["offline"][hm]["events"]
               for hm in H.minutes("17:05", "17:14"))


def test_retained_support_is_revalidated_and_withdrawn_on_contradiction(retained):
    adoption = retained["captured"]["support"]["adoption_id"]
    for hm in H.minutes("17:16", "17:40"):
        assert retained["offline"][hm]["route"].get("retained_support") == adoption, hm
    assert retained["offline"]["17:41"]["events"] == ["retained_support_withdrawn"]
    assert retained["offline"]["17:41"]["path"]["status"] == "contested"
    assert _lb(retained["offline"]["17:41"]["path"]) == {}
    assert retained["offline"]["17:41"]["route"] == {}


def _support(inputs, **change):
    args = copy.deepcopy(inputs)
    args.pop("settled_1m")
    args.update(change)
    return LA.retained_support_adoption(**args)


def _rs_life(inputs, edit):
    facts = copy.deepcopy(inputs["facts"])
    for life in facts["lives"]:
        if life["swing_id"] == "5m:swing_high:29294.5":
            edit(life)
    return facts


def _origin_before_failure(path):
    path["origin"]["source_bar_time"] = "2026-10-23T17:07:00+00:00"


def _no_later_progression(path):
    path["progression"]["latest_supporting_event"]["source_bar_time"] = "2026-10-23T17:09:00+00:00"


def _contradicted(path):
    path["transfer_evidence"]["opposing_structure_break"] = True


def _ambiguous_twin(inputs):
    """A second certified life registered at the same instant, with its own
    genuine raid association (the 11:55 ET raid re-associated to it)."""
    facts, rows = copy.deepcopy(inputs["facts"]), copy.deepcopy(inputs["ledger_rows"])
    life = next(l for l in facts["lives"] if l["swing_id"] == "5m:swing_high:29294.5")
    raid_id = "LIQUIDITY_SWEEP:CON.F.US.MNQ.Z26:5m:2026-10-23T15:55:00+00:00"
    twin = copy.deepcopy(life)
    twin.update(swing_id="5m:swing_high:29300", level=29300.0, sweep_occurrence_ids=[raid_id])
    life["sweep_occurrence_ids"] = [i for i in life["sweep_occurrence_ids"] if i != raid_id]
    facts["lives"].append(twin)
    for row in rows:
        if row.get("occurrence_id") == raid_id:
            row["swept_level"] = 29300.0
            row["protected_swing_lifetime"]["swing_id"] = twin["swing_id"]
    return {"facts": facts, "ledger_rows": rows}


SUPPORT_ATTACKS = {
    "no_failure": (lambda i: {"path": {**i["path"], "last_invalidated": None}},
                   "established_owner_or_failure_missing"),
    "origin_before_failure_without_witness": (
        lambda i: {"path": _edit(i["path"], _origin_before_failure)},
        "origin_not_post_failure_in_source_order"),
    "no_independent_later_progression": (
        lambda i: {"path": _edit(i["path"], _no_later_progression)},
        "no_independent_later_progression"),
    "new_owner_contradiction": (lambda i: {"path": _edit(i["path"], _contradicted)},
                                "new_owner_contradiction"),
    "violated_life": (lambda i: {"facts": _rs_life(i, lambda l: l["certificate"].update(
        status="FAILED"))}, "no_exact_current_associated_life"),
    "replaced_life": (lambda i: {"facts": _rs_life(i, lambda l: l.update(
        eligible_for_new_selection=False))}, "no_exact_current_associated_life"),
    "same_price_different_life": (lambda i: {"facts": _rs_life(i, lambda l: l.update(
        swing_id="5m:swing_high:other"))}, "no_exact_current_associated_life"),
    "stale_registration": (lambda i: {"facts": _rs_life(i, lambda l: l.update(
        registered_at="2026-10-23T15:54:00+00:00"))}, "no_exact_current_associated_life"),
    "missing_association": (lambda i: {"facts": _rs_life(i, lambda l: l.update(
        sweep_occurrence_ids=[]))}, "no_exact_current_associated_life"),
    "ambiguous_equal_registration": (_ambiguous_twin, "retained_support_ambiguous"),
    "changed_revision": (lambda i: {"history_revision": i["history_revision"] + 1},
                         "premise_facts_not_current"),
    "foreign_contract": (lambda i: {"contract_id": "CON.F.US.MNQ.H27"},
                         "premise_facts_not_current"),
}


def test_unaltered_inputs_reproduce_the_live_adoption(retained):
    adoption, reason = _support(retained["captured"]["inputs"])
    assert reason is None and adoption == retained["captured"]["support"]


@pytest.mark.parametrize("attack", sorted(SUPPORT_ATTACKS))
def test_each_broken_relation_refuses_retained_support(retained, attack):
    change, expected = SUPPORT_ATTACKS[attack]
    adoption, reason = _support(retained["captured"]["inputs"],
                                **change(retained["captured"]["inputs"]))
    assert adoption is None and reason
    if expected is not None:
        assert reason == expected


# ── scoped domain: neither new basis reaches D3-B ────────────────────────────
def _hypothetical_row(snapshot, supports, raid_time):
    """A TABLE/PREDICATE control: an unowned hypothetical B2/B3-passing row."""
    return {"supports": supports, "raids": [{"canonical_sweep_id": "HYPOTHETICAL",
                                             "event_time": raid_time,
                                             "association_observed_at": raid_time}]}


SCOPED_CASES = {"delivery_change": (LA.OFFLINE_TEST_PROFILE_V1, "16:10", "16:25"),
                "retained_support": (LA.OFFLINE_RETAINED_SUPPORT_TEST_PROFILE_V1,
                                     "17:05", "17:16")}


@pytest.mark.parametrize("case", sorted(SCOPED_CASES))
def test_scoped_proof_excludes_both_local_bases_even_with_a_b3_passing_raid(
        tmp_path, monkeypatch, case):
    profile, start, end = SCOPED_CASES[case]
    _isolate(monkeypatch, tmp_path)
    cycle = _cycle(f"M2-SCOPED-{case}", profile)
    for hm in H.minutes(start, end):
        scan, _ = _scan(cycle, P.TAPE, hm)
    snap = scan["snapshot"]                      # the CURRENT publication
    path = snap["active_path_state"]
    assert LA.local_refinements(path)[case] is not None
    row = _hypothetical_row(snap, "bearish", LA._instant(snap["timestamp"]))
    assert CS.campaign_scope_proof(snap, row) == (None, LA.LOCAL_ONLY_SCOPE_REASON)
    # Activated invariant break: without the explicit exclusion, an
    # implementation that authenticated the route inside B1 WOULD expand
    # scoped acceptance -- which is exactly why the domain is enforced here.
    import sys
    import ai_brain.narrative_continuity as NC
    original_proof, original_refinements = NC._transfer_proof, LA.local_refinements

    def refinements(p):           # blind ONLY the scoped exclusion
        if sys._getframe(1).f_code.co_name == "campaign_scope_proof":
            return {"delivery_change": None, "retained_support": None}
        return original_refinements(p)

    monkeypatch.setattr(LA, "local_refinements", refinements)
    monkeypatch.setattr(NC, "_transfer_proof",
                        lambda p, f, t, snapshot=None: original_proof(p, f, t, snapshot=snap))
    proof, reason = CS.campaign_scope_proof(snap, row)
    assert reason is None and proof["route"] == "B"
    assert proof["local_transfer_proof"]["local_authority_route"]["route"] == case


def test_a_bound_campaign_is_never_shadowed_by_a_local_refinement(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    cycle = _cycle("M2-BOUND", LA.OFFLINE_TEST_PROFILE_V1)
    for hm in H.minutes("16:10", "16:23"):
        _scan(cycle, P.TAPE, hm)
    cycle.campaign_scope_custody._campaign = {"campaign_id": "BOUND-CONTROL",
                                              "direction": "bullish"}
    monkeypatch.setattr(cycle.campaign_scope_custody, "_retire",
                        lambda *a, **k: None)        # keep the control binding in place
    scan, _ = _scan(cycle, P.TAPE, DC_CUTOFF)
    path = scan["snapshot"]["active_path_state"]
    assert "local_refinement_not_considered" in _events(cycle, scan["snapshot"])
    assert LA.local_refinements(path) == {"delivery_change": None, "retained_support": None}
    assert path["owner"] == "none"


# ── restart, revision ────────────────────────────────────────────────────────
def test_cold_restart_rederives_the_identical_market_proof_without_ladder(
        tmp_path, monkeypatch, friday):
    _isolate(monkeypatch, tmp_path)
    cycle = _cycle("M2-RESTART", LA.OFFLINE_TEST_PROFILE_V1)
    scan, _ = _scan(cycle, P.TAPE, "16:30")
    path = scan["snapshot"]["active_path_state"]
    assert _origin(path)["local_proof_id"] == friday["captured"]["packet"]["market_proof_id"]
    assert path["progression"]["favourable_ladder"] == []
    assert LA.authenticated_local_route(path, scan["snapshot"])["route"] == "delivery_change"


def test_history_revision_retires_the_issue(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    cycle = _cycle("M2-REV", LA.OFFLINE_TEST_PROFILE_V1)
    for hm in H.minutes("16:10", "16:26"):
        first, bars = _scan(cycle, P.TAPE, hm)
    old_snap = first["snapshot"]
    old_path = old_snap["active_path_state"]
    assert LA.authenticated_local_route(old_path, old_snap)["route"] == "delivery_change"
    revised = copy.deepcopy(bars)
    revised[10]["volume"] = revised[10].get("volume", 0) + 1     # a past bar changes
    second = cycle.scan(revised, now=datetime.fromisoformat(P._cut("16:26"))
                        + timedelta(minutes=1), invoke_brain=False)
    assert cycle._history.revision == old_snap["derived_state"]["history_revision"] + 1
    assert LA.authenticated_local_route(old_path, old_snap) is None
    assert _transfer_proof(old_path, "bullish", "bearish", snapshot=old_snap) is None
    new_path = second["snapshot"]["active_path_state"]
    route = LA.authenticated_local_route(new_path, second["snapshot"])
    assert route in ({}, None) or route["delivery_change"] != _origin(old_path)["local_proof_id"]
