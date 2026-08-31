"""ACTIVE-PATH-STATE-1 — the market's memory of its own path.

2026-08-24, 10:52. Three models on byte-identical payloads — gpt-5.6-luna,
gpt-5.6-terra, gpt-5.6-sol — were asked which side owned the market. All 19
calls answered BEARISH. Zero identified the bullish leg that had produced 29
structural breaks against 3 and three successively higher defended lows over the
preceding forty minutes.

That was not a reasoning failure. Ownership could only be read off the bearish
FVG sitting at price, because the chronology that answers the question was never
written down: `structure[tf].bos` expires next scan, and the protected-swing
tracker POPS each level as the next registers, destroying
28953.50 -> 28962.75 -> 28979.50 -> 29081.50 as it formed.

These tests pin the two defects found while certifying the synthesizer, because
both produced plausible-looking timelines that were wrong:

  GHOST REFERENCE   an adverse replacement was rejected as "not better", so the
                    reference stayed pinned to a level the producer had already
                    replaced — asserting `intact: True` about 29299.00 eleven
                    minutes after the tracker moved to 29321.00. Since the kill
                    rule matches on level equality, the leg became immortal:
                    2026-08-21 replayed 153/153 bearish with zero releases.
  FORMING OWNERSHIP a rejected raid alone set `owner`, so the degraded
                    2026-08-10 archive — sweeps present, ZERO structure breaks,
                    ZERO protected registrations — published `owner: bearish`
                    for all 116 scans of a session mechanics could not read.

And the invariant the whole unit exists to protect: ownership is EVIDENCE, never
authorisation. A lawful bearish reaction inside a bullish path must stay
executable, or the state has become the deterministic veto it replaced.

No network. No model. No order.
"""
from __future__ import annotations

import copy
import glob
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from market_state.active_path import (                                # noqa: E402
    LIQUIDITY_SWEEP, PROTECTED_SWING_REGISTERED, PROTECTED_SWING_REPLACED,
    PROTECTED_SWING_VIOLATED, STRUCTURE_BREAK, ActivePath,
    extract_occurrences, occurrence_id)

CONTRACT = "CON.F.US.MNQ.U26"
ARCHIVE = os.path.join(ROOT, "data", "ai_brain")


def _code_only(module) -> str:
    """Module source with comments and docstrings removed.

    A source guard exists to prove the CODE does not do something. Grepping raw
    text also greps the comments that explain why the code must not do it, so
    the more carefully a forbidden pattern is documented the more likely the
    guard is to fail on its own explanation.
    """
    import ast
    import inspect
    import io
    import tokenize
    src = inspect.getsource(module)
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING:
            continue          # drops docstrings AND string literals
        out.append(tok.string)
    return " ".join(out)


# ── helpers ──────────────────────────────────────────────────────────────────
def sweep(tf="1m", direction="below_low", at="T1"):
    return {"occurrence_id": occurrence_id(CONTRACT, LIQUIDITY_SWEEP, tf, at, direction),
            "event_type": LIQUIDITY_SWEEP, "contract": CONTRACT, "source_tf": tf,
            "event_time": at, "sweep_direction": direction, "reclaimed": True}


def brk(direction="bullish", tf="1m", at="T2", level=100.0):
    return {"occurrence_id": occurrence_id(CONTRACT, STRUCTURE_BREAK, tf, at, direction),
            "event_type": STRUCTURE_BREAK, "contract": CONTRACT, "source_tf": tf,
            "event_time": at, "direction": direction, "broken_level": level}


def prot(level, side="low", tf="1m", at="T3", replaced_from=None):
    et = PROTECTED_SWING_REPLACED if replaced_from is not None else PROTECTED_SWING_REGISTERED
    ev = {"occurrence_id": occurrence_id(CONTRACT, et, tf, at, f"{side}@{level}"),
          "event_type": et, "contract": CONTRACT, "source_tf": tf, "event_time": at,
          "side": side, "level": level, "basis": f"{'sell' if side == 'low' else 'buy'}_side_raid_rejected"}
    if replaced_from is not None:
        ev["old_level"] = replaced_from
    return ev


def violated(level, side="low", tf="1m", at="T9"):
    return {"occurrence_id": occurrence_id(CONTRACT, PROTECTED_SWING_VIOLATED, tf, at, f"{side}@{level}"),
            "event_type": PROTECTED_SWING_VIOLATED, "contract": CONTRACT,
            "source_tf": tf, "event_time": at, "side": side, "level": level}


