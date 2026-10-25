"""PHASE 3 -- an independent descriptive read beside the unchanged campaign packet.

`descriptive_market_read` is an optional, OBSERVATIONAL_ONLY object in the
Brain response. It is validated on its own and captured by value before any
participation hold, into the SAME `authored_market_read` envelope on the SAME
stance row. It travels only inside that envelope, through the existing
`market_narrative_history`, to the actual next provider input. Absent,
legacy, malformed or degraded reads are UNKNOWN; none is filled from the
root campaign fields. No participation reader consumes it.

Every Brain response here is a CONTROLLED mock (the repository's existing
reply plus a descriptive object chosen by the test). The follow-up responder
builds its descriptive story FROM the transported history and the current
input, so removing or poisoning that history visibly changes the next read.
That is a deterministic cognition-seam proof, not a claim about what any real
model would say. Real ProductionScanCycle / ProductionLoop, production stance
accessor, both ECU lanes.
"""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

import test_campaign_draw_temporal_authority as TA
import test_campaign_leg_scope_labels as L
import test_campaign_scope_binding as B
import test_market_narrative_first as NF
import test_protected_structure_continuity as P2
import test_reversal_foundation_proof_closure as RF
import test_stance_history_hygiene as H
from ai_brain import market_narrative as MN

ROOT = Path(__file__).resolve().parents[1]
ECU_MODES = NF.ECU_MODES
GUARDED_ROOT_KEYS = ("narrative_direction", "narrative_phase", "current_action",
                     "allowed_direction", "market_story", "invalidation_level",
                     "objective_id", "invalidation_id")


def _descriptive(direction, payload, tag):
    """CONTROLLED follow-up read built from the ACTUAL transported history."""
    last = ((payload.get("market_narrative_history") or {}).get("last") or {})
    prior = last.get("descriptive_market_read") or {}
    path = payload.get("active_path_state") or {}
    now = (f"now owner={path.get('owner')} status={path.get('status')} "
           f"last failure {(path.get('last_invalidated') or {}).get('at')}")
    if prior.get("status") == "AVAILABLE":
        story = (f"{tag} CONTINUITY from prior {prior['direction']} read recorded "
                 f"{last.get('recorded_at_cutoff')}; {now}")
    else:
        story = f"{tag} NO PRIOR DESCRIPTIVE READ ({prior.get('reason')}); {now}"
    return {"direction": direction, "market_story": story,
            "dominant_reasoning": f"{tag}: delivery read from current settled facts; {now}",
            "delivery_interpretation": "1m/3m delivery described, 5m scope noted",
            "liquidity_interpretation": "buy-side taken; sell-side remains",
            "protected_high_interpretation": "observed high context as published",
            "protected_low_interpretation": "observed low context as published",
            "thesis_health": "description only; a reclaim would change this read",
            "uncertainties": ["transfer proof unavailable", "higher-timeframe scope open"]}


def _mutator(*, bearish_from=4, root_action="stand_down", descriptive=True,
             desc_direction=lambda n: "bearish", raw=None):
    """Root packet exactly as NF._bearish (unchanged campaign semantics), plus
    an optional descriptive object -- or a raw override for malformed cases."""
    root = NF._bearish(root_action)

    def reply(out, ordinal, payload):
        out = root(out, ordinal, payload) if ordinal >= bearish_from else out
        if raw is not None:
            out = {**out, "descriptive_market_read": copy.deepcopy(raw)}
        elif descriptive:
            out = {**out, "descriptive_market_read": _descriptive(
                desc_direction(ordinal), payload, f"CALL{ordinal}")}
        return out
    return reply


def _geometry(candidate):
    return (candidate.direction, candidate.entry_price, candidate.invalidation_price,
            candidate.objective.identity, candidate.objective.kind,
            candidate.objective.price, candidate.narrative)


def _participation(scan):
    nc = scan["brain_block"]["narrative_continuity"]
    return (nc["control_state"], nc.get("dominant_direction"), nc.get("transfer_confirmed"),
            nc.get("active_leg_failure_status"), scan["campaign_lifecycle"].get("state"),
            scan["campaign_lifecycle"].get("reason"), L._candidate(scan),
            {k: scan["brain_block"]["output"].get(k) for k in GUARDED_ROOT_KEYS})


