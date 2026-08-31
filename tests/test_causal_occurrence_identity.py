"""CAUSAL-OCCURRENCE-IDENTITY-1A — which market event, not which observation.

CATEGORY A ONLY. Settled-bar-derived events (LIQUIDITY_SWEEP, STRUCTURE_BREAK)
gain causal identity here. The protected-swing family is REFUSED and returns in
CAUSAL-OCCURRENCE-IDENTITY-1B.

PROTECTED-SWING-CAUSAL-TIME-1 has since removed what BLOCKED Category B -- a
swing life now keeps one immutable birthday -- so `TestCategoryBIsRefused` no
longer records an impossibility. It records a boundary: the provenance is
correct and the key is still deliberately not minted here.

THE DEFECT. `occurrence_id` was minted from the SCAN clock, so one 15m
structure break entered the durable ledger fifteen times -- once per 1m scan
that re-observed the same settled bucket. Measured on the real 2026-08-25 tape:
84 raw observations, 84 distinct v1 identities, 52 actual market events.

WHAT THIS UNIT IS AND IS NOT. It adds v2 CAPABILITY. It does not activate v2 for
any production session: v1 remains the default everywhere, and who may select v2
in production belongs to CAUSAL-IDENTITY-VERSION-GATE-1. The inertness class
below is the load-bearing half of that promise.

NO BROKER, NO PROVIDER, NO NETWORK, NO ORDER.
"""
from __future__ import annotations

import glob
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from data_feed.timeframe_builder import build_timeframes            # noqa: E402
from market_data import causal_identity as CI                       # noqa: E402
from market_data import occurrence_ledger as OL                     # noqa: E402
from market_data.snapshot_builder import (build_snapshot,           # noqa: E402
                                          settled_source_provenance)
from market_state.active_path import ActivePath, extract_occurrences  # noqa: E402
from narrative_authority.protected_swings import ProtectedSwingTracker  # noqa: E402

CID = "CON.F.US.MNQ.U26"
V1, V2 = CI.CAUSAL_IDENTITY_V1, CI.CAUSAL_IDENTITY_V2
ARCHIVE = os.path.join(ROOT, "data", "ai_brain")


