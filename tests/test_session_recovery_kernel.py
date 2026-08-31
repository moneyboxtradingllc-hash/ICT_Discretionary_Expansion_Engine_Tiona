"""STARTUP-STATE-RECOVERY-KERNEL-1 — process start time stops being a variable.

THE DEFECT THIS ANSWERS. On 2026-08-25 production launched at 10:31 ET. Active
Path began cold, and six protected-swing transitions that a continuously running
process would have held simply never existed — their causal evidence predated
the process. `registered_at` was therefore unusable as identity provenance, not
because mechanics assigned it inconsistently, but because whether the transition
existed at all depended on process uptime.

The kernel replays the canonical tape from a fixed origin, so the answer no
longer depends on when we started looking.

NON-AUTHORITATIVE: it persists nothing, writes no occurrence, and holds no
ledger. No broker. No provider. No network.
"""
from __future__ import annotations

import glob
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from market_state import session_recovery as SR                      # noqa: E402

CID = "CON.F.US.MNQ.U26"
SESSION = "2026-08-25T13:00:00+00:00"          # 09:00 ET
ARCHIVE = os.path.join(ROOT, "data", "ai_brain")


def tape(day="20260825"):
    """The real 1m tape this session witnessed, deduped and ordered."""
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


def synthetic(n=60, start=29000.0):
    """A deterministic tape. Shape is irrelevant; determinism is the subject."""
    bars = []
    for i in range(n):
        px = start + (i % 7) * 2.5 - (i % 3) * 1.25
        bars.append({"timestamp": f"2026-08-25T13:{i:02d}:00+00:00",
                     "open": px, "high": px + 3.0, "low": px - 3.0,
                     "close": px + 0.5, "volume": 100 + i})
    return bars


@pytest.fixture(scope="module")
def real():
    bars = tape()
    if len(bars) < SR.MIN_BARS:
        pytest.skip("archived 1m tape absent")
    return bars


# ══ THE INVARIANT ═══════════════════════════════════════════════════════════
class TestStartTimeIsNotAVariable:

    def test_recovery_reproduces_the_live_active_path(self, real):
        """Live production held owner=bullish, 1m-only, ladder of 2. Fidelity
        means reproducing CURRENT mechanics, not a nicer answer."""
        r = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                       session_start=SESSION)
        ap = r["active_path"] or {}
        prog = ap.get("progression") or {}
        assert r["sufficient"] and not r["error"]
        assert ap["owner"] == "bullish" and ap["status"] == "active"
        assert prog["highest_confirmed"] == "1m"
        assert len(prog["favourable_ladder"] or []) == 2

    @pytest.mark.parametrize("min_bars", [20, 25, 30, 35, 40])
    def test_state_is_stable_against_the_evidence_floor(self, real, min_bars):
        r = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                       session_start=SESSION, min_bars=min_bars)
        ap = r["active_path"] or {}
        assert ap["owner"] == "bullish"
        assert (ap.get("progression") or {})["highest_confirmed"] == "1m"

    def test_handoff_state_accumulates_monotonically(self, real):
        """Recovery to an earlier handoff must be a PREFIX of a later one --
        never a differently-derived history."""
        seen = []
        for h in ("13:31", "14:00", "14:15", "14:31", "14:47"):
            r = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                           session_start=SESSION,
                           handoff=f"2026-08-25T{h}:00+00:00")
            seen.append(set(SR.transition_provenance(r)))
        for earlier, later in zip(seen, seen[1:]):
            assert earlier <= later, "an earlier handoff held a transition the later one lost"

    def test_a_later_start_does_not_change_the_answer(self, real):
        """The 2026-08-25 defect in one assertion: two processes 'starting' at
        different times reconstruct the same causal state."""
        early = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                           session_start=SESSION,
                           handoff="2026-08-25T14:47:00+00:00")
        late = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                          session_start=SESSION)
        assert SR.transition_provenance(early) == SR.transition_provenance(late)
        assert (early["active_path"] or {})["owner"] == \
            (late["active_path"] or {})["owner"]


# ══ CATEGORY B PROVENANCE ═══════════════════════════════════════════════════
class TestTransitionProvenance:

    def test_registered_at_is_identical_at_every_handoff(self, real):
        ref = SR.transition_provenance(
            SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                       session_start=SESSION))
        for h in ("13:31", "14:00", "14:15", "14:31"):
            r = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                           session_start=SESSION,
                           handoff=f"2026-08-25T{h}:00+00:00")
            for key in SR.transition_provenance(r):
                assert key in ref, f"{key} not present in the continuous run"

    def test_the_six_lost_transitions_are_recovered(self, real):
        """These registered before 10:31 ET and were absent from the live
        session entirely."""
        ref = SR.transition_provenance(
            SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                       session_start=SESSION))
        registered = {(k[2], k[3]) for k in ref
                      if k[0] == "PROTECTED_SWING_REGISTERED"}
        for swing_id in ("1m:swing_high:29341.2", "1m:swing_low:29279.2",
                         "1m:swing_high:29416"):
            assert any(s == swing_id for s, _ in registered), swing_id

    def test_swing_id_alone_is_not_identity(self):
        """`tf:side:price` can recur. Provenance must pair it with formation
        time or two lives of one price collapse into one."""
        a = ("PROTECTED_SWING_REGISTERED", "1m", "1m:swing_low:29145.5", "T1")
        b = ("PROTECTED_SWING_REGISTERED", "1m", "1m:swing_low:29145.5", "T2")
        assert a != b
        assert a[2] == b[2], "the swing_id itself is genuinely identical"

    def test_warmup_observations_are_tagged_not_owned(self, real):
        late_session = "2026-08-25T14:00:00+00:00"
        r = SR.recover(bars_1m=real, contract_id=CID, symbol="MNQ",
                       session_start=late_session)
        obs = r["observations"]
        assert any(not o["in_session"] for o in obs), "no warmup was tagged"
        assert any(o["in_session"] for o in obs), "nothing was owned"
        for o in obs:
            assert o["in_session"] == (o["observed_at"] >= late_session)


