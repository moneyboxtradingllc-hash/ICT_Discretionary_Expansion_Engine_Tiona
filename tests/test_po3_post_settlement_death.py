"""PO3 leg death AFTER the raid settles and BEFORE validation; leg vs campaign.

Stage 4 obligation B. Codex's natural W5 seed through 14:45 plus the S4I p2h
bars 14:46-14:49: the 14:45 5m bucket raids the 5m protected high 29519.75
(the bearish campaign premise, registered 14:29) and closes back below it, so
the 5m buy-side raid has source time 14:45 and is SETTLED (first published) on
the 14:49 scan. The declared lawful 1m bars after it then build, in order:

  * 14:52 a 1m swing high 29518 (confirmed 14:55);
  * 14:56 a rejected 1m buy-side raid of it: the 1m protected slot is replaced
    29519.25 -> 29518 and the bearish ActivePath load-bearing becomes the 1m
    high 29518, which lies between price and the 5m anchor;
  * DEATH: 14:58 closes 29518.5 above it, a genuine bearish release with
    source and observation time 14:58 -- after the raid settled (14:49) and
    before validation, while every 5m close stays below the anchor;
  * 15:00-15:04 the 5m bucket closes below the run body (validation 15:00,
    first visible on the 15:04 scan), 15:05-15:10 retrace into the block.

The HEALTHY twin differs only in the 14:58 bar, which wicks to 29519 but closes
29517.75 below 29518: no release. The detector sees identical geometry (raid
14:45, validation 15:00) on both tapes. Only the healthy producer retains the
formation; with an ACTIVE bearish campaign it executes, while the dead leg
stands the campaign down as an unresolved transfer even though the campaign
premise stays intact (a leg death is not a campaign death, and the later
retracement is not a transfer).

Bars are lawful synthetic OHLC appended to Codex's fixed natural W5 seed. The
Brain transport is mocked; quotes follow the settled close.
"""
import copy
from datetime import datetime, timedelta, timezone

import pytest

import test_campaign_scope as T
import test_campaign_scope_binding as B
import test_po3_execution_identity as X
import test_reversal_foundation_proof_closure as RF
from broker.luna_candidate_producer import NoCandidate
from market_data.campaign_scope import read_current_campaign_scope
from market_data.reversal_formation import current_block
from toolbox.price_levels import _detect_current_po3_reversal_order_block

FORMATION_ID = ("PO3_REVERSAL_ORDER_BLOCK:CON.F.US.MNQ.Z26:5m:2026-08-19T15:00:00+00:00:"
                "bearish:LIQUIDITY_SWEEP:CON.F.US.MNQ.Z26:5m:2026-08-19T14:45:00+00:00:"
                "5m:swing_high:29519.8:2026-08-19T14:29:00+00:00")
UNAVAILABLE = X.UNAVAILABLE
PO3 = "po3_reversal_order_block"

_DEATH = [row for row in X._P2H if row[0] <= "14:49"] + [
    ("14:50", 29517.0, 29514.0, 29515.0), ("14:51", 29516.5, 29513.0, 29514.0),
    ("14:52", 29518.0, 29514.5, 29517.5), ("14:53", 29517.0, 29514.0, 29515.0),
    ("14:54", 29516.5, 29513.5, 29514.5), ("14:55", 29516.0, 29513.0, 29514.0),
    ("14:56", 29518.75, 29514.5, 29516.0), ("14:57", 29517.5, 29515.0, 29516.5),
    ("14:58", 29519.0, 29516.0, 29518.5), ("14:59", 29518.5, 29515.0, 29515.5),
    ("15:00", 29516.0, 29511.0, 29512.0), ("15:01", 29512.5, 29508.0, 29509.0),
    ("15:02", 29509.5, 29505.5, 29506.0), ("15:03", 29507.0, 29504.0, 29504.5),
    ("15:04", 29505.5, 29503.0, 29503.5), ("15:05", 29507.0, 29503.0, 29506.5),
    ("15:06", 29511.0, 29506.0, 29510.5), ("15:07", 29512.0, 29509.5, 29511.0),
    ("15:08", 29511.5, 29508.0, 29508.5), ("15:09", 29509.0, 29505.0, 29505.5),
    ("15:10", 29506.0, 29503.5, 29504.0)]