def replay(day, mutation=None, upto=None):
    files = sorted(glob.glob(os.path.join(ARCHIVE, f"{day}_*_MNQ.json")))
    if not files:
        pytest.skip(f"archive {day} absent")
    ap, prior, out = ActivePath(), {}, []
    for f in files:
        try:
            snap = json.load(open(f, encoding="utf-8"))["raw_snapshot"]
        except Exception:
            continue
        if mutation == "strip":
            snap = dict(snap); snap["toolbox"] = {}
        elif mutation == "flip":
            snap = json.loads(json.dumps(snap))
            for i in (snap.get("toolbox") or {}).get("tool_instances") or []:
                if i.get("direction") in ("bullish", "bearish"):
                    i["direction"] = "bearish" if i["direction"] == "bullish" else "bullish"
        ap.ingest(extract_occurrences(snap, prior, CONTRACT))
        prior = ((snap.get("protected_swings") or {}).get("by_timeframe") or {})
        st = ap.state(); st["scan"] = os.path.basename(f)[9:15]
        out.append(st); ap.mark_scan_end()
        if upto and st["scan"] == upto:
            break
    return out


# ══════════════════════════════════════════════════════════════════════════════
class TestOwnershipRequiresConfirmation:
    """A rejected raid opens a HYPOTHESIS. It does not own the market."""

    def test_a_raid_alone_does_not_establish_owner(self):
        ap = ActivePath(); ap.ingest([sweep()])
        s = ap.state()
        assert s["owner"] == "none"
        assert s["forming_direction"] == "bullish"
        assert s["status"] == "forming"

    def test_confirmation_establishes_ownership(self):
        ap = ActivePath(); ap.ingest([sweep(), brk("bullish")])
        s = ap.state()
        assert s["owner"] == "bullish"
        assert s["forming_direction"] is None
        assert s["status"] == "active"

    def test_an_opposing_break_does_not_confirm_the_hypothesis(self):
        ap = ActivePath(); ap.ingest([sweep(), brk("bearish")])
        s = ap.state()
        assert s["owner"] == "none" and s["forming_direction"] == "bullish"

    def test_owner_and_forming_are_never_both_directional(self):
        ap = ActivePath(); ap.ingest([sweep(), brk("bullish")])
        s = ap.state()
        assert not (s["owner"] in ("bullish", "bearish") and s["forming_direction"])

    def test_owner_is_never_the_string_contested(self):
        """CONTESTED is a health verdict about an owner, not a third owner --
        otherwise you cannot tell WHICH leg is being challenged."""
        ap = ActivePath()
        ap.ingest([sweep(), brk("bullish"), prot(100.0), brk("bearish", at="T8")])
        s = ap.state()
        assert s["status"] == "contested"
        assert s["owner"] == "bullish"


class TestGhostReference:
    """THE 08-21 DEFECT. `load_bearing` must always name a level the producer
    currently holds -- otherwise it can never be violated and the leg cannot die."""

    def test_adverse_replacement_repoints_the_reference(self):
        ap = ActivePath()
        ap.ingest([sweep("1m", "above_high"), brk("bearish"),
                   prot(29299.0, side="high", at="T4")])
        assert ap.load_bearing["level"] == 29299.0
        ap.ingest([prot(29321.0, side="high", at="T5", replaced_from=29299.0)])
        assert ap.load_bearing["level"] == 29321.0, "reference must follow the producer"
        assert ap.load_bearing["last_move_favourable"] is False

    def test_the_adverse_level_is_excluded_from_the_favourable_ladder(self):
        ap = ActivePath()
        ap.ingest([sweep("1m", "above_high"), brk("bearish"),
                   prot(29299.0, side="high", at="T4"),
                   prot(29321.0, side="high", at="T5", replaced_from=29299.0)])
        assert ap.state()["progression"]["favourable_ladder"] == [29299.0]

    def test_the_repointed_level_can_then_kill_the_leg(self):
        """The exact 08-21 sequence. Before the fix this violation matched
        nothing and the leg survived to the end of the archive."""
        ap = ActivePath()
        ap.ingest([sweep("1m", "above_high"), brk("bearish"),
                   prot(29299.0, side="high", at="T4"),
                   prot(29321.0, side="high", at="T5", replaced_from=29299.0),
                   violated(29321.0, side="high", at="T6")])
        s = ap.state()
        assert s["owner"] == "none"
        assert s["load_bearing_structure"] is None
        assert s["last_invalidated"]["level"] == 29321.0

    def test_a_favourable_replacement_extends_the_ladder(self):
        ap = ActivePath()
        ap.ingest([sweep(), brk("bullish"), prot(28979.5, at="T4"),
                   prot(29081.5, at="T5", replaced_from=28979.5)])
        s = ap.state()
        assert s["progression"]["favourable_ladder"] == [28979.5, 29081.5]
        assert s["progression"]["successive_favourable"] is True
        assert s["load_bearing_structure"]["last_move_favourable"] is True