# ══ NON-AUTHORITATIVE ═══════════════════════════════════════════════════════
class TestTheKernelHasNoAuthority:

    def test_it_persists_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OCCURRENCE_LEDGER_DIR", str(tmp_path))
        SR.recover(bars_1m=synthetic(), contract_id=CID, symbol="MNQ")
        assert os.listdir(str(tmp_path)) == [], "recovery wrote durable evidence"

    def test_it_holds_no_ledger_and_calls_no_provider(self):
        import inspect
        src = inspect.getsource(SR)
        for banned in ("OccurrenceLedger", "run_narrative_brain", "modify_order",
                       "place_order", "submit", "apply_break_even"):
            assert banned not in src, banned

    def test_no_executable_price_is_fabricated(self):
        import inspect
        src = inspect.getsource(SR.recover)
        assert "execution_price=None" in src

    def test_no_production_module_calls_the_kernel_yet(self):
        """STRUCTURAL: does production IMPORT the kernel?

        This used to search `src/` for the substring "session_recovery", which
        was fine until something in `src/` described the kernel rather than
        using it. `rule_governance.epistemic_closure` now does exactly that --
        it registers a fact contract stating the kernel holds NO production
        authority -- and a substring scan cannot tell a declaration from a
        dependency. An `import` statement can.
        """
        from rule_governance.epistemic_closure import authority_ast as AST
        src_root = os.path.join(ROOT, "src")
        hits = AST.imports_module(
            src_root, "session_recovery",
            exclude_files=[os.path.join(src_root, "market_state",
                                        "session_recovery.py")])
        assert hits == [], hits


# ══ ROBUSTNESS ══════════════════════════════════════════════════════════════
class TestRobustness:

    def test_too_little_history_refuses_rather_than_guesses(self):
        r = SR.recover(bars_1m=synthetic(5), contract_id=CID)
        assert not r["sufficient"] and "required" in (r["error"] or "")
        assert r["active_path"] is None

    def test_an_empty_tape_is_refused(self):
        r = SR.recover(bars_1m=[], contract_id=CID)
        assert not r["sufficient"]

    def test_unordered_bars_are_ordered_not_trusted(self):
        bars = synthetic()
        shuffled = bars[30:] + bars[:30]
        a = SR.recover(bars_1m=bars, contract_id=CID, symbol="MNQ")
        b = SR.recover(bars_1m=shuffled, contract_id=CID, symbol="MNQ")
        assert a["snapshots"] == b["snapshots"]
        assert a["last_snapshot_time"] == b["last_snapshot_time"]

    def test_it_never_raises_on_malformed_bars(self):
        junk = synthetic(30) + [{"timestamp": "2026-08-25T14:00:00+00:00"}]
        r = SR.recover(bars_1m=junk, contract_id=CID, symbol="MNQ")
        assert isinstance(r, dict) and r["schema"] == SR.SCHEMA

    def test_a_deterministic_tape_gives_a_deterministic_answer(self):
        bars = synthetic()
        a = SR.recover(bars_1m=bars, contract_id=CID, symbol="MNQ")
        b = SR.recover(bars_1m=bars, contract_id=CID, symbol="MNQ")
        assert SR.transition_provenance(a) == SR.transition_provenance(b)
        assert (a["active_path"] or {}) == (b["active_path"] or {})


# ══ INDEPENDENT SESSION ═════════════════════════════════════════════════════
class TestIndependentSession:

    def test_an_independent_day_also_reconstructs(self):
        bars = tape("20260824")
        if len(bars) < SR.MIN_BARS:
            pytest.skip("independent archive absent")
        r = SR.recover(bars_1m=bars, contract_id=CID, symbol="MNQ",
                       session_start="2026-08-24T13:00:00+00:00")
        assert r["sufficient"] and not r["error"]
        assert r["snapshots"] > 0

    def test_the_independent_day_is_also_handoff_monotonic(self):
        bars = tape("20260824")
        if len(bars) < SR.MIN_BARS + 20:
            pytest.skip("independent archive absent")
        mid = str(bars[len(bars) // 2]["timestamp"])
        early = SR.recover(bars_1m=bars, contract_id=CID, symbol="MNQ",
                           handoff=mid)
        full = SR.recover(bars_1m=bars, contract_id=CID, symbol="MNQ")
        assert set(SR.transition_provenance(early)) <= \
            set(SR.transition_provenance(full))
