"""CONTINUITY-2E.3 — realtime volatility may tighten, never grant.

AUDIT_2E3_realtime_volatility_authority.md returned verdict B. Holding settled
history byte-identical and varying only the forming bucket, realtime volatility
RAISED the risk multiplier 170 times, REMOVED a volatility veto 68 times, and
GRANTED extended stop authority 22 times. It was an accelerator as well as a
brake, and `state` carried two propositions under one name:

    "realized range is elevated RIGHT NOW"        legitimately realtime
    "we are in a dangerous volatility REGIME"     a stateful claim with duration

THE COMPOSITION, and why it is not a ratchet:

    SETTLED volatility establishes the MAXIMUM authority available.
    REALTIME volatility may only REDUCE it.

Stateless. Each scan re-derives both views and takes the more restrictive. A
live bar that turns violent tightens instantly; a live bar that calms down
simply stops tightening. No memory, no latch, no hysteresis -- the audit found
the volatility lane has no state machine and 2E.3 does not add one.

THE INVARIANT UNDER TEST is stated against the SETTLED-ONLY baseline, not
against another forming variant. Comparing two arbitrary forming buckets makes
every tightening look like a loosening in reverse and proves nothing.
"""
from __future__ import annotations

import collections
import inspect
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.topstepx_combine_risk import extended_volatility_supported  # noqa: E402
from data_feed.timeframe_builder import build_timeframes                # noqa: E402
import market_data.snapshot_builder as SB                               # noqa: E402
import volatility_authority.volatility_authority as VA                  # noqa: E402


def bar(m, o, h, l, c):
    return {"timestamp": f"2026-08-11T{14 + m // 60:02d}:{m % 60:02d}:00+00:00",
            "open": o, "high": h, "low": l, "close": c, "volume": 1000}


def series(rng, n, scale, start=0, px=29700.0):
    out = []
    for i in range(n):
        o = px
        c = px + rng.gauss(0, scale)
        h = max(o, c) + abs(rng.gauss(0, scale * 0.5))
        l = min(o, c) - abs(rng.gauss(0, scale * 0.5))
        out.append(bar(start + i, o, h, l, c))
        px = c
    return out, px


def settled_only(bars):
    """The snapshot as it would be with NO realtime contribution at all."""
    real = SB.compose_authority
    SB.compose_authority = lambda s, r: dict(s or {}, temporal_class="settled_only")
    try:
        return SB.build_snapshot(build_timeframes(bars), symbol="MNQ")
    finally:
        SB.compose_authority = real


def composed(bars):
    return SB.build_snapshot(build_timeframes(bars), symbol="MNQ")


def grants_extended_stop(snap) -> bool:
    mr = snap.get("market_regime", {}) or {}
    ok, _ = extended_volatility_supported({
        "volatility_state": mr.get("volatility_state"),
        "expansion_state": mr.get("expansion_state"),
        "structural_level_identity": "SWING_LOW_29723.25"})
    return ok


def corpus(seed=23, trials=140, n_settled=180):
    rng = random.Random(seed)
    for _ in range(trials):
        settled_bars, px = series(rng, n_settled, rng.uniform(0.8, 8.0))
        forming, _ = series(rng, rng.randint(1, 4), rng.uniform(0.3, 40.0),
                            start=n_settled, px=px)
        yield settled_bars + forming


# ── the composition rule, in isolation ────────────────────────────────────────

