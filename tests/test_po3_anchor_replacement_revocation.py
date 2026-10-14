"""A replaced PO3 anchor revokes the formation alone; the campaign keeps participating.

Stage 4 obligation C (formation-only revocation at the candidate boundary).
Codex's natural W5 seed plus the S4I p2h bars: the bearish campaign (premise:
the 5m protected high 29519.75, registered 14:29) is ACTIVE, and the PO3
formation raiding that same 5m high is retained from 14:59. The declared
lawful 1m bars after 15:02 then differ in ONE bar:

  * REPLACED: 15:03 wicks to 29539 and closes 29509 back below. When its 5m
    bucket settles (15:04 scan) the 5m sweep of the 29538 swing high is the
    published structural pivot, so the 5m protected slot is REPLACED
    29519.75 -> 29538 and the formation's anchor life has ended.
  * HEALTHY twin: 15:03 stays at 29511.5, the slot keeps 29519.75.

The 15:02 high (29514) is the 1m pivot both twins share, so the 15:06-15:12
retrace closes below it on both tapes: no opposing structure break, and the
Draw objective (sell side 29504.75) is not reached. The campaign is therefore
equally alive on both tapes -- scope ACTIVE, premise certificate INTACT (v3
contract 4.7: a bound premise is not retired by replacement), incumbent
intact, Lifecycle ACTIVE_DELIVERY with participation permitted -- and the
formation is the ONLY difference. The mocked Brain is adversarial: it keeps
naming the retained formation's exact identity after the anchor is replaced.
The healthy twin executes it; the replaced twin refuses at the PO3 tool
boundary, never at Lifecycle.

Bars are lawful synthetic OHLC appended to Codex's fixed natural W5 seed. The
Brain transport is mocked; quotes follow the settled close.
"""
from datetime import datetime, timedelta, timezone

import pytest

import test_campaign_scope as T
import test_campaign_scope_binding as B
import test_po3_execution_identity as X
import test_po3_post_settlement_death as D
import test_reversal_foundation_proof_closure as RF
from broker.luna_candidate_producer import NoCandidate
from market_data.campaign_scope import read_current_campaign_scope

FORMATION_ID = X.EXPECTED_ID
PO3 = "po3_reversal_order_block"

_HEALTHY = [("15:02", 29514.0, 29509.5, 29511.0) if row[0] == "15:02" else row for row in X._P2H] + [
    ("15:05", 29510.0, 29505.5, 29509.5), ("15:06", 29513.5, 29509.0, 29513.0),
    ("15:07", 29513.75, 29511.5, 29513.25), ("15:08", 29513.5, 29511.0, 29512.75),
    ("15:09", 29513.75, 29511.0, 29513.0), ("15:10", 29513.5, 29511.5, 29513.25),
    ("15:11", 29513.75, 29511.5, 29513.0), ("15:12", 29513.5, 29511.0, 29512.75)]
_REPLACED = [("15:03", 29539.0, 29508.0, 29509.0) if row[0] == "15:03" else row for row in _HEALTHY]
ENTRIES = {"15:06": 29513.0, "15:07": 29513.25, "15:08": 29512.75, "15:09": 29513.0,
           "15:10": 29513.25, "15:11": 29513.0, "15:12": 29512.75}