# ── 1. Survives the hold into actual next input; participation unchanged ───
@ECU_MODES
def test_descriptive_read_survives_hold_into_next_input_without_permission(
        tmp_path, monkeypatch, ecu):
    geometry = {}

    def positive_geometry(key):
        def at(positive):
            geometry[key] = _geometry(RF._produce_candidate(positive))
        return at
    # Intact bullish campaign, root bullish propose_entry (baseline reply) while
    # the descriptive read calls the delivery BEARISH (row 3 of the matrix).
    _c, positive, _pp, records = NF._run(
        tmp_path / "with", monkeypatch, ecu,
        _mutator(desc_direction=lambda n: "bearish"),
        at_positive=positive_geometry("with"))
    _c0, positive0, _pp0, base = NF._run(
        tmp_path / "base", monkeypatch, ecu, NF._bearish(),
        at_positive=positive_geometry("base"))
    # Observational invariance: same candidate geometry, same refusals.
    assert geometry["with"] == geometry["base"]
    assert geometry["with"][0] == "bullish"
    for (scan, _), (scan0, _) in zip(records, base):
        assert _participation(scan) == _participation(scan0)

    held, _ = records[1]
    block = held["brain_block"]
    assert block["output"]["market_story"] == NF.HELD
    assert "descriptive_market_read" not in block["output"]
    read = block["authored_market_read"]["descriptive_market_read"]
    assert (read["status"], read["authority"], read["basis"], read["direction"]) == (
        "AVAILABLE", "OBSERVATIONAL_ONLY", MN.DESCRIPTIVE_BASIS, "bearish")
    assert read["market_story"].startswith("CALL4 CONTINUITY")   # captured pre-hold
    # The legacy pre-hold campaign capture is intact beside it.
    assert block["authored_market_read"]["market_story"] == NF.STORY

    nxt = records[2][1]
    last = nxt["market_narrative_history"]["last"]
    assert last["root_fields_basis"] == MN.ROOT_FIELDS_BASIS
    assert last["market_story"] == NF.STORY
    nested = last["descriptive_market_read"]
    assert nested["status"] == "AVAILABLE" and nested["direction"] == "bearish"
    assert nested["market_story"] == read["market_story"]
    # The CONTROLLED follow-up actually read that history.
    follow = records[2][0]["brain_block"]["authored_market_read"]["descriptive_market_read"]
    assert follow["market_story"].startswith("CALL5 CONTINUITY from prior bearish")
    # The guarded stance view never carries it.
    assert "authored_market_read" not in (nxt["stance_history"]["last"] or {})
    assert "descriptive_market_read" not in json.dumps(nxt["stance_history"])
    assert "descriptive_market_read" not in json.dumps(nxt["narrative_continuity"])


# ── 2. The follow-up really consumes history: poisoned/removed history ─────
@ECU_MODES
@pytest.mark.parametrize("case", ["healthy", "legacy_row", "foreign_custody",
                                  "authority_relabel"])
def test_follow_up_read_depends_on_transported_history(tmp_path, monkeypatch, ecu, case):
    def poison(cycle):
        read = cycle.stance_memory._buf[-1]["authored_market_read"]
        if case == "legacy_row":
            read.pop("descriptive_market_read")
        elif case == "foreign_custody":
            read["provenance"]["history_lineage"]["custody"] = "other-producer-custody"
        elif case == "authority_relabel":
            read["descriptive_market_read"]["authority"] = "EXECUTION"
    _c, _p, _pp, records = NF._run(tmp_path, monkeypatch, ecu, _mutator(), poison=poison)
    held, payload = records[2]
    last = payload["market_narrative_history"]["last"]
    nested = last["descriptive_market_read"]
    follow = held["brain_block"]["authored_market_read"]["descriptive_market_read"]
    expected = {"healthy": None,
                "legacy_row": "legacy_read_without_descriptive_field",
                "foreign_custody": "provenance_mismatch:history_lineage.custody",
                "authority_relabel": "descriptive_authority_label_invalid"}[case]
    if expected is None:
        assert nested["status"] == "AVAILABLE"
        assert follow["market_story"].startswith("CALL5 CONTINUITY")
    else:
        assert (nested["status"], nested["reason"]) == ("UNKNOWN", expected)
        assert "market_story" not in nested
        assert follow["market_story"].startswith(f"CALL5 NO PRIOR DESCRIPTIVE READ ({expected})")
    if case == "legacy_row":
        # Legacy root fields stay, labelled, never relabelled as the new read.
        assert last["market_story"] == NF.STORY
        assert last["root_fields_basis"] == MN.ROOT_FIELDS_BASIS
    assert L._candidate(held) == "campaign_lifecycle_refused"