_HEALTHY = [("14:58", 29519.0, 29516.0, 29517.75) if row[0] == "14:58" else row for row in _DEATH]
DEATH = ("bearish", "1m", "14:58", "14:58", "1m:swing_high:29518", "14:56")


def _tape(seq):
    head = T._tape()[:106]
    return head + X._bars(seq, head[-1]["close"])


def _hm(stamp):
    return str(stamp or "")[11:16]


def _facts(scan, cycle):
    snap = scan["snapshot"]
    block = current_block(snap, "bearish")
    detected = _detect_current_po3_reversal_order_block(snap, "bearish")
    liquidity = snap.get("liquidity") or {}
    highs = ((snap.get("protected_swings") or {}).get("by_timeframe") or {}).get("highs") or {}
    return {
        "custody": ((block or {}).get("formation_authority") or {}).get("occurrence_id") if block else None,
        "catalog": [(r["execution_eligible"], r["occurrence_id"], r["execution_ineligible_reason"])
                    for r in X._po3(snap)],
        "detected": ((detected.get("validation_timestamp"), (detected.get("sweep_evidence") or {})
                      .get("event_time")) if detected.get("available") else None),
        "raid_5m": (((liquidity.get("5m") or {}).get("sweep_fact") or {}).get("event_time")
                    if (liquidity.get("5m") or {}).get("sweep_detected") else None),
        "releases": [(r.get("owner"), r.get("source_tf"), _hm(r.get("source_bar_time")), _hm(r.get("at")),
                      r.get("swing_id"), _hm(r.get("registered_at")))
                     for r in cycle._active_path.releases
                     if str(r.get("source_bar_time")) >= "2026-08-19T14:40"],
        "load_bearing": ((cycle._active_path.load_bearing or {}).get("level"),
                         (cycle._active_path.load_bearing or {}).get("timeframe")),
        "path": ((snap.get("active_path_state") or {}).get("owner"),
                 (snap.get("active_path_state") or {}).get("status")),
        "anchor_5m": (highs.get("5m") or {}).get("level"),
        "high_1m": ((highs.get("1m") or {}).get("level"), _hm((highs.get("1m") or {}).get("registered_at"))),
    }


def _brainless(root, monkeypatch, seq):
    from live_scan.production_scan_cycle import ProductionScanCycle
    root.mkdir()
    X._isolate(root, monkeypatch)
    tape = _tape(seq)
    cycle = ProductionScanCycle(symbol="MNQ", contract_id=T.CONTRACT, session_id="S4-B")
    out = {}
    for end in range(20, len(tape) + 1):
        bars = tape[:end]
        scan = cycle.scan(bars, now=datetime.fromisoformat(bars[-1]["timestamp"]) + timedelta(minutes=1),
                          invoke_brain=False)
        if bars[-1]["timestamp"] >= "2026-08-19T14:44":
            out[_hm(bars[-1]["timestamp"])] = _facts(scan, cycle)
    return out


