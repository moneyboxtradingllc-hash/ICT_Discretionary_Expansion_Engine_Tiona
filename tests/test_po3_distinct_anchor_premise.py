"""S4-05: a PO3 formation on a DISTINCT anchor life from the campaign premise.

CONSTRUCTED TAPE (mechanical evidence only, never recognition truth). The
fixed natural W5 seed (13:00-14:45, bullish incumbent dies 14:23) is followed
by lawful synthetic 1m OHLC on the 0.25 tick:

  * 15:16 one wick raids the 15m swing high 29538 and closes back below. When
    the 15:15 bucket settles (15:29 scan) the 15m CONTEXT life 29538 is born;
    its raid (15:15) is strictly after the incumbent's death (D3=B STRICT).
  * 15:48 a 5m lower high 29518.5 forms; 16:15 raids it and closes back below.
    The 5m ACTIVE_LEG life 29518.5 is born at 16:19 by replacement of the
    seed's 5m slot, and 16:25 closes below the 16:05 run body with
    displacement: the PO3 formation on that 5m life validates at 16:29.
  * Every 15m close stays above the 13:45-14:00 run body (29505.75), so no
    15m formation on the premise's own life ever validates; the pre-run base
    has equal lows, so no swing low sits between the entry and the Draw.

The mocked Brain establishes the campaign on the 15m premise row (the only
row it may select) and, once the distinct 5m formation is executable, names
that exact occurrence every minute -- adversarially, even after it is gone.
The two twins differ in ONE bar: on REPLACED the 16:36 bar wicks to 29519.5
and closes back below, raiding the newest 5m swing high 29519.0, so when its
bucket settles (16:39 scan) the 5m slot is REPLACED 29518.5 -> 29519.0 and the
formation's anchor life has ended. The 15m premise, scope, Draw and Lifecycle
are untouched on both twins; only the formation differs, and only the PO3
tool gate refuses.
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
from market_data.reversal_formation import current_block

PO3 = "po3_reversal_order_block"
TAPE_CLASS = "CONSTRUCTED"
FORMATION_ID = ("PO3_REVERSAL_ORDER_BLOCK:CON.F.US.MNQ.Z26:5m:2026-08-19T16:25:00+00:00:bearish:"
                "LIQUIDITY_SWEEP:CON.F.US.MNQ.Z26:5m:2026-08-19T16:15:00+00:00:"
                "5m:swing_high:29518.5:2026-08-19T16:19:00+00:00")
PREMISE = ("15m", 29538.0, "2026-08-19T15:29:00+00:00")
ANCHOR = ("5m", 29518.5, "2026-08-19T16:19:00+00:00")
BASE = 29500.0
SEED_BARS = 106          # natural W5 seed through 14:45


def _t(hhmm, k):
    return (datetime(2026, 8, 19, int(hhmm[:2]), int(hhmm[3:])) + timedelta(minutes=k)).strftime("%H:%M")


def _decline(start, n, high):
    return [(_t(start, k), high - .25 * k, high - .25 * k - 1.5, high - .25 * k - 1.0) for k in range(n)]


def _flat(start, n, high, low, close):
    return [(_t(start, k), high, low, close) for k in range(n)]


def _rally(start, highs):
    return [(_t(start, k), high, high - 1.75, high - .25) for k, high in enumerate(highs)]


# (hh:mm, high, low, close) as offsets from BASE; opens are the prior close.
_ROWS = ([("14:46", 21.0, 16.75, 17.0), ("14:47", 21.0, 18.0, 18.5), ("14:48", 19.0, 16.5, 17.0),
          ("14:49", 17.5, 15.5, 16.0)]
         + _decline("14:50", 25, 16.75)
         + [("15:15", 10.5, 9.0, 9.5), ("15:16", 39.0, 9.25, 9.75)]            # raid of the 15m 29538
         + _decline("15:17", 12, 9.75) + _flat("15:29", 12, 7.0, 5.75, 6.0)
         + _rally("15:41", [8.0, 9.5, 11.0, 12.5, 14.0, 15.5, 17.0, 18.5])     # 5m swing high 29518.5
         + _decline("15:49", 9, 18.0) + _flat("15:58", 7, 14.25, 12.75, 13.25)
         + [("16:05", 14.25, 12.75, 14.0), ("16:06", 15.25, 12.75, 15.0)]
         + _rally("16:07", [16.25, 17.0, 17.75])                               # terminal bullish run
         + [("16:10", 18.25, 16.75, 17.5), ("16:11", 18.0, 16.75, 17.25), ("16:12", 17.75, 16.5, 17.0),
            ("16:13", 17.5, 16.25, 16.75), ("16:14", 17.25, 16.0, 16.5)]
         + [("16:15", 19.0, 16.25, 16.5), ("16:16", 16.75, 15.5, 16.0), ("16:17", 16.5, 15.25, 15.75),
            ("16:18", 16.25, 15.0, 15.5), ("16:19", 16.0, 14.75, 15.25)]        # raid of the 5m 29518.5
         + [("16:20", 15.5, 14.0, 14.5), ("16:21", 14.75, 13.5, 14.0), ("16:22", 14.25, 13.25, 13.75),
            ("16:23", 14.0, 13.0, 13.5), ("16:24", 13.75, 12.75, 13.25)]
         + [("16:25", 13.5, 11.75, 12.0), ("16:26", 12.25, 10.75, 11.0), ("16:27", 11.25, 9.75, 10.0),
            ("16:28", 10.5, 9.25, 9.5), ("16:29", 10.0, 9.0, 9.25)]             # displacement
         + [("16:30", 11.0, 9.0, 10.75), ("16:31", 12.25, 10.5, 12.0), ("16:32", 13.25, 11.75, 13.0)]
         + [(_t("16:33", k), 14.0, 12.75 if k == 0 else 13.0, 13.75 if k % 2 == 0 else 13.5)
            for k in range(12)])                                               # retrace into the block
_HEALTHY = [(h, BASE + hi, BASE + lo, BASE + c) for h, hi, lo, c in _ROWS]
_REPLACED = [(h, BASE + 19.5, lo, c) if h == "16:36" else (h, hi, lo, c) for h, hi, lo, c in _HEALTHY]
WINDOW = [_t("16:39", k) for k in range(6)]


def _tape(seq):
    head = T._tape()[:SEED_BARS]
    return head + X._bars(seq, head[-1]["close"])


def _reply(output, ordinal, payload, entry, state):
    """MOCKED, ADVERSARIAL Brain. Establishes on the 15m premise row only, then
    names the newest executable 5m-anchored PO3, keeping the last named exact
    identity after it disappears (nearest protected high above as stop,
    lowest objective below)."""
    output.update(narrative_direction="bearish", allowed_direction="bearish", forbidden_direction="bullish",
                  narrative_phase="continuation", active_draw="sell side liquidity below",
                  market_story="Bearish campaign: buy side raid rejected, structure delivering lower.",
                  dominant_reasoning=("After the buy side liquidity raid and reclaimed rejection, market structure "
                                      "shifted bearish and displacement delivered lower toward sell side liquidity."),
                  current_action="watching", objective_id=None, invalidation_id=None, invalidation_level=None,
                  recommended_playbook_family="none", recommended_tool_family=["none"])
    if not state.get("established"):
        rows = (payload.get("campaign_premise_catalog") or {}).get("rows") or []
        pick = [r for r in rows if r["supports"] == "bearish" and r["d3"]["route_b"]
                and (r["life"]["source_tf"], r["life"]["level"]) == PREMISE[:2]]
        if pick:
            state["established"] = ordinal
            output.update(current_action="stand_down", active_draw="none")
            output["campaign_scope_proposal"] = {"kind": "establish", "direction": "bearish",
                                                 "premise_candidate_id": pick[0]["premise_candidate_id"],
                                                 "scope_reason": "MOCKED constructed distinct-anchor selection"}
        return output
    distinct = [r["occurrence_id"] for r in payload.get("authorized_tool_catalog", [])
                if r.get("tool_family") == PO3 and r.get("direction") == "bearish"
                and r.get("execution_eligible") is True and r.get("occurrence_id")
                and ":5m:swing_high:" in r["occurrence_id"].rsplit(":LIQUIDITY_SWEEP:", 1)[-1]]
    if distinct:
        state["named"] = distinct[0]
    stops = [r for r in payload.get("authorized_invalidations", [])
             if isinstance(r.get("price"), (int, float)) and r["price"] > entry]
    targets = [r for r in payload.get("authorized_objectives", [])
               if isinstance(r.get("price"), (int, float)) and r["price"] < entry]
    if state.get("named") and stops and targets:
        stop, target = min(stops, key=lambda r: r["price"]), min(targets, key=lambda r: r["price"])
        output.update(current_action="propose_entry", objective_id=target["objective_id"],
                      invalidation_id=stop["invalidation_id"], invalidation_level=stop["price"],
                      recommended_playbook_family="manipulation_to_distribution",
                      recommended_tool_family=[PO3], recommended_tool_occurrence_id=state["named"])
    return output


def _life(rec):
    return (rec.get("source_tf") or rec.get("timeframe"), rec.get("level"), rec.get("registered_at"))


def _prime(root, monkeypatch, seq, *, ecu, session_id="S4-05-DAW", brain=True):
    """REAL ProductionScanCycle prewarmed brainless to 15:29; returns the
    cycle, tape, scan function and first Brain-scan index."""
    from broker.topstepx_slippage import QuoteCapture
    from live_scan.production_scan_cycle import ProductionScanCycle
    root.mkdir()
    X._isolate(root, monkeypatch)
    tape = _tape(seq)
    px = [tape[0]["close"]]

    def quote():
        return QuoteCapture(captured_at=datetime.now(timezone.utc), best_bid=px[0], best_ask=px[0] + .25,
                            last_trade=px[0], contract_id=T.CONTRACT, market_data_age_seconds=.25)
    cycle = ProductionScanCycle(symbol="MNQ", contract_id=T.CONTRACT, session_id=session_id,
                                quote_provider=quote)

    def scan(end, brain):
        bars = tape[:end]
        px[0] = bars[-1]["close"]
        return cycle.scan(bars, now=datetime.fromisoformat(bars[-1]["timestamp"]) + timedelta(minutes=1),
                          invoke_brain=brain)
    first = next(i for i, bar in enumerate(tape) if bar["timestamp"][11:16] == "15:30") + 1
    for end in range(20, first):
        scan(end, False)
    if brain:
        calls, state = [], {}
        RF._mock_current_brain(monkeypatch, calls,
                               output_mutator=lambda out, n, payload: _reply(out, n, payload, px[0], state))
        monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
    return cycle, tape, scan, first


def _row(result, cycle):
    """The per-minute observation every assertion reads."""
    snap = result["snapshot"]
    scope = read_current_campaign_scope(snap) or {}
    campaign = scope.get("campaign") or {}
    continuity = (result.get("brain_block") or {}).get("narrative_continuity") or {}
    output = (result.get("brain_block") or {}).get("output") or {}
    lifecycle = result.get("campaign_lifecycle") or {}
    facts = D._facts(result, cycle)
    highs = ((snap.get("protected_swings") or {}).get("by_timeframe") or {}).get("highs") or {}
    anchor = ((current_block(snap, "bearish") or {}).get("formation_authority") or {}).get(
        "anchor_identity") or {}
    try:
        candidate = B._candidate(result, cycle)
        outcome = ("CANDIDATE", candidate.extras.get("selected_tool_occurrence_id"),
                   candidate.entry_price, candidate.invalidation_price, candidate.objective.price)
    except NoCandidate as exc:
        outcome = ("NoCandidate", exc.reason)
    row = {
        "scope": (scope.get("state"), campaign.get("status"), campaign.get("direction"),
                  (campaign.get("certificate") or {}).get("status")),
        "premise_life": _life(campaign.get("premise") or {}),
        "premise": (continuity.get("campaign_premise") or {}).get("status"),
        "lifecycle": (lifecycle.get("state"), lifecycle.get("participation_permitted")),
        "highs": {tf: _life({**rec, "timeframe": tf}) for tf, rec in highs.items() if isinstance(rec, dict)},
        "custody": facts["custody"],
        "anchor_life": _life(anchor) if anchor else None,
        "anchor_side": anchor.get("side"),
        "executable": [r[1] for r in facts["catalog"] if r[0] is True],
        "named": output.get("recommended_tool_occurrence_id"),
        "candidate": outcome,
    }
    return row


def _run(root, monkeypatch, seq, *, ecu):
    """REAL ProductionScanCycle every settled minute; the Brain from 15:30."""
    cycle, tape, scan, first = _prime(root, monkeypatch, seq, ecu=ecu)
    out = {}
    for end in range(first, len(tape) + 1):
        result = scan(end, True)
        out[D._hm(result["snapshot"]["timestamp"])] = _row(result, cycle)
    return out


def _assert_distinct_anchor_witness(healthy, replaced):
    assert sorted(healthy) == sorted(replaced) and WINDOW[-1] in healthy
    # The campaign is established on the 15m CONTEXT life and stays bound to it
    # identically on both tapes, before and after the replacement.
    established = [hm for hm in healthy if healthy[hm]["scope"][0] == "ACTIVE"]
    assert established and established[0] <= "15:46"
    for lane in (healthy, replaced):
        for hm in [hm for hm in lane if hm >= established[0]]:
            assert lane[hm]["scope"] == ("ACTIVE", "ACTIVE", "bearish", "INTACT"), hm
            assert lane[hm]["premise_life"][:2] == PREMISE[:2], hm
            assert lane[hm]["premise"] == "INTACT", hm
            assert lane[hm]["highs"]["15m"] == PREMISE, hm
    # The formation is on a DIFFERENT same-side life: other timeframe, level,
    # birth -- born after the premise, with its own raid.
    for hm in ("16:30", "16:38"):
        for lane in (healthy, replaced):
            assert lane[hm]["custody"] == FORMATION_ID, hm
            assert lane[hm]["anchor_life"] == ANCHOR and lane[hm]["anchor_side"] == "high", hm
            assert lane[hm]["executable"] == [FORMATION_ID], hm
            assert lane[hm]["anchor_life"][:2] != lane[hm]["premise_life"][:2]
    assert ANCHOR[2] > PREMISE[2]
    # Until the one differing bar exists the twins are the same organism; while
    # only its 1m/3m consequences have settled, only the registry may differ.
    for hm in [hm for hm in healthy if hm < "16:36"]:
        assert healthy[hm] == replaced[hm], hm
    for hm in ("16:36", "16:37", "16:38"):
        assert ({k: v for k, v in healthy[hm].items() if k != "highs"}
                == {k: v for k, v in replaced[hm].items() if k != "highs"}), hm
        assert healthy[hm]["highs"]["5m"] == replaced[hm]["highs"]["5m"] == ANCHOR, hm
    # The replacement ends ONLY the formation's anchor life ...
    for hm in WINDOW:
        assert healthy[hm]["highs"]["5m"] == ANCHOR, hm
        assert replaced[hm]["highs"]["5m"][:2] == ("5m", 29519.0), hm
        assert replaced[hm]["custody"] is None and replaced[hm]["executable"] == [], hm
        # ... while premise, scope and Lifecycle read both tapes identically,
        # and Lifecycle PERMITS participation on both.
        for key in ("scope", "premise_life", "premise", "lifecycle"):
            assert healthy[hm][key] == replaced[hm][key], (hm, key)
        assert healthy[hm]["lifecycle"] == ("ACTIVE_DELIVERY", True), hm
        assert healthy[hm]["named"] == replaced[hm]["named"] == FORMATION_ID, hm
        assert healthy[hm]["candidate"][:2] == ("CANDIDATE", FORMATION_ID), hm
        assert healthy[hm]["candidate"][3:] == (29518.5, 29505.5), hm
        # The refusal is the PO3 tool gate, never Lifecycle or scope.
        assert replaced[hm]["candidate"] == ("NoCandidate", "tool_not_detected"), hm


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_formation_on_a_distinct_anchor_is_revoked_alone_while_the_premise_participates(
        tmp_path, monkeypatch, ecu):
    assert TAPE_CLASS == "CONSTRUCTED"
    healthy = _run(tmp_path / "healthy", monkeypatch, _HEALTHY, ecu=ecu)
    replaced = _run(tmp_path / "replaced", monkeypatch, _REPLACED, ecu=ecu)
    _assert_distinct_anchor_witness(healthy, replaced)


# Activated controls: each mutant collapses the two identities in one
# direction, and the decisive assertion above must catch it.

def test_control_formation_kept_alive_by_the_context_life_is_detected(tmp_path, monkeypatch):
    """IDENTITY COLLAPSE: revalidate the formation against the 15m context
    life instead of its own 5m anchor life."""
    import market_data.reversal_formation as RFM
    original = RFM.ReversalFormationCustody._still_current

    def collapsed(self, snapshot, record, *args, **kwargs):
        if original(self, snapshot, record, *args, **kwargs):
            return True
        highs = (((snapshot or {}).get("protected_swings") or {}).get("by_timeframe") or {}).get("highs") or {}
        return record.get("direction") == "bearish" and isinstance(highs.get("15m"), dict)
    monkeypatch.setattr(RFM.ReversalFormationCustody, "_still_current", collapsed)
    healthy = _run(tmp_path / "healthy", monkeypatch, _HEALTHY, ecu=False)
    replaced = _run(tmp_path / "replaced", monkeypatch, _REPLACED, ecu=False)
    with pytest.raises(AssertionError):
        _assert_distinct_anchor_witness(healthy, replaced)
    # Killed at the decisive boundary: the replaced twin still executes.
    assert replaced[WINDOW[0]]["candidate"][:2] == ("CANDIDATE", FORMATION_ID)


def test_control_premise_retired_by_an_unrelated_life_is_detected(tmp_path, monkeypatch):
    """RETIREMENT COLLAPSE: any same-side replacement or violation, on any
    timeframe, is read as the premise life's own violation."""
    import market_data.campaign_premise as CP
    original = CP._terminal_event

    def collapsed(ledger_rows, life, cutoff):
        exact = original(ledger_rows, life, cutoff)
        if exact is not None:
            return exact
        for row in ledger_rows or ():
            if (isinstance(row, dict) and row.get("contract") == life.contract_id
                    and row.get("side") == life.side and CP._available(row, cutoff)
                    and row.get("event_type") in (CP._REPLACED, CP._VIOLATED)
                    and (CP._instant(row.get("event_time")) or "") > life.registered_at):
                return {"type": CP._VIOLATED, "occurrence_id": row.get("occurrence_id"),
                        "event_time": CP._instant(row.get("event_time"))}
        return None
    monkeypatch.setattr(CP, "_terminal_event", collapsed)
    healthy = _run(tmp_path / "healthy", monkeypatch, _HEALTHY, ecu=False)
    replaced = _run(tmp_path / "replaced", monkeypatch, _REPLACED, ecu=False)
    with pytest.raises(AssertionError):
        _assert_distinct_anchor_witness(healthy, replaced)
    # Killed at the decisive boundary: an unrelated same-side life moving (the
    # 3m/5m registrations of 16:17/16:19) retires the 15m premise on the
    # HEALTHY twin. Ratified D0=a then returns the authentic UNBOUND scope to
    # the local table, so the kill is the premise/scope binding, not the
    # candidate outcome.
    assert all(healthy[hm]["scope"][0] == "UNBOUND" and healthy[hm]["premise"] != "INTACT"
               for hm in WINDOW)