# ── 3. Missing / null / malformed: nested UNKNOWN, root packet unchanged ───
MALFORMED = {
    "absent": None, "null": "NULL", "string": "bearish",
    "unexpected_action": {**_descriptive("bearish", {}, "X"), "current_action": "propose_entry"},
    "unexpected_metadata": {**_descriptive("bearish", {}, "X"), "status": "AVAILABLE"},
    "blank_story": {**_descriptive("bearish", {}, "X"), "market_story": "  "},
    "bad_direction": {**_descriptive("bearish", {}, "X"), "direction": "short"},
    "too_many_uncertainties": {**_descriptive("bearish", {}, "X"), "uncertainties": ["u"] * 9},
}
REASONS = {"absent": "descriptive_read_absent", "null": "descriptive_read_absent",
           "string": "descriptive_read_not_object",
           "unexpected_action": "descriptive_read_unexpected_field:current_action",
           "unexpected_metadata": "descriptive_read_unexpected_field:status",
           "blank_story": "descriptive_read_blank:market_story",
           "bad_direction": "descriptive_read_invalid:direction",
           "too_many_uncertainties": "descriptive_read_invalid:uncertainties"}


@pytest.mark.parametrize("shape", list(MALFORMED))
def test_malformed_descriptive_field_is_unknown_and_root_is_untouched(
        tmp_path, monkeypatch, shape):
    if shape == "absent":
        mutator = _mutator(descriptive=False)
    elif shape == "null":
        root = NF._bearish()

        def mutator(out, n, payload):
            out = root(out, n, payload) if n >= 4 else out
            return {**out, "descriptive_market_read": None}
    else:
        mutator = _mutator(raw=MALFORMED[shape])
    _c, _p, _pp, records = NF._run(tmp_path / "m", monkeypatch, False, mutator)
    _c0, _p0, _pp0, base = NF._run(tmp_path / "b", monkeypatch, False, NF._bearish())
    held, payload = records[1]
    read = held["brain_block"]["authored_market_read"]
    assert read["status"] == "AVAILABLE" and read["market_story"] == NF.STORY
    assert (read["descriptive_market_read"]["status"],
            read["descriptive_market_read"]["reason"]) == ("UNKNOWN", REASONS[shape])
    assert held["brain_block"]["source"] == base[1][0]["brain_block"]["source"] == "llm"
    for (scan, _), (scan0, _) in zip(records, base):
        assert _participation(scan) == _participation(scan0)
    nested = records[2][1]["market_narrative_history"]["last"]["descriptive_market_read"]
    assert (nested["status"], nested["reason"]) == ("UNKNOWN", REASONS[shape])


def test_degraded_or_fallback_cognition_has_no_available_descriptive_read():
    good = {"market_story": NF.STORY, "narrative_direction": "bearish",
            "descriptive_market_read": _descriptive("bearish", {}, "X")}
    for source, fallback in (("degraded", None), ("deterministic", None),
                             ("llm_failed_fallback", "x"), ("llm", "provider_circuit_open")):
        read = MN.capture(good, source=source, fallback_reason=fallback, llm_call={},
                          repair={}, snapshot={}, symbol="MNQ", stance_memory=None)
        assert read["status"] == "UNKNOWN"
        assert read["descriptive_market_read"]["status"] == "UNKNOWN"
        assert "market_story" not in read["descriptive_market_read"]
    assert MN.for_record(None)["descriptive_market_read"]["status"] == "UNKNOWN"
    assert MN._item({"recorded_at_cutoff": "t"})["descriptive_market_read"]["reason"] == \
        "legacy_row_without_authored_read"


def test_descriptive_text_is_bounded_and_truncation_declared():
    long = {**_descriptive("neutral", {}, "X"), "market_story": "s" * (MN.TEXT_LIMIT + 7),
            "uncertainties": ["u" * (MN.UNCERTAINTY_LIMIT + 3)]}
    view = MN.descriptive_view(long)
    assert view["status"] == "AVAILABLE"
    assert len(view["market_story"]) == MN.TEXT_LIMIT
    assert len(view["uncertainties"][0]) == MN.UNCERTAINTY_LIMIT
    assert [t["field"] for t in view["truncations"]] == ["market_story", "uncertainties[0]"]