def _reply(output, ordinal, payload, entry, chosen):
    """MOCKED, ADVERSARIAL Brain: the W5 establish/activate/first-candidate
    replies, then a bearish entry naming the executable PO3 occurrence when one
    exists and the retained formation's exact identity when none does (nearest
    protected high above as stop, lowest objective below)."""
    if ordinal <= 3:
        return B._w5_reply(output, ordinal, payload, entry=entry)
    stops = [r for r in payload.get("authorized_invalidations", [])
             if isinstance(r.get("price"), (int, float)) and r["price"] > entry]
    targets = [r for r in payload.get("authorized_objectives", [])
               if isinstance(r.get("price"), (int, float)) and r["price"] < entry]
    po3 = [r["occurrence_id"] for r in payload.get("authorized_tool_catalog", [])
           if r.get("tool_family") == PO3 and r.get("direction") == "bearish"
           and r.get("execution_eligible") is True and r.get("occurrence_id")]
    output.update(narrative_direction="bearish", allowed_direction="bearish", forbidden_direction="bullish",
                  narrative_phase="continuation", active_draw="sell side liquidity below",
                  market_story="Bearish campaign: buy side raid rejected, structure delivering lower.",
                  dominant_reasoning=("After the buy side liquidity raid and reclaimed rejection, market structure "
                                      "shifted bearish and displacement delivered lower toward sell side liquidity."))
    if stops and targets:
        stop, target = min(stops, key=lambda r: r["price"]), min(targets, key=lambda r: r["price"])
        chosen[ordinal] = po3[0] if po3 else FORMATION_ID
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
    tape = D._tape(seq)
    px = [tape[0]["close"]]

    def quote():
        return QuoteCapture(captured_at=datetime.now(timezone.utc), best_bid=px[0], best_ask=px[0] + .25,
                            last_trade=px[0], contract_id=T.CONTRACT, market_data_age_seconds=.25)
    cycle = ProductionScanCycle(symbol="MNQ", contract_id=T.CONTRACT, session_id="S4-C-ACTIVE",
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
        hm = D._hm(snap["timestamp"])
        if hm < "14:44":
            continue
        scope = read_current_campaign_scope(snap) or {}
        campaign = scope.get("campaign") or {}
        continuity = (result.get("brain_block") or {}).get("narrative_continuity") or {}
        output = (result.get("brain_block") or {}).get("output") or {}
        lifecycle = result.get("campaign_lifecycle") or {}
        facts = D._facts(result, cycle)
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
            "premise": (continuity.get("campaign_premise") or {}).get("status"),
            "lifecycle": (lifecycle.get("state"), lifecycle.get("participation_permitted")),
            "named": output.get("recommended_tool_occurrence_id"),
            "anchor_5m": facts["anchor_5m"],
            "custody": facts["custody"],
            "executable": [row[1] for row in facts["catalog"] if row[0] is True],
            "candidate": outcome,
        }
    return out


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_replaced_anchor_revokes_the_formation_while_the_campaign_participates(tmp_path, monkeypatch, ecu):
    healthy = _active(tmp_path / "healthy", monkeypatch, _HEALTHY, ecu=ecu)
    replaced = _active(tmp_path / "replaced", monkeypatch, _REPLACED, ecu=ecu)
    assert sorted(healthy) == sorted(replaced) and "15:12" in healthy
    active = ("ACTIVE", "ACTIVE", "bearish", "INTACT", 29519.75)
    for lane in (healthy, replaced):
        # The campaign is equally alive on both tapes, before and after the
        # replacement: the bound premise is never retired by it.
        for hm, row in lane.items():
            assert row["scope"] == active, hm
            assert row["control"] == "incumbent_intact", hm
            assert row["premise"] == "INTACT", hm
        # Both retain the same formation before the replacement settles.
        for hm in ("14:59", "15:00", "15:01", "15:02", "15:03"):
            assert lane[hm]["custody"] == FORMATION_ID, hm
            assert lane[hm]["anchor_5m"] == 29519.75, hm
    # The replacement is the only difference, published when its 5m bucket
    # settles on the 15:04 scan ...
    for hm in [hm for hm in healthy if hm >= "15:04"]:
        assert healthy[hm]["anchor_5m"] == 29519.75, hm
        assert replaced[hm]["anchor_5m"] == 29538.0, hm
        assert healthy[hm]["custody"] == FORMATION_ID, hm
        assert replaced[hm]["custody"] is None, hm
        assert replaced[hm]["executable"] == [], hm
        # ... and Lifecycle reads both tapes identically every minute.
        assert replaced[hm]["lifecycle"] == healthy[hm]["lifecycle"], hm
    # In the retrace Lifecycle PERMITS participation on both tapes; the Brain
    # names the same formation on both. Only the healthy twin executes it.
    for hm, entry in ENTRIES.items():
        assert healthy[hm]["lifecycle"] == replaced[hm]["lifecycle"] == ("ACTIVE_DELIVERY", True), hm
        assert healthy[hm]["named"] == replaced[hm]["named"] == FORMATION_ID, hm
        assert healthy[hm]["executable"] == [FORMATION_ID], hm
        assert healthy[hm]["candidate"] == ("CANDIDATE", FORMATION_ID, entry, 29519.25), hm
        assert replaced[hm]["candidate"] == ("NoCandidate", "tool_not_detected"), hm
