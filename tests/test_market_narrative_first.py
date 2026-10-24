"""NARRATIVE-FIRST-1: the Brain's authored read travels; permission is unchanged.

Built on the real producer/custody/Brain-input graph in both ECU lanes (the
same constructed tape as the stance-history and leg-scope suites): a genuine
bullish candidate, then the C2 local failure. A controlled Brain describes the
bearish delivery and stands down. Its read must reach the next canonical input
and the operator report as OBSERVATIONAL_ONLY context, while every
participation result stays exactly as before. Not an instruction to trade.
"""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

import test_campaign_draw_temporal_authority as TA
import test_campaign_leg_scope_labels as L
import test_reversal_foundation_proof_closure as RF
import test_stance_history_hygiene as H
from ai_brain import market_narrative as MN

ROOT = Path(__file__).resolve().parents[1]
STORY = ("AUDIT CONTROL: price rejected buy-side liquidity at 29500 and broke the "
         "protected local low at 29457. Bearish delivery challenges the prior bullish "
         "leg; campaign transfer remains unproved, and no entry is proposed.")
HELD = "Directional control is developing but no new dominant campaign is confirmed; stand down."
ECU_MODES = pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])


def _bearish(action="stand_down"):
    def reply(out, ordinal, payload):
        if ordinal < 4:
            return out
        return {**out, "narrative_direction": "bearish", "narrative_phase": "transition",
                "market_story": STORY, "dominant_reasoning": STORY,
                "current_action": action, "objective_id": None, "invalidation_id": None,
                "allowed_direction": "bearish" if action == "propose_entry" else "none",
                "forbidden_direction": None, "invalidation_level": None,
                "active_draw": "none", "recommended_playbook_family": "none",
                "recommended_tool_family": ["none"]}
    return reply


def _run(tmp_path, monkeypatch, ecu, mutator, *, poison=None, at_positive=None):
    cycle, calls = H._lane(tmp_path, monkeypatch, ecu, mutator=mutator)
    # The shared harness stubs persistence. Write the exact record production
    # persists (same json.dump form), with a sequence instead of a wall-clock
    # second so no call overwrites another.
    report_dir = tmp_path / "report_input"
    report_dir.mkdir(exist_ok=True)
    sequence = []

    def persist(symbol, record):
        sequence.append(1)
        path = report_dir / f"20261023_{len(sequence):06d}_{symbol}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=1, default=str)
        return str(path)
    from ai_brain import narrative_brain
    monkeypatch.setattr(narrative_brain, "persist_brain_call", persist)
    H._brain_scan(cycle, calls, RF.TAPE_1M)
    positive, positive_payload = H._brain_scan(cycle, calls, TA.LATER)
    # A scan's candidate authority is current only until the next scan.
    assert RF._produce_candidate(positive).direction == "bullish"
    if at_positive is not None:
        at_positive(positive)
    rows, records = list(TA.LATER), []
    for index, bar in enumerate(L.SCENARIOS["C2"][:3]):
        if poison is not None and index == 2:
            poison(cycle)
        rows.append(bar)
        records.append(H._brain_scan(cycle, calls, rows))
    return cycle, positive, positive_payload, records


def _history(payload):
    return payload.get("market_narrative_history") or {}