# ── 4. Root action / authority stays the root's (stand_down, propose_entry,
#       invalid packet); prose never becomes intent ──────────────────────────
@ECU_MODES
@pytest.mark.parametrize("root_action", ["stand_down", "propose_entry"])
def test_strong_descriptive_language_never_becomes_entry_or_plan(tmp_path, monkeypatch,
                                                               ecu, root_action):
    def setup_language(n):
        return "bearish"
    mutator = _mutator(root_action=root_action, desc_direction=setup_language)
    _c, _p, _pp, records = NF._run(tmp_path / "w", monkeypatch, ecu, mutator)
    _c0, _p0, _pp0, base = NF._run(tmp_path / "b", monkeypatch, ecu, NF._bearish(root_action))
    for (scan, _), (scan0, _) in zip(records, base):
        assert _participation(scan) == _participation(scan0)
        assert L._candidate(scan) is not None          # refused: no entry, no plan
    authored = records[1][0]["brain_block"]["authored_market_read"]
    assert authored["authored_action"] == root_action
    assert authored["descriptive_market_read"]["direction"] == "bearish"


def test_invalid_root_packet_is_not_repaired_by_a_valid_descriptive_read(tmp_path,
                                                                         monkeypatch):
    def bad(desc):
        root = NF._bearish()

        def reply(out, n, payload):
            out = root(out, n, payload) if n >= 4 else out
            if n == 4:
                out = {**out, "current_action": "enter_short_now"}
                if desc:
                    out["descriptive_market_read"] = _descriptive("bearish", payload, "BAD")
            return out
        return reply
    _c, _p, _pp, records = NF._run(tmp_path / "d", monkeypatch, False, bad(True))
    _c0, _p0, _pp0, base = NF._run(tmp_path / "b", monkeypatch, False, bad(False))
    held, held0 = records[1][0], base[1][0]
    assert held["brain_block"]["source"] == held0["brain_block"]["source"] != "llm"
    assert held["brain_block"]["output"] == held0["brain_block"]["output"]
    assert held["brain_block"]["authored_market_read"]["descriptive_market_read"][
        "status"] == "UNKNOWN"
    assert _participation(held) == _participation(held0)


# ── 5. Existing healthy positives and refusals with a descriptive read ─────
def _with_descriptive(monkeypatch, module, name, direction, payload_arg):
    original = getattr(module, name)

    def wrapped(*args, **kwargs):
        out = original(*args, **kwargs)
        payload = args[payload_arg] if len(args) > payload_arg else {}
        return {**out, "descriptive_market_read": _descriptive(direction, payload, "POS")}
    monkeypatch.setattr(module, name, wrapped)


def test_existing_bullish_retained_reversal_candidate_is_unchanged(tmp_path, monkeypatch):
    # The opposite descriptive direction is deliberate: description is not intent.
    _with_descriptive(monkeypatch, RF, "_valid_model_reply", "bearish", 0)
    RF.test_newborn_draw_waits_until_next_scan_for_positive_candidate_authority(
        tmp_path, monkeypatch)


@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_existing_w5_bearish_candidate_and_bound_plan_are_unchanged(tmp_path, monkeypatch,
                                                                     ecu):
    _with_descriptive(monkeypatch, B, "_w5_reply", "bullish", 2)
    (tmp_path / "t").mkdir()
    (tmp_path / "p").mkdir()
    B.test_real_t2_pending_t3_newborn_refusal_t4_candidate(tmp_path / "t", monkeypatch, ecu)
    B.test_real_bound_plan_survives_fresh_cutoff_and_refuses_lost_custody(
        tmp_path / "p", monkeypatch, ecu)


@ECU_MODES
def test_friday_retained_high_refusal_is_unchanged_with_a_descriptive_read(tmp_path,
                                                                           monkeypatch, ecu):
    # The same per-test runtime isolation P2's own autouse fixture applies.
    for key in ("OCCURRENCE_LEDGER_DIR", "AI_BRAIN_DIR", "AI_RETRIEVAL_DIR",
                "REPLAY_SESSIONS_DIR"):
        monkeypatch.setenv(key, str(tmp_path / key))
    monkeypatch.setenv("AI_BRAIN_ENABLED", "false")
    monkeypatch.setenv("AI_BRAIN_LLM", "false")
    import ai_brain.ecu as ECU
    monkeypatch.setattr(ECU, "_STANCE", None)
    original = P2._controlled

    def controlled(output, ordinal, payload):
        return {**original(output, ordinal, payload),
                "descriptive_market_read": _descriptive("bearish", payload, f"FRI{ordinal}")}
    monkeypatch.setattr(P2, "_controlled", controlled)
    P2.test_friday_retained_high_reaches_next_brain_but_bears_no_transfer(monkeypatch, ecu)


