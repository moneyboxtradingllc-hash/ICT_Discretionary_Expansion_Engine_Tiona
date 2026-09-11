"""`session_phase_blocks_entry` is a STAND-DOWN, and must count as one.

PROD-20260908. The producer raises it as `NoCandidate(..., stand_down=True)`
and it was the session's ONLY rejection reason -- 279 of 279 decisions. It was
absent from `_REASON_TO_DISPOSITION`, so every decision fell to UNCLASSIFIED
and `reconcile` reported CANDIDATE_DECISION_ACCOUNTING_FAILURE for a session
that had in fact recorded a reason for every scan.

ACCOUNTING ONLY. These tests also pin what must NOT change: the mapping is read
by `reconcile` and the decision ledger, and by nothing that decides whether a
candidate is eligible or how it is sized.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.candidate_decision_record import (CANDIDATE_CREATED,  # noqa: E402
                                              STOOD_DOWN, UNCLASSIFIED,
                                              build_record, reconcile,
                                              terminal_disposition)


class TestTheMapping:

    def test_the_session_phase_stand_down_counts_as_stood_down(self):
        assert terminal_disposition("session_phase_blocks_entry") == STOOD_DOWN

    def test_action_declines_entry_is_a_stood_down(self):
        assert terminal_disposition("action_declines_entry") == STOOD_DOWN

    def test_a_created_candidate_still_wins(self):
        """`created` is decided by the live path, never by the reason string."""
        assert terminal_disposition("session_phase_blocks_entry",
                                    created=True) == CANDIDATE_CREATED

    def test_genuinely_unmapped_reasons_stay_unclassified(self):
        """The owner asked for a BOUNDED mapping. A bulk sweep into STOOD_DOWN
        would trade one accounting error for a larger, quieter one."""
        for reason in ("tool_not_detected", "derived_state_stale",
                       "objective_ambiguous", "candle_gap_unrecovered",
                       "execution_price_unavailable"):
            assert terminal_disposition(reason) == UNCLASSIFIED

    def test_an_empty_or_unknown_reason_is_still_unclassified(self):
        assert terminal_disposition("") == UNCLASSIFIED
        assert terminal_disposition(None) == UNCLASSIFIED
        assert terminal_disposition("no_such_reason_exists") == UNCLASSIFIED


class TestReconciliation:

    def _rows(self, n, reason, disposition=UNCLASSIFIED):
        return [build_record(session_id="S", scan_id=f"s{i}", timestamp_et="t",
                             instrument="MNQ", contract="C", parsed={},
                             trace={}, disposition=disposition,
                             rejection_reason=reason, detail="d")
                for i in range(n)]

    def test_a_wholly_stood_down_session_reconciles(self):
        rows = self._rows(279, "session_phase_blocks_entry",
                          disposition=terminal_disposition(
                              "session_phase_blocks_entry"))
        out = reconcile(rows)
        assert out["status"] == "RECONCILED"
        assert out["dispositions"] == {STOOD_DOWN: 279}
        assert out["terra_proposals"] == 279
        assert out["unclassified"] == 0

    def test_one_unmapped_reason_still_fails_the_reconciliation(self):
        """The guard must keep firing for reasons that genuinely have no
        disposition -- mapping one reason may not silence the others."""
        rows = (self._rows(3, "session_phase_blocks_entry",
                           disposition=STOOD_DOWN)
                + self._rows(1, "tool_not_detected"))
        out = reconcile(rows)
        assert out["status"] == "CANDIDATE_DECISION_ACCOUNTING_FAILURE"
        assert out["unclassified"] == 1


class TestTheAuditNeverTouchesTheJournal:
    """Reclassifying evidence in place would make every later audit
    unfalsifiable. The tool must copy."""

    @pytest.fixture
    def journal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPLAY_SESSIONS_DIR", str(tmp_path))
        root = tmp_path / "PROD-T" / "memory_retrieval"
        root.mkdir(parents=True)
        rows = [build_record(session_id="PROD-T", scan_id=f"s{i}",
                             timestamp_et="t", instrument="MNQ", contract="C",
                             parsed={}, trace={}, disposition=UNCLASSIFIED,
                             rejection_reason="session_phase_blocks_entry",
                             detail="session PO3 phase REACCUMULATION")
                for i in range(5)]
        rows.append(build_record(session_id="PROD-T", scan_id="sX",
                                 timestamp_et="t", instrument="MNQ",
                                 contract="C", parsed={}, trace={},
                                 disposition=UNCLASSIFIED,
                                 rejection_reason="tool_not_detected",
                                 detail="unmapped"))
        path = root / "candidate_decisions.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return path

    def run(self, journal):
        return subprocess.run(
            [sys.executable,
             os.path.join(ROOT, "tools", "topstepx_reclassify_decision_audit.py"),
             "--session", "PROD-T"],
            capture_output=True, text=True, cwd=ROOT, env=dict(os.environ))

    def test_the_journal_is_byte_identical_afterwards(self, journal):
        before = journal.read_bytes()
        assert self.run(journal).returncode == 0
        assert journal.read_bytes() == before

    def test_the_copy_reclassifies_and_preserves_reason_and_detail(self, journal):
        assert self.run(journal).returncode == 0
        copy = journal.parent / "candidate_decisions.reclassified_PROD-T.jsonl"
        rows = [json.loads(l) for l in copy.read_text().splitlines() if l.strip()]
        assert len(rows) == 6
        stood = [r for r in rows if r["final_disposition"] == STOOD_DOWN]
        assert len(stood) == 5
        for r in stood:
            assert r["final_rejection_reason"] == "session_phase_blocks_entry"
            assert r["detail"] == "session PO3 phase REACCUMULATION"
            assert r["original_final_disposition"] == UNCLASSIFIED
        # the unmapped one is carried through, not swept
        assert [r for r in rows
                if r["final_rejection_reason"] == "tool_not_detected"
                ][0]["final_disposition"] == UNCLASSIFIED

    def test_the_total_is_preserved(self, journal):
        out = self.run(journal).stdout
        assert "TOTAL PRESERVED     : True" in out
        assert "unchanged=True" in out