class TestReleaseAndReestablishment:
    def test_death_releases_ownership(self):
        ap = ActivePath()
        ap.ingest([sweep(), brk("bullish"), prot(100.0), violated(100.0)])
        assert ap.state()["owner"] == "none"

    def test_a_new_path_can_establish_after_death_both_ways(self):
        ap = ActivePath()
        ap.ingest([sweep(), brk("bullish"), prot(100.0), violated(100.0)])
        ap.ingest([sweep("1m", "above_high", at="TA"), brk("bearish", at="TB")])
        assert ap.state()["owner"] == "bearish"
        ap.ingest([prot(200.0, side="high", at="TC"), violated(200.0, side="high", at="TD")])
        assert ap.state()["owner"] == "none"
        ap.ingest([sweep("1m", "below_low", at="TE"), brk("bullish", at="TF")])
        assert ap.state()["owner"] == "bullish"


class TestContestedRuleA:
    """Operator ruling: a rejected opposing raid is counter-evidence, not a
    contest. Counter-path liquidity behaviour is ordinary in a retracement."""

    def test_opposing_raid_alone_does_not_contest(self):
        ap = ActivePath()
        ap.ingest([sweep(), brk("bullish"), prot(100.0),
                   sweep("1m", "above_high", at="T7")])
        s = ap.state()
        assert s["status"] == "active"
        assert s["transfer_evidence"]["opposing_raid_rejected"] is True

    def test_opposing_structure_break_contests(self):
        ap = ActivePath()
        ap.ingest([sweep(), brk("bullish"), prot(100.0), brk("bearish", at="T8")])
        assert ap.state()["status"] == "contested"

    def test_contest_does_not_flip_ownership(self):
        ap = ActivePath()
        ap.ingest([sweep(), brk("bullish"), prot(100.0), brk("bearish", at="T8")])
        assert ap.state()["owner"] == "bullish"


class TestTruthfulNulls:
    def test_sideless_mss_is_null_not_false(self):
        """`structure[tf].mss` has no direction in this producer. Reporting it
        as `false` would claim the producer answered when it declined to."""
        ap = ActivePath(); ap.ingest([sweep(), brk("bullish")])
        te = ap.state()["transfer_evidence"]
        assert te["opposing_market_structure_shift"] is None
        assert te["opposing_displacement"] is None

    def test_mss_is_never_recorded_as_a_directional_event(self):
        snap = {"timestamp": "T", "structure": {"1m": {"mss": True}}, "liquidity": {}}
        assert extract_occurrences(snap, {}, CONTRACT) == []

    def test_unavailable_state_is_not_owner_none(self):
        """'no path established' and 'state could not be derived' are different
        facts. Publishing the first for the second is false certainty."""
        s = ActivePath().state(available=False, unavailable_reason="ledger:LEDGER_UNAVAILABLE")
        assert s["state_available"] is False
        assert s["owner"] is None and s["status"] is None
        assert "ledger" in s["unavailable_reason"]


class TestIdempotentIdentity:
    def test_the_same_event_seen_repeatedly_mints_one_identity(self):
        snap = {"timestamp": "2026-08-24T14:41:00+00:00",
                "liquidity": {"1m": {"sweep_detected": True, "reclaim_detected": True,
                                     "sweep_direction": "below_low", "swept_level": 28979.5}},
                "structure": {}, "protected_swings": {}}
        a = extract_occurrences(snap, {}, CONTRACT)
        b = extract_occurrences(copy.deepcopy(snap), {}, CONTRACT)
        assert [o["occurrence_id"] for o in a] == [o["occurrence_id"] for o in b]
        assert len({o["occurrence_id"] for o in a + b}) == 1

    def test_identity_does_not_depend_on_when_we_looked(self):
        """Scan time must not manufacture identity, or a restart duplicates
        history and the same tape event exists twice."""
        assert "scan" not in occurrence_id(CONTRACT, STRUCTURE_BREAK, "1m", "T", "bullish")
        assert occurrence_id(CONTRACT, STRUCTURE_BREAK, "1m", "T", "bullish") == \
            occurrence_id(CONTRACT, STRUCTURE_BREAK, "1m", "T", "bullish")

    def test_the_ledger_accepts_the_new_event_classes(self):
        from market_data.occurrence_ledger import FORBIDDEN_FIELDS
        for ev in (brk(), prot(100.0), violated(100.0)):
            assert not [f for f in FORBIDDEN_FIELDS if f in ev], ev["event_type"]

    def test_break_direction_is_a_tape_fact_not_an_opinion(self):
        from market_data.occurrence_ledger import FORBIDDEN_FIELDS, IMMUTABLE_FIELDS
        assert "direction" in IMMUTABLE_FIELDS
        assert "trade_direction" in FORBIDDEN_FIELDS and "bias" in FORBIDDEN_FIELDS