def tape(day="20260825"):
    seen = {}
    for f in sorted(glob.glob(os.path.join(ARCHIVE, f"{day}_*_MNQ.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                snap = json.load(fh)["raw_snapshot"]
        except Exception:  # noqa: BLE001
            continue
        for c in ((snap.get("timeframes") or {}).get("1m") or {}).get(
                "recent_candles") or []:
            if c.get("timestamp"):
                seen[str(c["timestamp"])] = c
    return [seen[k] for k in sorted(seen)]


def replay(bars, *, version=V2, min_bars=30, start_at=None):
    """The canonical growing-window rebuild, then occurrences + path."""
    tracker = ProtectedSwingTracker()
    path = ActivePath(causal_identity_version=version)
    prior, rows = {}, []
    for end in range(min_bars, len(bars) + 1):
        window = bars[:end]
        at = str(window[-1]["timestamp"])
        snap = build_snapshot(build_timeframes(window), ref_timestamp=at,
                              symbol="MNQ", swing_tracker=tracker,
                              contract_id=CID, execution_price=None)
        occ = extract_occurrences(snap, prior, CID)
        prior = ((snap.get("protected_swings") or {}).get("by_timeframe") or prior)
        if start_at and at < start_at:
            continue
        path.enforce_lifecycle(snap.get("timestamp"), CID)
        path.ingest(occ)
        path.mark_scan_end()
        rows.extend(occ)
    return path, rows, tracker


@pytest.fixture(scope="module")
def real():
    bars = tape()
    if len(bars) < 40:
        pytest.skip("archived 1m tape absent")
    return bars


@pytest.fixture(scope="module")
def observed(real):
    _path, rows, _tr = replay(real)
    return rows


def sweep(**kw):
    base = {"event_type": CI.LIQUIDITY_SWEEP, "contract": CID, "source_tf": "15m",
            "source_bar_time": "2026-08-25T14:00:00+00:00",
            "sweep_direction": "below_low", "swept_level": 29145.5}
    base.update(kw)
    return base


# ══ CATEGORY A — the authoring bucket, never the scan ═══════════════════════
class TestCategoryA:

    def test_repeated_observation_of_one_settled_edge_is_one_event(self, observed):
        """The whole defect, on the real tape. A 15m break observed on fifteen
        consecutive 1m scans is fifteen v1 identities and ONE market event."""
        rows = [r for r in observed
                if r["event_type"] == CI.STRUCTURE_BREAK and r["source_tf"] == "15m"]
        assert len(rows) > 1, "no repeated HTF observation on this tape"
        assert len({r["occurrence_id"] for r in rows}) == len(rows)
        assert len({CI.causal_event_key(r) for r in rows}) == 1

    @pytest.mark.parametrize("tf", ["3m", "5m", "15m"])
    def test_every_htf_collapses(self, observed, tf):
        rows = [r for r in observed
                if r["event_type"] == CI.STRUCTURE_BREAK and r["source_tf"] == tf]
        if not rows:
            pytest.skip(f"no {tf} break on this tape")
        v1 = len({r["occurrence_id"] for r in rows})
        v2 = len({CI.causal_event_key(r) for r in rows})
        assert v2 <= v1
        assert v2 == len({(r["source_bar_time"], r["direction"], r["broken_level"])
                          for r in rows})

    def test_one_minute_does_not_collapse(self, observed):
        """1m is the scan cadence, so v1 was already right there. A v2 that
        merged 1m events would be over-collapsing, not fixing anything."""
        rows = [r for r in observed if r["source_tf"] == "1m"
                and r["event_type"] in CI.CATEGORY_A]
        assert len({r["occurrence_id"] for r in rows}) == \
            len({CI.causal_event_key(r) for r in rows})

    def test_different_source_buckets_are_different_events(self):
        a = sweep(source_bar_time="2026-08-25T14:00:00+00:00")
        b = sweep(source_bar_time="2026-08-25T14:15:00+00:00")
        assert CI.causal_event_key(a) != CI.causal_event_key(b)

    def test_same_bucket_opposite_direction_is_a_different_event(self):
        assert CI.causal_event_key(sweep(sweep_direction="below_low")) != \
            CI.causal_event_key(sweep(sweep_direction="above_high"))

    def test_timezone_spellings_are_one_identity(self):
        z = sweep(source_bar_time="2026-08-25T14:00:00Z")
        offset = sweep(source_bar_time="2026-08-25T10:00:00-04:00")
        assert CI.causal_event_key(z) == CI.causal_event_key(offset)

    def test_level_spellings_are_one_identity(self):
        assert CI.causal_event_key(sweep(swept_level=29145.5)) == \
            CI.causal_event_key(sweep(swept_level=29145.50))

    def test_no_source_bar_means_no_key(self):
        """FAIL CLOSED. A snapshot from an older path publishes no
        `settled_source`; the honest answer is 'I cannot identify this', never a
        key built from the scan clock."""
        assert CI.causal_event_key(sweep(source_bar_time=None)) is None

    def test_the_scan_clock_is_absent_from_the_key(self):
        a = dict(sweep(), event_time="2026-08-25T14:03:00+00:00",
                 observed_at="2026-08-25T14:03:00+00:00")
        b = dict(sweep(), event_time="2026-08-25T14:11:00+00:00",
                 observed_at="2026-08-25T14:11:00+00:00")
        assert CI.causal_event_key(a) == CI.causal_event_key(b)


# ══ SETTLED SOURCE — three clocks, never interchangeable ════════════════════
class TestSettledSourceProvenance:

    def test_the_snapshot_publishes_the_authoring_bucket(self, real):
        snap = build_snapshot(build_timeframes(real),
                              ref_timestamp=str(real[-1]["timestamp"]),
                              symbol="MNQ", contract_id=CID, execution_price=None)
        block = snap["settled_source"]
        assert set(block) == {"15m", "5m", "3m", "1m"}
        for tf in ("15m", "5m", "3m", "1m"):
            assert block[tf]["source_bar_time"], tf

    def test_the_source_bar_is_never_after_the_scan(self, real):
        at = str(real[-1]["timestamp"])
        snap = build_snapshot(build_timeframes(real), ref_timestamp=at,
                              symbol="MNQ", contract_id=CID, execution_price=None)
        for tf, block in snap["settled_source"].items():
            assert block["source_bar_time"] <= at, tf

    def test_a_higher_timeframe_bucket_opens_before_a_lower_one(self, real):
        snap = build_snapshot(build_timeframes(real),
                              ref_timestamp=str(real[-1]["timestamp"]),
                              symbol="MNQ", contract_id=CID, execution_price=None)
        b = snap["settled_source"]
        assert b["15m"]["source_bar_time"] <= b["5m"]["source_bar_time"] \
            <= b["3m"]["source_bar_time"] <= b["1m"]["source_bar_time"]

    def test_the_edge_comes_from_the_member_list_or_is_absent(self, real):
        """No arithmetic. A 1m bucket publishes no member list, so it honestly
        has no terminal constituent to name rather than a derived one."""
        snap = build_snapshot(build_timeframes(real),
                              ref_timestamp=str(real[-1]["timestamp"]),
                              symbol="MNQ", contract_id=CID, execution_price=None)
        for tf in ("15m", "5m", "3m"):
            block = snap["settled_source"][tf]
            assert block["settled_edge_basis"] == "source_member_times[-1]"
            assert block["settled_edge_time"] >= block["source_bar_time"]
        one = snap["settled_source"]["1m"]
        assert one["settled_edge_time"] is None
        assert one["settled_edge_basis"] == "no_member_list_published"

    def test_an_empty_series_reports_absence(self):
        assert settled_source_provenance([], [])["source_bar_time"] is None


# ══ CATEGORY B — provenance CARRIED, identity REFUSED ═══════════════════════
class TestCategoryBIsRefused:
    """1A ships Category A only.

    `(swing_id, registered_at)` SEPARATES two lives of one price, and since
    PROTECTED-SWING-CAUSAL-TIME-1 it also UNIFIES one life -- the tracker no
    longer re-stamps a living swing, so the two properties an identity needs are
    both present and the causal chain closes below.

    THE KEY IS STILL NOT MINTED HERE. Wiring that provenance into
    `causal_event_key` is CAUSAL-OCCURRENCE-IDENTITY-1B, deliberately a separate
    unit: this file certifies that Category B is REFUSED, and 1B is what flips
    it. Refusal is still the correct behaviour until then.
    """

    def test_no_category_b_event_mints_a_key(self, observed):
        rows = [r for r in observed if r["event_type"] in CI.CATEGORY_B]
        assert rows, "no protected-swing transition on this tape"
        assert {CI.causal_event_key(r) for r in rows} == {None}

    def test_the_refusal_names_its_blocker(self, observed):
        rows = [r for r in observed if r["event_type"] in CI.CATEGORY_B]
        for r in rows:
            reason = CI.refusal_reason(r)
            assert reason == CI.CATEGORY_B_BLOCKED
            assert "PROTECTED-SWING-CAUSAL-TIME-1" in reason

    def test_a_category_a_refusal_is_a_different_reason(self):
        """A missing source bar is a real provenance gap with its own owner, not
        the known Category B block. Collapsing the two would hide a defect."""
        reason = CI.refusal_reason(sweep(source_bar_time=None))
        assert reason and reason != CI.CATEGORY_B_BLOCKED

    def test_violated_still_carries_the_dying_swing(self, observed):
        """The emitter used to drop `swing_id` even though `old` held it. That
        repair is factual and stays -- it is what 1B will build identity on."""
        rows = [r for r in observed if r["event_type"] == CI.PROTECTED_SWING_VIOLATED]
        assert rows, "no violation on this tape"
        for r in rows:
            assert r["swing_id"], r
            assert r["registered_at"], r

    def test_replaced_still_carries_both_ends(self, observed):
        rows = [r for r in observed if r["event_type"] == CI.PROTECTED_SWING_REPLACED]
        assert rows, "no replacement on this tape"
        for r in rows:
            assert r["old_swing_id"] and r["old_registered_at"]
            assert r["swing_id"] and r["registered_at"]
            assert (r["old_swing_id"], r["old_registered_at"]) != \
                (r["swing_id"], r["registered_at"])

    def test_a_v2_ledger_refuses_category_b(self, observed, tmp_path):
        led = OL.OccurrenceLedger(CID, directory=str(tmp_path),
                                  causal_identity_version=V2)
        rows = [r for r in observed if r["event_type"] in CI.CATEGORY_B]
        for r in rows:
            assert led.record(r)["outcome"] == OL.REJECTED
        assert led.occurrences() == []

    def test_a_v2_path_refuses_category_b_and_says_why(self, observed):
        path = ActivePath(causal_identity_version=V2)
        rows = [r for r in observed if r["event_type"] in CI.CATEGORY_B]
        path.ingest(rows)
        assert path.events == []
        assert len(path.unidentified) == len(rows)
        assert {u["reason"] for u in path.unidentified} == {CI.CATEGORY_B_BLOCKED}

    def test_a_violation_names_the_registration_it_kills(self, observed):
        """THE CAUSAL CHAIN CLOSES. Every swing that died must be a swing that
        was born, identified the same way.

        HISTORY, kept deliberately. This shipped in
        CAUSAL-OCCURRENCE-IDENTITY-1A as a STRICT xfail, because it could not
        pass: `protected_swings._update` re-stamped `registered_at` whenever an
        already-live level was reaffirmed, so a violation named the swing's LAST
        stamp, which no registration had ever carried. Measured then:
        1m:swing_low:29301 lived unbroken 13:43 -> 14:02 under five stamps, and
        its violation named 14:01 while its birth said 13:43.

        PROTECTED-SWING-CAUSAL-TIME-1 gave one continuous life one immutable
        birthday, the xfail XPASSed, and it is now an ordinary regression. What
        it prevents is the return of a tracker that lets formation time move
        under a living swing.
        """
        born = {(r["swing_id"], r["registered_at"]) for r in observed
                if r["event_type"] == CI.PROTECTED_SWING_REGISTERED}
        replaced = {(r["swing_id"], r["registered_at"]) for r in observed
                    if r["event_type"] == CI.PROTECTED_SWING_REPLACED}
        died = [(r["swing_id"], r["registered_at"]) for r in observed
                if r["event_type"] == CI.PROTECTED_SWING_VIOLATED]
        assert died, "no violation on this tape"
        for d in died:
            assert d in born or d in replaced, d

    def test_no_living_swing_is_ever_restamped_on_the_real_tape(self, real):
        """THE INVERSE OF THE 1A MEASUREMENT, on the same tape.

        1A pinned the defect by asserting a re-stamp COULD be found. That pin
        had a flaw worth recording: it carried per-slot state across a slot
        VACANCY, so once the tracker was fixed it kept passing by mistaking a
        genuinely new life at a repeated price for a re-stamp. Clearing on
        vacancy is what makes the two distinguishable, and it is the same
        distinction the tracker itself now draws.
        """
        tracker = ProtectedSwingTracker()
        prior, live = {}, {}
        restamped = []
        for end in range(30, len(real) + 1):
            w = real[:end]
            at = str(w[-1]["timestamp"])
            snap = build_snapshot(build_timeframes(w), ref_timestamp=at,
                                  symbol="MNQ", swing_tracker=tracker,
                                  contract_id=CID, execution_price=None)
            extract_occurrences(snap, prior, CID)
            by = (snap.get("protected_swings") or {}).get("by_timeframe") or {}
            for side in ("lows", "highs"):
                block = by.get(side) or {}
                for tf, rec in block.items():
                    slot, sid = (side, tf), rec.get("swing_id")
                    was = live.get(slot)
                    if was and was[0] == sid and was[1] != rec.get("registered_at"):
                        restamped.append((at, sid, was[1], rec.get("registered_at")))
                    live[slot] = (sid, rec.get("registered_at"))
                # A VACATED SLOT ENDS THE LIFE. The next occupant is new even at
                # the identical price, and must not inherit a birthday.
                for slot in [k for k in live if k[0] == side and k[1] not in block]:
                    live.pop(slot, None)
            prior = by or prior
        assert restamped == [], restamped

    def test_a_repeated_price_after_death_is_a_new_life_on_the_real_tape(self, real):
        """FOUND IN LIVE DATA, not constructed. On 2026-08-25 the 1m protected
        low at 29233.5 formed at 14:20, was violated (its slot stood empty
        14:23-14:25), and re-formed at the IDENTICAL price at 14:26.

        Preserving formation time through reaffirmation must NOT extend a
        birthday across a death. Same swing_id, two lives, two birthdays."""
        tracker = ProtectedSwingTracker()
        prior, seen = {}, []
        for end in range(30, len(real) + 1):
            w = real[:end]
            at = str(w[-1]["timestamp"])
            snap = build_snapshot(build_timeframes(w), ref_timestamp=at,
                                  symbol="MNQ", swing_tracker=tracker,
                                  contract_id=CID, execution_price=None)
            extract_occurrences(snap, prior, CID)
            by = (snap.get("protected_swings") or {}).get("by_timeframe") or {}
            rec = (by.get("lows") or {}).get("1m") or {}
            if rec.get("swing_id") == "1m:swing_low:29233.5":
                seen.append((at, rec.get("registered_at")))
            prior = by or prior
        if not seen:
            pytest.skip("the 29233.5 specimen is absent from this archive")
        stamps = sorted({r for _s, r in seen})
        assert len(stamps) == 2, f"expected two lives at one price, got {stamps}"
        assert stamps[0] < stamps[1]


# ══ THE SAME-PRICE REFORMATION REGRESSION — load-bearing ════════════════════
class TestSamePriceReformation:
    """GATE 1, made permanent. Driven through the REAL `ProtectedSwingTracker`:
    a level registers, is violated, and re-forms at the IDENTICAL price. Two
    lives of one price, distinguishable only by `registered_at`."""

    X = 29145.5

    @staticmethod
    def snap(ts, price, *, sweep_low=None):
        liq = {"1m": {}}
        if sweep_low is not None:
            liq["1m"] = {"sweep_detected": True, "reclaim_detected": True,
                         "sweep_direction": "below_low"}
        st = {"1m": {}}
        if sweep_low is not None:
            st["1m"]["last_swing_low"] = sweep_low
        return {"timestamp": ts, "liquidity": liq, "structure": st,
                "execution_price": {"available": True, "fresh": True,
                                    "best_bid": price, "best_ask": price + 0.25},
                "market": {"current_price": price},
                "timeframes": {"1m": {"last_candle": {"close": price}}}}

    @pytest.fixture(scope="class")
    def lives(self):
        tracker = ProtectedSwingTracker()
        prior, events = {}, []
        steps = [("2026-08-25T13:10:00+00:00", self.X + 20, self.X),
                 ("2026-08-25T13:11:00+00:00", self.X + 15, None),
                 ("2026-08-25T13:20:00+00:00", self.X - 60, None),
                 ("2026-08-25T13:30:00+00:00", self.X + 20, self.X),
                 ("2026-08-25T13:31:00+00:00", self.X + 18, None)]
        for ts, price, low in steps:
            s = self.snap(ts, price, sweep_low=low)
            tracker.update(s)
            s["protected_swings"] = tracker.state()
            events.extend(extract_occurrences(s, prior, CID))
            prior = (s["protected_swings"].get("by_timeframe") or prior)
        return events

    def test_the_reformation_actually_happened(self, lives):
        regs = [e for e in lives if e["event_type"] == CI.PROTECTED_SWING_REGISTERED]
        assert len(regs) >= 2, "the tracker did not re-form the level"
        assert regs[0]["swing_id"] == regs[1]["swing_id"], "not the same price"
        assert regs[0]["registered_at"] != regs[1]["registered_at"]

    def test_swing_id_alone_would_have_collapsed_them(self, lives):
        """THE SEPARATION PROPERTY, which survives 1A intact: one swing_id, two
        formation stamps. This is the half that works, and it is why
        `registered_at` is still the right raw material for 1B."""
        regs = [e for e in lives if e["event_type"] == CI.PROTECTED_SWING_REGISTERED]
        assert len({e["swing_id"] for e in regs[:2]}) == 1
        assert len({e["registered_at"] for e in regs[:2]}) == 2

    def test_the_violation_belongs_to_the_first_life(self, lives):
        regs = [e for e in lives if e["event_type"] == CI.PROTECTED_SWING_REGISTERED]
        viol = [e for e in lives if e["event_type"] == CI.PROTECTED_SWING_VIOLATED]
        assert viol, "the level was never violated"
        assert viol[0]["registered_at"] == regs[0]["registered_at"]
        assert viol[0]["registered_at"] != regs[1]["registered_at"]

    def test_the_violation_provenance_distinguishes_the_two_lives(self, lives):
        regs = [e for e in lives if e["event_type"] == CI.PROTECTED_SWING_REGISTERED]
        a = (regs[0]["swing_id"], regs[0]["registered_at"])
        b = (regs[1]["swing_id"], regs[1]["registered_at"])
        assert a[0] == b[0] and a != b

    def test_both_lives_survive_a_v1_ledger(self, lives, tmp_path):
        """v1 keys these by scan time, which happens to keep both. 1B must reach
        the same answer for the RIGHT reason -- by their formation, not by when
        the process looked."""
        led = OL.OccurrenceLedger(CID, directory=str(tmp_path))
        for e in lives:
            led.record(e)
        regs = led.occurrences(event_type=CI.PROTECTED_SWING_REGISTERED)
        assert len(regs) == 2, "one life was swallowed by the other"


# ══ VERSION IS EXPLICIT, AND CHOOSES EXACTLY ONE AUTHORITY ══════════════════
class TestVersionAuthority:

    def test_v1_is_the_default(self):
        assert CI.DEFAULT_CAUSAL_IDENTITY_VERSION == V1
        assert CI.resolve_version(None) == V1
        assert ActivePath().causal_identity_version == V1
        assert OL.OccurrenceLedger(CID, directory="x").causal_identity_version == V1

    def test_v1_uses_observation_identity_only(self):
        occ = sweep(occurrence_id="LEGACY")
        assert CI.identity_of(occ, V1) == "LEGACY"

    def test_v2_uses_causal_identity_only(self):
        occ = sweep(occurrence_id="LEGACY")
        assert CI.identity_of(occ, V2) == CI.causal_event_key(occ)
        assert CI.identity_of(occ, V2) != "LEGACY"

    def test_v2_never_falls_back_to_occurrence_id(self):
        """The mixed-epistemology refusal, stated as a test. An unidentifiable
        event yields None -- it does NOT quietly become its witness id."""
        occ = sweep(occurrence_id="LEGACY", source_bar_time=None)
        assert CI.identity_of(occ, V2) is None

    @pytest.mark.parametrize("bad", [0, 3, 99, "two", -1])
    def test_an_unknown_version_is_refused(self, bad):
        with pytest.raises(CI.UnsupportedCausalIdentityVersion):
            CI.resolve_version(bad)

    def test_a_ledger_refuses_an_unknown_version(self, tmp_path):
        with pytest.raises(CI.UnsupportedCausalIdentityVersion):
            OL.OccurrenceLedger(CID, directory=str(tmp_path),
                                causal_identity_version=7)


# ══ LEDGER ══════════════════════════════════════════════════════════════════
class TestLedger:

    @staticmethod
    def observation(n, **kw):
        """One market event, observed on scan `n`."""
        base = sweep(occurrence_id=f"LIQUIDITY_SWEEP:{CID}:15m:scan{n}",
                     event_time=f"2026-08-25T14:{n:02d}:00+00:00",
                     observed_at=f"2026-08-25T14:{n:02d}:00+00:00")
        base.update(kw)
        return base

    def test_v1_dedup_is_unchanged(self, tmp_path):
        led = OL.OccurrenceLedger(CID, directory=str(tmp_path))
        a = led.record(self.observation(1))
        b = led.record(self.observation(2))
        assert a["outcome"] == OL.RECORDED and b["outcome"] == OL.RECORDED
        assert led.record(self.observation(1))["outcome"] == OL.DUPLICATE
        assert len(led.occurrences()) == 2, "v1 must still count observations"

    def test_v2_collapses_re_observation_to_one_event(self, tmp_path):
        led = OL.OccurrenceLedger(CID, directory=str(tmp_path),
                                  causal_identity_version=V2)
        outcomes = [led.record(self.observation(n))["outcome"] for n in range(1, 6)]
        assert outcomes[0] == OL.RECORDED
        assert set(outcomes[1:]) == {OL.DUPLICATE}
        assert len(led.occurrences()) == 1

    def test_the_scan_clock_is_not_a_v2_integrity_conflict(self, tmp_path):
        """Under v2 a row is a MARKET event; a later sighting legitimately
        carries a later clock. Treating that as a rewrite would make every
        second observation a conflict."""
        led = OL.OccurrenceLedger(CID, directory=str(tmp_path),
                                  causal_identity_version=V2)
        led.record(self.observation(1))
        led.record(self.observation(9))
        assert led.health()["integrity_conflicts"] == 0

    def test_v2_still_refuses_a_rewritten_market_fact(self, tmp_path):
        led = OL.OccurrenceLedger(CID, directory=str(tmp_path),
                                  causal_identity_version=V2)
        led.record(self.observation(1))
        out = led.record(self.observation(2, liquidity_side_taken="buy_side"))
        assert out["outcome"] == OL.CONFLICT

    def test_v2_retains_occurrence_id_as_witness(self, tmp_path):
        led = OL.OccurrenceLedger(CID, directory=str(tmp_path),
                                  causal_identity_version=V2)
        led.record(self.observation(1))
        row = led.occurrences()[0]
        assert row["occurrence_id"] == f"LIQUIDITY_SWEEP:{CID}:15m:scan1"
        assert row["event_time"] == "2026-08-25T14:01:00+00:00"

    def test_v2_reload_dedups_from_disk(self, tmp_path):
        led = OL.OccurrenceLedger(CID, directory=str(tmp_path),
                                  causal_identity_version=V2)
        for n in range(1, 4):
            led.record(self.observation(n))
        again = OL.OccurrenceLedger(CID, directory=str(tmp_path),
                                    causal_identity_version=V2)
        assert again.health()["status"] == OL.HEALTHY
        assert len(again.occurrences()) == 1
        assert again.record(self.observation(7))["outcome"] == OL.DUPLICATE

    def test_v2_refuses_an_unidentifiable_event(self, tmp_path):
        led = OL.OccurrenceLedger(CID, directory=str(tmp_path),
                                  causal_identity_version=V2)
        out = led.record(self.observation(1, source_bar_time=None))
        assert out["outcome"] == OL.REJECTED
        assert led.occurrences() == []

    def test_the_two_versions_never_share_a_file(self, tmp_path):
        v1 = OL.OccurrenceLedger(CID, directory=str(tmp_path))
        v2 = OL.OccurrenceLedger(CID, directory=str(tmp_path),
                                 causal_identity_version=V2)
        assert v1.path != v2.path
        v1.record(self.observation(1))
        v2.record(self.observation(1))
        assert os.path.exists(v1.path) and os.path.exists(v2.path)
        assert len(OL.OccurrenceLedger(CID, directory=str(tmp_path)).occurrences()) == 1

    def test_a_v1_store_may_not_be_read_as_v2(self, tmp_path):
        """The silent-history-rewrite refusal. Observation identities read under
        market-identity law would report DUPLICATE for events never seen."""
        v1 = OL.OccurrenceLedger(CID, directory=str(tmp_path))
        v1.record(self.observation(1))
        os.replace(v1.path, os.path.join(str(tmp_path),
                                         f"{CID}{OL.V2_SUFFIX}.json"))
        mis = OL.OccurrenceLedger(CID, directory=str(tmp_path),
                                  causal_identity_version=V2)
        assert mis.health()["status"] == OL.DEGRADED
        assert "causal identity version" in mis.health()["detail"]

    def test_a_legacy_unstamped_store_still_loads_as_v1(self, tmp_path):
        """Files written before versions existed carry no stamp. They are v1 by
        definition and must not be degraded for saying nothing."""
        path = os.path.join(str(tmp_path), f"{CID}.json")
        row = self.observation(1)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"schema": OL.SCHEMA, "contract": CID,
                       "occurrences": {row["occurrence_id"]: row}}, fh)
        led = OL.OccurrenceLedger(CID, directory=str(tmp_path))
        assert led.health()["status"] == OL.HEALTHY
        assert len(led.occurrences()) == 1


# ══ ACTIVE PATH ═════════════════════════════════════════════════════════════
class TestActivePathDedup:

    @staticmethod
    def break_at(n, tf="15m"):
        return {"occurrence_id": f"STRUCTURE_BREAK:{CID}:{tf}:scan{n}",
                "event_type": CI.STRUCTURE_BREAK, "contract": CID,
                "source_tf": tf, "direction": "bullish", "broken_level": 29300.0,
                "source_bar_time": "2026-08-25T14:00:00+00:00",
                "event_time": f"2026-08-25T14:{n:02d}:00+00:00",
                "observed_at": f"2026-08-25T14:{n:02d}:00+00:00"}

    def test_v1_dedup_is_unchanged(self):
        p = ActivePath()
        p.ingest([self.break_at(1), self.break_at(1), self.break_at(2)])
        assert len(p.events) == 2, "v1 counts observations, as it always did"

    def test_v2_applies_one_market_event_once(self):
        p = ActivePath(causal_identity_version=V2)
        p.ingest([self.break_at(n) for n in range(1, 8)])
        assert len(p.events) == 1
        assert p.unidentified == []

    def test_v2_refuses_rather_than_ingesting_unidentified(self):
        """Ingesting undeduped would reintroduce the multiple counting; a
        manufactured key would be worse. Refusal is recorded, not silent."""
        p = ActivePath(causal_identity_version=V2)
        p.ingest([dict(self.break_at(1), source_bar_time=None)])
        assert p.events == []
        assert len(p.unidentified) == 1
        assert p.unidentified[0]["event_type"] == CI.STRUCTURE_BREAK

    def test_one_counter_raid_is_not_stored_as_many(self):
        """THE STATE-LEVEL DEFECT, in the exact shape `ingest` describes: a
        counter-raid held across scans was appended once per sighting, so
        anything reading `events` saw the market do it again and again.

        The 15m counter-raid below is ONE bucket observed on six 1m scans."""
        def raid(n, tf, direction, bar):
            return {"occurrence_id": f"LIQUIDITY_SWEEP:{CID}:{tf}:scan{n}",
                    "event_type": CI.LIQUIDITY_SWEEP, "contract": CID,
                    "source_tf": tf, "sweep_direction": direction,
                    "swept_level": 29100.0 if direction == "below_low" else 29500.0,
                    "source_bar_time": bar,
                    "event_time": f"2026-08-25T14:{n:02d}:00+00:00",
                    "observed_at": f"2026-08-25T14:{n:02d}:00+00:00"}

        origin = raid(0, "1m", "below_low", "2026-08-25T14:00:00+00:00")
        counters = [raid(n, "15m", "above_high", "2026-08-25T14:15:00+00:00")
                    for n in range(15, 21)]

        v1 = ActivePath()
        v1.ingest([origin] + counters)
        v2 = ActivePath(causal_identity_version=V2)
        v2.ingest([dict(origin)] + [dict(c) for c in counters])

        stored = [e for e in v1.events if e["source_tf"] == "15m"]
        assert len(stored) == 6, "v1 must still store one row per observation"
        assert len([e for e in v2.events if e["source_tf"] == "15m"]) == 1

        # Both still SEE the counter-evidence -- v2 removed copies, not facts.
        assert v1.forming_direction == v2.forming_direction == "bullish"
        assert all(p.transfer_evidence()["opposing_raid_rejected"]
                   for p in (v1, v2))

    def test_v1_remains_the_only_complete_reading_of_the_tape(self, real):
        """HONEST ABOUT WHAT 1A IS. With Category B refused, a v2 path holds no
        protected-swing evidence at all -- no load-bearing structure, no ladder.
        It is CAPABILITY UNDER TEST, not a second opinion about the market, and
        claiming equivalence here would be the mixed-epistemology error in
        reverse. v1 stays the production reading until 1B lands."""
        v1_path, rows, _t = replay(real, version=V1)
        v2_path, _r2, _t2 = replay(real, version=V2)
        v1_state, v2_state = v1_path.state(), v2_path.state()

        assert v1_state["owner"] == "bullish"
        assert v1_state["load_bearing_structure"] is not None

        assert v2_state["load_bearing_structure"] is None
        b_rows = [r for r in rows if r["event_type"] in CI.CATEGORY_B]
        assert len(v2_path.unidentified) == len(b_rows)

        # What v2 DOES deliver: every Category A event, each exactly once.
        a_rows = [r for r in rows if r["event_type"] in CI.CATEGORY_A]
        assert len(v2_path.events) == len({CI.causal_event_key(r) for r in a_rows})
        assert len(v2_path.events) < len(a_rows), "no duplication was collapsed"


# ══ RESTART / RECOVERY ══════════════════════════════════════════════════════
class TestRestart:

    def test_a_restart_rehydrating_from_a_v2_ledger_does_not_double_count(
            self, real, tmp_path):
        """The convergence invariant: replaying durable facts into a fresh
        process must reach the state a continuous process held."""
        led = OL.OccurrenceLedger(CID, directory=str(tmp_path),
                                  causal_identity_version=V2)
        live, rows, _tr = replay(real, version=V2)
        for r in rows:
            led.record(r)          # Category B is refused by the store itself
        restarted = ActivePath(causal_identity_version=V2)
        stored = sorted(led.occurrences(),
                        key=lambda r: (str(r.get("event_time") or ""),
                                       str(r.get("occurrence_id") or "")))
        restarted.ingest(stored)
        assert stored, "nothing durable to replay"
        assert len(stored) == len(live.events)
        assert restarted.state()["owner"] == live.state()["owner"]

    def test_recovery_provenance_is_unchanged_by_this_unit(self, real):
        """STARTUP-STATE-RECOVERY-KERNEL-1 stays non-persistent and start-time
        independent. Causal identity must not have moved it."""
        from market_state import session_recovery as SR
        early = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                           session_start="2026-08-25T13:00:00+00:00",
                           handoff="2026-08-25T14:47:00+00:00")
        late = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                          session_start="2026-08-25T13:00:00+00:00")
        assert SR.transition_provenance(early) == SR.transition_provenance(late)
        assert (early["active_path"] or {})["owner"] == "bullish"

    def test_the_kernel_still_persists_nothing(self, tmp_path, monkeypatch):
        from market_state import session_recovery as SR
        monkeypatch.setenv(OL.DIR_ENV, str(tmp_path))
        bars = [{"timestamp": f"2026-08-25T13:{i:02d}:00+00:00", "open": 29000 + i,
                 "high": 29010 + i, "low": 28990 + i, "close": 29005 + i,
                 "volume": 100} for i in range(40)]
        SR.recover(bars_1m=bars, contract_id=CID, symbol="MNQ")
        assert os.listdir(str(tmp_path)) == []