class TestComposeAuthority:

    def test_the_more_cautious_state_wins(self):
        calm = {"state": "stable", "volatility_score": 40}
        violent = {"state": "toxic", "volatility_score": 90}
        assert VA.compose_authority(calm, violent)["state"] == "toxic"
        assert VA.compose_authority(violent, calm)["state"] == "toxic"

    def test_realtime_cannot_make_settled_more_permissive(self):
        for settled_state in VA.CAUTION_RANK:
            for realtime_state in VA.CAUTION_RANK:
                out = VA.compose_authority({"state": settled_state},
                                           {"state": realtime_state})
                assert VA._rank(out["state"]) >= VA._rank(settled_state), \
                    f"{realtime_state} loosened {settled_state}"

    def test_expanding_is_the_most_permissive_state(self):
        """It is the only state in extended_volatility_supported's permit set,
        so a grant now needs BOTH views to agree."""
        assert VA.CAUTION_RANK["expanding"] == 0
        assert VA.compose_authority({"state": "expanding"},
                                    {"state": "stable"})["state"] == "stable"

    def test_numeric_fields_follow_the_winning_state(self):
        """A merged block must not be a chimera of two different reads."""
        calm = {"state": "stable", "volatility_score": 40, "range_acceleration": 0.9}
        violent = {"state": "toxic", "volatility_score": 95, "range_acceleration": 3.1}
        out = VA.compose_authority(calm, violent)
        assert out["volatility_score"] == 95 and out["range_acceleration"] == 3.1

    def test_it_carries_its_own_provenance(self):
        out = VA.compose_authority({"state": "stable"}, {"state": "toxic"})
        assert out["temporal_class"] == "authority"
        assert out["settled_state"] == "stable"
        assert out["realtime_state"] == "toxic"
        assert out["realtime_tightened"] is True
        quiet = VA.compose_authority({"state": "toxic"}, {"state": "stable"})
        assert quiet["realtime_tightened"] is False

    def test_an_unrecognised_label_is_neither_safe_nor_severe(self):
        """VACUOUS in its first form -- `_rank(x) == _UNRANKED` is true whatever
        `_UNRANKED` holds, so the mutation `_UNRANKED = 0` (unknown labels are
        SAFEST) escaped the campaign. Assert the PROPERTY, not the identity."""
        unknown = VA._rank("something_new")
        assert unknown > VA.CAUTION_RANK["expanding"], \
            "an unrecognised state must not be treated as permissive as expanding"
        assert unknown > VA.CAUTION_RANK["stable"], \
            "an unrecognised state must not qualify as safe harbour"
        assert unknown < VA.CAUTION_RANK["toxic"], \
            "an unrecognised state must not be treated as a severe-volatility veto"
        assert VA._rank(None) == VA.CAUTION_RANK["unknown"]

    def test_an_unrecognised_realtime_label_cannot_loosen_a_settled_veto(self):
        """The behavioural consequence of the rank above."""
        out = VA.compose_authority({"state": "toxic"}, {"state": "brand_new_state"})
        assert out["state"] == "toxic"

    def test_no_persistence_between_calls(self):
        """Stateless by construction -- 2E.3 must not smuggle in hysteresis."""
        first = VA.compose_authority({"state": "stable"}, {"state": "toxic"})
        second = VA.compose_authority({"state": "stable"}, {"state": "stable"})
        assert first["state"] == "toxic" and second["state"] == "stable"


# ── the invariant, hunted adversarially through the production path ──────────

class TestTheFormingBucketCanTightenButNeverGrant:

    def test_authority_is_never_more_permissive_than_the_settled_baseline(self):
        tightened = collections.Counter()
        for bars in corpus():
            live, base = composed(bars), settled_only(bars)
            for tf in ("3m", "5m", "15m"):
                a = VA._rank((live["volatility"][tf] or {}).get("state"))
                b = VA._rank((base["volatility"][tf] or {}).get("state"))
                assert a >= b, (tf, live["volatility"][tf], base["volatility"][tf])
                if a > b:
                    tightened[tf] += 1
        assert sum(tightened.values()) > 50, \
            f"corpus never exercised tightening: {tightened}"

    def test_a_settled_veto_can_never_be_erased(self):
        """The 68 measured veto-removals are the case this closes."""
        added = 0
        for bars in corpus():
            live, base = composed(bars), settled_only(bars)
            vl = VA.volatility_veto_reason(live.get("ai_context", {}),
                                           live.get("volatility", {}))
            vb = VA.volatility_veto_reason(base.get("ai_context", {}),
                                           base.get("volatility", {}))
            assert not (vb and not vl), "a forming bucket erased a settled veto"
            if vl and not vb:
                added += 1
        assert added > 0, "the corpus never exercised an emergency veto"

    def test_the_risk_multiplier_can_never_be_raised(self):
        lowered = 0
        for bars in corpus():
            live, base = composed(bars), settled_only(bars)
            ml = (live.get("risk") or {}).get("risk_multiplier")
            mb = (base.get("risk") or {}).get("risk_multiplier")
            if ml is None or mb is None:
                continue
            assert ml <= mb, f"forming bucket raised the multiplier {mb} -> {ml}"
            if ml < mb:
                lowered += 1
        assert lowered > 0, "the corpus never exercised tightening"

    def test_extended_stop_authority_can_never_be_granted(self):
        """The stop-geometry grant -- the one that would widen REAL risk."""
        for bars in corpus():
            live, base = composed(bars), settled_only(bars)
            assert not (grants_extended_stop(live) and not grants_extended_stop(base)), \
                "a forming bucket granted extended stop authority"

    def test_the_emergency_brake_still_works(self):
        """Verdict B was a split, not a removal. If realtime could no longer
        tighten at all, 2E.3 would have broken the useful half."""
        braked = 0
        for bars in corpus(seed=31):
            live = composed(bars)
            if any((live["volatility"][tf] or {}).get("realtime_tightened")
                   for tf in ("3m", "5m", "15m")):
                braked += 1
        assert braked > 10, f"realtime volatility can no longer tighten: {braked}"