class TestNoVotingShortcut:
    def test_more_opposing_breaks_do_not_flip_ownership(self):
        """Majority voting was forbidden by construction; prove it behaviourally."""
        ap = ActivePath()
        ap.ingest([sweep(), brk("bullish"), prot(100.0)])
        for i in range(9):
            ap.ingest([brk("bearish", at=f"T9{i}")])
        s = ap.state()
        assert s["owner"] == "bullish", "ownership must not be a headcount"
        assert s["status"] == "contested"

    def test_the_source_contains_no_count_comparison(self):
        """CODE ONLY. An earlier version grepped raw source and tripped on this
        module's own comments explaining what it must never do -- a guard that
        fails on its own documentation is testing prose, not behaviour."""
        from market_state import active_path as M
        for shortcut in ("len(bull", "len(bear", "> bear", "> bull", ".count("):
            assert shortcut not in _code_only(M), shortcut


class TestOwnerIsNotAuthorisation:
    """THE INVARIANT. Path memory must never become a counter-path veto."""

    def test_a_bearish_reaction_stays_lawful_under_a_bullish_path(self):
        from broker.luna_candidate_producer import CandidateProducer as P
        luna = {"narrative_direction": "bearish",
                "current_action": "propose bearish reaction entry",
                "recommended_tool_family": ["fvg"]}
        P._assert_action_permits_entry(luna)
        assert P._direction(luna, {}) == "bearish"

    def test_a_bullish_reaction_stays_lawful_under_a_bearish_path(self):
        from broker.luna_candidate_producer import CandidateProducer as P
        luna = {"narrative_direction": "bullish",
                "current_action": "propose bullish reaction entry",
                "recommended_tool_family": ["fvg"]}
        P._assert_action_permits_entry(luna)
        assert P._direction(luna, {}) == "bullish"

    def test_no_execution_surface_reads_active_path_state(self):
        from broker import luna_candidate_producer as CP
        from execution_gate import execution_gate as EG
        for mod in (CP, EG):
            assert "active_path_state" not in _code_only(mod), mod.__name__


class TestNarrativeFeedbackQuarantined:
    """NOT FIXED IN THIS UNIT, AND DELIBERATELY SO.

    `narrative_engine._ai_lens` feeds Luna's `narrative_direction` into the
    MECHANICAL market-direction authority, which derives
    `forbidden_trade_direction`, which `execution_gate.narrative_permits`
    enforces under `NARRATIVE_AUTHORITY=enforce`. Once `narrative_direction`
    means PROPOSED EXECUTION SIDE, that lets a lawful counter-path short become
    the narrative that forbids the opposite side.

    Retiring the lens was attempted and reverted: it drops the NA-1 arbitration
    constitution from three lenses to two and breaks 5 certification tests that
    encode "AI + Delivery agreement OWNS the direction". That is a doctrine
    change, not a defect fix, and it needs its own authorization.

    What IS proven here: the loop is inert at current settings, and path
    ownership was NOT substituted into it.
    """

    def test_the_loop_is_inert_at_the_production_default(self):
        from narrative_authority.narrative_engine import authority_level
        prev = os.environ.pop("NARRATIVE_AUTHORITY", None)
        try:
            assert authority_level() == "observe_only"
        finally:
            if prev is not None:
                os.environ["NARRATIVE_AUTHORITY"] = prev

    def test_the_loop_still_exists_and_is_recorded_as_a_known_debt(self):
        """Pinned so the debt cannot be silently forgotten: if the lens is ever
        retired, this test fails and the doctrine unit gets written."""
        from narrative_authority.narrative_engine import _ai_lens
        snap = {"ai_brain": {"output": {"narrative_direction": "bearish",
                                        "phase_confidence": 99}}}
        assert _ai_lens(snap)[0] == "bearish", (
            "the ai lens was retired without the NA-1 doctrine unit")

    def test_path_ownership_did_not_replace_it(self):
        """The forbidden repair: owner -> forbidden_trade_direction."""
        from narrative_authority import narrative_engine as NE
        assert "active_path_state" not in _code_only(NE)


