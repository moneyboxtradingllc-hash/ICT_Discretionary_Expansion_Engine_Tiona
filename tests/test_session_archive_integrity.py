"""Integrity locks for session-replay archives (PROD-20260806 and successors).

The archive itself is git-ignored -- it holds raw runtime and account-derived
evidence. These tests skip cleanly when it is absent, so a fresh clone stays
green, and enforce the contract whenever an archive IS present locally.

The committed index is always checked: it must never carry a secret.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

ROOT = os.path.join("data", "replay_sessions", "PROD-20260806")
DOC = os.path.join("docs", "production", "sessions",
                   "PROD-20260806_SESSION_ARCHIVE.md")
present = pytest.mark.skipif(not os.path.isdir(ROOT),
                             reason="session archive is git-ignored; not present here")


def read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def load(rel):
    return json.loads(read(rel))


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ══════════════════════════════════════════════════════════════════════════════
@present
class TestManifest:

    REQUIRED = ("archive_schema_version", "session_id", "session_date", "timezone",
                "instrument", "active_contract", "account_role", "production_window",
                "phases", "repairs", "final_account_reconciliation",
                "artifact_counts_by_category", "file_count", "archive_created_utc",
                "archive_tool", "known_omissions")

    def test_every_required_field_exists(self):
        m = load("manifest.json")
        assert not [k for k in self.REQUIRED if k not in m]

    def test_session_identity_is_consistent(self):
        m = load("manifest.json")
        assert m["session_id"] == "PROD-20260806"
        assert m["session_date"] == "2026-08-06"
        assert m["instrument"] == "MNQ"
        assert m["active_contract"] == "CON.F.US.MNQ.U26"

    def test_timestamps_parse(self):
        from datetime import datetime
        m = load("manifest.json")
        datetime.fromisoformat(m["archive_created_utc"])
        for p in m["phases"]:
            datetime.fromisoformat(p["start_et"])
            datetime.fromisoformat(p["end_et"])

    def test_every_phase_maps_to_a_commit(self):
        m = load("manifest.json")
        phases = {p["phase"]: p["commit"] for p in m["phases"]}
        assert set(phases) == {"A", "B", "C"}
        assert all(re.fullmatch(r"[0-9a-f]{7,40}", c) for c in phases.values())

    def test_known_omissions_are_declared(self):
        assert load("manifest.json")["known_omissions"]


@present
class TestIntegrity:

    def test_every_hash_verifies(self):
        bad = []
        for line in read("SHA256SUMS.txt").splitlines():
            if not line.strip():
                continue
            want, rel = line.split("  ", 1)
            p = os.path.join(ROOT, rel)
            if not os.path.exists(p) or sha(p) != want:
                bad.append(rel)
        assert not bad, bad[:5]

    def test_the_checksum_file_does_not_hash_itself(self):
        assert "SHA256SUMS.txt" not in read("SHA256SUMS.txt")

    def test_entries_are_sorted_and_unique(self):
        rels = [l.split("  ", 1)[1] for l in read("SHA256SUMS.txt").splitlines() if l.strip()]
        assert rels == sorted(rels)
        assert len(rels) == len(set(rels))

    def test_the_manifest_file_count_matches(self):
        rels = [l for l in read("SHA256SUMS.txt").splitlines() if l.strip()]
        assert load("manifest.json")["file_count"] == len(rels)


@present
class TestCensusConsistency:

    def test_census_total_matches_artifact_counts(self):
        c = load("analysis/scan_census.json")
        assert c["total_scans"] == load("brain/artifact_index.json")["count"]
        assert c["total_scans"] == load("scans/scan_index.json")["count"]

    def test_phase_totals_sum_to_the_whole(self):
        c = load("analysis/scan_census.json")
        assert c["before_repair"]["scans"] + c["after_repair"]["scans"] == c["total_scans"]

    def test_archived_scan_inputs_match_the_index(self):
        n = len(glob.glob(os.path.join(ROOT, "scans", "inputs", "*.json")))
        assert n == load("scans/scan_index.json")["count"]

    def test_the_census_disclaims_performance(self):
        assert "not" in load("analysis/scan_census.json")["note"].lower()


@present
class TestHistoricalTruthPreserved:
    """The archive must not improve history."""

    def test_the_malformed_raws_still_do_not_parse(self):
        bad = 0
        for p in glob.glob(os.path.join(ROOT, "brain", "raw_responses", "*.raw.txt")):
            try:
                json.loads(open(p, encoding="utf-8").read())
            except json.JSONDecodeError:
                bad += 1
        assert bad == 2, f"expected the 2 observed malformed responses, got {bad}"

    def test_the_degraded_artifacts_are_archived_as_degraded(self):
        n = len(glob.glob(os.path.join(ROOT, "brain", "degraded_outputs", "*.json")))
        assert n >= 5      # 3 schema degradations + 2 llm_failed_fallback

    def test_non_session_test_artifacts_are_excluded_and_explained(self):
        e = load("scans/EXCLUDED_non_session_artifacts.json")
        assert e["count"] > 0 and "TEST SUITE" in e["note"]


@present
class TestZeroStateIsExplicit:

    def test_session_zero_state_is_recorded(self):
        z = load("execution/session_zero_state.json")
        for k in ("candidates", "execution_tokens", "entry_attempts",
                  "orders_submitted", "fills", "round_trips"):
            assert z[k] == 0

    def test_absence_is_distinguishable_from_missing_files(self):
        for comp in ("candidate_state", "token_state", "order_state", "fill_state",
                     "execution_context", "mission_state", "slippage_state"):
            z = load(f"execution/{comp}/ZERO_STATE.json")
            assert z["explicit_zero"] is True and z["records"] == 0


@present
class TestArchiveCarriesNoSecrets:

    def test_no_credential_value_appears_anywhere(self):
        from dotenv import load_dotenv
        load_dotenv(".env")
        secrets = [os.getenv(k) for k in
                   ("TOPSTEPX_API_KEY", "TOPSTEPX_USERNAME", "TOPSTEPX_ACCOUNT_ID",
                    "TOPSTEPX_ACCOUNT_FINGERPRINT", "OPENAI_API_KEY")]
        secrets = [s for s in secrets if s]
        hits = []
        for root, _, files in os.walk(ROOT):
            for f in files:
                p = os.path.join(root, f)
                try:
                    txt = open(p, encoding="utf-8", errors="ignore").read()
                except Exception:  # noqa: BLE001
                    continue
                hits += [os.path.relpath(p, ROOT) for s in secrets if s in txt]
        assert not hits, hits[:5]

    def test_the_archived_authorization_is_redacted(self):
        a = load("execution/authorization_redacted.json")
        assert "REDACTED" in a["account_fingerprint"]
        assert "REDACTED" in a["authorization_fingerprint"]


class TestCommittedIndexIsSafe:
    """Always runs -- the committed document must be safe in every clone."""

    def test_the_index_exists(self):
        assert os.path.exists(DOC)

    def test_it_carries_no_credential_value(self):
        from dotenv import load_dotenv
        load_dotenv(".env")
        txt = open(DOC, encoding="utf-8").read()
        for k in ("TOPSTEPX_API_KEY", "TOPSTEPX_USERNAME", "TOPSTEPX_ACCOUNT_ID",
                  "TOPSTEPX_ACCOUNT_FINGERPRINT", "OPENAI_API_KEY"):
            v = os.getenv(k)
            if v:
                assert v not in txt, k

    def test_it_carries_no_jwt_or_full_fingerprint(self):
        txt = open(DOC, encoding="utf-8").read()
        assert not re.search(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.", txt)
        assert not re.search(r"\bacct:[0-9a-f]{12}\b", txt)
        assert not re.search(r"\bauth:[0-9a-f]{16}\b", txt)

    def test_it_states_the_zero_trade_outcome(self):
        txt = open(DOC, encoding="utf-8").read()
        assert "No candidate, no token, no attempt, no order, no fill" in txt

    def test_it_does_not_claim_profitability(self):
        # Whitespace-normalised: markdown line wrapping must not break a
        # content assertion about what the document claims.
        txt = " ".join(open(DOC, encoding="utf-8").read().lower().split())
        assert "proves nothing about profitability" in txt

    def test_it_declares_the_replay_automation_status(self):
        assert "ARCHIVED_NOT_YET_AUTOMATED" in open(DOC, encoding="utf-8").read()