# ── wiring and provenance ────────────────────────────────────────────────────

class TestWiringAndProvenance:

    def test_all_three_views_are_published(self):
        bars = next(iter(corpus(trials=1)))
        snap = composed(bars)
        for key in ("volatility", "volatility_realtime", "volatility_settled"):
            assert snap[key] and set(snap[key]) >= {"1m", "3m", "5m", "15m"}, key
        assert snap["volatility_realtime"]["5m"]["temporal_class"] == "realtime"
        assert snap["volatility_settled"]["5m"]["temporal_class"] == "settled"
        assert snap["volatility"]["5m"]["temporal_class"] == "authority"

    def test_the_realtime_view_still_sees_the_forming_bucket(self):
        """Safety by blindness is not the goal here either."""
        seen = 0
        for bars in corpus(trials=40):
            live, base = composed(bars), settled_only(bars)
            for tf in ("3m", "5m", "15m"):
                if (live["volatility_realtime"][tf].get("state")
                        != live["volatility_settled"][tf].get("state")):
                    seen += 1
        assert seen > 0, "realtime volatility no longer differs from settled"

    def test_the_authority_view_is_what_consumers_read(self):
        src = inspect.getsource(SB.build_snapshot)
        assert "volatility[tf] = compose_authority(volatility_settled[tf]," in src
        assert "volatility_realtime[tf] = dict(" in src

    def test_the_brain_receives_both_and_can_tell_them_apart(self):
        from ai_brain.brain_input import build_brain_input
        bars = next(iter(corpus(trials=1)))
        payload = build_brain_input(composed(bars), {})["market"]
        assert payload["volatility_state_temporal_class"] == \
            "authority_settled_baseline"
        live = payload["realtime_volatility"]
        assert live, "the Brain lost the realtime read entirely"
        for tf, block in live.items():
            assert block["temporal_class"] == "realtime"
            # CORRECTED BY 2E.3A. This asserted `includes_forming_bucket is True`
            # for EVERY timeframe -- which was the test encoding the bug rather
            # than catching it. The field was hardcoded True, and it is false for
            # 1m in production (the provider never emits a developing minute) and
            # for any timeframe evaluated on a bucket boundary. The truthful
            # assertion is that the flag AGREES with the 2G candle metadata;
            # TestProvenanceIsDerivedNotAsserted pins the specific cases.
            status = block["newest_bucket_temporal_status"]
            assert status in ("settled", "forming", "unknown"), (tf, status)
            assert block["includes_forming_bucket"] is (
                True if status == "forming" else False if status == "settled" else None)
            assert "settled_state" in block and "realtime_tightened" in block

    def test_an_archive_without_the_block_omits_it_rather_than_faking_it(self):
        from ai_brain.brain_input import build_brain_input
        payload = build_brain_input({"timestamp": "t"}, {})["market"]
        assert payload["realtime_volatility"] == {}


# ── CONTINUITY-2E.3A — provenance closure ────────────────────────────────────

