"""The catalogs churn measurement must be trustworthy before it is believed.

A measurement tool that miscategorises is worse than no measurement: it would
send the owner to fix the wrong thing. These tests build archives whose cause
of change is known by construction, then assert the audit names that cause.

Two of the candidate causes are asserted to be IMPOSSIBLE rather than merely
absent, because `_catalog_view` sorts rows and picks only named keys.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from catalogs_churn_audit import audit                              # noqa: E402

OBJ = {"objective_id": "OBJ_1", "type": "liquidity", "price": 30900.0,
       "side": "sell", "valid": True}
INV = {"invalidation_id": "INV_PH_1m_1", "type": "protected_high",
       "price": 30957.75, "timeframe": "1m"}
TOOL = {"tool_id": "FVG_1", "occurrence_id": "OCC_1", "tool_family": "fvg",
        "direction": "bearish", "zone_low": 30950.0, "zone_high": 30960.0,
        "validation_timestamp": "2026-09-22T17:30:00+00:00"}


def write(tmp_path, scans) -> list:
    """One archived brain call per scan, in time order."""
    paths = []
    for index, (tools, objectives, invalidations) in enumerate(scans):
        path = os.path.join(str(tmp_path), f"20260922_{index:04d}00_MNQ.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"input_payload": {
                "authorized_tool_catalog": tools,
                "authorized_objectives": objectives,
                "authorized_invalidations": invalidations}}, fh)
        paths.append(path)
    return sorted(paths)


class TestNoChangeIsReportedAsNoChange:

    def test_two_identical_scans_report_nothing(self, tmp_path):
        paths = write(tmp_path, [([TOOL], [OBJ], [INV])] * 2)
        out = audit(paths)
        assert out["pairs"] == 1
        assert out["catalogs_changed"] == 0
        assert out["unchanged"] == 1
        assert not out["fields"]


class TestTheImpossibleCauses:
    """Ordering and serialization churn cannot reach the fingerprint."""

    def test_reordering_the_rows_is_not_a_change(self, tmp_path):
        second = dict(OBJ, objective_id="OBJ_2", price=30880.0)
        paths = write(tmp_path, [
            ([TOOL], [OBJ, second], [INV]),
            ([TOOL], [second, OBJ], [INV]),   # same set, reversed
        ])
        out = audit(paths)
        assert out["catalogs_changed"] == 0, (
            "_catalog_view sorts rows; order cannot move the fingerprint")

    def test_a_field_outside_the_key_tuple_is_not_a_change(self, tmp_path):
        paths = write(tmp_path, [
            ([TOOL], [OBJ], [INV]),
            ([TOOL], [dict(OBJ, some_unpicked_diagnostic="moved")], [INV]),
        ])
        out = audit(paths)
        assert out["catalogs_changed"] == 0, (
            "_pick keeps only named keys; anything else is invisible")


class TestGenuineSemanticChange:

    def test_an_added_objective_is_membership(self, tmp_path):
        paths = write(tmp_path, [
            ([TOOL], [OBJ], [INV]),
            ([TOOL], [OBJ, dict(OBJ, objective_id="OBJ_2")], [INV]),
        ])
        out = audit(paths)
        assert out["catalogs_changed"] == 1
        assert out["membership"]["objectives"] == 1
        assert out["members_added"]["objectives"] == 1
        assert out["members_removed"]["objectives"] == 0

    def test_a_removed_invalidation_is_membership(self, tmp_path):
        paths = write(tmp_path, [([TOOL], [OBJ], [INV]),
                                 ([TOOL], [OBJ], [])])
        out = audit(paths)
        assert out["membership"]["invalidations"] == 1
        assert out["members_removed"]["invalidations"] == 1

    def test_a_moved_price_is_named_as_price(self, tmp_path):
        paths = write(tmp_path, [
            ([TOOL], [OBJ], [INV]),
            ([TOOL], [dict(OBJ, price=30901.25)], [INV]),
        ])
        out = audit(paths)
        assert out["fields"]["objectives.price"] == 1
        assert out["value_movement"]["objectives"] == 1
        assert out["membership"]["objectives"] == 0
        assert not out["float_only"]["objectives.price"]


class TestRepresentationChurn:
    """The hypothesis worth testing: a restamped field is not a new fact."""

    def test_a_restamped_tool_timestamp_is_named(self, tmp_path):
        paths = write(tmp_path, [
            ([TOOL], [OBJ], [INV]),
            ([dict(TOOL, validation_timestamp="2026-09-22T17:31:00+00:00")],
             [OBJ], [INV]),
        ])
        out = audit(paths)
        assert out["fields"]["tools.validation_timestamp"] == 1
        assert out["membership"]["tools"] == 0, (
            "the same tool is still offered; only its stamp moved")

    def test_a_float_representation_change_is_flagged_as_such(self, tmp_path):
        paths = write(tmp_path, [
            ([TOOL], [dict(OBJ, price=30900.0)], [INV]),
            ([TOOL], [dict(OBJ, price=30900)], [INV]),   # 30900.0 == 30900
        ])
        out = audit(paths)
        assert out["fields"]["objectives.price"] == 1
        assert out["float_only"]["objectives.price"] == 1, (
            "same number, different representation, and the audit must say so")


class TestTheAuditIsHonestAboutItself:

    def test_an_unreadable_archive_row_is_counted_not_skipped(self, tmp_path):
        paths = write(tmp_path, [([TOOL], [OBJ], [INV])] * 2)
        broken = os.path.join(str(tmp_path), "20260922_999900_MNQ.json")
        with open(broken, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        out = audit(sorted(paths + [broken]))
        assert out["unreadable"] == 1

    def test_a_single_scan_yields_no_pairs(self, tmp_path):
        out = audit(write(tmp_path, [([TOOL], [OBJ], [INV])]))
        assert out["pairs"] == 0
        assert out["catalogs_changed"] == 0

    def test_examples_are_captured_for_the_operator(self, tmp_path):
        paths = write(tmp_path, [
            ([TOOL], [OBJ], [INV]),
            ([TOOL], [dict(OBJ, price=30905.0)], [INV]),
        ])
        out = audit(paths)
        assert out["examples"]["objectives.price"], (
            "a count without an example cannot be acted on")