# ══ PRODUCTION INERTNESS — the load-bearing half of the split ═══════════════
class TestProductionDoesNotActivateV2:
    """CAUSAL-OCCURRENCE-IDENTITY-1 adds v2 CAPABILITY. Activating it in
    production is the NEXT unit's job, and until that unit is certified the
    production lane must behave exactly as v1."""

    def test_no_production_source_selects_v2(self):
        """STRUCTURAL: does any production CALL select a non-v1 identity?

        This searched source text until EPISTEMIC-CLOSURE-CERTIFICATION-1
        arrived and started DESCRIBING v2 in order to record that production
        does not use it. A comment is not a call, a docstring is not a call, and
        a governance contract naming a keyword is emphatically not a call --
        `keyword_call_sites` parses the AST and only reports real call sites.

        A non-literal value is NOT treated as inert: it cannot be proven v1, so
        it is surfaced for review rather than assumed harmless.
        """
        from rule_governance.epistemic_closure import authority_ast as AST
        src_root = os.path.join(ROOT, "src")
        sites = AST.keyword_call_sites(
            src_root, "causal_identity_version",
            exclude_files=[os.path.join(src_root, "market_data",
                                        "causal_identity.py")])
        selecting = [f"{s['file']}:{s['line']} {s['callee']}(...={s['value']})"
                     for s in sites
                     if not s["literal"] or s["value"] not in (None, 1)]
        assert selecting == [], selecting

    def test_the_scan_cycle_constructs_a_v1_ledger_and_a_v1_path(self):
        import inspect

        from live_scan import production_scan_cycle as PSC
        src = inspect.getsource(PSC)
        assert "causal_identity_version" not in src
        assert "CAUSAL_IDENTITY_V2" not in src

    def test_the_production_entrypoint_is_untouched_by_this_unit(self):
        with open(os.path.join(ROOT, "tools", "topstepx_production_session.py"),
                  encoding="utf-8") as fh:
            text = fh.read()
        assert "causal_identity" not in text

    def test_the_default_construction_is_v1_everywhere(self, tmp_path):
        assert ActivePath().causal_identity_version == V1
        assert OL.OccurrenceLedger(
            CID, directory=str(tmp_path)).causal_identity_version == V1

    def test_no_broker_or_provider_reaches_causal_identity(self):
        import inspect
        src = inspect.getsource(CI)
        for banned in ("requests", "topstepx", "place_order", "modify_order",
                       "http", "socket", "openai"):
            assert banned not in src.lower(), banned

    def test_the_brain_payload_gained_no_causal_field(self):
        """`ActivePath.state()` is published to the Brain. This unit adds
        provenance to OCCURRENCES, not to what the Brain is told."""
        state = ActivePath().state()
        for leaked in ("causal_event_key", "causal_identity_version",
                       "source_bar_time", "settled_edge_time", "unidentified"):
            assert leaked not in state, leaked

    def test_settled_source_is_read_by_nothing_that_decides(self):
        """STRUCTURAL: does any deciding production module READ the key?

        Same repair as the v2 check above, and the same cause: the governance
        registry names `settled_source` to record that nothing decides on it.
        `field_authority` asks the parser, and `production_files` already
        excludes governance by package location rather than by filename.

        `snapshot_builder` PRODUCES it and `active_path` reads it to build
        occurrence provenance; neither decides on it. `causal_identity` names it
        only to say where Category A provenance comes from.
        """
        from rule_governance.epistemic_closure import authority_ast as AST
        src_root = os.path.join(ROOT, "src")
        allowed = {os.path.join(src_root, "market_data", "snapshot_builder.py"),
                   os.path.join(src_root, "market_state", "active_path.py"),
                   os.path.join(src_root, "market_data", "causal_identity.py")}
        candidates = [p for p in AST.production_files(src_root)
                      if os.path.abspath(p) not in
                      {os.path.abspath(a) for a in allowed}]
        result = AST.field_authority(candidates, "settled_source")
        # NOT-PRESENT, not proven-ABSENT. Across ~600 production modules the
        # honest tri-state answer is UNKNOWN -- many of them build dicts with
        # computed keys, and no parser can rule out a dynamic read at that
        # scope. What this test CAN prove is that nothing outside the allowed
        # set NAMES the field, which is what a decision-bearing consumer would
        # have to do. Claiming more would be the overreach this framework
        # exists to refuse.
        assert result["state"] != AST.PRESENT, result["sites"]


