"""DECISION-ACCOUNTING-HELD-1 — a suppressed scan is not a stand-down.

PROD-20260922 was the first session in which ENFORCE ever suppressed a Brain
call. 38 scans held. All 38 fell to UNCLASSIFIED because `brain_sleep_hold`
did not exist in `_REASON_TO_DISPOSITION`, and 4 daily-loss-governor refusals
fell the same way. `reconcile` then reported

    CANDIDATE_DECISION_ACCOUNTING_FAILURE   (42 unclassified of 593)

for a session that had truthfully recorded a reason for every single scan.
That is the same failure mode 636c978 repaired for `action_declines_entry`,
and it only surfaced now because holds had never happened before.

THE DISTINCTION THIS FILE PROTECTS. `STOOD_DOWN` means the organism looked at
the market and declined. `HELD` means it never looked, because the wake
controller proved no material semantic change. Merging them would make the
ledger say the Brain rejected 581 setups on a day it actually rejected 543 and
was never asked about 38.

The governor keeps the same discipline one level down: `BUDGET_EXHAUSTED` is a
refusal on PROVEN truth, `GOVERNOR_UNPROVEN` is a refusal because truth could
not be established. Rendering those identically would lose the only signal
that says go and look at the venue.

ACCOUNTING ONLY. Nothing here decides eligibility, sizing or execution.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.candidate_decision_record import (  # noqa: E402
    BUDGET_EXHAUSTED, CANDIDATE_CREATED, GOVERNOR_UNPROVEN, HELD,
    STOOD_DOWN, TERMINAL_DISPOSITIONS, UNCLASSIFIED, build_record, reconcile,
    terminal_disposition,
)
from broker import daily_loss_budget as DLB                        # noqa: E402


class TestTheSuppressedScan:
    """1. brain_sleep_hold -> HELD."""

    def test_a_suppressed_scan_is_held(self):
        assert terminal_disposition("brain_sleep_hold") == HELD

    def test_it_is_deliberately_not_a_stand_down(self):
        """The Brain did not evaluate that scan. It cannot have declined."""
        assert terminal_disposition("brain_sleep_hold") != STOOD_DOWN

    def test_held_is_a_countable_terminal_disposition(self):
        assert HELD in TERMINAL_DISPOSITIONS

    def test_a_created_candidate_still_wins_over_the_reason(self):
        assert terminal_disposition("brain_sleep_hold",
                                    created=True) == CANDIDATE_CREATED


class TestTheStandDownsAreUnchanged:
    """2. Everything that was a stand-down stays one."""

    @pytest.mark.parametrize("reason", [
        "action_declines_entry",
        "session_phase_blocks_entry",
        "stand_down",
    ])
    def test_existing_stand_downs_are_untouched(self, reason):
        assert terminal_disposition(reason) == STOOD_DOWN


class TestTheGovernorRefusals:
    """3. order_discovery_incomplete maps explicitly, and is neither a hold
    nor a stand-down: the governor refused, the Brain was not consulted, and
    the market was not judged."""

    def test_incomplete_discovery_is_explicitly_classified(self):
        assert terminal_disposition(
            DLB.DISCOVERY_INCOMPLETE) == GOVERNOR_UNPROVEN

    def test_incomplete_discovery_is_not_held_and_not_stood_down(self):
        got = terminal_disposition(DLB.DISCOVERY_INCOMPLETE)
        assert got != HELD
        assert got != STOOD_DOWN
        assert got != UNCLASSIFIED

    def test_the_live_path_passes_the_state_not_the_reason(self):
        """`_record_decision` is handed `budget["state"]`. The granular reason
        travels in `detail`, so BOTH vocabularies must classify."""
        assert terminal_disposition(DLB.UNKNOWN) == GOVERNOR_UNPROVEN
        assert terminal_disposition(DLB.CONTAMINATED) == GOVERNOR_UNPROVEN
        assert terminal_disposition(DLB.EXHAUSTED) == BUDGET_EXHAUSTED

    @pytest.mark.parametrize("reason", [
        "venue_truth_unavailable",
        "unattributable_in_session_trade",
        "authorization_carries_no_daily_loss_budget",
        "daily_loss_budget_is_not_a_positive_number",
    ])
    def test_every_unprovable_governor_reason_is_unproven_not_exhausted(
            self, reason):
        assert terminal_disposition(reason) == GOVERNOR_UNPROVEN

    def test_a_spent_budget_is_exhaustion_not_uncertainty(self):
        """Proven `no` and unprovable `cannot tell` are different answers."""
        assert terminal_disposition(DLB.ROOM_SPENT) == BUDGET_EXHAUSTED
        assert terminal_disposition(DLB.ROOM_SPENT) != GOVERNOR_UNPROVEN

    def test_a_permitted_budget_never_reaches_the_classifier(self):
        """`resolve` records nothing when entry is permitted, so OK has no
        disposition and must not acquire one by accident."""
        assert terminal_disposition(DLB.OK) == UNCLASSIFIED


class TestRealHolesStillShow:
    """4. Mapping these reasons may not silence the ones that remain."""

    @pytest.mark.parametrize("reason", [
        "tool_not_detected", "derived_state_stale", "objective_ambiguous",
        "candle_gap_unrecovered", "execution_price_unavailable",
        "tool_occurrence_ambiguous", "hybrid_envelope_unauthorized",
    ])
    def test_genuinely_unmapped_reasons_stay_unclassified(self, reason):
        assert terminal_disposition(reason) == UNCLASSIFIED

    def test_an_absent_or_nonsense_reason_stays_unclassified(self):
        assert terminal_disposition("") == UNCLASSIFIED
        assert terminal_disposition(None) == UNCLASSIFIED
        assert terminal_disposition("no_such_reason_exists") == UNCLASSIFIED

    def test_the_governor_states_are_matched_exactly_not_loosely(self):
        """The governor's states are upper case and the producer's reasons are
        lower case. A near miss must not inherit a governor classification."""
        for near in ("unknown", "Unknown", "exhausted", "contaminated",
                     "UNKNOWN_STATE", "EXHAUSTED_BUDGET"):
            assert terminal_disposition(near) == UNCLASSIFIED


class TestReconciliation:
    """5. A truthfully classified session reconciles; an untruthful one does
    not."""

    def _rows(self, n, reason):
        return [build_record(session_id="S", scan_id=f"s{i}", timestamp_et="t",
                             instrument="MNQ", contract="C", parsed={},
                             trace={},
                             disposition=terminal_disposition(reason),
                             rejection_reason=reason, detail="d")
                for i in range(n)]

    def test_the_prod_20260922_shape_now_reconciles(self):
        """THE REGRESSION. These are the real counts from the session that
        raised the false alarm: 543 stand-downs, 38 holds, 4 governor
        refusals, 8 candidates."""
        rows = (self._rows(543, "session_phase_blocks_entry")
                + self._rows(38, "brain_sleep_hold")
                + self._rows(4, DLB.UNKNOWN)
                + [build_record(session_id="S", scan_id=f"c{i}",
                                timestamp_et="t", instrument="MNQ",
                                contract="C", parsed={}, trace={},
                                disposition=CANDIDATE_CREATED,
                                rejection_reason=None, detail="")
                   for i in range(8)])

        out = reconcile(rows)

        assert out["status"] == "RECONCILED"
        assert out["unclassified"] == 0
        assert out["terra_proposals"] == 593
        assert out["disposition_total"] == 593
        assert out["dispositions"] == {
            CANDIDATE_CREATED: 8,
            GOVERNOR_UNPROVEN: 4,
            HELD: 38,
            STOOD_DOWN: 543,
        }

    def test_holds_are_counted_separately_from_stand_downs(self):
        out = reconcile(self._rows(10, "session_phase_blocks_entry")
                        + self._rows(7, "brain_sleep_hold"))
        assert out["dispositions"] == {STOOD_DOWN: 10, HELD: 7}

    def test_one_unmapped_reason_still_fails_the_reconciliation(self):
        """The guard must keep firing. Repairing these reasons may not buy
        silence for the twelve that still have no ruling."""
        out = reconcile(self._rows(38, "brain_sleep_hold")
                        + self._rows(1, "tool_not_detected"))
        assert out["status"] == "CANDIDATE_DECISION_ACCOUNTING_FAILURE"
        assert out["unclassified"] == 1