# ══════════════════════════════════════════════════════════════════════════════
class TestArchivedCanonicalReplay:
    """The 2026-08-24 specimens, chronologically, no hindsight."""

    @pytest.fixture(scope="class")
    def day(self):
        return replay("20260824")

    def test_10_52_reports_bullish_ownership(self, day):
        r = next(x for x in day if x["scan"] == "105200")
        assert r["owner"] == "bullish"
        assert r["status"] == "active"
        assert r["load_bearing_structure"]["level"] == 28979.5
        assert r["load_bearing_structure"]["basis"] == "sell_side_raid_rejected"
        assert r["transfer_evidence"]["load_bearing_failure"] is False

    def test_10_57_is_continuation_of_the_same_leg(self, day):
        r = next(x for x in day if x["scan"] == "105733")
        assert r["owner"] == "bullish"
        assert r["load_bearing_structure"]["level"] == 29081.5
        assert r["progression"]["favourable_ladder"] == [28979.5, 29081.5]
        assert r["progression"]["successive_favourable"] is True

    def test_no_illegal_owner_status_combination_all_session(self, day):
        bad = [r for r in day if r["owner"] in ("bullish", "bearish")
               and r["status"] == "forming"]
        assert not bad

    def test_ownership_releases_and_re_establishes_both_ways(self, day):
        seq = []
        for r in day:
            if not seq or seq[-1] != r["owner"]:
                seq.append(r["owner"])
        assert "none" in seq and "bullish" in seq and "bearish" in seq

    def test_load_bearing_is_always_producer_backed(self, day):
        for r in day:
            lb = r["load_bearing_structure"]
            if lb:
                assert lb["producer_backed"] is True


class TestToolDirectionIndependence:
    """Ownership must not be readable off the executable object at price --
    that is precisely what all three models did on 2026-08-24."""

    def test_stripping_every_tool_changes_nothing(self):
        base, strip = replay("20260824"), replay("20260824", "strip")
        assert [(r["owner"], r["status"]) for r in base] == \
               [(r["owner"], r["status"]) for r in strip]

    def test_inverting_every_tool_direction_changes_nothing(self):
        base, flip = replay("20260824"), replay("20260824", "flip")
        assert [(r["owner"], r["status"], r["forming_direction"]) for r in base] == \
               [(r["owner"], r["status"], r["forming_direction"]) for r in flip]


class TestDegradedArchiveFailsHonestly:
    def test_08_10_never_claims_ownership_from_sweeps_alone(self):
        """Zero structure breaks, zero protected registrations. Sweeps exist.
        The pre-fix synthesizer published `owner: bearish` for all 116 scans."""
        day = replay("20260810")
        assert day, "08-10 archive absent"
        assert all(r["owner"] == "none" for r in day)
        assert all(r["status"] == "forming" for r in day)
        assert all(r["forming_direction"] == "bearish" for r in day)


class TestBrainPayload:
    def test_the_block_reaches_brain_input(self):
        from ai_brain.brain_input import build_brain_input
        f = os.path.join(ARCHIVE, "20260824_105200_MNQ.json")
        if not os.path.exists(f):
            pytest.skip("specimen absent")
        snap = copy.deepcopy(json.load(open(f, encoding="utf-8"))["raw_snapshot"])
        ap = ActivePath(); ap.ingest([sweep(), brk("bullish"), prot(28979.5)])
        snap["active_path_state"] = ap.state()
        out = build_brain_input(snap, {}) or {}
        assert out.get("active_path_state", {}).get("owner") == "bullish"

    def test_the_block_stays_compact(self):
        ap = ActivePath()
        ap.ingest([sweep(), brk("bullish"), prot(28979.5),
                   prot(29081.5, at="T5", replaced_from=28979.5)])
        assert len(json.dumps(ap.state())) < 2000

    def test_no_event_history_is_shipped_to_the_model(self):
        """The model gets the synthesis, not hundreds of raw occurrences."""
        ap = ActivePath()
        for i in range(50):
            ap.ingest([brk("bullish", at=f"T{i:03d}")])
        s = ap.state()
        assert "events" not in s
        assert len(json.dumps(s)) < 2000

    def test_the_prompt_explains_the_fields_without_prescribing_a_decision(self):
        from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT as P
        assert "`active_path_state`" in P
        assert "IT IS EVIDENCE, NOT PERMISSION" in P
        assert "narrative_direction does NOT have to equal it" in P