def test_post_settlement_leg_death_retires_the_formation_before_it_is_born(tmp_path, monkeypatch):
    death = _brainless(tmp_path / "death", monkeypatch, _DEATH)
    healthy = _brainless(tmp_path / "healthy", monkeypatch, _HEALTHY)
    for lane in (death, healthy):
        # The 5m raid (source 14:45) is first published when its bucket settles.
        assert lane["14:48"]["raid_5m"] is None
        assert lane["14:49"]["raid_5m"] == "2026-08-19T14:45:00+00:00"
        # 14:56: the 1m slot is replaced by the raided 1m pivot and the
        # bearish leg now rests on it, below the 5m anchor.
        assert lane["14:55"]["high_1m"] == (29519.25, "14:39")
        assert lane["14:56"]["high_1m"] == (29518.0, "14:56")
        assert lane["14:56"]["load_bearing"] == (29518.0, "1m")
        assert lane["14:57"]["path"] == ("bearish", "active")
        # The anchor is never closed through: no anchor invalidation.
        assert all(row["anchor_5m"] == 29519.75 for row in lane.values())
        # Identical detector geometry: raid 14:45, validation 15:00, first
        # visible on the 15:04 scan.
        assert lane["15:03"]["detected"] is None
        for hm in ("15:04", "15:05", "15:06", "15:07", "15:08"):
            assert lane[hm]["detected"] == ("2026-08-19T15:00:00+00:00",
                                            "2026-08-19T14:45:00+00:00"), hm
    # The dead leg: source and observation 14:58, after settlement (14:49) and
    # before validation (15:00). The healthy twin never releases.
    assert death["14:57"]["releases"] == []
    assert death["14:58"]["releases"] == [DEATH]
    assert death["14:58"]["path"] == ("none", "none")
    assert all(row["releases"] == [] for row in healthy.values())
    # Only the healthy producer retains, and only from first visibility.
    for hm, row in healthy.items():
        expected = FORMATION_ID if hm >= "15:04" else None
        assert row["custody"] == expected, hm
    for hm in ("15:04", "15:05", "15:06", "15:07", "15:08"):
        assert healthy[hm]["catalog"] == [(True, FORMATION_ID, None)], hm
        assert death[hm]["catalog"] == [(False, None, UNAVAILABLE)], hm
    assert all(row["custody"] is None for row in death.values())


def _reply(output, ordinal, payload, entry, chosen):
    """MOCKED Brain: the W5 establish/activate/first-candidate replies, then a
    bearish entry naming the current executable PO3 occurrence (nearest
    protected high above as stop, lowest objective below), else watching."""
    if ordinal <= 3:
        return B._w5_reply(output, ordinal, payload, entry=entry)
    stops = [r for r in payload.get("authorized_invalidations", [])
             if isinstance(r.get("price"), (int, float)) and r["price"] > entry]
    targets = [r for r in payload.get("authorized_objectives", [])
               if isinstance(r.get("price"), (int, float)) and r["price"] < entry]
    po3 = [r for r in payload.get("authorized_tool_catalog", []) if r.get("tool_family") == PO3
           and r.get("direction") == "bearish" and r.get("execution_eligible") is True
           and r.get("occurrence_id")]
    output.update(narrative_direction="bearish", allowed_direction="bearish", forbidden_direction="bullish",
                  narrative_phase="continuation", active_draw="sell side liquidity below",
                  market_story="Bearish campaign: buy side raid rejected, structure delivering lower.",
                  dominant_reasoning=("After the buy side liquidity raid and reclaimed rejection, market structure "
                                      "shifted bearish and displacement delivered lower toward sell side liquidity."))
    if stops and targets and po3:
        stop, target = min(stops, key=lambda r: r["price"]), min(targets, key=lambda r: r["price"])
        chosen[ordinal] = po3[0]["occurrence_id"]
        output.update(current_action="propose_entry", objective_id=target["objective_id"],
                      invalidation_id=stop["invalidation_id"], invalidation_level=stop["price"],
                      recommended_playbook_family="manipulation_to_distribution",
                      recommended_tool_family=[PO3], recommended_tool_occurrence_id=chosen[ordinal])
    else:
        chosen[ordinal] = None
        output.update(current_action="watching", objective_id=None, invalidation_id=None,
                      invalidation_level=None, recommended_playbook_family="none",
                      recommended_tool_family=["none"])
    return output