# ══ V1 BEHAVIOUR PRESERVATION ═══════════════════════════════════════════════
class TestV1IsPreserved:

    def test_occurrence_ids_are_bit_identical_to_the_shipped_scheme(self, observed):
        from market_state.active_path import occurrence_id
        for r in observed:
            if r["event_type"] == CI.LIQUIDITY_SWEEP:
                assert r["occurrence_id"] == occurrence_id(
                    CID, CI.LIQUIDITY_SWEEP, r["source_tf"], r["event_time"],
                    r["sweep_direction"])
            elif r["event_type"] == CI.STRUCTURE_BREAK:
                assert r["occurrence_id"] == occurrence_id(
                    CID, CI.STRUCTURE_BREAK, r["source_tf"], r["event_time"],
                    f"{r['direction']}@{r['broken_level']}")

    def test_event_time_is_still_the_scan(self, observed):
        for r in observed:
            assert r["event_time"] == r["observed_at"]

    def test_the_real_ledger_shape_still_loads(self):
        """The live store on disk must remain readable as exactly what it is."""
        directory = os.path.join(ROOT, "data", "occurrence_ledger")
        if not os.path.exists(os.path.join(directory, f"{CID}.json")):
            pytest.skip("no live store present")
        led = OL.OccurrenceLedger(CID, directory=directory)
        assert led.health()["status"] == OL.HEALTHY
        assert led.causal_identity_version == V1
        assert len(led.occurrences()) > 0