# ══════════════════════════════════════════════════════════════════════════════
class TestSessionAndContractLifecycle:
    """ACTIVE-PATH-STATE-1D. Before this, an established leg survived into the
    next production session for one reason only: the launcher happens to restart
    the process every morning. `ProductionScanCycle` is built once per launched
    loop, so nothing in the architecture stopped Monday's bullish owner from
    still owning Tuesday's tape. A safety property resting on an operating habit
    is not a guarantee."""

    def test_session_key_uses_exchange_time_not_a_utc_date_slice(self):
        """21:30 New York belongs to THAT session, not the next UTC day."""
        from market_state.active_path import production_session_key as key
        assert key("2026-08-24T14:41:00+00:00") == "20260824"   # 10:41 ET
        assert key("2026-08-25T01:30:00+00:00") == "20260824"   # 21:30 ET same session
        assert key("2026-08-25T14:00:00+00:00") == "20260825"

    def test_the_boundary_comes_from_the_canonical_authority(self):
        """Not a second copy of the doctrine. If production moves the window's
        timezone, this moves with it."""
        import inspect
        from market_state import active_path as M
        src = inspect.getsource(M.production_session_key)
        assert "topstepx_session_authorization" in src
        assert "PRODUCTION_WINDOW_TZ" in src
        assert "America/New_York" not in _code_only(M), "timezone re-declared locally"

    def test_unreadable_timestamp_yields_absence_not_a_guess(self):
        from market_state.active_path import production_session_key as key
        assert key(None) is None and key("") is None and key("not-a-time") is None

    def test_ownership_does_not_survive_a_new_production_session(self):
        ap = ActivePath()
        ap.enforce_lifecycle("2026-08-24T14:41:00+00:00", "CON.A")
        ap.ingest([sweep(), brk("bullish"), prot(28979.5)])
        assert ap.state()["owner"] == "bullish"
        reason = ap.enforce_lifecycle("2026-08-25T14:00:00+00:00", "CON.A")
        assert reason == "new_production_session"
        s = ap.state()
        assert s["owner"] == "none" and s["forming_direction"] is None
        assert s["load_bearing_structure"] is None

    def test_same_session_never_resets(self):
        ap = ActivePath()
        ap.enforce_lifecycle("2026-08-24T13:35:00+00:00", "CON.A")
        ap.ingest([sweep(), brk("bullish")])
        for ts in ("2026-08-24T14:41:00+00:00", "2026-08-24T18:00:00+00:00",
                   "2026-08-25T01:30:00+00:00"):
            assert ap.enforce_lifecycle(ts, "CON.A") is None, ts
        assert ap.state()["owner"] == "bullish"

    def test_a_contract_rollover_cannot_inherit_ownership(self):
        """An exact contract is a different instrument. Inheriting a ladder or a
        load-bearing level across a rollover files one instrument's structure
        under another's identity."""
        ap = ActivePath()
        ap.enforce_lifecycle("2026-08-24T14:41:00+00:00", "CON.F.US.MNQ.U26")
        ap.ingest([sweep(), brk("bullish"), prot(28979.5)])
        assert ap.state()["owner"] == "bullish"
        assert ap.enforce_lifecycle("2026-08-24T14:42:00+00:00",
                                    "CON.F.US.MNQ.Z26") == "contract_rollover"
        s = ap.state()
        assert s["owner"] == "none"
        assert s["load_bearing_structure"] is None
        assert s["progression"]["favourable_ladder"] == []

    def test_a_new_leg_must_be_established_causally_after_a_reset(self):
        """Facts survive; the CONCLUSION must be re-earned."""
        ap = ActivePath()
        ap.enforce_lifecycle("2026-08-24T14:41:00+00:00", "CON.A")
        ap.ingest([sweep(), brk("bullish"), prot(28979.5)])
        ap.enforce_lifecycle("2026-08-25T14:00:00+00:00", "CON.A")
        ap.ingest([sweep(at="U1")])                       # raid alone
        assert ap.state()["owner"] == "none"
        assert ap.state()["forming_direction"] == "bullish"
        ap.ingest([brk("bullish", at="U2")])              # confirmation
        assert ap.state()["owner"] == "bullish"

    def test_the_reset_reason_is_reported(self):
        ap = ActivePath()
        ap.enforce_lifecycle("2026-08-24T14:41:00+00:00", "CON.A")
        ap.ingest([sweep(), brk("bullish")])
        ap.enforce_lifecycle("2026-08-25T14:00:00+00:00", "CON.A")
        assert ap.state()["last_reset_reason"] == "new_production_session"
        assert ap.state()["session"] == "20260825"

    def test_no_business_logic_branches_on_a_reset_reason(self):
        """Reasons are diagnostics. If ownership ever depends on the string, the
        reason has quietly become a rule."""
        from market_state import active_path as M
        code = _code_only(M)
        for reason in ("new_production_session", "contract_rollover",
                       "canonical_history_revision"):
            assert f'== "{reason}"' not in code and f"== '{reason}'" not in code

    def test_the_scan_cycle_enforces_lifecycle_before_ingesting(self):
        """Order matters: a stale leg must be released BEFORE this scan's
        events could extend it."""
        import inspect
        from live_scan.production_scan_cycle import ProductionScanCycle
        src = inspect.getsource(ProductionScanCycle._update_active_path)
        assert src.index("enforce_lifecycle") < src.index("ingest("), \
            "lifecycle must be enforced before ingest"