class TestNoSettledBaselineMeansNoAuthority:
    """`compose_authority`'s no-settled branch. PROVEN UNREACHABLE from the
    production path -- `classify_volatility` always returns a populated
    `state: "unknown"` block rather than `{}`, and the only skip in
    `build_snapshot` (`if not candles: continue`) omits the timeframe entirely
    instead of composing it. Made fail-closed anyway: realtime must not hold
    authority precisely when the baseline that bounds it is missing."""

    def test_the_classifier_never_returns_an_empty_block(self):
        from volatility.atr_engine import calculate_atr
        from volatility.volatility_classifier import classify_volatility
        for candles in ([], [{"open": 1, "high": 2, "low": 0, "close": 1,
                              "range": 2, "body_size": 0, "direction": "neutral"}]):
            out = classify_volatility(candles, calculate_atr(candles))
            assert out and out.get("state") is not None

    def test_production_never_produces_a_realtime_only_authority(self):
        for minutes in (60, 61, 74, 75, 120, 300):
            rng = random.Random(minutes)
            bars, _ = series(rng, minutes, 3.0)
            snap = composed(bars)
            for tf, block in (snap.get("volatility") or {}).items():
                assert block.get("temporal_class") == "authority", (minutes, tf, block)

    def test_the_branch_fails_closed_rather_than_granting(self):
        out = VA.compose_authority({}, {"state": "expanding", "volatility_score": 90})
        assert out["state"] == "unknown"
        assert out["temporal_class"] == "unknown_no_settled_baseline"
        assert out["settled_state"] is None
        assert out["realtime_tightened"] is False
        assert VA._rank(out["state"]) > VA.CAUTION_RANK["expanding"], \
            "a missing baseline must not leave the most permissive state standing"

    def test_and_therefore_cannot_grant_extended_stop(self):
        """Isolating the VOLATILITY term. `extended_volatility_supported` grants
        on `elevated OR expanding`, and `expanding` reads `expansion_state` --
        so passing `mature_expansion` here (as a first draft of this test did)
        grants via EXPANSION and proves nothing about volatility. Expansion is
        settled as of 2E.1; this test is about the volatility half."""
        out = VA.compose_authority(None, {"state": "expanding"})
        ok, why = extended_volatility_supported({
            "volatility_state": out["state"], "expansion_state": "compression",
            "structural_level_identity": "X"})
        assert ok is False and "volatility state does not support" in why

    def test_a_realtime_expanding_state_cannot_grant_it_either(self):
        """The composed path, not just the fail-closed branch."""
        out = VA.compose_authority({"state": "stable"}, {"state": "expanding"})
        ok, _ = extended_volatility_supported({
            "volatility_state": out["state"], "expansion_state": "compression",
            "structural_level_identity": "X"})
        assert ok is False