@ECU_MODES
def test_authored_read_reaches_next_brain_and_report_without_participation(
        tmp_path, monkeypatch, ecu):
    cycle, positive, _pp, records = _run(tmp_path, monkeypatch, ecu, _bearish())
    assert positive["brain_block"]["authored_market_read"]["narrative_direction"] == "bullish"
    held, _ = records[1]
    block = held["brain_block"]
    # Participation view: exactly the pre-existing guarded hold.
    assert block["narrative_continuity"]["control_state"] == "developing_transfer"
    assert block["output"]["current_action"] == "stand_down"
    assert block["output"]["market_story"] == HELD
    assert L._candidate(held) == "campaign_lifecycle_refused"
    # Authored view in the envelope, captured before the hold.
    read = block["authored_market_read"]
    assert read["status"] == "AVAILABLE" and read["authority"] == "OBSERVATIONAL_ONLY"
    assert (read["market_story"], read["narrative_direction"], read["authored_action"]) == (
        STORY, "bearish", "stand_down")
    prov = read["provenance"]
    assert prov["source"] == MN.SOURCE and prov["contract_id"] == RF.CONTRACT
    assert prov["brain_fingerprint"].startswith("brain:")
    assert prov["retrieval_fingerprint"].startswith("retr:")
    assert prov["pre_hold_output_digest"].startswith("sha256:")
    # Actual next transported input: guarded stance unchanged, read separate.
    nxt = records[2][1]
    assert nxt["narrative_continuity"]["prior_thesis"]["market_story"] == HELD
    assert "authored_market_read" not in (nxt["stance_history"]["last"] or {})
    hist = _history(nxt)
    assert hist["schema"] == MN.HISTORY_SCHEMA and hist["authority"] == "OBSERVATIONAL_ONLY"
    last = hist["last"]
    assert (last["market_story"], last["narrative_direction"], last["authority"]) == (
        STORY, "bearish", "OBSERVATIONAL_ONLY")
    assert last["recorded_at_cutoff"] == nxt["stance_history"]["last"]["recorded_at_cutoff"]
    # The healthy bullish read is still present as an earlier item.
    assert any(i.get("narrative_direction") == "bullish" for i in hist["prior"])
    # Operator report consumes the actual persisted records.
    spec = importlib.util.spec_from_file_location("nrr", ROOT / "tools/narrative_read_report.py")
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    items = report.rows(str(tmp_path / "report_input"))
    row = next(r for r in items if r["authored"].get("story") == STORY)
    assert row["authored"]["basis"] == "authored_market_read"
    assert (row["permitted"]["action"], row["permitted"]["story"]) == ("stand_down", HELD)
    assert row["refusal"]["status"] == block["narrative_authority_guard"]["status"]
    text = report.render([row])
    assert "AUTHORED" in text and "PERMITTED" in text and "REFUSAL" in text


@ECU_MODES
def test_blocked_proposal_is_shown_beside_the_exact_hold(tmp_path, monkeypatch, ecu):
    _cycle, _pos, _pp, records = _run(tmp_path, monkeypatch, ecu, _bearish("propose_entry"))
    held, _ = records[1]
    assert held["brain_block"]["authored_market_read"]["authored_action"] == "propose_entry"
    assert held["brain_block"]["output"]["current_action"] == "stand_down"
    assert held["brain_block"]["narrative_authority_guard"]["proposed_direction"] == "bearish"
    assert L._candidate(held) == "campaign_lifecycle_refused"
    assert _history(records[2][1])["last"]["authored_action"] == "propose_entry"


@ECU_MODES
def test_observational_read_cannot_change_any_participation_outcome(
        tmp_path, monkeypatch, ecu):
    def compare(positive):
        base = RF._produce_candidate(positive)
        forged = positive   # in place: a copied scan loses its authenticated publication
        touched = 0
        for holder in (forged["brain_block"], forged["brain_result"]):
            if isinstance(holder, dict) and isinstance(holder.get("authored_market_read"), dict):
                holder["authored_market_read"].update(
                    narrative_direction="bearish", authored_action="propose_entry",
                    authority="EXECUTION", market_story="forged")
                touched += 1
        assert touched >= 1
        again = RF._produce_candidate(forged)
        def geometry(c):
            return (c.direction, c.entry_price, c.invalidation_price, c.objective.identity,
                    c.objective.kind, c.objective.price, c.narrative)
        assert geometry(again) == geometry(base)
    _cycle, _positive, _pp, records = _run(tmp_path, monkeypatch, ecu, _bearish(),
                                           at_positive=compare)
    held, _ = records[1]
    forged_held = copy.deepcopy(held)
    forged_held["brain_block"]["authored_market_read"]["narrative_direction"] = "bullish"
    assert L._candidate(forged_held) == L._candidate(held) == "campaign_lifecycle_refused"


def _rewrite_last_read(cycle, mutate):
    row = cycle.stance_memory._buf[-1]
    mutate(row["authored_market_read"])


