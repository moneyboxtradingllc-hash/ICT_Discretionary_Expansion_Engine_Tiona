"""STAGE 3C-1 — shadow life inventory and survival certificates.

Authority "none": these facts are measured, published and consumed by nothing.
Real-producer cases run the actual ProductionScanCycle over the synthetic PO3
tape; certificate cases feed lawful settled 1m rows through the production
timeframe builder, which is what the scan hands the shadow.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

import test_campaign_draw_temporal_authority as TA
import test_reversal_foundation_proof_closure as RF
from data_feed.timeframe_builder import _floor_timestamp, build_timeframes
from market_data import campaign_premise as CP
from market_data.object_identity import market_object_id
from market_state.active_path import production_session_key

C = RF.CONTRACT


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    import ai_brain.ecu as ECU
    monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path / "brain_runtime"))
    ECU._STANCE = None
    yield
    ECU._STANCE = None


def _bar(stamp, o, h, l, c):
    return {"timestamp": stamp, "open": o, "high": h, "low": l, "close": c,
            "volume": 10, "contract": C}


# The C2 continuation used throughout Stage 3C: a 3m close below 29429.75 at
# the 03:09 bucket, recovered by 03:12, while every 5m close stays above.
C2_BARS = [
    _bar("2026-08-19T03:05:00+00:00", 29460, 29461, 29458, 29460),
    _bar("2026-08-19T03:06:00+00:00", 29460, 29461, 29455, 29456),
    _bar("2026-08-19T03:07:00+00:00", 29456, 29457, 29450, 29451),
    _bar("2026-08-19T03:08:00+00:00", 29451, 29452, 29446, 29447),
    _bar("2026-08-19T03:09:00+00:00", 29447, 29448, 29440, 29445),
    _bar("2026-08-19T03:10:00+00:00", 29445, 29446, 29420, 29425),
    _bar("2026-08-19T03:11:00+00:00", 29425, 29428, 29418, 29422),
    _bar("2026-08-19T03:12:00+00:00", 29422, 29440, 29421, 29438),
    _bar("2026-08-19T03:13:00+00:00", 29438, 29450, 29437, 29448),
    _bar("2026-08-19T03:14:00+00:00", 29448, 29452, 29446, 29450),
]


def _scan(cycle, rows):
    return cycle.scan(rows, now=RF._now_for(rows), invoke_brain=False)


def _warm(tmp_path, monkeypatch):
    """The accepted Stage 2 warmup, then the LATER bucket (cutoff 03:04)."""
    cycle = RF._cycle(tmp_path, monkeypatch)
    RF._scan_prefix(cycle, len(RF.TAPE_1M))
    _scan(cycle, list(TA.LATER))
    return cycle


def _shadow(snapshot):
    block = snapshot["campaign_premise_shadow"]
    assert block["schema"] == CP.SCHEMA and block["authority"] == "none"
    return block


def _life(block, tf, level=29429.75, side="low"):
    rows = [r for r in block["lives"] if r["source_tf"] == tf and r["side"] == side
            and r["level"] == level]
    return rows[0] if len(rows) == 1 else None


def _registration_ref(cycle, tf, level=29429.75, side="low"):
    rows = [r for r in cycle.occurrence_ledger.occurrences()
            if r.get("event_type") == "PROTECTED_SWING_REGISTERED"
            and r.get("source_tf") == tf and r.get("side") == side
            and float(r.get("level")) == level]
    assert len(rows) == 1, rows
    row = rows[0]
    return CP.LifeRef(
        contract_id=C, market_session=production_session_key(row["event_time"]),
        source_tf=tf, side=side, swing_id=row["swing_id"],
        registered_at=CP._instant(row["registered_at"]), level=float(level),
        basis=row["basis"], registration_occurrence_id=row["occurrence_id"],
        registration_bucket_open=CP._instant(row["source_bar_time"]))


# ── real producer: identity and inventory ──────────────────────────────────
def test_birth_and_resweep_join_one_exact_life(tmp_path, monkeypatch):
    cycle = _warm(tmp_path, monkeypatch)
    block = _shadow(cycle.previous_snapshot)
    assert block["status"] == "AVAILABLE" and block["retained_chains"] == 0
    life = _life(block, "5m")
    assert life is not None
    assert life["registered_at"] == "2026-08-19T01:39:00+00:00"
    assert life["registration_bucket_open"] == "2026-08-19T01:35:00+00:00"
    assert life["sweep_occurrence_ids"] == [
        market_object_id("LIQUIDITY_SWEEP", contract=C, timeframe="5m",
                         instant="2026-08-19T01:35:00+00:00"),
        market_object_id("LIQUIDITY_SWEEP", contract=C, timeframe="5m",
                         instant="2026-08-19T02:15:00+00:00")]
    assert life["association_source"] == CP.ASSOCIATION_SOURCE
    assert life["tracker_slot_present"] is True and life["terminal_event"] is None
    assert life["certificate"]["status"] == "INTACT"
    assert life["certificate"]["settled_through"] == "2026-08-19T03:04:00+00:00"
    assert life["eligible_for_new_selection"] is True
    assert life["eligibility_failures"] == []
    # The current producer associates 15m/5m only: no 3m or 1m life appears.
    assert {r["source_tf"] for r in block["lives"]} <= {"5m", "15m"}


@pytest.mark.parametrize("cadence", ["every_minute", "jump_0308_to_0314"])
def test_trailing_forming_bucket_is_not_required(tmp_path, monkeypatch, cadence):
    """At 03:05 the 03:05 bucket has one settled member and is normally
    forming. It is not yet required, so the 5m life stays INTACT through 03:04;
    from 03:09 that whole bucket is required."""
    cycle = _warm(tmp_path, monkeypatch)
    expected = {"03:04": "03:04", "03:05": "03:04", "03:06": "03:04",
                "03:07": "03:04", "03:08": "03:04", "03:09": "03:09",
                "03:10": "03:09", "03:11": "03:09", "03:12": "03:09",
                "03:13": "03:09", "03:14": "03:14"}
    rows = list(TA.LATER)
    seen = {}
    for bar in C2_BARS:
        rows = rows + [bar]
        stamp = bar["timestamp"][11:16]
        if cadence == "jump_0308_to_0314" and "03:09" <= stamp <= "03:13":
            continue
        life = _life(_shadow(_scan(cycle, rows)["snapshot"]), "5m")
        assert life["certificate"]["status"] == "INTACT", (stamp, life["certificate"])
        seen[stamp] = life["certificate"]["settled_through"][11:16]
    assert seen == {k: v for k, v in expected.items() if k in seen}
    assert "03:14" in seen


def test_missed_three_minute_close_is_failed_by_certificate(tmp_path, monkeypatch):
    """Stage 3C 2B: scans at 03:08 then 03:14 never see 03:09 as the newest
    3m bucket, so the tracker keeps the 3m life. The certificate does not."""
    cycle = _warm(tmp_path, monkeypatch)
    rows = list(TA.LATER) + C2_BARS[:4]
    _scan(cycle, rows)
    rows = list(TA.LATER) + C2_BARS
    snapshot = _scan(cycle, rows)["snapshot"]
    three = snapshot["protected_swings"]["by_timeframe"]["lows"]["3m"]
    assert three["level"] == 29429.75                     # slot still occupied
    block = _shadow(snapshot)
    assert _life(block, "3m") is None                     # no 3m association
    ref = _registration_ref(cycle, "3m")
    settled = build_timeframes(rows)["1m"]
    cert = CP.observe_life(ref, settled_1m=settled, history_revision=0,
                           contract_id=C, cutoff=snapshot["timestamp"])
    assert cert["status"] == "FAILED"
    assert cert["failure_bucket"]["open"] == "2026-08-19T03:09:00+00:00"
    assert cert["failure_bucket"]["close"] == 29422
    assert len(cert["failure_bucket"]["member_digests"]) == 3
    # Explicit frozen-life observation of the same exact life.
    watcher = CP.CampaignPremiseShadow()
    observed = watcher.advance(
        snapshot=snapshot, settled_1m=settled,
        ledger_rows=cycle.occurrence_ledger.occurrences(), history_revision=0,
        contract_id=C, market_session=ref.market_session,
        cutoff=snapshot["timestamp"], watched_lives=(ref,))
    [watched] = observed["watched_lives"]
    assert watched["tracker_slot_present"] is True
    assert watched["certificate"]["status"] == "FAILED"
    assert observed["retained_chains"] == 1


def test_every_minute_tracker_violation_agrees_with_certificate(tmp_path, monkeypatch):
    cycle = _warm(tmp_path, monkeypatch)
    ref = _registration_ref(cycle, "3m")
    watcher = CP.CampaignPremiseShadow()
    rows = list(TA.LATER)
    states = {}
    for bar in C2_BARS:
        rows = rows + [bar]
        snapshot = _scan(cycle, rows)["snapshot"]
        observed = watcher.advance(
            snapshot=snapshot, settled_1m=build_timeframes(rows)["1m"],
            ledger_rows=cycle.occurrence_ledger.occurrences(), history_revision=0,
            contract_id=C, market_session=ref.market_session,
            cutoff=snapshot["timestamp"], watched_lives=(ref,))
        [watched] = observed["watched_lives"]
        states[bar["timestamp"][11:16]] = (watched["certificate"]["status"],
                                           (watched["terminal_event"] or {}).get("type"),
                                           watched["tracker_slot_present"])
    assert states["03:10"] == ("INTACT", None, True)
    assert states["03:11"] == ("FAILED", "PROTECTED_SWING_VIOLATED", False)
    # Slot and catalog disappearance do not stop observing the exact life;
    # the failure stays sticky inside the retained lineage after recovery.
    assert states["03:14"] == ("FAILED", "PROTECTED_SWING_VIOLATED", False)


def test_production_retains_zero_chains_and_publishes_detached_blocks(tmp_path, monkeypatch):
    cycle = RF._cycle(tmp_path, monkeypatch)
    for end in range(5, len(RF.TAPE_1M) + 1, 5):
        snapshot = _scan(cycle, RF.TAPE_1M[:end])["snapshot"]
        assert _shadow(snapshot)["retained_chains"] == 0
        assert cycle.campaign_premise_shadow.retained_chains == 0
    ledger_before = copy.deepcopy(cycle.occurrence_ledger.occurrences())
    slots_before = copy.deepcopy(snapshot["protected_swings"])
    block = _shadow(snapshot)
    block["lives"][0]["certificate"]["status"] = "TAMPERED"
    block["lives"][0]["sweep_occurrence_ids"].append("TAMPERED")
    assert cycle.occurrence_ledger.occurrences() == ledger_before
    assert snapshot["protected_swings"] == slots_before
    nxt = _shadow(_scan(cycle, list(TA.LATER))["snapshot"])
    assert nxt["lives"][0]["certificate"]["status"] == "INTACT"
    assert "TAMPERED" not in nxt["lives"][0]["sweep_occurrence_ids"]


def test_common_cutoff_certificates_match_across_cadence(tmp_path, monkeypatch):
    """The 5m life is the same exact life at both cadences on this tape (its
    registration edge coincides with both scan grids), so its certificate is
    identical at every common cutoff. Different lives are never merged."""
    out = {}
    for cadence in (1, 5):
        cycle = RF._cycle(tmp_path / f"c{cadence}", monkeypatch)
        out[cadence] = {}
        for end in range(5, len(TA.LATER) + 1):
            if end % cadence and end != len(TA.LATER):
                continue
            rows = TA.LATER[:end]
            life = _life(_shadow(_scan(cycle, rows)["snapshot"]), "5m")
            if life is not None:
                out[cadence][rows[-1]["timestamp"]] = (
                    life["registered_at"], life["registration_bucket_open"],
                    life["certificate"]["status"], life["certificate"]["settled_through"],
                    life["certificate"]["covered_buckets"])
    common = sorted(set(out[1]) & set(out[5]))
    assert len(common) >= 5
    assert all(out[1][t] == out[5][t] for t in common), [
        (t, out[1][t], out[5][t]) for t in common if out[1][t] != out[5][t]]


# ── real producer: lanes, single cognition, no consumer ─────────────────────
@pytest.mark.parametrize("ecu", [True, False], ids=["ecu", "non-ecu"])
def test_one_advance_per_scan_and_no_brain_input(tmp_path, monkeypatch, ecu):
    cycle, calls = TA._cycle_with_brain(tmp_path, monkeypatch, ecu=ecu)
    advances = []
    real = CP.CampaignPremiseShadow.advance

    def spy(self, **kwargs):
        advances.append(kwargs["cutoff"])
        return real(self, **kwargs)

    monkeypatch.setattr(CP.CampaignPremiseShadow, "advance", spy)
    first = TA._scan(cycle, RF.TAPE_1M)
    later = TA._scan(cycle, TA.LATER)
    RF._assert_retained_reversal_candidate(RF._produce_candidate(later))
    trigger = TA._scan(cycle, TA.NEXT_MINUTE, brain=False)
    assert len(advances) == 3 and len(calls) == 2
    for payload in calls:
        # M2 adds only its producer-owned frozen catalog; raw M1 facts/custody
        # still cannot enter cognition or become execution authority.
        assert set(k for k in payload if "campaign_premise" in k) == {"campaign_premise_catalog"}
        assert payload["campaign_premise_catalog"]["schema"] == "campaign_premise_catalog/v1"
        # M3 carries the authenticated scope projection in continuity. Raw M1
        # facts remain excluded and the shadow itself stays authority none.
        scope = payload["narrative_continuity"]["campaign_scope"]
        assert scope["schema"] == "campaign_scope_custody/v1"
        assert scope["authority"] == "scope"
        assert "campaign_premise_shadow" not in str(payload)
    for scan in (first, later, trigger):
        assert _shadow(scan["snapshot"])["status"] == "AVAILABLE"
    assert later["campaign_lifecycle"]["state"] == "ACTIVE_DELIVERY"


@pytest.mark.parametrize("ecu", [True, False], ids=["ecu", "non-ecu"])
def test_shadow_failure_makes_current_scope_unavailable_and_holds_entry(tmp_path, monkeypatch, ecu):
    def outcomes(root, broken):
        cycle, calls = TA._cycle_with_brain(root, monkeypatch, ecu=ecu)
        if broken:
            def boom(self, **kwargs):
                raise RuntimeError("shadow fault")
            monkeypatch.setattr(CP.CampaignPremiseShadow, "_advance", boom)
        TA._scan(cycle, RF.TAPE_1M)
        later = TA._scan(cycle, TA.LATER)
        if broken:
            from broker.luna_candidate_producer import NoCandidate
            with pytest.raises(NoCandidate, match="campaign_lifecycle_refused"):
                RF._produce_candidate(later)
            assert later["campaign_lifecycle"]["participation_permitted"] is False
            continuity = later["brain_block"]["narrative_continuity"]
            assert continuity["campaign_premise"]["reason"] == "campaign_scope_unavailable"
            assert continuity["dominant_direction"] is None
            candidate = None
        else:
            candidate = RF._produce_candidate(later)
        block = later["snapshot"]["campaign_premise_shadow"]
        return (later["campaign_lifecycle"]["state"],
                later["campaign_lifecycle"]["reason"],
                later["campaign_draw_authority"].get("authority_status"),
                (later["snapshot"].get("ai_brain") or {}).get("output", {}).get(
                    "narrative_direction"),
                candidate.direction if candidate else None,
                candidate.invalidation_price if candidate else None,
                candidate.objective.price if candidate else None, len(calls)), block

    healthy, block_ok = outcomes(tmp_path / "ok", broken=False)
    broken, block_bad = outcomes(tmp_path / "bad", broken=True)
    assert block_ok["status"] == "AVAILABLE"
    assert block_bad["status"] == "UNAVAILABLE"
    assert block_bad["reason"] == "shadow_error:RuntimeError"
    assert healthy[0] == "ACTIVE_DELIVERY" and healthy[4] == "bullish"
    assert broken[0] == "TRANSFER_UNRESOLVED" and broken[4:7] == (None,None,None)
    assert healthy[-1] == broken[-1] == 2


def test_history_rebuild_recreates_the_shadow(tmp_path, monkeypatch):
    cycle = _warm(tmp_path, monkeypatch)
    before = cycle.campaign_premise_shadow
    revised = [dict(bar) for bar in TA.LATER]
    revised[-3]["close"] = revised[-3]["close"] + 0.25
    revised[-3]["high"] = max(revised[-3]["high"], revised[-3]["close"])
    snapshot = _scan(cycle, revised)["snapshot"]
    assert cycle.campaign_premise_shadow is not before
    assert _shadow(snapshot)["history_revision"] == cycle._history.revision


# ── certificate units over lawful settled rows ──────────────────────────────
START = datetime(2026, 8, 19, 13, 0, tzinfo=timezone.utc)


def _settled(minutes, *, start=START, price=29500.0, skip=(), overrides=None):
    rows = []
    for i in range(minutes):
        stamp = (start + timedelta(minutes=i)).isoformat()
        if stamp[11:16] in skip:
            continue
        bar = _bar(stamp, price, price + 1, price - 1, price)
        bar.update((overrides or {}).get(stamp[11:16], {}))
        rows.append(bar)
    return build_timeframes(rows)["1m"]


def _ref(tf="5m", anchor="13:00", level=29490.0, side="low"):
    return CP.LifeRef(contract_id=C, market_session="20260819", source_tf=tf,
                      side=side, swing_id=f"{tf}:swing_{side}:{level:g}",
                      registered_at=f"2026-08-19T{anchor}:00+00:00", level=level,
                      basis="sell_side_raid_rejected",
                      registration_occurrence_id="REG",
                      registration_bucket_open=f"2026-08-19T{anchor}:00+00:00")


def _observe(rows, life, cutoff, **kwargs):
    return CP.observe_life(life, settled_1m=rows, history_revision=kwargs.pop("rev", 0),
                           contract_id=C, cutoff=f"2026-08-19T{cutoff}:00+00:00",
                           **kwargs)


def test_zero_post_registration_buckets_can_be_intact():
    cert = _observe(_settled(5), _ref(), "13:04")
    assert cert["status"] == "INTACT" and cert["covered_buckets"] == 0
    assert cert["settled_through"] == "2026-08-19T13:04:00+00:00"


def test_fifteen_minute_geometry_requires_only_settled_buckets():
    life = _ref(tf="15m")
    rows = _settled(45, skip=("13:20",))          # interior gap in bucket 13:15
    for cutoff in ("13:14", "13:15", "13:20", "13:28"):
        cert = _observe([r for r in rows if r["timestamp"][11:16] <= cutoff], life, cutoff)
        assert cert["status"] == "INTACT", (cutoff, cert)
        assert cert["settled_through"] == "2026-08-19T13:14:00+00:00"
    cert = _observe([r for r in rows if r["timestamp"][11:16] <= "13:29"], life, "13:29")
    assert cert["status"] == "UNKNOWN"
    assert cert["reason"].startswith("required_bucket_missing_interior_member")
    assert cert["settled_through"] == "2026-08-19T13:29:00+00:00"


@pytest.mark.parametrize("case,expected", [
    ("missing_interior", "required_bucket_missing_interior_member"),
    ("missing_terminal", "required_bucket_missing_terminal_member"),
    ("conflicting_duplicate", "required_bucket_member_invalid:conflicting_duplicate"),
    ("not_proven_settled", "required_bucket_member_invalid:candle_not_proven_settled"),
    ("unexpected_instant", "required_bucket_unexpected_member_instant"),
    ("malformed_ohlc", "required_bucket_member_invalid:malformed_candle"),
])
def test_required_coverage_failures_are_unknown(case, expected):
    rows = _settled(15)
    if case == "missing_interior":
        rows = [r for r in rows if r["timestamp"][11:16] != "13:07"]
    elif case == "missing_terminal":
        rows = [r for r in rows if r["timestamp"][11:16] != "13:09"]
    elif case == "conflicting_duplicate":
        twin = dict(next(r for r in rows if r["timestamp"][11:16] == "13:07"))
        twin["close"] = twin["close"] - 0.25
        rows = rows + [twin]
        rows.sort(key=lambda r: r["timestamp"])
    elif case == "not_proven_settled":
        for r in rows:
            if r["timestamp"][11:16] == "13:07":
                r["complete"] = False
    elif case == "unexpected_instant":
        extra = dict(rows[7])
        extra["timestamp"] = "2026-08-19T13:07:30+00:00"
        rows = rows + [extra]
        rows.sort(key=lambda r: r["timestamp"])
    elif case == "malformed_ohlc":
        for r in rows:
            if r["timestamp"][11:16] == "13:07":
                r["low"] = r["high"] + 5
    cert = _observe(rows, _ref(), "13:14")
    assert cert["status"] == "UNKNOWN"
    assert cert["reason"].startswith(expected), cert["reason"]


def test_unknown_cadence_bucket_is_unknown(monkeypatch):
    import market_data.evidence_continuity as EC
    rows = _settled(20, skip=tuple(f"13:{m:02d}" for m in range(5, 10)))
    monkeypatch.setattr(EC, "evaluate", lambda *a, **k: {
        "continuity_class": EC.UNKNOWN_CADENCE, "gaps": []})
    cert = _observe(rows, _ref(), "13:19")
    assert cert["status"] == "UNKNOWN"
    assert cert["reason"].startswith("required_bucket_no_members")


def test_expected_break_is_continuous_but_open_venue_absence_is_unknown():
    closed = [r for r in _settled(150, start=datetime(2026, 8, 19, 20, 0,
                                                      tzinfo=timezone.utc))
              if not ("21:00" <= r["timestamp"][11:16] <= "21:59")]
    cert = _observe(closed, _ref(anchor="20:00"), "22:29")
    assert cert["status"] == "INTACT", cert
    absent = _settled(40, skip=tuple(f"13:{m:02d}" for m in range(10, 15)))
    cert = _observe(absent, _ref(), "13:39")
    assert cert["status"] == "UNKNOWN"
    assert cert["reason"] == "required_bucket_no_members:2026-08-19T13:10:00+00:00"


def test_valid_violation_survives_unrelated_gap_and_malformed_row():
    rows = _settled(30, skip=("13:07",), overrides={
        "13:24": {"close": 29480.0, "low": 29479.0},       # 13:20 bucket closes below
        "13:12": {"high": 1.0}})                          # malformed, unrelated
    rows = rows + [{"timestamp": "not-a-time", "open": 1, "high": 1, "low": 1,
                    "close": 1, "volume": 1, "contract": C, "complete": True}]
    cert = _observe(rows, _ref(), "13:29")
    assert cert["status"] == "FAILED"
    assert cert["failure_bucket"]["open"] == "2026-08-19T13:20:00+00:00"
    assert cert["failure_bucket"]["close"] == 29480.0
    # Control: the same damaged window without the violating close is UNKNOWN.
    control = _settled(30, skip=("13:07",), overrides={"13:12": {"high": 1.0}})
    control = control + [rows[-1]]
    assert _observe(control, _ref(), "13:29")["status"] == "UNKNOWN"


def test_registration_bucket_cannot_fail_retroactively():
    rows = _settled(10, overrides={"13:04": {"close": 29480.0, "low": 29479.0}})
    cert = _observe(rows, _ref(), "13:09")
    assert cert["status"] == "INTACT" and cert["covered_buckets"] == 1


def test_retained_chain_continuation_and_retirement():
    life = _ref()
    full = _settled(60)
    first = _observe(full[:30], life, "13:29")
    assert first["status"] == "INTACT"
    window = full[20:45]                          # anchor bucket no longer in window
    kept = _observe(window, life, "13:44", retained=first)
    assert kept["status"] == "INTACT" and kept["settled_through"].endswith("13:44:00+00:00")
    # a revised history is another lineage: the chain is retired
    revised = _observe(window, life, "13:44", retained=first, rev=1)
    assert revised["status"] == "UNKNOWN"
    assert revised["reason"] == "registration_anchor_outside_window"
    # changed tip digest
    changed = [dict(r) for r in window]
    for r in changed:
        if r["timestamp"][11:16] == "13:27":
            r["volume"] = 11
    assert _observe(changed, life, "13:44", retained=first)["status"] == "UNKNOWN"
    # non-overlap: the retained tip is outside the window
    assert _observe(full[35:55], life, "13:54", retained=first)["status"] == "UNKNOWN"
    # restart without span: no chain, anchor outside window
    assert _observe(window, life, "13:44")["reason"] == "registration_anchor_outside_window"


def test_failure_stays_sticky_inside_its_lineage_only():
    life = _ref()
    rows = _settled(30, overrides={"13:09": {"close": 29480.0, "low": 29479.0}})
    failed = _observe(rows, life, "13:29")
    assert failed["status"] == "FAILED"
    later = _observe(_settled(60)[25:60], life, "13:59", retained=failed)
    assert later["status"] == "FAILED" and later["reason"] == "failure_witness_retained"
    assert _observe(_settled(60)[25:60], life, "13:59", retained=failed,
                    rev=1)["status"] == "UNKNOWN"


def test_tracker_witness_conflict():
    intact = {"status": "INTACT", "reason": "all_required_buckets_valid"}
    conflict = CP.apply_tracker_witness(intact, {"type": "PROTECTED_SWING_VIOLATED"})
    assert conflict["status"] == "UNKNOWN"
    assert conflict["reason"] == "tracker_certificate_conflict"
    replaced = CP.apply_tracker_witness(intact, {"type": "PROTECTED_SWING_REPLACED"})
    assert replaced == intact
    failed = {"status": "FAILED", "reason": "valid_close_beyond_level"}
    assert CP.apply_tracker_witness(failed, {"type": "PROTECTED_SWING_VIOLATED"}) == failed


# ── inventory and eligibility units ─────────────────────────────────────────
SESSION = production_session_key("2026-08-19T13:20:00+00:00")


def _sweep_row(at, *, level=29490.0, tf="5m", registered="13:09", observed="13:09",
               basis="sell_side_raid_rejected", session=SESSION, contract=C,
               swing_id=None):
    instant = f"2026-08-19T{at}:00+00:00"
    return {
        "occurrence_id": market_object_id("LIQUIDITY_SWEEP", contract=C, timeframe=tf,
                                          instant=instant),
        "event_type": "LIQUIDITY_SWEEP", "contract": C, "source_tf": tf,
        "event_time": instant, "sweep_direction": "below_low", "swept_level": level,
        "reclaimed": True, "source_bars": [instant],
        "protected_swing_lifetime": {
            "contract": contract, "market_session": session, "source_tf": tf,
            "side": "low", "swing_id": swing_id or f"{tf}:swing_low:{level:g}",
            "registered_at": f"2026-08-19T{registered}:00+00:00", "level": level,
            "basis": basis, "observed_at": f"2026-08-19T{observed}:00+00:00"}}


def _registration_row(registered="13:09", *, level=29490.0, tf="5m", source="13:05",
                      basis="sell_side_raid_rejected", oid=None):
    stamp = f"2026-08-19T{registered}:00+00:00"
    return {"occurrence_id": oid or f"REG:{tf}:{registered}:{level}",
            "event_type": "PROTECTED_SWING_REGISTERED", "contract": C,
            "source_tf": tf, "event_time": stamp, "side": "low", "level": level,
            "basis": basis, "swing_id": f"{tf}:swing_low:{level:g}",
            "registered_at": stamp, "source_bar_time": f"2026-08-19T{source}:00+00:00",
            "settled_edge_time": stamp, "observed_at": stamp}


def _slots(registered="13:09", level=29490.0, tf="5m"):
    return {"lows": {tf: {"level": level, "timeframe": tf, "role": "active_leg",
                          "registered_at": f"2026-08-19T{registered}:00+00:00",
                          "swing_id": f"{tf}:swing_low:{level:g}",
                          "basis": "sell_side_raid_rejected"}}, "highs": {}}


def _inventory(rows, slots=None, cutoff="13:20"):
    return CP.life_inventory(ledger_rows=rows, protected_by_timeframe=slots or {},
                             contract_id=C, market_session=SESSION,
                             cutoff=f"2026-08-19T{cutoff}:00+00:00")


def test_same_price_distinct_lives_stay_distinct():
    rows = [_sweep_row("13:05"), _registration_row(),
            _sweep_row("13:15", registered="13:19", observed="13:19"),
            _registration_row("13:19", source="13:15")]
    lives = _inventory(rows)
    assert [(r["registered_at"][11:16], r["registration_bucket_open"][11:16])
            for r in lives] == [("13:09", "13:05"), ("13:19", "13:15")]
    assert all(r["join"]["tuple_conflict"] is False for r in lives)


def test_conflicting_tuple_is_never_eligible():
    rows = [_sweep_row("13:05"), _sweep_row("13:10", basis="other_basis"),
            _registration_row()]
    lives = _inventory(rows, _slots())
    assert len(lives) == 2 and all(r["join"]["tuple_conflict"] for r in lives)
    for row in lives:
        verdict = CP.selection_eligibility(
            row, {"status": "INTACT"}, protected_by_timeframe=_slots(),
            ledger_rows=rows, cutoff="2026-08-19T13:20:00+00:00")
        assert "V7" in verdict["failures"] and not verdict["eligible"]


def test_stale_future_foreign_and_v1_rows_are_excluded():
    v1 = dict(_sweep_row("13:05"))
    v1["occurrence_id"] = "LIQUIDITY_SWEEP:" + C + ":5m:2026-08-19T13:09:00+00:00:below_low"
    rows = [v1, _registration_row(),
            _sweep_row("13:10", observed="13:25", registered="13:14"),   # future
            _sweep_row("13:00", session="20260101"),                     # other session
            _sweep_row("13:15", level=float("nan"))]                     # malformed
    assert _inventory(rows) == []


def test_registration_join_must_be_unique_and_aligned():
    base = [_sweep_row("13:05")]
    twice = base + [_registration_row(), _registration_row(oid="REG:other")]
    [row] = _inventory(twice, _slots())
    assert row["join"]["registration_rows"] == 2
    assert row["registration_occurrence_id"] is None
    misaligned = base + [_registration_row(source="13:06")]
    [row] = _inventory(misaligned, _slots())
    assert row["registration_bucket_open"] is None
    replacement = dict(_registration_row(), event_type="PROTECTED_SWING_REPLACED")
    [row] = _inventory(base + [replacement], _slots())
    assert row["join"] == dict(row["join"], registration_rows=0, replacement_birth_rows=1)
    for candidate in (twice, misaligned, base + [replacement]):
        [row] = _inventory(candidate, _slots())
        verdict = CP.selection_eligibility(
            row, {"status": "INTACT"}, protected_by_timeframe=_slots(),
            ledger_rows=candidate, cutoff="2026-08-19T13:20:00+00:00")
        assert "V2" in verdict["failures"]


def test_slot_and_terminal_events_drive_v3_v4_only():
    rows = [_sweep_row("13:05"), _registration_row()]
    [row] = _inventory(rows, _slots())
    ok = CP.selection_eligibility(row, {"status": "INTACT"}, protected_by_timeframe=_slots(),
                                  ledger_rows=rows, cutoff="2026-08-19T13:20:00+00:00")
    assert ok == {"eligible": True, "failures": []}
    gone = CP.selection_eligibility(row, {"status": "INTACT"}, protected_by_timeframe={},
                                    ledger_rows=rows, cutoff="2026-08-19T13:20:00+00:00")
    assert gone["failures"] == ["V3"]
    violated = rows + [dict(_registration_row(), occurrence_id="VIO",
                            event_type="PROTECTED_SWING_VIOLATED",
                            event_time="2026-08-19T13:15:00+00:00",
                            observed_at="2026-08-19T13:15:00+00:00",
                            source_bar_time="2026-08-19T13:10:00+00:00")]
    [row] = _inventory(violated, _slots())
    assert row["terminal_event"]["type"] == "PROTECTED_SWING_VIOLATED"
    verdict = CP.selection_eligibility(row, {"status": "INTACT"},
                                       protected_by_timeframe=_slots(),
                                       ledger_rows=violated,
                                       cutoff="2026-08-19T13:20:00+00:00")
    assert verdict["failures"] == ["V4"]
    # A violation not yet available at T is not a terminal event.
    [row] = _inventory(violated, _slots(), cutoff="13:12")
    assert row["terminal_event"] is None


# ── floors, limits, bounds ──────────────────────────────────────────────────
@pytest.mark.parametrize("minutes", [1, 3, 5, 15])
@pytest.mark.parametrize("offset", ["-04:00", "-05:00"])
def test_canonical_floor_matches_builder_floor_in_repeated_hour(minutes, offset):
    for minute in range(60):
        local = f"2026-11-01T01:{minute:02d}:00{offset}"
        builder = CP._instant(_floor_timestamp(local, minutes))
        assert CP._iso(CP._floor(CP._dt(CP._instant(local)), minutes)) == builder


def test_watch_limit_is_refused_not_truncated_and_reasons_are_bounded():
    shadow = CP.CampaignPremiseShadow()
    lives = tuple(_ref(level=29490.0 + i) for i in range(3))
    out = shadow.advance(snapshot={}, settled_1m=_settled(10), ledger_rows=[],
                         history_revision=0, contract_id=C, market_session=SESSION,
                         cutoff="2026-08-19T13:09:00+00:00", watched_lives=lives)
    assert out["status"] == "UNAVAILABLE"
    assert out["reason"] == "watched_lives_limit_exceeded:3"
    assert out["retained_chains"] == 0 and shadow.retained_chains == 0
    two = shadow.advance(snapshot={}, settled_1m=_settled(10), ledger_rows=[],
                         history_revision=0, contract_id=C, market_session=SESSION,
                         cutoff="2026-08-19T13:09:00+00:00", watched_lives=lives[:2])
    assert two["status"] == "AVAILABLE" and two["retained_chains"] == 2
    none = shadow.advance(snapshot={}, settled_1m=_settled(10), ledger_rows=[],
                          history_revision=0, contract_id=C, market_session=SESSION,
                          cutoff="2026-08-19T13:09:00+00:00")
    assert none["retained_chains"] == 0
    long_reason = CP.unavailable(reason="x" * 1000)["reason"]
    assert len(long_reason) <= CP.REASON_CAP


# ── Stage 3C-1-R1: source order, chain retirement, watch context, duplicates ─
FAIL_AT_0909 = {"13:09": {"close": 29480.0, "low": 29479.0}}


def _swap(rows, first, second):
    rows = [dict(r) for r in rows]
    i = next(k for k, r in enumerate(rows) if r["timestamp"][11:16] == first)
    j = next(k for k, r in enumerate(rows) if r["timestamp"][11:16] == second)
    rows[i], rows[j] = rows[j], rows[i]
    return rows


def test_out_of_order_bucket_is_never_sorted_into_intact():
    cert = _observe(_swap(_settled(15), "13:06", "13:07"), _ref(), "13:14")
    assert cert["status"] == "UNKNOWN"
    assert cert["reason"] == ("required_bucket_member_invalid:settled_candles_not_"
                              "chronological:2026-08-19T13:05:00+00:00")


def test_bucket_interleaved_across_its_boundary_is_invalid():
    cert = _observe(_swap(_settled(20), "13:09", "13:10"), _ref(), "13:19")
    assert cert["status"] == "UNKNOWN"
    assert cert["reason"] == ("required_bucket_member_order_interleaved:"
                              "2026-08-19T13:05:00+00:00")


def test_disordered_bucket_proves_nothing_but_a_valid_violation_still_fails():
    bad = {"close": 29480.0, "low": 29479.0}
    only = _swap(_settled(20, overrides={"13:09": bad}), "13:06", "13:07")
    assert _observe(only, _ref(), "13:19")["status"] == "UNKNOWN"
    both = _swap(_settled(20, overrides={"13:09": bad, "13:19": bad}), "13:06", "13:07")
    cert = _observe(both, _ref(), "13:19")
    assert cert["status"] == "FAILED"
    assert cert["failure_bucket"]["open"] == "2026-08-19T13:15:00+00:00"


def test_identical_duplicates_and_equivalent_instants_keep_their_meaning():
    rows = _settled(15)
    plain = _observe(rows, _ref(), "13:14")
    assert plain["status"] == "INTACT"
    twin = dict(rows[7])                                     # 13:07, identical
    for variant in (rows[:8] + [twin] + rows[8:], rows + [dict(twin)]):
        cert = _observe(variant, _ref(), "13:14")
        assert cert["status"] == "INTACT", cert
        assert cert["tip_member_digests"] == plain["tip_member_digests"]
    zulu = [dict(r, timestamp=r["timestamp"].replace("+00:00", "Z")) for r in rows]
    cert = _observe(zulu, _ref(), "13:14")
    assert cert["status"] == "INTACT"
    assert cert["tip_member_digests"] == plain["tip_member_digests"]


@pytest.mark.parametrize("status", ["FAILED", "INTACT"])
def test_retained_chain_rule_is_the_same_for_failed_and_intact(status):
    life = _ref()
    overrides = FAIL_AT_0909 if status == "FAILED" else None
    first = _observe(_settled(30, overrides=overrides), life, "13:29")
    assert first["status"] == status
    assert first["tip_bucket_open"] == "2026-08-19T13:25:00+00:00"
    later = _settled(60, overrides=overrides)[25:60]     # holds the 13:25 tip, not the anchor
    kept = _observe(later, life, "13:59", retained=first)
    assert kept["status"] == status
    # the measurement advances; nothing stays frozen at the retained one
    assert kept["tip_bucket_open"] == "2026-08-19T13:55:00+00:00"
    assert kept["settled_through"] == "2026-08-19T13:59:00+00:00"
    assert kept["cutoff"] == "2026-08-19T13:59:00+00:00"
    if status == "FAILED":
        assert kept["reason"] == "failure_witness_retained"
        assert kept["failure_bucket"] == first["failure_bucket"]
    # a duplicate cutoff over identical evidence is the identical certificate
    assert _observe(later, life, "13:59", retained=kept) == kept


@pytest.mark.parametrize("status", ["FAILED", "INTACT"])
@pytest.mark.parametrize("case", ["changed_digest", "missing_tip", "revision",
                                  "backwards_cutoff", "restart"])
def test_retained_chain_retires_and_recomputes_from_current_evidence(status, case):
    life = _ref()
    full = _settled(60, overrides=FAIL_AT_0909 if status == "FAILED" else None)
    first = _observe(full[:30], life, "13:29")
    window, cutoff, kwargs = full[25:60], "13:59", {"retained": first}
    if case == "changed_digest":
        window = [dict(r, volume=999) if r["timestamp"][11:16] == "13:27" else r
                  for r in window]
    elif case == "missing_tip":
        window = full[35:60]
    elif case == "revision":
        kwargs["rev"] = 1
    elif case == "backwards_cutoff":
        mid = _observe(full[25:59], life, "13:58", retained=first)
        assert mid["status"] == status
        assert mid["tip_bucket_open"] == "2026-08-19T13:50:00+00:00"
        # 13:56 still holds that tip, but the cutoff moved backwards
        window, cutoff, kwargs = full[25:57], "13:56", {"retained": mid}
    elif case == "restart":
        kwargs = {}
    cert = _observe(window, life, cutoff, **kwargs)
    assert cert["status"] == "UNKNOWN", cert
    assert cert["reason"] == "registration_anchor_outside_window"


@pytest.mark.parametrize("status", ["FAILED", "INTACT"])
def test_retained_chain_rolls_minute_by_minute_past_its_witness(status):
    life = _ref()
    full = _settled(90, overrides=FAIL_AT_0909 if status == "FAILED" else None)
    cert = _observe(full[:30], life, "13:29")
    for end in range(31, 91):          # the window's leading edge walks through 13:05..13:09
        window = full[max(0, end - 30):end]
        cert = _observe(window, life, window[-1]["timestamp"][11:16], retained=cert)
        assert cert["status"] == status, (end, cert)
        if status == "FAILED":
            assert cert["failure_bucket"]["open"] == "2026-08-19T13:05:00+00:00"
    assert cert["settled_through"] == "2026-08-19T14:29:00+00:00"


def test_fresh_current_failure_still_proves_failed_after_retirement():
    life = _ref()
    first = _observe(_settled(30), life, "13:29")
    later = _settled(60, overrides={"13:49": {"close": 29480.0, "low": 29479.0}})[35:60]
    cert = _observe(later, life, "13:59", retained=first)      # tip absent: retired
    assert cert["status"] == "FAILED" and cert["reason"] == "valid_close_beyond_level"
    assert cert["failure_bucket"]["open"] == "2026-08-19T13:45:00+00:00"


def test_failed_chain_survives_an_unrelated_damaged_bucket():
    failed = _observe(_settled(30, overrides=FAIL_AT_0909), _ref(), "13:29")
    later = [r for r in _settled(60)[25:60] if r["timestamp"][11:16] != "13:42"]
    cert = _observe(later, _ref(), "13:59", retained=failed)
    assert cert["status"] == "FAILED" and cert["reason"] == "failure_witness_retained"


def test_contradicted_failure_witness_is_not_retained():
    failed = _observe(_settled(30, overrides=FAIL_AT_0909), _ref(), "13:29")
    current = _settled(45)              # the 13:09 close no longer breaks the level
    cert = _observe(current, _ref(), "13:44", retained=failed)
    assert cert["reason"] != "failure_witness_retained"
    assert cert["status"] == "INTACT" and cert["failure_bucket"] is None


def _watch(lives, *, rows=None, slots=None, ledger=(), cutoff="13:14", shadow=None):
    shadow = shadow or CP.CampaignPremiseShadow()
    block = shadow.advance(snapshot={"protected_swings": {"by_timeframe": slots or {}}},
                           settled_1m=_settled(15) if rows is None else rows,
                           ledger_rows=list(ledger), history_revision=0, contract_id=C,
                           market_session=SESSION, cutoff=f"2026-08-19T{cutoff}:00+00:00",
                           watched_lives=tuple(lives))
    return block, shadow


@pytest.mark.parametrize("change,reason", [
    ({"market_session": "20260101"}, "watched_life_foreign_session"),
    ({"contract_id": "CON.F.US.MNQ.H27"}, "watched_life_foreign_contract"),
    ({"source_tf": "4m"}, "watched_life_unsupported_timeframe"),
    ({"side": "middle"}, "watched_life_invalid_side"),
    ({"level": float("nan")}, "watched_life_invalid_level"),
    ({"level": True}, "watched_life_invalid_level"),
    ({"swing_id": ""}, "watched_life_invalid_identity"),
    ({"registered_at": "2026-08-19T13:00:00Z"}, "watched_life_registered_at_not_canonical"),
    ({"registered_at": "2026-08-19T13:30:00+00:00"}, "watched_life_registered_after_cutoff"),
    ({"registered_at": "2026-08-18T13:00:00+00:00"},
     "watched_life_registered_in_other_session"),
    ({"registration_bucket_open": "2026-08-19T13:02:00+00:00"},
     "watched_life_registration_anchor_invalid"),
])
def test_foreign_or_malformed_watch_is_refused_and_never_measured(change, reason):
    from dataclasses import replace
    block, shadow = _watch([replace(_ref(), **change)])
    [watched] = block["watched_lives"]
    assert block["status"] == "AVAILABLE"
    assert watched["certificate"]["status"] == "UNKNOWN"
    assert watched["certificate"]["reason"] == reason
    assert watched["certificate"]["lineage_id"] is None
    assert watched["certificate"]["covered_buckets"] == 0
    assert block["retained_chains"] == 0 and shadow.retained_chains == 0


def test_watch_contradicting_the_producer_registration_is_refused():
    from dataclasses import replace
    ledger = [_registration_row("13:09", source="13:05", oid="REG")]
    agreeing = replace(_ref(), registered_at="2026-08-19T13:09:00+00:00",
                       registration_bucket_open="2026-08-19T13:05:00+00:00")
    block, _ = _watch([agreeing], ledger=ledger)
    assert block["watched_lives"][0]["certificate"]["status"] == "INTACT"
    for wrong in (replace(agreeing, registration_bucket_open="2026-08-19T13:00:00+00:00"),
                  replace(_ref(), registration_occurrence_id="REG")):
        block, shadow = _watch([wrong], ledger=ledger)
        certificate = block["watched_lives"][0]["certificate"]
        assert certificate["status"] == "UNKNOWN"
        assert certificate["reason"] == "watched_life_registration_mismatch"
        assert shadow.retained_chains == 0


def test_valid_watch_survives_slot_absence_and_never_inherits_another_failure():
    from dataclasses import replace
    first = _ref()
    successor = replace(_ref(), swing_id="5m:swing_low:29490@13:15",
                        registered_at="2026-08-19T13:15:00+00:00",
                        registration_bucket_open="2026-08-19T13:15:00+00:00")
    rows = _settled(30, overrides=FAIL_AT_0909)
    block, shadow = _watch([first], rows=rows, cutoff="13:29")
    [watched] = block["watched_lives"]
    assert watched["tracker_slot_present"] is False
    assert watched["certificate"]["status"] == "FAILED"
    block, shadow = _watch([first, successor], rows=rows, cutoff="13:29", shadow=shadow)
    by_id = {w["swing_id"]: w["certificate"] for w in block["watched_lives"]}
    assert by_id[first.swing_id]["status"] == "FAILED"
    assert by_id[successor.swing_id]["status"] == "INTACT"
    assert by_id[successor.swing_id]["failure_bucket"] is None
    assert shadow.retained_chains == 2


def test_identical_canonical_sweep_copies_are_one_fact():
    sweep = _sweep_row("13:05")
    rows = [sweep, copy.deepcopy(sweep), _registration_row()]
    [life] = _inventory(rows, _slots())
    assert life["sweep_occurrence_ids"] == [sweep["occurrence_id"]]
    assert "conflicting_sweep_ids" not in life["join"]
    assert "excluded_associations_at_cutoff" not in life["join"]
    verdict = CP.selection_eligibility(life, {"status": "INTACT"},
                                       protected_by_timeframe=_slots(), ledger_rows=rows,
                                       cutoff="2026-08-19T13:20:00+00:00")
    assert verdict == {"eligible": True, "failures": []}


def test_conflicting_payloads_under_one_canonical_id_are_refused_not_picked():
    sweep = _sweep_row("13:05")
    other = copy.deepcopy(sweep)
    other["source_bars"] = []
    resweep = _sweep_row("13:15")
    rows = [sweep, other, resweep, _registration_row()]
    [life] = _inventory(rows, _slots())
    assert life["sweep_occurrence_ids"] == [resweep["occurrence_id"]]
    assert life["join"]["conflicting_sweep_ids"] == [sweep["occurrence_id"]]
    assert life["join"]["excluded_associations_at_cutoff"] == 1
    verdict = CP.selection_eligibility(life, {"status": "INTACT"},
                                       protected_by_timeframe=_slots(), ledger_rows=rows,
                                       cutoff="2026-08-19T13:20:00+00:00")
    assert verdict["failures"] == ["V7"]
    alone = [sweep, other, _registration_row()]
    [life] = _inventory(alone, _slots())
    assert life["sweep_occurrence_ids"] == []
    assert life["join"]["conflicting_sweep_ids"] == [sweep["occurrence_id"]]
    verdict = CP.selection_eligibility(life, {"status": "INTACT"},
                                       protected_by_timeframe=_slots(), ledger_rows=alone,
                                       cutoff="2026-08-19T13:20:00+00:00")
    assert verdict["failures"] == ["V1", "V7"]


# ── STAGE 3C-1-R2: canonical copies are judged as of T ─────────────────────
# The market fact (the row without its association) and the life association
# become evidence separately; conflicts are resolved only from what is visible
# at T at each level. Later evidence never changes the projection at T.
LATER = "2026-08-19T13:25:00+00:00"
LATENESS = ("row_observed", "row_source", "association_only")


def _later_copy(current, lateness):
    """A copy of `current` whose `lateness` evidence first exists at 13:25.

    A wholly later row (observed or sourced later) carries a contradictory
    market payload; an association-only copy keeps the market fields identical."""
    later = copy.deepcopy(current)
    later["protected_swing_lifetime"]["observed_at"] = LATER
    if lateness == "row_observed":
        later["observed_at"] = LATER
    elif lateness == "row_source":
        later["source_bar_time"] = LATER
    if lateness != "association_only":
        later["source_bars"] = []
    return later


def _orders(current, other):
    return ([current, other, _registration_row()], [other, current, _registration_row()])


def _verdict(life, rows, cutoff):
    return CP.selection_eligibility(life, {"status": "INTACT"},
                                    protected_by_timeframe=_slots(), ledger_rows=rows,
                                    cutoff=f"2026-08-19T{cutoff}:00+00:00")


@pytest.mark.parametrize("lateness", LATENESS)
def test_a_later_copy_never_changes_the_projection_at_t(lateness):
    current = _sweep_row("13:05")
    before = _inventory([current, _registration_row()], _slots())
    for rows in _orders(current, _later_copy(current, lateness)):
        at = _inventory(rows, _slots())
        assert at == before
        assert _verdict(at[0], rows, "13:20") == {"eligible": True, "failures": []}


@pytest.mark.parametrize("cutoff", ["13:24", "13:25", "13:26"])
@pytest.mark.parametrize("lateness", LATENESS)
def test_a_later_copy_becomes_evidence_exactly_when_it_is_available(lateness, cutoff):
    current = _sweep_row("13:05")
    before = _inventory([current, _registration_row()], _slots(), cutoff=cutoff)
    for rows in _orders(current, _later_copy(current, lateness)):
        [life] = _inventory(rows, _slots(), cutoff=cutoff)
        if cutoff < "13:25":
            assert [life] == before
            continue
        # visible now, and it differs (market fact or association): refused
        assert life["sweep_occurrence_ids"] == []
        assert life["join"]["conflicting_sweep_ids"] == [current["occurrence_id"]]
        assert _verdict(life, rows, cutoff)["failures"] == ["V1", "V7"]


@pytest.mark.parametrize("cutoff", ["13:20", "13:26"])
def test_a_current_market_conflict_is_refused_though_its_association_is_later(cutoff):
    current = _sweep_row("13:05")
    conflicting = copy.deepcopy(current)
    conflicting["source_bars"] = []
    conflicting["protected_swing_lifetime"]["observed_at"] = LATER
    for rows in _orders(current, conflicting):
        [life] = _inventory(rows, _slots(), cutoff=cutoff)
        assert life["sweep_occurrence_ids"] == []
        assert life["join"]["conflicting_sweep_ids"] == [current["occurrence_id"]]
        assert _verdict(life, rows, cutoff)["failures"] == ["V1", "V7"]


@pytest.mark.parametrize("cutoff", ["13:20", "13:26"])
def test_identical_copies_stay_one_fact_at_every_cutoff(cutoff):
    current = _sweep_row("13:05")
    before = _inventory([current, _registration_row()], _slots(), cutoff=cutoff)
    for rows in _orders(current, copy.deepcopy(current)):
        assert _inventory(rows, _slots(), cutoff=cutoff) == before


def test_no_observational_equivalence_is_assumed():
    # identical except the row's own observation time: invisible at 13:20,
    # a different visible payload from 13:25 on (the current-conflict law)
    current = _sweep_row("13:05")
    later = copy.deepcopy(current)
    later["observed_at"] = LATER
    rows = [current, later, _registration_row()]
    assert _inventory(rows, _slots()) == _inventory([current, _registration_row()], _slots())
    [life] = _inventory(rows, _slots(), cutoff="13:25")
    assert life["join"]["conflicting_sweep_ids"] == [current["occurrence_id"]]


@pytest.mark.parametrize("cutoff", ["13:20", "13:30"])
def test_a_copy_with_a_later_event_time_is_not_that_canonical_fact(cutoff):
    # the canonical id binds the event instant, so a row claiming the 13:05 id
    # with a 13:25 event time is not a copy of that fact at any cutoff
    current = _sweep_row("13:05")
    moved = copy.deepcopy(current)
    moved["event_time"] = LATER
    moved["source_bars"] = []
    before = _inventory([current, _registration_row()], _slots(), cutoff=cutoff)
    for rows in _orders(current, moved):
        assert _inventory(rows, _slots(), cutoff=cutoff) == before


def test_a_later_association_to_another_life_is_not_used_at_t():
    current = _sweep_row("13:05")
    later = copy.deepcopy(current)
    later["protected_swing_lifetime"].update(
        swing_id="5m:swing_low:29490:later", registered_at="2026-08-19T13:19:00+00:00",
        observed_at=LATER)
    rows = [later, current, _registration_row()]
    assert _inventory(rows, _slots()) == _inventory([current, _registration_row()], _slots())
    # alone, an association not yet observed is not evidence of any life
    assert _inventory([later, _registration_row()], _slots()) == []
    # at 13:25 both associations are evidence: each named life carries the conflict
    lives = _inventory(rows, _slots(), cutoff="13:25")
    assert [r["swing_id"] for r in lives] == ["5m:swing_low:29490", "5m:swing_low:29490:later"]
    for life in lives:
        assert life["sweep_occurrence_ids"] == []
        assert life["join"]["conflicting_sweep_ids"] == [current["occurrence_id"]]


def test_a_later_separate_sweep_leaves_the_projection_at_t_byte_identical():
    current, registration = _sweep_row("13:05"), _registration_row()
    before = _inventory([current, registration], _slots())
    later = _sweep_row("13:15", registered="13:19", observed="13:25")
    unseen = _sweep_row("13:15", registered="13:19", observed="13:19")
    unseen["observed_at"] = LATER
    for extra in (later, unseen):
        assert _inventory([current, extra, registration], _slots()) == before


def test_shadow_block_at_t_ignores_a_later_copy():
    current = _sweep_row("13:05")
    later = _later_copy(current, "row_observed")
    plain, _ = _watch([], rows=_settled(21), slots=_slots(),
                      ledger=[current, _registration_row()], cutoff="13:20")
    mixed, _ = _watch([], rows=_settled(21), slots=_slots(),
                      ledger=[current, later, _registration_row()], cutoff="13:20")
    assert mixed == plain
    [life] = mixed["lives"]
    assert life["sweep_occurrence_ids"] == [current["occurrence_id"]]


# Real-producer shape (synthetic W4 tape, independently replayed at 14:37): the
# canonical 15m sweep sourced 14:00 and its exact low 29494, registered 14:14
# from the settled 14:00..14:14 birth bucket, with its slot present.
W4_STAMP = "2026-08-19T{}:00+00:00".format
W4_SWEEP = {
    "occurrence_id": market_object_id("LIQUIDITY_SWEEP", contract=C, timeframe="15m",
                                      instant=W4_STAMP("14:00")),
    "event_type": "LIQUIDITY_SWEEP", "contract": C, "source_tf": "15m",
    "event_time": W4_STAMP("14:00"), "sweep_direction": "below_low",
    "liquidity_side_taken": "sell_side", "swept_level": 29494.0, "reclaimed": True,
    "reclaimed_at": W4_STAMP("14:00"), "reclaim_basis": "same_bar_close_back_through_level",
    "source_bars": [W4_STAMP("13:45"), W4_STAMP("14:00")],
    "protected_swing_lifetime": {
        "contract": C, "market_session": SESSION, "source_tf": "15m", "side": "low",
        "swing_id": "15m:swing_low:29494", "registered_at": W4_STAMP("14:14"),
        "level": 29494.0, "basis": "sell_side_raid_rejected",
        "observed_at": W4_STAMP("14:14"),
        "sweep_occurrence_id": market_object_id("LIQUIDITY_SWEEP", contract=C,
                                                timeframe="15m", instant=W4_STAMP("14:00"))},
}
W4_REGISTRATION = {
    "occurrence_id": ("PROTECTED_SWING_REGISTERED:" + C + ":15m:2026-08-19T14:14:00+00:00:"
                      "low@29494.0:15m:swing_low:29494@2026-08-19T14:14:00+00:00"),
    "event_type": "PROTECTED_SWING_REGISTERED", "contract": C, "source_tf": "15m",
    "event_time": W4_STAMP("14:14"), "side": "low", "level": 29494.0,
    "basis": "sell_side_raid_rejected", "swing_id": "15m:swing_low:29494",
    "registered_at": W4_STAMP("14:14"), "source_bar_time": W4_STAMP("14:00"),
    "settled_edge_time": W4_STAMP("14:14"), "observed_at": W4_STAMP("14:14")}
W4_SLOTS = {"lows": {"15m": {"level": 29494.0, "timeframe": "15m", "role": "context",
                             "registered_at": W4_STAMP("14:14"),
                             "swing_id": "15m:swing_low:29494",
                             "basis": "sell_side_raid_rejected"}}, "highs": {}}


def _w4(rows):
    lives = CP.life_inventory(ledger_rows=rows, protected_by_timeframe=W4_SLOTS,
                              contract_id=C, market_session=SESSION, cutoff=W4_STAMP("14:37"))
    [life] = lives
    verdict = CP.selection_eligibility(life, {"status": "INTACT"},
                                       protected_by_timeframe=W4_SLOTS, ledger_rows=rows,
                                       cutoff=W4_STAMP("14:37"))
    return life, verdict


@pytest.mark.parametrize("variant", ["row_later", "association_only",
                                     "current_conflict", "current_conflict_future_association"])
def test_w4_shaped_life_at_1437_against_a_duplicate_of_its_sweep(variant):
    current = copy.deepcopy(W4_SWEEP)
    before, verdict = _w4([current, W4_REGISTRATION])
    assert before["sweep_occurrence_ids"] == [current["occurrence_id"]]
    assert verdict == {"eligible": True, "failures": []}
    dup = copy.deepcopy(current)
    if variant != "current_conflict":
        dup["protected_swing_lifetime"]["observed_at"] = W4_STAMP("14:45")
    if variant == "row_later":
        dup["observed_at"] = W4_STAMP("14:45")
    if variant != "association_only":
        dup["source_bars"] = []
    for rows in ([current, dup, W4_REGISTRATION], [dup, current, W4_REGISTRATION]):
        life, verdict = _w4(rows)
        if variant in ("row_later", "association_only"):
            assert life == before
            assert verdict == {"eligible": True, "failures": []}
        else:
            assert life["sweep_occurrence_ids"] == []
            assert life["join"]["conflicting_sweep_ids"] == [current["occurrence_id"]]
            assert verdict["failures"] == ["V1", "V7"]
