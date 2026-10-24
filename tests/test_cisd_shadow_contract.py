"""Policy-independent tests of the PROPOSED CISD fact contract (shadow only).

These hold whichever owner choice O1-O9 is ratified: settled availability,
exact identity, prefix/restart determinism, fail-closed input, and that no
production authority route accepts the family. The archived-tape case is the
2026-10-23 recorded December-contract tape (fixture provenance), read as facts;
it is not a recognition, entry or fill claim. Mutated rows are labelled
FICTIONAL.
"""
import copy
import importlib.util
import json
import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "cisd_shadow", ROOT / "docs/recognition_validation/cisd/cisd_shadow.py")
CISD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CISD)

CONTRACT = "CON.F.US.MNQ.Z26"
TAPE = json.loads((ROOT / "tests/fixtures/session_20261023_bearing_handoff.json")
                  .read_text())["tape"]
EXTREME = "2026-10-23T16:00:00+00:00"   # 12:00 ET 5m bucket, high 29306.0


def z(hhmm):
    return f"2026-10-23T{hhmm}:00+00:00"


def detect(bars=None, *, through="16:25", direction="bearish", extreme=EXTREME, **policy):
    return CISD.detect_cisd(TAPE if bars is None else bars, minutes=5, direction=direction,
                            extreme_at=extreme, settled_through=z(through),
                            contract=CONTRACT, policy=policy or None)


def edit(minute, **fields):
    """FICTIONAL: a copy of the archived tape with one minute changed."""
    bars = copy.deepcopy(TAPE)
    row = next(b for b in bars if b["timestamp"] == z(minute))
    row.update(fields)
    row["high"] = max(row["high"], row["open"], row["close"])
    row["low"] = min(row["low"], row["open"], row["close"])
    return bars


def test_archived_tape_buckets_match_the_recorded_5m_candles():
    buckets = {b["open_time"]: b for b in CISD.settled_buckets(TAPE, 5, z("16:25"))}
    b = buckets[z("16:20")]
    assert (b["open"], b["high"], b["low"], b["close"]) == (29241.75, 29249.5, 29204.0, 29215.25)
    assert b["available_at"] == z("16:25")
    assert buckets[z("15:45")]["open"] == 29231.75


def test_archived_tape_bearish_cisd_is_the_1220_close_through_the_1145_run_open():
    out = detect()
    assert out["status"] == "CONFIRMED"
    assert out["run"] == {"first_open_time": z("15:45"), "last_open_time": z("15:55"),
                          "buckets": 3, "anchor_open": 29231.75, "extreme": 29306.0,
                          "extreme_open_time": EXTREME}
    assert out["event"] == {"break_open_time": z("16:20"), "break_close": 29215.25,
                            "available_at": z("16:25")}
    assert out["occurrence_id"] == (f"cisd_body_open_break:{CONTRACT}:5m:bearish:"
                                    f"{z('15:45')}:29231.75:{z('16:20')}")
    assert out["authority"] == {"enabled": False, "status": "UNPROVEN",
                                "reason": "owner_route_unratified"}


def test_forming_break_bucket_is_never_a_fact():
    out = detect(through="16:24")
    assert out["status"] == "PENDING" and "event" not in out
    assert z("16:20") not in {b["open_time"] for b in CISD.settled_buckets(TAPE, 5, z("16:24"))}


def test_every_cutoff_prefix_replay_and_restart_order_agree_and_confirmation_is_immutable():
    rng = random.Random(20261023)
    confirmed = None
    for minute in range(16 * 60 + 5, 17 * 60 + 16):
        hhmm = f"{minute // 60:02d}:{minute % 60:02d}"
        full = detect(through=hhmm)
        prefix = detect([b for b in TAPE if b["timestamp"] < z(hhmm)], through=hhmm)
        shuffled = TAPE[:]
        rng.shuffle(shuffled)
        assert full == prefix == detect(shuffled, through=hhmm), hhmm
        if confirmed is None and full["status"] == "CONFIRMED":
            confirmed = full
            assert hhmm == "16:25"
        if confirmed is not None:
            assert full == confirmed, hhmm
        else:
            assert full["status"] == "PENDING", hhmm
    assert confirmed is not None