class TestProvenanceIsDerivedNotAsserted:
    """The Brain must never be told the evidence contains a forming candle when
    it does not. Derived from the 2G candle metadata -- no second detector."""

    def payload(self, bars):
        from ai_brain.brain_input import build_brain_input
        return build_brain_input(composed(bars), {})["market"]

    def test_one_minute_never_claims_a_forming_bucket(self):
        """The provider emits only completed minutes, so 1m is always settled."""
        for minutes in (75, 120, 300):
            rng = random.Random(minutes)
            bars, _ = series(rng, minutes, 3.0)
            live = self.payload(bars)["realtime_volatility"]["1m"]
            assert live["newest_bucket_temporal_status"] == "settled"
            assert live["includes_forming_bucket"] is False

    def test_a_higher_timeframe_on_a_bucket_boundary_reports_false(self):
        """300 minutes divides exactly by 3/5/15 -- no forming bucket exists."""
        rng = random.Random(9)
        bars, _ = series(rng, 300, 3.0)
        live = self.payload(bars)["realtime_volatility"]
        for tf in ("3m", "5m", "15m"):
            assert live[tf]["newest_bucket_temporal_status"] == "settled", tf
            assert live[tf]["includes_forming_bucket"] is False, tf

    def test_and_reports_true_only_when_one_actually_exists(self):
        rng = random.Random(9)
        bars, _ = series(rng, 302, 3.0)          # 2 minutes into the next bucket
        live = self.payload(bars)["realtime_volatility"]
        for tf in ("3m", "5m", "15m"):
            assert live[tf]["includes_forming_bucket"] is True, tf
            assert live[tf]["newest_bucket_temporal_status"] == "forming", tf
        assert live["1m"]["includes_forming_bucket"] is False

    def test_unknown_completeness_is_not_reported_as_settled(self):
        """Claiming False where 2G says `unknown` would assert a settlement that
        was never recorded."""
        rng = random.Random(4)
        bars, _ = series(rng, 200, 3.0)
        raw = build_timeframes(bars)
        stripped = {tf: [{k: v for k, v in b.items()
                          if k not in ("complete", "members", "expected_members")}
                         for b in rows] for tf, rows in raw.items()}
        from ai_brain.brain_input import build_brain_input
        snap = SB.build_snapshot(stripped, symbol="MNQ")
        live = build_brain_input(snap, {})["market"]["realtime_volatility"]
        for tf, block in live.items():
            assert block["newest_bucket_temporal_status"] == "unknown", tf
            assert block["includes_forming_bucket"] is None, tf

    def test_the_authority_label_describes_the_object_delivered(self):
        rng = random.Random(2)
        bars, _ = series(rng, 200, 3.0)
        assert self.payload(bars)["volatility_state_temporal_class"] == \
            "authority_settled_baseline"

    def test_the_label_follows_a_fail_closed_authority_block(self):
        from ai_brain.brain_input import _authority_temporal_class
        assert _authority_temporal_class(
            {"volatility": {"15m": {"temporal_class": "unknown_no_settled_baseline"}}}
        ) == "unknown_no_settled_baseline"
        assert _authority_temporal_class({"volatility": {}}) == "unavailable"
        assert _authority_temporal_class({}) == "unavailable"

    def test_the_payload_label_is_read_from_the_block_not_asserted(self):
        """The test above only covers the HELPER. Re-hardcoding the constant at
        the CALL SITE escaped the mutation campaign, because in production the
        value genuinely is `authority_settled_baseline` -- so a hardcoded
        constant and a derived one are indistinguishable on real snapshots.
        This drives a snapshot whose 15m block is NOT `authority` through
        `build_brain_input` itself, where only a derived label can be right."""
        from ai_brain.brain_input import build_brain_input
        for cls, expected in (("unknown_no_settled_baseline",
                               "unknown_no_settled_baseline"),
                              ("authority", "authority_settled_baseline")):
            payload = build_brain_input(
                {"timestamp": "t", "volatility": {"15m": {"temporal_class": cls}}},
                {})["market"]
            assert payload["volatility_state_temporal_class"] == expected, cls
        absent = build_brain_input({"timestamp": "t"}, {})["market"]
        assert absent["volatility_state_temporal_class"] == "unavailable"


# ── explicitly out of scope ──────────────────────────────────────────────────

class TestOutOfScope:

    def test_the_extended_stop_lane_stays_starved(self):
        """`luna_candidate_producer` still does not populate
        extras["volatility_state"], so the extended lane remains unreachable.
        2E.3 deliberately did NOT wire it -- that is a separate decision, and
        one key accidentally absent is not a safety mechanism. Pinned so the
        starvation stays visible instead of being mistaken for design."""
        from broker import luna_candidate_producer as LP
        src = inspect.getsource(LP)
        assert '"volatility_state"' not in src
        assert '"volatility_evidence"' not in src

    def test_toolbox_zone_witness_survived_2f(self):
        """SUPERSEDED BY 2F (2026-08-12). This guarded that 2E.3 had not touched
        the toolbox, by pinning the literal `recent_candles` read inside
        `build_price_level`. 2F moved that read into `_locate_zone` and split the
        zone into a realtime witness plus an execution-eligibility verdict, so
        the string is gone while the property it protected -- the toolbox still
        SEES the forming bar -- is intact. Re-expressed as that property."""
        from toolbox import price_levels as PL
        src = inspect.getsource(PL._locate_zone)
        assert 'tfs.get(tf, {}).get("recent_candles") or []' in src
        assert "settled_only" in src

    def test_classify_volatility_itself_was_not_changed(self):
        from volatility import volatility_classifier as VC
        src = inspect.getsource(VC.classify_volatility)
        assert "atr_result[\"atr_trend\"]" in src
        assert "compose" not in src and "settled" not in src, \
            "the classifier must stay a pure function of what it is handed"