@ECU_MODES
def test_c2_surviving_high_refusal_is_unchanged_with_a_descriptive_read(tmp_path,
                                                                        monkeypatch, ecu):
    # The same per-test runtime isolation P2's own autouse fixture applies.
    for key in ("OCCURRENCE_LEDGER_DIR", "AI_BRAIN_DIR", "AI_RETRIEVAL_DIR",
                "REPLAY_SESSIONS_DIR"):
        monkeypatch.setenv(key, str(tmp_path / key))
    import ai_brain.ecu as ECU
    import ai_brain.narrative_brain as NB
    monkeypatch.setattr(ECU, "_STANCE", None)
    lane, seen = H._lane, []

    def described(tmp, mp, e, *, mutator=None):
        def reply(out, ordinal, payload):
            out = mutator(out, ordinal, payload) if mutator else out
            return {**out, "descriptive_market_read": _descriptive("bearish", payload,
                                                                   f"C2-{ordinal}")}
        built = lane(tmp, mp, e, mutator=reply)
        transport = NB._call_llm          # the lane's mocked transport

        def observe(payload, repair=None):
            last = (payload.get("market_narrative_history") or {}).get("last") or {}
            seen.append(copy.deepcopy(last.get("descriptive_market_read")))
            return transport(payload, repair)
        mp.setattr(NB, "_call_llm", observe)
        return built
    monkeypatch.setattr(H, "_lane", described)
    # The parent's own C2 assertions: fact transported, no transfer, refusal.
    P2.test_c2_surviving_pre_death_high_is_fact_not_transfer(tmp_path, monkeypatch, ecu)
    # Non-vacuous: a bearish descriptive read really reached those provider inputs.
    assert any((d or {}).get("status") == "AVAILABLE" and d["direction"] == "bearish"
               for d in seen)


# ── 6. Chronology: future rows and duplicate cutoffs ──────────────────────
@pytest.mark.parametrize("case", list(H.EXPECTED_REASON))
def test_withheld_row_never_supplies_descriptive_continuity(tmp_path, monkeypatch, case):
    # Future-dated, wrong contract/session, superseded, legacy and malformed
    # rows: each carries a well-formed descriptive read, none may supply it.
    def poison(cycle):
        bad = H._poison(cycle.stance_memory._buf[-1], case)
        bad["authored_market_read"] = copy.deepcopy(
            cycle.stance_memory._buf[-1]["authored_market_read"])
        bad["authored_market_read"]["descriptive_market_read"]["market_story"] = "WITHHELD READ"
        cycle.stance_memory._buf.append(bad)
    _c, _p, _pp, records = NF._run(tmp_path, monkeypatch, False, _mutator(), poison=poison)
    hist = records[2][1]["market_narrative_history"]
    stories = [((i or {}).get("descriptive_market_read") or {}).get("market_story")
               for i in [hist["last"], *hist["prior"]]]
    assert "WITHHELD READ" not in stories
    assert hist["withheld_rows"].get(H.EXPECTED_REASON[case], 0) >= 1
    assert hist["last"]["descriptive_market_read"]["status"] == "AVAILABLE"


@ECU_MODES
def test_duplicate_cutoff_keeps_honest_identity(tmp_path, monkeypatch, ecu):
    cycle, calls = H._lane(tmp_path, monkeypatch, ecu, mutator=_mutator(bearish_from=99))
    sent = H._capture_transport(monkeypatch)
    H._brain_scan(cycle, calls, RF.TAPE_1M)
    first, _ = H._brain_scan(cycle, calls, TA.LATER)
    H._brain_scan(cycle, calls, TA.LATER)            # the same settled cutoff again
    again = sent[-1][1]["market_narrative_history"]["last"]
    captured = first["brain_block"]["authored_market_read"]
    assert again["recorded_at_cutoff"] == captured["provenance"]["settled_cutoff"]
    assert again["descriptive_market_read"]["market_story"] == \
        captured["descriptive_market_read"]["market_story"]
    assert again["recorded_at_cutoff"] <= sent[-1][1]["stance_history"]["last"][
        "recorded_at_cutoff"]