@ECU_MODES
def test_poisoned_or_copied_reads_change_no_authority_and_are_not_continuity(
        tmp_path, monkeypatch, ecu):
    _c, _p, _pp, clean = _run(tmp_path, monkeypatch, ecu, _bearish())
    def poison(cycle):
        _rewrite_last_read(cycle, lambda r: r.update(
            narrative_direction="bullish", authority="EXECUTION",
            market_story="FORGED execution authority"))
    _c2, _p2, _pp2, dirty = _run(tmp_path / "b", monkeypatch, ecu, _bearish(), poison=poison)
    last = _history(dirty[2][1])["last"]
    assert last["status"] == "UNKNOWN" and last["reason"] == "authority_label_invalid"
    def authority_view(payload):
        nc = payload["narrative_continuity"]
        return (nc["control_state"], nc.get("dominant_direction"), nc.get("transfer_confirmed"),
                nc.get("active_leg_failure_status"), nc["prior_thesis"].get("direction"),
                nc["prior_thesis"].get("market_story"),
                payload["stance_history"]["last"]["direction"])
    assert authority_view(dirty[2][1]) == authority_view(clean[2][1])
    assert dirty[2][0]["campaign_lifecycle"] == clean[2][0]["campaign_lifecycle"]
    assert L._candidate(dirty[2][0]) == L._candidate(clean[2][0])

    def foreign(cycle):
        _rewrite_last_read(cycle, lambda r: r["provenance"].update(
            contract_id="CON.F.US.MES.Z26"))
    _c3, _p3, _pp3, copied = _run(tmp_path / "c", monkeypatch, ecu, _bearish(), poison=foreign)
    last = _history(copied[2][1])["last"]
    assert last["status"] == "UNKNOWN" and last["reason"] == "provenance_mismatch:contract_id"


@pytest.mark.parametrize("case", ["future_dated", "wrong_contract", "superseded_revision",
                                  "legacy_schema"])
def test_withheld_rows_never_supply_the_narrative(tmp_path, monkeypatch, case):
    def poison(cycle):
        bad = H._poison(cycle.stance_memory._buf[-1], case)
        bad["authored_market_read"] = {**copy.deepcopy(
            cycle.stance_memory._buf[-1]["authored_market_read"]),
            "market_story": "WITHHELD ROW STORY", "narrative_direction": "bullish"}
        cycle.stance_memory._buf.append(bad)
    _c, _p, _pp, records = _run(tmp_path, monkeypatch, False, _bearish(), poison=poison)
    hist = _history(records[2][1])
    assert hist["last"]["market_story"] == STORY
    assert all(i.get("market_story") != "WITHHELD ROW STORY" for i in hist["prior"])
    assert sum(hist["withheld_rows"].values()) >= 1


def test_degraded_missing_and_legacy_reads_are_unknown_never_invented():
    out = {"market_story": STORY, "narrative_direction": "bearish"}
    for source, fallback in (("degraded", None), ("deterministic", None),
                             ("llm_failed_fallback", "x"), ("llm", "provider_circuit_open")):
        read = MN.capture(out, source=source, fallback_reason=fallback, llm_call={},
                          repair={}, snapshot={}, symbol="MNQ", stance_memory=None)
        assert read["status"] == "UNKNOWN" and "market_story" not in read
    assert MN.for_record(None)["reason"] == "authored_read_not_supplied"
    assert MN._item({"recorded_at_cutoff": "t"})["reason"] == "legacy_row_without_authored_read"
    assert MN.unavailable_history("x")["available"] is False


def test_capture_is_by_value_and_truncation_is_declared():
    out = {"market_story": "x" * (MN.TEXT_LIMIT + 50), "narrative_direction": "bullish",
           "current_action": "stand_down"}
    read = MN.capture(out, source="llm", fallback_reason=None, llm_call={"model": "m"},
                      repair={}, snapshot={"timestamp": "2026-10-23T16:29:00+00:00"},
                      symbol="MNQ", stance_memory=None)
    out["market_story"], out["narrative_direction"] = HELD, "conflicted"
    assert read["narrative_direction"] == "bullish"
    assert len(read["market_story"]) == MN.TEXT_LIMIT
    assert read["truncations"][0]["field"] == "market_story"
    assert read["truncations"][0]["chars"] == MN.TEXT_LIMIT + 50


def test_no_authority_module_reads_the_observational_view():
    allowed = {"ai_brain/market_narrative.py", "ai_brain/narrative_brain.py",
               "ai_brain/stance_memory.py", "ai_brain/brain_input.py",
               "ai_brain/brain_prompt.py"}
    readers = sorted(str(p.relative_to(ROOT / "src")) for p in (ROOT / "src").rglob("*.py")
                     if "authored_market_read" in p.read_text(encoding="utf-8")
                     or "market_narrative_history" in p.read_text(encoding="utf-8"))
    assert set(readers) <= allowed, readers