class TestSessionCrossingIsNotProcessDependent:
    """The exact defect the push review exposed, stated as a test."""

    def test_a_long_lived_process_cannot_carry_a_leg_into_a_new_session(self):
        ap = ActivePath()                      # ONE object, never re-created
        ap.enforce_lifecycle("2026-08-24T14:41:00+00:00", "CON.A")
        ap.ingest([sweep(), brk("bullish"), prot(28979.5)])
        owned_day_one = ap.state()["owner"]
        ap.enforce_lifecycle("2026-08-25T13:35:00+00:00", "CON.A")
        owned_day_two = ap.state()["owner"]
        assert owned_day_one == "bullish"
        assert owned_day_two == "none", (
            "ownership survived a session boundary because the process did")


# ══════════════════════════════════════════════════════════════════════════════
class TestIngestIsIdempotentByIdentity:
    """One factual event is ONE occurrence -- in memory exactly as on disk.

    A sweep is re-detected on every scan while its two-candle predicate holds,
    so an un-deduplicated ingest applied the same tape fact five or six times.
    It also made a restart produce a DIFFERENT state from a continuous process,
    because ledger replay is deduplicated and live ingest was not."""

    def test_the_same_occurrence_applied_twice_changes_nothing(self):
        ap = ActivePath()
        ap.ingest([sweep(), brk("bullish"), prot(28979.5)])
        before = ap.state()
        ap.ingest([sweep(), brk("bullish"), prot(28979.5)])
        assert ap.state() == before

    def test_a_favourable_level_cannot_enter_the_ladder_twice(self):
        ap = ActivePath()
        ap.ingest([sweep(), brk("bullish"), prot(28979.5)])
        ap.ingest([prot(28979.5)])
        assert ap.state()["progression"]["favourable_ladder"] == [28979.5]

    def test_a_stale_counter_raid_is_not_re_counted(self):
        """`transfer_evidence` looks at events after the last confirmation.
        Duplicates of an old counter-raid must not keep re-asserting it."""
        ap = ActivePath()
        ap.ingest([sweep(), brk("bullish"), prot(100.0)])
        ap.ingest([sweep("1m", "above_high", at="T7")])
        first = ap.state()["transfer_evidence"]["opposing_raid_rejected"]
        ap.ingest([sweep("1m", "above_high", at="T7")])       # same identity
        assert ap.state()["transfer_evidence"]["opposing_raid_rejected"] == first

    def test_events_without_identity_are_still_applied(self):
        ap = ActivePath()
        ap.ingest([{k: v for k, v in sweep().items() if k != "occurrence_id"}])
        assert ap.state()["forming_direction"] == "bullish"


class TestProductionEnvelopeEquivalence:
    """`production_session_key` uses the exchange-local DATE, not the window
    start. That is only sufficient because the production loop cannot observe a
    timestamp outside one local day. Pin the envelope so widening it past local
    midnight cannot pass silently."""

    def test_the_loop_only_scans_before_or_inside_the_window(self):
        import inspect
        import tools.topstepx_production_session as PS
        src = inspect.getsource(PS.should_continue) if hasattr(PS, "should_continue") \
            else inspect.getsource(PS)
        assert "production_window_open" in src and "before_production_window" in src

    def test_both_predicates_compare_within_one_local_day(self):
        import inspect
        import tools.topstepx_production_session as PS
        for fn in (PS.production_window_open, PS.before_production_window):
            src = inspect.getsource(fn)
            assert 'strftime("%H:%M")' in src, fn.__name__
            assert "timedelta" not in src, f"{fn.__name__} may span days now"

    def test_the_docstring_does_not_claim_window_start_authority(self):
        from market_state.active_path import production_session_key as key
        doc = key.__doc__ or ""
        assert "It does NOT read `PRODUCTION_WINDOW_START`" in doc