@ECU_MODES
def test_restart_keeps_the_persisted_read_but_lends_it_no_continuity(tmp_path, monkeypatch,
                                                                     ecu):
    import ai_brain.ecu as ECU
    monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path / "brain_runtime"))
    monkeypatch.setattr(ECU, "_STANCE", None)
    first, calls = H._lane(tmp_path / "process_a", monkeypatch, ecu,
                           mutator=_mutator(bearish_from=99))
    H._brain_scan(first, calls, RF.TAPE_1M)
    before, _ = H._brain_scan(first, calls, TA.LATER)
    captured = before["brain_block"]["authored_market_read"]
    persisted = json.loads((tmp_path / "brain_runtime" / "stance_memory.json")
                           .read_text())["buf"][-1]["authored_market_read"]
    # The original capture, identity and cutoff are persisted as recorded.
    assert persisted["descriptive_market_read"] == captured["descriptive_market_read"]
    assert persisted["provenance"] == captured["provenance"]

    # A new process (same session/contract) cannot prove that lineage.
    second, calls = H._lane(tmp_path / "process_b", monkeypatch, ecu,
                            mutator=_mutator(bearish_from=99))
    sent = H._capture_transport(monkeypatch)
    after, _ = H._brain_scan(second, calls, RF.TAPE_1M)
    hist = sent[-1][1]["market_narrative_history"]
    assert captured["descriptive_market_read"]["market_story"] not in json.dumps(hist)
    follow = after["brain_block"]["authored_market_read"]["descriptive_market_read"]
    assert follow["status"] == "AVAILABLE"
    assert " NO PRIOR DESCRIPTIVE READ" in follow["market_story"]
    # Fresh cognition in the new lineage becomes the next continuity.
    H._brain_scan(second, calls, TA.LATER)
    last = sent[-1][1]["market_narrative_history"]["last"]
    assert last["descriptive_market_read"]["market_story"] == follow["market_story"]


# ── 7. Contract, reader scope and report ─────────────────────────────────
def test_prompt_states_the_two_roles_narrowly():
    from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT as PROMPT
    assert '"descriptive_market_read": {"direction"' in PROMPT
    assert "This governs\n  the root campaign field only" in PROMPT
    assert "only then, `narrative_direction` may change to that new owner." in PROMPT
    assert "DIRECTION AND ACTION ARE SEPARATE QUESTIONS" in PROMPT


def test_no_participation_module_reads_the_descriptive_view():
    allowed = {"ai_brain/market_narrative.py", "ai_brain/narrative_brain.py",
               "ai_brain/brain_prompt.py"}
    readers = sorted(p.relative_to(ROOT / "src").as_posix()
                     for p in (ROOT / "src").rglob("*.py")
                     if "descriptive_market_read" in p.read_text(encoding="utf-8"))
    assert set(readers) <= allowed, readers
    source = (ROOT / "src/ai_brain/narrative_brain.py").read_text(encoding="utf-8")
    # The only narrative_brain use removes the raw object from the root output.
    assert source.count("descriptive_market_read") == 1
    assert 'output.pop("descriptive_market_read", None)' in source


@ECU_MODES
def test_report_separates_descriptive_campaign_permitted_and_refusal(tmp_path,
                                                                     monkeypatch, ecu):
    _c, _p, _pp, records = NF._run(tmp_path, monkeypatch, ecu, _mutator())
    spec = importlib.util.spec_from_file_location("nrr", ROOT / "tools/narrative_read_report.py")
    nrr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nrr)
    items = nrr.rows(str(tmp_path / "report_input"))
    held = records[1][0]["brain_block"]
    row = next(r for r in items if r["authored"].get("story") == NF.STORY)
    assert row["descriptive"]["status"] == "AVAILABLE"
    assert row["descriptive"]["direction"] == "bearish"
    assert row["descriptive"]["story"] == held["authored_market_read"][
        "descriptive_market_read"]["market_story"]
    assert row["permitted"]["story"] == NF.HELD
    assert row["refusal"]["status"] == held["narrative_authority_guard"]["status"]
    assert row["source"] == "llm" and row["read_settled_cutoff"]
    text = nrr.render(items)
    for column in ("DESCRIPTIVE_READ", "PRE_HOLD_CAMPAIGN_RESPONSE", "PERMITTED_RESPONSE",
                   "REFUSAL"):
        assert column in text
    legacy = nrr._descriptive({"llm_raw_response": json.dumps(
        {"descriptive_market_read": _descriptive("bearish", {}, "RAW")})})
    assert legacy["status"] == "UNKNOWN"   # a raw field is never promoted