def test_missing_constituent_minute_never_settles_the_break_bucket():
    bars = [b for b in TAPE if b["timestamp"] != z("16:22")]
    assert detect(bars, through="16:25")["status"] == "PENDING"
    late = detect(bars, through="16:40")
    assert late["status"] == "UNAVAILABLE" and late["reason"] == "tape_gap"
    assert late["gap_after"] == z("16:15")


def test_strict_boundary_equal_close_is_not_a_break():
    bars = edit("16:24", close=29231.75)          # FICTIONAL
    strict = detect(bars, through="16:30")
    assert strict["status"] == "CONFIRMED" and strict["event"]["break_open_time"] == z("16:25")
    inclusive = detect(bars, through="16:30", boundary="INCLUSIVE")
    assert inclusive["event"]["break_open_time"] == z("16:20")


def test_new_extreme_before_the_break_supersedes_the_selected_extreme():
    bars = edit("16:12", high=29310.0)            # FICTIONAL
    out = detect(bars)
    assert out["status"] == "SUPERSEDED" and out["superseded_at"] == z("16:15")


def test_mirror_tape_gives_the_symmetric_bullish_fact():
    mirror = [{"timestamp": b["timestamp"], "open": -b["open"], "high": -b["low"],
               "low": -b["high"], "close": -b["close"]} for b in TAPE]
    out = detect(mirror, direction="bullish")
    assert out["status"] == "CONFIRMED"
    assert out["run"]["anchor_open"] == -29231.75 and out["run"]["extreme"] == -29306.0
    assert out["event"]["break_open_time"] == z("16:20")


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(open=True), lambda b: b.update(close=float("nan")),
    lambda b: b.update(timestamp="2026-10-23T16:21:00"), lambda b: b.update(timestamp=z("16:20")),
    lambda b: b.update(high=b["low"] - 1.0)],
    ids=["bool", "nan", "naive", "duplicate", "high_below_low"])
def test_unreadable_tape_refuses_whole_request(mutate):
    bars = copy.deepcopy(TAPE)
    mutate(next(b for b in bars if b["timestamp"] == z("16:21")))
    out = detect(bars)
    assert out["status"] == "UNAVAILABLE" and out["reason"] == "tape_unreadable"


def test_extreme_must_be_settled_and_maximal_over_its_run():
    assert detect(extreme=z("16:05"))["reason"] == "extreme_not_maximal"   # 16:00 printed higher
    assert detect(extreme=z("15:55"))["reason"] == "new_extreme_before_break"
    assert detect(extreme=z("16:30"))["reason"] == "extreme_bucket_not_settled"
    assert detect(direction="sideways")["reason"] == "invalid_request"


def test_production_authority_route_rejects_the_family_and_d3_is_unchanged():
    from ai_brain.narrative_continuity import _authoritative_opposing_origin, _transfer_proof
    from market_data.campaign_scope import POLICY

    def path(family):
        return {"state_available": True, "owner": "bearish", "status": "active",
                "last_invalidated": {"owner": "bullish", "at": z("16:10")},
                "origin": {"proof_family": family, "event": "buy_side_raid_rejected",
                           "direction": "bearish", "at": z("16:25")},
                "progression": {"supporting_timeframes": ["5m"]},
                "load_bearing_structure": {"level": 29249.5, "side": "high", "intact": True}}

    assert _transfer_proof(path("rejected_raid_reclaim"), "bullish", "bearish")["status"] == "verified"
    assert _authoritative_opposing_origin(path(CISD.FAMILY)["origin"], "bearish") is False
    assert _transfer_proof(path(CISD.FAMILY), "bullish", "bearish") is None
    assert (POLICY["roles"], POLICY["k"], POLICY["scope"], POLICY["time"], POLICY["bearing"]) == (
        ["5m", "15m"], 1, "B", "STRICT", "INDEPENDENT_SUPPORTING_LIFE")
    mentions = [p for p in (ROOT / "src").rglob("*.py")
                if "cisd_shadow" in p.read_text(encoding="utf-8")
                or CISD.FAMILY in p.read_text(encoding="utf-8")]
    assert mentions == []