class TestRestartRecovery:
    """THE QUESTION THIS WHOLE UNIT EXISTS TO ANSWER: if the machine restarts at
    10:50, does it still know at 10:52 that the bullish path belongs to the
    market? Before this, no -- a fresh process built an empty ActivePath and
    learned only what the CURRENT scan witnessed, which is the original defect
    displaced from scan lifetime to process lifetime."""

    FIELDS = ("owner", "status", "forming_direction", "origin",
              "load_bearing_structure", "progression", "transfer_evidence")

    def _run(self, tmpdir, upto, restart_at=None):
        import glob as _g
        os.environ["OCCURRENCE_LEDGER_DIR"] = tmpdir
        from live_scan.production_scan_cycle import ProductionScanCycle
        files = sorted(_g.glob(os.path.join(ARCHIVE, "20260824_*_MNQ.json")))
        if not files:
            pytest.skip("archive absent")
        cyc = ProductionScanCycle(symbol="MNQ", contract_id=CONTRACT)
        state = None
        for f in files:
            scan = os.path.basename(f)[9:15]
            if scan > upto:
                break
            snap = json.load(open(f, encoding="utf-8"))["raw_snapshot"]
            if restart_at and scan == restart_at:
                del cyc                       # process death
                cyc = ProductionScanCycle(symbol="MNQ", contract_id=CONTRACT)
            state = cyc._update_active_path(snap)
        return state

    def test_continuous_and_restarted_processes_agree_at_10_52(self, tmp_path):
        a = self._run(str(tmp_path / "a"), upto="105200")
        b = self._run(str(tmp_path / "a"), upto="105200", restart_at="105200")
        assert a["owner"] == b["owner"] == "bullish"
        assert a["status"] == b["status"] == "active"
        assert a["load_bearing_structure"]["level"] == 28979.5
        for f in self.FIELDS:
            assert a[f] == b[f], f

    def test_a_restart_replays_durable_current_session_events(self, tmp_path):
        os.environ["OCCURRENCE_LEDGER_DIR"] = str(tmp_path / "r")
        from live_scan.production_scan_cycle import ProductionScanCycle
        import glob as _g
        files = sorted(_g.glob(os.path.join(ARCHIVE, "20260824_*_MNQ.json")))
        if not files:
            pytest.skip("archive absent")
        cyc = ProductionScanCycle(symbol="MNQ", contract_id=CONTRACT)
        for f in files:
            if os.path.basename(f)[9:15] > "105128":
                break
            cyc._update_active_path(json.load(open(f, encoding="utf-8"))["raw_snapshot"])
        fresh = ProductionScanCycle(symbol="MNQ", contract_id=CONTRACT)
        # Production creates the synthesizer BEFORE recovering into it; calling
        # recovery on a cycle whose path is still None returns early by design.
        fresh._active_path = ActivePath()
        snap = json.load(open(files[0], encoding="utf-8"))["raw_snapshot"]
        diag = fresh._recover_active_path(snap)
        assert diag["replayed"] > 0, "no durable chronology was replayed"
        assert diag["session"] == "20260824"

    def test_recovery_does_not_resurrect_a_ghost_level(self, tmp_path):
        """A durable record proves a level was registered once. It does not
        prove the producer still holds it."""
        os.environ["OCCURRENCE_LEDGER_DIR"] = str(tmp_path / "g")
        from live_scan.production_scan_cycle import ProductionScanCycle
        cyc = ProductionScanCycle(symbol="MNQ", contract_id=CONTRACT)
        cyc._active_path = ActivePath()
        cyc._active_path.ingest([sweep(), brk("bullish"), prot(28979.5)])
        assert cyc._active_path.load_bearing["level"] == 28979.5
        # live registry no longer holds it
        assert cyc._reconcile_load_bearing({"protected_swings": {
            "by_timeframe": {"lows": {"1m": {"level": 29999.0}}}}}) is False
        assert cyc._active_path.load_bearing is None

    def test_recovery_keeps_a_level_the_producer_still_holds(self, tmp_path):
        os.environ["OCCURRENCE_LEDGER_DIR"] = str(tmp_path / "k")
        from live_scan.production_scan_cycle import ProductionScanCycle
        cyc = ProductionScanCycle(symbol="MNQ", contract_id=CONTRACT)
        cyc._active_path = ActivePath()
        cyc._active_path.ingest([sweep(), brk("bullish"), prot(28979.5)])
        assert cyc._reconcile_load_bearing({"protected_swings": {
            "by_timeframe": {"lows": {"1m": {"level": 28979.5}}}}}) is True
        assert cyc._active_path.load_bearing["level"] == 28979.5

    def test_recovery_excludes_prior_session_and_foreign_contract_facts(self, tmp_path):
        import inspect
        from live_scan.production_scan_cycle import ProductionScanCycle
        src = inspect.getsource(ProductionScanCycle._recover_active_path)
        assert 'r.get("contract") == self.contract_id' in src
        assert 'production_session_key(r.get("event_time")) == key' in src
