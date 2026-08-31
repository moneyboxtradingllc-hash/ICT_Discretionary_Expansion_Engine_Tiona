"""RAW-SNAPSHOT-ARCHIVE (2026-08-07). Observational only.

Two authors read two different objects. The external Brain reads `brain_input`;
the deterministic author reads the raw snapshot. Only the first was ever
archived, so no session on disk can replay both authors over the same moment:
PROD-20260807 has canonical objects but no raw snapshot, and the QQQ-era
snapshots have the raw snapshot but predate canonical objects.

Archiving the snapshot fixes that going forward. It must stay purely
observational -- market truth only, never account truth, and never able to
break a scan.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain.narrative_brain import _ACCOUNT_BLOCKS, _archivable_snapshot  # noqa: E402


class TestArchivableSnapshot:

    def test_market_truth_survives(self):
        snap = {"market": {"current_price": 29700.0},
                "liquidity": {"nearest_buy_side": 29850.0},
                "protected_swings": {"protected_high": None},
                "delivery": {"state": "bearish_delivery"},
                "narrative_authority": {"narrative_direction": "bearish"}}
        out = _archivable_snapshot(snap)
        assert out == snap, "market facts must be preserved exactly"

    def test_account_truth_is_stripped(self):
        """Market truth != account truth. The Brain never sees account state,
        and neither should a replay archive."""
        snap = {"market": {"current_price": 1.0}}
        snap.update({block: {"secret": "account state"} for block in _ACCOUNT_BLOCKS})
        out = _archivable_snapshot(snap)
        assert out == {"market": {"current_price": 1.0}}
        for block in _ACCOUNT_BLOCKS:
            assert block not in out, block

    def test_it_can_never_break_a_scan(self):
        """Archiving a scan may never be the reason a scan fails."""
        class Hostile(dict):
            def items(self):
                raise RuntimeError("boom")
        assert _archivable_snapshot(Hostile()) == {}
        assert _archivable_snapshot(None) == {}
        assert _archivable_snapshot("not a dict") == {}
        assert _archivable_snapshot([1, 2, 3]) == {}

    def test_it_does_not_mutate_the_snapshot(self):
        snap = {"market": {"current_price": 1.0}, "risk": {"x": 1}}
        before = dict(snap)
        _archivable_snapshot(snap)
        assert snap == before, "the archiver must not touch the live snapshot"

    def test_the_record_carries_it(self):
        """It must actually reach the persisted artifact, next to input_payload."""
        src = open(os.path.join(ROOT, "src", "ai_brain", "narrative_brain.py"),
                   encoding="utf-8").read()
        assert '"raw_snapshot": _archivable_snapshot(snapshot),' in src
        assert src.index('"input_payload"') < src.index('"raw_snapshot"')

    def test_nothing_reads_it_back(self):
        """Observational only: no decision may depend on the archive."""
        for module in ("narrative_brain.py",):
            src = open(os.path.join(ROOT, "src", "ai_brain", module),
                       encoding="utf-8").read()
            reads = [l for l in src.splitlines()
                     if 'raw_snapshot' in l and 'get("raw_snapshot")' in l]
            assert reads == [], reads