def _active(root, monkeypatch, seq, *, ecu):
    """REAL W5 ProductionScanCycle; the bearish campaign is proposed (T2),
    activated (T3) and participates (T4) through the unchanged M3/W5 path, then
    the Brain runs every settled minute."""
    from broker.topstepx_slippage import QuoteCapture
    from live_scan.production_scan_cycle import ProductionScanCycle
    root.mkdir()
    X._isolate(root, monkeypatch)
    tape = _tape(seq)
    px = [tape[0]["close"]]

    def quote():
        return QuoteCapture(captured_at=datetime.now(timezone.utc), best_bid=px[0], best_ask=px[0] + .25,
                            last_trade=px[0], contract_id=T.CONTRACT, market_data_age_seconds=.25)
    cycle = ProductionScanCycle(symbol="MNQ", contract_id=T.CONTRACT, session_id="S4-B-ACTIVE",
                                quote_provider=quote)

    def scan(end, brain):
        bars = tape[:end]
        px[0] = bars[-1]["close"]
        return cycle.scan(bars, now=datetime.fromisoformat(bars[-1]["timestamp"]) + timedelta(minutes=1),
                          invoke_brain=brain)
    for end in range(20, 97):
        scan(end, False)
    calls, chosen = [], {}
    RF._mock_current_brain(monkeypatch, calls,
                           output_mutator=lambda out, n, payload: _reply(out, n, payload, px[0], chosen))
    monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
    out = {}
    for end in range(97, len(tape) + 1):
        result = scan(end, True)
        snap = result["snapshot"]
        hm = _hm(snap["timestamp"])
        if hm < "14:44":
            continue
        scope = read_current_campaign_scope(snap) or {}
        campaign = scope.get("campaign") or {}
        continuity = (result.get("brain_block") or {}).get("narrative_continuity") or {}
        output = (result.get("brain_block") or {}).get("output") or {}
        lifecycle = result.get("campaign_lifecycle") or {}
        try:
            candidate = B._candidate(result, cycle)
            outcome = ("CANDIDATE", candidate.extras.get("selected_tool_occurrence_id"),
                       candidate.entry_price, candidate.invalidation_price)
        except NoCandidate as exc:
            outcome = ("NoCandidate", exc.reason)
        out[hm] = {
            "scope": (scope.get("state"), campaign.get("status"), campaign.get("direction"),
                      (campaign.get("certificate") or {}).get("status"),
                      (campaign.get("premise") or {}).get("level")),
            "control": continuity.get("control_state"),
            "leg_failure": continuity.get("active_leg_failure_status"),
            "premise": (continuity.get("campaign_premise") or {}).get("status"),
            "transfer_confirmed": continuity.get("transfer_confirmed"),
            "brain": (output.get("current_action"), output.get("allowed_direction")),
            "lifecycle": (lifecycle.get("state"), lifecycle.get("participation_permitted")),
            "custody": _facts(result, cycle)["custody"],
            "candidate": outcome,
        }
    return out


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_leg_death_is_not_campaign_death_and_never_a_transfer(tmp_path, monkeypatch, ecu):
    healthy = _active(tmp_path / "healthy", monkeypatch, _HEALTHY, ecu=ecu)
    death = _active(tmp_path / "death", monkeypatch, _DEATH, ecu=ecu)
    active = ("ACTIVE", "ACTIVE", "bearish", "INTACT", 29519.75)
    # The campaign (premise 5m 29519.75) is ACTIVE and INTACT on both tapes
    # throughout, before and after the leg dies.
    assert all(row["scope"] == active for row in healthy.values())
    assert all(row["scope"] == active for row in death.values())
    # Healthy: the retained formation executes in the retrace.
    assert healthy["15:06"]["candidate"] == ("CANDIDATE", FORMATION_ID, 29510.5, 29518.0)
    assert healthy["15:07"]["candidate"] == ("CANDIDATE", FORMATION_ID, 29511.0, 29518.0)
    assert all(row["control"] == "incumbent_intact" for row in healthy.values())
    # Death: identical through 14:57 ...
    assert death["14:57"]["lifecycle"] == ("ACTIVE_DELIVERY", True)
    assert death["14:57"]["control"] == healthy["14:57"]["control"] == "incumbent_intact"
    # ... then the leg failure is a developing transfer the campaign stands
    # down on: the premise stays INTACT, no transfer is confirmed, and the
    # 15:01-15:10 retracement (a sell-side raid included) never becomes one.
    for hm, row in death.items():
        if hm < "14:58":
            continue
        assert row["control"] == "developing_transfer", hm
        assert row["leg_failure"] == "occurred", hm
        assert row["premise"] == "INTACT", hm
        assert row["transfer_confirmed"] is False, hm
        assert row["lifecycle"] == ("TRANSFER_UNRESOLVED", False), hm
        assert row["brain"][1] != "bullish", hm
        assert row["custody"] is None, hm
        assert row["candidate"] == ("NoCandidate", "campaign_lifecycle_refused"), hm
